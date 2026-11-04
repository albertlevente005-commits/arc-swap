// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/*
 * ValtoDEX - tobb-poolos AMM valto az Arc halozatra (mainnet / testnet).
 * =======================================================================
 * Uniswap-elvu constant-product (x*y=k) arazas, 0,3% valtasi dijjal.
 * A dij a poolban marad, igy a likviditas-adok keresnek vele.
 *
 *  - createPool(tokenA, tokenB)                         -> uj tokenpar (csak tulajdonos, ha zart)
 *  - addLiquidity(id, aDesired, bDesired, aMin, bMin, deadline)
 *                                                       -> aranyos beteves, a felesleg nem kerul be
 *  - removeLiquidity(id, shares, aMin, bMin, deadline)  -> likviditas kivetele (SOHA nem szuneteltetheto)
 *  - getQuote(id, tokenIn, amountIn)                    -> mennyi jonne ki (ingyenes lekerdezes)
 *  - swap(id, tokenIn, amountIn, minOut, deadline)      -> tenyleges valtas
 *
 * Eles uzemi vedelmek:
 *  - reentrancy-zar minden allapotvaltoztato fuggvenyen
 *  - "safe" ERC-20 hivasok (nem szabvanyos visszateresi ertek is kezelve)
 *  - a tenylegesen beerkezett osszeggel szamolunk (balance-delta), nem a kerttel
 *  - MINIMUM_LIQUIDITY zar az elso betevesnel (share-inflacios tamadas ellen)
 *  - deadline minden tranzakcion (lejart, sokaig fuggo tx nem hajtodik vegre)
 *  - slippage-vedelem a likviditas kivetelen is
 *  - duplikalt tokenpar nem hozhato letre
 *  - tulajdonos: szuneteltetes (swap + beteves), pool-letrehozas zarasa, ketlepcsos atadas
 *
 * Arc-specifikus megjegyzes: az USDC az Arc-on nativ gaz-token is (18 tizedes),
 * de ez a szerzodes KIZAROLAG az ERC-20 interfeszen (6 tizedes) keresztul mozgat
 * USDC-t, nativ erteket (msg.value) nem fogad - lasd receive().
 *
 * Fuggetlen audit nelkul; a kod a hardhat/foundry-fuggetlen pytest csomaggal
 * (tests/) van lefedve.
 */

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract ValtoDEX {
    // ---------- Tipusok ----------

    struct Pool {
        address tokenA;
        address tokenB;
        uint256 reserveA;
        uint256 reserveB;
        uint256 totalShares;
    }

    // ---------- Allapot ----------

    Pool[] public pools;
    // poolId => likviditas-ado => jegyek
    mapping(uint256 => mapping(address => uint256)) public shares;
    // keccak(tokenA, tokenB) rendezett parra => poolId + 1 (0 = nincs)
    mapping(bytes32 => uint256) private _poolIdPlusOne;

    uint256 public constant FEE_BPS = 30;              // 0,3% valtasi dij
    uint256 public constant BPS = 10_000;
    uint256 public constant MINIMUM_LIQUIDITY = 1_000; // orokre zarolt jegyek az elso betevesnel
    address private constant LOCK_ADDRESS = address(0xdead);

    address public owner;
    address public pendingOwner;
    bool public paused;                 // swap + addLiquidity szunetel (removeLiquidity SOHA)
    bool public poolCreationRestricted; // true: csak a tulajdonos hozhat letre poolt

    uint256 private _reentrancyStatus = 1; // 1 = szabad, 2 = foglalt

    // ---------- Esemenyek ----------

    event PoolCreated(uint256 indexed id, address indexed tokenA, address indexed tokenB);
    event LiquidityAdded(uint256 indexed id, address indexed provider,
                         uint256 amountA, uint256 amountB, uint256 minted);
    event LiquidityRemoved(uint256 indexed id, address indexed provider,
                           uint256 amountA, uint256 amountB, uint256 burned);
    event Swapped(uint256 indexed id, address indexed trader,
                  address tokenIn, uint256 amountIn, uint256 amountOut);
    event Paused(address indexed by);
    event Unpaused(address indexed by);
    event PoolCreationRestrictedSet(bool restricted);
    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    // ---------- Hibak ----------

    error NotOwner();
    error NotPendingOwner();
    error ZeroAddress();
    error SameToken();
    error PoolExists();
    error PoolCreationRestricted();
    error IsPaused();
    error Reentrancy();
    error Expired();
    error ZeroAmount();
    error InsufficientLiquidityMinted();
    error InsufficientAmountA();
    error InsufficientAmountB();
    error InsufficientShares();
    error BadTokenIn();
    error EmptyPool();
    error Slippage();
    error TransferFailed();
    error NativeValueNotAccepted();
    error NoPool();

    // ---------- Modositok ----------

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier nonReentrant() {
        if (_reentrancyStatus == 2) revert Reentrancy();
        _reentrancyStatus = 2;
        _;
        _reentrancyStatus = 1;
    }

    modifier whenNotPaused() {
        if (paused) revert IsPaused();
        _;
    }

    modifier ensure(uint256 deadline) {
        if (block.timestamp > deadline) revert Expired();
        _;
    }

    // ---------- Konstruktor ----------

    /// @param initialOwner a tulajdonos (szuneteltetes, pool-letrehozas joga). Nem lehet 0.
    /// @param restrictPools true eseten csak a tulajdonos hozhat letre poolt (mainneten ajanlott).
    constructor(address initialOwner, bool restrictPools) {
        if (initialOwner == address(0)) revert ZeroAddress();
        owner = initialOwner;
        poolCreationRestricted = restrictPools;
        emit OwnershipTransferred(address(0), initialOwner);
        emit PoolCreationRestrictedSet(restrictPools);
    }

    /// Nativ USDC-t (msg.value) nem fogadunk: minden mozgas az ERC-20 interfeszen megy.
    receive() external payable {
        revert NativeValueNotAccepted();
    }

    fallback() external payable {
        revert NativeValueNotAccepted();
    }

    // ---------- Tulajdonosi muveletek ----------

    function pause() external onlyOwner {
        paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external onlyOwner {
        paused = false;
        emit Unpaused(msg.sender);
    }

    function setPoolCreationRestricted(bool restricted) external onlyOwner {
        poolCreationRestricted = restricted;
        emit PoolCreationRestrictedSet(restricted);
    }

    /// Ketlepcsos atadas: az uj tulajdonosnak el kell fogadnia (acceptOwnership).
    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        pendingOwner = newOwner;
        emit OwnershipTransferStarted(owner, newOwner);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert NotPendingOwner();
        emit OwnershipTransferred(owner, msg.sender);
        owner = msg.sender;
        pendingOwner = address(0);
    }

    // ---------- Pool letrehozas ----------

    function createPool(address tokenA, address tokenB) external returns (uint256 id) {
        if (poolCreationRestricted && msg.sender != owner) revert PoolCreationRestricted();
        if (tokenA == tokenB) revert SameToken();
        if (tokenA == address(0) || tokenB == address(0)) revert ZeroAddress();
        bytes32 key = _pairKey(tokenA, tokenB);
        if (_poolIdPlusOne[key] != 0) revert PoolExists();

        pools.push(Pool(tokenA, tokenB, 0, 0, 0));
        id = pools.length - 1;
        _poolIdPlusOne[key] = id + 1;
        emit PoolCreated(id, tokenA, tokenB);
    }

    // ---------- Likviditas ----------

    /// Aranyos beteves. Az elso betevo hatarozza meg az arat (amountADesired : amountBDesired).
    /// Kesobbi betevesnel csak annyit huzunk le, amennyi a pool aranyahoz kell; a tobbi a
    /// felhasznalonal marad. amountAMin/amountBMin: slippage-vedelem.
    function addLiquidity(
        uint256 id,
        uint256 amountADesired,
        uint256 amountBDesired,
        uint256 amountAMin,
        uint256 amountBMin,
        uint256 deadline
    )
        external nonReentrant whenNotPaused ensure(deadline)
        returns (uint256 amountA, uint256 amountB, uint256 minted)
    {
        Pool storage p = pools[id];
        if (amountADesired == 0 || amountBDesired == 0) revert ZeroAmount();

        if (p.totalShares == 0) {
            (amountA, amountB) = (amountADesired, amountBDesired);
        } else {
            uint256 amountBOptimal = amountADesired * p.reserveB / p.reserveA;
            if (amountBOptimal <= amountBDesired) {
                if (amountBOptimal < amountBMin) revert InsufficientAmountB();
                (amountA, amountB) = (amountADesired, amountBOptimal);
            } else {
                uint256 amountAOptimal = amountBDesired * p.reserveA / p.reserveB;
                // amountAOptimal <= amountADesired itt mindig teljesul
                if (amountAOptimal < amountAMin) revert InsufficientAmountA();
                (amountA, amountB) = (amountAOptimal, amountBDesired);
            }
        }
        if (amountA < amountAMin) revert InsufficientAmountA();
        if (amountB < amountBMin) revert InsufficientAmountB();

        // a TENYLEGESEN beerkezett osszegekkel szamolunk
        amountA = _pullExact(p.tokenA, amountA);
        amountB = _pullExact(p.tokenB, amountB);

        if (p.totalShares == 0) {
            uint256 liquidity = _sqrt(amountA * amountB);
            if (liquidity <= MINIMUM_LIQUIDITY) revert InsufficientLiquidityMinted();
            minted = liquidity - MINIMUM_LIQUIDITY;
            // a minimum orokre zarolva marad, igy a share ara nem manipulalhato
            shares[id][LOCK_ADDRESS] += MINIMUM_LIQUIDITY;
            p.totalShares = liquidity;
        } else {
            uint256 mintedA = amountA * p.totalShares / p.reserveA;
            uint256 mintedB = amountB * p.totalShares / p.reserveB;
            minted = mintedA < mintedB ? mintedA : mintedB;
            if (minted == 0) revert InsufficientLiquidityMinted();
            p.totalShares += minted;
        }

        p.reserveA += amountA;
        p.reserveB += amountB;
        shares[id][msg.sender] += minted;
        emit LiquidityAdded(id, msg.sender, amountA, amountB, minted);
    }

    /// Likviditas kivetele. Szandekosan NINCS whenNotPaused: a likviditas-ado
    /// mindig ki tudja venni a penzet, szunetelteteskor is.
    function removeLiquidity(
        uint256 id,
        uint256 shareAmount,
        uint256 amountAMin,
        uint256 amountBMin,
        uint256 deadline
    )
        external nonReentrant ensure(deadline)
        returns (uint256 outA, uint256 outB)
    {
        Pool storage p = pools[id];
        if (shareAmount == 0 || shareAmount > shares[id][msg.sender]) revert InsufficientShares();

        outA = shareAmount * p.reserveA / p.totalShares;
        outB = shareAmount * p.reserveB / p.totalShares;
        if (outA < amountAMin) revert InsufficientAmountA();
        if (outB < amountBMin) revert InsufficientAmountB();
        if (outA == 0 && outB == 0) revert ZeroAmount();

        shares[id][msg.sender] -= shareAmount;
        p.totalShares -= shareAmount;
        p.reserveA -= outA;
        p.reserveB -= outB;

        _safeTransfer(p.tokenA, msg.sender, outA);
        _safeTransfer(p.tokenB, msg.sender, outB);
        emit LiquidityRemoved(id, msg.sender, outA, outB, shareAmount);
    }

    // ---------- Arjegyzes es valtas ----------

    function getQuote(uint256 id, address tokenIn, uint256 amountIn)
        public view returns (uint256 amountOut)
    {
        Pool storage p = pools[id];
        (uint256 rIn, uint256 rOut) = _reserves(p, tokenIn);
        if (rIn == 0 || rOut == 0) revert EmptyPool();
        amountOut = _getAmountOut(amountIn, rIn, rOut);
    }

    function swap(
        uint256 id,
        address tokenIn,
        uint256 amountIn,
        uint256 minOut,
        uint256 deadline
    )
        external nonReentrant whenNotPaused ensure(deadline)
        returns (uint256 amountOut)
    {
        Pool storage p = pools[id];
        if (amountIn == 0) revert ZeroAmount();
        (uint256 rIn, uint256 rOut) = _reserves(p, tokenIn);
        if (rIn == 0 || rOut == 0) revert EmptyPool();

        // elobb behuzzuk a tokent, es a TENYLEGESEN beerkezett osszeggel arazunk
        uint256 received = _pullExact(tokenIn, amountIn);
        amountOut = _getAmountOut(received, rIn, rOut);
        if (amountOut < minOut) revert Slippage();
        if (amountOut == 0 || amountOut >= rOut) revert Slippage();

        address tokenOut;
        if (tokenIn == p.tokenA) {
            p.reserveA += received;
            p.reserveB -= amountOut;
            tokenOut = p.tokenB;
        } else {
            p.reserveB += received;
            p.reserveA -= amountOut;
            tokenOut = p.tokenA;
        }
        _safeTransfer(tokenOut, msg.sender, amountOut);
        emit Swapped(id, msg.sender, tokenIn, received, amountOut);
    }

    // ---------- Nezetek ----------

    function poolCount() external view returns (uint256) {
        return pools.length;
    }

    function myShares(uint256 id, address who) external view returns (uint256) {
        return shares[id][who];
    }

    /// A tokenparhoz tartozo pool azonositoja (barmelyik sorrendben). Hiba, ha nincs.
    function poolIdFor(address tokenA, address tokenB) external view returns (uint256) {
        uint256 plusOne = _poolIdPlusOne[_pairKey(tokenA, tokenB)];
        if (plusOne == 0) revert NoPool();
        return plusOne - 1;
    }

    function poolExists(address tokenA, address tokenB) external view returns (bool) {
        return _poolIdPlusOne[_pairKey(tokenA, tokenB)] != 0;
    }

    // ---------- Belso ----------

    function _pairKey(address tokenA, address tokenB) internal pure returns (bytes32) {
        (address lo, address hi) = tokenA < tokenB ? (tokenA, tokenB) : (tokenB, tokenA);
        return keccak256(abi.encodePacked(lo, hi));
    }

    function _reserves(Pool storage p, address tokenIn)
        internal view returns (uint256 rIn, uint256 rOut)
    {
        if (tokenIn == p.tokenA) return (p.reserveA, p.reserveB);
        if (tokenIn == p.tokenB) return (p.reserveB, p.reserveA);
        revert BadTokenIn();
    }

    function _getAmountOut(uint256 amountIn, uint256 rIn, uint256 rOut)
        internal pure returns (uint256)
    {
        uint256 inWithFee = amountIn * (BPS - FEE_BPS);
        return inWithFee * rOut / (rIn * BPS + inWithFee);
    }

    /// transferFrom a hivotol, es visszaadja a tenylegesen beerkezett osszeget.
    function _pullExact(address token, uint256 amount) internal returns (uint256 received) {
        uint256 before = IERC20(token).balanceOf(address(this));
        _safeTransferFrom(token, msg.sender, address(this), amount);
        uint256 after_ = IERC20(token).balanceOf(address(this));
        if (after_ <= before) revert TransferFailed();
        received = after_ - before;
    }

    function _safeTransfer(address token, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(IERC20.transfer.selector, to, amount));
        if (!ok || (data.length != 0 && !abi.decode(data, (bool)))) revert TransferFailed();
    }

    function _safeTransferFrom(address token, address from, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(IERC20.transferFrom.selector, from, to, amount));
        if (!ok || (data.length != 0 && !abi.decode(data, (bool)))) revert TransferFailed();
    }

    function _sqrt(uint256 x) internal pure returns (uint256 y) {
        if (x == 0) return 0;
        uint256 z = (x + 1) / 2;
        y = x;
        while (z < y) {
            y = z;
            z = (x / z + z) / 2;
        }
    }
}

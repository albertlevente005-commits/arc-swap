// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/*
 * ValtoDEX - egyszeru tobb-poolos AMM valto az Arc Testnetre.
 * =============================================================
 * Uniswap-elvu constant-product (x*y=k) arazas, 0,3% valtasi dijjal.
 * A dij a poolban marad, igy a likviditas-adok keresnek vele.
 *
 *  - createPool(tokenA, tokenB)          -> uj tokenpar
 *  - addLiquidity(id, amountA, amountB)  -> likviditas betetele (jegyekert)
 *  - removeLiquidity(id, shares)         -> likviditas kivetele
 *  - getQuote(id, tokenIn, amountIn)     -> mennyi jonne ki (ingyenes lekerdezes)
 *  - swap(id, tokenIn, amountIn, minOut) -> tenyleges valtas
 *
 * Tervezett parok az Arc Testneten:
 *   USDC (6 tizedes)  0x3600000000000000000000000000000000000000
 *   EURC (6 tizedes)  0x89B50855Aa3bE2F677cD6303Cec089B5F319D72a
 *   cirBTC (8 tizedes) 0xf0C4a4CE82A5746AbAAd9425360Ab04fbBA432BF
 *
 * Demo, teszthalozatra - nem auditalt, eles hasznalatra nem ajanlott.
 */

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract ValtoDEX {
    struct Pool {
        address tokenA;
        address tokenB;
        uint256 reserveA;
        uint256 reserveB;
        uint256 totalShares;
    }

    Pool[] public pools;
    // poolId => likviditas-ado => jegyek
    mapping(uint256 => mapping(address => uint256)) public shares;

    uint256 public constant FEE_BPS = 30; // 0,3% valtasi dij

    event PoolCreated(uint256 indexed id, address tokenA, address tokenB);
    event LiquidityAdded(uint256 indexed id, address indexed provider,
                         uint256 amountA, uint256 amountB, uint256 minted);
    event LiquidityRemoved(uint256 indexed id, address indexed provider,
                           uint256 amountA, uint256 amountB);
    event Swapped(uint256 indexed id, address indexed trader,
                  address tokenIn, uint256 amountIn, uint256 amountOut);

    // ---------- Pool letrehozas ----------

    function createPool(address tokenA, address tokenB) external returns (uint256 id) {
        require(tokenA != tokenB, "same token");
        require(tokenA != address(0) && tokenB != address(0), "zero address");
        pools.push(Pool(tokenA, tokenB, 0, 0, 0));
        id = pools.length - 1;
        emit PoolCreated(id, tokenA, tokenB);
    }

    // ---------- Likviditas ----------

    function addLiquidity(uint256 id, uint256 amountA, uint256 amountB)
        external returns (uint256 minted)
    {
        Pool storage p = pools[id];
        require(amountA > 0 && amountB > 0, "amounts=0");

        if (p.totalShares == 0) {
            // elso beteves: a jegyek szama a mertani kozep
            minted = _sqrt(amountA * amountB);
        } else {
            // aranyos beteves: a kisebbik arany szamit
            uint256 mintedA = amountA * p.totalShares / p.reserveA;
            uint256 mintedB = amountB * p.totalShares / p.reserveB;
            minted = mintedA < mintedB ? mintedA : mintedB;
        }
        require(minted > 0, "too small");

        require(IERC20(p.tokenA).transferFrom(msg.sender, address(this), amountA), "A transfer failed");
        require(IERC20(p.tokenB).transferFrom(msg.sender, address(this), amountB), "B transfer failed");

        p.reserveA += amountA;
        p.reserveB += amountB;
        p.totalShares += minted;
        shares[id][msg.sender] += minted;
        emit LiquidityAdded(id, msg.sender, amountA, amountB, minted);
    }

    function removeLiquidity(uint256 id, uint256 shareAmount)
        external returns (uint256 outA, uint256 outB)
    {
        Pool storage p = pools[id];
        require(shareAmount > 0 && shareAmount <= shares[id][msg.sender], "bad shares");

        outA = shareAmount * p.reserveA / p.totalShares;
        outB = shareAmount * p.reserveB / p.totalShares;

        shares[id][msg.sender] -= shareAmount;
        p.totalShares -= shareAmount;
        p.reserveA -= outA;
        p.reserveB -= outB;

        require(IERC20(p.tokenA).transfer(msg.sender, outA), "A transfer failed");
        require(IERC20(p.tokenB).transfer(msg.sender, outB), "B transfer failed");
        emit LiquidityRemoved(id, msg.sender, outA, outB);
    }

    // ---------- Arjegyzes es valtas ----------

    function getQuote(uint256 id, address tokenIn, uint256 amountIn)
        public view returns (uint256 amountOut)
    {
        Pool storage p = pools[id];
        require(tokenIn == p.tokenA || tokenIn == p.tokenB, "bad tokenIn");
        (uint256 rIn, uint256 rOut) = tokenIn == p.tokenA
            ? (p.reserveA, p.reserveB)
            : (p.reserveB, p.reserveA);
        require(rIn > 0 && rOut > 0, "empty pool");

        // constant-product a 0,3% dij levonasa utan
        uint256 inWithFee = amountIn * (10000 - FEE_BPS);
        amountOut = inWithFee * rOut / (rIn * 10000 + inWithFee);
    }

    function swap(uint256 id, address tokenIn, uint256 amountIn, uint256 minOut)
        external returns (uint256 amountOut)
    {
        Pool storage p = pools[id];
        amountOut = getQuote(id, tokenIn, amountIn);
        require(amountOut >= minOut, "slippage");

        address tokenOut = tokenIn == p.tokenA ? p.tokenB : p.tokenA;
        require(IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn), "in transfer failed");

        if (tokenIn == p.tokenA) {
            p.reserveA += amountIn;
            p.reserveB -= amountOut;
        } else {
            p.reserveB += amountIn;
            p.reserveA -= amountOut;
        }
        require(IERC20(tokenOut).transfer(msg.sender, amountOut), "out transfer failed");
        emit Swapped(id, msg.sender, tokenIn, amountIn, amountOut);
    }

    // ---------- Nezetek ----------

    function poolCount() external view returns (uint256) {
        return pools.length;
    }

    function myShares(uint256 id, address who) external view returns (uint256) {
        return shares[id][who];
    }

    // ---------- Belso ----------

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

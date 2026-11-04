// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

// Teszt-segedszerzodesek - NEM kerulnek telepitesre.

interface IValtoDEX {
    function swap(uint256 id, address tokenIn, uint256 amountIn, uint256 minOut, uint256 deadline)
        external returns (uint256);
    function removeLiquidity(uint256 id, uint256 shareAmount, uint256 aMin, uint256 bMin, uint256 deadline)
        external returns (uint256, uint256);
}

/// Szabvanyos ERC-20, szabad mint-tel.
contract MockERC20 {
    string public name;
    string public symbol;
    uint8 public decimals;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(string memory n, string memory s, uint8 d) { name = n; symbol = s; decimals = d; }

    function mint(address to, uint256 amount) external {
        totalSupply += amount; balanceOf[to] += amount; emit Transfer(address(0), to, amount);
    }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount; emit Approval(msg.sender, spender, amount); return true;
    }
    function transfer(address to, uint256 amount) external virtual returns (bool) {
        _move(msg.sender, to, amount); return true;
    }
    function transferFrom(address from, address to, uint256 amount) external virtual returns (bool) {
        uint256 a = allowance[from][msg.sender];
        require(a >= amount, "allowance");
        if (a != type(uint256).max) allowance[from][msg.sender] = a - amount;
        _move(from, to, amount); return true;
    }
    function _move(address from, address to, uint256 amount) internal {
        require(balanceOf[from] >= amount, "balance");
        balanceOf[from] -= amount; balanceOf[to] += amount; emit Transfer(from, to, amount);
    }
}

/// USDT-stilusu token: transfer/transferFrom NEM ad vissza bool-t.
contract NoReturnERC20 {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount; return true;
    }
    function transfer(address to, uint256 amount) external {
        require(balanceOf[msg.sender] >= amount, "balance");
        balanceOf[msg.sender] -= amount; balanceOf[to] += amount;
    }
    function transferFrom(address from, address to, uint256 amount) external {
        require(allowance[from][msg.sender] >= amount, "allowance");
        allowance[from][msg.sender] -= amount;
        require(balanceOf[from] >= amount, "balance");
        balanceOf[from] -= amount; balanceOf[to] += amount;
    }
}

/// Hibas token: false-t ad vissza, de nem revertel.
contract FalseReturnERC20 {
    mapping(address => uint256) public balanceOf;
    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }
    function approve(address, uint256) external pure returns (bool) { return true; }
    function transfer(address, uint256) external pure returns (bool) { return false; }
    function transferFrom(address, address, uint256) external pure returns (bool) { return false; }
}

/// Dijat levono token (fee-on-transfer): a cimzett 1%-kal kevesebbet kap.
contract FeeERC20 is MockERC20 {
    constructor() MockERC20("Fee", "FEE", 6) {}
    function transferFrom(address from, address to, uint256 amount) external override returns (bool) {
        uint256 a = allowance[from][msg.sender];
        require(a >= amount, "allowance");
        allowance[from][msg.sender] = a - amount;
        uint256 fee = amount / 100;
        _move(from, address(0xfee), fee);
        _move(from, to, amount - fee);
        return true;
    }
}

/// Tamado token: amikor a DEX kiutal belole, visszahiv a DEX-be (reentrancy).
contract ReentrantERC20 is MockERC20 {
    IValtoDEX public dex;
    uint256 public poolId;
    address public otherToken;
    bool public attack;
    bool public reentered;
    bool public reentrySucceeded;

    constructor() MockERC20("Evil", "EVIL", 6) {}

    function arm(IValtoDEX d, uint256 id, address other) external { dex = d; poolId = id; otherToken = other; attack = true; }

    function transfer(address to, uint256 amount) external override returns (bool) {
        _move(msg.sender, to, amount);
        if (attack && msg.sender == address(dex) && !reentered) {
            reentered = true;
            // visszahivas: ujabb swap ugyanabban a tranzakcioban
            try dex.swap(poolId, otherToken, 1, 0, type(uint256).max) {
                reentrySucceeded = true;
            } catch {}
        }
        return true;
    }
}

"""
ARC-SWAP: tokenek, poolok, a telepitett DEX cime es ABI-k.
A halozatot (mainnet/testnet) a config.py valasztja ki.
"""

import json
import os
from pathlib import Path

import config

GYOKER = Path(__file__).resolve().parent

# ----- Tokenek az aktualis halozaton -----
TOKENEK = {
    "USDC":   {"cim": config._H["usdc"],   "tizedes": 6},
    "EURC":   {"cim": config._H["eurc"],   "tizedes": 6},
    "CIRBTC": {"cim": config._H["cirbtc"], "tizedes": 8},
}


def _pool_env(nev, alap):
    """POOL_<A>_<B>=<mennyisegA>,<mennyisegB> a .env-bol (pl. POOL_USDC_EURC=5000,4600)."""
    ertek = os.getenv(nev)
    if not ertek:
        return alap
    try:
        a, b = (float(x) for x in ertek.split(","))
        if a <= 0 or b <= 0:
            raise ValueError
        return a, b
    except ValueError:
        raise RuntimeError(f"{nev}: 'mennyisegA,mennyisegB' formatum kell, pl. 5000,4600")


# ----- A tervezett poolok es a kezdo likviditas -----
# FIGYELEM: az ELSO betevo aranya hatarozza meg a pool kezdo arat. Mainneten a piaci
# arfolyamhoz igazitsd (a pool_feltoltes.py ellenorzi a referencia-arfolyamhoz kepest),
# kulonben arbitrazsorok azonnal elviszik a kulonbseget.
if config.MAINNET:
    POOLOK = [
        ("USDC", "EURC",   *_pool_env("POOL_USDC_EURC",   (1000.0, 920.0))),
        ("USDC", "CIRBTC", *_pool_env("POOL_USDC_CIRBTC", (1000.0, 0.01))),
    ]
else:
    POOLOK = [
        ("USDC", "EURC",   *_pool_env("POOL_USDC_EURC",   (20.0, 18.5))),
        ("USDC", "CIRBTC", *_pool_env("POOL_USDC_CIRBTC", (10.0, 0.0001))),
    ]

# ----- A telepitett DEX cime (halozatonkent kulon fajl) -----
VALTO_CIMEK_JSON = GYOKER / f"valto_cimek.{config.HALOZAT}.json"
DEX_CIM = None
DEX_TELEPITES = {}
if VALTO_CIMEK_JSON.exists():
    try:
        DEX_TELEPITES = json.loads(VALTO_CIMEK_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"{VALTO_CIMEK_JSON.name} nem olvashato: {e}")
    if int(DEX_TELEPITES.get("chainId", -1)) != config.CHAIN_ID:
        raise RuntimeError(
            f"{VALTO_CIMEK_JSON.name}: chainId {DEX_TELEPITES.get('chainId')} != "
            f"{config.CHAIN_ID} ({config.HALOZAT_NEV}) - rossz halozat cimfajlja!")
    DEX_CIM = DEX_TELEPITES.get("ValtoDEX")

# ----- ABI-k -----
_BUILD = GYOKER / "build" / "ValtoDEX.json"
if _BUILD.exists():
    DEX_ABI = json.loads(_BUILD.read_text(encoding="utf-8"))["abi"]
else:  # minimalis tartalek, ha nincs build (csak olvasashoz)
    DEX_ABI = [
        {"type": "function", "name": "poolCount", "stateMutability": "view",
         "inputs": [], "outputs": [{"type": "uint256"}]},
        {"type": "function", "name": "pools", "stateMutability": "view",
         "inputs": [{"type": "uint256"}],
         "outputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"},
                     {"name": "reserveA", "type": "uint256"}, {"name": "reserveB", "type": "uint256"},
                     {"name": "totalShares", "type": "uint256"}]},
        {"type": "function", "name": "getQuote", "stateMutability": "view",
         "inputs": [{"type": "uint256"}, {"type": "address"}, {"type": "uint256"}],
         "outputs": [{"type": "uint256"}]},
        {"type": "function", "name": "paused", "stateMutability": "view",
         "inputs": [], "outputs": [{"type": "bool"}]},
        {"type": "event", "name": "Swapped", "anonymous": False, "inputs": [
            {"indexed": True, "name": "id", "type": "uint256"},
            {"indexed": True, "name": "trader", "type": "address"},
            {"indexed": False, "name": "tokenIn", "type": "address"},
            {"indexed": False, "name": "amountIn", "type": "uint256"},
            {"indexed": False, "name": "amountOut", "type": "uint256"}]},
    ]

ERC20_ABI = [
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "decimals", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint8"}]},
]

# A webes feluletnek atadott (ethers.js) ABI - csak az ott hasznalt fuggvenyek
DEX_ABI_JS = [
    "function swap(uint256 id, address tokenIn, uint256 amountIn, uint256 minOut, uint256 deadline) returns (uint256)",
    "function addLiquidity(uint256 id, uint256 amountADesired, uint256 amountBDesired, uint256 amountAMin, uint256 amountBMin, uint256 deadline) returns (uint256, uint256, uint256)",
    "function removeLiquidity(uint256 id, uint256 shareAmount, uint256 amountAMin, uint256 amountBMin, uint256 deadline) returns (uint256, uint256)",
    "function myShares(uint256 id, address who) view returns (uint256)",
    "function pools(uint256) view returns (address tokenA, address tokenB, uint256 reserveA, uint256 reserveB, uint256 totalShares)",
]
ERC20_ABI_JS = [
    "function approve(address spender, uint256 amount) returns (bool)",
    "function allowance(address owner, address spender) view returns (uint256)",
    "function balanceOf(address who) view returns (uint256)",
]


def token_nev(cim):
    for nev, t in TOKENEK.items():
        if t["cim"].lower() == cim.lower():
            return nev
    return cim[:8]


def egysegbe(token, mennyiseg):
    """Ember altal irt mennyiseg -> lanc-egyseg (string). Pontos, tizedes alapu."""
    from decimal import Decimal, InvalidOperation
    t = TOKENEK[token]
    try:
        d = Decimal(str(mennyiseg).strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"ervenytelen mennyiseg: {mennyiseg!r}")
    if not d.is_finite() or d <= 0:
        raise ValueError("a mennyisegnek pozitivnak kell lennie")
    egyseg = int(d.scaleb(t["tizedes"]).to_integral_value(rounding="ROUND_DOWN"))
    if egyseg <= 0:
        raise ValueError(f"tul kicsi mennyiseg ({token}: min 1e-{t['tizedes']})")
    return str(egyseg)


def egysegbol(token, egyseg):
    t = TOKENEK[token]
    return int(egyseg) / (10 ** t["tizedes"])

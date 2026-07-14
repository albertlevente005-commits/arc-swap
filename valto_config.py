"""
ARC-SWAP kozponti beallitasok (onallo repo valtozat).
A kozos magot (Circle kliens, lanc, naplo) helyben tartalmazza a repo.
"""

import json
from pathlib import Path

import config  # helyi config.py (ugyanebben a mappaban)

GYOKER = Path(__file__).resolve().parent

# ----- Tokenek az Arc Testneten -----
TOKENEK = {
    "USDC":   {"cim": "0x3600000000000000000000000000000000000000", "tizedes": 6},
    "EURC":   {"cim": "0x89B50855Aa3bE2F677cD6303Cec089B5F319D72a", "tizedes": 6},
    "CIRBTC": {"cim": "0xf0C4a4CE82A5746AbAAd9425360Ab04fbBA432BF", "tizedes": 8},
}

# ----- A tervezett poolok es a kezdo likviditas -----
POOLOK = [
    ("USDC", "EURC",   20.0, 18.5),
    ("USDC", "CIRBTC", 10.0, 0.0001),
]

# ----- A telepitett DEX cime -----
VALTO_CIMEK_JSON = GYOKER / "valto_cimek.json"
DEX_CIM = None
if VALTO_CIMEK_JSON.exists():
    try:
        DEX_CIM = json.loads(VALTO_CIMEK_JSON.read_text(encoding="utf-8")).get("ValtoDEX")
    except Exception:
        DEX_CIM = None

# ----- ABI-k -----
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
    {"type": "function", "name": "myShares", "stateMutability": "view",
     "inputs": [{"type": "uint256"}, {"type": "address"}],
     "outputs": [{"type": "uint256"}]},
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
]


def token_nev(cim):
    for nev, t in TOKENEK.items():
        if t["cim"].lower() == cim.lower():
            return nev
    return cim[:8]


def egysegbe(token, mennyiseg):
    t = TOKENEK[token]
    return str(int(round(float(mennyiseg) * (10 ** t["tizedes"]))))


def egysegbol(token, egyseg):
    t = TOKENEK[token]
    return int(egyseg) / (10 ** t["tizedes"])

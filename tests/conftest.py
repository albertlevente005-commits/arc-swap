"""
ValtoDEX tesztkornyezet: helyi EVM (eth-tester / py-evm), halozat nelkul.
Futtatas:  node compile.js && python -m pytest tests -q
"""

import json
from pathlib import Path

import pytest
from eth_tester import EthereumTester, PyEVMBackend
from web3 import Web3, EthereumTesterProvider

GYOKER = Path(__file__).resolve().parent.parent
BUILD = GYOKER / "build"

DEADLINE = 2 ** 64  # "soha nem jar le"
MAX = 2 ** 256 - 1


def _art(name):
    if name == "ValtoDEX":
        return json.loads((BUILD / "ValtoDEX.json").read_text(encoding="utf-8"))
    return json.loads((BUILD / "TestMocks.json").read_text(encoding="utf-8"))[name]


@pytest.fixture
def w3():
    tester = EthereumTester(backend=PyEVMBackend())
    w3 = Web3(EthereumTesterProvider(tester))
    w3.eth.default_account = w3.eth.accounts[0]
    return w3


@pytest.fixture
def accounts(w3):
    return w3.eth.accounts


def deploy(w3, name, *args, sender=None):
    art = _art(name)
    c = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    tx = c.constructor(*args).transact({"from": sender or w3.eth.default_account})
    rc = w3.eth.wait_for_transaction_receipt(tx)
    assert rc["status"] == 1, f"{name} telepites hiba"
    return w3.eth.contract(address=rc["contractAddress"], abi=art["abi"])


@pytest.fixture
def tokens(w3, accounts):
    usdc = deploy(w3, "MockERC20", "USD Coin", "USDC", 6)
    eurc = deploy(w3, "MockERC20", "Euro Coin", "EURC", 6)
    for a in accounts[:4]:
        usdc.functions.mint(a, 1_000_000 * 10**6).transact()
        eurc.functions.mint(a, 1_000_000 * 10**6).transact()
    return usdc, eurc


@pytest.fixture
def dex(w3, accounts):
    # tulajdonos = accounts[0]; pool-letrehozas NEM zart (a tesztek egy resze kulon nyitja)
    return deploy(w3, "ValtoDEX", accounts[0], False)


@pytest.fixture
def pool(w3, dex, tokens, accounts):
    """USDC/EURC pool 100 000 USDC + 92 000 EURC kezdo likviditassal (accounts[0])."""
    usdc, eurc = tokens
    dex.functions.createPool(usdc.address, eurc.address).transact()
    a, b = 100_000 * 10**6, 92_000 * 10**6
    usdc.functions.approve(dex.address, a).transact()
    eurc.functions.approve(dex.address, b).transact()
    dex.functions.addLiquidity(0, a, b, a, b, DEADLINE).transact()
    return 0



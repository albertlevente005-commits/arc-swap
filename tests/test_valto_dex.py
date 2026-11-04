"""ValtoDEX - teljes viselkedesi tesztcsomag helyi EVM-en."""

import pytest
from conftest import DEADLINE, MAX, deploy


def _revert_selector(exc):
    """A revert adat elso 4 bajtja hexben (web3 ContractCustomError vagy eth-tester TransactionFailed)."""
    import ast
    import re
    data = getattr(exc, "data", None)
    if isinstance(data, str) and data.startswith("0x"):
        return data[2:10]
    for a in exc.args:
        if isinstance(a, bytes):
            return a[:4].hex()
        if isinstance(a, str):
            if a.startswith("0x"):
                return a[2:10]
            m = re.search(r"""(b'(?:[^'\\]|\\.)*'|b"(?:[^"\\]|\\.)*")""", a)
            if m:
                return ast.literal_eval(m.group(1))[:4].hex()
    return None


def expect_error(name, fn, tx=None):
    """A hivasnak a megadott egyedi hibaval kell revertelnie (eth_call + tranzakcio is)."""
    from web3 import Web3
    tx = tx or {}
    with pytest.raises(Exception) as ei:
        fn.call(tx)
    sel = _revert_selector(ei.value)
    abi = fn.contract_abi if hasattr(fn, "contract_abi") else fn.abi
    names = {}
    for item in abi:
        if item.get("type") == "error":
            types = ",".join(i["type"] for i in item.get("inputs", []))
            names[Web3.keccak(text=f"{item['name']}({types})")[:4].hex()] = item["name"]
    assert names.get(sel, sel) == name, f"vart: {name}, kapott: {names.get(sel, sel)} ({ei.value})"
    with pytest.raises(Exception):
        fn.transact(tx)


def amount_out(amount_in, r_in, r_out, fee_bps=30):
    k = amount_in * (10_000 - fee_bps)
    return k * r_out // (r_in * 10_000 + k)


# ---------- Pool letrehozas / tulajdonos ----------

def test_constructor_sets_owner_and_restriction(w3, accounts):
    d = deploy(w3, "ValtoDEX", accounts[1], True)
    assert d.functions.owner().call() == accounts[1]
    assert d.functions.poolCreationRestricted().call() is True
    assert d.functions.paused().call() is False


def test_constructor_rejects_zero_owner(w3):
    from conftest import _art
    art = _art("ValtoDEX")
    c = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    with pytest.raises(Exception):
        c.constructor("0x" + "0" * 40, True).transact()


def test_create_pool_and_lookup(dex, tokens):
    usdc, eurc = tokens
    dex.functions.createPool(usdc.address, eurc.address).transact()
    assert dex.functions.poolCount().call() == 1
    assert dex.functions.poolIdFor(usdc.address, eurc.address).call() == 0
    assert dex.functions.poolIdFor(eurc.address, usdc.address).call() == 0
    assert dex.functions.poolExists(eurc.address, usdc.address).call() is True


def test_duplicate_pool_rejected_in_both_orders(dex, tokens):
    usdc, eurc = tokens
    dex.functions.createPool(usdc.address, eurc.address).transact()
    expect_error("PoolExists", dex.functions.createPool(usdc.address, eurc.address))
    expect_error("PoolExists", dex.functions.createPool(eurc.address, usdc.address))


def test_create_pool_validations(dex, tokens):
    usdc, _ = tokens
    expect_error("SameToken", dex.functions.createPool(usdc.address, usdc.address))
    expect_error("ZeroAddress", dex.functions.createPool(usdc.address, "0x" + "0" * 40))


def test_restricted_pool_creation(w3, accounts, tokens):
    usdc, eurc = tokens
    d = deploy(w3, "ValtoDEX", accounts[0], True)
    expect_error("PoolCreationRestricted",
                 d.functions.createPool(usdc.address, eurc.address), {"from": accounts[1]})
    d.functions.createPool(usdc.address, eurc.address).transact({"from": accounts[0]})
    assert d.functions.poolCount().call() == 1
    d.functions.setPoolCreationRestricted(False).transact()
    expect_error("NotOwner", d.functions.setPoolCreationRestricted(True), {"from": accounts[1]})


def test_two_step_ownership(dex, accounts):
    expect_error("ZeroAddress", dex.functions.transferOwnership("0x" + "0" * 40))
    dex.functions.transferOwnership(accounts[2]).transact()
    assert dex.functions.owner().call() == accounts[0]
    expect_error("NotPendingOwner", dex.functions.acceptOwnership(), {"from": accounts[1]})
    dex.functions.acceptOwnership().transact({"from": accounts[2]})
    assert dex.functions.owner().call() == accounts[2]
    assert dex.functions.pendingOwner().call() == "0x" + "0" * 40
    expect_error("NotOwner", dex.functions.pause(), {"from": accounts[0]})


def test_native_value_rejected(w3, dex, accounts):
    with pytest.raises(Exception):
        w3.eth.send_transaction({"from": accounts[0], "to": dex.address, "value": 1})


# ---------- Likviditas ----------

def test_first_deposit_locks_minimum_liquidity(dex, tokens, pool, accounts):
    import math
    p = dex.functions.pools(0).call()
    total = p[4]
    expected_total = math.isqrt(100_000 * 10**6 * 92_000 * 10**6)
    assert total == expected_total
    assert dex.functions.myShares(0, accounts[0]).call() == expected_total - 1000
    assert dex.functions.myShares(0, "0x000000000000000000000000000000000000dEaD").call() == 1000


def test_first_deposit_too_small(dex, tokens):
    usdc, eurc = tokens
    dex.functions.createPool(usdc.address, eurc.address).transact()
    usdc.functions.approve(dex.address, MAX).transact()
    eurc.functions.approve(dex.address, MAX).transact()
    expect_error("InsufficientLiquidityMinted",
                 dex.functions.addLiquidity(0, 30, 30, 0, 0, DEADLINE))
    expect_error("ZeroAmount", dex.functions.addLiquidity(0, 0, 30, 0, 0, DEADLINE))


def test_proportional_deposit_takes_only_needed(dex, tokens, pool, accounts):
    usdc, eurc = tokens
    me = accounts[1]
    usdc.functions.approve(dex.address, MAX).transact({"from": me})
    eurc.functions.approve(dex.address, MAX).transact({"from": me})
    u0, e0 = usdc.functions.balanceOf(me).call(), eurc.functions.balanceOf(me).call()
    # 1000 USDC + 5000 EURC-t ajanlunk, de az arany 100:92 -> csak 920 EURC megy be
    dex.functions.addLiquidity(0, 1000 * 10**6, 5000 * 10**6, 1000 * 10**6, 900 * 10**6,
                               DEADLINE).transact({"from": me})
    assert u0 - usdc.functions.balanceOf(me).call() == 1000 * 10**6
    assert e0 - eurc.functions.balanceOf(me).call() == 920 * 10**6
    assert dex.functions.myShares(0, me).call() > 0
    # forditva: 5000 USDC + 920 EURC -> csak 1000 USDC megy be
    u0 = usdc.functions.balanceOf(me).call()
    dex.functions.addLiquidity(0, 5000 * 10**6, 920 * 10**6, 0, 0, DEADLINE).transact({"from": me})
    assert u0 - usdc.functions.balanceOf(me).call() == 1000 * 10**6


def test_deposit_min_amount_guards(dex, tokens, pool, accounts):
    usdc, eurc = tokens
    me = accounts[1]
    usdc.functions.approve(dex.address, MAX).transact({"from": me})
    eurc.functions.approve(dex.address, MAX).transact({"from": me})
    expect_error("InsufficientAmountB",
                 dex.functions.addLiquidity(0, 1000 * 10**6, 5000 * 10**6, 0, 921 * 10**6, DEADLINE),
                 {"from": me})
    expect_error("InsufficientAmountA",
                 dex.functions.addLiquidity(0, 5000 * 10**6, 920 * 10**6, 1001 * 10**6, 0, DEADLINE),
                 {"from": me})


def test_remove_liquidity_roundtrip_and_slippage(dex, tokens, pool, accounts):
    usdc, eurc = tokens
    me = accounts[0]
    sh = dex.functions.myShares(0, me).call()
    u0, e0 = usdc.functions.balanceOf(me).call(), eurc.functions.balanceOf(me).call()
    expect_error("InsufficientAmountA",
                 dex.functions.removeLiquidity(0, sh, 10**30, 0, DEADLINE))
    expect_error("InsufficientShares",
                 dex.functions.removeLiquidity(0, sh + 1, 0, 0, DEADLINE))
    expect_error("InsufficientShares",
                 dex.functions.removeLiquidity(0, 0, 0, 0, DEADLINE))
    dex.functions.removeLiquidity(0, sh, 0, 0, DEADLINE).transact()
    # a zarolt 1000 share-nyi likviditas a poolban marad, a tobbi visszajon
    p = dex.functions.pools(0).call()
    assert p[4] == 1000 and p[2] > 0 and p[3] > 0
    assert usdc.functions.balanceOf(me).call() - u0 == 100_000 * 10**6 - p[2]
    assert eurc.functions.balanceOf(me).call() - e0 == 92_000 * 10**6 - p[3]
    assert dex.functions.myShares(0, me).call() == 0


def test_remove_liquidity_works_while_paused(dex, tokens, pool, accounts):
    dex.functions.pause().transact()
    sh = dex.functions.myShares(0, accounts[0]).call()
    dex.functions.removeLiquidity(0, sh // 2, 0, 0, DEADLINE).transact()
    assert dex.functions.myShares(0, accounts[0]).call() == sh - sh // 2


# ---------- Arjegyzes es valtas ----------

def test_quote_matches_formula(dex, tokens, pool):
    usdc, eurc = tokens
    q = dex.functions.getQuote(0, usdc.address, 1000 * 10**6).call()
    assert q == amount_out(1000 * 10**6, 100_000 * 10**6, 92_000 * 10**6)
    q2 = dex.functions.getQuote(0, eurc.address, 1000 * 10**6).call()
    assert q2 == amount_out(1000 * 10**6, 92_000 * 10**6, 100_000 * 10**6)


def test_quote_errors(dex, tokens, accounts):
    usdc, eurc = tokens
    dex.functions.createPool(usdc.address, eurc.address).transact()
    with pytest.raises(Exception) as e1:
        dex.functions.getQuote(0, usdc.address, 1).call()
    with pytest.raises(Exception) as e2:
        dex.functions.getQuote(0, accounts[5], 1).call()
    from web3 import Web3
    assert _revert_selector(e1.value) == Web3.keccak(text="EmptyPool()")[:4].hex()
    assert _revert_selector(e2.value) == Web3.keccak(text="BadTokenIn()")[:4].hex()


def test_swap_moves_tokens_and_keeps_k(dex, tokens, pool, accounts):
    usdc, eurc = tokens
    me = accounts[1]
    amt = 1000 * 10**6
    usdc.functions.approve(dex.address, amt).transact({"from": me})
    q = dex.functions.getQuote(0, usdc.address, amt).call()
    e0 = eurc.functions.balanceOf(me).call()
    rc = w3_receipt(dex, dex.functions.swap(0, usdc.address, amt, q, DEADLINE), {"from": me})
    assert eurc.functions.balanceOf(me).call() - e0 == q
    p = dex.functions.pools(0).call()
    assert p[2] == 100_000 * 10**6 + amt and p[3] == 92_000 * 10**6 - q
    assert p[2] * p[3] >= 100_000 * 10**6 * 92_000 * 10**6  # k nem csokkenhet
    ev = dex.events.Swapped().process_receipt(rc)
    assert ev[0]["args"]["amountOut"] == q and ev[0]["args"]["trader"] == me
    # a szerzodes tenyleges egyenlege = reserve
    assert usdc.functions.balanceOf(dex.address).call() == p[2]
    assert eurc.functions.balanceOf(dex.address).call() == p[3]


def w3_receipt(contract, fn, tx):
    h = fn.transact(tx)
    return contract.w3.eth.wait_for_transaction_receipt(h)


def test_swap_slippage_and_deadline(dex, tokens, pool, accounts):
    usdc, _ = tokens
    me = accounts[1]
    amt = 1000 * 10**6
    usdc.functions.approve(dex.address, MAX).transact({"from": me})
    q = dex.functions.getQuote(0, usdc.address, amt).call()
    expect_error("Slippage", dex.functions.swap(0, usdc.address, amt, q + 1, DEADLINE), {"from": me})
    expect_error("Expired", dex.functions.swap(0, usdc.address, amt, 0, 1), {"from": me})
    expect_error("ZeroAmount", dex.functions.swap(0, usdc.address, 0, 0, DEADLINE), {"from": me})
    expect_error("BadTokenIn", dex.functions.swap(0, accounts[5], amt, 0, DEADLINE), {"from": me})


def test_swap_blocked_when_paused(dex, tokens, pool, accounts):
    usdc, _ = tokens
    me = accounts[1]
    usdc.functions.approve(dex.address, MAX).transact({"from": me})
    dex.functions.pause().transact()
    expect_error("IsPaused", dex.functions.swap(0, usdc.address, 10**6, 0, DEADLINE), {"from": me})
    expect_error("IsPaused", dex.functions.addLiquidity(0, 10**6, 10**6, 0, 0, DEADLINE), {"from": me})
    dex.functions.unpause().transact()
    dex.functions.swap(0, usdc.address, 10**6, 0, DEADLINE).transact({"from": me})


def test_swap_cannot_drain_pool(dex, tokens, pool, accounts):
    usdc, eurc = tokens
    me = accounts[1]
    usdc.functions.mint(me, 10**30).transact()
    usdc.functions.approve(dex.address, MAX).transact({"from": me})
    dex.functions.swap(0, usdc.address, 10**24, 0, DEADLINE).transact({"from": me})
    p = dex.functions.pools(0).call()
    assert p[3] > 0  # soha nem megy nullara


def test_insufficient_allowance_reverts(dex, tokens, pool, accounts):
    usdc, _ = tokens
    me = accounts[1]
    usdc.functions.approve(dex.address, 1).transact({"from": me})
    with pytest.raises(Exception):
        dex.functions.swap(0, usdc.address, 10**6, 0, DEADLINE).transact({"from": me})


# ---------- Token-kompatibilitas ----------

def test_no_return_value_token_works(w3, dex, tokens, accounts):
    usdc, _ = tokens
    usdt = deploy(w3, "NoReturnERC20")
    usdt.functions.mint(accounts[0], 10**12).transact()
    dex.functions.createPool(usdc.address, usdt.address).transact()
    usdc.functions.approve(dex.address, MAX).transact()
    usdt.functions.approve(dex.address, MAX).transact()
    dex.functions.addLiquidity(0, 10**10, 10**10, 0, 0, DEADLINE).transact()
    dex.functions.swap(0, usdc.address, 10**6, 0, DEADLINE).transact()
    sh = dex.functions.myShares(0, accounts[0]).call()
    dex.functions.removeLiquidity(0, sh, 0, 0, DEADLINE).transact()
    assert usdt.functions.balanceOf(dex.address).call() > 0  # zarolt resz


def test_false_return_token_rejected(w3, dex, tokens, accounts):
    usdc, _ = tokens
    bad = deploy(w3, "FalseReturnERC20")
    bad.functions.mint(accounts[0], 10**12).transact()
    dex.functions.createPool(usdc.address, bad.address).transact()
    usdc.functions.approve(dex.address, MAX).transact()
    expect_error("TransferFailed", dex.functions.addLiquidity(0, 10**10, 10**10, 0, 0, DEADLINE))


def test_fee_on_transfer_token_uses_received_amount(w3, dex, tokens, accounts):
    usdc, _ = tokens
    fee = deploy(w3, "FeeERC20")
    fee.functions.mint(accounts[0], 10**12).transact()
    dex.functions.createPool(usdc.address, fee.address).transact()
    usdc.functions.approve(dex.address, MAX).transact()
    fee.functions.approve(dex.address, MAX).transact()
    dex.functions.addLiquidity(0, 10**10, 10**10, 0, 0, DEADLINE).transact()
    p = dex.functions.pools(0).call()
    assert p[3] == 10**10 - 10**8            # 1% dij levonva -> a reserve a valos egyenleg
    assert fee.functions.balanceOf(dex.address).call() == p[3]
    q_naive = amount_out(10**6, p[3], p[2])
    rc = w3_receipt(dex, dex.functions.swap(0, fee.address, 10**6, 0, DEADLINE), {"from": accounts[0]})
    ev = dex.events.Swapped().process_receipt(rc)[0]["args"]
    assert ev["amountIn"] == 10**6 - 10**4   # a tenylegesen beerkezett
    assert ev["amountOut"] < q_naive
    p2 = dex.functions.pools(0).call()
    assert fee.functions.balanceOf(dex.address).call() == p2[3]


def test_reentrancy_blocked(w3, dex, tokens, accounts):
    usdc, _ = tokens
    evil = deploy(w3, "ReentrantERC20")
    evil.functions.mint(accounts[0], 10**12).transact()
    dex.functions.createPool(usdc.address, evil.address).transact()
    usdc.functions.approve(dex.address, MAX).transact()
    evil.functions.approve(dex.address, MAX).transact()
    dex.functions.addLiquidity(0, 10**10, 10**10, 0, 0, DEADLINE).transact()
    evil.functions.arm(dex.address, 0, usdc.address).transact()
    # USDC -> EVIL valtas: a DEX kiutal EVIL-t, ami visszahiv swap()-ba
    dex.functions.swap(0, usdc.address, 10**6, 0, DEADLINE).transact()
    assert evil.functions.reentered().call() is True
    assert evil.functions.reentrySucceeded().call() is False
    p = dex.functions.pools(0).call()
    assert usdc.functions.balanceOf(dex.address).call() == p[2]
    assert evil.functions.balanceOf(dex.address).call() == p[3]


# ---------- Tobb pool, tobb LP ----------

def test_multiple_lps_share_fees(dex, tokens, pool, accounts):
    usdc, eurc = tokens
    lp2, trader = accounts[1], accounts[2]
    for t in (usdc, eurc):
        t.functions.approve(dex.address, MAX).transact({"from": lp2})
        t.functions.approve(dex.address, MAX).transact({"from": trader})
    dex.functions.addLiquidity(0, 10_000 * 10**6, 9_200 * 10**6, 0, 0, DEADLINE).transact({"from": lp2})
    sh2 = dex.functions.myShares(0, lp2).call()
    for _ in range(20):
        dex.functions.swap(0, usdc.address, 500 * 10**6, 0, DEADLINE).transact({"from": trader})
        dex.functions.swap(0, eurc.address, 450 * 10**6, 0, DEADLINE).transact({"from": trader})
    p = dex.functions.pools(0).call()
    out_a = sh2 * p[2] // p[4]
    out_b = sh2 * p[3] // p[4]
    # a dijak miatt az LP ertekben tobbet kap vissza, mint amennyit betett (k nott)
    assert out_a * out_b > 10_000 * 10**6 * 9_200 * 10**6

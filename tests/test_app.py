"""
valto_app - HTTP szintu tesztek helyi EVM-mel (eth-tester), halozat es Circle nelkul.
A DEX-et a tesztlancra telepitjuk, es az app `lanc.web3` / `dex` objektumait arra iranyitjuk.
"""

import os

import pytest
from conftest import DEADLINE, deploy

os.environ.setdefault("ARC_HALOZAT", "testnet")
os.environ["VALTO_ADMIN_TOKEN"] = "teszt-admin-token-1234567890"
os.environ["MEGRENDELO_CIM"] = "0x" + "11" * 20
os.environ["CIRCLE_API_KEY"] = "x"
os.environ["CIRCLE_ENTITY_SECRET"] = "y"


@pytest.fixture
def kliens(w3, accounts, monkeypatch):
    import config
    import valto_config as vc
    from mag import lanc
    import valto_app

    usdc = deploy(w3, "MockERC20", "USD Coin", "USDC", 6)
    eurc = deploy(w3, "MockERC20", "Euro Coin", "EURC", 6)
    dex = deploy(w3, "ValtoDEX", accounts[0], False)
    for t in (usdc, eurc):
        t.functions.mint(accounts[0], 10**12).transact()
        t.functions.approve(dex.address, 10**12).transact()
    dex.functions.createPool(usdc.address, eurc.address).transact()
    dex.functions.addLiquidity(0, 100_000 * 10**6, 92_000 * 10**6, 0, 0, DEADLINE).transact()

    monkeypatch.setitem(vc.TOKENEK["USDC"], "cim", usdc.address)
    monkeypatch.setitem(vc.TOKENEK["EURC"], "cim", eurc.address)
    monkeypatch.setattr(vc, "DEX_CIM", dex.address)
    monkeypatch.setattr(lanc, "web3", w3)
    monkeypatch.setattr(valto_app, "dex", w3.eth.contract(address=dex.address, abi=vc.DEX_ABI))
    monkeypatch.setattr(config, "MEGRENDELO_CIM", accounts[1])
    valto_app._allapot_cache.update(ido=0, adat=None)
    valto_app._elozmeny.update(utolso_blokk=0, sorok=[])
    valto_app.app.config["TESTING"] = True
    return valto_app.app.test_client(), dex, usdc, eurc


def test_allapot_lists_pool_and_network(kliens):
    c, dex, usdc, eurc = kliens
    r = c.get("/api/allapot")
    assert r.status_code == 200
    d = r.get_json()
    assert d["halozat"]["chainId"] in (5042, 5042002)
    assert d["dex"] == dex.address
    assert d["circle_mod"] is True
    assert len(d["poolok"]) == 1 and d["poolok"][0]["tokenA"] == "USDC"
    assert abs(d["poolok"][0]["arfolyam"] - 0.92) < 1e-9
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Frame-Options"] == "DENY"


def test_healthz(kliens):
    c, *_ = kliens
    r = c.get("/healthz")
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_quote_ok_and_validation(kliens):
    c, dex, usdc, eurc = kliens
    r = c.post("/api/arjegyzes", json={"pool_id": 0, "token_be": "USDC", "token_ki": "EURC",
                                       "mennyiseg": "1000"})
    d = r.get_json()
    assert r.status_code == 200 and d["ok"]
    assert int(d["ki_egyseg"]) == dex.functions.getQuote(0, usdc.address, 1000 * 10**6).call()
    assert c.post("/api/arjegyzes", json={"pool_id": 0, "token_be": "USDC", "token_ki": "EURC",
                                          "mennyiseg": "-1"}).status_code == 400
    assert c.post("/api/arjegyzes", json={"pool_id": 0, "token_be": "USDC", "token_ki": "EURC",
                                          "mennyiseg": "abc"}).status_code == 400
    assert c.post("/api/arjegyzes", json={"pool_id": 9, "token_be": "USDC", "token_ki": "EURC",
                                          "mennyiseg": "1"}).status_code == 400
    assert c.post("/api/arjegyzes", json={"pool_id": 0, "token_be": "USDC", "token_ki": "CIRBTC",
                                          "mennyiseg": "1"}).status_code == 400
    assert c.post("/api/arjegyzes", json={"pool_id": 0, "token_be": "USDC", "token_ki": "USDC",
                                          "mennyiseg": "1"}).status_code == 400
    assert c.post("/api/arjegyzes", data="nem json").status_code == 400
    # vesszovel irt tizedes is megy
    r = c.post("/api/arjegyzes", json={"pool_id": 0, "token_be": "USDC", "token_ki": "EURC",
                                       "mennyiseg": "1,5"})
    assert r.get_json()["ok"]


def test_write_endpoints_require_admin_token(kliens):
    c, *_ = kliens
    body = {"pool_id": 0, "token_be": "USDC", "token_ki": "EURC", "mennyiseg": "1"}
    assert c.post("/api/valtas", json=body).status_code == 403
    assert c.post("/api/valtas", json=body, headers={"X-Admin-Token": "rossz"}).status_code == 403
    assert c.post("/api/likviditas", json={"pool_id": 0, "mennyiseg_a": "1", "mennyiseg_b": "1"}).status_code == 403
    assert c.post("/api/likviditas_kivet", json={"pool_id": 0}).status_code == 403


def test_write_endpoints_disabled_without_token(kliens, monkeypatch):
    import config
    c, *_ = kliens
    monkeypatch.setattr(config, "ADMIN_TOKEN", None)
    r = c.post("/api/valtas", json={"pool_id": 0, "token_be": "USDC", "token_ki": "EURC", "mennyiseg": "1"},
               headers={"X-Admin-Token": "akarmi"})
    assert r.status_code == 403
    r = c.get("/api/allapot")
    assert r.get_json()["circle_mod"] is False and r.get_json()["megrendelo"]["cim"] is None


def test_swap_with_admin_token_calls_circle_with_slippage(kliens, monkeypatch):
    import config
    from mag import circle_kliens
    c, dex, usdc, eurc = kliens
    hivasok = []

    def fake_tx(tarca, szerzodes, szignatura, parameterek, cimke):
        hivasok.append((szerzodes, szignatura, parameterek))
        return "0x" + "ab" * 32
    monkeypatch.setattr(circle_kliens, "contract_tx", fake_tx)
    usdc.functions.mint(config.MEGRENDELO_CIM, 10**9).transact()

    r = c.post("/api/valtas", json={"pool_id": 0, "token_be": "USDC", "token_ki": "EURC",
                                    "mennyiseg": "10", "slippage_bps": 100},
               headers={"X-Admin-Token": os.environ["VALTO_ADMIN_TOKEN"]})
    d = r.get_json()
    assert r.status_code == 200 and d["ok"], d
    # approve (nincs allowance) + swap
    assert hivasok[0][1] == "approve(address,uint256)"
    assert hivasok[1][1] == "swap(uint256,address,uint256,uint256,uint256)"
    pid, token_in, amount_in, min_out, deadline = hivasok[1][2]
    q = dex.functions.getQuote(0, usdc.address, 10 * 10**6).call()
    assert int(amount_in) == 10 * 10**6 and int(min_out) == q * 9900 // 10000
    assert int(deadline) > 0
    assert d["tx"].endswith("ab" * 32)

    # tul nagy slippage -> 400
    r = c.post("/api/valtas", json={"pool_id": 0, "token_be": "USDC", "token_ki": "EURC",
                                    "mennyiseg": "10", "slippage_bps": 5000},
               headers={"X-Admin-Token": os.environ["VALTO_ADMIN_TOKEN"]})
    assert r.status_code == 400

    # elegtelen egyenleg -> 400, nincs Circle hivas
    n = len(hivasok)
    r = c.post("/api/valtas", json={"pool_id": 0, "token_be": "EURC", "token_ki": "USDC",
                                    "mennyiseg": "10"},
               headers={"X-Admin-Token": os.environ["VALTO_ADMIN_TOKEN"]})
    assert r.status_code == 400 and len(hivasok) == n


def test_swap_blocked_when_paused(kliens, monkeypatch):
    from mag import circle_kliens
    c, dex, usdc, eurc = kliens
    monkeypatch.setattr(circle_kliens, "contract_tx", lambda *a, **k: "0x00")
    dex.functions.pause().transact()
    r = c.post("/api/valtas", json={"pool_id": 0, "token_be": "USDC", "token_ki": "EURC",
                                    "mennyiseg": "1"},
               headers={"X-Admin-Token": os.environ["VALTO_ADMIN_TOKEN"]})
    assert r.status_code == 409
    assert c.get("/api/allapot").get_json()["szunetel"] is True


def test_lp_position_and_history(kliens, accounts):
    c, dex, usdc, eurc = kliens
    r = c.post("/api/lp", json={"cim": accounts[0]})
    d = r.get_json()
    assert d["ok"] and d["poolok"][0]["resz"] > 0.99
    assert c.post("/api/lp", json={"cim": "nem cim"}).status_code == 400
    import valto_app
    dex.functions.swap(0, usdc.address, 10**6, 0, DEADLINE).transact()
    valto_app.elozmenyek_frissitese()
    d = c.get("/api/allapot").get_json()
    assert len(d["elozmenyek"]) == 1 and d["elozmenyek"][0]["be"].endswith("USDC")


def test_index_serves_ui_and_static_ethers(kliens):
    c, *_ = kliens
    r = c.get("/")
    assert r.status_code == 200 and b"ARC Swap" in r.data and b"cdnjs" not in r.data
    r = c.get("/static/ethers-5.7.2.umd.min.js")
    assert r.status_code == 200 and len(r.data) > 100_000

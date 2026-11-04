"""
ARC SWAP - webes valto felulet (Flask), angol UI
=================================================
Ket mod:
  1. METAMASK mod - a bongeszoben a SAJAT tarcaddal irod ala a valtast (alapertelmezett,
                    a szervernek nincs hozzaferese a penzedhez)
  2. CIRCLE mod   - a szerver a MEGRENDELO Circle-tarcaval valt. Csak akkor elerheto,
                    ha a .env-ben van VALTO_ADMIN_TOKEN, es a felulet elkeri a tokent.

Inditas (a projektmappabol):
    python valto_app.py
Utana bongeszoben:  http://127.0.0.1:8060   (APP_HOST / APP_PORT a .env-ben)

Eles uzemben (mainnet) a szervert TLS-t vegzo reverse proxy (nginx, Caddy) moge tedd,
es csak a sajat halozatodon / VPN-en keresztul erd el a Circle-modot.
"""

import hmac
import threading
import time
import traceback

from flask import Flask, jsonify, request
from web3 import Web3

import valto_config as vc
import config
from mag import circle_kliens, lanc, seged

app = Flask(__name__, static_folder=str(vc.GYOKER / "static"), static_url_path="/static")
app.config["JSON_SORT_KEYS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
naplo = seged.naplo

zar = threading.Lock()            # egyszerre csak egy Circle-tranzakcio-sorozat
_elozmeny_zar = threading.Lock()
_elozmeny = {"utolso_blokk": 0, "sorok": [], "frissitve": 0}
_allapot_cache = {"ido": 0, "adat": None}
ALLAPOT_CACHE_MP = 3

dex = lanc.web3.eth.contract(
    address=Web3.to_checksum_address(vc.DEX_CIM or "0x" + "0" * 40), abi=vc.DEX_ABI)


class Hiba(Exception):
    """Felhasznalonak szant hiba (HTTP statusszal)."""

    def __init__(self, uzenet, statusz=400):
        super().__init__(uzenet)
        self.statusz = statusz


# ---------- Segedek ----------

def _token_c(token):
    return lanc.web3.eth.contract(
        address=Web3.to_checksum_address(vc.TOKENEK[token]["cim"]), abi=vc.ERC20_ABI)


def token_egyenleg(token, cim):
    try:
        return vc.egysegbol(token, _token_c(token).functions.balanceOf(
            Web3.to_checksum_address(cim)).call())
    except Exception:
        return None


def allowance(token, tulaj, kolto):
    return int(_token_c(token).functions.allowance(
        Web3.to_checksum_address(tulaj), Web3.to_checksum_address(kolto)).call())


def poolok_lekerese():
    ki = []
    if not vc.DEX_CIM:
        return ki
    darab = int(dex.functions.poolCount().call())
    for i in range(darab):
        p = dex.functions.pools(i).call()
        na, nb = vc.token_nev(p[0]), vc.token_nev(p[1])
        if na not in vc.TOKENEK or nb not in vc.TOKENEK:
            continue  # ismeretlen token - nem mutatjuk
        ra, rb = vc.egysegbol(na, p[2]), vc.egysegbol(nb, p[3])
        ki.append({"id": i, "tokenA": na, "tokenB": nb,
                   "keszletA": ra, "keszletB": rb, "shares": str(p[4]),
                   "arfolyam": (rb / ra) if ra else 0})
    return ki


def dex_szunetel():
    try:
        return bool(dex.functions.paused().call())
    except Exception:
        return False


def elozmenyek_frissitese():
    """Swapped esemenyek beolvasasa (max 9000 blokk / keres az Arc RPC limit miatt)."""
    if not vc.DEX_CIM:
        return
    with _elozmeny_zar:
        try:
            veg = lanc.blokkszam()
            if _elozmeny["utolso_blokk"]:
                frm = _elozmeny["utolso_blokk"] + 1
            else:
                frm = max(0, veg - config.ELOZMENY_VISSZA_BLOKK)
            while frm <= veg:
                to = min(frm + config.MAX_LOG_BLOKK - 1, veg)
                logs = seged.retry(lambda f=frm, t=to: dex.events.Swapped.create_filter(
                    from_block=f, to_block=t).get_all_entries(), "swap esemenyek", probak=3)
                for lg in logs:
                    be_nev = vc.token_nev(lg["args"]["tokenIn"])
                    pool = dex.functions.pools(int(lg["args"]["id"])).call()
                    ki_cim = pool[1] if pool[0].lower() == lg["args"]["tokenIn"].lower() else pool[0]
                    ki_nev = vc.token_nev(ki_cim)
                    if be_nev not in vc.TOKENEK or ki_nev not in vc.TOKENEK:
                        continue
                    _elozmeny["sorok"].append({
                        "blokk": lg["blockNumber"], "valto": lg["args"]["trader"],
                        "tx": lg["transactionHash"].hex(),
                        "be": f'{vc.egysegbol(be_nev, lg["args"]["amountIn"])} {be_nev}',
                        "ki": f'{vc.egysegbol(ki_nev, lg["args"]["amountOut"])} {ki_nev}'})
                frm = to + 1
            _elozmeny["utolso_blokk"] = veg
            _elozmeny["sorok"] = _elozmeny["sorok"][-25:]
            _elozmeny["frissitve"] = time.time()
        except Exception as e:
            naplo.warning("elozmeny frissites hiba: %s", e)


def _elozmeny_hatter():
    while True:
        elozmenyek_frissitese()
        time.sleep(15)


def _admin_ellenorzes():
    """A Circle-mod iro vegpontjai: csak ervenyes admin tokennel."""
    if not config.ADMIN_TOKEN:
        raise Hiba("Circle mode is disabled on this server (no VALTO_ADMIN_TOKEN).", 403)
    if not config.MEGRENDELO_CIM:
        raise Hiba("Circle mode is not configured (MEGRENDELO_CIM missing).", 403)
    kapott = request.headers.get("X-Admin-Token", "")
    if not kapott or not hmac.compare_digest(kapott, config.ADMIN_TOKEN):
        raise Hiba("Invalid admin token.", 403)


def _json():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise Hiba("JSON body expected.")
    return d


def _pool_id(d):
    try:
        pid = int(d.get("pool_id"))
    except (TypeError, ValueError):
        raise Hiba("pool_id must be an integer.")
    if pid < 0 or not vc.DEX_CIM or pid >= int(dex.functions.poolCount().call()):
        raise Hiba("Unknown pool.")
    return pid


def _token(d, kulcs):
    t = str(d.get(kulcs, "")).upper()
    if t not in vc.TOKENEK:
        raise Hiba(f"Unknown token: {kulcs}.")
    return t


def _egyseg(token, ertek):
    try:
        return vc.egysegbe(token, ertek)
    except (ValueError, TypeError) as e:
        raise Hiba(f"Invalid amount: {e}")


def _slippage_bps(d):
    try:
        bps = int(d.get("slippage_bps", config.ALAP_SLIPPAGE_BPS))
    except (TypeError, ValueError):
        raise Hiba("slippage_bps must be an integer.")
    if bps < 1 or bps > config.MAX_SLIPPAGE_BPS:
        raise Hiba(f"slippage_bps must be between 1 and {config.MAX_SLIPPAGE_BPS}.")
    return bps


def _pool_tokenek(pid, token_be, token_ki):
    p = dex.functions.pools(pid).call()
    cimek = {p[0].lower(), p[1].lower()}
    if (vc.TOKENEK[token_be]["cim"].lower() not in cimek
            or vc.TOKENEK[token_ki]["cim"].lower() not in cimek or token_be == token_ki):
        raise Hiba("Token pair does not match the pool.")
    return p


def _hatarido():
    return str(int(time.time()) + config.TX_HATARIDO_MP)


def _approve_ha_kell(tarca, token, egyseg, kolto):
    """Csak akkor kuld approve tranzakciot, ha a meglevo allowance nem eleg."""
    if allowance(token, tarca, kolto) >= int(egyseg):
        return None
    return circle_kliens.contract_tx(
        tarca, vc.TOKENEK[token]["cim"], "approve(address,uint256)", [kolto, egyseg],
        f"{token} approve")


# ---------- Hibakezeles / fejlecek ----------

@app.errorhandler(Hiba)
def _hiba(e):
    return jsonify({"ok": False, "uzenet": str(e)}), e.statusz


@app.errorhandler(404)
def _404(e):
    return jsonify({"ok": False, "uzenet": "Not found"}), 404


@app.errorhandler(Exception)
def _altalanos_hiba(e):
    naplo.error("kezeletlen hiba: %s\n%s", e, traceback.format_exc())
    szoveg = str(e)
    # a lancrol / Circle-tol jovo hibak hasznosak a felhasznalonak, a tobbi nem
    if any(k in szoveg for k in ("tranzakcio", "idotullepes", "Slippage", "revert", "Circle")):
        return jsonify({"ok": False, "uzenet": f"Transaction failed: {szoveg[:200]}"}), 502
    return jsonify({"ok": False, "uzenet": "Internal error - see server log."}), 500


@app.after_request
def _fejlecek(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "public, max-age=86400"
    else:
        resp.headers["Cache-Control"] = "no-store"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src *; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    return resp


# ---------- API ----------

@app.route("/healthz")
def healthz():
    try:
        blokk = lanc.blokkszam()
        return jsonify({"ok": True, "halozat": config.HALOZAT, "blokk": blokk,
                        "dex": vc.DEX_CIM, "szunetel": dex_szunetel()})
    except Exception as e:
        return jsonify({"ok": False, "uzenet": str(e)[:200]}), 503


@app.route("/api/allapot")
def allapot():
    most = time.time()
    if _allapot_cache["adat"] and most - _allapot_cache["ido"] < ALLAPOT_CACHE_MP:
        adat = dict(_allapot_cache["adat"])
    else:
        egyenlegek = {}
        if config.MEGRENDELO_CIM and config.ADMIN_TOKEN:
            egyenlegek = {t: token_egyenleg(t, config.MEGRENDELO_CIM) for t in vc.TOKENEK}
        adat = {
            "halozat": {"nev": config.HALOZAT_NEV, "kulcs": config.HALOZAT,
                        "chainId": config.CHAIN_ID, "chainIdHex": hex(config.CHAIN_ID),
                        "rpc": config.RPC_URL, "explorer": config.EXPLORER,
                        "mainnet": config.MAINNET},
            "dex": vc.DEX_CIM, "dex_abi": vc.DEX_ABI_JS, "erc20_abi": vc.ERC20_ABI_JS,
            "explorer": config.EXPLORER_TX, "explorer_cim": config.EXPLORER_CIM,
            "szunetel": dex_szunetel(),
            "tokenek": vc.TOKENEK, "poolok": poolok_lekerese(),
            "circle_mod": bool(config.ADMIN_TOKEN and config.MEGRENDELO_CIM),
            "megrendelo": {"cim": config.MEGRENDELO_CIM if config.ADMIN_TOKEN else None,
                           "egyenlegek": egyenlegek},
            "alap_slippage_bps": config.ALAP_SLIPPAGE_BPS,
            "max_slippage_bps": config.MAX_SLIPPAGE_BPS,
            "hatarido_mp": config.TX_HATARIDO_MP,
        }
        _allapot_cache.update(ido=most, adat=adat)
    adat["elozmenyek"] = _elozmeny["sorok"][::-1]
    return jsonify(adat)


@app.route("/api/arjegyzes", methods=["POST"])
def arjegyzes():
    d = _json()
    pid = _pool_id(d)
    token_be, token_ki = _token(d, "token_be"), _token(d, "token_ki")
    _pool_tokenek(pid, token_be, token_ki)
    egyseg_be = _egyseg(token_be, d.get("mennyiseg"))
    try:
        ki_egyseg = dex.functions.getQuote(
            pid, Web3.to_checksum_address(vc.TOKENEK[token_be]["cim"]), int(egyseg_be)).call()
    except Exception as e:
        raise Hiba("No quote: " + ("empty pool" if "EmptyPool" in str(e) or "11077125" in str(e)
                                   else "contract rejected the request"))
    return jsonify({"ok": True, "ki_egyseg": str(ki_egyseg),
                    "ki_mennyiseg": vc.egysegbol(token_ki, ki_egyseg)})


@app.route("/api/valtas", methods=["POST"])
def valtas():
    _admin_ellenorzes()
    d = _json()
    pid = _pool_id(d)
    token_be, token_ki = _token(d, "token_be"), _token(d, "token_ki")
    _pool_tokenek(pid, token_be, token_ki)
    egyseg_be = _egyseg(token_be, d.get("mennyiseg"))
    bps = _slippage_bps(d)
    if dex_szunetel():
        raise Hiba("The DEX is paused.", 409)
    tarca = config.MEGRENDELO_CIM
    egyenleg = token_egyenleg(token_be, tarca)
    if egyenleg is not None and egyenleg < vc.egysegbol(token_be, egyseg_be):
        raise Hiba(f"Insufficient {token_be} balance in the server wallet.")
    with zar:
        ki_egyseg = dex.functions.getQuote(
            pid, Web3.to_checksum_address(vc.TOKENEK[token_be]["cim"]), int(egyseg_be)).call()
        min_ki = int(ki_egyseg) * (10_000 - bps) // 10_000
        _approve_ha_kell(tarca, token_be, egyseg_be, vc.DEX_CIM)
        tx = circle_kliens.contract_tx(
            tarca, vc.DEX_CIM, "swap(uint256,address,uint256,uint256,uint256)",
            [str(pid), vc.TOKENEK[token_be]["cim"], egyseg_be, str(min_ki), _hatarido()], "swap")
    kapott = vc.egysegbol(token_ki, ki_egyseg)
    seged.esemeny("Swap", f"{d.get('mennyiseg')} {token_be} -> ~{kapott} {token_ki} (Circle) {tx}")
    _allapot_cache["ido"] = 0
    return jsonify({"ok": True, "uzenet": f"Swap done: {d.get('mennyiseg')} {token_be} "
                    f"-> ~{round(kapott, 8)} {token_ki} (min {vc.egysegbol(token_ki, min_ki)})",
                    "tx": config.EXPLORER_TX + tx})


@app.route("/api/likviditas", methods=["POST"])
def likviditas():
    _admin_ellenorzes()
    d = _json()
    pid = _pool_id(d)
    bps = _slippage_bps(d)
    p = dex.functions.pools(pid).call()
    ta, tb = vc.token_nev(p[0]), vc.token_nev(p[1])
    if ta not in vc.TOKENEK or tb not in vc.TOKENEK:
        raise Hiba("Unsupported pool tokens.")
    ea, eb = _egyseg(ta, d.get("mennyiseg_a")), _egyseg(tb, d.get("mennyiseg_b"))
    if dex_szunetel():
        raise Hiba("The DEX is paused.", 409)
    tarca = config.MEGRENDELO_CIM
    min_a = int(ea) * (10_000 - bps) // 10_000
    min_b = int(eb) * (10_000 - bps) // 10_000
    with zar:
        _approve_ha_kell(tarca, ta, ea, vc.DEX_CIM)
        _approve_ha_kell(tarca, tb, eb, vc.DEX_CIM)
        tx = circle_kliens.contract_tx(
            tarca, vc.DEX_CIM,
            "addLiquidity(uint256,uint256,uint256,uint256,uint256,uint256)",
            [str(pid), ea, eb, str(min_a), str(min_b), _hatarido()], "add liquidity")
    seged.esemeny("Liquidity", f"+{d.get('mennyiseg_a')} {ta} / {d.get('mennyiseg_b')} {tb} (Circle) {tx}")
    _allapot_cache["ido"] = 0
    return jsonify({"ok": True, "uzenet": f"Liquidity added (up to {d.get('mennyiseg_a')} {ta}"
                    f" + {d.get('mennyiseg_b')} {tb}; the pool ratio decides the exact amounts)",
                    "tx": config.EXPLORER_TX + tx})


@app.route("/api/likviditas_kivet", methods=["POST"])
def likviditas_kivet():
    _admin_ellenorzes()
    d = _json()
    pid = _pool_id(d)
    bps = _slippage_bps(d)
    tarca = config.MEGRENDELO_CIM
    sajat = int(dex.functions.myShares(pid, Web3.to_checksum_address(tarca)).call())
    try:
        szazalek = float(d.get("szazalek", 100))
    except (TypeError, ValueError):
        raise Hiba("szazalek must be a number.")
    if not 0 < szazalek <= 100:
        raise Hiba("szazalek must be between 0 and 100.")
    shares = sajat * int(szazalek * 100) // 10_000
    if shares <= 0:
        raise Hiba("No LP shares to remove.")
    p = dex.functions.pools(pid).call()
    out_a = shares * p[2] // p[4]
    out_b = shares * p[3] // p[4]
    with zar:
        tx = circle_kliens.contract_tx(
            tarca, vc.DEX_CIM, "removeLiquidity(uint256,uint256,uint256,uint256,uint256)",
            [str(pid), str(shares), str(out_a * (10_000 - bps) // 10_000),
             str(out_b * (10_000 - bps) // 10_000), _hatarido()], "remove liquidity")
    seged.esemeny("Liquidity", f"-{szazalek}% shares pool #{pid} (Circle) {tx}")
    _allapot_cache["ido"] = 0
    return jsonify({"ok": True, "uzenet": f"Removed {szazalek}% of LP shares from pool #{pid}",
                    "tx": config.EXPLORER_TX + tx})


@app.route("/api/lp", methods=["POST"])
def lp():
    """Egy cim LP-reszesedese a poolokban (csak olvasas, a MetaMask modhoz)."""
    d = _json()
    cim = str(d.get("cim", ""))
    if not Web3.is_address(cim):
        raise Hiba("Invalid address.")
    ki = []
    for p in poolok_lekerese():
        sh = int(dex.functions.myShares(p["id"], Web3.to_checksum_address(cim)).call())
        ossz = int(p["shares"])
        ki.append({"id": p["id"], "shares": str(sh),
                   "resz": (sh / ossz) if ossz else 0,
                   "ertekA": p["keszletA"] * sh / ossz if ossz else 0,
                   "ertekB": p["keszletB"] * sh / ossz if ossz else 0})
    return jsonify({"ok": True, "poolok": ki})


@app.route("/")
def fooldal():
    return HTML


HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ARC Swap</title>
<script src="/static/ethers-5.7.2.umd.min.js"></script>
<style>
:root{
 --bg:#eaf5ee;--bg2:#f7fbf8;--card:#ffffff;--inset:#f2f8f4;--border:#d3e6da;
 --text:#12291d;--muted:#5e7d6c;--faint:#93aa9d;
 --green:#1eb45a;--green2:#149048;--greenl:#dff6e7;--greenb:#b6e6c8;
 --red:#e64545;--red2:#c62f2f;--redl:#ffe3e3;--redb:#f5c0c0;
 --amber:#b26a00;--amberl:#fff3dc;
 --grad:linear-gradient(135deg,#25c766 0%,#149048 100%);
}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;color:var(--text);
 font-family:"Inter",-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;
 background:
   radial-gradient(900px 420px at 80% -10%,rgba(37,199,102,.18),transparent 60%),
   radial-gradient(760px 400px at 6% 4%,rgba(230,69,69,.10),transparent 55%),
   var(--bg);}
a{color:var(--green2);text-decoration:none}a:hover{text-decoration:underline}
.col{max-width:500px;margin:0 auto;padding:20px 16px 44px;display:flex;
 flex-direction:column;gap:16px}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px}
.brand{display:flex;align-items:center;gap:11px}
.logo{width:40px;height:40px;border-radius:12px;background:var(--grad);display:grid;
 place-items:center;font-weight:800;color:#fff;font-size:19px;
 box-shadow:0 8px 20px rgba(30,180,90,.4)}
.brand b{font-size:19px;letter-spacing:.2px}
.brand span{display:block;font-size:11.5px;color:var(--muted);margin-top:-2px}
.net{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--green2);
 background:var(--greenl);border:1px solid var(--greenb);border-radius:20px;padding:6px 13px;font-weight:600}
.net.test{color:var(--amber);background:var(--amberl);border-color:#f0d9a8}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);
 box-shadow:0 0 0 3px rgba(30,180,90,.2)}
.card{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:18px;
 box-shadow:0 10px 30px rgba(20,80,45,.08)}
.card h2{font-size:12px;margin:0 0 13px;color:var(--muted);text-transform:uppercase;
 letter-spacing:.09em;font-weight:700}
.banner{background:var(--amberl);border:1px solid #f0d9a8;color:var(--amber);border-radius:14px;
 padding:11px 14px;font-size:13px;font-weight:600;display:none}
.banner.red{background:var(--redl);border-color:var(--redb);color:var(--red2)}
.swaphead{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.swaphead h1{font-size:20px;margin:0}
.modewrap{display:flex;background:var(--inset);border:1px solid var(--border);
 border-radius:11px;padding:3px}
.modebtn{border:none;background:transparent;color:var(--muted);font:inherit;font-size:12px;
 font-weight:700;padding:6px 12px;border-radius:8px;cursor:pointer}
.modebtn.aktiv{background:var(--grad);color:#fff}
.modebtn:disabled{opacity:.4;cursor:not-allowed}
.tokbox{border-radius:16px;padding:14px 15px;margin:7px 0;border:1.5px solid transparent}
.tokbox.be{background:var(--redl);border-color:var(--redb)}
.tokbox.ki{background:var(--greenl);border-color:var(--greenb)}
.tokbox .fej{display:flex;justify-content:space-between;font-size:12px;margin-bottom:9px;font-weight:600}
.tokbox.be .fej .cimke{color:var(--red2)}
.tokbox.ki .fej .cimke{color:var(--green2)}
.tokbox .fej .bal{color:var(--muted);font-weight:500}
.maxbtn{background:var(--red);color:#fff;border:none;border-radius:6px;
 font:inherit;font-size:10px;font-weight:700;padding:2px 7px;cursor:pointer;margin-left:6px}
.tokrow{display:flex;align-items:center;gap:10px}
.amt{flex:1;min-width:0;background:transparent;border:none;color:var(--text);
 font-size:28px;font-weight:700;outline:none;font-family:inherit}
.amt::placeholder{color:var(--faint)}
.amt[readonly]{color:var(--green2)}
.tokpick{display:flex;align-items:center;gap:8px;background:var(--card);
 border:1px solid var(--border);border-radius:30px;padding:5px 11px 5px 6px;cursor:pointer;
 font-weight:700;font-size:14px;white-space:nowrap;box-shadow:0 2px 6px rgba(20,80,45,.06)}
.tokpick:hover{border-color:var(--green)}
.tokpickwrap{position:relative}
.tokpick select{position:absolute;opacity:0;inset:0;width:100%;cursor:pointer}
.ic{width:27px;height:27px;border-radius:50%;display:grid;place-items:center;
 font-size:11px;font-weight:800;color:#fff}
.ic-USDC{background:linear-gradient(135deg,#4c8dff,#2f6fe0)}
.ic-EURC{background:linear-gradient(135deg,#25c766,#149048)}
.ic-CIRBTC{background:linear-gradient(135deg,#ffab4c,#f5852b)}
.caret{color:var(--muted);font-size:10px}
.flipwrap{display:flex;justify-content:center;height:0;position:relative;z-index:2}
.flip{width:40px;height:40px;margin-top:-14px;border-radius:13px;background:var(--grad);
 border:4px solid var(--card);color:#fff;font-size:17px;cursor:pointer;
 display:grid;place-items:center;transition:transform .25s;box-shadow:0 6px 16px rgba(30,180,90,.35)}
.flip:hover{transform:rotate(180deg)}
.rate{display:flex;justify-content:space-between;align-items:center;font-size:13px;
 color:var(--muted);padding:12px 4px 4px;flex-wrap:wrap;gap:6px}
.rate b{color:var(--text);font-weight:700}
.impact{font-size:11.5px;color:var(--red2)}
.impact.warn{font-weight:800}
.settings{display:flex;gap:10px;align-items:center;font-size:12px;color:var(--muted);padding:6px 4px 0;flex-wrap:wrap}
.settings input{width:62px;background:var(--inset);border:1px solid var(--border);border-radius:8px;
 padding:5px 7px;font:inherit;font-size:12px;color:var(--text)}
.cta{width:100%;margin-top:13px;border:none;border-radius:15px;padding:16px;
 font:inherit;font-size:16px;font-weight:800;color:#fff;cursor:pointer;
 background:var(--grad);box-shadow:0 12px 26px rgba(30,180,90,.32)}
.cta:hover{filter:brightness(1.05)}.cta:disabled{opacity:.5;cursor:default;box-shadow:none}
.cta.wallet{background:linear-gradient(135deg,#ef5b5b,#c62f2f);
 box-shadow:0 12px 26px rgba(230,69,69,.3)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:var(--faint);text-align:left;font-weight:700;padding:6px 7px;
 border-bottom:1px solid var(--border);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em}
td{padding:8px 7px;border-bottom:1px solid #eef4f0}tr:last-child td{border-bottom:none}
.pill{display:inline-flex;align-items:center;gap:5px;background:var(--inset);
 border:1px solid var(--border);border-radius:20px;padding:2px 9px;font-size:11.5px;font-weight:700}
.mono{font-family:ui-monospace,Menlo,monospace}
.zold{color:var(--green2);font-weight:700}.piros{color:var(--red2);font-weight:700}.muted{color:var(--muted)}
.baljelek{display:flex;flex-wrap:wrap;gap:9px}
.bchip{display:flex;align-items:center;gap:9px;background:var(--inset);
 border:1px solid var(--border);border-radius:13px;padding:9px 12px;flex:1;min-width:120px}
.bchip .v{font-weight:800}.bchip .t{font-size:11px;color:var(--muted)}
#naplo{background:#0c2016;border:1px solid var(--border);border-radius:12px;padding:11px;
 font-family:ui-monospace,Menlo,monospace;font-size:11px;max-height:170px;overflow:auto;
 white-space:pre-wrap;color:#bfe8cf;line-height:1.7;word-break:break-all}
.lik .row{display:flex;gap:9px;flex-wrap:wrap;align-items:flex-end}
.lik label{display:block;font-size:11px;color:var(--muted);margin-bottom:4px;font-weight:600}
.lik input,.lik select{background:var(--inset);border:1px solid var(--border);color:var(--text);
 border-radius:9px;padding:9px 10px;font:inherit;font-size:13px}
.lik input{width:92px}
.lik .go{background:var(--grad);border:none;color:#fff;border-radius:9px;padding:9px 16px;
 font:inherit;font-size:13px;font-weight:700;cursor:pointer}
.lik .go.sec{background:linear-gradient(135deg,#ef5b5b,#c62f2f)}
.lik .hint{font-size:11px;color:var(--muted);margin-top:8px}
.foot{color:var(--faint);font-size:11.5px;text-align:center;line-height:1.6}
</style></head><body>
<div class="col">

 <div class="top">
  <div class="brand"><div class="logo">◈</div>
   <div><b>ARC Swap</b><span id="subtitle">AMM DEX · Arc</span></div></div>
  <div class="net" id="netpill"><span class="dot"></span><span id="netname">Arc</span></div>
 </div>

 <div id="banner" class="banner"></div>

 <!-- SWAP -->
 <div class="card">
  <div class="swaphead"><h1>Swap</h1>
   <div class="modewrap">
    <button id="modMM" class="modebtn aktiv" onclick="modValt('mm')">MetaMask</button>
    <button id="modCircle" class="modebtn" onclick="modValt('circle')" title="Server-side Circle wallet (admin only)">Circle</button></div></div>

  <div class="tokbox be">
   <div class="fej"><span class="cimke">You pay</span>
    <span class="bal">Balance: <span id="balFrom">–</span><button class="maxbtn" onclick="maxBe()">MAX</button></span></div>
   <div class="tokrow">
    <input id="mennyiseg" class="amt" value="" inputmode="decimal" placeholder="0" oninput="arjegyzesKesleltetve()">
    <div class="tokpickwrap"><div class="tokpick"><span id="icFrom" class="ic"></span>
     <span id="lblFrom">–</span><span class="caret">▼</span>
     <select id="selFrom" onchange="fromValt()"></select></div></div></div>
  </div>

  <div class="flipwrap"><button class="flip" onclick="flip()" title="Reverse direction">⇅</button></div>

  <div class="tokbox ki">
   <div class="fej"><span class="cimke">You receive (est.)</span>
    <span class="bal">Balance: <span id="balTo">–</span></span></div>
   <div class="tokrow">
    <input id="kimenet" class="amt" value="" readonly placeholder="0">
    <div class="tokpickwrap"><div class="tokpick"><span id="icTo" class="ic"></span>
     <span id="lblTo">–</span><span class="caret">▼</span>
     <select id="selTo" onchange="toValt()"></select></div></div></div>
  </div>

  <div class="rate"><span id="rateTxt">Enter an amount…</span>
   <span id="impactTxt" class="impact"></span></div>
  <div class="settings">
   <span>Max slippage</span><input id="slip" value="0.5" inputmode="decimal" onchange="slipValt()"><span>%</span>
   <span id="minOutTxt" class="muted"></span>
  </div>

  <button id="cta" class="cta" onclick="valtas()">Swap</button>
  <div id="mmAllapot" class="muted" style="font-size:11.5px;text-align:center;margin-top:9px"></div>
 </div>

 <!-- POOLS -->
 <div class="card"><h2>Liquidity pools</h2>
  <table><thead><tr><th>Pair</th><th>Reserves</th><th>Mid-price</th></tr></thead>
  <tbody id="poolok"></tbody></table></div>

 <!-- BALANCES -->
 <div class="card"><h2 id="balTitle">Balances · your wallet</h2>
  <div class="baljelek" id="egyenlegek"></div>
  <div class="muted" style="font-size:11px;margin-top:10px" id="mCim"></div></div>

 <!-- LIQUIDITY -->
 <div class="card lik"><h2>Liquidity</h2>
  <div class="row">
   <div><label>Pool</label><select id="likPool" onchange="lpFrissit()"></select></div>
   <div><label id="likLblA">A</label><input id="likA" value=""></div>
   <div><label id="likLblB">B</label><input id="likB" value=""></div>
   <button class="go" onclick="likviditas()">Add</button></div>
  <div class="hint">Amounts are upper bounds: the pool ratio decides how much of each is actually used.
   The first deposit into an empty pool sets the price.</div>
  <div class="row" style="margin-top:12px">
   <div><label>Your LP position</label><div id="lpPos" class="muted" style="font-size:12.5px;padding:6px 0">–</div></div>
   <div><label>Remove %</label><input id="likPct" value="100"></div>
   <button class="go sec" onclick="likviditasKivet()">Remove</button></div></div>

 <!-- RECENT SWAPS -->
 <div class="card"><h2>Recent swaps · on-chain</h2>
  <table><thead><tr><th>Block</th><th>Trader</th><th>In</th><th>Out</th></tr></thead>
  <tbody id="elozmenyek"></tbody></table></div>

 <!-- LOG -->
 <div class="card"><h2>Log</h2><div id="naplo">Ready.</div></div>

 <div class="foot">Constant-product AMM · 0.3% fee goes to liquidity providers · unaudited code, use at your own risk<br>
  DEX: <a id="dexlink" class="mono" target="_blank" rel="noopener">…</a></div>
</div>

<script>
let ALLAPOT=null, MOD='mm', MM_CIM=null, MM_SIGNER=null, MM_PROVIDER=null;
let FROM=null, TO=null, TOKLISTA=[], MM_EGYENLEGEK={}, SLIP_BPS=50, ADMIN_TOKEN=null;
const $=id=>document.getElementById(id);
function log(t){$('naplo').textContent=(new Date()).toLocaleTimeString()+"  "+t+"\n"+$('naplo').textContent;}
const DEX_ERRORS=["error NotOwner()","error ZeroAddress()","error SameToken()","error PoolExists()",
 "error PoolCreationRestricted()","error IsPaused()","error Reentrancy()","error Expired()","error ZeroAmount()",
 "error InsufficientLiquidityMinted()","error InsufficientAmountA()","error InsufficientAmountB()",
 "error InsufficientShares()","error BadTokenIn()","error EmptyPool()","error Slippage()","error TransferFailed()",
 "error NativeValueNotAccepted()","error NoPool()"];
const FRIENDLY={Slippage:'price moved beyond your slippage limit – try again or raise slippage',
 Expired:'transaction deadline passed – try again',IsPaused:'the DEX is paused by the operator',
 EmptyPool:'this pool has no liquidity yet',InsufficientAmountA:'pool ratio changed – raise slippage',
 InsufficientAmountB:'pool ratio changed – raise slippage',InsufficientShares:'not enough LP shares',
 InsufficientLiquidityMinted:'first deposit too small'};
function hibaSzoveg(e){
 const n=e&&(e.errorName||(e.error&&e.error.errorName)||(e.data&&e.data.errorName));
 if(n&&FRIENDLY[n])return n+': '+FRIENDLY[n]; if(n)return n;
 const m=(e&&(e.reason||(e.error&&e.error.message)||e.message||String(e)))||'error';
 return m.length>220?m.slice(0,220)+'…':m;}
function dexAbi(){return ALLAPOT.dex_abi.concat(DEX_ERRORS);}
function deadline(){return Math.floor(Date.now()/1000)+(ALLAPOT.hatarido_mp||600);}
function fmt(x,d){const n=Number(x);if(!isFinite(n))return '–';return n.toFixed(d).replace(/\.?0+$/,'')||'0';}
function slipValt(){let v=parseFloat(String($('slip').value).replace(',','.'));
 const max=(ALLAPOT?ALLAPOT.max_slippage_bps:1000)/100;
 if(!(v>0))v=(ALLAPOT?ALLAPOT.alap_slippage_bps:50)/100; if(v>max)v=max;
 $('slip').value=v;SLIP_BPS=Math.round(v*100);arjegyzes();}

function setIc(el,tok){el.className='ic ic-'+tok;el.textContent=tok==='CIRBTC'?'₿':tok[0];}
function poolKereses(a,b){
 if(!ALLAPOT)return null;
 for(const p of ALLAPOT.poolok){
  if((p.tokenA===a&&p.tokenB===b)||(p.tokenA===b&&p.tokenB===a))return{id:p.id};}
 return null;}
function parok(tok){const ki=new Set();
 for(const p of ALLAPOT.poolok){if(p.tokenA===tok)ki.add(p.tokenB);if(p.tokenB===tok)ki.add(p.tokenA);}
 return [...ki];}
function egyenlegek(){return MOD==='mm'?MM_EGYENLEGEK:(ALLAPOT?ALLAPOT.megrendelo.egyenlegek:{});}

function feltoltSelectek(){
 const sf=$('selFrom');sf.innerHTML='';
 TOKLISTA.forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=t;sf.appendChild(o);});
 sf.value=FROM;
 const st=$('selTo');st.innerHTML='';
 parok(FROM).forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=t;st.appendChild(o);});
 if(!parok(FROM).includes(TO))TO=parok(FROM)[0];
 st.value=TO;
 setIc($('icFrom'),FROM);$('lblFrom').textContent=FROM;
 setIc($('icTo'),TO);$('lblTo').textContent=TO;frissEgyenleg();}
function frissEgyenleg(){const e=egyenlegek();
 $('balFrom').textContent=(e[FROM]!=null?fmt(e[FROM],8):'–')+' '+FROM;
 $('balTo').textContent=(e[TO]!=null?fmt(e[TO],8):'–')+' '+TO;
 $('egyenlegek').innerHTML=Object.keys(ALLAPOT?ALLAPOT.tokenek:{}).map(t=>
  `<div class="bchip"><span class="ic ic-${t}">${t==='CIRBTC'?'₿':t[0]}</span>`+
  `<div><div class="v">${e[t]!=null?fmt(e[t],8):'–'}</div><div class="t">${t}</div></div></div>`).join('');
 const cim=MOD==='mm'?MM_CIM:(ALLAPOT&&ALLAPOT.megrendelo.cim);
 $('balTitle').textContent=MOD==='mm'?'Balances · your wallet':'Balances · server (Circle) wallet';
 $('mCim').textContent=cim?('Address: '+cim):(MOD==='mm'?'Connect MetaMask to see balances.':'');}
function fromValt(){FROM=$('selFrom').value;if(!parok(FROM).includes(TO))TO=parok(FROM)[0];feltoltSelectek();arjegyzes();}
function toValt(){TO=$('selTo').value;feltoltSelectek();arjegyzes();}
function flip(){const a=FROM;FROM=TO;TO=a;if(!parok(FROM).includes(TO))TO=parok(FROM)[0];feltoltSelectek();arjegyzes();}
function maxBe(){const e=egyenlegek()[FROM];if(e){$('mennyiseg').value=e;arjegyzes();}}

function modValt(m){
 if(m==='circle'){
  if(!ALLAPOT||!ALLAPOT.circle_mod){log('Circle mode is disabled on this server.');return;}
  if(!ADMIN_TOKEN){const t=prompt('Admin token for the server-side Circle wallet:');if(!t)return;
   ADMIN_TOKEN=t;try{sessionStorage.setItem('adminToken',t);}catch(e){}}
 }
 MOD=m;
 $('modCircle').classList.toggle('aktiv',m==='circle');
 $('modMM').classList.toggle('aktiv',m==='mm');ctaFrissit();frissEgyenleg();lpFrissit();
 if(m==='mm'&&!MM_CIM)mmCsatlakozas();}
function ctaFrissit(){const b=$('cta');
 if(MOD==='mm'&&!MM_CIM){b.textContent='Connect MetaMask';b.classList.add('wallet');}
 else{b.textContent=(ALLAPOT&&ALLAPOT.szunetel)?'Paused':'Swap';b.classList.remove('wallet');}
 b.disabled=!!(ALLAPOT&&ALLAPOT.szunetel&&MM_CIM);}

async function mmCsatlakozas(){
 if(!window.ethereum){$('mmAllapot').textContent='No MetaMask in this browser.';return;}
 try{
  const h=ALLAPOT.halozat;
  MM_PROVIDER=new ethers.providers.Web3Provider(window.ethereum,'any');
  await MM_PROVIDER.send('eth_requestAccounts',[]);
  try{await MM_PROVIDER.send('wallet_switchEthereumChain',[{chainId:h.chainIdHex}]);}
  catch(err){const c=err&&(err.code||(err.data&&err.data.originalError&&err.data.originalError.code));
   if(c===4902){await MM_PROVIDER.send('wallet_addEthereumChain',[{chainId:h.chainIdHex,chainName:h.nev,
    rpcUrls:[h.rpc],nativeCurrency:{name:'USDC',symbol:'USDC',decimals:18},
    blockExplorerUrls:[h.explorer]}]);}else throw err;}
  const net=await MM_PROVIDER.getNetwork();
  if(net.chainId!==h.chainId)throw new Error('wrong network in MetaMask (chain '+net.chainId+', expected '+h.chainId+')');
  MM_SIGNER=MM_PROVIDER.getSigner();MM_CIM=await MM_SIGNER.getAddress();
  $('mmAllapot').textContent='Connected: '+MM_CIM.slice(0,6)+'…'+MM_CIM.slice(-4)+' · '+h.nev;
  ctaFrissit();log('MetaMask connected: '+MM_CIM);
  if(window.ethereum.on){window.ethereum.on('accountsChanged',()=>{MM_CIM=null;MM_SIGNER=null;mmCsatlakozas();});
   window.ethereum.on('chainChanged',()=>location.reload());}
  await mmEgyenlegek();lpFrissit();
 }catch(e){$('mmAllapot').textContent='MetaMask error: '+hibaSzoveg(e);}}

async function mmEgyenlegek(){
 if(!MM_CIM||!MM_PROVIDER)return;
 const ki={};
 for(const [t,info] of Object.entries(ALLAPOT.tokenek)){
  try{const c=new ethers.Contract(info.cim,ALLAPOT.erc20_abi,MM_PROVIDER);
   ki[t]=ethers.utils.formatUnits(await c.balanceOf(MM_CIM),info.tizedes);}catch(e){ki[t]=null;}}
 MM_EGYENLEGEK=ki;frissEgyenleg();}

let idozito=null;
function arjegyzesKesleltetve(){clearTimeout(idozito);idozito=setTimeout(arjegyzes,350);}
async function arjegyzes(){
 if(!ALLAPOT||!FROM||!TO)return;
 const pool=poolKereses(FROM,TO);const m=String($('mennyiseg').value).replace(',','.');
 $('minOutTxt').textContent='';
 if(!pool){$('rateTxt').textContent='No pool for this pair.';$('kimenet').value='';return;}
 if(!m||!(parseFloat(m)>0)){$('rateTxt').textContent='Enter an amount…';$('kimenet').value='';$('impactTxt').textContent='';return;}
 try{
  const r=await fetch('/api/arjegyzes',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({pool_id:pool.id,token_be:FROM,token_ki:TO,mennyiseg:m})});
  const d=await r.json();
  if(d.ok){const ki=Number(d.ki_mennyiseg);
   $('kimenet').value=fmt(ki,8);
   $('cta').dataset.kiEgyseg=d.ki_egyseg;$('cta').dataset.pool=pool.id;
   const egys=ki/parseFloat(m);
   $('rateTxt').innerHTML='1 '+FROM+' ≈ <b>'+fmt(egys,8)+'</b> '+TO;
   const p=ALLAPOT.poolok.find(x=>x.id===pool.id);
   const kozep=(p.tokenA===FROM)?p.arfolyam:(p.arfolyam?1/p.arfolyam:0);
   const hatas=kozep?(1-egys/kozep)*100:0;
   const it=$('impactTxt');it.textContent=hatas>0.01?('price impact −'+hatas.toFixed(2)+'%'):'';
   it.classList.toggle('warn',hatas>5);$('cta').dataset.impact=hatas;
   const minKi=ethers.BigNumber.from(d.ki_egyseg).mul(10000-SLIP_BPS).div(10000);
   $('minOutTxt').textContent='min. received: '+fmt(ethers.utils.formatUnits(minKi,ALLAPOT.tokenek[TO].tizedes),8)+' '+TO;
  }else{$('rateTxt').textContent=d.uzenet;$('kimenet').value='';$('impactTxt').textContent='';}
 }catch(e){$('rateTxt').textContent='Quote error: '+e.message;}}

function fejlecek(){const h={'Content-Type':'application/json'};if(ADMIN_TOKEN)h['X-Admin-Token']=ADMIN_TOKEN;return h;}
async function apiPost(ut,adat){
 const r=await fetch(ut,{method:'POST',headers:fejlecek(),body:JSON.stringify(adat)});
 let d;try{d=await r.json();}catch(e){d={ok:false,uzenet:'HTTP '+r.status};}
 if(r.status===403){ADMIN_TOKEN=null;try{sessionStorage.removeItem('adminToken');}catch(e){}}
 return d;}
async function approveHaKell(tokenInfo,osszeg){
 const c=new ethers.Contract(tokenInfo.cim,ALLAPOT.erc20_abi,MM_SIGNER);
 const a=await c.allowance(MM_CIM,ALLAPOT.dex);
 if(a.gte(osszeg))return;
 log('MetaMask: approving '+(tokenInfo.nev||'token')+'…');
 await (await c.approve(ALLAPOT.dex,osszeg)).wait();}

async function valtas(){
 if(MOD==='mm'&&!MM_CIM){await mmCsatlakozas();return;}
 const pool=poolKereses(FROM,TO);if(!pool)return;const m=String($('mennyiseg').value).replace(',','.');
 if(!(parseFloat(m)>0)){log('Enter an amount first.');return;}
 const hatas=parseFloat($('cta').dataset.impact||'0');
 if(hatas>15&&!confirm('Price impact is '+hatas.toFixed(1)+'%. You will receive far less than the mid-price. Continue?'))return;
 const btns=document.querySelectorAll('button');btns.forEach(b=>b.disabled=true);
 try{
  if(MOD==='circle'){
   log('Swap (Circle): '+m+' '+FROM+' → '+TO+' … (20–60s)');
   const d=await apiPost('/api/valtas',{pool_id:pool.id,token_be:FROM,token_ki:TO,mennyiseg:m,slippage_bps:SLIP_BPS});
   log((d.ok?'✓ ':'✗ ')+d.uzenet+(d.tx?('  '+d.tx):''));
  }else{
   if(!MM_SIGNER){await mmCsatlakozas();if(!MM_SIGNER)throw new Error('no MetaMask');}
   const t=ALLAPOT.tokenek[FROM];
   const be=ethers.utils.parseUnits(m,t.tizedes);
   const kiE=ethers.BigNumber.from($('cta').dataset.kiEgyseg||'0');
   if(kiE.isZero())throw new Error('request a quote first');
   const minKi=kiE.mul(10000-SLIP_BPS).div(10000);
   await approveHaKell({...t,nev:FROM},be);
   log('MetaMask: signing swap (min '+fmt(ethers.utils.formatUnits(minKi,ALLAPOT.tokenek[TO].tizedes),8)+' '+TO+')…');
   const dx=new ethers.Contract(ALLAPOT.dex,dexAbi(),MM_SIGNER);
   const rc=await (await dx.swap(pool.id,t.cim,be,minKi,deadline())).wait();
   log('✓ Swap done (MetaMask). '+ALLAPOT.explorer+rc.transactionHash);
  }
 }catch(e){log('✗ '+hibaSzoveg(e));}
 btns.forEach(b=>b.disabled=false);refresh();}

async function likviditas(){
 const pid=parseInt($('likPool').value);const a=String($('likA').value).replace(',','.'),b=String($('likB').value).replace(',','.');
 if(!(parseFloat(a)>0)||!(parseFloat(b)>0)){log('Enter both amounts.');return;}
 if(MOD==='mm'&&!MM_CIM){await mmCsatlakozas();if(!MM_CIM)return;}
 const btns=document.querySelectorAll('button');btns.forEach(x=>x.disabled=true);
 try{
  if(MOD==='circle'){
   log('Adding liquidity (Circle)… (30–90s)');
   const d=await apiPost('/api/likviditas',{pool_id:pid,mennyiseg_a:a,mennyiseg_b:b,slippage_bps:SLIP_BPS});
   log((d.ok?'✓ ':'✗ ')+d.uzenet+(d.tx?('  '+d.tx):''));
  }else{
   const p=ALLAPOT.poolok.find(x=>x.id===pid);
   const tA=ALLAPOT.tokenek[p.tokenA],tB=ALLAPOT.tokenek[p.tokenB];
   const eA=ethers.utils.parseUnits(a,tA.tizedes),eB=ethers.utils.parseUnits(b,tB.tizedes);
   const minA=eA.mul(10000-SLIP_BPS).div(10000),minB=eB.mul(10000-SLIP_BPS).div(10000);
   await approveHaKell({...tA,nev:p.tokenA},eA);await approveHaKell({...tB,nev:p.tokenB},eB);
   log('MetaMask: adding liquidity…');
   const dx=new ethers.Contract(ALLAPOT.dex,dexAbi(),MM_SIGNER);
   const rc=await (await dx.addLiquidity(pid,eA,eB,minA,minB,deadline())).wait();
   log('✓ Liquidity added (MetaMask). '+ALLAPOT.explorer+rc.transactionHash);
  }
 }catch(e){log('✗ '+hibaSzoveg(e));}
 btns.forEach(x=>x.disabled=false);refresh();}

async function likviditasKivet(){
 const pid=parseInt($('likPool').value);const pct=parseFloat($('likPct').value);
 if(!(pct>0&&pct<=100)){log('Remove % must be between 0 and 100.');return;}
 if(!confirm('Remove '+pct+'% of your LP position from pool #'+pid+'?'))return;
 const btns=document.querySelectorAll('button');btns.forEach(x=>x.disabled=true);
 try{
  if(MOD==='circle'){
   log('Removing liquidity (Circle)…');
   const d=await apiPost('/api/likviditas_kivet',{pool_id:pid,szazalek:pct,slippage_bps:SLIP_BPS});
   log((d.ok?'✓ ':'✗ ')+d.uzenet+(d.tx?('  '+d.tx):''));
  }else{
   if(!MM_SIGNER){await mmCsatlakozas();if(!MM_SIGNER)throw new Error('no MetaMask');}
   const dx=new ethers.Contract(ALLAPOT.dex,dexAbi(),MM_SIGNER);
   const sh=await dx.myShares(pid,MM_CIM);
   const resz=sh.mul(Math.round(pct*100)).div(10000);
   if(resz.isZero())throw new Error('no LP shares in this pool');
   const p=await dx.pools(pid);
   const outA=resz.mul(p.reserveA).div(p.totalShares),outB=resz.mul(p.reserveB).div(p.totalShares);
   log('MetaMask: removing liquidity…');
   const rc=await (await dx.removeLiquidity(pid,resz,outA.mul(10000-SLIP_BPS).div(10000),outB.mul(10000-SLIP_BPS).div(10000),deadline())).wait();
   log('✓ Liquidity removed (MetaMask). '+ALLAPOT.explorer+rc.transactionHash);
  }
 }catch(e){log('✗ '+hibaSzoveg(e));}
 btns.forEach(x=>x.disabled=false);refresh();}

async function lpFrissit(){
 const pid=parseInt($('likPool').value);const p=ALLAPOT&&ALLAPOT.poolok.find(x=>x.id===pid);
 if(!p){$('lpPos').textContent='–';return;}
 $('likLblA').textContent=p.tokenA;$('likLblB').textContent=p.tokenB;
 const cim=MOD==='mm'?MM_CIM:ALLAPOT.megrendelo.cim;
 if(!cim){$('lpPos').textContent='–';return;}
 try{const d=await apiPost('/api/lp',{cim});
  const x=d.ok&&d.poolok.find(q=>q.id===pid);
  $('lpPos').textContent=x&&x.shares!=='0'?(fmt(x.resz*100,4)+'% · ≈ '+fmt(x.ertekA,6)+' '+p.tokenA+' + '+fmt(x.ertekB,6)+' '+p.tokenB):'no position';
 }catch(e){$('lpPos').textContent='–';}}

async function refresh(){
 try{
  const r=await fetch('/api/allapot');ALLAPOT=await r.json();
  const h=ALLAPOT.halozat;
  $('netname').textContent=h.nev;$('netpill').classList.toggle('test',!h.mainnet);
  $('subtitle').textContent='AMM DEX · '+h.nev;
  const dl=$('dexlink');dl.textContent=ALLAPOT.dex||'not deployed';if(ALLAPOT.dex)dl.href=ALLAPOT.explorer_cim+ALLAPOT.dex;
  const bn=$('banner');
  if(ALLAPOT.szunetel){bn.textContent='The DEX is paused by the operator: swaps and deposits are disabled, withdrawals still work.';bn.className='banner red';bn.style.display='block';}
  else if(!ALLAPOT.dex){bn.textContent='No DEX deployed on this network yet (run telepit.py).';bn.className='banner';bn.style.display='block';}
  else bn.style.display='none';
  $('modCircle').disabled=!ALLAPOT.circle_mod;
  if(!ALLAPOT.circle_mod&&MOD==='circle'){MOD='mm';$('modMM').classList.add('aktiv');$('modCircle').classList.remove('aktiv');}
  const set=new Set();ALLAPOT.poolok.forEach(p=>{set.add(p.tokenA);set.add(p.tokenB);});
  TOKLISTA=[...set];
  if(!FROM||!TOKLISTA.includes(FROM))FROM=TOKLISTA[0];
  if(FROM&&(!TO||!parok(FROM).includes(TO)))TO=parok(FROM)[0];
  if(TOKLISTA.length)feltoltSelectek();
  $('poolok').innerHTML=ALLAPOT.poolok.map(p=>
   `<tr><td><span class="pill"><span class="ic ic-${p.tokenA}" style="width:16px;height:16px;font-size:8px">${p.tokenA==='CIRBTC'?'₿':p.tokenA[0]}</span>${p.tokenA}/${p.tokenB}</span></td>`+
   `<td class="mono">${fmt(p.keszletA,3)} / ${fmt(p.keszletB,6)}</td>`+
   `<td class="mono">${p.arfolyam?fmt(p.arfolyam,6):'—'}</td></tr>`).join('')
   ||'<tr><td colspan="3" class="muted">No pool yet — run: python pool_feltoltes.py</td></tr>';
  const lp=$('likPool');const rl=lp.value;lp.innerHTML='';
  ALLAPOT.poolok.forEach(p=>{const o=document.createElement('option');o.value=p.id;
   o.textContent=p.tokenA+'/'+p.tokenB;lp.appendChild(o);});if(rl)lp.value=rl;
  $('elozmenyek').innerHTML=(ALLAPOT.elozmenyek||[]).map(e=>
   `<tr><td class="mono"><a href="${ALLAPOT.explorer}${e.tx}" target="_blank" rel="noopener">${e.blokk}</a></td><td class="mono muted">${e.valto.slice(0,6)}…</td>`+
   `<td class="piros">${e.be}</td><td class="zold">${e.ki}</td></tr>`).join('')
   ||'<tr><td colspan="4" class="muted">No swaps yet.</td></tr>';
  if(MOD==='mm')await mmEgyenlegek(); else frissEgyenleg();
  ctaFrissit();lpFrissit();
 }catch(e){log('refresh error: '+hibaSzoveg(e));}}

try{ADMIN_TOKEN=sessionStorage.getItem('adminToken');}catch(e){}
ctaFrissit();
refresh().then(()=>{slipValt();});
setInterval(refresh,12000);
</script></body></html>"""


def _indulasi_ellenorzes():
    """Gyors, hangos hibak indulaskor - ne fusson rossz halozaton / rossz cimmel."""
    print(f"ARC Swap - {config.osszefoglalo()}")
    lanc.halozat_ellenorzes()
    if not vc.DEX_CIM:
        print(f"FIGYELEM: meg nincs telepitve a DEX ezen a halozaton "
              f"(futtasd: python telepit.py) - {vc.VALTO_CIMEK_JSON.name}")
    else:
        kod = lanc.web3.eth.get_code(Web3.to_checksum_address(vc.DEX_CIM))
        if not kod or len(kod) < 10:
            raise RuntimeError(f"Nincs szerzodes a DEX cimen ({vc.DEX_CIM}) a(z) "
                               f"{config.HALOZAT_NEV} halozaton. Rossz cimfajl?")
        print(f"DEX: {vc.DEX_CIM}  szunetel={dex_szunetel()}")
    if config.ADMIN_TOKEN:
        if len(config.ADMIN_TOKEN) < 16:
            raise RuntimeError("VALTO_ADMIN_TOKEN tul rovid - legalabb 16 karakter legyen")
        config.kotelezo("MEGRENDELO_CIM", "CIRCLE_API_KEY", "CIRCLE_ENTITY_SECRET")
        print(f"Circle-mod: BEKAPCSOLVA (tarca: {config.MEGRENDELO_CIM})")
        if config.APP_HOST == "0.0.0.0":
            print("FIGYELEM: a Circle-mod minden halozati interfeszen elerheto (APP_HOST=0.0.0.0). "
                  "Tedd TLS-es reverse proxy / tuzfal moge!")
    else:
        print("Circle-mod: kikapcsolva (nincs VALTO_ADMIN_TOKEN) - csak MetaMask-mod")


def inditas():
    _indulasi_ellenorzes()
    threading.Thread(target=_elozmeny_hatter, daemon=True).start()
    print(f"ARC Swap running - open: http://{config.APP_HOST}:{config.APP_PORT}")
    try:
        from waitress import serve
        serve(app, host=config.APP_HOST, port=config.APP_PORT, threads=8)
    except ImportError:
        print("waitress nincs telepitve - Flask fejlesztoi szerver (NEM eles uzemre)")
        app.run(host=config.APP_HOST, port=config.APP_PORT)


if __name__ == "__main__":
    try:
        inditas()
    except Exception as error:
        print(f"\nHiba: {error}")
        raise SystemExit(1)

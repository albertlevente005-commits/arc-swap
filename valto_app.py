"""
ARC VALTO - webes valto felulet (Flask), angol UI
==================================================
Ket mod:
  1. CIRCLE mod   - a szerver a MEGRENDELO Circle-tarcaval valt (gombnyomasra)
  2. METAMASK mod - a bongeszoben a SAJAT MetaMask tarcaddal irod ala a valtast

Inditas (cmd, a projektmappabol):
    python valto_app.py
Utana bongeszoben:  http://127.0.0.1:8060
"""

import threading

from flask import Flask, jsonify, request
from web3 import Web3

import valto_config as vc
import config
from mag import circle_kliens, lanc, seged

app = Flask(__name__)
zar = threading.Lock()

dex = lanc.web3.eth.contract(
    address=Web3.to_checksum_address(vc.DEX_CIM or "0x" + "0" * 40), abi=vc.DEX_ABI)

_elozmeny = {"utolso_blokk": 0, "sorok": []}


def token_egyenleg(token, cim):
    c = lanc.web3.eth.contract(
        address=Web3.to_checksum_address(vc.TOKENEK[token]["cim"]), abi=vc.ERC20_ABI)
    try:
        return vc.egysegbol(token, c.functions.balanceOf(
            Web3.to_checksum_address(cim)).call())
    except Exception:
        return 0


def poolok_lekerese():
    ki = []
    try:
        darab = int(dex.functions.poolCount().call())
    except Exception:
        return ki
    for i in range(darab):
        p = dex.functions.pools(i).call()
        na, nb = vc.token_nev(p[0]), vc.token_nev(p[1])
        ra, rb = vc.egysegbol(na, p[2]), vc.egysegbol(nb, p[3])
        ki.append({"id": i, "tokenA": na, "tokenB": nb,
                   "keszletA": ra, "keszletB": rb,
                   "arfolyam": (rb / ra) if ra else 0})
    return ki


def elozmenyek_frissitese():
    try:
        veg = lanc.web3.eth.block_number
        kezdet = _elozmeny["utolso_blokk"] or max(0, veg - 20000)
        frm = kezdet + 1 if _elozmeny["utolso_blokk"] else kezdet
        while frm <= veg:
            to = min(frm + 8999, veg)
            logs = dex.events.Swapped.create_filter(
                from_block=frm, to_block=to).get_all_entries()
            for lg in logs:
                be_nev = vc.token_nev(lg["args"]["tokenIn"])
                pool = dex.functions.pools(int(lg["args"]["id"])).call()
                ki_cim = pool[1] if pool[0].lower() == lg["args"]["tokenIn"].lower() else pool[0]
                ki_nev = vc.token_nev(ki_cim)
                _elozmeny["sorok"].append({
                    "blokk": lg["blockNumber"], "valto": lg["args"]["trader"],
                    "be": f'{vc.egysegbol(be_nev, lg["args"]["amountIn"])} {be_nev}',
                    "ki": f'{vc.egysegbol(ki_nev, lg["args"]["amountOut"])} {ki_nev}'})
            frm = to + 1
        _elozmeny["utolso_blokk"] = veg
        _elozmeny["sorok"] = _elozmeny["sorok"][-25:]
    except Exception:
        pass


@app.errorhandler(Exception)
def hiba(e):
    return jsonify({"ok": False, "uzenet": f"Error: {e}"}), 200


@app.route("/api/allapot")
def allapot():
    elozmenyek_frissitese()
    egyenlegek = {t: token_egyenleg(t, config.MEGRENDELO_CIM) for t in vc.TOKENEK}
    return jsonify({
        "dex": vc.DEX_CIM, "explorer": config.EXPLORER_TX, "rpc": config.RPC_URL,
        "tokenek": vc.TOKENEK, "poolok": poolok_lekerese(),
        "megrendelo": {"cim": config.MEGRENDELO_CIM, "egyenlegek": egyenlegek},
        "elozmenyek": _elozmeny["sorok"][::-1]})


@app.route("/api/arjegyzes", methods=["POST"])
def arjegyzes():
    d = request.json
    egyseg_be = vc.egysegbe(d["token_be"], d["mennyiseg"])
    ki_egyseg = dex.functions.getQuote(
        int(d["pool_id"]), Web3.to_checksum_address(vc.TOKENEK[d["token_be"]]["cim"]),
        int(egyseg_be)).call()
    return jsonify({"ok": True, "ki_egyseg": str(ki_egyseg),
                    "ki_mennyiseg": vc.egysegbol(d["token_ki"], ki_egyseg)})


@app.route("/api/valtas", methods=["POST"])
def valtas():
    d = request.json
    token_be, token_ki = d["token_be"], d["token_ki"]
    egyseg_be = vc.egysegbe(token_be, d["mennyiseg"])
    with zar:
        ki_egyseg = dex.functions.getQuote(
            int(d["pool_id"]), Web3.to_checksum_address(vc.TOKENEK[token_be]["cim"]),
            int(egyseg_be)).call()
        min_ki = int(ki_egyseg * 99 // 100)
        circle_kliens.contract_tx(
            config.MEGRENDELO_CIM, vc.TOKENEK[token_be]["cim"],
            "approve(address,uint256)", [vc.DEX_CIM, egyseg_be], f"{token_be} approve")
        tx = circle_kliens.contract_tx(
            config.MEGRENDELO_CIM, vc.DEX_CIM, "swap(uint256,address,uint256,uint256)",
            [str(int(d["pool_id"])), vc.TOKENEK[token_be]["cim"], egyseg_be, str(min_ki)],
            "swap")
    kapott = vc.egysegbol(token_ki, ki_egyseg)
    seged.esemeny("Swap", f"{d['mennyiseg']} {token_be} -> ~{kapott} {token_ki} (Circle)")
    return jsonify({"ok": True, "uzenet": f"Swap done: {d['mennyiseg']} {token_be} "
                    f"-> ~{round(kapott, 6)} {token_ki}", "tx": config.EXPLORER_TX + tx})


@app.route("/api/likviditas", methods=["POST"])
def likviditas():
    d = request.json
    pool = poolok_lekerese()[int(d["pool_id"])]
    ta, tb = pool["tokenA"], pool["tokenB"]
    ea, eb = vc.egysegbe(ta, d["mennyiseg_a"]), vc.egysegbe(tb, d["mennyiseg_b"])
    with zar:
        circle_kliens.contract_tx(config.MEGRENDELO_CIM, vc.TOKENEK[ta]["cim"],
                                  "approve(address,uint256)", [vc.DEX_CIM, ea], f"{ta} approve")
        circle_kliens.contract_tx(config.MEGRENDELO_CIM, vc.TOKENEK[tb]["cim"],
                                  "approve(address,uint256)", [vc.DEX_CIM, eb], f"{tb} approve")
        circle_kliens.contract_tx(
            config.MEGRENDELO_CIM, vc.DEX_CIM, "addLiquidity(uint256,uint256,uint256)",
            [str(int(d["pool_id"])), ea, eb], "add liquidity")
    return jsonify({"ok": True, "uzenet": f"Liquidity added: {d['mennyiseg_a']} {ta}"
                    f" + {d['mennyiseg_b']} {tb}"})


@app.route("/")
def fooldal():
    return HTML


HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ARC Swap</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/ethers/5.7.2/ethers.umd.min.js"></script>
<style>
:root{
 --bg:#eaf5ee;--bg2:#f7fbf8;--card:#ffffff;--inset:#f2f8f4;--border:#d3e6da;
 --text:#12291d;--muted:#5e7d6c;--faint:#93aa9d;
 --green:#1eb45a;--green2:#149048;--greenl:#dff6e7;--greenb:#b6e6c8;
 --red:#e64545;--red2:#c62f2f;--redl:#ffe3e3;--redb:#f5c0c0;
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
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);
 box-shadow:0 0 0 3px rgba(30,180,90,.2)}
.card{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:18px;
 box-shadow:0 10px 30px rgba(20,80,45,.08)}
.card h2{font-size:12px;margin:0 0 13px;color:var(--muted);text-transform:uppercase;
 letter-spacing:.09em;font-weight:700}
.swaphead{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.swaphead h1{font-size:20px;margin:0}
.modewrap{display:flex;background:var(--inset);border:1px solid var(--border);
 border-radius:11px;padding:3px}
.modebtn{border:none;background:transparent;color:var(--muted);font:inherit;font-size:12px;
 font-weight:700;padding:6px 12px;border-radius:8px;cursor:pointer}
.modebtn.aktiv{background:var(--grad);color:#fff}
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
 color:var(--muted);padding:12px 4px 4px}
.rate b{color:var(--text);font-weight:700}
.impact{font-size:11.5px;color:var(--red2)}
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
 font-family:ui-monospace,Menlo,monospace;font-size:11px;max-height:150px;overflow:auto;
 white-space:pre-wrap;color:#bfe8cf;line-height:1.7}
.lik .row{display:flex;gap:9px;flex-wrap:wrap;align-items:flex-end}
.lik label{display:block;font-size:11px;color:var(--muted);margin-bottom:4px;font-weight:600}
.lik input,.lik select{background:var(--inset);border:1px solid var(--border);color:var(--text);
 border-radius:9px;padding:9px 10px;font:inherit;font-size:13px}
.lik input{width:92px}
.lik .go{background:var(--grad);border:none;color:#fff;border-radius:9px;padding:9px 16px;
 font:inherit;font-size:13px;font-weight:700;cursor:pointer}
.foot{color:var(--faint);font-size:11.5px;text-align:center}
</style></head><body>
<div class="col">

 <div class="top">
  <div class="brand"><div class="logo">◈</div>
   <div><b>ARC Swap</b><span>Your own AMM DEX · Arc Testnet</span></div></div>
  <div class="net"><span class="dot"></span><span>Arc Testnet</span></div>
 </div>

 <!-- SWAP -->
 <div class="card">
  <div class="swaphead"><h1>Swap</h1>
   <div class="modewrap">
    <button id="modCircle" class="modebtn aktiv" onclick="modValt('circle')">Circle</button>
    <button id="modMM" class="modebtn" onclick="modValt('mm')">MetaMask</button></div></div>

  <div class="tokbox be">
   <div class="fej"><span class="cimke">You pay</span>
    <span class="bal">Balance: <span id="balFrom">–</span><button class="maxbtn" onclick="maxBe()">MAX</button></span></div>
   <div class="tokrow">
    <input id="mennyiseg" class="amt" value="1" inputmode="decimal" placeholder="0" oninput="arjegyzesKesleltetve()">
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

  <button id="cta" class="cta" onclick="valtas()">Swap</button>
  <div id="mmAllapot" class="muted" style="font-size:11.5px;text-align:center;margin-top:9px"></div>
 </div>

 <!-- POOLS -->
 <div class="card"><h2>Liquidity pools</h2>
  <table><thead><tr><th>Pair</th><th>Reserves</th><th>Mid-price</th></tr></thead>
  <tbody id="poolok"></tbody></table></div>

 <!-- BALANCES -->
 <div class="card"><h2>Balances · client wallet</h2>
  <div class="baljelek" id="egyenlegek"></div>
  <div class="muted" style="font-size:11px;margin-top:10px" id="mCim"></div></div>

 <!-- ADD LIQUIDITY -->
 <div class="card lik"><h2>Add liquidity</h2>
  <div class="row">
   <div><label>Pool</label><select id="likPool"></select></div>
   <div><label>A</label><input id="likA" value="1"></div>
   <div><label>B</label><input id="likB" value="1"></div>
   <button class="go" onclick="likviditas()">Add</button></div></div>

 <!-- RECENT SWAPS -->
 <div class="card"><h2>Recent swaps · on-chain</h2>
  <table><thead><tr><th>Block</th><th>Trader</th><th>In</th><th>Out</th></tr></thead>
  <tbody id="elozmenyek"></tbody></table></div>

 <!-- LOG -->
 <div class="card"><h2>Log</h2><div id="naplo">Ready.</div></div>

 <div class="foot">Testnet demo · unaudited · the 0.3% fee goes to liquidity providers<br>
  DEX: <span id="dexcim" class="mono">…</span></div>
</div>

<script>
let ALLAPOT=null, MOD='circle', MM_CIM=null, MM_SIGNER=null;
let FROM=null, TO=null, TOKLISTA=[];
const $=id=>document.getElementById(id);
function log(t){$('naplo').textContent=(new Date()).toLocaleTimeString()+"  "+t+"\n"+$('naplo').textContent;}
const DEX_ABI_JS=[
 "function swap(uint256 id, address tokenIn, uint256 amountIn, uint256 minOut) returns (uint256)",
 "function addLiquidity(uint256 id, uint256 amountA, uint256 amountB) returns (uint256)"];
const ERC20_ABI_JS=["function approve(address,uint256) returns (bool)"];
const LANC_HEX="0x4cef52"; // 5042002

function setIc(el,tok){el.className='ic ic-'+tok;el.textContent=tok==='CIRBTC'?'₿':tok[0];}
function poolKereses(a,b){
 if(!ALLAPOT)return null;
 for(const p of ALLAPOT.poolok){
  if(p.tokenA===a&&p.tokenB===b)return{id:p.id};
  if(p.tokenA===b&&p.tokenB===a)return{id:p.id};}
 return null;}
function parok(tok){const ki=new Set();
 for(const p of ALLAPOT.poolok){if(p.tokenA===tok)ki.add(p.tokenB);if(p.tokenB===tok)ki.add(p.tokenA);}
 return [...ki];}

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
function frissEgyenleg(){if(!ALLAPOT)return;const e=ALLAPOT.megrendelo.egyenlegek;
 $('balFrom').textContent=(e[FROM]??'–')+' '+FROM;$('balTo').textContent=(e[TO]??'–')+' '+TO;}
function fromValt(){FROM=$('selFrom').value;if(!parok(FROM).includes(TO))TO=parok(FROM)[0];feltoltSelectek();arjegyzes();}
function toValt(){TO=$('selTo').value;feltoltSelectek();arjegyzes();}
function flip(){const a=FROM;FROM=TO;TO=a;if(!parok(FROM).includes(TO))TO=parok(FROM)[0];feltoltSelectek();arjegyzes();}
function maxBe(){const e=ALLAPOT?.megrendelo.egyenlegek[FROM];if(e){$('mennyiseg').value=e;arjegyzes();}}

function modValt(m){MOD=m;
 $('modCircle').classList.toggle('aktiv',m==='circle');
 $('modMM').classList.toggle('aktiv',m==='mm');ctaFrissit();
 if(m==='mm'&&!MM_CIM)mmCsatlakozas();}
function ctaFrissit(){const b=$('cta');
 if(MOD==='mm'&&!MM_CIM){b.textContent='Connect MetaMask';b.classList.add('wallet');}
 else{b.textContent='Swap';b.classList.remove('wallet');}}

async function mmCsatlakozas(){
 if(!window.ethereum){$('mmAllapot').textContent='No MetaMask in this browser.';return;}
 try{
  const pr=new ethers.providers.Web3Provider(window.ethereum,'any');
  await pr.send('eth_requestAccounts',[]);
  try{await pr.send('wallet_switchEthereumChain',[{chainId:LANC_HEX}]);}
  catch(err){const c=err&&(err.code||(err.data&&err.data.originalError&&err.data.originalError.code));
   if(c===4902){await pr.send('wallet_addEthereumChain',[{chainId:LANC_HEX,chainName:'Arc Testnet',
    rpcUrls:[ALLAPOT.rpc],nativeCurrency:{name:'USDC',symbol:'USDC',decimals:18},
    blockExplorerUrls:['https://testnet.arcscan.app']}]);}else throw err;}
  MM_SIGNER=pr.getSigner();MM_CIM=await MM_SIGNER.getAddress();
  $('mmAllapot').textContent='Connected: '+MM_CIM.slice(0,6)+'…'+MM_CIM.slice(-4)+' · Arc Testnet';
  ctaFrissit();log('MetaMask connected: '+MM_CIM);
 }catch(e){$('mmAllapot').textContent='MetaMask error: '+(e.message||e);}}

let idozito=null;
function arjegyzesKesleltetve(){clearTimeout(idozito);idozito=setTimeout(arjegyzes,350);}
async function arjegyzes(){
 if(!ALLAPOT||!FROM||!TO)return;
 const pool=poolKereses(FROM,TO);const m=$('mennyiseg').value;
 if(!pool){$('rateTxt').textContent='No pool for this pair.';$('kimenet').value='';return;}
 if(!m||parseFloat(m)<=0){$('rateTxt').textContent='Enter an amount…';$('kimenet').value='';$('impactTxt').textContent='';return;}
 try{
  const r=await fetch('/api/arjegyzes',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({pool_id:pool.id,token_be:FROM,token_ki:TO,mennyiseg:m})});
  const d=await r.json();
  if(d.ok){const ki=Number(d.ki_mennyiseg);
   $('kimenet').value=ki.toFixed(6).replace(/\.?0+$/,'');
   $('cta').dataset.kiEgyseg=d.ki_egyseg;$('cta').dataset.pool=pool.id;
   const egys=ki/parseFloat(m);
   $('rateTxt').innerHTML='1 '+FROM+' ≈ <b>'+egys.toFixed(6).replace(/\.?0+$/,'')+'</b> '+TO;
   const p=ALLAPOT.poolok.find(x=>x.id===pool.id);
   const kozep=(p.tokenA===FROM)?p.arfolyam:(p.arfolyam?1/p.arfolyam:0);
   const hatas=kozep?(1-egys/kozep)*100:0;
   $('impactTxt').textContent=hatas>0.01?('price impact −'+hatas.toFixed(2)+'%'):'';
  }else{$('rateTxt').textContent=d.uzenet;$('kimenet').value='';}
 }catch(e){$('rateTxt').textContent='Quote error: '+e.message;}}

async function valtas(){
 if(MOD==='mm'&&!MM_CIM){await mmCsatlakozas();return;}
 const pool=poolKereses(FROM,TO);if(!pool)return;const m=$('mennyiseg').value;
 const btns=document.querySelectorAll('button');btns.forEach(b=>b.disabled=true);
 try{
  if(MOD==='circle'){
   log('Swap (Circle): '+m+' '+FROM+' → '+TO+' … (20–60s)');
   const r=await fetch('/api/valtas',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({pool_id:pool.id,token_be:FROM,token_ki:TO,mennyiseg:m})});
   const d=await r.json();log((d.ok?'✓ ':'✗ ')+d.uzenet+(d.tx?('  '+d.tx):''));
  }else{
   if(!MM_SIGNER){await mmCsatlakozas();if(!MM_SIGNER)throw new Error('no MetaMask');}
   const t=ALLAPOT.tokenek[FROM];
   const be=ethers.utils.parseUnits(String(m),t.tizedes);
   const kiE=ethers.BigNumber.from($('cta').dataset.kiEgyseg||'0');
   if(kiE.isZero())throw new Error('request a quote first');
   const minKi=kiE.mul(99).div(100);
   log('MetaMask: signing '+FROM+' approval…');
   await (await new ethers.Contract(t.cim,ERC20_ABI_JS,MM_SIGNER).approve(ALLAPOT.dex,be)).wait();
   log('MetaMask: signing swap…');
   const dx=new ethers.Contract(ALLAPOT.dex,DEX_ABI_JS,MM_SIGNER);
   const rc=await (await dx.swap(pool.id,t.cim,be,minKi)).wait();
   log('✓ Swap done (MetaMask). '+ALLAPOT.explorer+rc.transactionHash);
  }
 }catch(e){log('✗ '+(e.reason||e.message||e));}
 btns.forEach(b=>b.disabled=false);refresh();}

async function likviditas(){
 const pid=parseInt($('likPool').value);const a=$('likA').value,b=$('likB').value;
 const btns=document.querySelectorAll('button');btns.forEach(x=>x.disabled=true);
 try{
  if(MOD==='circle'){
   log('Adding liquidity (Circle)… (30–90s)');
   const r=await fetch('/api/likviditas',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({pool_id:pid,mennyiseg_a:a,mennyiseg_b:b})});
   const d=await r.json();log((d.ok?'✓ ':'✗ ')+d.uzenet);
  }else{
   if(!MM_SIGNER){await mmCsatlakozas();if(!MM_SIGNER)throw new Error('no MetaMask');}
   const p=ALLAPOT.poolok.find(x=>x.id===pid);
   const tA=ALLAPOT.tokenek[p.tokenA],tB=ALLAPOT.tokenek[p.tokenB];
   const eA=ethers.utils.parseUnits(String(a),tA.tizedes),eB=ethers.utils.parseUnits(String(b),tB.tizedes);
   log('MetaMask: approvals…');
   await (await new ethers.Contract(tA.cim,ERC20_ABI_JS,MM_SIGNER).approve(ALLAPOT.dex,eA)).wait();
   await (await new ethers.Contract(tB.cim,ERC20_ABI_JS,MM_SIGNER).approve(ALLAPOT.dex,eB)).wait();
   log('MetaMask: adding liquidity…');
   const dx=new ethers.Contract(ALLAPOT.dex,DEX_ABI_JS,MM_SIGNER);
   const rc=await (await dx.addLiquidity(pid,eA,eB)).wait();
   log('✓ Liquidity added (MetaMask). '+ALLAPOT.explorer+rc.transactionHash);
  }
 }catch(e){log('✗ '+(e.reason||e.message||e));}
 btns.forEach(x=>x.disabled=false);refresh();}

async function refresh(){
 try{
  const r=await fetch('/api/allapot');ALLAPOT=await r.json();
  $('dexcim').textContent=ALLAPOT.dex||'not deployed';
  $('mCim').textContent='Address: '+ALLAPOT.megrendelo.cim;
  const set=new Set();ALLAPOT.poolok.forEach(p=>{set.add(p.tokenA);set.add(p.tokenB);});
  TOKLISTA=[...set];
  if(!FROM||!TOKLISTA.includes(FROM))FROM=TOKLISTA[0];
  if(!TO||!parok(FROM).includes(TO))TO=parok(FROM)[0];
  if(TOKLISTA.length)feltoltSelectek();
  $('poolok').innerHTML=ALLAPOT.poolok.map(p=>
   `<tr><td><span class="pill"><span class="ic ic-${p.tokenA}" style="width:16px;height:16px;font-size:8px">${p.tokenA==='CIRBTC'?'₿':p.tokenA[0]}</span>${p.tokenA}/${p.tokenB}</span></td>`+
   `<td class="mono">${(+p.keszletA).toFixed(3)} / ${(+p.keszletB).toFixed(4)}</td>`+
   `<td class="mono">${p.arfolyam?p.arfolyam.toFixed(5):'—'}</td></tr>`).join('')
   ||'<tr><td colspan="3" class="muted">No pool — run: python pool_feltoltes.py</td></tr>';
  $('egyenlegek').innerHTML=Object.entries(ALLAPOT.megrendelo.egyenlegek).map(([t,e])=>
   `<div class="bchip"><span class="ic ic-${t}">${t==='CIRBTC'?'₿':t[0]}</span>`+
   `<div><div class="v">${e}</div><div class="t">${t}</div></div></div>`).join('');
  const lp=$('likPool');const rl=lp.value;lp.innerHTML='';
  ALLAPOT.poolok.forEach(p=>{const o=document.createElement('option');o.value=p.id;
   o.textContent=p.tokenA+'/'+p.tokenB;lp.appendChild(o);});if(rl)lp.value=rl;
  $('elozmenyek').innerHTML=(ALLAPOT.elozmenyek||[]).map(e=>
   `<tr><td class="mono">${e.blokk}</td><td class="mono muted">${e.valto.slice(0,6)}…</td>`+
   `<td class="piros">${e.be}</td><td class="zold">${e.ki}</td></tr>`).join('')
   ||'<tr><td colspan="4" class="muted">No swaps yet.</td></tr>';
  frissEgyenleg();
 }catch(e){}}

ctaFrissit();
refresh().then(()=>arjegyzes());
setInterval(refresh,12000);
</script></body></html>"""


if __name__ == "__main__":
    if not vc.DEX_CIM:
        print("FIGYELEM: meg nincs telepitve a DEX (futtasd: python telepit.py)")
    print("ARC Swap running - open: http://127.0.0.1:8060")
    app.run(host="127.0.0.1", port=8060)

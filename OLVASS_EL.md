# ARC Váltó — saját AMM DEX az Arc hálózaton (mainnet-kész)

Saját AMM (automata árjegyző) váltó **USDC · EURC · cirBTC** párokkal, Uniswap-elven
(x·y=k, 0,3% díj), plusz egy **Váltó-Ügynök**, aki a piactéren job-alapon vált.

Ez a verzió az **Arc mainnetre** (éles) van felkészítve; a részletes élesítési
lépések és a biztonsági változtatások a [`MAINNET.md`](MAINNET.md)-ben vannak.
A hálózatot a `.env` `ARC_HALOZAT` sora választja (`mainnet` vagy `testnet`).

## Részei

| Fájl | Mire való |
|---|---|
| `contracts/ValtoDEX.sol` | Az AMM okosszerződés (pool + likviditás + swap, pause, tulajdonos) |
| `build/ValtoDEX.json` | Lefordítva, telepítésre kész (ABI + bytecode + metadata) |
| `compile.js` | Fordítás: `npm install && node compile.js` |
| `telepit.py` | Telepíti a DEX-et (Circle SCP, a `TELEPITO_CIM` tárcáról, az lesz a tulajdonos) |
| `pool_feltoltes.py` | Létrehozza a poolokat + beteszi a kezdő likviditást (piaci ár ellenőrzéssel) |
| `dex_admin.py` | Tulajdonosi műveletek: pause/unpause, pool, tulajdonos-átadás |
| `valto_app.py` | Webes váltó felület — http://127.0.0.1:8060 |
| `valto_ugynok.py` | Piactéri ügynök: `[skill:valtas]` jobokat vált a DEX-en |
| `config.py`, `valto_config.py` | Hálózat, tokenek, poolok, címek egy helyen |
| `tests/` | pytest tesztek helyi EVM-en (`python -m pytest tests`) |

## Beüzemelés (sorban)

**0. Beállítás**
```
pip install -r requirements.txt
npm install && node compile.js
copy .env.minta .env        (Linux/mac: cp .env.minta .env)
```
A `.env`-ben: `ARC_HALOZAT`, Circle kulcsok (mainneten LIVE!), `TELEPITO_CIM`,
`MEGRENDELO_CIM`, `VALTO_ADMIN_TOKEN`, és a kezdő likviditás (`POOL_USDC_EURC=...`).

**1. DEX telepítése** (a telepítő tárcán legyen ~1 USDC gázra):
```
python telepit.py
```
Mainneten be kell gépelni, hogy `MAINNET`. A cím a `valto_cimek.mainnet.json`-ba kerül — commitold.

**2. Poolok + kezdő likviditás:**
```
python pool_feltoltes.py
```
Az első betevés aránya = a pool kezdő ára. A script összeveti a piaci árfolyammal, és
2% feletti eltérésnél megáll (`--kenyszerit` felülírja).

**3. Webes váltó:**
```
python valto_app.py
```
→ http://127.0.0.1:8060

Két mód a felületen:
- **MetaMask** (alap) — a saját böngészős tárcáddal váltasz; a gomb magától csatlakoztat és
  beállítja az Arc hálózatot. Likviditást is tehetsz be / vehetsz ki.
- **Circle** — a szerver a `MEGRENDELO_CIM` tárcával vált. Csak akkor elérhető, ha a `.env`-ben
  van `VALTO_ADMIN_TOKEN`, és a felület bekéri a tokent. Idegen gépről ne engedd!

**4. Váltó-Ügynök a piactéren** (opcionális):
```
python valto_ugynok.py
```
Mainneten csak akkor indul, ha a `.env`-ben meg van adva a saját ERC-8183 piactér
(`AGENTIC_COMMERCE_CIM`) és AgentBond (`AGENTBOND_CIM`) címe — a Circle-féle referencia
csak testneten létezik. Az ügynök a **ténylegesen** kapott összeget küldi a megrendelőnek,
és jobonként legfeljebb `UGYNOK_MAX_VALTAS_USDC` (alap 100) USDC-t vált.

> A Váltó-Ügynök csak `be=USDC` irányt vállal (a készlete USDC-ben van).

## Üzemeltetés

```
python dex_admin.py allapot
python dex_admin.py pause        # swap + betevés leáll; a likviditás-kivétel mindig működik
python dex_admin.py unpause
```
Egészség: `GET /healthz`. Napló: `adat/valto.<halozat>.log`.

## Hogyan áraz az AMM?

A pool két készlete szorzatának állandónak kell maradnia (x·y=k). Minél nagyobbat váltasz a
pool méretéhez képest, annyival rosszabb az árfolyam (csúszás). A 0,3% díj a poolban marad —
aki likviditást tett be, annak dolgozik. A felületen állítható a max. csúszás (alap 0,5%), és
a lánc csak a megadott határidőn (alap 10 perc) belül hajtja végre a tranzakciót.

## Hibaelhárítás

- **„Nincs valto_cimek.mainnet.json"** → futtasd a `telepit.py`-t.
- **„chain id ... != ..."** → az `ARC_HALOZAT` és az `ARC_RPC_URL` nem ugyanaz a hálózat.
- **„EmptyPool"** → futtasd a `pool_feltoltes.py`-t (és legyen elég token).
- **„Slippage"** → az ár elmozdult; emeld a csúszást vagy próbáld újra.
- **„IsPaused"** → a tulajdonos szünetelteti a DEX-et (`dex_admin.py unpause`).
- **MetaMask nem vált hálózatot** → fogadd el a felugró ablakokat; kézzel: lánc ID `5042`,
  RPC `https://rpc.mainnet.arc.io`, explorer `https://explorer.arc.io`.
- **Circle-mód 403** → rossz vagy hiányzó `VALTO_ADMIN_TOKEN`.

> Nem auditált kód — korlátozott összeggel indulj, és tartsd kéznél a pause-t.

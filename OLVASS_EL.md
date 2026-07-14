# ARC Váltó — saját mini-DEX az Arc Testneten

Saját AMM (automata árjegyző) váltó **USDC · EURC · cirBTC** párokkal, Uniswap-elven
(x·y=k, 0,3% díj), plusz egy **Váltó-Ügynök**, aki a piactéren job-alapon vált.

## Részei

| Fájl | Mire való |
|---|---|
| `contracts/ValtoDEX.sol` | Az AMM okosszerződés (pool + likviditás + swap) |
| `build/ValtoDEX.json` | Lefordítva, telepítésre kész (ABI + bytecode) |
| `telepit.py` | Telepíti a DEX-et az Arc-ra (Circle SCP, a 0x774E... tárcáról) |
| `pool_feltoltes.py` | Létrehozza a poolokat + beteszi a kezdő likviditást |
| `valto_app.py` | Webes váltó felület — http://127.0.0.1:8060 |
| `valto_ugynok.py` | Piactéri ügynök: `[skill:valtas]` jobokat vált a DEX-en |
| `valto_config.py` | Tokenek, poolok, címek egy helyen |

A közös alapokat (Circle kliens, lánc-olvasó, napló) az `arc-platform` mappából
használja — azt ne töröld/mozgasd el.

## Beüzemelés (cmd, sorban)

```
cd C:\Users\Panoskir\Cowork\ARC2026\arc-valto
```

**0. Tokenek a megrendelő tárcára** — a kezdő likviditáshoz kell:
- USDC és **EURC**: https://faucet.circle.com → Arc Testnet → cím:
  `0xfd38e25aca03e65d4b203b329733cf7e9c1a414b`
- cirBTC: Circle Console faucet (https://console.circle.com/faucet), vagy
  küldd át a MetaMask tárcádból. (Ha nincs, a cirBTC pool kimarad — nem gond.)

**1. DEX telepítése** (a telepítő tárcán legyen ~1-2 USDC gázra):
```
python telepit.py
```

**2. Poolok + kezdő likviditás** (20 USDC + 18,5 EURC; 10 USDC + 0,0001 cirBTC):
```
python pool_feltoltes.py
```

**3. Webes váltó:**
```
python valto_app.py
```
→ http://127.0.0.1:8060

Két mód a felületen:
- **Circle tárca** — a megrendelő tárcával vált, gombnyomásra (szerver írja alá)
- **MetaMask** — a saját böngészős tárcáddal váltasz; a gomb magától
  csatlakoztat és beállítja az Arc Testnet hálózatot. Így a MetaMask-on lévő
  USDC/EURC/cirBTC készletedet is tudod váltani, és likviditást is tehetsz be.

**4. Váltó-Ügynök a piactéren** (opcionális, de ez a menő rész):
```
python valto_ugynok.py
```
Az ügynök első induláskor saját tárcát + ERC-8004 identitást csinál magának,
kauciót tesz le, és onnantól figyeli a láncot. Küldj neki USDC készletet
(a címét kiírja induláskor), abból vált.

Job kiírása a piactéren (másik cmd ablakban, az arc-platform mappából):
```
python megrendelo.py --skill valtas --parameter "be=USDC ki=EURC osszeg=5" --max 6
```
A `--max` legyen legalább `osszeg + 0,5` (ennyi az ügynök díja).
Az ügynök átváltja a DEX-en, az EURC-t elküldi a megrendelőnek, a hash-t
leadja, a megrendelő ellenőriz, fizet és értékel — a teljes kör a láncon.

> A Váltó-Ügynök csak `be=USDC` irányt vállal (a készlete USDC-ben van).

## Hogyan áraz az AMM?

A pool két készlete szorzatának állandónak kell maradnia (x·y=k).
Minél nagyobbat váltasz a pool méretéhez képest, annyival rosszabb az árfolyam
(csúszás). A 0,3% díj a poolban marad — aki likviditást tett be, annak dolgozik.

## Hibaelhárítás

- **„Nincs valto_cimek.json"** → futtasd a `telepit.py`-t.
- **„empty pool"** → futtasd a `pool_feltoltes.py`-t (és legyen elég token).
- **MetaMask nem vált hálózatot** → fogadd el a felugró ablakokat; ha kézzel
  kell: lánc ID `5042002`, RPC `https://rpc.testnet.arc.network`.
- **A telepítés elakad** → a telepítő tárcán (`0x774E...`) legyen USDC a gázra.

> Teszthálózati demó, nem auditált — éles használatra nem való.

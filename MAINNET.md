# Arc mainnet – éles üzembe helyezési ellenőrzőlista

Ez a repo a hackathon-tesztnet verzióból éles (Arc mainnet) üzemre lett felkészítve.
Az alábbi sorrendben haladj. **Minden lépést előbb testneten játssz végig** (`ARC_HALOZAT=testnet`),
az új szerződést a régi testnet-címre NEM lehet használni (más az ABI), tehát testneten is újra kell telepíteni.

## 0. Mi változott a testnet-demóhoz képest

| Terület | Testnet-demó | Éles verzió |
|---|---|---|
| Hálózat | beégetett testnet (5042002) | `ARC_HALOZAT=mainnet` → chain id 5042, `rpc.mainnet.arc.io`, `explorer.arc.io`, Circle `ARC` |
| Tokencímek | testnet | mainnet USDC / EURC / cirBTC (docs.arc.io/contract-addresses) |
| Tárcacímek | kódba égetve | `.env` (`TELEPITO_CIM`, `MEGRENDELO_CIM`), nincs „szomszéd mappa” `.env`-keresés |
| Szerződés | demó AMM | reentrancy-zár, safe-ERC20, balance-delta elszámolás, `MINIMUM_LIQUIDITY`, deadline, slippage a kivételen is, duplikált pool tiltás, tulajdonos + pause (a kivétel soha nem pausolható), zárt pool-létrehozás, kétlépcsős tulajdonos-átadás, natív érték elutasítása |
| Webapp | bárki küldhetett tranzakciót a szerver Circle-tárcájával | Circle-mód csak `VALTO_ADMIN_TOKEN`-nel; alapértelmezett a MetaMask-mód; bemenet-validálás; nincs hibaszöveg-kiszivárgás; CSP/biztonsági fejlécek; állítható slippage + deadline; allowance-ellenőrzés; waitress szerver; `/healthz`; naplófájl |
| Frontend | ethers CDN-ről | helyben kiszolgált `static/ethers-5.7.2.umd.min.js` (nincs CDN-függés); hálózati adatok a szerverről; LP-pozíció + kivétel; custom error-ok olvasható üzenettel |
| Telepítés | fix testnet | constructor(owner, zárt poolok), chain-id ellenőrzés, mainnet megerősítés, on-chain tulajdonos-ellenőrzés, hálózatonkénti `valto_cimek.<halozat>.json` |
| Poolok | fix mennyiség | `.env`-ből; kezdő ár összevetése piaci referenciával (2% felett megáll) |
| Tesztek | nincs | 35 pytest (szerződés helyi EVM-en + webapp HTTP) + CI (GitHub Actions) |
| Ügynök | testnet-only ERC-8183 cím beégetve | mainneten csak saját `AGENTIC_COMMERCE_CIM` / `AGENTBOND_CIM` megadásával indul; a ténylegesen kapott összeget küldi (Swapped event), jobonkénti plafon |

## 1. Előfeltételek

- Python 3.10+, Node 22 (csak a fordításhoz), `pip install -r requirements.txt`, `npm install`.
- Circle Console **LIVE** környezet: API kulcs + regisztrált entity secret. (A TEST kulcs mainneten nem működik.)
- Két developer-controlled tárca az **ARC** (mainnet) láncon a Circle-nél:
  - `TELEPITO_CIM` – a DEX telepítője és **tulajdonosa** (pause, pool-létrehozás). Kezeld hidegen, minimális egyenleggel.
  - `MEGRENDELO_CIM` – kezdő likviditás + a webapp Circle-módja.
- USDC mindkét tárcán (gáz: pár cent/tx; a minimum base fee 20 gwei, Circle `feeLevel=MEDIUM` kezeli).
- EURC / cirBTC a `MEGRENDELO_CIM`-en a kezdő likviditáshoz (Circle Mint / CCTP / bridge).

## 2. Konfiguráció

```bash
cp .env.minta .env
```

Töltsd ki: `ARC_HALOZAT=mainnet`, Circle LIVE kulcsok, `TELEPITO_CIM`, `MEGRENDELO_CIM`,
`VALTO_ADMIN_TOKEN` (`python -c "import secrets; print(secrets.token_urlsafe(32))"`),
`POOL_USDC_EURC` / `POOL_USDC_CIRBTC` a **piaci árfolyam** szerint.

## 3. Fordítás és tesztek

```bash
npm install && node compile.js
pip install -r requirements-dev.txt
ARC_HALOZAT=testnet python -m pytest tests -q
```

A `build/ValtoDEX.json` legyen commitolva és egyezzen a forrással (a CI ezt ellenőrzi).

## 4. Telepítés

```bash
python telepit.py            # „MAINNET” begépelése kell
```

- A tulajdonos alapból a `TELEPITO_CIM`; `--tulajdonos 0x...`-szel más (pl. multisig) is lehet.
- Alapból **csak a tulajdonos hozhat létre poolt** (`--nyitott-poolok` kapcsolja ki).
- A script ellenőrzi a láncon a kódot és a tulajdonost, majd `valto_cimek.mainnet.json`-t ír → **commitold**.
- Ellenőrizd a szerződést az explorerben: https://explorer.arc.io/address/<cím>; a forrás verifikálásához a
  `build/ValtoDEX.json` tartalmazza a `metadata`-t (solc 0.8.28, optimizer 1000 runs, evm cancun).

## 5. Poolok és kezdő likviditás

```bash
python pool_feltoltes.py
```

- Az első betevő aránya = a pool kezdő ára. A script lekéri az EUR/USD (frankfurter) és BTC/USD (CoinGecko)
  referenciát, és 2% feletti eltérésnél nem tesz be (`--kenyszerit` felülírja).
- Ha a `MEGRENDELO_CIM` nem tulajdonos és a pool-létrehozás zárt: előbb `python dex_admin.py pool USDC EURC`.
- 1000 share örökre zárolva marad (MINIMUM_LIQUIDITY) – ez elhanyagolható összeg, de nem vehető ki.

## 6. Webapp éles futtatása

```bash
python valto_app.py          # waitress, APP_HOST/APP_PORT szerint
# vagy
docker build -t arc-swap . && docker run --env-file .env -p 8060:8060 arc-swap
```

- Tedd TLS-es reverse proxy (nginx/Caddy) mögé; a Circle-módot csak belső hálózatról / VPN-ről engedd.
- A `VALTO_ADMIN_TOKEN` nélkül a szerver csak MetaMask-módot ad (a szerver tárcájához senki nem fér hozzá).
- `/healthz` a monitorozáshoz; napló: `adat/valto.mainnet.log`.
- Indulási ellenőrzések: chain id egyezés, van kód a DEX címén, token hossza, kötelező `.env` mezők.

## 7. Üzemeltetés / incidens

```bash
python dex_admin.py allapot
python dex_admin.py pause          # swap + betevés leáll, a likviditás-kivétel működik
python dex_admin.py unpause
python dex_admin.py tulajdonos-atadas 0x<multisig>   # majd a másik félen: tulajdonos-elfogadas
```

## 8. Ami tudatosan NINCS benne / kockázatok

- **Nincs független audit.** A tesztek a tipikus AMM-hibákat fedik (reentrancy, share-infláció, slippage,
  nem szabványos tokenek, fee-on-transfer), de audit nélkül korlátozott összeggel indulj.
- Nincs oracle-alapú árvédelem: a pool ára arbitrázs útján követi a piacot; kis likviditásnál nagy a csúszás.
- Nincs protokoll-díj (a teljes 0,3% az LP-ké) és nincs upgrade-proxy: új verzió = új telepítés + likviditás-átköltöztetés.
- A Circle-tárcák kulcsait a Circle kezeli; az entity secret + API kulcs kompromittálódása a tárcák feletti
  kontrollt jelenti → a `.env`-et titokkezelőben tartsd, a webapp gépén csak a szükséges jogokkal.
- Az ERC-8183 piactér (ügynök) mainneten csak saját telepítéssel működik; a referencia-implementáció testnet-only.

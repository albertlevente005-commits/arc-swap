"""
Poolok letrehozasa + kezdo likviditas betetele a MEGRENDELO tarcarol.
======================================================================
A poolok es mennyisegek a valto_config.py POOLOK listajaban vannak, a .env-bol
felulirhatok (POOL_USDC_EURC=5000,4600  POOL_USDC_CIRBTC=5000,0.05).

FONTOS: az ELSO beteves aranya hatarozza meg a pool kezdo arat. Mainneten a script
osszeveti a referencia-arfolyammal (EUR/USD: frankfurter.app, BTC/USD: CoinGecko),
es 2% feletti elteresnel nem engedi a betevest (--kenyszerit kapcsoloval igen).

Futtatas (a projektmappabol):
    python pool_feltoltes.py
    python pool_feltoltes.py --igen            # mainnet megerosites nelkul
    python pool_feltoltes.py --kenyszerit      # referencia-ar eltereskor is
"""

import argparse
import sys
import time

import requests
from web3 import Web3

import valto_config as vc
import config
from mag import circle_kliens, lanc, seged

MAX_ELTERES = 0.02  # 2%


def parancssor():
    p = argparse.ArgumentParser(description="ValtoDEX poolok + kezdo likviditas")
    p.add_argument("--igen", action="store_true", help="Nem ker megerositest mainneten")
    p.add_argument("--kenyszerit", action="store_true",
                   help="Akkor is betesz, ha a kezdo ar elter a referenciatol")
    return p.parse_args()


def token_egyenleg(token, cim):
    c = lanc.web3.eth.contract(
        address=Web3.to_checksum_address(vc.TOKENEK[token]["cim"]), abi=vc.ERC20_ABI)
    return vc.egysegbol(token, c.functions.balanceOf(Web3.to_checksum_address(cim)).call())


def referencia_ar(token_a, token_b):
    """Hany token_b er 1 token_a a piacon (None, ha nem tudjuk)."""
    try:
        if {token_a, token_b} == {"USDC", "EURC"}:
            r = requests.get("https://api.frankfurter.app/latest?from=USD&to=EUR", timeout=10)
            usd_eur = float(r.json()["rates"]["EUR"])
            return usd_eur if token_a == "USDC" else 1 / usd_eur
        if {token_a, token_b} == {"USDC", "CIRBTC"}:
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
                             timeout=10)
            btc_usd = float(r.json()["bitcoin"]["usd"])
            return 1 / btc_usd if token_a == "USDC" else btc_usd
    except Exception as e:
        print(f"  (referencia-ar nem elerheto: {e})")
    return None


def main():
    arg = parancssor()
    print(f"=== ValtoDEX - poolok feltoltese: {config.HALOZAT_NEV} ===")
    config.kotelezo("CIRCLE_API_KEY", "CIRCLE_ENTITY_SECRET", "MEGRENDELO_CIM")
    lanc.halozat_ellenorzes()
    if not vc.DEX_CIM:
        raise RuntimeError(f"Nincs {vc.VALTO_CIMEK_JSON.name} - futtasd elobb: python telepit.py")
    print(f"DEX: {vc.DEX_CIM}")

    megrendelo = config.MEGRENDELO_CIM
    dex = lanc.web3.eth.contract(address=Web3.to_checksum_address(vc.DEX_CIM), abi=vc.DEX_ABI)
    tulaj = dex.functions.owner().call()
    zart = dex.functions.poolCreationRestricted().call()
    if dex.functions.paused().call():
        raise RuntimeError("A DEX szunetel (paused) - elobb unpause a tulajdonossal")

    print(f"\nMegrendelo tarca egyenlegei ({seged.rovid(megrendelo)}):")
    egyenlegek = {t: token_egyenleg(t, megrendelo) for t in vc.TOKENEK}
    for t, e in egyenlegek.items():
        print(f"  {t}: {e}")

    print("\nTervezett poolok:")
    for token_a, token_b, kezdo_a, kezdo_b in vc.POOLOK:
        print(f"  {token_a}/{token_b}: {kezdo_a} {token_a} + {kezdo_b} {token_b} "
              f"(kezdo ar: 1 {token_a} = {kezdo_b / kezdo_a:.8g} {token_b})")
    if config.MAINNET and not arg.igen:
        if input("\nELES mainnet, valodi penz. Gepeld be: MAINNET  > ").strip() != "MAINNET":
            print("Megszakitva.")
            return

    hatarido = lambda: str(int(time.time()) + config.TX_HATARIDO_MP)

    for token_a, token_b, kezdo_a, kezdo_b in vc.POOLOK:
        print(f"\n-- {token_a}/{token_b} pool --")
        cim_a, cim_b = vc.TOKENEK[token_a]["cim"], vc.TOKENEK[token_b]["cim"]

        if dex.functions.poolExists(cim_a, cim_b).call():
            pool_id = int(dex.functions.poolIdFor(cim_a, cim_b).call())
            print(f"  Mar letezik (pool ID: {pool_id})")
        else:
            if zart and tulaj.lower() != megrendelo.lower():
                print(f"  A pool letrehozasa a tulajdonos ({tulaj}) joga, a megrendelo nem az. "
                      f"Kihagyom. (Telepitskor --tulajdonos, vagy setPoolCreationRestricted(false).)")
                continue
            circle_kliens.contract_tx(megrendelo, vc.DEX_CIM, "createPool(address,address)",
                                      [cim_a, cim_b], f"{token_a}/{token_b} pool letrehozas")
            pool_id = int(dex.functions.poolIdFor(cim_a, cim_b).call())
            print(f"  Pool ID: {pool_id}")

        p = dex.functions.pools(pool_id).call()
        # a pool tenyleges sorrendje (tokenA/tokenB) elterhet a konfigtol
        if p[0].lower() != cim_a.lower():
            token_a, token_b, kezdo_a, kezdo_b = token_b, token_a, kezdo_b, kezdo_a
        if int(p[4]) > 0:
            print(f"  Mar van benne likviditas ({vc.egysegbol(token_a, p[2])} {token_a} + "
                  f"{vc.egysegbol(token_b, p[3])} {token_b}) - kihagyom a betevest.")
            continue

        if egyenlegek[token_a] < kezdo_a or egyenlegek[token_b] < kezdo_b:
            print(f"  KEVES AZ EGYENLEG a kezdo likviditashoz "
                  f"(kell: {kezdo_a} {token_a} + {kezdo_b} {token_b}). Kihagyom.")
            continue

        ref = referencia_ar(token_a, token_b)
        kezdo_ar = kezdo_b / kezdo_a
        if ref:
            elteres = abs(kezdo_ar / ref - 1)
            print(f"  Kezdo ar: 1 {token_a} = {kezdo_ar:.8g} {token_b} | piaci: {ref:.8g} "
                  f"| elteres: {elteres * 100:.2f}%")
            if elteres > MAX_ELTERES and not arg.kenyszerit:
                print(f"  TUL NAGY ELTERES (> {MAX_ELTERES * 100:.0f}%) - arbitrazs vinne el a penzt. "
                      f"Igazitsd a POOL_{token_a}_{token_b} erteket, vagy --kenyszerit.")
                continue
        elif config.MAINNET and not arg.kenyszerit:
            print("  Nincs referencia-ar, mainneten nem teszek be vakon (--kenyszerit).")
            continue

        egyseg_a = vc.egysegbe(token_a, kezdo_a)
        egyseg_b = vc.egysegbe(token_b, kezdo_b)
        for tok, egys in ((token_a, egyseg_a), (token_b, egyseg_b)):
            circle_kliens.contract_tx(megrendelo, vc.TOKENEK[tok]["cim"],
                                      "approve(address,uint256)", [vc.DEX_CIM, egys],
                                      f"{tok} jovahagyas")
        circle_kliens.contract_tx(
            megrendelo, vc.DEX_CIM,
            "addLiquidity(uint256,uint256,uint256,uint256,uint256,uint256)",
            [str(pool_id), egyseg_a, egyseg_b, egyseg_a, egyseg_b, hatarido()],
            "likviditas betetele")
        seged.esemeny("Pool", f"#{pool_id} {kezdo_a} {token_a} + {kezdo_b} {token_b} ({config.HALOZAT})")
        print(f"  KESZ: {kezdo_a} {token_a} + {kezdo_b} {token_b} a poolban.")

    print("\n=== OSSZEGZES ===")
    for i in range(int(dex.functions.poolCount().call())):
        p = dex.functions.pools(i).call()
        na, nb = vc.token_nev(p[0]), vc.token_nev(p[1])
        if na in vc.TOKENEK and nb in vc.TOKENEK:
            print(f"  Pool #{i}: {vc.egysegbol(na, p[2])} {na}  <->  {vc.egysegbol(nb, p[3])} {nb}")
        else:
            print(f"  Pool #{i}: {p[0]} / {p[1]} (ismeretlen tokenek)")
    print(f"\nKovetkezo lepes: python valto_app.py  ->  http://{config.APP_HOST}:{config.APP_PORT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nHiba: {error}")
        sys.exit(1)

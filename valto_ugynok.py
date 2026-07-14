"""
VALTO-UGYNOK - a piacter valtos ugynoke
========================================
Egy specialis ugynok az arc-platform piacteren, aki [skill:valtas] jobokat
vallal: a sajat USDC keszletebol a ValtoDEX-en atvalt, es a kapott tokent
(EURC vagy cirBTC) elkuldi a megrendelonek. A fizetseget (USDC, escrow-bol)
a munka atvetele utan kapja meg - igy a keszlete visszatoltodik.

Job formatum (a megrendelo/vezerlopult irja ki):
    [skill:valtas be=USDC ki=EURC osszeg=5]

Dijazas: osszeg + 0,5 USDC szolgaltatasi dij.
FIGYELEM: csak be=USDC iranyt vallal (a keszlete USDC-ben van).

Futtatas (cmd, a projektmappabol):
    python valto_ugynok.py
Leallitas: Ctrl+C
"""

import sys
import time

from web3 import Web3

import valto_config as vc
import config
import ugynok  # az arc-platform ugynok-segedfuggvenyei (tarca, identitas, kaucio)
from mag import circle_kliens, lanc, munkak, piacter, regiszter, seged

NEV = "Valto-Ugynok"
SKILLEK = ["valtas"]
SZOLGALTATASI_DIJ = 0.5   # USDC / job
MIN_KESZLET = 2.0         # ennyi USDC keszlet alatt nem vallal jobot

dex = lanc.web3.eth.contract(
    address=Web3.to_checksum_address(vc.DEX_CIM or "0x" + "0" * 40), abi=vc.DEX_ABI)


def pool_kereses(be, ki):
    """Melyik poolban van a (be, ki) par? -> (pool_id, be_cim) vagy None"""
    for i in range(int(dex.functions.poolCount().call())):
        p = dex.functions.pools(i).call()
        cimek = {vc.token_nev(p[0]): p[0], vc.token_nev(p[1]): p[1]}
        if be in cimek and ki in cimek:
            return i, cimek[be]
    return None


def valtas_elvegzese(tarca, megrendelo_cim, p):
    """A tenyleges munka: DEX swap + a kapott token elkuldese a megrendelonek."""
    be = p.get("be", "USDC").upper()
    ki = p.get("ki", "EURC").upper()
    osszeg = float(p.get("osszeg", 1))
    if be != "USDC":
        raise RuntimeError("csak be=USDC iranyt vallalok (a keszletem USDC)")
    if ki not in vc.TOKENEK:
        raise RuntimeError(f"ismeretlen cel token: {ki}")

    talalat = pool_kereses(be, ki)
    if not talalat:
        raise RuntimeError(f"nincs {be}/{ki} pool a DEX-en")
    pool_id, be_cim = talalat

    egyseg_be = vc.egysegbe(be, osszeg)
    ki_egyseg = dex.functions.getQuote(
        pool_id, Web3.to_checksum_address(be_cim), int(egyseg_be)).call()
    min_ki = int(ki_egyseg * 99 // 100)

    seged.esemeny(NEV, f"Valtas: {osszeg} {be} -> ~{vc.egysegbol(ki, ki_egyseg)} {ki} "
                       f"(pool #{pool_id})")
    circle_kliens.contract_tx(tarca.address, vc.TOKENEK[be]["cim"],
                              "approve(address,uint256)", [vc.DEX_CIM, egyseg_be],
                              f"{be} jovahagyas")
    swap_tx = circle_kliens.contract_tx(
        tarca.address, vc.DEX_CIM, "swap(uint256,address,uint256,uint256)",
        [str(pool_id), vc.TOKENEK[be]["cim"], egyseg_be, str(min_ki)], "DEX valtas")

    # a kapott tokent elkuldjuk a megrendelonek
    kuldes_tx = circle_kliens.contract_tx(
        tarca.address, vc.TOKENEK[ki]["cim"], "transfer(address,uint256)",
        [megrendelo_cim, str(ki_egyseg)], f"{ki} kuldese a megrendelonek")

    return {
        "tipus": "valtas", "be": be, "ki": ki,
        "mennyiseg_be": osszeg,
        "mennyiseg_ki": vc.egysegbol(ki, ki_egyseg),
        "arfolyam": round(vc.egysegbol(ki, ki_egyseg) / osszeg, 6) if osszeg else 0,
        "swap_tx": swap_tx, "kuldes_tx": kuldes_tx,
    }


def main():
    print("=" * 60)
    print(f"  VALTO-UGYNOK INDUL (skill: valtas)")
    print("=" * 60)
    if not vc.DEX_CIM:
        print("HIBA: nincs telepitve a ValtoDEX (futtasd: python telepit.py)")
        sys.exit(1)

    tarca = ugynok.tarca_biztositasa(NEV, None)
    ugynok.indulo_usdc(NEV, tarca)
    agent_id = ugynok.identitas_biztositasa(NEV, tarca)
    kaucio = ugynok.kaucio_biztositasa(NEV, tarca)

    bejegyzes = regiszter.ugynokok().get(NEV, {})
    utolso_blokk = int(bejegyzes.get("utolso_blokk", 0)) or (
        lanc.blokkszam() - config.SCAN_VISSZA)
    latott = set(bejegyzes.get("latott_jobok", []))
    figyelt = {int(k): v for k, v in bejegyzes.get("figyelt_jobok", {}).items()}

    def mentes():
        regiszter.ugynok_mentes(NEV, {
            "cim": tarca.address, "tarca_id": tarca.id, "skillek": SKILLEK,
            "agent_id": agent_id, "utolso_blokk": utolso_blokk,
            "latott_jobok": sorted(latott)[-300:],
            "figyelt_jobok": {str(k): v for k, v in figyelt.items()},
        })

    mentes()
    keszlet = float(circle_kliens.usdc_egyenleg(tarca.id) or 0)
    seged.esemeny(NEV, f"Keszen allok. Cim: {seged.rovid(tarca.address)} | "
                       f"USDC keszlet: {keszlet} | Szabad kaucio: {kaucio['szabad']}")
    if keszlet < MIN_KESZLET + 1:
        seged.esemeny(NEV, f"FIGYELEM: keves a keszletem a valtasokhoz - "
                           f"kuldj USDC-t ide: {tarca.address}")

    while True:
        try:
            aktualis = lanc.blokkszam()
            if aktualis > utolso_blokk:
                ujak = lanc.jobok_cimre(tarca.address, utolso_blokk + 1, aktualis)
                utolso_blokk = aktualis
                for job_id, megrendelo_cim in ujak:
                    if job_id in latott:
                        continue
                    latott.add(job_id)
                    j = lanc.job(job_id)
                    if not j or j["statusz_kod"] != 0:
                        continue
                    ertelmezes = munkak.cimke_ertelmezes(j["leiras"])
                    if ertelmezes is None:
                        seged.esemeny(NEV, f"UZENET {seged.rovid(megrendelo_cim)}: "
                                           f"\"{j['leiras'][:100]}\"")
                        continue
                    skill, p, _ = ertelmezes
                    if skill != "valtas":
                        continue
                    osszeg = float(p.get("osszeg", 1))
                    keszlet = float(circle_kliens.usdc_egyenleg(tarca.id) or 0)
                    if keszlet < osszeg + 1:
                        seged.esemeny(NEV, f"Job #{job_id}: keves a keszletem "
                                           f"({keszlet} USDC) - kihagyom")
                        continue
                    ar = round(osszeg + SZOLGALTATASI_DIJ, 2)
                    seged.esemeny(NEV, f"Job #{job_id} FELVEVE (valtas "
                                       f"{p.get('be','USDC')}->{p.get('ki','EURC')} "
                                       f"{osszeg}) - dij: {ar} USDC")
                    try:
                        piacter.dij_beallitas(tarca.address, job_id, ar)
                        figyelt[job_id] = {"parameterek": p, "hibak": 0}
                    except Exception as e:
                        seged.esemeny(NEV, f"Job #{job_id}: dij hiba: {e}")
                mentes()

            for job_id in list(figyelt):
                adat = figyelt[job_id]
                j = lanc.job(job_id)
                if not j:
                    continue
                kod = j["statusz_kod"]

                if kod == 1:  # Feltoltve -> valtas + leadas
                    try:
                        eredmeny = valtas_elvegzese(tarca, j["megrendelo"],
                                                    adat["parameterek"])
                    except Exception as e:
                        adat["hibak"] += 1
                        seged.esemeny(NEV, f"Job #{job_id}: valtas hiba "
                                           f"({adat['hibak']}/3): {e}")
                        if adat["hibak"] >= 3:
                            try:
                                piacter.uzenet_kuldes(tarca.address, j["megrendelo"],
                                                      f"Job #{job_id}: nem sikerult: {e}")
                            except Exception:
                                pass
                            del figyelt[job_id]
                        mentes()
                        continue
                    h = piacter.munka_leadas(tarca.address, job_id, eredmeny)
                    regiszter.eredmeny_mentes(job_id, eredmeny, h, NEV)
                    seged.esemeny(NEV, f"Job #{job_id}: VALTAS LEADVA. {eredmeny}")

                elif kod == 3:
                    seged.esemeny(NEV, f"Job #{job_id}: KIFIZETVE "
                                       f"(+{j['koltsegvetes']} USDC).")
                    del figyelt[job_id]
                    mentes()

                elif kod in (4, 5):
                    del figyelt[job_id]
                    mentes()

            mentes()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            seged.esemeny(NEV, f"Ciklus hiba (megyek tovabb): {e}")
        time.sleep(config.POLL_MP)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nValto-Ugynok leallitva (Ctrl+C).")
    except Exception as error:
        print(f"\nHiba: {error}")
        sys.exit(1)

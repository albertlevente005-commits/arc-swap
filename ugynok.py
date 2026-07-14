"""
AUTONOM UGYNOK DAEMON
=====================
Egy folyamatosan futo ugynok, aki:
  1. gondoskodik a sajat tarcajarol, onchain identitasarol (ERC-8004)
     es kauciojarol (AgentBond),
  2. figyeli a lancot a neki cimzett jobokert (ERC-8183),
  3. a skilljeibe vago jobokra dijat ajanl, elvegzi a VALODI munkat,
     leadja az eredmeny hash-et, es begyujti a fizetseget,
  4. a cimke nelkuli jobokat uzenetkent kezeli (postalada).

Futtatas (cmd, a projektmappabol):
    python ugynok.py --nev Adat-Ugynok --skillek price,fx,top --tarca 0xf195...
    python ugynok.py --nev Elemzo-Ugynok --skillek weather,summary,matek

Ha nincs --tarca es a nev meg nem szerepel a regiszterben, UJ tarcat hoz letre.
Leallitas: Ctrl+C
"""

import argparse
import math
import sys
import time

import config
from mag import boitblance, circle_kliens, lanc, munkak, piacter, regiszter, seged


def parancssor():
    p = argparse.ArgumentParser(description="Autonom ugynok daemon (Arc Testnet)")
    p.add_argument("--nev", required=True, help="Az ugynok neve (pl. Adat-Ugynok)")
    p.add_argument("--skillek", required=True,
                   help="Vesszovel: " + ",".join(munkak.SKILLEK))
    p.add_argument("--tarca", default=None, help="Meglevo tarca cime (opcionalis)")
    p.add_argument("--egyszer", action="store_true",
                   help="Csak egy kort fut (teszteleshez)")
    return p.parse_args()


def tarca_biztositasa(nev, cim_arg):
    """Tarca a regiszterbol / cim alapjan / uj letrehozasa."""
    bejegyzes = regiszter.ugynokok().get(nev, {})
    cim = cim_arg or bejegyzes.get("cim")
    if cim:
        t = circle_kliens.tarca_cim_alapjan(cim)
        return t
    seged.esemeny(nev, "Nincs meg tarcam - ujat hozok letre a Circle-nel...")
    t = circle_kliens.tarca_letrehozas(f"{nev} tarca")
    seged.esemeny(nev, f"Uj tarca: {t.address}")
    return t


def indulo_usdc(nev, tarca):
    """Ha 0 az egyenleg, a megrendelo tarcarol kap indulo USDC-t (gazra)."""
    egyenleg = circle_kliens.usdc_egyenleg(tarca.id)
    if egyenleg in ("0", "?") or float(egyenleg) == 0:
        seged.esemeny(nev, f"0 az egyenlegem - indulo {config.INDULO_USDC} USDC-t kerek "
                           f"a megrendelotol ({seged.rovid(config.MEGRENDELO_CIM)})")
        try:
            circle_kliens.usdc_kuldes(config.MEGRENDELO_CIM, tarca.address,
                                      config.INDULO_USDC)
        except Exception as e:
            seged.esemeny(nev, f"FIGYELEM: nem sikerult indulo USDC-t kapni: {e}")


def identitas_biztositasa(nev, tarca):
    """Agent ID a regiszterbol, vagy uj ERC-8004 regisztracio."""
    bejegyzes = regiszter.ugynokok().get(nev, {})
    if bejegyzes.get("agent_id"):
        return int(bejegyzes["agent_id"])
    seged.esemeny(nev, "Onchain identitas regisztralasa (ERC-8004)...")
    agent_id = piacter.identitas_regisztralas(tarca.address)
    seged.esemeny(nev, f"Identitas kesz. Agent ID: {agent_id}")
    return agent_id


def kaucio_biztositasa(nev, tarca):
    """Ha a szabad kaucio a minimum alatt van, feltolti (amennyire az egyenleg engedi)."""
    allapot = lanc.kaucio_allapot(tarca.address)
    if allapot["szabad"] >= config.MIN_KAUCIO:
        return allapot
    hiany = math.ceil(config.MIN_KAUCIO - allapot["szabad"])
    try:
        egyenleg = float(circle_kliens.usdc_egyenleg(tarca.id))
    except ValueError:
        egyenleg = 0.0
    befizetes = min(hiany, max(0.0, egyenleg - 1.0))  # 1 USDC marad gazra
    if befizetes <= 0:
        seged.esemeny(nev, f"FIGYELEM: keves a szabad kaucio ({allapot['szabad']} USDC) "
                           f"es nincs mibol feltolteni. A megrendelok kihagyhatnak!")
        return allapot
    seged.esemeny(nev, f"Kaucio feltoltese: +{befizetes} USDC (AgentBond)...")
    boitblance.kaucio_befizetes(tarca.address, befizetes)
    return lanc.kaucio_allapot(tarca.address)


def main():
    arg = parancssor()
    nev = arg.nev
    skillek = [s.strip().lower() for s in arg.skillek.split(",") if s.strip()]
    ismeretlen = [s for s in skillek if s not in munkak.SKILLEK]
    if ismeretlen:
        print(f"Ismeretlen skill(ek): {ismeretlen}. Valaszthato: {list(munkak.SKILLEK)}")
        sys.exit(1)

    print("=" * 60)
    print(f"  UGYNOK INDUL: {nev}")
    print(f"  Skillek: {', '.join(skillek)}")
    print("=" * 60)

    # ----- 1. Onallo felkeszules -----
    tarca = tarca_biztositasa(nev, arg.tarca)
    indulo_usdc(nev, tarca)
    agent_id = identitas_biztositasa(nev, tarca)
    kaucio = kaucio_biztositasa(nev, tarca)

    bejegyzes = regiszter.ugynokok().get(nev, {})
    utolso_blokk = int(bejegyzes.get("utolso_blokk", 0)) or (
        lanc.blokkszam() - config.SCAN_VISSZA)
    latott = set(bejegyzes.get("latott_jobok", []))
    figyelt = {int(k): v for k, v in bejegyzes.get("figyelt_jobok", {}).items()}

    def mentes():
        regiszter.ugynok_mentes(nev, {
            "cim": tarca.address, "tarca_id": tarca.id, "skillek": skillek,
            "agent_id": agent_id, "utolso_blokk": utolso_blokk,
            "latott_jobok": sorted(latott)[-300:],
            "figyelt_jobok": {str(k): v for k, v in figyelt.items()},
        })

    mentes()
    seged.esemeny(nev, f"Keszen allok. Cim: {seged.rovid(tarca.address)} | "
                       f"Agent ID: {agent_id} | Szabad kaucio: {kaucio['szabad']} USDC | "
                       f"Figyeles a(z) {utolso_blokk}. blokktol")

    # ----- 2. Fo ciklus: lancfigyeles + munkavegzes -----
    while True:
        try:
            # --- uj jobok keresese ---
            aktualis = lanc.blokkszam()
            if aktualis > utolso_blokk:
                ujak = lanc.jobok_cimre(tarca.address, utolso_blokk + 1, aktualis)
                utolso_blokk = aktualis
                for job_id, megrendelo in ujak:
                    if job_id in latott:
                        continue
                    latott.add(job_id)
                    j = lanc.job(job_id)
                    if not j:
                        continue
                    ertelmezes = munkak.cimke_ertelmezes(j["leiras"])
                    if ertelmezes is None:
                        # nincs skill cimke -> ez egy uzenet (postalada)
                        seged.esemeny(nev, f"UZENET erkezett {seged.rovid(megrendelo)} "
                                           f"cimrol: \"{j['leiras'][:120]}\"",
                                      tipus="uzenet", job_id=job_id)
                        continue
                    skill, parameterek, szoveg = ertelmezes
                    if skill not in skillek:
                        seged.esemeny(nev, f"Job #{job_id} ({skill}) nem az en skillem"
                                           " - kihagyom")
                        continue
                    if j["statusz_kod"] != 0:  # csak Nyitott
                        continue
                    ar = config.SKILL_ARAK.get(skill, 1.0)
                    seged.esemeny(nev, f"Job #{job_id} FELVEVE ({skill}) - "
                                       f"dijajanlat: {ar} USDC", tipus="job_felvetel",
                                  job_id=job_id)
                    try:
                        piacter.dij_beallitas(tarca.address, job_id, ar)
                        figyelt[job_id] = {"skill": skill, "parameterek": parameterek,
                                           "szoveg": szoveg, "hibak": 0}
                    except Exception as e:
                        seged.esemeny(nev, f"Job #{job_id}: dij beallitas hiba: {e}")
                mentes()

            # --- figyelt jobok leptetese a lanc-statusz szerint ---
            for job_id in list(figyelt):
                adat = figyelt[job_id]
                j = lanc.job(job_id)
                if not j:
                    continue
                kod = j["statusz_kod"]

                if kod == 1:  # Feltoltve -> MUNKA + leadas
                    seged.esemeny(nev, f"Job #{job_id}: escrow feltoltve - "
                                       f"vegzem a munkat ({adat['skill']})...")
                    try:
                        eredmeny = munkak.munka_elvegzes(
                            adat["skill"], adat["parameterek"], adat["szoveg"])
                    except Exception as e:
                        adat["hibak"] += 1
                        seged.esemeny(nev, f"Job #{job_id}: munka hiba "
                                           f"({adat['hibak']}/3): {e}")
                        if adat["hibak"] >= 3:
                            try:
                                piacter.uzenet_kuldes(
                                    tarca.address, j["megrendelo"],
                                    f"Job #{job_id}: sajnos nem sikerult elvegezni: {e}")
                            except Exception:
                                pass
                            del figyelt[job_id]
                        mentes()
                        continue
                    h = piacter.munka_leadas(tarca.address, job_id, eredmeny)
                    regiszter.eredmeny_mentes(job_id, eredmeny, h, nev)
                    seged.esemeny(nev, f"Job #{job_id}: MUNKA LEADVA. "
                                       f"Eredmeny: {eredmeny}", tipus="leadas",
                                  job_id=job_id, hash=h)

                elif kod == 3:  # Kesz -> fizetseg megjott
                    seged.esemeny(nev, f"Job #{job_id}: KIFIZETVE (+"
                                       f"{j['koltsegvetes']} USDC). Koszonom!",
                                  tipus="kifizetes", job_id=job_id,
                                  usdc=j["koltsegvetes"])
                    del figyelt[job_id]
                    mentes()

                elif kod in (4, 5):  # Elutasitva / Lejart
                    seged.esemeny(nev, f"Job #{job_id}: {j['statusz']} - elengedem")
                    del figyelt[job_id]
                    mentes()

            # eletjel a regiszterbe
            mentes()

        except KeyboardInterrupt:
            raise
        except Exception as e:
            seged.esemeny(nev, f"Ciklus hiba (megyek tovabb): {e}")

        if arg.egyszer:
            seged.esemeny(nev, "Egy kor kesz (--egyszer), kilepes.")
            break
        time.sleep(config.POLL_MP)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nUgynok leallitva (Ctrl+C).")
    except Exception as error:
        print(f"\nHiba: {error}")
        sys.exit(1)

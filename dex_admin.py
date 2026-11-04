"""
ValtoDEX tulajdonosi muveletek (uzemeltetes / incidens-kezeles) a Circle tarcaval.
==================================================================================
A TELEPITO_CIM (a szerzodes tulajdonosa) neveben hajtja vegre.

    python dex_admin.py allapot                       # tulajdonos, szunetel-e, poolok
    python dex_admin.py pause                         # swap + beteves LEALLITASA (kivetel marad)
    python dex_admin.py unpause
    python dex_admin.py poolok-nyitasa | poolok-zarasa
    python dex_admin.py pool USDC EURC                # uj pool letrehozasa (tulajdonos)
    python dex_admin.py tulajdonos-atadas 0x...       # 1. lepes (az uj tulaj acceptOwnership-et hiv)
    python dex_admin.py tulajdonos-elfogadas          # 2. lepes (az uj tulaj = TELEPITO_CIM)
"""

import argparse
import sys

from web3 import Web3

import valto_config as vc
import config
from mag import circle_kliens, lanc, seged


def main():
    p = argparse.ArgumentParser(description="ValtoDEX tulajdonosi muveletek")
    p.add_argument("parancs", choices=["allapot", "pause", "unpause", "poolok-nyitasa",
                                       "poolok-zarasa", "pool", "tulajdonos-atadas",
                                       "tulajdonos-elfogadas"])
    p.add_argument("argumentumok", nargs="*")
    p.add_argument("--igen", action="store_true", help="Nem ker megerositest")
    arg = p.parse_args()

    lanc.halozat_ellenorzes()
    if not vc.DEX_CIM:
        raise RuntimeError(f"Nincs telepitett DEX ({vc.VALTO_CIMEK_JSON.name})")
    dex = lanc.web3.eth.contract(address=Web3.to_checksum_address(vc.DEX_CIM), abi=vc.DEX_ABI)
    tulaj = dex.functions.owner().call()
    print(f"{config.HALOZAT_NEV} | DEX {vc.DEX_CIM} | tulajdonos {tulaj} | "
          f"szunetel={dex.functions.paused().call()} | "
          f"zart poolok={dex.functions.poolCreationRestricted().call()}")

    if arg.parancs == "allapot":
        for i in range(int(dex.functions.poolCount().call())):
            q = dex.functions.pools(i).call()
            print(f"  pool #{i}: {vc.token_nev(q[0])}/{vc.token_nev(q[1])} "
                  f"{vc.egysegbol(vc.token_nev(q[0]), q[2]) if vc.token_nev(q[0]) in vc.TOKENEK else q[2]} / "
                  f"{vc.egysegbol(vc.token_nev(q[1]), q[3]) if vc.token_nev(q[1]) in vc.TOKENEK else q[3]} "
                  f"shares={q[4]}")
        pend = dex.functions.pendingOwner().call()
        if int(pend, 16):
            print(f"  fuggo tulajdonos-atadas: {pend}")
        return

    config.kotelezo("CIRCLE_API_KEY", "CIRCLE_ENTITY_SECRET", "TELEPITO_CIM")
    kuldo = config.TELEPITO_CIM
    if arg.parancs != "tulajdonos-elfogadas" and kuldo.lower() != tulaj.lower():
        raise RuntimeError(f"A TELEPITO_CIM ({kuldo}) nem a tulajdonos ({tulaj})")

    if arg.parancs == "pause":
        szig, par, cimke = "pause()", [], "DEX szuneteltetes"
    elif arg.parancs == "unpause":
        szig, par, cimke = "unpause()", [], "DEX folytatas"
    elif arg.parancs == "poolok-nyitasa":
        szig, par, cimke = "setPoolCreationRestricted(bool)", [False], "poolok nyitasa"
    elif arg.parancs == "poolok-zarasa":
        szig, par, cimke = "setPoolCreationRestricted(bool)", [True], "poolok zarasa"
    elif arg.parancs == "pool":
        if len(arg.argumentumok) != 2 or any(t.upper() not in vc.TOKENEK for t in arg.argumentumok):
            raise RuntimeError(f"pool <A> <B>, ahol A/B: {list(vc.TOKENEK)}")
        a, b = (vc.TOKENEK[t.upper()]["cim"] for t in arg.argumentumok)
        szig, par, cimke = "createPool(address,address)", [a, b], "pool letrehozas"
    elif arg.parancs == "tulajdonos-atadas":
        if len(arg.argumentumok) != 1 or not Web3.is_address(arg.argumentumok[0]):
            raise RuntimeError("tulajdonos-atadas <0x uj tulajdonos>")
        szig, par, cimke = "transferOwnership(address)", [arg.argumentumok[0]], "tulajdonos atadas"
    else:
        szig, par, cimke = "acceptOwnership()", [], "tulajdonos elfogadas"

    print(f"-> {cimke}: {szig} {par}  (kuldo: {kuldo})")
    if config.MAINNET and not arg.igen:
        if input("ELES mainnet. Gepeld be: MAINNET  > ").strip() != "MAINNET":
            print("Megszakitva.")
            return
    tx = circle_kliens.contract_tx(kuldo, vc.DEX_CIM, szig, par, cimke)
    seged.esemeny("Admin", f"{cimke} {config.EXPLORER_TX}{tx}")
    print(f"KESZ: {config.EXPLORER_TX}{tx}")
    print(f"szunetel={dex.functions.paused().call()} zart poolok="
          f"{dex.functions.poolCreationRestricted().call()} tulajdonos={dex.functions.owner().call()}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nHiba: {error}")
        sys.exit(1)

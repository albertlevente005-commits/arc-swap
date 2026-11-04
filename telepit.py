"""
ValtoDEX telepitese az Arc halozatra (Circle Smart Contract Platform).
=====================================================================
A halozatot az ARC_HALOZAT valasztja (mainnet / testnet), a telepito tarca a
TELEPITO_CIM (.env). A telepito tarca lesz a szerzodes TULAJDONOSA (pause,
pool-letrehozas joga) - mainneten ezt a tarcat kulon ovd.

Futtatas (a projektmappabol):
    python telepit.py            # mainneten kozben meg kell erositeni
    python telepit.py --igen     # megerosites nelkul (CI / automatizalas)
    python telepit.py --nyitott-poolok   # barki hozhat letre poolt (alap: csak a tulajdonos)
"""

import argparse
import json
import sys
import time

from web3 import Web3

import valto_config as vc
import config
from mag import lanc, seged


def parancssor():
    p = argparse.ArgumentParser(description="ValtoDEX telepitese az Arc-ra (Circle SCP)")
    p.add_argument("--igen", action="store_true", help="Nem ker megerositest mainneten")
    p.add_argument("--nyitott-poolok", action="store_true",
                   help="Barki hozhat letre poolt (alap: csak a tulajdonos)")
    p.add_argument("--tulajdonos", default=None,
                   help="A szerzodes tulajdonosa (alap: a telepito tarca)")
    return p.parse_args()


def main():
    arg = parancssor()
    print(f"=== ValtoDEX telepitese: {config.HALOZAT_NEV} (chain {config.CHAIN_ID}) ===")
    config.kotelezo("CIRCLE_API_KEY", "CIRCLE_ENTITY_SECRET", "TELEPITO_CIM")
    lanc.halozat_ellenorzes()

    build = vc.GYOKER / "build" / "ValtoDEX.json"
    if not build.exists():
        raise RuntimeError("Nincs build/ValtoDEX.json - futtasd elobb: npm install && node compile.js")
    art = json.loads(build.read_text(encoding="utf-8"))
    if not any(f.get("type") == "constructor" and len(f.get("inputs", [])) == 2 for f in art["abi"]):
        raise RuntimeError("A build elavult (nincs 2 parameteres constructor) - forditsd ujra: node compile.js")

    if vc.DEX_CIM:
        print(f"FIGYELEM: mar van telepitett DEX ezen a halozaton: {vc.DEX_CIM} "
              f"({vc.VALTO_CIMEK_JSON.name}). Uj telepitessel FELULIRODIK a cimfajl.")

    tulajdonos = Web3.to_checksum_address(arg.tulajdonos or config.TELEPITO_CIM)
    zart_poolok = not arg.nyitott_poolok
    print(f"Telepito tarca : {config.TELEPITO_CIM}")
    print(f"Tulajdonos     : {tulajdonos}")
    print(f"Pool letrehozas: {'csak tulajdonos' if zart_poolok else 'BARKI'}")
    print(f"Fordito        : {art.get('compiler', '?')}")

    if config.MAINNET and not arg.igen:
        valasz = input("\nEz az ELES Arc mainnet - valodi USDC-be kerul. Gepeld be: MAINNET  > ")
        if valasz.strip() != "MAINNET":
            print("Megszakitva.")
            return

    from circle.web3 import utils, smart_contract_platform, developer_controlled_wallets

    scp = utils.init_smart_contract_platform_client(
        api_key=config.CIRCLE_API_KEY, entity_secret=config.CIRCLE_ENTITY_SECRET)
    deploy_api = smart_contract_platform.DeployImportApi(scp)
    view_api = smart_contract_platform.ViewUpdateApi(scp)
    dcw = utils.init_developer_controlled_wallets_client(
        api_key=config.CIRCLE_API_KEY, entity_secret=config.CIRCLE_ENTITY_SECRET)
    wallets_api = developer_controlled_wallets.WalletsApi(dcw)

    wallet_id = None
    for w in seged.retry(lambda: wallets_api.get_wallets(
            blockchain=developer_controlled_wallets.Blockchain(config.LANC)),
            "tarcak lekerese").data.wallets or []:
        wallet = getattr(w, "actual_instance", w)
        if wallet.address.lower() == config.TELEPITO_CIM.lower():
            wallet_id = wallet.id
            break
    if not wallet_id:
        raise RuntimeError(f"Nem talalhato a telepito tarca a Circle-nel ({config.LANC}): "
                           f"{config.TELEPITO_CIM}. Mainneten a Circle Console LIVE "
                           f"kornyezeteben kell lennie a tarcanak es az API kulcsnak.")

    usdc = lanc.web3.eth.contract(address=Web3.to_checksum_address(config.USDC), abi=vc.ERC20_ABI)
    gaz = usdc.functions.balanceOf(Web3.to_checksum_address(config.TELEPITO_CIM)).call() / 1e6
    print(f"Telepito USDC egyenlege (gaz): {gaz}")
    if gaz < 0.5:
        raise RuntimeError("Keves USDC a telepito tarcan a gazhoz (min. ~0,5 USDC)")

    req = smart_contract_platform.ContractDeploymentRequest.from_dict({
        "name": "ValtoDEX",
        "description": f"AMM exchange on {config.HALOZAT_NEV}",
        "walletId": wallet_id,
        "blockchain": config.LANC,
        "abiJson": json.dumps(art["abi"]),
        "bytecode": art["bytecode"],
        "constructorParameters": [tulajdonos, zart_poolok],
        "feeLevel": "MEDIUM",
    })
    resp = seged.retry(lambda: deploy_api.deploy_contract(contract_deployment_request=req),
                       "telepites inditasa", probak=3)
    contract_id = resp.data.contract_id
    print(f"Contract ID: {contract_id}  (telepites folyamatban...)")

    cim, tx_hash = None, None
    for _ in range(100):
        time.sleep(3)
        try:
            c = view_api.get_contract(id=contract_id).data.contract
        except Exception:
            print("x", end="", flush=True)
            continue
        if c.contract_address:
            cim, tx_hash = c.contract_address, c.tx_hash
            print(f"\nOK -> {cim}")
            if tx_hash:
                print(f"Tx: {config.EXPLORER_TX}{tx_hash}")
            break
        if getattr(c, "deployment_error_reason", None):
            raise RuntimeError(f"Telepites hiba: {c.deployment_error_reason}")
        print(".", end="", flush=True)
    if not cim:
        raise RuntimeError("Telepites idotullepes - nezd meg a Circle Console-ban a contract allapotat")

    # lancon ellenorzes: van kod, es a tulajdonos az, akit kertunk
    dex = lanc.web3.eth.contract(address=Web3.to_checksum_address(cim), abi=art["abi"])
    for _ in range(20):
        if len(lanc.web3.eth.get_code(Web3.to_checksum_address(cim))) > 10:
            break
        time.sleep(2)
    lanc_tulaj = dex.functions.owner().call()
    if lanc_tulaj.lower() != tulajdonos.lower():
        raise RuntimeError(f"A lancon a tulajdonos {lanc_tulaj}, nem {tulajdonos}!")
    print(f"Ellenorizve: owner={lanc_tulaj} poolCreationRestricted="
          f"{dex.functions.poolCreationRestricted().call()}")

    vc.VALTO_CIMEK_JSON.write_text(json.dumps({
        "ValtoDEX": cim, "chainId": config.CHAIN_ID, "halozat": config.HALOZAT,
        "owner": lanc_tulaj, "txHash": tx_hash, "circleContractId": contract_id,
        "compiler": art.get("compiler"), "telepites": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=2), encoding="utf-8")
    seged.esemeny("Telepites", f"ValtoDEX {cim} ({config.HALOZAT_NEV})")
    print(f"\n=== KESZ - ValtoDEX: {cim} ===")
    print(f"Cim elmentve: {vc.VALTO_CIMEK_JSON}  (commitold a repoba!)")
    print("Kovetkezo lepes: python pool_feltoltes.py")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nHiba: {error}")
        sys.exit(1)

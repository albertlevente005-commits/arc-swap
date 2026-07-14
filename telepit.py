"""
ValtoDEX telepitese az Arc Testnetre (Circle Smart Contract Platform).
A telepito tarca a 0x774E... (ugyanaz, mint a BoitBlance-nel) - legyen rajta
egy kis USDC a gazra.

Futtatas (cmd, a projektmappabol):
    python telepit.py
"""

import json
import time

import valto_config as vc
import config
from mag import seged

from circle.web3 import utils, smart_contract_platform, developer_controlled_wallets

BLOCKCHAIN = "ARC-TESTNET"


def main():
    print("=== ValtoDEX telepitese az Arc Testnetre ===")

    if not (vc.GYOKER / "build" / "ValtoDEX.json").exists():
        raise RuntimeError("Nincs build/ValtoDEX.json - futtasd elobb: node compile.js")

    scp = utils.init_smart_contract_platform_client(
        api_key=config.CIRCLE_API_KEY, entity_secret=config.CIRCLE_ENTITY_SECRET)
    deploy_api = smart_contract_platform.DeployImportApi(scp)
    view_api = smart_contract_platform.ViewUpdateApi(scp)

    dcw = utils.init_developer_controlled_wallets_client(
        api_key=config.CIRCLE_API_KEY, entity_secret=config.CIRCLE_ENTITY_SECRET)
    wallets_api = developer_controlled_wallets.WalletsApi(dcw)

    # telepito tarca ID
    telepito = config.TELEPITO_CIM
    wallet_id = None
    for w in wallets_api.get_wallets().data.wallets or []:
        wallet = getattr(w, "actual_instance", w)
        if wallet.address.lower() == telepito.lower():
            wallet_id = wallet.id
            break
    if not wallet_id:
        raise RuntimeError(f"Nem talalhato a telepito tarca: {telepito}")
    print(f"Telepito tarca: {telepito}")

    art = json.load(open(vc.GYOKER / "build" / "ValtoDEX.json", encoding="utf-8"))
    req = smart_contract_platform.ContractDeploymentRequest.from_dict({
        "name": "ValtoDEX",
        "description": "Simple AMM exchange on Arc Testnet",
        "walletId": wallet_id,
        "blockchain": BLOCKCHAIN,
        "abiJson": json.dumps(art["abi"]),
        "bytecode": art["bytecode"],
        "constructorParameters": [],   # a ValtoDEX-nek nincs constructor parametere
        "feeLevel": "MEDIUM",
    })
    resp = deploy_api.deploy_contract(contract_deployment_request=req)
    contract_id = resp.data.contract_id
    print(f"Contract ID: {contract_id}  (telepites folyamatban...)")

    cim = None
    for _ in range(60):
        time.sleep(3)
        c = view_api.get_contract(id=contract_id).data.contract
        if c.contract_address:
            cim = c.contract_address
            print(f"OK -> {cim}")
            if c.tx_hash:
                print(f"Tx: {config.EXPLORER_TX}{c.tx_hash}")
            break
        if getattr(c, "deployment_error_reason", None):
            raise RuntimeError(f"Telepites hiba: {c.deployment_error_reason}")
        print(".", end="", flush=True)
    if not cim:
        raise RuntimeError("Telepites idotullepes")

    vc.VALTO_CIMEK_JSON.write_text(json.dumps(
        {"ValtoDEX": cim, "chainId": 5042002}, indent=2), encoding="utf-8")
    print(f"\n=== KESZ - ValtoDEX: {cim} ===")
    print(f"Cim elmentve: {vc.VALTO_CIMEK_JSON}")
    print("Kovetkezo lepes: python pool_feltoltes.py")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nHiba: {error}")

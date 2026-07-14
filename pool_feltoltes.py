"""
Poolok letrehozasa + kezdo likviditas betetele a MEGRENDELO tarcarol.

A tervezett poolok es mennyisegek a valto_config.py POOLOK listajaban vannak:
    USDC/EURC   : 20 USDC + 18,5 EURC
    USDC/CIRBTC : 10 USDC + 0,0001 cirBTC

Ha valamelyik tokenbol nincs eleg a megrendelo tarcan (0xfd38...), a script
kihagyja azt a poolt, es megmondja, honnan potolhatod:
  - USDC/EURC: https://faucet.circle.com (Arc Testnet, USDC vagy EURC)
  - cirBTC:    Circle Console faucet, vagy kuldj at a MetaMask tarcadbol

Futtatas (cmd, a projektmappabol):
    python pool_feltoltes.py
"""

import valto_config as vc
import config
from web3 import Web3

from mag import circle_kliens, lanc, seged


def token_egyenleg(token, cim):
    c = lanc.web3.eth.contract(
        address=Web3.to_checksum_address(vc.TOKENEK[token]["cim"]), abi=vc.ERC20_ABI)
    return vc.egysegbol(token, c.functions.balanceOf(
        Web3.to_checksum_address(cim)).call())


def main():
    print("=== ValtoDEX - poolok feltoltese ===")
    if not vc.DEX_CIM:
        raise RuntimeError("Nincs valto_cimek.json - futtasd elobb: python telepit.py")
    print(f"DEX: {vc.DEX_CIM}")

    megrendelo = config.MEGRENDELO_CIM
    dex = lanc.web3.eth.contract(
        address=Web3.to_checksum_address(vc.DEX_CIM), abi=vc.DEX_ABI)

    print(f"\nMegrendelo tarca egyenlegei ({seged.rovid(megrendelo)}):")
    egyenlegek = {}
    for token in vc.TOKENEK:
        egyenlegek[token] = token_egyenleg(token, megrendelo)
        print(f"  {token}: {egyenlegek[token]}")

    meglevo_poolok = int(dex.functions.poolCount().call())
    print(f"\nMeglevo poolok a DEX-en: {meglevo_poolok}")

    for token_a, token_b, kezdo_a, kezdo_b in vc.POOLOK:
        print(f"\n-- {token_a}/{token_b} pool --")

        # van-e mar ilyen pool?
        pool_id = None
        for i in range(int(dex.functions.poolCount().call())):
            p = dex.functions.pools(i).call()
            if (p[0].lower() == vc.TOKENEK[token_a]["cim"].lower()
                    and p[1].lower() == vc.TOKENEK[token_b]["cim"].lower()):
                pool_id = i
                break

        if pool_id is None:
            circle_kliens.contract_tx(
                megrendelo, vc.DEX_CIM, "createPool(address,address)",
                [vc.TOKENEK[token_a]["cim"], vc.TOKENEK[token_b]["cim"]],
                f"{token_a}/{token_b} pool letrehozas")
            pool_id = int(dex.functions.poolCount().call()) - 1
            print(f"  Pool ID: {pool_id}")
        else:
            print(f"  Mar letezik (pool ID: {pool_id})")

        p = dex.functions.pools(pool_id).call()
        if int(p[4]) > 0:
            print(f"  Mar van benne likviditas "
                  f"({vc.egysegbol(token_a, p[2])} {token_a} + "
                  f"{vc.egysegbol(token_b, p[3])} {token_b}) - kihagyom a betevest.")
            continue

        if egyenlegek[token_a] < kezdo_a or egyenlegek[token_b] < kezdo_b:
            print(f"  KEVES AZ EGYENLEG a kezdo likviditashoz "
                  f"(kell: {kezdo_a} {token_a} + {kezdo_b} {token_b}).")
            print(f"  Potlas: faucet.circle.com -> {megrendelo}")
            if token_b == "CIRBTC" or token_a == "CIRBTC":
                print("  (cirBTC: Circle Console faucet, vagy kuldj at a MetaMaskbol)")
            continue

        egyseg_a = vc.egysegbe(token_a, kezdo_a)
        egyseg_b = vc.egysegbe(token_b, kezdo_b)
        circle_kliens.contract_tx(megrendelo, vc.TOKENEK[token_a]["cim"],
                                  "approve(address,uint256)", [vc.DEX_CIM, egyseg_a],
                                  f"{token_a} jovahagyas")
        circle_kliens.contract_tx(megrendelo, vc.TOKENEK[token_b]["cim"],
                                  "approve(address,uint256)", [vc.DEX_CIM, egyseg_b],
                                  f"{token_b} jovahagyas")
        circle_kliens.contract_tx(
            megrendelo, vc.DEX_CIM, "addLiquidity(uint256,uint256,uint256)",
            [str(pool_id), egyseg_a, egyseg_b], "likviditas betetele")
        print(f"  KESZ: {kezdo_a} {token_a} + {kezdo_b} {token_b} a poolban.")

    print("\n=== OSSZEGZES ===")
    for i in range(int(dex.functions.poolCount().call())):
        p = dex.functions.pools(i).call()
        na, nb = vc.token_nev(p[0]), vc.token_nev(p[1])
        print(f"  Pool #{i}: {vc.egysegbol(na, p[2])} {na}  <->  "
              f"{vc.egysegbol(nb, p[3])} {nb}")
    print("\nKovetkezo lepes: python valto_app.py  ->  http://127.0.0.1:5060")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nHiba: {error}")

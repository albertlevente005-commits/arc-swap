"""
Circle Developer-Controlled Wallets kliens - kozos reteg.
Minden alairas a Circle API-n keresztul tortenik (privat kulcs nelkul).
"""

import time

import config
from mag import seged

_kliens = None
_wallets_api = None
_tx_api = None
_sets_api = None


def kliens():
    """Lusta inicializalas - csak az elso hasznalatkor csatlakozik."""
    global _kliens, _wallets_api, _tx_api, _sets_api
    if _kliens is None:
        if not config.CIRCLE_API_KEY or not config.CIRCLE_ENTITY_SECRET:
            raise RuntimeError(
                "Hianyzik a CIRCLE_API_KEY / CIRCLE_ENTITY_SECRET. "
                "Ellenorizd a .env fajlt (erc8004-quickstart mappaban is lehet).")
        from circle.web3 import developer_controlled_wallets, utils
        _kliens = utils.init_developer_controlled_wallets_client(
            api_key=config.CIRCLE_API_KEY,
            entity_secret=config.CIRCLE_ENTITY_SECRET)
        _wallets_api = developer_controlled_wallets.WalletsApi(_kliens)
        _tx_api = developer_controlled_wallets.TransactionsApi(_kliens)
        _sets_api = developer_controlled_wallets.WalletSetsApi(_kliens)
    return _kliens


def _dcw():
    kliens()
    from circle.web3 import developer_controlled_wallets
    return developer_controlled_wallets


# ---------- Tarcak ----------

def osszes_tarca():
    kliens()
    resp = seged.retry(lambda: _wallets_api.get_wallets(), "tarcak lekerese")
    tarcak = []
    for w in resp.data.wallets or []:
        tarcak.append(getattr(w, "actual_instance", w))
    return tarcak


def tarca_cim_alapjan(cim):
    for t in osszes_tarca():
        if t.address.lower() == cim.lower():
            return t
    raise RuntimeError(f"Nem talalhato tarca ezzel a cimmel: {cim}")


def tarca_letrehozas(megnevezes="arc-platform tarca"):
    """Uj tarca a mar meglevo wallet set-ben (ha nincs, ujat hoz letre)."""
    dcw = _dcw()
    set_id = None
    for t in osszes_tarca():
        set_id = getattr(t, "wallet_set_id", None)
        if set_id:
            break
    if not set_id:
        ws = seged.retry(lambda: _sets_api.create_wallet_set(
            dcw.CreateWalletSetRequest.from_dict({"name": "Arc Platform"})),
            "wallet set letrehozas")
        set_id = ws.data.wallet_set.actual_instance.id
    resp = seged.retry(lambda: _wallets_api.create_wallet(
        dcw.CreateWalletRequest.from_dict({
            "blockchains": [config.LANC], "count": 1,
            "walletSetId": set_id, "accountType": "SCA"})),
        "tarca letrehozas")
    uj = resp.data.wallets[0]
    return getattr(uj, "actual_instance", uj)


def usdc_egyenleg(tarca_id):
    """A tarca USDC egyenlege (string, pl. '4.5'). Hibanal '?'."""
    kliens()
    try:
        balances = seged.retry(
            lambda: _wallets_api.list_wallet_balance(id=tarca_id), "egyenleg")
    except Exception:
        return "?"
    for entry in balances.data.token_balances or []:
        b = getattr(entry, "actual_instance", entry)
        token = getattr(b, "token", None)
        token = getattr(token, "actual_instance", token)
        if token and getattr(token, "symbol", None) == "USDC":
            return getattr(b, "amount", "0")
    return "0"


# ---------- Tranzakciok ----------

def _varakozas(tx_id, cimke, max_kor=90):
    """Megvarja, amig a Circle tranzakcio felkerul a lancra. Visszaadja a tx hash-t."""
    kliens()
    seged.kiir(f"    Varakozas: {cimke}", veg="")
    for _ in range(max_kor):
        time.sleep(2)
        try:
            tx = _tx_api.get_transaction(id=tx_id)
        except Exception:
            seged.kiir("x", veg="")
            continue
        t = tx.data.transaction
        if t.state == "COMPLETE" and t.tx_hash:
            seged.kiir(f" OK ({t.tx_hash[:14]}...)")
            return t.tx_hash
        if t.state in ("FAILED", "DENIED", "CANCELLED"):
            seged.kiir(" HIBA")
            raise RuntimeError(f"{cimke}: a tranzakcio hibazott a lancon ({t.state})")
        seged.kiir(".", veg="")
    raise RuntimeError(f"{cimke}: idotullepes")


def contract_tx(tarca_cim, szerzodes_cim, szignatura, parameterek, cimke):
    """Okosszerzodes-hivas a megadott tarcarol. Visszaadja a tx hash-t."""
    dcw = _dcw()

    def kuldes():
        req = dcw.CreateContractExecutionTransactionForDeveloperRequest.from_dict({
            "walletAddress": tarca_cim, "blockchain": config.LANC,
            "contractAddress": szerzodes_cim, "abiFunctionSignature": szignatura,
            "abiParameters": parameterek, "feeLevel": "MEDIUM"})
        return _tx_api.create_developer_transaction_contract_execution(req)

    resp = seged.retry(kuldes, cimke)
    return _varakozas(resp.data.id, cimke)


def usdc_kuldes(honnan_cim, hova_cim, mennyi_usdc):
    """USDC utalas ket cim kozott. Visszaadja a tx hash-t."""
    dcw = _dcw()

    def kuldes():
        req = dcw.CreateTransferTransactionForDeveloperRequest.from_dict({
            "walletAddress": honnan_cim, "blockchain": config.LANC,
            "tokenAddress": config.USDC, "destinationAddress": hova_cim,
            "amounts": [str(mennyi_usdc)], "feeLevel": "MEDIUM"})
        return _tx_api.create_developer_transaction_transfer(
            create_transfer_transaction_for_developer_request=req)

    resp = seged.retry(kuldes, "USDC utalas")
    return _varakozas(resp.data.id, f"USDC utalas ({mennyi_usdc})")

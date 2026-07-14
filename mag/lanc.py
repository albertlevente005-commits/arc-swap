"""
Lanc-olvaso reteg: web3 kapcsolat, ABI-k, csak-olvaso lekerdezesek.
(Az iro muveletek a piacter.py-ban es a boitblance.py-ban vannak,
a Circle-en keresztul.)
"""

import warnings

from web3 import Web3

import config
from mag import seged

# A receipt-feldolgozas artalmatlan "MismatchedABI" figyelmeztetesei nem kellenek
warnings.filterwarnings("ignore", message=".*MismatchedABI.*")

web3 = Web3(Web3.HTTPProvider(config.RPC_URL))

JOB_STATUSZ = ["Nyitott", "Feltoltve", "Leadva", "Kesz", "Elutasitva", "Lejart"]
# ERC-8183 statusz kodok: 0=Open 1=Funded 2=Submitted 3=Completed 4=Rejected 5=Expired

# ---------- ABI-k ----------

JOB_ABI = [
    {"type": "function", "name": "getJob", "stateMutability": "view",
     "inputs": [{"name": "jobId", "type": "uint256"}],
     "outputs": [{"type": "tuple", "components": [
         {"name": "id", "type": "uint256"}, {"name": "client", "type": "address"},
         {"name": "provider", "type": "address"}, {"name": "evaluator", "type": "address"},
         {"name": "description", "type": "string"}, {"name": "budget", "type": "uint256"},
         {"name": "expiredAt", "type": "uint256"}, {"name": "status", "type": "uint8"},
         {"name": "hook", "type": "address"}]}]},
    {"type": "event", "name": "JobCreated", "anonymous": False, "inputs": [
        {"indexed": True, "name": "jobId", "type": "uint256"},
        {"indexed": True, "name": "client", "type": "address"},
        {"indexed": True, "name": "provider", "type": "address"},
        {"indexed": False, "name": "evaluator", "type": "address"},
        {"indexed": False, "name": "expiredAt", "type": "uint256"},
        {"indexed": False, "name": "hook", "type": "address"}]},
]

IDENTITY_ABI = [{"anonymous": False, "name": "Transfer", "type": "event", "inputs": [
    {"indexed": True, "name": "from", "type": "address"},
    {"indexed": True, "name": "to", "type": "address"},
    {"indexed": True, "name": "tokenId", "type": "uint256"}]}]

REPUTACIO_ABI = [
    {"type": "function", "name": "getSummary", "stateMutability": "view",
     "inputs": [{"name": "agentId", "type": "uint256"},
                {"name": "clientAddresses", "type": "address[]"},
                {"name": "tag1", "type": "string"}, {"name": "tag2", "type": "string"}],
     "outputs": [{"name": "count", "type": "uint64"},
                 {"name": "summaryValue", "type": "int128"},
                 {"name": "summaryValueDecimals", "type": "uint8"}]},
    {"type": "function", "name": "getClients", "stateMutability": "view",
     "inputs": [{"name": "agentId", "type": "uint256"}],
     "outputs": [{"name": "", "type": "address[]"}]},
]

BOND_ABI = [
    {"name": "bonded", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "locked", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "freeBond", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "obligationCount", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"name": "obligations", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "uint256"}],
     "outputs": [{"type": "address"}, {"type": "address"},
                 {"type": "uint256"}, {"type": "uint8"}]},
]

STREAM_ABI = [
    {"name": "streamCount", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"name": "recipientBalance", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}]},
    {"name": "streams", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "uint256"}],
     "outputs": [{"type": "address"}, {"type": "address"}, {"type": "uint256"},
                 {"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"},
                 {"type": "bool"}]},
]

COMMIT_ABI = [
    {"name": "commitmentCount", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"name": "commitments", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "uint256"}],
     "outputs": [{"type": "address"}, {"type": "address"}, {"type": "address"},
                 {"type": "uint256"}, {"type": "uint256"}, {"type": "uint8"},
                 {"type": "string"}]},
]

# ---------- Szerzodes objektumok ----------

def _c(cim, abi):
    return web3.eth.contract(address=Web3.to_checksum_address(cim), abi=abi)


jobok = _c(config.AGENTIC_COMMERCE, JOB_ABI)
identitas = _c(config.IDENTITY_REGISTRY, IDENTITY_ABI)
reputacio_c = _c(config.REPUTATION_REGISTRY, REPUTACIO_ABI)
bond = _c(config.AGENTBOND, BOND_ABI)
stream = _c(config.STREAMPAY, STREAM_ABI)
commit = _c(config.COMMITSTAKE, COMMIT_ABI)


# ---------- Olvaso fuggvenyek ----------

def blokkszam():
    return seged.retry(lambda: web3.eth.block_number, "blokkszam")


def job(job_id):
    """Egy job adatai szotarkent (vagy None, ha nem letezik)."""
    try:
        j = seged.retry(lambda: jobok.functions.getJob(int(job_id)).call(), "getJob", probak=3)
    except Exception:
        return None
    return {
        "id": int(j[0]), "megrendelo": j[1], "ugynok": j[2], "ertekelo": j[3],
        "leiras": j[4], "koltsegvetes": seged.usdc_be(j[5]),
        "lejarat": int(j[6]), "statusz_kod": int(j[7]),
        "statusz": JOB_STATUSZ[int(j[7])] if int(j[7]) < len(JOB_STATUSZ) else str(j[7]),
        "hook": j[8],
    }


def jobok_cimre(ugynok_cim, kezdo_blokk, veg_blokk, darab=9000):
    """JobCreated esemenyek, ahol a provider a megadott cim. [(job_id, megrendelo), ...]"""
    cim = Web3.to_checksum_address(ugynok_cim)
    talalt = []
    frm = kezdo_blokk
    while frm <= veg_blokk:
        to = min(frm + darab - 1, veg_blokk)
        try:
            logs = seged.retry(lambda f=frm, t=to: jobok.events.JobCreated.create_filter(
                from_block=f, to_block=t,
                argument_filters={"provider": cim}).get_all_entries(), "job esemenyek", probak=3)
            for lg in logs:
                talalt.append((int(lg["args"]["jobId"]), lg["args"]["client"]))
        except Exception:
            pass
        frm = to + 1
    return talalt


def job_id_tx_hashbol(tx_hash):
    """A createJob tranzakciobol kiolvassa a job ID-t."""
    receipt = seged.retry(lambda: web3.eth.get_transaction_receipt(tx_hash), "receipt")
    logs = jobok.events.JobCreated().process_receipt(receipt)
    if not logs:
        raise RuntimeError("A JobCreated esemeny nem olvashato ki")
    return int(logs[0]["args"]["jobId"])


def agent_id_tx_hashbol(tx_hash, ugynok_cim):
    """A register() tranzakciobol kiolvassa az ugynok NFT ID-jat (Transfer esemeny)."""
    receipt = seged.retry(lambda: web3.eth.get_transaction_receipt(tx_hash), "receipt")
    logs = identitas.events.Transfer().process_receipt(receipt)
    for lg in logs:
        if lg["args"]["to"].lower() == ugynok_cim.lower():
            return int(lg["args"]["tokenId"])
    raise RuntimeError("A Transfer esemeny nem olvashato ki")


def reputacio(agent_id):
    """{'db': visszajelzesek szama, 'atlag': 0-100 pont}"""
    try:
        kliensek = seged.retry(
            lambda: reputacio_c.functions.getClients(int(agent_id)).call(), "kliensek", probak=3)
        if not kliensek:
            return {"db": 0, "atlag": 0}
        db, ossz, dec = seged.retry(
            lambda: reputacio_c.functions.getSummary(int(agent_id), kliensek, "", "").call(),
            "reputacio", probak=3)
        atlag = (ossz / (10 ** dec)) if db else 0
        return {"db": int(db), "atlag": round(atlag, 1)}
    except Exception:
        return {"db": 0, "atlag": 0}


def kaucio_allapot(cim):
    """{'teljes': x, 'lekotve': y, 'szabad': z} USDC-ben."""
    a = Web3.to_checksum_address(cim)
    try:
        teljes = bond.functions.bonded(a).call()
        lekotve = bond.functions.locked(a).call()
        return {"teljes": seged.usdc_be(teljes), "lekotve": seged.usdc_be(lekotve),
                "szabad": seged.usdc_be(teljes - lekotve)}
    except Exception:
        return {"teljes": 0, "lekotve": 0, "szabad": 0}


def obligation_darab():
    try:
        return int(bond.functions.obligationCount().call())
    except Exception:
        return 0


def obligation(oid):
    try:
        o = bond.functions.obligations(int(oid)).call()
        return {"ugynok": o[0], "megbizo": o[1], "osszeg": seged.usdc_be(o[2]),
                "statusz": ["aktiv", "felszabaditva", "slashelve"][int(o[3])]}
    except Exception:
        return None


def stream_darab():
    try:
        return int(stream.functions.streamCount().call())
    except Exception:
        return 0


def stream_adat(sid):
    try:
        s = stream.functions.streams(int(sid)).call()
        kiveheto = stream.functions.recipientBalance(int(sid)).call()
        return {"kuldo": s[0], "fogado": s[1], "letet": seged.usdc_be(s[2]),
                "kezdet": int(s[3]), "vege": int(s[4]),
                "kivett": seged.usdc_be(s[5]), "aktiv": bool(s[6]),
                "kiveheto": seged.usdc_be(kiveheto)}
    except Exception:
        return None


def commitment_darab():
    try:
        return int(commit.functions.commitmentCount().call())
    except Exception:
        return 0


def commitment(cid):
    try:
        c = commit.functions.commitments(int(cid)).call()
        return {"vallalo": c[0], "ellenor": c[1], "kedvezmenyezett": c[2],
                "tet": seged.usdc_be(c[3]), "hatarido": int(c[4]),
                "statusz": ["nyitott", "teljesitve", "slashelve"][int(c[5])],
                "cel": c[6]}
    except Exception:
        return None

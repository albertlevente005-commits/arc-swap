"""
ARC-SWAP - kozponti beallitasok (halozat, cimek, szabalyok)
===========================================================
MINDEN cim es szabaly egy helyen. A tobbi fajl innen olvassa.

A halozatot az ARC_HALOZAT kornyezeti valtozo valasztja ki:
    ARC_HALOZAT=mainnet   -> Arc (eles, chain id 5042, Circle: "ARC")
    ARC_HALOZAT=testnet   -> Arc Testnet (chain id 5042002, Circle: "ARC-TESTNET")
Alapertelmezes: mainnet.

A .env fajlt CSAK a projektmappabol olvassuk (nincs tobbe "szomszed mappa" keresgeles).
Ami titok vagy telepites-fuggo (API kulcs, tarca-cimek), az a .env-bol jon - a kodban
nincs beegetett tarca-cim.
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

GYOKER = Path(__file__).resolve().parent
ADAT = GYOKER / "adat"                         # futasi adatok (naplo, regiszter)
ADAT.mkdir(exist_ok=True)

ENV_FAJL = GYOKER / ".env"
ENV_FORRAS = str(ENV_FAJL) if ENV_FAJL.exists() else None
if ENV_FORRAS:
    load_dotenv(ENV_FAJL)

_CIM_MINTA = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _env(nev, alap=None):
    ertek = os.getenv(nev)
    if ertek is None or ertek.strip() == "":
        return alap
    return ertek.strip()


def _cim_env(nev, alap=None):
    """Kotelezoen ervenyes EVM cim a .env-bol (vagy None, ha nincs megadva)."""
    ertek = _env(nev, alap)
    if ertek is None:
        return None
    if not _CIM_MINTA.match(ertek):
        raise RuntimeError(f"{nev}: ervenytelen cim: {ertek!r}")
    return ertek


# ----- Halozat kivalasztasa -----

HALOZAT = (_env("ARC_HALOZAT", "mainnet") or "mainnet").lower()
if HALOZAT not in ("mainnet", "testnet"):
    raise RuntimeError(f"ARC_HALOZAT csak 'mainnet' vagy 'testnet' lehet, nem {HALOZAT!r}")
MAINNET = HALOZAT == "mainnet"

HALOZATOK = {
    "mainnet": {
        "nev": "Arc",
        "chain_id": 5042,
        "rpc": "https://rpc.mainnet.arc.io",
        "explorer": "https://explorer.arc.io",
        "circle": "ARC",                 # Circle Wallets / SCP blockchain azonosito
        "usdc": "0x3600000000000000000000000000000000000000",
        "eurc": "0xbEf5f6d51CB62b58e6A8f77868681825C6fe21c1",
        "cirbtc": "0x171A4217b86A807A64eB94757Db6849fb4bDbAA0",
        "identity_registry": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
        "reputation_registry": "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63",
        # ERC-8183 (AgenticCommerce) referencia-implementacio CSAK testneten letezik.
        # Mainneten a sajat telepitesed cimet add meg: AGENTIC_COMMERCE_CIM=0x...
        "agentic_commerce": None,
    },
    "testnet": {
        "nev": "Arc Testnet",
        "chain_id": 5042002,
        "rpc": "https://rpc.testnet.arc.io",
        "explorer": "https://explorer.testnet.arc.io",
        "circle": "ARC-TESTNET",
        "usdc": "0x3600000000000000000000000000000000000000",
        "eurc": "0x89B50855Aa3bE2F677cD6303Cec089B5F319D72a",
        "cirbtc": "0xf0C4a4CE82A5746AbAAd9425360Ab04fbBA432BF",
        "identity_registry": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
        "reputation_registry": "0x8004B663056A597Dffe9eCcC1965A193B7388713",
        "agentic_commerce": "0x0747EEf0706327138c69792bF28Cd525089e4583",
    },
}
_H = HALOZATOK[HALOZAT]

HALOZAT_NEV = _H["nev"]
CHAIN_ID = _H["chain_id"]
RPC_URL = _env("ARC_RPC_URL", _H["rpc"])        # sajat/szolgaltatoi RPC is megadhato
LANC = _H["circle"]                              # Circle API "blockchain" mezo
EXPLORER = _H["explorer"]
EXPLORER_TX = EXPLORER + "/tx/"
EXPLORER_CIM = EXPLORER + "/address/"

# ----- Circle hitelesites -----
# Mainneten a Circle Console LIVE kornyezetenek API kulcsa kell (a TEST kulcs nem mukodik).
CIRCLE_API_KEY = _env("CIRCLE_API_KEY")
CIRCLE_ENTITY_SECRET = _env("CIRCLE_ENTITY_SECRET")

# ----- Kozponti szerzodesek -----
IDENTITY_REGISTRY = _H["identity_registry"]      # ERC-8004 identitas
REPUTATION_REGISTRY = _H["reputation_registry"]  # ERC-8004 reputacio
AGENTIC_COMMERCE = _cim_env("AGENTIC_COMMERCE_CIM", _H["agentic_commerce"])  # ERC-8183 jobok
USDC = _H["usdc"]

# ----- Sajat BoitBlance szerzodesek (csak az ugynokhoz; .env-bol) -----
AGENTBOND = _cim_env("AGENTBOND_CIM")
STREAMPAY = _cim_env("STREAMPAY_CIM")
COMMITSTAKE = _cim_env("COMMITSTAKE_CIM")

# ----- Tarcak (Circle developer-controlled tarcak cimei, .env-bol) -----
MEGRENDELO_CIM = _cim_env("MEGRENDELO_CIM")      # a webapp Circle-modjanak tarcaja (LP + swap)
TELEPITO_CIM = _cim_env("TELEPITO_CIM")          # a DEX telepitoje = a szerzodes tulajdonosa
UGYNOK1_CIM = _cim_env("UGYNOK1_CIM")

METADATA_URI = _env(
    "METADATA_URI",
    "ipfs://bafkreibdi6623n3xpf7ymk62ckb4bo75o3qemwkpfvp5i25j66itxvsoei")

# ----- Webapp -----
APP_HOST = _env("APP_HOST", "127.0.0.1")
APP_PORT = int(_env("APP_PORT", "8060"))
# A Circle-modot (a szerver tarcajaval valtas/likviditas) csak ezzel a tokennel lehet hasznalni.
# Ha nincs beallitva, a Circle-mod IRO vegpontjai le vannak tiltva (a MetaMask-mod mukodik).
ADMIN_TOKEN = _env("VALTO_ADMIN_TOKEN")
ALAP_SLIPPAGE_BPS = int(_env("ALAP_SLIPPAGE_BPS", "50"))      # 0,5%
MAX_SLIPPAGE_BPS = 1000                                        # 10% felett nem engedjuk
TX_HATARIDO_MP = int(_env("TX_HATARIDO_MP", "600"))            # deadline a lancon (mp)
ELOZMENY_VISSZA_BLOKK = int(_env("ELOZMENY_VISSZA_BLOKK", "20000"))
MAX_LOG_BLOKK = 9000                                           # Arc RPC: max 10 000 blokk/eth_getLogs

# ----- Piacteri szabalyok (ugynok) -----
MIN_KAUCIO = 2.0        # USDC - ennyi SZABAD kaucio kell, hogy az ugynok jobot kapjon
LEKOTES = 1.0           # USDC - ennyit kot le a megrendelo a kauciobol jobonkent
INDULO_USDC = "1"       # uj ugynok ennyi USDC-t kap a megrendelotol (gazra)
JOB_LEJARAT_MP = 3600   # a job lejarata (mp)
VARAKOZAS_MAX_MP = 600  # ennyit var max a megrendelo a leadasra (utana slash)
POLL_MP = 8             # lancfigyeles gyakorisaga (mp)
SCAN_VISSZA = 4000      # elso indulaskor ennyi blokkot nezunk vissza

# ----- Skill arak (USDC / job) - az ugynok ennyit ker -----
SKILL_ARAK = {
    "price": 1.0, "top": 1.5, "fx": 1.0, "weather": 1.0,
    "summary": 2.0, "matek": 0.5,
    "valtas": 1.5,    # token valtas (a Valto-Ugynok dinamikusan araz: osszeg + 0,5)
}

# ----- Futasi adatfajlok -----
UGYNOKOK_JSON = ADAT / f"ugynokok.{HALOZAT}.json"
JOBOK_JSON = ADAT / f"jobok.{HALOZAT}.json"
EREDMENYEK_JSON = ADAT / f"eredmenyek.{HALOZAT}.json"
ESEMENYEK_JSON = ADAT / f"esemenyek.{HALOZAT}.json"
NAPLO_FAJL = ADAT / f"valto.{HALOZAT}.log"


def kotelezo(*nevek):
    """Hibat dob, ha a felsorolt beallitasok barmelyike hianyzik (.env)."""
    hianyzo = [n for n in nevek if not globals().get(n)]
    if hianyzo:
        raise RuntimeError(
            "Hianyzo beallitas a .env fajlban: " + ", ".join(hianyzo)
            + f"  (halozat: {HALOZAT}; minta: .env.minta)")


def osszefoglalo():
    """Rovid, titok nelkuli leiras a konzolra."""
    return (f"halozat={HALOZAT_NEV} chain_id={CHAIN_ID} rpc={RPC_URL} circle={LANC} "
            f"circle_kulcs={'van' if CIRCLE_API_KEY else 'NINCS'} "
            f"megrendelo={MEGRENDELO_CIM or '-'} telepito={TELEPITO_CIM or '-'}")

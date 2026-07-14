"""
ARC-PLATFORM - kozponti beallitasok
====================================
MINDEN cim, ar es szabaly egy helyen. A tobbi fajl innen olvassa.

A .env fajlt automatikusan megtalalja:
  1. arc-platform/.env (ha van)
  2. ../erc8004-quickstart/.env (a mar meglevo kulcsod)
"""

import os
import json
from pathlib import Path

from dotenv import load_dotenv

GYOKER = Path(__file__).resolve().parent      # arc-platform mappa
ARC2026 = GYOKER.parent                        # ARC2026 mappa
ADAT = GYOKER / "adat"                         # futasi adatok (naplo, regiszter)
ADAT.mkdir(exist_ok=True)

# ----- .env keresese -----
ENV_FORRAS = None
for _env in (GYOKER / ".env", ARC2026 / "erc8004-quickstart" / ".env"):
    if _env.exists():
        load_dotenv(_env)
        ENV_FORRAS = str(_env)
        break

CIRCLE_API_KEY = os.getenv("CIRCLE_API_KEY")
CIRCLE_ENTITY_SECRET = os.getenv("CIRCLE_ENTITY_SECRET")

# ----- Halozat -----
RPC_URL = "https://rpc.testnet.arc.network"
LANC = "ARC-TESTNET"
EXPLORER_TX = "https://testnet.arcscan.app/tx/"

# ----- Kozponti szerzodesek (Arc Testnet) -----
IDENTITY_REGISTRY = "0x8004A818BFB912233c491871b3d84c89A494BD9e"   # ERC-8004 identitas
REPUTATION_REGISTRY = "0x8004B663056A597Dffe9eCcC1965A193B7388713" # ERC-8004 reputacio
AGENTIC_COMMERCE = "0x0747EEf0706327138c69792bF28Cd525089e4583"    # ERC-8183 jobok
USDC = "0x3600000000000000000000000000000000000000"

# ----- Sajat BoitBlance szerzodesek (a BoitBlance/cimek.json-bol) -----
_cimek_fajl = ARC2026 / "BoitBlance" / "cimek.json"
_cimek = {}
if _cimek_fajl.exists():
    try:
        _cimek = json.loads(_cimek_fajl.read_text(encoding="utf-8"))
    except Exception:
        _cimek = {}
AGENTBOND = _cimek.get("AgentBond", "0xb92e9e0737e585a5032ce64a43a118f6bd8e15e0")
STREAMPAY = _cimek.get("StreamPay", "0xe2d81453ff4d870375566bd5e29f174661b1e5f6")
COMMITSTAKE = _cimek.get("CommitStake", "0xd42f3deb8906b54c75b85c3cb9e05457fb574a0b")

# ----- Tarcak (a korabbi projektekbol ujrahasznalt cimek) -----
MEGRENDELO_CIM = "0xfd38e25aca03e65d4b203b329733cf7e9c1a414b"
UGYNOK1_CIM = "0xf195bf8b147a4c5c94f3dedf147a5f283fddf50a"
# A BoitBlance szerzodeseket (AgentBond/StreamPay/CommitStake) ez a tarca telepitette:
TELEPITO_CIM = "0x774ECDb8b57C85aB610ED6C6bA3483F2E425c975"

METADATA_URI = os.getenv(
    "METADATA_URI",
    "ipfs://bafkreibdi6623n3xpf7ymk62ckb4bo75o3qemwkpfvp5i25j66itxvsoei")

# ----- Piacteri szabalyok -----
MIN_KAUCIO = 2.0        # USDC - ennyi SZABAD kaucio kell, hogy az ugynok jobot kapjon
LEKOTES = 1.0           # USDC - ennyit kot le a megrendelo a kauciobol jobonkent
INDULO_USDC = "1"       # uj ugynok ennyi USDC-t kap a megrendelotol (gazra)
JOB_LEJARAT_MP = 3600   # a job lejarata (mp)
VARAKOZAS_MAX_MP = 600  # ennyit var max a megrendelo a leadasra (utana slash)
POLL_MP = 8             # lancfigyeles gyakorisaga (mp)
SCAN_VISSZA = 4000      # elso indulaskor ennyi blokkot nezunk vissza

# ----- Skill arak (USDC / job) - az ugynok ennyit ker -----
SKILL_ARAK = {
    "price": 1.0,     # kripto arfolyam
    "top": 1.5,       # top kriptolista
    "fx": 1.0,        # deviza arfolyam
    "weather": 1.0,   # idojaras
    "summary": 2.0,   # szoveg-osszefoglalo
    "matek": 0.5,     # szamitas
    "valtas": 1.5,    # token valtas (a Valto-Ugynok dinamikusan araz: osszeg + 0,5)
}

# ----- Futasi adatfajlok -----
UGYNOKOK_JSON = ADAT / "ugynokok.json"      # ugynok-regiszter (nev, cim, skillek, id)
JOBOK_JSON = ADAT / "jobok.json"            # a megrendelo altal kiirt jobok allapota
EREDMENYEK_JSON = ADAT / "eredmenyek.json"  # a leadott munkak olvashato eredmenyei
ESEMENYEK_JSON = ADAT / "esemenyek.json"    # kozos esemenynaplo (minden komponens ir bele)

"""
Piacteri IRO muveletek (ERC-8183 job + ERC-8004 identitas/reputacio).
Minden hivas a Circle-en keresztul megy, a megadott tarca neveben.
"""

import json

from web3 import Web3

import config
from mag import circle_kliens, lanc, seged

NULLA_CIM = "0x0000000000000000000000000000000000000000"


def identitas_regisztralas(ugynok_cim):
    """ERC-8004 regisztracio. Visszaadja az uj agent ID-t (NFT tokenId)."""
    tx = circle_kliens.contract_tx(
        ugynok_cim, config.IDENTITY_REGISTRY, "register(string)",
        [config.METADATA_URI], "identitas regisztralas")
    return lanc.agent_id_tx_hashbol(tx, ugynok_cim)


def job_kiiras(megrendelo_cim, ugynok_cim, leiras, lejarat_mp=None):
    """A megrendelo kiir egy jobot a kivalasztott ugynoknek. Visszaadja a job ID-t."""
    lejarat = seged.retry(
        lambda: lanc.web3.eth.get_block("latest")["timestamp"], "blokk ido") + (
        lejarat_mp or config.JOB_LEJARAT_MP)
    tx = circle_kliens.contract_tx(
        megrendelo_cim, config.AGENTIC_COMMERCE,
        "createJob(address,address,uint256,string,address)",
        [ugynok_cim, megrendelo_cim, str(lejarat), leiras, NULLA_CIM],
        "job kiiras")
    return lanc.job_id_tx_hashbol(tx)


def dij_beallitas(ugynok_cim, job_id, usdc_osszeg):
    """Az ugynok beallitja a dijat (setBudget)."""
    return circle_kliens.contract_tx(
        ugynok_cim, config.AGENTIC_COMMERCE, "setBudget(uint256,uint256,bytes)",
        [str(job_id), seged.egysegbe(usdc_osszeg), "0x"], "dij beallitas")


def job_fizetes(megrendelo_cim, job_id, usdc_osszeg):
    """A megrendelo escrow-ba teszi a dijat (approve + fund)."""
    egyseg = seged.egysegbe(usdc_osszeg)
    circle_kliens.contract_tx(
        megrendelo_cim, config.USDC, "approve(address,uint256)",
        [config.AGENTIC_COMMERCE, egyseg], "USDC jovahagyas")
    return circle_kliens.contract_tx(
        megrendelo_cim, config.AGENTIC_COMMERCE, "fund(uint256,bytes)",
        [str(job_id), "0x"], "escrow feltoltes")


def eredmeny_hash(eredmeny_dict):
    """Az eredmeny kanonikus hash-e - MINDENHOL ugyanigy szamoljuk."""
    return Web3.to_hex(Web3.keccak(text=json.dumps(
        eredmeny_dict, sort_keys=True, ensure_ascii=False)))


def munka_leadas(ugynok_cim, job_id, eredmeny_dict):
    """Az ugynok leadja a munkat (submit) az eredmeny hash-evel."""
    h = eredmeny_hash(eredmeny_dict)
    circle_kliens.contract_tx(
        ugynok_cim, config.AGENTIC_COMMERCE, "submit(uint256,bytes32,bytes)",
        [str(job_id), h, "0x"], "munka leadas")
    return h


def job_lezaras(megrendelo_cim, job_id, indok="deliverable-approved"):
    """A megrendelo lezarja a jobot -> az escrow kifizetodik az ugynoknek."""
    return circle_kliens.contract_tx(
        megrendelo_cim, config.AGENTIC_COMMERCE, "complete(uint256,bytes32,bytes)",
        [str(job_id), Web3.to_hex(Web3.keccak(text=indok)), "0x"], "lezaras + kifizetes")


def ertekeles(megrendelo_cim, agent_id, pont=100, cimke="job_completed"):
    """Reputacios visszajelzes az ugynoknek (0-100 pont)."""
    return circle_kliens.contract_tx(
        megrendelo_cim, config.REPUTATION_REGISTRY,
        "giveFeedback(uint256,int128,uint8,string,string,string,string,bytes32)",
        [str(agent_id), str(int(pont)), "0", cimke, "", "", "",
         Web3.to_hex(Web3.keccak(text=cimke))], f"reputacio ({pont} pont)")


def uzenet_kuldes(felado_cim, cimzett_cim, szoveg):
    """Olvashato uzenet a lancra (0 koltsegvetesu job, provider=cimzett)."""
    return job_kiiras(felado_cim, cimzett_cim, szoveg)

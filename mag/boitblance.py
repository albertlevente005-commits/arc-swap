"""
BoitBlance IRO muveletek a sajat szerzodeseiden:
AgentBond (kaucio) + StreamPay (folyamatos fizetes) + CommitStake (vallalas).
"""

import config
from mag import circle_kliens, lanc, seged


# ---------- AgentBond - kaucio ----------

def kaucio_befizetes(ugynok_cim, usdc):
    """Az ugynok kauciot tesz le (approve + deposit)."""
    egyseg = seged.egysegbe(usdc)
    circle_kliens.contract_tx(ugynok_cim, config.USDC, "approve(address,uint256)",
                              [config.AGENTBOND, egyseg], "USDC jovahagyas (kaucio)")
    return circle_kliens.contract_tx(ugynok_cim, config.AGENTBOND, "deposit(uint256)",
                                     [egyseg], "kaucio letetele")


def kaucio_kivet(ugynok_cim, usdc):
    """Az ugynok kiveszi a szabad kauciojat (vagy egy reszet)."""
    return circle_kliens.contract_tx(ugynok_cim, config.AGENTBOND, "withdraw(uint256)",
                                     [seged.egysegbe(usdc)], "kaucio kivet")


def lekotes(megrendelo_cim, ugynok_cim, usdc):
    """A megrendelo lekot egy szeletet az ugynok kauciojabol egy job moge.
    Visszaadja az obligation ID-t."""
    circle_kliens.contract_tx(
        megrendelo_cim, config.AGENTBOND, "lockObligation(address,uint256)",
        [ugynok_cim, seged.egysegbe(usdc)], "kaucio lekotes")
    return lanc.obligation_darab() - 1


def felszabaditas(megrendelo_cim, obligation_id):
    """Jo munka -> a lekotott kaucio felszabadul."""
    return circle_kliens.contract_tx(megrendelo_cim, config.AGENTBOND, "release(uint256)",
                                     [str(int(obligation_id))], "kaucio felszabaditas")


def slash(megrendelo_cim, obligation_id):
    """Rossz/elmaradt munka -> a lekotott kaucio a megrendelohoz kerul."""
    return circle_kliens.contract_tx(megrendelo_cim, config.AGENTBOND, "slash(uint256)",
                                     [str(int(obligation_id))], "kaucio SLASH")


# ---------- StreamPay - folyamatos fizetes ----------

def stream_nyitas(kuldo_cim, fogado_cim, usdc, idotartam_mp):
    """USDC folyik masodpercenkent a fogadonak. Visszaadja a stream ID-t."""
    egyseg = seged.egysegbe(usdc)
    circle_kliens.contract_tx(kuldo_cim, config.USDC, "approve(address,uint256)",
                              [config.STREAMPAY, egyseg], "USDC jovahagyas (stream)")
    circle_kliens.contract_tx(
        kuldo_cim, config.STREAMPAY, "createStream(address,uint256,uint256)",
        [fogado_cim, egyseg, str(int(idotartam_mp))], "stream nyitas")
    return lanc.stream_darab() - 1


def stream_kivet(fogado_cim, stream_id):
    """A fogado kiveszi az eddig beerett osszeget. Visszaadja (tx, kivett_usdc)."""
    kiveheto = lanc.stream.functions.recipientBalance(int(stream_id)).call()
    if kiveheto == 0:
        raise RuntimeError("Meg nincs kiveheto osszeg ezen a streamen")
    tx = circle_kliens.contract_tx(
        fogado_cim, config.STREAMPAY, "withdraw(uint256,uint256)",
        [str(int(stream_id)), str(kiveheto)], "stream kivet")
    return tx, seged.usdc_be(kiveheto)


def stream_leallitas(fel_cim, stream_id):
    """Barmelyik fel leallitja: a fogado a beerettet, a kuldo a maradekot kapja."""
    return circle_kliens.contract_tx(fel_cim, config.STREAMPAY, "cancelStream(uint256)",
                                     [str(int(stream_id))], "stream leallitas")


# ---------- CommitStake - vallalas ----------

def vallalas(vallalo_cim, ellenor_cim, kedvezmenyezett_cim, usdc, hatarido_mp, cel):
    """Az ugynok tetet tesz egy vallalasra. Visszaadja a commitment ID-t."""
    egyseg = seged.egysegbe(usdc)
    hatarido = seged.retry(
        lambda: lanc.web3.eth.get_block("latest")["timestamp"], "blokk ido") + int(hatarido_mp)
    circle_kliens.contract_tx(vallalo_cim, config.USDC, "approve(address,uint256)",
                              [config.COMMITSTAKE, egyseg], "USDC jovahagyas (vallalas)")
    circle_kliens.contract_tx(
        vallalo_cim, config.COMMITSTAKE,
        "createCommitment(address,address,uint256,uint256,string)",
        [ellenor_cim, kedvezmenyezett_cim, str(hatarido), egyseg, str(cel)[:120]],
        "vallalas letrehozas")
    return lanc.commitment_darab() - 1


def megerosites(ellenor_cim, commitment_id):
    """Az ellenor megerositi a teljesitest -> a tet visszajar."""
    return circle_kliens.contract_tx(ellenor_cim, config.COMMITSTAKE, "confirm(uint256)",
                                     [str(int(commitment_id))], "vallalas megerosites")


def vallalas_slash(barki_cim, commitment_id):
    """Hatarido utan barki kivalthatja a slasht -> a tet a kedvezmenyezette."""
    return circle_kliens.contract_tx(barki_cim, config.COMMITSTAKE, "slash(uint256)",
                                     [str(int(commitment_id))], "vallalas slash")

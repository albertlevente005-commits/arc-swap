"""
Az ugynokok VALODI munkai (skillek) + a skill-cimke formatum.

A job leirasa a lancon igy nez ki:
    [skill:price coin=bitcoin] Kerem a Bitcoin aktualis arat
A cimke mondja meg, MIT kell csinalni; a szoveg a "emberi" leiras.
Cimke nelkuli, nekunk cimzett job = siman uzenet (postalada).

Uj skill hozzaadasa: irj egy fuggvenyt, es vedd fel a SKILLEK szotarba +
a config.SKILL_ARAK-ba az arat.
"""

import ast
import operator
import re
from collections import Counter

import requests

from mag import seged

CIMKE_MINTA = re.compile(r"^\s*\[skill:(\w+)([^\]]*)\]\s*(.*)$", re.S)


def cimke(skill, **parameterek):
    """Skill-cimke szoveg keszitese. cimke('price', coin='bitcoin') -> '[skill:price coin=bitcoin]'"""
    resz = " ".join(f"{k}={v}" for k, v in parameterek.items() if v not in (None, ""))
    return f"[skill:{skill}{(' ' + resz) if resz else ''}]"


def cimke_ertelmezes(leiras):
    """Leiras -> (skill, parameterek, szoveg) vagy None, ha nincs cimke (= uzenet)."""
    m = CIMKE_MINTA.match(leiras or "")
    if not m:
        return None
    skill = m.group(1).lower()
    parameterek = {}
    for resz in m.group(2).split():
        if "=" in resz:
            k, v = resz.split("=", 1)
            parameterek[k.strip()] = v.strip()
    return skill, parameterek, m.group(3).strip()


# ---------- A skillek ----------

def munka_price(p):
    """Elo kripto arfolyam (CoinGecko, kulcs nelkul)."""
    coin = p.get("coin", "bitcoin").lower()

    def hivas():
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd",
            timeout=15)
        r.raise_for_status()
        return r.json()[coin]["usd"]

    ar = seged.retry(hivas, f"{coin} arfolyam")
    return {"tipus": "price", "coin": coin, "ar_usd": ar}


def munka_top(p):
    """Top N kripto piaci ertek szerint (CoinGecko)."""
    n = max(1, min(int(p.get("n", 5)), 10))

    def hivas():
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets"
            f"?vs_currency=usd&order=market_cap_desc&per_page={n}&page=1",
            timeout=15)
        r.raise_for_status()
        return r.json()

    adat = seged.retry(hivas, "top coinok")
    lista = [{"nev": c["symbol"].upper(), "ar_usd": c["current_price"],
              "piaci_ertek_mrd": round(c["market_cap"] / 1e9, 1)} for c in adat]
    return {"tipus": "top", "darab": n, "coinok": lista}


def munka_fx(p):
    """Deviza arfolyam (open.er-api.com, kulcs nelkul). Pl. base=EUR quote=HUF"""
    base = p.get("base", "USD").upper()
    quote = p.get("quote", "HUF").upper()

    def hivas():
        r = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=15)
        r.raise_for_status()
        return r.json()["rates"]

    arfolyamok = seged.retry(hivas, "deviza arfolyam")
    if quote not in arfolyamok:
        raise RuntimeError(f"Ismeretlen devizanem: {quote}")
    return {"tipus": "fx", "par": f"{base}/{quote}", "arfolyam": arfolyamok[quote]}


def munka_weather(p):
    """Elo idojaras (Open-Meteo, kulcs nelkul). lat/lon parameterekkel."""
    lat = float(p.get("lat", 47.4979))
    lon = float(p.get("lon", 19.0402))

    def hivas():
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m",
            timeout=15)
        r.raise_for_status()
        return r.json()["current"]

    most = seged.retry(hivas, "idojaras")
    return {"tipus": "weather", "lat": lat, "lon": lon,
            "homerseklet_c": most["temperature_2m"], "szel_kmh": most["wind_speed_10m"]}


def munka_summary(p, szoveg=""):
    """Szoveg-osszefoglalo (helyi feldolgozas). A szoveg a leirasbol jon."""
    szoveg = (p.get("text") or szoveg or "").strip()
    if not szoveg:
        raise RuntimeError("Nincs osszefoglalando szoveg a job leirasaban")
    mondatok = [s.strip() for s in re.split(r"[.!?]+", szoveg) if s.strip()]
    szavak = re.findall(r"\w+", szoveg.lower())
    stop = set("az es hogy is de nem egy ezt a the and to of in".split())
    kulcsszavak = [w for w, _ in Counter(
        w for w in szavak if len(w) > 4 and w not in stop).most_common(5)]
    return {"tipus": "summary", "mondatok": len(mondatok), "szavak": len(szavak),
            "kulcsszavak": kulcsszavak, "elso_mondat": mondatok[0] if mondatok else ""}


_MUVELETEK = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
              ast.USub: operator.neg, ast.UAdd: operator.pos}


def _biztonsagos_ertekeles(fa):
    if isinstance(fa, ast.Expression):
        return _biztonsagos_ertekeles(fa.body)
    if isinstance(fa, ast.Constant) and isinstance(fa.value, (int, float)):
        return fa.value
    if isinstance(fa, ast.BinOp) and type(fa.op) in _MUVELETEK:
        return _MUVELETEK[type(fa.op)](
            _biztonsagos_ertekeles(fa.left), _biztonsagos_ertekeles(fa.right))
    if isinstance(fa, ast.UnaryOp) and type(fa.op) in _MUVELETEK:
        return _MUVELETEK[type(fa.op)](_biztonsagos_ertekeles(fa.operand))
    raise RuntimeError("Nem engedelyezett kifejezes")


def munka_matek(p, szoveg=""):
    """Szamtani kifejezes kiertekelese (biztonsagosan). Pl. kif=2*(3+4)"""
    kif = (p.get("kif") or szoveg or "").strip()
    if not kif:
        raise RuntimeError("Nincs kifejezes (kif=...)")
    ertek = _biztonsagos_ertekeles(ast.parse(kif, mode="eval"))
    return {"tipus": "matek", "kifejezes": kif, "eredmeny": ertek}


def munka_valtas(p, sz=""):
    """A valtast a Valto-Ugynok vegzi a ValtoDEX-en (arc-valto projekt) -
    ez a bejegyzes csak a skill regisztralasahoz kell."""
    raise RuntimeError("a valtast a Valto-Ugynok vegzi (inditsd: arc-valto\\valto_ugynok.py)")


SKILLEK = {
    "price": lambda p, sz: munka_price(p),
    "top": lambda p, sz: munka_top(p),
    "fx": lambda p, sz: munka_fx(p),
    "weather": lambda p, sz: munka_weather(p),
    "summary": lambda p, sz: munka_summary(p, sz),
    "matek": lambda p, sz: munka_matek(p, sz),
    "valtas": munka_valtas,
}

SKILL_LEIRAS = {
    "price": "Kripto arfolyam (coin=bitcoin)",
    "top": "Top kriptolista (n=5)",
    "fx": "Deviza arfolyam (base=EUR quote=HUF)",
    "weather": "Idojaras (lat=47.5 lon=19.04)",
    "summary": "Szoveg-osszefoglalo (a szoveg a leirasban)",
    "matek": "Szamitas (kif=2*(3+4))",
    "valtas": "Token valtas a ValtoDEX-en (be=USDC ki=EURC osszeg=5)",
}


def munka_elvegzes(skill, parameterek, szoveg=""):
    """A tenyleges munka. Ezt vegzi el az ugynok a job felvetele utan."""
    if skill not in SKILLEK:
        raise RuntimeError(f"Ismeretlen skill: {skill}")
    return SKILLEK[skill](parameterek, szoveg)

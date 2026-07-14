"""Kozos segedfuggvenyek: ujraprobalkozas, JSON fajlok, esemenynaplo, formazas."""

import json
import os
import sys
import time
import tempfile

import config

# Ha CSENDES=True (pl. MCP szerver alatt), minden kiiras a stderr-re megy,
# mert a stdout az MCP protokolle.
CSENDES = False


def kiir(szoveg, veg="\n"):
    celf = sys.stderr if CSENDES else sys.stdout
    try:
        celf.write(szoveg + veg)
        celf.flush()
    except Exception:
        pass


def retry(fn, cimke="muvelet", probak=5, szunet=3):
    """Halozati hiba eseten ujraprobalkozik."""
    utolso = None
    for i in range(probak):
        try:
            return fn()
        except Exception as e:
            utolso = e
            if i < probak - 1:
                kiir(f"  [!] Halozati hiba ({cimke}) - ujraproba {i + 1}/{probak - 1}...")
                time.sleep(szunet)
    raise utolso


# ---------- JSON fajlok (biztonsagos iras: temp + csere) ----------

def json_olvas(utvonal, alap):
    try:
        with open(utvonal, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return alap


def json_ir(utvonal, adat):
    utvonal = str(utvonal)
    d = os.path.dirname(utvonal) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(adat, f, ensure_ascii=False, indent=2)
        os.replace(tmp, utvonal)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ---------- Kozos esemenynaplo ----------

def esemeny(forras, szoveg, **extra):
    """Bejegyzes a kozos esemenynaploba (adat/esemenyek.json) + kiiras a konzolra."""
    sor = {"ido": time.strftime("%Y-%m-%d %H:%M:%S"), "forras": forras, "szoveg": szoveg}
    sor.update(extra)
    for _ in range(3):  # ha ket folyamat egyszerre ir, ujraprobaljuk
        try:
            adatok = json_olvas(config.ESEMENYEK_JSON, [])
            adatok.append(sor)
            json_ir(config.ESEMENYEK_JSON, adatok[-500:])  # csak az utolso 500-at tartjuk
            break
        except Exception:
            time.sleep(0.2)
    kiir(f"[{forras}] {szoveg}")


# ---------- USDC formazas (6 tizedesjegy) ----------

def egysegbe(usdc):
    """USDC -> lanc-egyseg (string). Pl. 1.5 -> '1500000'"""
    return str(int(round(float(usdc) * 1_000_000)))


def usdc_be(egyseg):
    """lanc-egyseg -> USDC (float). Pl. 1500000 -> 1.5"""
    return int(egyseg) / 1_000_000


def rovid(cim):
    """Cim roviditese kiirashoz: 0x1234...abcd"""
    cim = str(cim)
    return cim[:6] + "..." + cim[-4:] if len(cim) > 12 else cim

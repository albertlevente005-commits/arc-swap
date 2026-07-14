"""
Helyi nyilvantartasok (az adat/ mappaban):
  - ugynokok.json:    ki elerheto, milyen skillekkel, milyen cimen (az ugynok daemon irja)
  - jobok.json:       a megrendelo altal kiirt jobok allapota (a megrendelo irja)
  - eredmenyek.json:  a leadott munkak OLVASHATO eredmenye (az ugynok irja,
                      a lancra csak a hash kerul - a hash-nek egyeznie kell!)

A penz es a bizonyitek a LANCON van; ezek a fajlok csak a helyi koordinaciot
segitik a gepen futo folyamatok kozott.
"""

import time

import config
from mag import seged


# ---------- Ugynok-regiszter ----------

def ugynokok():
    return seged.json_olvas(config.UGYNOKOK_JSON, {})


def ugynok_mentes(nev, adatok):
    r = ugynokok()
    regi = r.get(nev, {})
    regi.update(adatok)
    regi["utolso_eletjel"] = time.strftime("%Y-%m-%d %H:%M:%S")
    r[nev] = regi
    seged.json_ir(config.UGYNOKOK_JSON, r)
    return regi


def ugynok_kereses_skillre(skill):
    """A skillhez erto ugynokok nevei."""
    return [nev for nev, a in ugynokok().items() if skill in a.get("skillek", [])]


# ---------- Jobok (megrendeloi oldal) ----------

def jobok_lista():
    return seged.json_olvas(config.JOBOK_JSON, [])


def job_hozzaadas(bejegyzes):
    lista = jobok_lista()
    lista.append(bejegyzes)
    seged.json_ir(config.JOBOK_JSON, lista)


def job_frissites(job_id, **valtozas):
    lista = jobok_lista()
    for j in lista:
        if j.get("job_id") == job_id:
            j.update(valtozas)
    seged.json_ir(config.JOBOK_JSON, lista)


def job_bejegyzes(job_id):
    for j in jobok_lista():
        if j.get("job_id") == job_id:
            return j
    return None


# ---------- Eredmenyek (ugynoki oldal) ----------

def eredmeny_mentes(job_id, eredmeny, deliverable_hash, ugynok_nev):
    adatok = seged.json_olvas(config.EREDMENYEK_JSON, {})
    adatok[str(job_id)] = {
        "ido": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ugynok": ugynok_nev,
        "hash": deliverable_hash,
        "eredmeny": eredmeny,
    }
    seged.json_ir(config.EREDMENYEK_JSON, adatok)


def eredmeny(job_id):
    return seged.json_olvas(config.EREDMENYEK_JSON, {}).get(str(job_id))

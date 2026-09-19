# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Le pool : rafraîchir ce qu'on consulte, effacer ce qu'on ne lit plus.

Aucun thread n'est démarré ici : les passes sont appelées directement, avec
un espacement nul. Sans cela un test attendrait des heures, le pool étalant
ses téléchargements sur la moitié de sa période.
"""

import json
import os
import time

import pandas as pd
import pytest

from card_api import cache, hubeau, pool

BRUT = [{"code_station": "K0550010", "date_obs_elab": "1990-01-01",
         "resultat_obs_elab": 272000.0}]


def _copie(station, age_jours=0.0):
    """Une chronique en cache, dont la COLLECTE date de `age_jours`."""
    f = cache.chronicle_path(station)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x")
    quand = time.time() - age_jours * 86400
    os.utime(f, (quand, quand))
    return f


def _serie(cle):
    cache.store_series(cle, pd.DataFrame({"code_station": ["K0550010"],
                                          "date": pd.to_datetime(["1990-01-01"]),
                                          "QA": [11.5]}))


def _lu_il_y_a(prefixe, cle, jours):
    """Force la date de dernière lecture d'une entrée du registre."""
    cache._marque_cle(prefixe + cle)
    with cache._verrou:
        con = cache._connexion()
        con.execute("UPDATE lectures SET dernier_acces = ? WHERE cle = ?",
                    (time.time() - jours * 86400, prefixe + cle))
        con.commit()


@pytest.fixture(autouse=True)
def _dans_le_dossier_du_test(monkeypatch, tmp_path):
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    monkeypatch.setattr(hubeau, "_fetch_all", lambda url, params: BRUT)


def test_l_eviction_efface_ce_que_personne_ne_lit_plus():
    """La règle, et elle ramasse aussi les ORPHELINES : une clé qui change
    cesse d'être demandée, donc cesse d'être lue, donc tombe ici. Aucune
    liste à tenir de ce qu'un changement a périmé."""
    _copie("VIEILLE0", age_jours=200)
    _copie("RECENTE0", age_jours=200)
    _lu_il_y_a(cache._CHRONIQUE, "VIEILLE0", 120)
    _lu_il_y_a(cache._CHRONIQUE, "RECENTE0", 2)

    assert cache.evict(90) == {"chroniques": 1, "series": 0}
    assert not cache.chronicle_path("VIEILLE0").exists()
    assert cache.chronicle_path("RECENTE0").exists()
    # le registre suit : il cesserait sinon de décrire le cache
    assert cache.last_read("VIEILLE0") is None
    assert cache.last_read("RECENTE0") is not None


def test_l_eviction_ramasse_les_series_aussi():
    """Même règle, même date, même registre : c'est pour cela que les deux
    étages partagent un module."""
    _serie("vieille-serie")
    _serie("recente-serie")
    _lu_il_y_a(cache._SERIE, "vieille-serie", 120)
    assert cache.evict(90) == {"chroniques": 0, "series": 1}
    assert not cache.series_path("vieille-serie").exists()
    assert cache.series_path("recente-serie").exists()


def test_sans_date_de_lecture_on_se_rabat_sur_le_fichier():
    """Une entrée tout juste écrite dont le marquage a échoué ne doit pas
    partir dans la seconde qui suit. On garde un peu trop plutôt que
    d'effacer ce qui sert."""
    _copie("TOUTNEUF", age_jours=0)
    _copie("ANCIENNE", age_jours=200)
    assert cache.last_read("TOUTNEUF") is None       # jamais marquée
    assert cache.evict(90) == {"chroniques": 1, "series": 0}
    assert cache.chronicle_path("TOUTNEUF").exists()
    assert not cache.chronicle_path("ANCIENNE").exists()


def test_le_pool_rafraichit_ce_qui_vieillit_et_rien_d_autre(monkeypatch):
    monkeypatch.setattr(pool, "FRAICHEUR_JOURS", 7)
    monkeypatch.setattr(pool, "EVICTION_JOURS", 10_000)   # rien à évincer
    _copie("K0550010", age_jours=30)          # au-delà du seuil
    _copie("K0550011", age_jours=1)           # encore fraîche

    bilan = pool.passe(espacement=0)
    assert bilan["candidates"] == 1 and bilan["rafraichies"] == 1
    # la vieille a été réécrite, donc sa collecte est de maintenant
    assert cache.is_fresh("K0550010", 0.01)
    assert not cache.is_fresh("K0550011", 0.01)


def test_le_pool_ne_marque_aucune_lecture(monkeypatch):
    """**La règle sur laquelle repose toute l'éviction.**

    Le pool réécrit les copies, donc écrase leur date de collecte. S'il
    marquait aussi les lectures, toutes les entrées paraîtraient consultées
    en permanence et rien ne sortirait jamais du cache : la station que
    personne ne redemande resterait là pour toujours.
    """
    monkeypatch.setattr(pool, "FRAICHEUR_JOURS", 7)
    monkeypatch.setattr(pool, "EVICTION_JOURS", 10_000)
    _copie("K0550010", age_jours=30)
    _lu_il_y_a(cache._CHRONIQUE, "K0550010", 40)
    avant = cache.last_read("K0550010")

    assert pool.passe(espacement=0)["rafraichies"] == 1
    assert cache.last_read("K0550010") == avant      # inchangée
    assert cache.read_count("K0550010") == 1         # et pas deux


def test_une_station_muette_n_arrete_pas_la_passe(monkeypatch):
    """Le pool repassera, et le service sert la copie en place en
    attendant : une station qui ne répond pas ne doit pas emporter les
    autres."""
    monkeypatch.setattr(pool, "FRAICHEUR_JOURS", 7)
    monkeypatch.setattr(pool, "EVICTION_JOURS", 10_000)
    _copie("K0550010", age_jours=30)
    _copie("XXXX0000", age_jours=30)

    def capricieux(url, params):
        if params["code_entite"].startswith("X"):
            raise hubeau.HubEauIndisponible("Hub'Eau ne répond pas")
        return BRUT

    monkeypatch.setattr(hubeau, "_fetch_all", capricieux)
    bilan = pool.passe(espacement=0)
    assert bilan["rafraichies"] == 1 and bilan["echecs"] == 1


def test_la_passe_est_journalisee(monkeypatch):
    """Un pool qu'on ne voit pas tourner est un pool dont on ne sait pas
    s'il tourne : `make stats` lit cette ligne."""
    monkeypatch.setattr(pool, "EVICTION_JOURS", 10_000)
    _copie("K0550010", age_jours=30)
    pool.passe(espacement=0)
    fichier = next(cache.data_dir().glob("usage-*.jsonl"))
    passes = [json.loads(ligne) for ligne in fichier.read_text().splitlines()]
    passes = [p for p in passes if p.get("event") == "pool"]
    assert len(passes) == 1
    assert passes[0]["rafraichies"] == 1


def test_le_pool_ne_demarre_pas_s_il_est_coupe(monkeypatch):
    """Un exploitant doit pouvoir le fermer, et les tests ne doivent
    démarrer aucun thread."""
    monkeypatch.setattr(pool, "ENABLED", False)
    assert pool.ensure_pool() is False

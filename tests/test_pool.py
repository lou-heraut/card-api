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

    assert cache.evict(90) == {"chroniques": 1, "series": 0, "place": 0}
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
    assert cache.evict(90) == {"chroniques": 0, "series": 1, "place": 0}
    assert not cache.series_path("vieille-serie").exists()
    assert cache.series_path("recente-serie").exists()


def test_sans_date_de_lecture_on_se_rabat_sur_le_fichier():
    """Une entrée tout juste écrite dont le marquage a échoué ne doit pas
    partir dans la seconde qui suit. On garde un peu trop plutôt que
    d'effacer ce qui sert."""
    _copie("TOUTNEUF", age_jours=0)
    _copie("ANCIENNE", age_jours=200)
    assert cache.last_read("TOUTNEUF") is None       # jamais marquée
    assert cache.evict(90) == {"chroniques": 1, "series": 0, "place": 0}
    assert cache.chronicle_path("TOUTNEUF").exists()
    assert not cache.chronicle_path("ANCIENNE").exists()


def test_le_pool_rafraichit_ce_qui_vieillit_et_rien_d_autre(monkeypatch):
    monkeypatch.setattr(cache, "MAX_AGE_DAYS", 30)     # seuil du pool : 25
    monkeypatch.setattr(pool, "EVICTION_JOURS", 10_000)   # rien à évincer
    _copie("K0550010", age_jours=30)          # au-delà du seuil
    _copie("K0550011", age_jours=1)           # encore fraîche

    bilan = pool.passe(espacement=0)
    assert bilan["candidates"] == 1 and bilan["rafraichies"] == 1
    # la vieille a été réécrite, donc sa collecte est de maintenant
    assert cache.is_fresh("K0550010", 0.01)
    assert not cache.is_fresh("K0550011", 0.01)


@pytest.mark.parametrize("accepte", [30, 60])
def test_le_pool_renouvelle_avant_que_la_requete_ne_refuse(monkeypatch,
                                                            accepte):
    """Le seuil du pool se DÉDUIT de l'âge accepté, il n'est pas réglé à part.

    Une copie dans la marge (plus vieille que le seuil, plus jeune que l'âge
    accepté) serait encore servie à une requête, et le pool la renouvelle
    quand même : c'est ce qui épargne le téléchargement à la requête. Une
    copie plus jeune que le seuil n'est pas touchée. Changer l'âge accepté
    déplace le seuil avec lui (B6 de dev/plans/2026-09-19_cache-followup.md).
    """
    monkeypatch.setattr(cache, "MAX_AGE_DAYS", accepte)
    monkeypatch.setattr(pool, "EVICTION_JOURS", 10_000)
    seuil = pool.seuil_jours()
    assert 0 < seuil < accepte
    _copie("K0550010", age_jours=(seuil + accepte) / 2)     # dans la marge
    _copie("K0550011", age_jours=seuil - 1)                 # trop jeune
    assert cache.is_fresh("K0550010")      # une requête la servirait encore

    bilan = pool.passe(espacement=0)
    assert bilan["candidates"] == 1 and bilan["rafraichies"] == 1
    assert cache.is_fresh("K0550010", 0.01)                 # renouvelée
    assert not cache.is_fresh("K0550011", 0.01)             # laissée


def test_le_pool_ne_marque_aucune_lecture(monkeypatch):
    """**La règle sur laquelle repose toute l'éviction.**

    Le pool réécrit les copies, donc écrase leur date de collecte. S'il
    marquait aussi les lectures, toutes les entrées paraîtraient consultées
    en permanence et rien ne sortirait jamais du cache : la station que
    personne ne redemande resterait là pour toujours.
    """
    monkeypatch.setattr(cache, "MAX_AGE_DAYS", 30)     # seuil du pool : 25
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
    monkeypatch.setattr(cache, "MAX_AGE_DAYS", 30)     # seuil du pool : 25
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


def test_l_eviction_s_abstient_si_le_registre_ne_repond_pas():
    """Effacer sur une information absente est la seule faute de ce module
    qui coûterait plus qu'un recalcul.

    Sans registre, l'éviction se rabattrait sur les dates de fichier, donc
    effacerait ce qui sert : elle s'abstient et le dit. Le pool, lui,
    continue de rafraîchir, les deux gestes d'une passe répondant à deux
    questions.
    """
    _copie("K0550010", age_jours=200)
    (cache.data_dir() / "cache.db").write_bytes(b"pas une base sqlite")
    cache._con = None

    with pytest.raises(cache.RegistreIndisponible):
        cache.evict(90)
    assert cache.chronicle_path("K0550010").exists()      # rien d'effacé

    bilan = pool.passe(espacement=0)
    assert "abandon" in bilan["eviction"]
    assert bilan["rafraichies"] == 1                       # le reste tourne


def test_le_plafond_de_place_efface_les_moins_recemment_lues(monkeypatch):
    """L'éviction par le temps ne borne pas la TAILLE du cache : si l'usage
    explose, le disque se remplit avant que la première entrée ne devienne
    évinçable. Le plafond de place s'en charge, sur la même information de
    dernière lecture, en commençant par ce que personne ne regarde plus.
    """
    monkeypatch.setattr(cache, "MAX_GO", 3_000 / 1e9)       # 3 Ko
    for station, jours in (("ANCIENNE", 90), ("MOYENNE0", 10),
                           ("RECENTE0", 1)):
        f = _copie(station)
        f.write_bytes(b"x" * 2_000)                         # 2 Ko chacune
        _lu_il_y_a(cache._CHRONIQUE, station, jours)

    bilan = cache.evict(10_000)                 # rien à évincer par le temps
    assert bilan["place"] >= 2_000
    assert not cache.chronicle_path("ANCIENNE").exists()    # la moins lue
    assert cache.chronicle_path("RECENTE0").exists()        # la plus lue
    reste = sum(p.stat().st_size for p in cache.chronicles_dir().iterdir())
    assert reste <= 3_000


def test_le_plafond_de_place_ne_touche_a_rien_s_il_reste_de_la_marge():
    _copie("K0550010")
    _lu_il_y_a(cache._CHRONIQUE, "K0550010", 1)
    assert cache.evict(10_000)["place"] == 0
    assert cache.chronicle_path("K0550010").exists()


# ── Ce que /v1/health publie du pool, et ce que la sonde en fait (B3) ──

@pytest.fixture
def pool_allume(monkeypatch):
    """Le pool déclaré allumé, sans thread, et sans passe depuis le départ."""
    monkeypatch.setattr(pool, "ENABLED", True)
    monkeypatch.setattr(pool, "_derniere_passe", None)
    monkeypatch.setattr(pool, "_echeance", None)


def test_une_passe_repousse_l_echeance(pool_allume, monkeypatch):
    monkeypatch.setattr(pool, "EVICTION_JOURS", 10_000)
    assert pool.etat()["last_pass"] is None
    avant = time.time()
    pool.passe(espacement=0)
    assert avant - 1 <= pool._derniere_passe <= time.time()
    # le sommeil d'une période, puis une période pour la passe suivante
    assert pool._echeance == pytest.approx(
        pool._derniere_passe + 2 * pool.PASSE_HEURES * 3600, abs=1)
    assert pool.etat()["last_pass"].endswith("+00:00")


def test_une_passe_qui_echoue_ne_repousse_pas_l_echeance(pool_allume,
                                                          monkeypatch):
    """Un pool dont toutes les passes échouent tourne, mais ne sert à rien :
    la sonde doit le voir en retard."""
    pool._repousse_echeance(0)
    echeance = pool._echeance

    def en_panne():
        raise OSError("disque illisible")
    monkeypatch.setattr(cache, "cached_stations", en_panne)
    with pytest.raises(OSError):
        pool.passe(espacement=0)
    assert pool._echeance == echeance and pool._derniere_passe is None


def test_la_sonde_lit_le_pool_dans_la_vraie_reponse(pool_allume, monkeypatch):
    """La sonde tourne hors de la VM et lit `/v1/health` : on la confronte
    à la réponse que le service rend, pas à un exemple écrit à la main."""
    import sys
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from fastapi.testclient import TestClient

    from card_api.main import app
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import veille_sante

    monkeypatch.setattr(veille_sante, "DISQUE_PCT", 100)   # disque du poste
    client = TestClient(app)

    def verdict(maintenant=None):
        corps = client.get("/v1/health").json()
        return veille_sante.anomalie(corps, 0, maintenant)

    assert "jamais démarré" in verdict()
    pool._repousse_echeance(pool.DEPART_S)                 # ce que fait ensure_pool
    assert verdict() is None
    plus_tard = datetime.now(timezone.utc) + timedelta(
        hours=2 * pool.PASSE_HEURES)
    assert "en retard" in verdict(plus_tard)
    monkeypatch.setattr(pool, "ENABLED", False)
    assert "coupé" in verdict()

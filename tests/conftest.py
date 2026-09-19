"""Rend card_api, card et stase importables sans installation (dev),
et fournit la chronique simulée qui garde la suite HORS-LIGNE.

En production l'image Docker installe card et stase depuis GitHub.
"""

import queue
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

for p in (
    _ROOT / "src",
    _ROOT.parent / "card" / "src",
    _ROOT.parent.parent / "EXstat_project" / "stase" / "src",
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture(autouse=True)
def _test_env(monkeypatch, tmp_path):
    """Quotas neutralisés (tous les tests partagent l'« IP » testclient)
    et données/journal dans un dossier temporaire.
    """
    from card_api import pool, usage
    usage._hits.clear()
    # Aucun test ne démarre le pool : un thread qui rafraîchit partirait
    # interroger le VRAI Hub'Eau, station par station, pendant la suite.
    # Les tests du pool appellent ses passes directement.
    monkeypatch.setattr(pool, "ENABLED", False)
    monkeypatch.setattr(usage, "RATE_COMPUTE", 10_000)
    monkeypatch.setattr(usage, "RATE_LIGHT", 10_000)
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    yield
    reste = _travail_en_vol()
    if reste:
        pytest.fail(
            "ce test laisse du travail en vol : " + ", ".join(reste) + ".\n"
            "Un job qui survit au test qui l'a lancé emporte deux ennuis "
            "avec lui. Il perd le simulateur Hub'Eau, retiré à la fin du "
            "test, donc il part interroger le VRAI Hub'Eau ; et il écrit "
            "son résultat dans un dossier de données qui n'est plus celui "
            "du test, d'où une exception dans un thread, sans rapport "
            "visible avec le test qui l'a causée. Simuler `jobs.submit` "
            "quand seule l'enveloppe du ticket compte, ou attendre la fin "
            "du job dans le test.")


def _travail_en_vol():
    """Ce qui restait à faire quand le test s'est terminé.

    Deux gestes, et ils répondent à deux besoins différents.

    La file est VIDÉE tout de suite : c'est un objet de module, partagé
    par toute la suite, et un reste de test s'exécuterait plus tard, dans
    le contexte d'un autre test.

    Un job déjà parti, lui, ne s'interrompt pas. On ATTEND qu'il finisse,
    pour qu'aucun thread ne traverse la frontière du test suivant, et on
    le SIGNALE quand même, sur ce qui a été vu au premier coup d'œil :
    attendre est de l'hygiène, signaler est ce qui fait corriger le test.
    Sans quoi un job assez court pour finir pendant l'attente resterait
    invisible, alors qu'il a déjà perdu son simulateur Hub'Eau.
    """
    from card_api import jobs

    restes = []
    while True:
        try:
            restes.append("en file " + jobs._queue.get_nowait()[2])
        except queue.Empty:
            break

    def _en_cours():
        try:
            return [f"{job['status']} {d.name}"
                    for d in jobs.jobs_dir().iterdir()
                    if (job := jobs.load(d.name))
                    and job["status"] in ("queued", "running")]
        except OSError:
            return []

    vus = _en_cours()
    fin = time.time() + 30.0
    while _en_cours() and time.time() < fin:
        time.sleep(0.05)
    return restes + vus


@pytest.fixture
def hubeau_simule(monkeypatch):
    """Chronique synthétique de 30 ans, saisonnière, une par station.

    À demander dans TOUT test qui appelle /v1/extract ou /v1/trend. Sans
    elle, le test part chercher la vraie chronique sur Hub'Eau : le
    `_test_env` ci-dessus place le cache dans un dossier temporaire, donc
    il est toujours vide et rien ne retient l'appel. La suite se dit
    hors-ligne, elle deviendrait alors dépendante d'un service tiers,
    lente, et rouge le jour où Hub'Eau est en maintenance. C'est arrivé
    aux tests ajoutés le 2026-07-28, d'où cette fixture partagée plutôt
    qu'une copie par fichier.
    """
    import numpy as np
    import pandas as pd

    from card_api import hubeau

    def fake_fetch(station, refresh=False, max_age=None):
        if station.startswith("X"):
            raise hubeau.StationInconnue(
                f"aucune chronique QmnJ pour {station!r}")
        dates = pd.date_range("1968-01-01", "2024-12-31", freq="D")
        doy = dates.dayofyear.to_numpy()
        rng = np.random.default_rng(abs(hash(station)) % 2**32)
        q = 10 + 8 * np.sin(2 * np.pi * (doy - 30) / 365.25) \
            + rng.lognormal(0, 0.3, len(dates))
        return pd.DataFrame({"code_station": station, "date": dates, "Q": q})

    monkeypatch.setattr(hubeau, "fetch_chronicle", fake_fetch)
    return fake_fetch

"""Rend card_api, card et stase importables sans installation (dev),
et fournit la chronique simulée qui garde la suite HORS-LIGNE.

En production l'image Docker installe card et stase depuis GitHub.
"""

import sys
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
    et données/journal dans un dossier temporaire."""
    from card_api import usage
    usage._hits.clear()
    monkeypatch.setattr(usage, "RATE_COMPUTE", 10_000)
    monkeypatch.setattr(usage, "RATE_LIGHT", 10_000)
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))


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

    def fake_fetch(station, refresh=False):
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

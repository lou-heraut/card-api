"""Validation croisée avec MAKAHO (https://makaho.sk8.inrae.fr/).

Les exports de tests/data/makaho/ ont été générés par MAKAHO le
2026-07-16 (EXstat/CARD R, stations RRSE, période 1968-09-01 à
2024-08-31, année hydrologique 09-01, significativité 0.1, option
Hamed & Rao AR1) pour quatre analyses : QA, tQJXA, dtLF, QSA_DJF.

Partie hors-ligne (toujours exécutée) : stase.trend sur les séries
agrégées de MAKAHO (dataEX) doit reproduire leurs tendances (trendEX)
à la précision machine ; cela valide le port MK/Sen indépendamment de
la source de données.

Partie live (CARD_API_LIVE=1) : le pipeline complet de l'API (Hub'Eau
-> extract -> trend) comparé aux mêmes exports ; la source diffère
(scrape HydroPortail vs API Hub'Eau), la concordance est donc mesurée
avec tolérance.

Point de protocole (vérifié le 2026-07-16 sur les 4 exports) : MAKAHO
n'utilise PAS l'échantillonnage adaptatif des fiches ; il impose le
preferred_sampling_period de chaque fiche à toutes les stations
(sampling_period_overwrite de CARD-R : 09-01 pour tQJXA, 01-01 pour
dtLF), et c'est documenté dans la colonne sampling_period_en de ses
metaEX. Toute comparaison sur fiche adaptative doit reproduire ces
fenêtres fixes. Validation à trois voies faite sur les mêmes
chroniques Hub'Eau : CARD-R vs card/stase identiques (séries 94-100 %,
H 99-100 %, résidus = divergences documentées ORIGINE_R.md) ; les
écarts restants vs MAKAHO sont dus à la source de données
(révisions HydroPortail/Hub'Eau), pas à l'implémentation.
"""

import os
import warnings
from pathlib import Path

import pandas as pd
import pytest
import stase

MAKAHO = Path(__file__).parent / "data" / "makaho"

# (dossier, relative de la variable, période de tendance MAKAHO)
# QSA_DJF : le premier hiver (déc. 1967 absent) est exclu par MAKAHO,
# le dernier (2024) est gardé ; les autres analyses couvrent tout
# leur dataEX.
CASES = [
    ("QA", True, None),
    ("tQJXA", False, None),
    ("dtLF", False, None),
    ("QSA_DJF", True, ["1969-01-01", "2024-01-01"]),
]


@pytest.mark.parametrize("var,relative,period", CASES)
def test_trend_reproduces_makaho(var, relative, period):
    data = pd.read_csv(MAKAHO / var / "dataEX.csv", parse_dates=["date"])
    ref = pd.read_csv(MAKAHO / var / "trendEX.csv").set_index("code")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = stase.trend(data, level=0.1, dependency="AR1",
                        relative={var: relative}, period=period)
    t = t.set_index("code")
    j = t.join(ref, rsuffix="_mk").dropna(subset=["p_mk"])

    assert len(j) == 228                       # tout le RRSE
    assert (j["H"].astype(bool) == j["H_mk"].astype(bool)).all()
    assert (j["p"] - j["p_mk"]).abs().max() < 1e-12
    assert (j["a"] - j["a_mk"]).abs().max() < 1e-12
    assert (j["a_relative"] - j["a_normalise"]).abs().max() < 1e-12


@pytest.mark.skipif(os.environ.get("CARD_API_LIVE") != "1",
                    reason="test réseau : lancer avec CARD_API_LIVE=1")
def test_api_pipeline_agrees_with_makaho_subset():
    """Pipeline complet sur un sous-ensemble de stations RRSE : la
    tendance QA de l'API doit concorder avec MAKAHO malgré le
    changement de source de données."""
    from fastapi.testclient import TestClient
    from card_api.main import app

    client = TestClient(app)
    ref = pd.read_csv(MAKAHO / "QA" / "trendEX.csv").set_index("code")
    stations = sorted(ref.index)[:10]

    r = client.get("/v1/trend", params=dict(
        stations=",".join(stations), cards="QA",
        start="1968-09-01", end="2024-08-31"))
    assert r.status_code == 200
    api = (pd.DataFrame(r.json()["data"]["QA"])
           .rename(columns={"id": "code"}).set_index("code"))
    j = api.join(ref, rsuffix="_mk").dropna(subset=["p_mk"])
    assert len(j) >= 8                          # tolère quelques codes disparus
    agree = (j["H"].astype(bool) == j["H_mk"].astype(bool)).mean()
    assert agree >= 0.8

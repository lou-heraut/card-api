"""Tests de /v1/extract avec un Hub'Eau simulé (hors-ligne)."""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from card_api import hubeau
from card_api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_hubeau(monkeypatch):
    """Chronique synthétique de 30 ans, saisonnière, pour 2 stations."""
    def fake_fetch(station, refresh=False):
        if station.startswith("X"):
            raise hubeau.StationInconnue(f"aucune chronique QmnJ pour {station!r}")
        dates = pd.date_range("1990-01-01", "2019-12-31", freq="D")
        doy = dates.dayofyear.to_numpy()
        rng = np.random.default_rng(abs(hash(station)) % 2**32)
        q = 10 + 8 * np.sin(2 * np.pi * (doy - 30) / 365.25) \
            + rng.lognormal(0, 0.3, len(dates))
        return pd.DataFrame({"id": station, "date": dates, "Q": q})
    monkeypatch.setattr(hubeau, "fetch_chronicle", fake_fetch)


def test_extract_two_stations_two_cards():
    r = client.get("/v1/extract", params={
        "stations": "F700000103,K0550010", "cards": "QA,VCN10"})
    assert r.status_code == 200
    body = r.json()
    assert set(body["dataEX"]) == {"QA", "VCN10"}
    qa = body["dataEX"]["QA"]
    assert len(qa) == 62                       # 2 stations x 31 années hydro
                                               # (échantillonnage 09-01)
    assert {row["id"] for row in qa} == {"F700000103", "K0550010"}
    assert all(row["QA"] > 0 for row in qa if row["QA"] is not None)
    assert any(m["variable_en"] == "VCN10" for m in body["metaEX"])


def test_extract_period_filter():
    r = client.get("/v1/extract", params={
        "stations": "K0550010", "cards": "QA",
        "start": "2000-01-01", "end": "2009-12-31"})
    assert r.status_code == 200
    assert len(r.json()["dataEX"]["QA"]) == 11   # années hydro 1999..2009


def test_extract_errors():
    assert client.get("/v1/extract", params={
        "stations": "X0000000", "cards": "QA"}).status_code == 404
    assert client.get("/v1/extract", params={
        "stations": "K0550010", "cards": "FICHE_INEXISTANTE"}).status_code == 404
    too_many = ",".join(f"K{i:07d}" for i in range(11))
    assert client.get("/v1/extract", params={
        "stations": too_many, "cards": "QA"}).status_code == 422


def test_extract_card_needing_other_inputs_rejected():
    r = client.get("/v1/extract", params={"stations": "K0550010", "cards": "RA"})
    assert r.status_code == 422
    assert "R" in r.json()["detail"]

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
    assert set(body["data"]) == {"QA", "VCN10"}
    qa = body["data"]["QA"]
    assert len(qa) == 62                       # 2 stations x 31 années hydro
                                               # (échantillonnage 09-01)
    assert {row["id"] for row in qa} == {"F700000103", "K0550010"}
    assert all(row["QA"] > 0 for row in qa if row["QA"] is not None)
    assert any(m["variable_en"] == "VCN10" for m in body["meta"])


def test_extract_period_filter():
    r = client.get("/v1/extract", params={
        "stations": "K0550010", "cards": "QA",
        "start": "2000-01-01", "end": "2009-12-31"})
    assert r.status_code == 200
    assert len(r.json()["data"]["QA"]) == 11   # années hydro 1999..2009


def test_extract_errors():
    assert client.get("/v1/extract", params={
        "stations": "X0000000", "cards": "QA"}).status_code == 404
    assert client.get("/v1/extract", params={
        "stations": "K0550010", "cards": "FICHE_INEXISTANTE"}).status_code == 404
    # au-delà du plafond JOB (le plafond synchrone, lui, bascule en job)
    too_many = ",".join(f"K{i:07d}" for i in range(101))
    assert client.get("/v1/extract", params={
        "stations": too_many, "cards": "QA"}).status_code == 422


def test_extract_card_needing_other_inputs_rejected():
    r = client.get("/v1/extract", params={"stations": "K0550010", "cards": "RA"})
    assert r.status_code == 422
    assert "R" in r.json()["detail"]


def test_extract_orient_columns():
    r = client.get("/v1/extract", params={
        "stations": "K0550010", "cards": "QA", "orient": "columns"})
    assert r.status_code == 200
    qa = r.json()["data"]["QA"]
    assert set(qa) == {"id", "date", "QA"}
    assert len(qa["date"]) == len(qa["QA"]) == 31
    assert client.get("/v1/extract", params={
        "stations": "K0550010", "cards": "QA", "orient": "n_importe"}).status_code == 422


def test_trend_endpoint():
    r = client.get("/v1/trend", params={
        "stations": "K0550010", "cards": "QA,VCN10"})
    assert r.json()["mk"] == "AR1"                 # défaut : robuste AR(1)
    assert r.status_code == 200
    body = r.json()
    assert set(body["data"]) == {"QA", "VCN10"}
    row = body["data"]["QA"][0]
    assert "H" in row and "level" in str(body)
    # fiche scalaire refusée pour la tendance
    r2 = client.get("/v1/trend", params={
        "stations": "K0550010", "cards": "median-dtLF"})
    assert r2.status_code == 422
    assert "series" in r2.json()["detail"]


def test_rate_limit_and_usage_log(monkeypatch, tmp_path):
    from card_api import usage
    usage._hits.clear()
    monkeypatch.setattr(usage, "RATE_COMPUTE", 2)
    ok1 = client.get("/v1/extract", params={"stations": "K0550010", "cards": "QA"})
    ok2 = client.get("/v1/extract", params={"stations": "K0550010", "cards": "QA"})
    blocked = client.get("/v1/extract", params={"stations": "K0550010", "cards": "QA"})
    assert ok1.status_code == ok2.status_code == 200
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    log = (tmp_path / "usage.jsonl").read_text().strip().split("\n")
    assert len(log) == 2                       # seules les requêtes servies
    import json
    entry = json.loads(log[0])
    assert entry["endpoint"] == "extract" and "user" in entry
    assert "." not in entry["user"] and len(entry["user"]) == 12   # hash, pas l'IP


def test_extract_sampling_override():
    """sampling=preferred et sampling=MM-JJ décalent la fenêtre annuelle
    des fiches adaptatives (QJXA : mois du minimum par défaut)."""
    def month(r):
        dates = [row["date"] for row in r.json()["data"]["QJXA"]]
        months = pd.Series(pd.to_datetime(dates)).dt.month
        return months.mode()[0]

    base = {"stations": "K0550010", "cards": "QJXA"}
    r_def = client.get("/v1/extract", params=base)
    r_pref = client.get("/v1/extract", params={**base, "sampling": "preferred"})
    r_exp = client.get("/v1/extract", params={**base, "sampling": "03-01"})
    assert r_def.status_code == r_pref.status_code == r_exp.status_code == 200
    assert month(r_pref) == 9                  # preferred de QJXA : 09-01
    assert month(r_exp) == 3
    assert month(r_def) != 9                   # adaptatif (régime simulé)
    assert r_pref.json()["sampling"] == "preferred"


def test_extract_sampling_invalid():
    r = client.get("/v1/extract", params={
        "stations": "K0550010", "cards": "QA", "sampling": "septembre"})
    assert r.status_code == 422
    assert "preferred" in r.json()["detail"]

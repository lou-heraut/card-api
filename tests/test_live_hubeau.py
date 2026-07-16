"""Test live contre Hub'Eau, exécuté seulement si CARD_API_LIVE=1."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CARD_API_LIVE") != "1",
    reason="test réseau : lancer avec CARD_API_LIVE=1",
)


def test_live_extract_austerlitz(tmp_path, monkeypatch):
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    from fastapi.testclient import TestClient
    from card_api.main import app

    client = TestClient(app)
    r = client.get("/v1/extract", params={
        "stations": "F700000103", "cards": "QA",
        "start": "2010-01-01", "end": "2019-12-31"})
    assert r.status_code == 200
    qa = r.json()["data"]["QA"]
    values = [row["QA"] for row in qa if row["QA"] is not None]
    assert values and all(50 < v < 2000 for v in values)   # la Seine à Paris, m3/s

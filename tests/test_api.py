"""Tests de l'étape 1 : découverte du catalogue."""

from fastapi.testclient import TestClient

from card_api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_cards_catalogue():
    r = client.get("/v1/cards")
    body = r.json()
    assert r.status_code == 200
    assert body["count"] > 200
    first = body["cards"][0]
    assert {"variable_en", "name_fr", "domain_fr", "output_en"} <= set(first)


def test_cards_facet_filters():
    fr = client.get("/v1/cards", params={"phenomenon": "basses eaux"}).json()
    en = client.get("/v1/cards", params={"phenomenon": "low flows"}).json()
    assert 0 < fr["count"] < 400
    assert fr["count"] == en["count"]
    delta = client.get("/v1/cards", params={"operator": "delta"}).json()
    assert all(c["operator"] == "delta" for c in delta["cards"])


def test_card_detail_and_404():
    r = client.get("/v1/cards/VCN10")
    body = r.json()
    assert r.status_code == 200
    assert body["card"]["id"] == "VCN10"
    assert body["card"]["phenomenon"] == "basses eaux"
    assert "path" not in body["card"]
    assert body["card"]["yaml"].startswith("https://github.com/")
    assert client.get("/v1/cards/INEXISTANTE").status_code == 404

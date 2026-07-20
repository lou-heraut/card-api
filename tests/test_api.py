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


def test_card_detail_does_not_disguise_a_missing_data_file(monkeypatch):
    """Un fichier de données absent du package est un bug serveur, pas une
    fiche inconnue. La suite tourne en install éditable, où ces fichiers
    sont toujours là : seul un test explicite couvre le cas."""
    def boom(*a, **kw):
        raise FileNotFoundError(2, "No such file or directory",
                                "/usr/lib/card/inputs.yaml")
    monkeypatch.setattr("card_api.main.card.info", boom)
    strict = TestClient(app, raise_server_exceptions=False)
    assert strict.get("/v1/cards/VCN10").status_code == 500

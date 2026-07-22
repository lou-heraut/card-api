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


def test_reponses_portent_l_identite_du_calcul():
    """Un résultat doit dire ce qui l'a produit : la version du corpus,
    celle du moteur, celle du service. Sans quoi il n'est ni
    reproductible ni citable."""
    for url in ("/v1/health", "/v1/cards", "/v1/cards/QA"):
        j = client.get(url).json()
        for k in ("card_version", "stase_version", "api_version"):
            assert k in j, f"{url} : {k} absent"


def test_commit_publie_quand_l_image_le_connait(tmp_path, monkeypatch):
    """Le numéro de version ne désigne un état unique que si la ref
    était un tag. Construite depuis une branche, l'image résout le
    commit : c'est lui qui rend le résultat reproductible."""
    from card_api import main

    refs = tmp_path / "build_refs.json"
    refs.write_text('{"card": {"ref": "main", "commit": "abc123def456"},'
                    ' "stase": {"ref": "main", "commit": "789abc012def"}}')
    monkeypatch.setenv("CARD_API_BUILD_REFS", str(refs))
    monkeypatch.setattr(main, "CARD_COMMIT", "abc123def456")
    monkeypatch.setattr(main, "STASE_COMMIT", "789abc012def")

    v = main.versions()
    assert v["card_commit"] == "abc123def456"
    assert v["stase_commit"] == "789abc012def"


def test_versions_des_fiches_arrivent_a_l_utilisateur():
    """Chaque fiche porte sa propre version : deux fiches d'une même
    réponse peuvent ne pas avoir la même, elle voyage donc par variable
    dans les métadonnées, pas globalement."""
    j = client.get("/v1/cards", params={"search": "QA"}).json()
    assert j["cards"], "aucune fiche renvoyée"
    assert any("version" in c for c in j["cards"]), list(j["cards"][0])

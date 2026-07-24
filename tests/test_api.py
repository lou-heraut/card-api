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
    # L'identifiant Software Heritage d'une révision git EST le hash du
    # commit : citable sans appel d'API, une fois le dépôt archivé.
    assert v["card_swhid"] == "swh:1:rev:abc123def456"
    assert v["stase_swhid"] == "swh:1:rev:789abc012def"


def test_versions_des_fiches_arrivent_a_l_utilisateur():
    """Chaque fiche porte sa propre version : deux fiches d'une même
    réponse peuvent ne pas avoir la même, elle voyage donc par variable
    dans les métadonnées, pas globalement."""
    j = client.get("/v1/cards", params={"search": "QA"}).json()
    assert j["cards"], "aucune fiche renvoyée"
    assert any("version" in c for c in j["cards"]), list(j["cards"][0])


def test_reponse_synchrone_porte_la_date_de_lecture():
    """Hub'Eau révise ses données : sans la date de lecture, deux
    résultats identiques en apparence ne sont pas comparables. Elle
    n'était présente que dans les jobs."""
    from card_api import main
    assert main._fetched_at([]), "une borne doit toujours être rendue"


def test_le_ltp_est_reproductible():
    """Le LTP départage les ex-æquo au hasard. Sans graine fixée, deux
    appels identiques peuvent rendre des p-values différentes : le
    service en fixe une et la publie dans la provenance."""
    from card_api import main
    assert isinstance(main.LTP_SEED, int)


def test_empreinte_des_donnees_identifie_la_source():
    """Hub'Eau révise ses chroniques : sans empreinte, un écart entre
    deux calculs ne se distingue pas d'un changement de code. Elle doit
    être stable sur une donnée identique et bouger au moindre écart."""
    import numpy as np
    import pandas as pd

    from card_api import hubeau

    n = 4000
    df = pd.DataFrame({
        "date": pd.date_range("1990-01-01", periods=n, freq="D"),
        "id": "K0550010",
        "Q": np.random.default_rng(0).gamma(2, 5, n)})

    assert hubeau.fingerprint(df) == hubeau.fingerprint(df.copy())

    revise = df.copy()
    revise.loc[10, "Q"] += 1e-9          # une révision minuscule de Hub'Eau
    assert hubeau.fingerprint(df) != hubeau.fingerprint(revise)

    lacune = df.copy()
    lacune.loc[20, "Q"] = np.nan
    assert hubeau.fingerprint(df) != hubeau.fingerprint(lacune)

    # l'ordre dans lequel on demande les stations ne doit rien changer
    a, b = hubeau.fingerprint(df), hubeau.fingerprint(revise)
    assert (hubeau.combine_fingerprints({"S1": a, "S2": b})
            == hubeau.combine_fingerprints({"S2": b, "S1": a}))


def test_racine_situe_le_service_et_ses_droits():
    """Point d'entrée : un client doit trouver ce qu'est le service, ce
    qu'il relie, et sous quels droits réutiliser le résultat."""
    b = client.get("/v1").json()
    assert b["service"] == "card-api"
    assert {"card", "stase", "hubeau"} <= set(b["ecosystem"])
    assert b["rights"]["data"]["license"].startswith("Licence Ouverte")
    assert b["rights"]["definitions"]["license"] == "GPL-3.0-or-later"
    assert "/v1/cards" in b["endpoints"].values()


def test_figure_est_servie_en_texte_et_le_detail_reste_json():
    """Les deux représentations : JSON par défaut pour les machines,
    figure dessinée sur son propre endpoint pour comprendre."""
    r = client.get("/v1/cards/QA/figure")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "QA" in r.text and "▼" in r.text
    # le détail JSON ne se met pas à charrier la figure
    assert "figure" not in client.get("/v1/cards/QA").json()["card"]


def test_figure_fiche_inconnue_et_langue_invalide():
    assert client.get("/v1/cards/PASUNEFICHE/figure").status_code == 404
    assert client.get("/v1/cards/QA/figure?lang=de").status_code == 422


def test_vocabulaire_donne_les_filtres_valides():
    """Sans lui, un client devine les valeurs de facette."""
    b = client.get("/v1/vocabulary").json()
    v = b["vocabulary"]
    assert {"domain", "phenomenon", "output"} <= set(v)
    assert v["phenomenon"]["low flows"]["fr"] == "basses eaux"
    # et ces valeurs filtrent réellement le catalogue
    r = client.get("/v1/cards", params={"phenomenon": "low flows"})
    assert r.status_code == 200 and r.json()["count"] > 0


def test_droits_dans_un_resultat_de_donnees(monkeypatch):
    """Un résultat qui circule doit dire sous quels droits il circule."""
    import card_api.main as m
    b = client.get("/v1/cards").json()
    assert "card_swhid" in b or "card_version" in b   # provenance déjà là
    assert m.rights()["cite"].endswith("CITATION.cff")

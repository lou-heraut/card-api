"""Tests de l'étape 1 : découverte du catalogue."""

import datetime as dt

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
    """Une facette filtre par SLUG, et par lui seul.

    Le slug est l'identifiant du concept, celui qui ne privilégie ni le
    français ni l'anglais ; les libellés sont de la PRÉSENTATION, ils
    vivent dans le résultat (colonnes _fr et _en), dans /v1/vocabulary et
    dans le paramètre lang. Mélanger les deux dans la requête donnait
    trois orthographes pour un concept, donc un contrat qui ne peut plus
    annoncer ses valeurs valides.
    """
    r = client.get("/v1/cards", params={"phenomenon": "low-flows"})
    assert r.status_code == 200
    assert 0 < r.json()["count"] < 400
    # un libellé n'est pas un identifiant : refus, avec les valeurs valides
    refus = client.get("/v1/cards", params={"phenomenon": "basses eaux"})
    assert refus.status_code == 422
    assert "low-flows" in refus.text
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
    from card_api import main, pipeline

    refs = tmp_path / "build_refs.json"
    refs.write_text('{"card": {"ref": "main", "commit": "abc123def456"},'
                    ' "stase": {"ref": "main", "commit": "789abc012def"}}')
    monkeypatch.setenv("CARD_API_BUILD_REFS", str(refs))
    # `versions()` a migré dans pipeline.py avec le reste de
    # l'identité du calcul : c'est là que vivent les commits.
    monkeypatch.setattr(pipeline, "CARD_COMMIT", "abc123def456")
    monkeypatch.setattr(pipeline, "STASE_COMMIT", "789abc012def")

    v = main.versions()
    assert v["card_commit"] == "abc123def456"
    assert v["stase_commit"] == "789abc012def"
    # L'identifiant Software Heritage d'une révision git EST le hash du
    # commit : citable sans appel d'API, une fois le dépôt archivé.
    assert v["card_swhid"] == "swh:1:rev:abc123def456"
    assert v["stase_swhid"] == "swh:1:rev:789abc012def"


def test_les_commits_du_build_traversent_vraiment_la_chaine(tmp_path):
    """Le chemin de l'IMAGE, éprouvé de bout en bout.

    Depuis card 0.4.0, le service ne résout plus les commits lui-même :
    il pose `CARD_COMMIT` / `STASE_COMMIT` depuis `build_refs.json`, et
    la résolution de card les lit en premier. Le test voisin force les
    constantes et ne dit donc rien de cette chaîne ; celui-ci la parcourt
    en entier.

    En sous-processus parce que tout se joue à l'import du module, et
    qu'un import déjà fait ne se rejoue pas.
    """
    import json
    import os
    import subprocess
    import sys

    card_sha, stase_sha = "a" * 40, "b" * 40
    refs = tmp_path / "build_refs.json"
    refs.write_text(json.dumps({"card": {"ref": "main", "commit": card_sha},
                                "stase": {"ref": "main", "commit": stase_sha}}))

    out = subprocess.run(
        [sys.executable, "-c",
         "import json; from card_api.pipeline import versions;"
         " print(json.dumps(versions()))"],
        capture_output=True, text=True, check=True,
        env={**os.environ, "CARD_API_BUILD_REFS": str(refs)})
    v = json.loads(out.stdout)

    assert v["card_commit"] == card_sha
    assert v["stase_commit"] == stase_sha
    assert v["card_swhid"] == f"swh:1:rev:{card_sha}"


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
        "code_station": "K0550010",
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


def test_la_racine_renvoie_par_relation_de_lien():
    """`/` est un panneau indicateur, dans la forme des « landing pages »
    d'OGC API : ce qui compte n'est pas l'ordre des entrées mais leur
    RELATION, qu'un client générique sait suivre sans connaître le
    service. Elle ne redit pas ce que /v1 dit déjà."""
    r = client.get("/")
    assert r.status_code == 200
    liens = {lien["rel"]: lien["href"] for lien in r.json()["links"]}
    assert liens["service-desc"].endswith("/openapi.json")
    assert liens["service-doc"].endswith("/docs")
    assert liens["latest-version"].endswith("/v1")


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
    # clé = slug neutre, en et fr à égalité (pas d'anglais privilégié)
    assert v["phenomenon"]["low-flows"] == {"en": "low flows",
                                            "fr": "basses eaux"}
    # et TOUS ces slugs sont acceptés par /v1/cards : le vocabulaire et
    # les énumérations de l'OpenAPI sortent de la même source, ce test
    # échouerait s'ils se mettaient à diverger.
    for facette in ("domain", "phenomenon", "aspect", "season", "output"):
        for slug in v[facette]:
            r = client.get("/v1/cards", params={facette: slug})
            assert r.status_code == 200, f"{facette}={slug}"


def test_droits_dans_un_resultat_de_donnees(monkeypatch):
    """Un résultat qui circule doit dire sous quels droits il circule."""
    import card_api.main as m
    b = client.get("/v1/cards").json()
    assert "card_swhid" in b or "card_version" in b   # provenance déjà là
    assert m.rights()["cite"].endswith("CITATION.cff")


def test_la_cle_de_priorite_existe_dans_le_contrat():
    """Elle existait dans le service (usage.priority_of lit l'en-tête)
    sans exister dans le contrat : personne ne pouvait la découvrir, et
    depuis /docs personne ne pouvait la PRÉSENTER, donc `GET /v1/jobs` y
    rendait 401 sans recours. Elle reste facultative : c'est ce qui garde
    le service public."""
    spec = client.get("/openapi.json").json()
    schemes = spec["components"]["securitySchemes"]
    (scheme,) = schemes.values()
    assert scheme["type"] == "apiKey" and scheme["in"] == "header"
    assert scheme["name"] == "X-API-Key"
    # déclarée sur les opérations, donc « Authorize » s'affiche
    assert spec["paths"]["/v1/trend"]["get"]["security"]
    # ... et le service répond toujours sans clé
    assert client.get("/v1/cards?limit=1").status_code == 200


def test_l_ordre_des_sections_suit_le_parcours():
    """L'ordre des tags EST celui de la page. On choisit une station
    avant d'extraire : `stations` passe donc avant `data`."""
    noms = [t["name"] for t in client.get("/openapi.json").json()["tags"]]
    assert noms.index("stations") < noms.index("data")


def test_les_listes_sont_rendues_pretes_a_coller():
    """Filtrer puis recopier quinze identifiants à la main est la corvée
    qui décide de l'abandon. Les deux endpoints de découverte rendent
    donc la liste déjà jointe, à coller telle quelle dans le paramètre
    de l'endpoint suivant."""
    j = client.get("/v1/cards", params={"phenomenon": "low-flows",
                                        "output": "series",
                                        "limit": 5}).json()
    ids = j["ids"].split(",")
    assert len(ids) == len(set(ids)), "identifiants répétés"
    assert ids == [c["id"] for c in j["cards"]][:len(ids)]
    # collée telle quelle, la liste doit être acceptée
    assert client.get("/v1/cards/" + ids[0]).status_code == 200


def test_l_identifiant_d_une_fiche_est_rendu_par_le_catalogue():
    """L'identifiant est le NOM DU FICHIER, pas la variable : les deux
    diffèrent pour la majorité des fiches (`ETPMA_month.yaml` produit
    `ETPMA_jan`...`ETPMA_dec`). La colonne était annoncée partout sans
    être rendue, si bien qu'on devinait `variable_en` et qu'on obtenait
    un 404."""
    j = client.get("/v1/cards", params={"search": "ETPMA", "limit": 3}).json()
    if not j["cards"]:
        return
    fiche = j["cards"][0]
    assert "id" in fiche
    assert client.get("/v1/cards/" + fiche["id"]).status_code == 200


def test_la_tendance_se_lit_aussi_dessinee(hubeau_simule):
    """Une représentation, une URL. La figure est un endpoint et non un
    paramètre `format` : une opération dont le type de média dépendrait
    d'un paramètre de requête ne peut pas se décrire en OpenAPI, et le
    contrat annoncerait du JSON en rendant du texte.

    Les deux endpoints partagent UN modèle de paramètres : les recopier
    serait la garantie qu'ils divergent au premier ajout."""
    p = {"stations": "F700000103", "cards": "QA"}
    r = client.get("/v1/trend/figure", params=p)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "TENDANCE" in r.text and "verdict" in r.text
    assert "significative" in r.text
    # le JSON reste la représentation par défaut, à l'URL nue
    assert client.get("/v1/trend", params=p).json()["data"]

    spec = client.get("/openapi.json").json()["paths"]
    assert set(spec["/v1/trend"]["get"]["responses"]["200"]["content"]) == {
        "application/json"}
    assert set(spec["/v1/trend/figure"]["get"]["responses"]["200"]
               ["content"]) == {"text/plain"}
    noms = [q["name"] for q in spec["/v1/trend"]["get"]["parameters"]]
    assert noms == [q["name"] for q in
                    spec["/v1/trend/figure"]["get"]["parameters"]]


def test_le_csv_porte_sa_provenance(hubeau_simule):
    """Un CSV ne sait pas porter de bloc `versions` : livré nu, il devient
    en trois copies un tableau de chiffres dont plus personne ne sait d'où
    il vient, c'est-à-dire ce que ce service existe pour éviter. La
    provenance part donc en lignes `#`, que pandas et R sautent d'eux-
    mêmes et qui survivent à l'enregistrement du fichier, contrairement à
    un en-tête HTTP."""
    import io

    import pandas as pd

    p = {"stations": "F700000103", "cards": "QA,VCN10", "start": "1990-01-01"}
    r = client.get("/v1/extract.csv", params=p)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")

    entete = [ligne for ligne in r.text.splitlines() if ligne.startswith("#")]
    joint = "\n".join(entete)
    for attendu in ("card-api", "stations :", "fiches :", "source :",
                    "empreinte", "droits :", "citer :"):
        assert attendu in joint, attendu

    # et le fichier reste un CSV ordinaire une fois les commentaires sautés
    d = pd.read_csv(io.StringIO(r.text), comment="#")
    assert list(d.columns) == ["code_station", "date", "variable", "value"]
    assert set(d["variable"]) == {"QA", "VCN10"}


def test_le_nom_du_fichier_dit_l_analyse(hubeau_simule):
    """Du plus général au plus particulier, pour que deux analyses
    voisines se rangent côte à côte. L'empreinte des données termine le
    nom : deux extractions séparées par une révision Hub'Eau ne
    s'écrasent pas l'une l'autre, là où une date de génération changerait
    sans que rien ne change."""
    r = client.get("/v1/trend.csv", params={"stations": "F700000103",
                                            "cards": "QA,VCN10"})
    nom = r.headers["content-disposition"].split('filename="')[1].rstrip('"')
    champs = nom.removesuffix(".csv").split("_")
    assert champs[0] == "card-api" and champs[1] == "trend"
    assert champs[2] == "F700000103"
    assert "QA-VCN10" in nom and "AR1" in nom
    assert nom.endswith(".csv")

    from card_api.main import _abrege
    assert _abrege(["A", "B"], "stations") == "A-B"
    assert _abrege(list("ABCDE"), "stations") == "5stations"


def test_les_csv_ont_un_contrat_exact():
    """Une représentation, une URL : chaque opération déclare le seul
    type de média qu'elle rend, et les quatre endpoints d'un même calcul
    partagent leurs paramètres au lieu de les recopier."""
    paths = client.get("/openapi.json").json()["paths"]
    attendu = {"/v1/extract": "application/json", "/v1/extract.csv": "text/csv",
               "/v1/trend": "application/json", "/v1/trend.csv": "text/csv",
               "/v1/trend/figure": "text/plain"}
    for path, media in attendu.items():
        contenu = paths[path]["get"]["responses"]["200"]["content"]
        assert set(contenu) == {media}, (path, list(contenu))
    for a, b in (("/v1/extract", "/v1/extract.csv"),
                 ("/v1/trend", "/v1/trend.csv")):
        assert ([q["name"] for q in paths[a]["get"]["parameters"]]
                == [q["name"] for q in paths[b]["get"]["parameters"]])


def test_le_bandeau_csv_ne_contient_aucune_virgule(hubeau_simule):
    """Un tableur n'a pas de notion de commentaire : il affiche les
    lignes `#` comme des données et les DÉCOUPE sur les virgules. Le
    bandeau se retrouvait éparpillé sur huit colonnes.

    Le quoter le garderait en une cellule, mais il ne commencerait plus
    par `#` et `read_csv(comment="#")` cesserait de le sauter : le remède
    serait pire. Reste à ne produire aucune virgule."""
    r = client.get("/v1/trend.csv", params={"stations": "F700000103",
                                            "cards": "QA,VCN10"})
    entete = [ligne for ligne in r.text.splitlines() if ligne.startswith("#")]
    assert entete
    for ligne in entete:
        assert "," not in ligne, ligne
    # la liste des fiches reste lisible, séparateur changé
    assert any("QA · VCN10" in ligne for ligne in entete)


def test_la_fenetre_par_defaut_demarre_en_1968(hubeau_simule):
    """Pas « toute la chronique » : 1968 est la borne d'analyse du projet
    et le point où le réseau français devient assez fourni pour que des
    stations se comparent. La période effective est publiée, donc le
    résultat dit toujours sur quoi il porte."""
    # La fenêtre par défaut est appliquée par `pipeline.normalise`, avant
    # que la demande ne bifurque vers une réponse immédiate ou un job :
    # c'est ce qui garantit que les deux portes portent la même période.
    from card_api.pipeline import START_DEFAUT

    assert START_DEFAUT == "1968-01-01"
    j = client.get("/v1/trend", params={"stations": "F700000103",
                                        "cards": "QA"}).json()
    assert j["period"] == {"start": "1968-01-01", "end": None}
    # une demande explicite reste souveraine
    j = client.get("/v1/trend", params={"stations": "F700000103",
                                        "cards": "QA",
                                        "start": "1990-01-01"}).json()
    assert j["period"]["start"] == "1990-01-01"


def test_la_racine_v1_ne_cache_aucun_endpoint():
    """Elle était recopiée à la main et avait menti : trois endpoints
    ajoutés le 2026-07-28 n'y figuraient pas, si bien que la porte
    d'entrée du service en cachait une partie. Elle est maintenant
    dérivée des routes, et ce test tient la promesse."""
    from card_api.main import app

    annonces = set(client.get("/v1").json()["endpoints"].values())
    reels = {p for p in app.openapi()["paths"] if p.startswith("/v1")}
    assert reels <= annonces, sorted(reels - annonces)


def test_les_descriptions_ne_figent_pas_la_taille_du_corpus():
    """Un nombre de fiches écrit dans une description périme sans bruit :
    le corpus grandit, la phrase reste. Les descriptions disent donc la
    règle, pas le décompte."""
    import re

    spec = client.get("/openapi.json").json()
    textes = [q.get("description", "")
              for op in spec["paths"].values()
              for m in op.values()
              for q in m.get("parameters", [])]
    for t in textes:
        assert not re.search(r"\b\d{2,4} (des|sur) \d{2,4}\b", t), t


def test_la_consultation_est_journalisee_mais_pas_les_sondes():
    """Consulter le catalogue est un usage aussi réel que lancer un
    calcul : ne pas le journaliser faisait sous-estimer l'audience, alors
    que le journal sert de preuve d'impact.

    Mais tout ce qui est appelé EN BOUCLE par une machine reste muet :
    la sonde de santé, et le suivi d'un job qu'un client interroge sans
    cesse. Sinon le journal se remplit sans rien dire de l'usage."""
    import json

    from card_api import usage

    journal = usage.data_dir() / f"usage-{dt.datetime.now().year}.jsonl"
    avant = journal.stat().st_size if journal.exists() else 0

    client.get("/v1/cards", params={"limit": 1})
    client.get("/v1/vocabulary")
    client.get("/v1/health")

    lignes = [json.loads(x) for x in
              journal.read_text(encoding="utf-8")[avant:].splitlines() if x]
    vus = {e["endpoint"] for e in lignes}
    assert {"cards", "vocabulary"} <= vus
    assert "health" not in vus, "la sonde de surveillance doit rester muette"
    assert all(e["famille"] == "découverte" for e in lignes)


def test_les_defauts_de_compose_suivent_le_code():
    """`compose.yaml` fournit un défaut pour chaque réglage : s'il diverge
    de celui du code, retirer une ligne de son `.env` change le
    comportement en silence, dans le sens de l'ancien réglage.

    Trouvé le 2026-07-29 : `CARD_API_PRIORITY_CARDS` valait encore 226
    dans compose alors que le code était passé à 0 (sans limite). 226
    était la taille du corpus au jour où il avait été écrit, un plafond
    qui redevenait mordant dès que card gagnait une fiche.

    On compare les DÉCLARATIONS des deux fichiers, pas les valeurs du
    module : celles-ci sont remplacées par la fixture de test, et un test
    qui lit l'état courant ne dirait rien du défaut livré.
    """
    import pathlib
    import re

    racine = pathlib.Path(__file__).resolve().parents[1]
    compose = dict(re.findall(
        r"\$\{(CARD_API_[A-Z_]+):-([^}]*)\}",
        (racine / "compose.yaml").read_text()))
    code = {}
    for module in ("jobs.py", "usage.py"):
        code.update(dict(re.findall(
            r'os\.environ\.get\("(CARD_API_[A-Z_]+)",\s*([0-9.]+)\)',
            (racine / "src" / "card_api" / module).read_text())))

    assert code, "aucun défaut lu dans le code"
    manquants = [n for n in code if n not in compose]
    assert not manquants, f"absents de compose.yaml : {manquants}"
    for nom, attendu in code.items():
        assert float(compose[nom]) == float(attendu), (
            f"{nom} : compose dit {compose[nom]}, le code dit {attendu}")


def test_les_limites_sont_publiees_et_ne_peuvent_pas_mentir():
    """Un client doit pouvoir DÉCOUVRIR les limites : découper sa liste,
    choisir entre l'appel direct et le job, espacer ses requêtes. Il ne
    pouvait que se cogner à un 422 ou à un 429.

    Elles sont lues dans les modules qui les appliquent, jamais recopiées.
    Le 2026-07-29, la description de /v1/extract annonçait encore
    « 10 stations, 20 fiches » alors que le seuil était devenu double :
    un nombre recopié dans une prose périme sans bruit.
    """
    from card_api import jobs, usage

    lim = client.get("/v1").json()["limits"]
    assert lim["sync"]["stations_to_download"] == jobs.SYNC_STATIONS
    assert lim["sync"]["stations_total"] == jobs.SYNC_STATIONS_CACHED
    assert lim["sync"]["cards"] == jobs.SYNC_CARDS
    assert lim["job"]["stations"] == jobs.JOB_STATIONS
    assert lim["job"]["cards"] == jobs.JOB_CARDS
    assert lim["rate_per_minute"]["compute"] == usage.RATE_COMPUTE
    assert lim["rate_per_minute"]["light"] == usage.RATE_LIGHT


def test_aucune_description_ne_fige_un_plafond():
    """Même règle que pour la taille du corpus, étendue aux plafonds et
    aux descriptions d'OPÉRATIONS, pas seulement de paramètres : c'est là
    que la phrase périmée s'était glissée."""
    import re

    spec = client.get("/openapi.json").json()
    textes = []
    for chemin in spec["paths"].values():
        for op in chemin.values():
            textes.append(op.get("description", ""))
            textes += [q.get("description", "")
                       for q in op.get("parameters", [])]
    motif = re.compile(r"\b\d{2,4} (stations|fiches)\b")
    fautifs = [t for t in textes if motif.search(t)]
    assert not fautifs, fautifs

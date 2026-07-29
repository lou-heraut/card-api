# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Un résultat, plusieurs représentations, un seul chemin de rendu.

Le service a déjà connu deux fois le même bug : une logique écrite deux
fois, corrigée d'un côté seulement. D'abord le ticket de job, qui ne
sortait qu'en JSON et rendait un 500 partout ailleurs ; puis la chaîne de
calcul, dupliquée entre `main` et `jobs`.

Servir un CSV depuis un job rouvrait exactement ce risque, sur l'axe du
RENDU cette fois : trois rendus alimentés par des DataFrames vivants, un
résultat gelé qui n'existe que sérialisé, donc trois occasions d'écrire
un second chemin. Ces tests verrouillent le choix inverse, un rendu ne
prend que le résultat sérialisé, et vérifient ce qui compte vraiment :
que les deux portes rendent le MÊME fichier.
"""

import time

import pytest
from fastapi.testclient import TestClient

from card_api.main import app

client = TestClient(app)

STATIONS = "K0550010,F7000001"


@pytest.fixture(autouse=True)
def _hubeau(hubeau_simule):
    return hubeau_simule


def _job_fini(endpoint, **extra):
    jid = client.post("/v1/jobs", json={
        "endpoint": endpoint, "stations": STATIONS,
        "cards": "QA", **extra}).json()["job"]
    for _ in range(80):
        if client.get(f"/v1/jobs/{jid}").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert client.get(f"/v1/jobs/{jid}").json()["status"] == "done"
    return jid


def _lignes(texte):
    """Les données seules, sans le bandeau de provenance."""
    return [li for li in texte.split("\n") if not li.startswith("#")]


@pytest.mark.parametrize("endpoint", ["extract", "trend"])
def test_le_csv_est_le_meme_par_les_deux_portes(endpoint):
    """Le cœur du sujet. Si ces deux fichiers divergent un jour, c'est
    qu'un second chemin de rendu a été écrit."""
    direct = client.get(f"/v1/{endpoint}.csv",
                        params={"stations": STATIONS, "cards": "QA"})
    assert direct.status_code == 200
    par_job = client.get(f"/v1/jobs/{_job_fini(endpoint)}/result.csv")
    assert par_job.status_code == 200
    assert _lignes(par_job.text) == _lignes(direct.text)


def test_la_figure_est_la_meme_par_les_deux_portes():
    direct = client.get("/v1/trend/figure",
                        params={"stations": STATIONS, "cards": "QA"})
    par_job = client.get(f"/v1/jobs/{_job_fini('trend')}/result/figure")
    assert par_job.status_code == 200
    assert par_job.text == direct.text


def test_la_representation_ne_depend_pas_de_la_porte_d_entree():
    """Un job déposé en demandant du JSON se récupère en CSV et en figure.
    Ce qui limite les représentations n'est pas l'endpoint d'origine, mais
    ce que le résultat CONTIENT."""
    jid = _job_fini("trend")
    for chemin, attendu in ((f"/v1/jobs/{jid}/result", "application/json"),
                            (f"/v1/jobs/{jid}/result.csv", "text/csv"),
                            (f"/v1/jobs/{jid}/result/figure", "text/plain")):
        r = client.get(chemin)
        assert r.status_code == 200, chemin
        assert attendu in r.headers["content-type"], chemin


def test_une_extraction_n_a_pas_de_figure():
    """Le contenu commande : pas de verdict de stationnarité dans une
    extraction. Le refus nomme la représentation qui, elle, existe."""
    jid = _job_fini("extract")
    r = client.get(f"/v1/jobs/{jid}/result/figure")
    assert r.status_code == 422
    assert "result.csv" in r.json()["detail"]


def test_orient_columns_ne_casse_pas_les_rendus():
    """L'orientation est normalisée par le rendu lui-même.

    Elle l'était chez l'appelant, ce qui marchait tant que le seul
    appelant tenait des DataFrames. Un résultat gelé sous `orient=columns`
    aurait produit une figure VIDE, sans erreur : le pire des deux mondes.
    """
    jid = _job_fini("trend", orient="columns")
    csv = client.get(f"/v1/jobs/{jid}/result.csv")
    assert csv.status_code == 200
    assert len(_lignes(csv.text)) > 2                  # en-tête + des lignes
    fig = client.get(f"/v1/jobs/{jid}/result/figure")
    assert fig.status_code == 200
    assert "TENDANCE" in fig.text and "K0550010" in fig.text


def test_le_ticket_csv_annonce_ou_prendre_le_csv():
    """Demander un CSV et recevoir un ticket qui ne mène qu'à du JSON
    était la friction signalée : le ticket porte maintenant l'adresse de
    sa propre représentation."""
    stations = ",".join(f"K{i:07d}" for i in range(11))   # > plafond sync
    r = client.get("/v1/trend.csv", params={"stations": stations,
                                            "cards": "QA"})
    assert r.status_code == 202
    jid = r.headers["location"].rsplit("/", 1)[-1]
    assert f"/v1/jobs/{jid}/result.csv" in r.text

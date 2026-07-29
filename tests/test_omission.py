# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Une station sans série exploitable est écartée, pas fatale.

Le service refusait tout le lot pour une seule station muette : vingt
stations demandées, une échelle limnimétrique parmi elles, et les
dix-neuf autres étaient perdues avec le travail déjà fait. Or rien dans
le référentiel Hub'Eau ne permet de le savoir d'avance.

Ce qui se teste ici n'est donc pas « ça ne plante plus » mais le contrat
qui remplace le refus : le résultat dit exactement ce qu'il contient,
dans TOUTES ses représentations, et ne se laisse jamais lire comme
complet quand il ne l'est pas.
"""

import pytest
from fastapi.testclient import TestClient

from card_api import hubeau
from card_api.main import app

client = TestClient(app)

# Le simulé de conftest fait taire toute station en X. Trois vivantes,
# une muette : la forme même du cas qui cassait.
VIVANTES = "K0550010,F7000001,K0114020"
AVEC_MUETTE = "K0550010,X0000001,F7000001"


@pytest.fixture(autouse=True)
def _hubeau(hubeau_simule):
    return hubeau_simule


def test_une_station_muette_n_annule_pas_les_autres():
    r = client.get("/v1/extract",
                   params={"stations": AVEC_MUETTE, "cards": "QA"})
    assert r.status_code == 200
    body = r.json()
    assert body["stations"] == ["K0550010", "F7000001"]      # les DONNÉES
    assert body["stations_requested"] == ["K0550010", "X0000001", "F7000001"]
    (omise,) = body["stations_omitted"]
    assert omise["code_station"] == "X0000001"
    assert omise["reason"] == "no_series"
    assert "X0000001" in omise["detail"]
    # et le calcul a bien porté sur les deux survivantes
    vues = {row["code_station"] for row in body["data"]["QA"]}
    assert vues == {"K0550010", "F7000001"}


def test_le_bloc_existe_toujours_meme_vide():
    """Une clé qui apparaît seulement en cas de problème oblige chaque
    client à tester sa présence, et laisse croire à celui qui l'ignore
    que le cas n'existe pas."""
    body = client.get("/v1/extract",
                      params={"stations": VIVANTES, "cards": "QA"}).json()
    assert body["stations_omitted"] == []
    assert body["stations"] == body["stations_requested"]


def test_toutes_muettes_reste_un_refus():
    """Rien à calculer : un 200 portant zéro ligne serait un mensonge
    poli, du genre qu'un script avale sans broncher."""
    r = client.get("/v1/extract",
                   params={"stations": "X0000001,X0000002", "cards": "QA"})
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "X0000001" in detail and "X0000002" in detail  # nommées, toutes


def test_hubeau_injoignable_n_est_jamais_une_omission(monkeypatch):
    """La ligne de partage est la reproductibilité, pas la gravité. Une
    panne Hub'Eau est transitoire : la sauter fabriquerait des résultats
    silencieusement plus petits les jours de panne, ce que personne ne
    remarquerait au milieu d'un bloc d'omissions."""
    def indisponible(station, refresh=False):
        raise hubeau.HubEauIndisponible("Hub'Eau ne répond pas")

    monkeypatch.setattr(hubeau, "fetch_chronicle", indisponible)
    r = client.get("/v1/extract",
                   params={"stations": VIVANTES, "cards": "QA"})
    assert r.status_code == 504
    assert "Retry-After" in r.headers


def test_periode_sans_mesure_est_une_omission(monkeypatch, hubeau_simule):
    """Chronique présente mais rien dans la fenêtre demandée : c'est un
    fait stable de la station, il se rapporte comme les autres plutôt que
    d'annuler les stations qui, elles, couvrent la période. Cas réel des
    stations récentes dans une étude qui remonte à 1968."""
    def recente_pour_une(station, refresh=False):
        df = hubeau_simule(station)
        if station == "F7000001":                  # ouverte en 2010
            df = df[df["date"] >= "2010-01-01"]
        return df

    monkeypatch.setattr(hubeau, "fetch_chronicle", recente_pour_une)
    body = client.get("/v1/extract", params={
        "stations": VIVANTES, "cards": "QA",
        "start": "1970-01-01", "end": "1990-12-31"}).json()
    assert body["stations"] == ["K0550010", "K0114020"]
    (omise,) = body["stations_omitted"]
    assert omise["code_station"] == "F7000001"
    assert omise["reason"] == "no_data_in_period"
    assert "1970-01-01" in omise["detail"]


def test_l_omission_voyage_dans_le_csv():
    """Un tableur ne verra jamais le JSON : sans ces lignes, un CSV de
    deux stations pour une demande de trois se lit comme complet."""
    for chemin in ("/v1/extract.csv", "/v1/trend.csv"):
        r = client.get(chemin, params={"stations": AVEC_MUETTE,
                                       "cards": "QA"})
        assert r.status_code == 200, chemin
        entete = [li for li in r.text.split("\n") if li.startswith("#")]
        ecartees = [li for li in entete if "station écartée" in li]
        assert len(ecartees) == 1, chemin
        assert "X0000001" in ecartees[0] and "no_series" in ecartees[0]
        # la ligne `stations` du bandeau ne ment pas non plus
        (ligne,) = [li for li in entete if li.startswith("# stations :")]
        assert "X0000001" not in ligne


def test_l_omission_voyage_dans_la_figure():
    r = client.get("/v1/trend/figure", params={"stations": AVEC_MUETTE,
                                               "cards": "QA"})
    assert r.status_code == 200
    assert "1 station(s) écartée(s) sur 3 demandées" in r.text
    assert "X0000001" in r.text


def test_stations_meta_couvre_les_omises():
    """Le référentiel porte les stations DEMANDÉES : c'est là qu'on lit
    pourquoi l'une n'a rien, le libellé suffisant souvent à l'expliquer."""
    appels = {}

    def faux_referentiel(codes):
        appels["codes"] = list(codes)
        return [{"code_station": c} for c in codes]

    import card_api.main as m
    original = m.hubeau.stations_referential
    m.hubeau.stations_referential = faux_referentiel
    try:
        body = client.get("/v1/extract", params={
            "stations": AVEC_MUETTE, "cards": "QA",
            "stations_meta": "true"}).json()
    finally:
        m.hubeau.stations_referential = original
    assert "X0000001" in appels["codes"]
    assert {s["code_station"] for s in body["stations_meta"]} \
        == set(body["stations_requested"])

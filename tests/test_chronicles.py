# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""La chronique journalière exposée, et la raison pour laquelle elle l'est.

Ce n'est pas le téléchargement évité : c'est que le graphe d'une page et la
carte de la même page doivent venir de la MÊME copie, avec la même
empreinte. Le premier test est donc celui de la provenance, pas celui du
contenu.
"""

import pytest
from fastapi.testclient import TestClient

from card_api import cache, pipeline
from card_api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _hubeau(hubeau_simule):
    return hubeau_simule


def test_la_chronique_vient_de_la_meme_copie_que_le_calcul(hubeau_simule):
    """**La raison d'être de cet endpoint.**

    Si l'export et l'extraction ne partageaient pas la copie, une page
    afficherait une carte et un graphe qui ne parlent pas du même état de
    la source, et rien ne le signalerait. Deux champs le prouvent :
    l'empreinte, qui identifie l'état de Hub'Eau, et la date de lecture.

    Les copies sont posées sur le disque exprès : sans fichier, la date de
    lecture retombe sur l'instant courant, qui diffère d'une requête à
    l'autre et ne prouverait donc rien.
    """
    for station in ("K0550010", "F7000001"):
        cache.store_chronicle(station, hubeau_simule(station))
    p = {"stations": "K0550010,F7000001"}
    chronique = client.get("/v1/chronicles", params=p).json()
    calcul = client.get("/v1/extract", params={**p, "cards": "QA"}).json()
    assert chronique["data_fingerprint"] == calcul["data_fingerprint"]
    assert chronique["data_fetched_at"] == calcul["data_fetched_at"]


def test_la_chronique_porte_ses_droits_et_sa_source():
    r = client.get("/v1/chronicles", params={"stations": "K0550010"})
    assert r.status_code == 200
    out = r.json()
    assert out["source"].startswith("Hub'Eau")
    assert out["rights"]["data"]["license"]
    assert out["stations"] == ["K0550010"]
    premiere = out["data"][0]
    assert set(premiere) == {"code_station", "date", "Q"}


def test_la_periode_borne_ce_qui_est_servi():
    """Une chronique entière pèse des dizaines de milliers de lignes : la
    fenêtre demandée doit vraiment couper ce qui part sur le réseau."""
    p = {"stations": "K0550010", "start": "2000-01-01", "end": "2000-12-31"}
    out = client.get("/v1/chronicles", params=p).json()
    assert len(out["data"]) == 366                   # 2000 est bissextile
    assert out["data"][0]["date"].startswith("2000-01-01")
    # ... et l'empreinte porte quand même sur la chronique ENTIÈRE
    entiere = client.get("/v1/chronicles",
                         params={"stations": "K0550010"}).json()
    assert out["data_fingerprint"] == entiere["data_fingerprint"]


def test_le_plafond_borne_le_transfert(monkeypatch):
    """Ailleurs un plafond borne un calcul, que la bascule en file
    rattrape. Ici il borne un transfert, et rien ne le rattrape : le refus
    doit donc être franc et nommer le plafond."""
    monkeypatch.setattr(pipeline, "CHRONICLE_STATIONS", 2)
    r = client.get("/v1/chronicles",
                   params={"stations": "K0550010,F7000001,K0550012"})
    assert r.status_code == 422
    assert "2 stations" in r.json()["detail"]


def test_une_station_muette_est_ecartee_et_non_fatale():
    """Même règle que partout : ce qui est vrai de la station se rapporte,
    et n'annule pas le lot."""
    out = client.get("/v1/chronicles",
                     params={"stations": "K0550010,X0000000"}).json()
    assert out["stations"] == ["K0550010"]
    assert [o["reason"] for o in out["stations_omitted"]] == ["no_series"]


def test_le_csv_porte_sa_provenance_sans_inventer_de_fiche():
    """Un export de chronique n'a ni fiche ni fenêtre d'échantillonnage :
    l'en-tête décrit ce que l'enveloppe porte, il ne récite pas une liste
    fixe. Et il porte la source, l'empreinte et les droits, sans quoi un
    tableau de chiffres ne dit plus d'où il vient."""
    r = client.get("/v1/chronicles.csv", params={"stations": "K0550010",
                                                 "start": "2000-01-01",
                                                 "end": "2000-01-31"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    entete = [ligne for ligne in r.text.splitlines() if ligne.startswith("#")]
    texte = "\n".join(entete)
    assert "fiches :" not in texte and "échantillonnage" not in texte
    assert "stations : K0550010" in texte
    assert "empreinte" in texte and "Hub'Eau" in texte
    assert "chronicles" in r.headers["content-disposition"]
    assert r.text.splitlines()[len(entete)].startswith("code_station,date,Q")


def test_les_deux_representations_disent_la_meme_chose():
    """Une représentation, une URL : le CSV n'est pas un second calcul,
    c'est le même résultat autrement écrit."""
    p = {"stations": "K0550010", "start": "2010-01-01", "end": "2010-01-10"}
    js = client.get("/v1/chronicles", params=p).json()
    csv = client.get("/v1/chronicles.csv", params=p).text
    lignes = [ligne for ligne in csv.splitlines()
              if not ligne.startswith("#")]
    assert len(lignes) == len(js["data"]) + 1        # + la ligne de colonnes
    assert js["data"][0]["Q"] == pytest.approx(float(lignes[1].split(",")[2]))

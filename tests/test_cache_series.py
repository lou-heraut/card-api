# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Le second étage de cache : sa clé, et son magasin.

La clé d'abord, parce que c'est la seule partie du chantier où une erreur
est invisible : une clé trop complète ne coûte que des recalculs, une clé
incomplète rend des résultats faux, en silence.
"""

import pandas as pd
import pytest

from card_api import cache, pipeline

# Une fiche à fenêtre ADAPTATIVE, et c'est délibéré. `QA` déclare `09-01`
# et sa fenêtre préférée est `09-01` : l'absence de paramètre et
# `preferred` y donnent le même résultat, si bien qu'un test écrit sur
# `QA` resterait vert le jour où quelqu'un « normaliserait » la fenêtre
# dans la clé, en laissant le bug entier. Sur `dtLF` les deux diffèrent.
FICHE = "dtLF"

BASE = dict(station="K0550010", empreinte="v1:abc123", fiche=FICHE,
            start="1968-01-01", end=None, sampling=None, build="b-1")


def test_la_cle_est_stable_et_se_lit():
    """Fonction pure : mêmes ingrédients, même clé. Et le nom porte la
    fiche et la station en clair, pour que `ls data/series` se lise."""
    assert pipeline.cle_serie(**BASE) == pipeline.cle_serie(**BASE)
    cle = pipeline.cle_serie(**BASE)
    assert cle.startswith(f"{FICHE}-K0550010-")
    assert len(cle.rsplit("-", 1)[1]) == 64          # sha256 en hexadécimal


@pytest.mark.parametrize("champ, valeur", [
    ("station", "F700000103"),      # une autre station, une autre série
    ("empreinte", "v1:autre"),      # Hub'Eau a révisé la chronique
    ("fiche", "QA"),                # un autre calcul
    ("start", "1990-01-01"),        # 21 fiches series dépendent de la fenêtre
    ("end", "2020-12-31"),          # idem, et une fin posée n'est pas l'absence
    ("sampling", "preferred"),      # trois états, jamais normalisés
    ("sampling", "09-01"),
    ("build", "b-2"),               # image reconstruite : environnement neuf
])
def test_chaque_ingredient_change_la_cle(champ, valeur):
    """Le garde-fou de la règle : ajouter demain un paramètre à
    l'extraction sans l'ajouter à la clé doit casser ce test."""
    autre = dict(BASE, **{champ: valeur})
    assert pipeline.cle_serie(**autre) != pipeline.cle_serie(**BASE)


def test_le_swhid_de_la_fiche_entre_dans_la_cle():
    """Une version de fiche se bosse à la main, un SWHID non : c'est le
    hash du contenu du YAML. C'est lui qui distingue deux définitions."""
    assert pipeline.swhid_de_fiche(FICHE).startswith("swh:1:cnt:")
    assert pipeline.swhid_de_fiche("QA") != pipeline.swhid_de_fiche(FICHE)


def _serie():
    """Un cadre aux types que card rend vraiment : `code_station` en
    catégorie, la date d'agrégation, une valeur flottante (`QA`) et une
    valeur ENTIÈRE NULLABLE, comme une fiche de date (`tQJXA`)."""
    return pd.DataFrame({
        "code_station": pd.Series(["K0550010"] * 4, dtype="category"),
        "date": pd.date_range("1990-01-01", periods=4, freq="YS"),
        "QA": [11.25, float("nan"), 9.875, 10.5],
        "tQJXA": pd.array([120, None, 305, 88], dtype="Int64"),
    })


def test_l_aller_retour_rend_le_cadre_identique(monkeypatch, tmp_path):
    """C'est la raison du Parquet, et elle se vérifie ici.

    Un CSV relu perd le dernier bit des flottants, et surtout il ne sait
    pas qu'une colonne est une date ou un entier nullable : `tQJXA`
    repartirait en `Int64` et reviendrait en `float64`. Une réponse servie
    par le cache différerait alors d'une réponse calculée, ce qu'aucun
    lecteur ne remarquerait.
    """
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    df = _serie()
    cache.store_series("essai", df)
    relu = cache.load_series("essai")
    pd.testing.assert_frame_equal(df, relu, check_exact=True)
    assert relu["QA"].to_numpy().tobytes() == df["QA"].to_numpy().tobytes()


def test_une_serie_absente_rend_none(monkeypatch, tmp_path):
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    assert cache.load_series("jamais-calculee") is None


def test_un_fichier_illisible_est_traite_comme_absent(monkeypatch, tmp_path):
    """Une écriture interrompue par un arrêt brutal laisserait un fichier
    tronqué. Il se recalcule, et il est EFFACÉ : sans quoi il serait relu
    éternellement. Du temps perdu, jamais de la justesse."""
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    cache.series_path("abimee").write_bytes(b"ceci n'est pas du parquet")
    assert cache.load_series("abimee") is None
    assert not cache.series_path("abimee").exists()


def test_l_ecriture_ne_laisse_rien_derriere(monkeypatch, tmp_path):
    """Temporaire puis renommage : une lecture concurrente ne doit jamais
    tomber sur un fichier à moitié écrit."""
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    cache.store_series("propre", _serie())
    assert [f.name for f in cache.series_dir().iterdir()] == ["propre.parquet"]


def test_une_serie_servie_est_notee_au_registre(monkeypatch, tmp_path):
    """Même registre que les chroniques, même question pour l'éviction :
    qui a demandé cette entrée, et quand. Une série qu'on vient de
    calculer compte comme demandée, sans quoi elle sortirait du cache
    avant d'avoir servi."""
    monkeypatch.setenv("CARD_API_DATA", str(tmp_path))
    cle = "notee"
    assert cache._ligne_cle(cache._SERIE + cle) is None
    cache.store_series(cle, _serie())
    assert cache._ligne_cle(cache._SERIE + cle)[1] == 1
    cache.load_series(cle)
    assert cache._ligne_cle(cache._SERIE + cle)[1] == 2

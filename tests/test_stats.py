# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Tests du tableau de bord (`make stats`), sur ce qu'il COMPTE.

Le reste du cadre est de la mise en forme, qui se juge à l'œil. Ce qui
se teste, c'est l'arithmétique : un chiffre faux dans ce tableau ne se
voit pas, et il sert de preuve d'impact pour les financements.
"""

from datetime import date, timedelta

from card_api.stats import _activity_box

AUJOURD_HUI = str(date.today())
HIER = str(date.today() - timedelta(1))


def _rendu(entries):
    """Le cadre rendu, débarrassé de sa bordure : les tests lisent des
    chiffres, pas des filets."""
    return _activity_box(entries).replace("│", " ")


def test_un_job_ne_compte_pas_deux_fois():
    """`job_done` porte l'`endpoint` du traitement exécuté. Le filtre ne
    regardait que la présence de ce champ : chaque job était donc compté
    au dépôt PUIS à sa fin, et la famille calcul surestimait d'autant."""
    entries = [
        {"ts": AUJOURD_HUI, "user": "aaa", "endpoint": "jobs",
         "target": "trend"},
        {"ts": AUJOURD_HUI, "event": "job_done", "job": "x",
         "status": "done", "endpoint": "trend", "stations": 20},
    ]
    texte = _rendu(entries)
    assert "1 requêtes" in texte
    ligne = next(li for li in texte.split("\n") if li.strip().startswith("trend"))
    assert ligne.rstrip().endswith("0")     # le job fini n'est pas un appel


def test_les_refus_ne_sont_pas_des_usages():
    """Un utilisateur repoussé n'a rien consommé : son refus ne doit
    grossir aucune des deux familles, seulement la ligne REFUS."""
    entries = [
        {"ts": AUJOURD_HUI, "user": "aaa", "endpoint": "extract"},
        {"ts": AUJOURD_HUI, "user": "aaa", "event": "quota",
         "famille": "calcul", "endpoint": "extract", "limit": 60},
        {"ts": HIER, "user": "bbb", "event": "quota",
         "famille": "découverte", "endpoint": "cards", "limit": 300},
    ]
    texte = _rendu(entries)
    assert "1 requêtes" in texte                     # le refus n'y est pas
    ligne = next(li for li in texte.split("\n") if li.strip().startswith("REFUS"))
    assert ligne.rstrip().endswith("2")
    # La question qui permet de régler le plafond : une personne bloquée
    # vingt fois est un script mal écrit, vingt personnes bloquées une
    # fois est un plafond trop bas.
    assert "2 IP distinctes" in texte
    assert "1 calcul" in texte and "1 découverte" in texte


def test_aucun_refus_ne_dit_rien():
    """Un plafond qui ne mord jamais n'a rien à afficher."""
    texte = _rendu([{"ts": AUJOURD_HUI, "user": "aaa", "endpoint": "extract"}])
    assert "REFUS" not in texte

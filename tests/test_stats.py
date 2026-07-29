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


def test_le_tableau_garde_la_meme_forme_a_vide():
    """Toutes les lignes, toujours, zéro compris.

    Une ligne qui n'apparaît qu'au-dessus de zéro fait changer le tableau
    de forme d'un jour à l'autre : on cherche des yeux une ligne qu'on
    s'attendait à trouver, et on ne distingue plus « personne n'a appelé »
    de « je ne sais pas ». Un zéro est une information, souvent la plus
    utile puisqu'il dit qu'un endpoint qu'on maintient ne sert à personne.
    """
    from card_api.stats import ENDPOINTS_CALCUL, ENDPOINTS_DECOUVERTE

    vide = _rendu([])
    plein = _rendu([{"ts": AUJOURD_HUI, "user": "aaa", "endpoint": "extract"}])
    for label in ("CALCUL", "DÉCOUVERTE", "REFUS", "rendu", "fiches",
                  *ENDPOINTS_CALCUL, *ENDPOINTS_DECOUVERTE):
        assert label in vide, label
        assert label in plein, label
    assert vide.count("\n") == plein.count("\n")     # même hauteur, à vide
    assert "0 figure" in vide                        # les zéros sont écrits


def test_la_decouverte_est_ventilee_comme_le_calcul():
    """Savoir si les gens consultent `stations` ou `cards` demande une
    courbe par endpoint, pas un total : c'est ce que la famille calcul
    avait déjà et qui manquait ici."""
    entries = [{"ts": AUJOURD_HUI, "user": "aaa", "endpoint": "stations",
                "famille": "découverte"} for _ in range(4)]
    entries += [{"ts": HIER, "user": "bbb", "endpoint": "cards",
                 "famille": "découverte"}]
    texte = _rendu(entries)
    ligne = next(li for li in texte.split("\n")
                 if li.strip().startswith("stations"))
    assert ligne.rstrip().endswith("4")
    ligne = next(li for li in texte.split("\n") if li.strip().startswith("cards"))
    assert ligne.rstrip().endswith("1")
    ligne = next(li for li in texte.split("\n")
                 if li.strip().startswith("vocabulary"))
    assert ligne.rstrip().endswith("0")


def test_le_suivi_de_jobs_ne_passe_pas_pour_du_catalogue():
    """job_list et job_delete partagent le quota léger, donc la famille
    découverte, mais consulter ses propres tickets n'est pas consulter le
    catalogue : ils ont leur ligne, et le total reste juste."""
    entries = [{"ts": AUJOURD_HUI, "user": "aaa", "endpoint": e,
                "famille": "découverte"}
               for e in ("job_list", "job_delete", "cards")]
    texte = _rendu(entries)
    ligne = next(li for li in texte.split("\n") if li.strip().startswith("suivi"))
    assert ligne.rstrip().endswith("2")
    ligne = next(li for li in texte.split("\n")
                 if li.strip().startswith("DÉCOUVERTE"))
    assert ligne.rstrip().endswith("3")


def test_une_ligne_trop_longue_le_dit():
    """Elle était coupée en silence : « ✗ 5 échecs » se lisait « ✗ 5 éc »,
    un chiffre amputé qu'on croit complet."""
    from card_api.stats import W, _box

    rendu = _box("t", ["x" * (W + 20)])
    assert "…" in rendu
    assert all(len(li) == W + 4 for li in rendu.split("\n"))


def test_les_compteurs_de_la_file_tiennent_dans_le_cadre():
    from card_api.stats import W, _paquets

    segments = [f"compteur numéro {i} avec un libellé long" for i in range(5)]
    for ligne in _paquets(segments):
        assert len(ligne) <= W
    assert "".join(_paquets(segments)).count("compteur") == 5   # rien de perdu

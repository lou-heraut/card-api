# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""La chaîne de calcul, écrite UNE fois, et l'identité qu'elle publie.

Ce module existe à cause d'un bug. La chaîne extract/trend était écrite
deux fois : dans `main.py` pour les réponses immédiates, dans `jobs.py`
pour la file de calcul, cette seconde copie n'ayant d'autre raison d'être
que l'affichage de la progression. Une correction faite d'un côté
n'atteignait pas l'autre, et rien ne le signalait. Le 2026-07-29, les
stations sans série ont cessé d'être fatales en synchrone et sont restées
fatales en job, ce que l'utilisateur a découvert avant nous. En mesurant,
trois autres divergences sont apparues, dont une fenêtre temporelle
différente selon la porte employée : plus grave que la panne, puisqu'un
résultat faux ne se voit pas.

Le module ne connaît donc RIEN de HTTP. Il lève des exceptions neutres
que `main.py` traduit en codes, et que `jobs.py` enregistre telles
quelles. C'est ce qui permet aux deux portes d'appeler le même code.

Deux fonctions portent tout :

- `normalise` applique les défauts et les validations AVANT que la
  demande ne bifurque vers l'une ou l'autre porte. C'est là que se règle
  la classe de bug « selon par où l'on entre, la réponse diffère ».
- `compute` fait le calcul et assemble le résultat commun. Ce que `jobs`
  ajoute par-dessus (bloc de provenance, empreintes par station) est ce
  qui distingue légitimement un artefact gelé d'une réponse immédiate.

Le garde-fou est dans les tests : `test_les_deux_portes_rendent_le_meme_
contrat` compare les enveloppes, pas seulement les données. Il aurait
attrapé les quatre divergences.
"""

import datetime as dt
import json
import os
import re

import pandas as pd

import card

from . import hubeau
from .serialize import serialize

SOURCE = "Hub'Eau hydrométrie (eaufrance, Licence Ouverte), QmnJ en m³/s"

_SAMPLING_RE = re.compile(r"^(preferred|\d{2}-\d{2})$")

# Le LTP départage les ex-æquo au hasard (choix documenté dans le tools.R
# d'origine). Sans graine, deux appels identiques rendent des p-values
# différentes : le service en fixe donc une, en dur. Elle n'est pas
# réglable par déploiement, ce qui ne servirait personne ; si un jour on
# veut tester la sensibilité d'un verdict au tirage, c'est un paramètre
# de REQUÊTE qu'il faudra, pas une variable d'environnement.
LTP_SEED = 0

# Début de la fenêtre d'analyse quand la demande n'en donne pas. Ce n'est
# PAS « toute la chronique » : 1968 est la borne d'analyse du projet,
# celle des validations MAKAHO, et le point à partir duquel le réseau
# hydrométrique français est assez fourni pour que des stations se
# comparent entre elles. Laisser courir jusqu'aux plus anciennes séries
# donnerait, sans que personne ne l'ait demandé, des périodes de
# longueurs très différentes d'une station à l'autre.
#
# Conséquence assumée : les mesures antérieures à 1968 ne sont pas
# reprises par défaut. Elles restent accessibles en donnant `start`
# explicitement, et la période effective est publiée dans chaque réponse
# (bloc `period`) : le résultat dit toujours sur quoi il porte.
#
# Pas de borne de fin symétrique : on veut suivre la chronique jusqu'à
# son dernier jour disponible, donc ne pas en poser.
START_DEFAUT = "1968-01-01"

MK_DEFAUT = "AR1"
LEVEL_DEFAUT = 0.1
ORIENT_DEFAUT = "records"


# ── Identité du calcul ─────────────────────────────────────────────────

try:
    from importlib.metadata import version as _pkg_version
    try:
        CARD_VERSION = _pkg_version("card")
    except Exception:       # distribution "card-stase" (PEP 541 en attente)
        CARD_VERSION = _pkg_version("card-stase")
except Exception:                                    # non installé
    CARD_VERSION = "dev"

try:
    STASE_VERSION = _pkg_version("stase")
except Exception:                                    # non installé
    STASE_VERSION = "dev"

try:
    API_VERSION = _pkg_version("card-api")
except Exception:                                    # exécution hors install
    API_VERSION = "dev"


# Commits résolus à la construction de l'image (scripts/resolve_refs.py).
# Un numéro de version ne désigne un état unique que si la ref était un
# tag ; le commit, lui, désigne toujours un état et un seul. Absent hors
# Docker : le service annonce alors le seul numéro de version.
def _build_refs():
    path = os.environ.get("CARD_API_BUILD_REFS", "/app/build_refs.json")
    try:
        with open(path, encoding="utf-8") as f:
            refs = json.load(f)
        return (refs.get("card", {}).get("commit"),
                refs.get("stase", {}).get("commit"))
    except Exception:
        return None, None


CARD_COMMIT, STASE_COMMIT = _build_refs()


def versions():
    """Identité du calcul, telle qu'elle part chez l'utilisateur.

    Le numéro dit la version publiée, le commit dit l'état exact. Les
    versions des FICHES employées voyagent à part, dans les métadonnées :
    une par variable, puisque deux fiches d'une même réponse peuvent
    avoir des versions différentes.
    """
    v = {"card_version": CARD_VERSION, "stase_version": STASE_VERSION,
         "api_version": API_VERSION}
    # Pour un dépôt git, l'identifiant Software Heritage d'une révision
    # est swh:1:rev: suivi du hash du commit : citable tel quel, sans
    # appel d'API, dès lors que le dépôt a été archivé une fois.
    if CARD_COMMIT:
        v["card_commit"] = CARD_COMMIT
        v["card_swhid"] = f"swh:1:rev:{CARD_COMMIT}"
    if STASE_COMMIT:
        v["stase_commit"] = STASE_COMMIT
        v["stase_swhid"] = f"swh:1:rev:{STASE_COMMIT}"
    return v


def rights():
    """Droits sur un résultat : il combine des données ouvertes (Hub'Eau)
    et des définitions GPL (fiches CARD). Les énoncer, c'est le rendre
    réutilisable sans zone grise (FAIR, le R de Reusable)."""
    return {
        "data": {
            "source": "Hub'Eau (eaufrance)",
            "license": "Licence Ouverte / Etalab 2.0",
            "url": "https://hubeau.eaufrance.fr/",
        },
        "definitions": {
            "source": "fiches CARD",
            "license": "GPL-3.0-or-later",
            "url": "https://github.com/lou-heraut/card",
        },
        "cite": "https://github.com/lou-heraut/card/blob/main/CITATION.cff",
    }


def fetched_at(stations):
    """Date de lecture des chroniques employées, la plus ancienne.

    Hub'Eau révise ses données : sans cette date, deux résultats
    identiques en apparence ne sont pas comparables. On prend la plus
    ancienne des chroniques du lot, qui borne l'âge de l'ensemble.

    À défaut d'information (chronique jamais mise en cache), on rend
    l'instant courant : la donnée a forcément été lue au plus tard
    maintenant, c'est une borne vraie, simplement moins précise.
    """
    dates = [d for d in (hubeau.chronicle_fetched_at(s) for s in stations) if d]
    if dates:
        return min(dates)
    return (dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0).isoformat())


# ── Paramètres : normalisés une fois, pour les deux portes ─────────────

class ParametresInvalides(ValueError):
    """Demande refusable sans rien télécharger. `main.py` en fait un 422."""


def normalise(params: dict) -> dict:
    """Les défauts et les validations, AVANT la bifurcation sync/job.

    C'est ici que se règle la classe de bug « selon la porte employée, la
    réponse diffère ». `START_DEFAUT` était appliqué dans les endpoints
    synchrones seulement : un `POST /v1/jobs` sans `start` calculait donc
    sur toute la chronique là où `GET /v1/extract` partait de 1968, sans
    que rien ne le dise. Le paramètre résolu ICI part ensuite partout, y
    compris dans les paramètres GELÉS d'un job, si bien qu'une demande et
    le job qu'elle engendre portent la même fenêtre.
    """
    p = dict(params)
    p["start"] = p.get("start") or START_DEFAUT
    p.setdefault("end", None)
    p.setdefault("sampling", None)
    p["orient"] = p.get("orient") or ORIENT_DEFAUT
    if p.get("endpoint") == "trend":
        p["mk"] = p.get("mk") or MK_DEFAUT
        p["level"] = LEVEL_DEFAUT if p.get("level") is None else p["level"]
    sampling = p.get("sampling")
    if sampling is not None and not _SAMPLING_RE.match(sampling):
        raise ParametresInvalides(
            f"sampling invalide : {sampling!r}. Valeurs acceptées : "
            "'preferred' (fenêtre fixe déclarée par chaque fiche) "
            "ou 'MM-JJ' (ex. '09-01')")
    return p


# ── La chaîne, écrite une fois ─────────────────────────────────────────

def _omission(station: str, reason: str, detail) -> dict:
    """Une station écartée du calcul, dite en clair ET en code.

    `reason` se teste par un programme, `detail` se lit par un humain.
    Le nom de colonne est `code_station`, celui de Hub'Eau, pour que le
    bloc se joigne au référentiel sans traduction (règle du service).
    """
    return {"code_station": station, "reason": reason, "detail": str(detail)}


class RienACalculer(ValueError):
    """Toutes les stations écartées. `main.py` en fait un 404."""


def chroniques(stations, start, end, progress=None):
    """Les chroniques utilisables, et le compte rendu de ce qui a sauté.

    Rend (data, empreintes, retenues, omises). L'empreinte est prise sur
    la chronique ENTIÈRE, avant filtre de période : la période demandée
    figure déjà dans la provenance, et ce qu'on identifie ici c'est la
    source.

    Une station sans série exploitable est OMISE, pas fatale. Le contraire
    a longtemps été vrai et c'était trop raide : une seule station muette
    sur vingt annulait les dix-neuf autres, et le travail déjà fait était
    perdu. Or il n'existe aucun moyen de le savoir d'avance, le référentiel
    Hub'Eau ne portant pas l'information (ni `type_station` ni `en_service`
    ne disent si une série de débit existe : vérifié le 2026-07-29, une
    station en service peut n'avoir aucun QmnJ, une station fermée peut
    avoir vingt ans d'historique). Demander la série EST le seul test.

    La ligne de partage n'est donc pas la gravité mais la REPRODUCTIBILITÉ :
    ce qui est vrai de la station elle-même (elle ne publie pas de débit,
    son code est un site ambigu, il n'y a rien dans la période demandée)
    est un fait stable, qui se rapporte ; ce qui tient à l'instant de
    l'appel (Hub'Eau injoignable) remonte tel quel. Sauter le second
    fabriquerait des résultats silencieusement plus petits les jours de
    panne, ce qu'aucun lecteur ne remarquerait.
    """
    frames, empreintes, retenues, omises = [], {}, [], []
    total = len(stations)
    for i, s in enumerate(stations):
        if progress:
            progress(i, total, f"chronique {s}")
        try:
            df = hubeau.fetch_chronicle(s)
        except hubeau.StationInconnue as e:
            omises.append(_omission(s, "no_series", e))
            continue
        except hubeau.SiteAmbigu as e:
            omises.append(_omission(s, "ambiguous_site", e))
            continue
        empreintes[s] = hubeau.fingerprint(df)
        if start:
            df = df[df["date"] >= start]
        if end:
            df = df[df["date"] <= end]
        if df.empty:
            del empreintes[s]        # rien n'a servi, rien n'est à identifier
            omises.append(_omission(
                s, "no_data_in_period",
                f"chronique présente, mais aucune mesure entre "
                f"{start or 'le début'} et {end or 'la fin'}"))
            continue
        retenues.append(s)
        frames.append(df)
    if not frames:
        # Toutes omises : il n'y a rien à calculer. Un 200 portant zéro
        # ligne serait un mensonge poli, du genre qu'un script avale sans
        # broncher. On refuse en nommant chaque station et son motif.
        detail = " ; ".join(f"{o['code_station']} ({o['detail']})"
                            for o in omises)
        raise RienACalculer(
            f"aucune des {total} stations demandées n'a de série "
            f"exploitable : {detail}")
    return (pd.concat(frames, ignore_index=True),
            empreintes, retenues, omises)


def compute(params: dict, progress=None, verrou=None) -> dict:
    """Le calcul et le résultat COMMUN aux deux portes.

    `params` sort de `normalise`. `progress(fait, total, phase)` est
    optionnel : c'est la seule chose que la file avait de plus, et c'est
    devenu un paramètre au lieu d'une seconde implémentation. `verrou`
    est le sémaphore qui sérialise les calculs lourds, passé de
    l'extérieur pour que ce module ignore la file.

    Rend le dictionnaire de résultat, plus les objets intermédiaires dont
    les appelants ont besoin (`_extracted`, `_trend`, `_empreintes`),
    préfixés d'un souligné : ils ne partent pas chez l'utilisateur, c'est
    l'appelant qui les retire.
    """
    st, cd = params["stations"], params["cards"]
    data, empreintes, retenues, omises = chroniques(
        st, params["start"], params["end"], progress)

    total = len(st)
    if progress:
        progress(total, total, "extraction")
    ctx = verrou if verrou is not None else _sans_verrou()
    with ctx:
        res = card.extract(data, cards=cd,
                           sampling_period=params.get("sampling"),
                           verbose=False)
        extracted = res["data"]
        if not isinstance(extracted, dict):
            extracted = {cd[0]: extracted}
        tr = None
        if params.get("endpoint") == "trend":
            if progress:
                progress(total, total, "tendance")
            tr = card.trend(res, level=params["level"],
                            dependency=params["mk"], seed=LTP_SEED)

    sortie = tr["data"] if tr is not None else extracted
    orient = params["orient"]
    out = {
        **versions(),
        "rights": rights(),
        # `stations` décrit les DONNÉES, pas la demande : ce sont les
        # stations que `data` contient réellement. Recopier la demande
        # annoncerait vingt stations pour dix-neuf séries, et toute
        # jointure faite sur cette liste porterait à faux.
        "stations": retenues,
        "stations_requested": list(st),
        "stations_omitted": omises,
        "cards": list(cd),
        "period": {"start": params["start"], "end": params["end"]},
        "sampling": params.get("sampling"),
        "source": SOURCE,
        "data_fetched_at": fetched_at(retenues),
        "data_fingerprint": hubeau.combine_fingerprints(empreintes),
        "orient": orient,
        "meta": serialize(res["meta"]),
        "data": {k: serialize(v, orient) for k, v in sortie.items()},
    }
    if params.get("endpoint") == "trend":
        out["mk"] = params["mk"]
        out["level"] = params["level"]
        if params.get("series"):
            out["series"] = {k: serialize(v, orient)
                             for k, v in extracted.items()}
    return {**out, "_extracted": extracted, "_trend": tr,
            "_empreintes": empreintes}


class _sans_verrou:
    """Aucun sémaphore fourni (tests, appel direct) : on n'en invente pas."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def sans_prives(out: dict) -> dict:
    """Le résultat débarrassé des objets de travail (`_extracted`...)."""
    return {k: v for k, v in out.items() if not k.startswith("_")}

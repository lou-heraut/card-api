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
import hashlib
import json
import os
import re

import pandas as pd

import card
from importlib.metadata import version as _pkg_version

from . import cache, hubeau
from .serialize import serialize

# La provenance de card ET du moteur vient de card, qui répond de
# lui-même depuis sa 0.4.0. Le service ne déclare pas card en dépendance
# (l'image l'installe depuis GitHub à une ref choisie), donc rien ne
# vérifie la version à l'installation : autant que l'exigence soit dite
# ici, en une phrase, plutôt que sous la forme d'un AttributeError.
try:
    _card_provenance = card.provenance
except AttributeError as e:                             # card < 0.4.0
    raise RuntimeError(
        "card-api exige card >= 0.4.0, qui publie la provenance logicielle "
        f"(card.provenance). Version installée : {card.__version__}. "
        "Reconstruire l'image avec un CARD_REF plus récent."
    ) from e

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

# Commits résolus à la construction de l'image (scripts/resolve_refs.py).
# C'est la SEULE chose que card ne peut pas observer lui-même : l'image
# installe des ARCHIVES (`.../archive/main.tar.gz`), qui ne portent aucune
# trace de leur commit, là où une installation `git+…` l'enregistre (PEP
# 610). Celui qui a construit l'image est donc le seul à le savoir, et il
# le dit à card par `CARD_COMMIT` / `STASE_COMMIT`, que la résolution de
# card lit en premier. Une seule règle de résolution existe donc, la
# sienne, et le service n'apporte que ce que lui seul sait.
def _build_refs() -> dict:
    path = os.environ.get("CARD_API_BUILD_REFS", "/app/build_refs.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_REFS = _build_refs()

for _cle, _nom in (("CARD", "card"), ("STASE", "stase")):
    _commit = _REFS.get(_nom, {}).get("commit")
    if _commit and not os.environ.get(f"{_cle}_COMMIT"):
        os.environ[f"{_cle}_COMMIT"] = _commit

# card répond de lui-même et du moteur depuis card 0.4.0 : versions ET
# commits, quel que soit le mode d'installation (docstring de
# `card/provenance.py`). Le service ne le refait donc pas, il consomme.
# Deux méthodes divergentes pour le même fait finiraient par se
# contredire, et c'était déjà à moitié le cas : le numéro lu ici venait
# des métadonnées d'installation, qui périment en installation éditable.
_CARD = _card_provenance()

CARD_VERSION = _CARD.get("card_version") or "dev"
STASE_VERSION = _CARD.get("stase_version") or "dev"
CARD_COMMIT = _CARD.get("card_commit")
STASE_COMMIT = _CARD.get("stase_commit")

try:
    API_VERSION = _pkg_version("card-api")
except Exception:                                    # exécution hors install
    API_VERSION = "dev"

# Identité de la CONSTRUCTION de l'image, ingrédient de la clé du second
# étage de cache. Deux choses changent un résultat sans changer un
# commit : la bascule `CARD_ROLL_COMPAT`, documentée dans l'ORIGINE_R.md
# de card, qui modifie la moyenne mobile donc VCN10 et tout ce qui en
# découle ; et une reconstruction qui tire un numpy ou un pandas plus
# récent. L'instant de construction les couvre toutes les deux d'un coup,
# sans rien avoir à énumérer, et il s'écrit sans réseau donc ne peut pas
# manquer dans une image.
#
# ABSENT, le second étage est DÉSACTIVÉ, jamais dégradé : une clé amputée
# d'un ingrédient ferait collisionner deux états différents du code, ce
# qui rendrait des résultats faux sans que personne ne le voie. C'est le
# cas en développement, où il n'y a pas d'image du tout.
_BUILT_AT = _REFS.get("built_at")
BUILD_ID = (None if not _BUILT_AT
            else f"{_BUILT_AT}|{CARD_COMMIT}|{STASE_COMMIT}")

# SWHID des fiches employées, mémorisé : le corpus ne bouge pas pendant
# la vie du processus, l'image installant une révision de card et une
# seule.
_swhids: dict[str, str] = {}


def swhid_de_fiche(fiche: str) -> str:
    """Le SWHID du FICHIER de fiche, qui identifie sa définition exacte.

    Une version de fiche se bosse à la main, un SWHID non : c'est le hash
    du contenu du YAML, donc deux définitions différentes ne peuvent pas
    le partager. Il voyage déjà dans les métadonnées, colonne `swhid`, et
    s'obtient sans données.
    """
    if fiche not in _swhids:
        meta = card.extract(None, cards=[fiche], metadata_only=True,
                            verbose=False)["meta"]
        _swhids[fiche] = str(meta["swhid"].iloc[0])
    return _swhids[fiche]


def cle_serie(station: str, empreinte: str, fiche: str,
              start, end, sampling, build: str) -> str:
    """La clé d'une série dans le second étage de cache.

    **La règle qui commande tout** : une clé trop complète ne coûte que
    des recalculs, une clé incomplète rend des résultats faux, en
    silence, et personne ne le voit. On énumère donc tout ce qui peut
    influencer une valeur, et dans le doute on ajoute. Tout paramètre
    ajouté un jour à l'extraction entre dans la clé le même jour.

    Les ingrédients, et pourquoi chacun :

    - `station`, parce que l'extraction est indépendante d'une station à
      l'autre, ce qui est mesuré et ce qui rend une entrée par station
      légitime ;
    - `empreinte`, la révision Hub'Eau de CETTE chronique : Hub'Eau
      révise n'importe quel point de l'historique, pas seulement la queue
      récente ;
    - `fiche` et son `swhid`, la définition exacte du calcul ;
    - `start` et `end` **tels que demandés**, parce que 21 fiches
      `output: series` sur 99 ont une valeur qui dépend de la fenêtre
      entière (les seuils d'étiage, pris sur toute la période). Tels que
      DEMANDÉS et non tels qu'appliqués : une fin absente devient la
      dernière date du LOT, si bien qu'une clé prise sur la valeur
      effective dépendrait des autres stations de la demande. Une fin
      absente est donc gardée absente, et la fin réelle est celle de la
      chronique, déjà identifiée par son empreinte ;
    - `sampling` tel que demandé, **jamais normalisé** : absent,
      `preferred` et `MM-JJ` sont trois choses différentes pour une fiche
      à fenêtre adaptative. Mesuré, `dtLF` rend 42 lignes sans paramètre
      et 41 avec `preferred` ;
    - `build`, l'identité de construction de l'image (cf. `BUILD_ID`).

    Ce qui reste DEHORS, et c'est tout l'intérêt : `level`, `mk`,
    `series`, `orient`, `stations_meta`. Ils ne touchent que le test ou
    la mise en forme, si bien que déplacer le curseur de signification
    devient gratuit alors qu'il relançait toute l'agrégation.

    Le nom porte la fiche et la station en clair devant l'empreinte : ce
    ne sont pas des secrets, et `ls data/series` devient lisible au lieu
    d'être un mur de hachages. L'empreinte, elle, couvre TOUT, y compris
    ces deux-là.
    """
    brut = "\n".join([
        f"station={station}",
        f"empreinte={empreinte}",
        f"fiche={fiche}",
        f"swhid={swhid_de_fiche(fiche)}",
        f"start={start}",
        f"end={end}",
        f"sampling={sampling}",
        f"build={build}",
    ])
    return f"{fiche}-{station}-{hashlib.sha256(brut.encode()).hexdigest()}"


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
    dates = [d for d in (cache.collected_at(s) for s in stations) if d]
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
    # L'âge accepté d'une copie : la requête décide, la configuration donne
    # le défaut. Résolu ICI, donc le routage et le calcul lisent la même
    # valeur et ne peuvent plus se contredire, et un job gèle celle de la
    # demande qui l'a créé. `0` est légitime, « rien que du frais », donc
    # on teste l'absence et non la fausseté.
    if p.get("max_age") is None:
        p["max_age"] = cache.MAX_AGE_DAYS
    else:
        p["max_age"] = float(p["max_age"])
        if p["max_age"] < 0:
            raise ParametresInvalides(
                f"max_age invalide : {p['max_age']}. C'est un nombre de "
                "jours, donc positif ou nul ; 0 exige une lecture neuve "
                "chez Hub'Eau")
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


def chroniques(stations, start, end, progress=None, max_age=None):
    """Les chroniques utilisables, et le compte rendu de ce qui a sauté.

    Rend (data, empreintes, retenues, omises). Les chroniques sont
    transmises ENTIÈRES : la période est un paramètre du moteur, pas un
    découpage du service (cf. `compute`). L'empreinte porte donc, elle
    aussi, sur la chronique entière : la période demandée figure déjà
    dans la provenance, et ce qu'on identifie ici c'est la source.

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
            df = hubeau.fetch_chronicle(s, max_age=max_age)
        except hubeau.StationInconnue as e:
            omises.append(_omission(s, "no_series", e))
            continue
        except hubeau.SiteAmbigu as e:
            omises.append(_omission(s, "ambiguous_site", e))
            continue
        empreintes[s] = hubeau.fingerprint(df)
        # La période ne SERT PAS à découper ici : elle est un paramètre du
        # moteur, qui l'applique dans son ordre (grille, max_na_years,
        # coupe, fenêtre adaptative). Découper en amont privait
        # max_na_years de la chronique entière, c'est-à-dire de ce sur
        # quoi il est censé travailler. Elle ne sert donc qu'à écarter
        # proprement une station qui n'a rien à dire dans la fenêtre.
        dedans = df["date"].between(start or df["date"].min(),
                                    end or df["date"].max())
        if not dedans.any():
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
        st, params["start"], params["end"], progress,
        max_age=params.get("max_age"))

    total = len(st)
    if progress:
        progress(total, total, "extraction")
    ctx = verrou if verrou is not None else _sans_verrou()
    with ctx:
        # La période va au moteur, qui la fait passer à chaque process.
        # Borne haute absente : la dernière date disponible, sans effet
        # puisque le filtre est `date <= fin`, mais `stase` veut deux
        # bornes et une date inventée se lirait dans les traces.
        res = card.extract(data, cards=cd,
                           default_period=[params["start"],
                                           params["end"] or data["date"].max()],
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

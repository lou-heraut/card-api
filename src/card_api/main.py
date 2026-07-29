# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""card-api : service web des fiches CARD (v1).

Conception : docs/dev/API.md du repo card. Découverte du catalogue et
des stations, extraction Hub'Eau, tendance Mann-Kendall/Sen ; quotas
par IP et journal d'usage anonymisé (usage.py).
"""

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import urllib.parse
from typing import Annotated, Literal

import httpx
import pandas as pd
from fastapi import (Depends, FastAPI, HTTPException, Query, Request,
                     Response, Security)
from fastapi import Path as PathParam   # pathlib.Path est pris ailleurs
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               Response as _RawResponse)
from pydantic import BaseModel, Field

import card

from . import hubeau, jobs, usage
from .serialize import clean, serialize

_SAMPLING_RE = re.compile(r"^(preferred|\d{2}-\d{2})$")
SOURCE = "Hub'Eau hydrométrie (eaufrance, Licence Ouverte), QmnJ en m³/s"


def _card_meta_map():
    """{id de fiche: {input_vars, output}}, calculé une fois.
    input_vars : refuser les fiches non-débit sur les données Hub'Eau
    (l'affectation automatique de colonnes de la bibliothèque mapperait
    sinon Q sur n'importe quelle variable requise unique).
    output : la tendance n'a de sens que sur les fiches 'series'."""
    global _CARDS_META
    try:
        return _CARDS_META
    except NameError:
        from pathlib import Path
        df = card.list_cards()
        _CARDS_META = {}
        for p, iv, out in zip(df["script_path"], df["input_vars"],
                              df["output_en"]):
            _CARDS_META.setdefault(Path(p).stem,
                                   {"input_vars": iv, "output": out})
        return _CARDS_META

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


CARD_COMMIT, STASE_COMMIT = _build_refs()


def _fetched_at(stations):
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


# ── Vocabulaire de classification : des menus, pas des champs libres ──
#
# Les valeurs valides des facettes ne sont pas écrites ici : elles sont
# LUES dans card (topics.yaml, via card.vocabulary()). Déclarées en
# énumérations, elles partent dans l'OpenAPI, ce qui a deux effets d'un
# seul geste : une machine connaît les valeurs sans appeler
# /v1/vocabulary, et Swagger rend le champ en MENU DÉROULANT au lieu
# d'une saisie libre que personne ne peut deviner.
#
# L'API canonise sur le SLUG. `card.list_cards` accepte aussi les
# libellés fr/en ('basses eaux' vaut 'low-flows'), mais un contrat n'a
# qu'un identifiant par concept, et un menu à trois orthographes du même
# phénomène serait illisible. Le slug est justement ce qui n'appartient à
# aucune des deux langues (cf. docs/dev/TOPICS.md de card).
_VOCAB = card.vocabulary()


def _facet_enum(facette):
    """Type énuméré d'une facette, dans l'ordre déclaré du vocabulaire.

    L'ordre vient de topics.yaml et il est signifiant (basses eaux,
    moyennes eaux, hautes eaux...) : le trier alphabétiquement rendrait
    le menu plus difficile à lire, pas moins.
    """
    return Literal[tuple(_VOCAB[facette])]


def _facet_doc(facette, intro):
    """Description d'un filtre de facette, slugs glosés en français.

    Le menu déroulant n'affiche que des slugs : sans cette glose, rien à
    l'écran ne dit que `low-flows` désigne les basses eaux.
    """
    gloss = ", ".join(f"{slug} = {e['fr']}"
                      for slug, e in _VOCAB[facette].items())
    return f"{intro} {gloss}."


_Domain = _facet_enum("domain")
_Phenomenon = _facet_enum("phenomenon")
_Aspect = _facet_enum("aspect")
_Season = _facet_enum("season")
_Output = _facet_enum("output")
_Purpose = _facet_enum("purpose")

# Les autres listes fermées du service. Énumérées plutôt que vérifiées à
# la main : le contrat les annonce, Swagger en fait des menus, et le 422
# qu'on écrivait ligne à ligne devient automatique.
_Orient = Literal["records", "columns"]
_Mk = Literal["INDE", "AR1", "LTP"]
_Endpoint = Literal["extract", "trend"]

# Descriptions des paramètres communs à /v1/extract, /v1/trend et au corps
# de POST /v1/jobs. Écrites une fois : les trois points d'entrée décrivent
# les mêmes champs, et trois copies finiraient par diverger.
_D_STATIONS = ("Codes de stations Hub'Eau, séparés par des virgules. "
               "Les retrouver par nom avec /v1/stations : depuis la "
               "refonte Hydro, les anciens codes Banque Hydro ne valent "
               "plus. Exemple : `F700000103`, la Seine à Paris "
               "(Austerlitz).")
_D_CARDS = ("Identifiants de fiches, séparés par des virgules (colonne "
            "`id` de /v1/cards). Fiches à entrée Q uniquement, puisque "
            "les données sont hydrométriques. Exemple : `QA,VCN10`, le "
            "module annuel et l'étiage.")
_D_START = ("Début de la période, AAAA-MM-JJ. Par défaut **1968-01-01**, "
            "et non le début de la chronique : c'est la borne d'analyse "
            "du projet (validations MAKAHO) et le point à partir duquel "
            "le réseau hydrométrique français est assez fourni pour que "
            "des stations se comparent. Les mesures antérieures "
            "s'obtiennent en donnant une date plus ancienne.")
_D_END = ("Fin de la période, AAAA-MM-JJ. Par défaut, et c'est ce qu'on "
          "veut le plus souvent, le DERNIER JOUR DISPONIBLE : laisser "
          "vide pour suivre la chronique à mesure qu'elle s'allonge.")
# Ce paramètre décide du JOUR OÙ COMMENCE L'ANNÉE de calcul, pas d'une
# durée. Chaque fiche déclare le sien, et près d'un tiers du corpus le
# calcule sur la donnée plutôt que de le fixer : l'année démarre alors à
# une date propre à chaque série, c'est-à-dire à chaque couple
# station-variable. La formulation doit dire QUI varie, sans quoi « la
# fenêtre de la fiche » laisse croire à une valeur unique par fiche.
#
# Aucun DÉCOMPTE dans la description : le corpus grandit, la phrase
# resterait. C'est la fiche dessinée (/v1/cards/{id}/figure) qui dit le
# cas de chacune, et elle, elle est calculée.
_D_SAMPLING = (
    "Jour de départ de l'année de calcul. Par défaut, chaque fiche "
    "applique le sien : fixe pour la plupart, mais **calculé sur la "
    "donnée** pour d'autres, dont les étiages et les crues, dont "
    "l'année démarre alors à une date propre à chaque couple "
    "station-variable ; la fiche dessinée le dit pour chacune. "
    "`preferred` : impose à chaque fiche le départ FIXE qu'elle "
    "déclare, ce qui rend les stations comparables entre elles et "
    "reproductibles (protocole MAKAHO). `MM-JJ` (ex. `09-01`) : impose "
    "le même départ à toutes les fiches.")
_D_STATIONS_META = (
    "Joint sous `stations_meta` les fiches du référentiel Hub'Eau des "
    "stations demandées (libellé, longitude, latitude...). Le résultat "
    "devient autoportant : tracer une carte ne demande aucun fichier "
    "local.")
_D_ORIENT = ("Forme des tableaux rendus. `records` : liste d'objets, "
             "comme Hub'Eau. `columns` : {colonne: [valeurs]}, plus "
             "compact.")
_D_MK = ("Hypothèse du test de Mann-Kendall. `AR1` : robuste à "
         "l'autocorrélation d'ordre 1, fréquente sur les séries "
         "annuelles d'étiage (Hamed & Rao 1998). `INDE` : test "
         "standard, hypothèse d'indépendance. `LTP` : mémoire longue "
         "(Hamed 2008).")
_D_LEVEL = "Niveau de signification du test."
_D_SERIES = (
    "Joint sous `series` les séries extraites sur lesquelles la tendance "
    "a été calculée. Mêmes données garanties, puisque tout vient du même "
    "calcul : de quoi tracer les points et la tendance sans second appel.")
_D_JOB_ID = "Ticket rendu au dépôt du job (champ `job` de la réponse 202)."

# ── Exemples : ce qui remplit vraiment le champ ───────────────────────
#
# Un exemple par paramètre, et RIEN AUTOUR. Les trois formes que FastAPI
# accepte ne produisent pas le même contrat, et une seule remplit la case
# sans rien ajouter au-dessus :
#
#   examples=["F700..."]                  -> schema.examples (tableau) :
#       Swagger ne lit pas ce mot-clé pour un paramètre, le champ reste
#       vide avec son placeholder gris.
#   openapi_examples={"seine": {...}}     -> parameter.examples nommés :
#       remplit, mais pose un MENU DÉROULANT d'exemples au-dessus du
#       champ. Avec un seul exemple, ce menu n'affiche que le libellé
#       de la valeur qui est déjà dans la case juste en dessous.
#   json_schema_extra={"example": "..."}  -> schema.example (singulier) :
#       remplit, sans menu. C'est ce qu'on veut.
#
# `example` au singulier n'existe pas dans JSON Schema 2020-12, qui n'a
# que `examples` : un validateur strict l'ignore comme une annotation
# inconnue, rien ne casse. C'est le prix du pré-remplissage sans menu.
#
# La glose de la valeur va donc dans la `description` du paramètre, où
# elle se lit à côté du champ, et non dans le libellé d'un menu.
#
# Les paramètres optionnels qui changent le CALCUL ne sont pas
# pré-remplis (`sampling` : le pré-remplir ferait exécuter un protocole
# à qui n'en a pas demandé). Leur description dit les valeurs acceptées.
_X_STATIONS = {"example": "F700000103"}
_X_CARDS = {"example": "QA,VCN10"}
_X_START = {"example": "1968-01-01"}
_X_JOB_ID = {"example": "3f2a9c1b7e4d8506"}

# L'ordre des sections EST celui de la page : Swagger les affiche dans
# l'ordre de cette liste, pas dans l'ordre alphabétique ni dans celui des
# routes. Il suit donc le parcours réel d'une première demande : ce
# qu'est le service, quelles variables existent, sur quelle station, puis
# le calcul, et la file d'attente pour ce qui est trop gros. `stations`
# passe ainsi AVANT `data` : on choisit une station avant d'extraire, et
# c'est le code trouvé là qui remplit le champ `stations` d'`extract`.
# Une clé se demande par COURRIEL, et le lien porte le canevas de la
# demande. Le passage par une issue GitHub a été retiré le 2026-07-29 :
# il était inutilisable, pour trois raisons qui se cumulaient. Les issues
# d'un dépôt public sont publiques et le réglage n'existe pas, donc le
# jeton ne pouvait pas repartir par là sans être divulgué ; le formulaire
# ne demandait aucune adresse, donc il n'y avait AUCUN canal de réponse ;
# et il fallait un compte GitHub, barrière rédhibitoire pour un public
# d'agences et de bureaux d'études.
#
# `quote` sur chaque partie : un objet accentué ou un retour à la ligne
# non échappé casse le lien sur la moitié des clients de messagerie.
_MAILTO_CLE = "mailto:louis.heraut@inrae.fr?" + urllib.parse.urlencode({
    "subject": "card-api : demande de clé de priorité",
    "body": (
        "Bonjour,\n\n"
        "Je souhaite une clé de priorité pour card-api.\n\n"
        "Qui je suis (nom, organisme) :\n\n"
        "Usage prévu (combien de stations, quelles variables, à quelle "
        "fréquence) :\n\n"
        "Contexte, projet ou financement associé (facultatif) :\n\n"
        "Merci."
    ),
}, quote_via=urllib.parse.quote)


_TAGS = [
    {"name": "service", "description": "Identité, versions et santé du service."},
    {"name": "cards", "description": "Catalogue et détail des fiches CARD."},
    {"name": "stations", "description": "Référentiel des stations hydrométriques."},
    {"name": "data", "description": "Extraction et tendance sur les débits Hub'Eau."},
    {"name": "jobs", "description": "File de calcul asynchrone (grosses demandes)."},
]

# Adresse publique, déclarée dans le contrat quand elle est connue. Sans
# elle, pas de bloc `servers` : un client déduit alors l'adresse de
# l'endroit d'où il a chargé `openapi.json`, ce qui est exactement ce
# qu'il faut en développement. Une URL de production écrite en dur dans
# le code enverrait le « Try it out » d'une instance locale sur la VRAIE
# production, et c'est le genre de bêtise qu'on ne remarque qu'après.
# Le schéma fait partie de la variable : il ne se déduit pas de `DOMAIN`,
# qui peut être une IP nue (donc HTTP, aucun certificat possible).
_PUBLIC_URL = os.environ.get("CARD_API_PUBLIC_URL", "").rstrip("/")
_SERVERS = ([{"url": _PUBLIC_URL, "description": "production"}]
            if _PUBLIC_URL else None)

app = FastAPI(
    title="card-api",
    version=API_VERSION,
    servers=_SERVERS,
    # Ce que porte l'en-tête de /docs, et dans quel ordre Swagger le
    # rend : titre, `summary`, `description`, `termsOfService`, puis
    # contact et licence.
    #
    # La règle est la même pour tous ces champs : le CONTRAT les porte
    # tous, la PAGE n'en montre que ce qui aide à lire. Ce qui se règle
    # dans openapi.json ne coûte rien à personne et sert une machine ;
    # ce qui s'affiche coûte une ligne à chaque visiteur.
    #
    # `summary` (une phrase, OpenAPI 3.1) en est l'exemple : un moteur de
    # recherche d'API ou un catalogue l'affiche seul, sans la
    # description, donc il doit exister. Mais Swagger le rend JUSTE
    # au-dessus de la description, où il en redit la première phrase :
    # son affichage est masqué par le calque (section 3).
    #
    # La DESCRIPTION reste de la prose : ce que fait le service, pour qui,
    # par où commencer. UN paragraphe, pas trois. Pas de lien au fil des
    # phrases, ils cassent la lecture et on ne sait plus si on lit un
    # texte ou un sommaire. Rien non plus sur la mécanique interne
    # (provenance, SWHID, droits) : ces champs voyagent dans chaque
    # réponse, où ils servent, et le README les explique. Un en-tête
    # n'est pas un résumé du projet, c'est ce qu'il faut savoir avant de
    # cliquer sur une opération.
    #
    # Dessous, QUATRE lignes, dans l'ordre de ce qu'on veut qu'un
    # visiteur retienne : d'abord que la bibliothèque Python existe et
    # qu'elle est le bon outil pour un gros volume (le service est une
    # porte d'entrée, pas un moteur de calcul de masse), puis à qui
    # écrire, puis où aller lire, puis sous quels droits. Elles absorbent
    # la licence et le contact, que Swagger
    # sait pourtant rendre lui-même (`license_info`, `contact`) mais
    # chacun dans sa présentation : trois façons de poser un lien dans
    # quinze centimètres de page. Les deux champs RESTENT déclarés plus
    # bas, parce qu'un contrat doit dire sa licence à une machine ; c'est
    # leur AFFICHAGE que le calque masque (theme-identity.css, section 3).
    summary=("Variables hydroclimatiques (fiches CARD) sur les débits "
             "Hub'Eau, avec diagnostic de tendance."),
    description=(
        "Variables hydroclimatiques prêtes à l'emploi, calculées sur les "
        "débits Hub'Eau, avec diagnostic de tendance. Façade du projet "
        "CARD : les fiches définissent les variables, le moteur stase "
        "les calcule, Hub'Eau fournit les observations. Service public "
        "de recherche (INRAE, UR RiverLy), accès ouvert, sans "
        "inscription ni clé. Point d'entrée : `GET /v1`.\n\n"
        "Gros volume, vos propres données, ou un calcul à refaire chez "
        "vous : la bibliothèque Python fait le même calcul "
        "en local, sans quota et sans réseau : [card](https://github.com/lou-heraut/card).\n\n"
        "**Service** : "
        "[dépôt du code](https://github.com/lou-heraut/card-api) · "
        "[mentions légales]"
        "(https://github.com/lou-heraut/card-api#mentions-légales) <br>"
        "**Ressources externes** : "
        "[Hub'Eau](https://hubeau.eaufrance.fr/)<br>"
        "**Codes** : "
        "[GPL-3.0-or-later]"
        "(https://www.gnu.org/licenses/gpl-3.0.html)<br>"
        "**Données** : [Licence Ouverte / Etalab 2.0]"
        "(https://www.etalab.gouv.fr/licence-ouverte-open-licence/)\n\n"
        "[signaler un bug]"
        "(https://github.com/lou-heraut/card-api/issues) · "
        f"[demander une clé de priorité]({_MAILTO_CLE}) · "
        "[écrire à l'auteur](mailto:louis.heraut@inrae.fr)"
    ),
    # Déclarés pour la MACHINE, masqués à l'écran (cf. plus haut). Retirer
    # `license_info` du contrat pour gagner une ligne d'affichage ferait
    # perdre à un moissonneur le seul endroit où il lit sous quels droits
    # réutiliser : le prix est sans commune mesure avec le gain.
    #
    # `terms_of_service` est le champ prévu pour les conditions d'usage.
    # Il pointe les MENTIONS LÉGALES : éditeur, hébergeur, droits, et le
    # volet données personnelles, qui existe parce que le service
    # journalise un dérivé de l'adresse IP. Champ masqué à l'écran comme
    # les autres, mais présent dans openapi.json, donc opposable et
    # lisible par une machine ; la description porte le lien visible.
    terms_of_service=("https://github.com/lou-heraut/card-api"
                      "#mentions-légales"),
    contact={"name": "Louis Héraut (INRAE, UR RiverLy)",
             "url": "https://github.com/lou-heraut/card-api"},
    license_info={"name": "GPL-3.0-or-later",
                  "url": "https://www.gnu.org/licenses/gpl-3.0.html"},
    openapi_tags=_TAGS,
    # La clé de priorité EXISTE dans le service depuis le début, mais
    # n'existait nulle part dans le contrat : `usage.priority_of` lit
    # l'en-tête à la main, sans que rien ne le déclare. Deux conséquences,
    # toutes deux invisibles depuis le code : un client ne pouvait pas
    # savoir que le service accepte une clé, et un porteur de clé n'avait
    # AUCUN moyen de la présenter depuis /docs, donc `GET /v1/jobs` y
    # rendait 401 sans recours. La déclarer ajoute le bouton « Authorize »
    # et met la clé dans toutes les requêtes de la page.
    #
    # `auto_error=False` est ce qui garde le service public : sans clé, la
    # dépendance rend None et laisse passer. Rien ne change côté serveur,
    # `priority_of` continue de lire l'en-tête lui-même.
    dependencies=[Security(APIKeyHeader(
        name="X-API-Key", auto_error=False, scheme_name="Clé de priorité",
        description="Facultative. Sans elle, l'accès est public et "
                    "soumis aux quotas par IP. Avec elle, les quotas "
                    "sont levés, les plafonds relevés, les jobs passent "
                    "en tête de file et `GET /v1/jobs` liste les vôtres. "
                    "Elle se demande par une issue du dépôt, elle ne "
                    "s'achète pas. Coller le jeton tel quel, sans "
                    "préfixe."))],
    # Réglages d'AFFICHAGE de Swagger. Ils ne touchent pas au contrat :
    # `openapi.json` reste complet, c'est la page qui décide de ce
    # qu'elle montre d'emblée.
    swagger_ui_parameters={
        # Champs éditables sans cliquer « Try it out » d'abord.
        "tryItOutEnabled": True,
        # Le pavé « Schemas » en bas de page noyait tout le reste.
        "defaultModelsExpandDepth": -1,
        # Sections ouvertes, opérations repliées : on voit d'un coup
        # d'oeil TOUTES les actions possibles et ce que chacune fait
        # (leur `summary` s'affiche dans la barre), sans dérouler.
        "docExpansion": "list",
        # `pattern`, `maxLength`, `minimum`... sur chaque paramètre :
        # c'est FastAPI qui les allume par défaut, pas Swagger. Détail
        # de machine, et il est de toute façon dans openapi.json.
        "showCommonExtensions": False,
        "showExtensions": False,
        # Durée de la requête à côté du code de statut. Sur une API où
        # une extraction prend quelques secondes et une tendance
        # davantage, c'est l'information qui dit s'il faut passer par un
        # job : elle se lit, au lieu de se deviner.
        "displayRequestDuration": True,
    },
    docs_url=None,          # servi plus bas, avec le thème
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


# ── /docs : Swagger UI habillé ───────────────────────────────────────
# Le thème est un CALQUE posé après le CSS de Swagger, pas un
# remplacement : Swagger reste maître de sa mise en page, on ne
# retouche que ce qui se voit. Il est produit par
# `scripts/build_theme.py`, qui relit le CSS réel de Swagger et
# re-déclare chacune de ses règles de couleur ; écrire ces règles à la
# main revient à en oublier, et un thème à moitié appliqué est pire
# qu'un thème absent (leçon du 2026-07-23, cf. docs/dev/THEME_DOCS.md).
# DEUX feuilles, servies dans cet ordre, et c'est délibéré :
#
#   swagger-colors.css   GÉNÉRÉ par scripts/build_theme.py. Ne contient
#                        que des couleurs transposées. Ne bouge qu'à une
#                        montée de version de Swagger.
#   theme-identity.css   ÉCRIT À LA MAIN. Gamme, typographie, densité,
#                        forme. C'est le fichier qu'on retouche.
#
# Les coller en un seul fichier obligerait à relancer le générateur pour
# la moindre virgule de style. Séparés, retoucher l'apparence se résume
# à éditer theme-identity.css et à recharger la page.
_STATIC = pathlib.Path(__file__).with_name("static")
_CSS_LAYERS = ("swagger-colors.css", "theme-identity.css")


def _css_tag(path) -> str:
    """Empreinte courte d'une feuille, à coller dans l'URL du `<link>`.

    Sans elle, le navigateur garde sa copie une heure durant (le
    `Cache-Control` plus bas) : on retouche le CSS et l'écran ne bouge
    pas, ce qui fait croire que la règle est mauvaise alors qu'elle
    n'est simplement pas arrivée. Avec elle, l'URL change dès que le
    fichier change : on garde le cache sans garder le périmé.

    Vaut aussi en production, où un `make update` prend effet tout de
    suite au lieu d'attendre l'expiration chez chaque visiteur.
    """
    st = path.stat()
    return hashlib.sha256(
        f"{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:12]


@app.get("/static/{sheet}.css", include_in_schema=False)
def theme_css(sheet: str) -> _RawResponse:
    name = f"{sheet}.css"
    if name not in _CSS_LAYERS:            # pas de traversée de chemin
        raise HTTPException(404, f"feuille inconnue : {name}")
    return _RawResponse((_STATIC / name).read_bytes(), media_type="text/css",
                        headers={"Cache-Control": "public, max-age=3600"})


# Logo INRAE, appelé par le calque d'identité en image de fond (donc pas
# de balise injectée dans le HTML de Swagger : cf. la règle du thème,
# rien qui ne soit une règle CSS ou une chaîne de caractères). Route
# nommée en dur plutôt que paramétrée : un seul fichier, pas de chemin à
# valider.
@app.get("/static/inrae.svg", include_in_schema=False)
def theme_logo() -> _RawResponse:
    return _RawResponse((_STATIC / "inrae.svg").read_bytes(),
                        media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=3600"})


# Favicon : un SVG d'une ligne portant l'émoji, en URL `data:`. Aucun
# fichier à servir, aucun appel réseau, et l'onglet cesse d'afficher
# celui de FastAPI, qui n'est pas le nôtre. `quote` est indispensable :
# une URL `data:` non échappée casse sur le `#` d'une couleur comme sur
# certains caractères non ASCII.
_FAVICON = "data:image/svg+xml," + urllib.parse.quote(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<text y='26' font-size='28'>\N{FLOWER PLAYING CARDS}</text></svg>")


@app.get("/docs", include_in_schema=False)
def swagger_docs(request: Request) -> HTMLResponse:
    page = get_swagger_ui_html(
        openapi_url=str(request.scope.get("root_path", "")) + app.openapi_url,
        # Le <title> est ce que le navigateur met dans l'onglet et
        # dans un signet : le nom du service suffit, la page se voit
        # bien assez pour ne pas avoir à s'annoncer.
        title=app.title,
        swagger_favicon_url=_FAVICON,
        swagger_ui_parameters=app.swagger_ui_parameters,
    ).body.decode()
    links = "\n".join(
        f'<link rel="stylesheet" href="static/{n}?v={_css_tag(_STATIC / n)}">'
        for n in _CSS_LAYERS)
    return HTMLResponse(page.replace("</head>", links + "\n</head>", 1))

# API publique en lecture : un client navigateur (site web tiers) doit
# pouvoir l'appeler. Origines ouvertes, sans cookies d'identité.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["*"],
)




def _endpoints():
    """La liste des endpoints de /v1, DÉRIVÉE des routes déclarées.

    Elle était recopiée à la main, et elle avait menti : trois endpoints
    ajoutés le 2026-07-28 (`extract.csv`, `trend.csv`, `trend/figure`)
    n'y figuraient pas, si bien que la porte d'entrée du service en
    cachait une partie. Même leçon que `versions()` : un point de sortie
    recopié à la main finit toujours par mentir, le seul remède est de ne
    pas le recopier.

    La clé est le nom de la fonction qui sert la route : il est déjà
    parlant (`card_figure`, `trend_csv`) et il ne peut pas diverger du
    chemin puisque les deux viennent du même objet.
    """
    routes = {}
    for r in app.routes:
        chemin = getattr(r, "path", "")
        if chemin.startswith("/v1") and "GET" in getattr(r, "methods", ()):
            routes[r.name] = chemin
    for r in app.routes:                       # le POST de dépôt de job
        if getattr(r, "path", "") == "/v1/jobs" and \
                "POST" in getattr(r, "methods", ()):
            routes["job_submit"] = "/v1/jobs"
    # Hors /v1 : le contrat et sa page. Ils n'ont pas de version parce
    # qu'ils décrivent TOUTES les versions.
    routes["openapi"] = str(app.openapi_url)
    routes["docs"] = "/docs"
    return routes


# ── La racine : un panneau indicateur, pas une page d'accueil ─────────
#
# `/` rendait 404, ce qui est correct mais désobligeant : quelqu'un qui
# tape le nom de domaine dans une barre d'adresse n'a rien fait de mal.
#
# La forme est celle de la « landing page » d'OGC API (Common, et donc
# Processes, dont la file de calcul suit déjà le dessin) : un titre, une
# phrase, et un tableau `links` où chaque entrée porte sa RELATION.
# `service-desc` désigne le contrat lisible par une machine,
# `service-doc` la page lisible par un humain, `latest-version` la
# version courante de l'API. Un client générique sait suivre ces
# relations sans rien connaître de card-api ; c'est tout l'intérêt, et
# c'est ce qu'une redirection vers /docs ne donnerait pas.
#
# Ce qui n'est PAS ici : le détail du service, qui vit dans /v1 et n'a
# pas à être maintenu à deux endroits. La racine ne fait que renvoyer.
@app.get("/", tags=["service"], summary="Racine : où aller ensuite")
def landing(request: Request):
    """Panneau indicateur : où trouver le contrat, la documentation et la
    version courante de l'API. Le détail du service est sous `/v1`."""
    base = str(request.scope.get("root_path", ""))
    return {
        "title": "card-api",
        "description": ("Variables hydroclimatiques (fiches CARD) sur les "
                        "débits Hub'Eau, avec diagnostic de tendance."),
        "links": [
            {"rel": "self", "type": "application/json",
             "href": f"{base}/", "title": "cette page"},
            {"rel": "service-desc",
             "type": "application/vnd.oai.openapi+json;version=3.1",
             "href": f"{base}/openapi.json", "title": "contrat OpenAPI"},
            {"rel": "service-doc", "type": "text/html",
             "href": f"{base}/docs",
             "title": "documentation interactive"},
            {"rel": "latest-version", "type": "application/json",
             "href": f"{base}/v1",
             "title": "point d'entrée de la version courante"},
        ],
    }


@app.get("/v1", tags=["service"],
         summary="Point d'entrée : ce que fait le service")
def root():
    """Point d'entrée : ce qu'est le service, ce qu'il relie, où le réutiliser."""
    return {
        **versions(),
        "service": "card-api",
        "summary": "Variables hydroclimatiques (fiches CARD) sur les débits "
                   "Hub'Eau, avec diagnostic de tendance.",
        "ecosystem": {
            "card": {"role": "définit les variables (fiches YAML)",
                     "url": "https://github.com/lou-heraut/card"},
            "stase": {"role": "moteur de calcul et de stationnarité",
                      "url": "https://github.com/lou-heraut/stase"},
            "hubeau": {"role": "fournit les débits observés",
                       "url": "https://hubeau.eaufrance.fr/"},
        },
        "endpoints": _endpoints(),
        "reuse": "API pour l'usage ponctuel ; la bibliothèque Python card "
                 "pour le gros volume et l'intégration ; citer une fiche par "
                 "son swhid (présent dans les métadonnées) pour reproduire.",
        "rights": rights(),
    }


@app.get("/v1/cards", tags=["cards"],
         summary="Catalogue, filtrable par facette",
         dependencies=[Depends(usage.rate_light)])
def cards(
    domain: _Domain | None = Query(
        None, description=_facet_doc("domain", "Grandeur mesurée.")),
    phenomenon: _Phenomenon | None = Query(
        None, description=_facet_doc("phenomenon", "Phénomène décrit.")),
    aspect: _Aspect | None = Query(
        None, description=_facet_doc("aspect", "Dimension IHA.")),
    season: _Season | None = Query(
        None, description=_facet_doc("season", "Fenêtre d'échantillonnage.")),
    output: _Output | None = Query(
        None, description=_facet_doc("output", "Forme du résultat.")),
    purpose: _Purpose | None = Query(
        None, description=_facet_doc("purpose", "Finalité particulière.")),
    operator: str | None = Query(
        None,
        description="Opérateur inter-annuel, lu sur le préfixe de l'id. "
                    "Valeurs rencontrées : mean, median, delta, "
                    "trend slope, trend test, count."),
    function: str | None = Query(
        None,
        description="Sous-chaîne d'un nom de fonction employée dans le "
                    "calcul : rollmean, baseflow, return_level, delta, "
                    "apply_threshold..."),
    variable: str | None = Query(
        None,
        description="Sous-chaîne du nom de variable produit : VCN attrape "
                    "toute la famille des étiages, QA le module annuel."),
    search: str | None = Query(
        None,
        description="Recherche libre dans le nom, la description et la "
                    "variable, en français comme en anglais, insensible à "
                    "la casse. Un fragment suffit : « basses », "
                    "« minimum », « maximal »."),
    limit: int = Query(default=1000, le=1000,
                       description="Nombre maximal de lignes rendues."),
):
    """Catalogue des fiches, une ligne par variable produite.

    Les six premiers filtres sont les facettes de classification : ce
    sont des listes fermées, proposées en menu, et `/v1/vocabulary` les
    rend aussi sous forme de données. Les quatre suivants sont du texte
    libre. Tous se combinent, et ce sont ceux de `card.list_cards()`.
    """
    df = card.list_cards(domain=domain, phenomenon=phenomenon,
                         aspect=aspect, season=season, output=output,
                         purpose=purpose, operator=operator,
                         function=function, variable=variable,
                         search=search)
    rows = clean(df.head(limit).to_dict(orient="records"))
    # L'identifiant d'une fiche est le NOM DE SON FICHIER, pas sa
    # variable. Les deux coïncident pour une minorité de fiches et
    # diffèrent pour la majorité : `ETPMA_month.yaml` produit `ETPMA_jan` à
    # `ETPMA_dec`, et c'est `ETPMA_month` qu'attendent /v1/cards/{id},
    # /v1/extract et /v1/trend. Cette colonne était annoncée partout
    # (« colonne `id` de /v1/cards ») sans jamais être rendue : on
    # cherchait un identifiant absent, et celui qu'on devinait donnait un
    # 404 une fois sur deux.
    for r in rows:
        r["id"] = pathlib.Path(r["script_path"]).stem
    return {
        **versions(),
        "count": int(len(df)),
        # Les identifiants ci-dessus, prêts à coller dans le paramètre
        # `cards` d'/v1/extract ou /v1/trend. Sans lui, filtrer par
        # facette puis recopier quinze identifiants à la main était le
        # seul chemin, et personne ne le fait sans se tromper. Dédoublonné
        # en gardant l'ordre : douze variables d'une même fiche ne font
        # qu'un identifiant.
        "ids": ",".join(dict.fromkeys(r["id"] for r in rows)),
        "cards": rows,
    }


@app.get("/v1/cards/{card_id}", tags=["cards"],
         summary="Détail d'une fiche, en JSON",
         dependencies=[Depends(usage.rate_light)])
def card_detail(
    card_id: str = PathParam(
        json_schema_extra={"example": "VCN10"},
        description="Identifiant de la fiche, tel que rendu par "
                    "/v1/cards (colonne `id`). Exemple : `VCN10`, "
                    "l'étiage."),
    lang: Literal["fr", "en"] = Query(
        "fr", description="Langue des libellés et des descriptions."),
):
    """Détail d'une fiche : métadonnées complètes et classification.

    Deux liens vers la définition employée : `yaml` pointe le fichier sur
    GitHub à la révision réellement exécutée, `archive` le même contenu
    dans Software Heritage, qui restera lisible même si le dépôt bouge.
    """
    try:
        # quiet : le service n'a pas de terminal ; sans lui, la figure
        # partirait dans les logs à chaque requête, calculée pour rien.
        # Elle est servie telle quelle par /v1/cards/{id}/figure.
        meta = card.info(card_id, lang=lang, quiet=True)
    except FileNotFoundError as e:
        # Deux causes distinctes derrière la même exception : fiche absente
        # du corpus (levée nue par card, sans filename) ou fichier de
        # données du package illisible (OSError, filename renseigné).
        # Les confondre annonce « fiche inconnue » sur un bug serveur.
        if e.filename:
            raise                                # 500 + trace dans les logs
        raise HTTPException(404, f"fiche inconnue : {card_id}")
    # Deux liens vers la définition, complémentaires. GitHub pointe la
    # révision RÉELLEMENT exécutée, pas `main` : une fiche consultée
    # aujourd'hui correspond ainsi au calcul d'aujourd'hui. Software
    # Heritage pointe le contenu exact, qui restera lisible même si le
    # dépôt disparaît.
    rel = meta.pop("path", "")
    if rel:
        ref = CARD_COMMIT or "main"
        meta["yaml"] = ("https://github.com/lou-heraut/card/blob/"
                        f"{ref}/src/card/cards/{rel}")
    if meta.get("swhid"):
        meta["archive"] = f"https://archive.softwareheritage.org/{meta['swhid']}"
    return {**versions(), "lang": lang, "card": meta}


@app.get("/v1/cards/{card_id}/figure", tags=["cards"],
         summary="La fiche dessinée, en texte",
         response_class=PlainTextResponse,
         dependencies=[Depends(usage.rate_light)])
def card_figure(
    card_id: str = PathParam(
        json_schema_extra={"example": "QA"},
        description="Identifiant de la fiche, tel que rendu par "
                    "/v1/cards (colonne `id`). Exemple : `QA`, le "
                    "module annuel."),
    lang: Literal["fr", "en"] = Query(
        "fr", description="Langue des libellés et des descriptions."),
):
    """La fiche **dessinée** : chaîne de calcul, fonctions et réglages,
    fenêtre d'échantillonnage sur douze mois, ce qui est produit.

    Même fiche que `/v1/cards/{id}`, autre représentation : celui-ci reste
    du JSON pour les machines, celui-là est du texte pour comprendre d'un
    coup d'oeil ce que la fiche calcule, sans lire son YAML.
    """
    try:
        return card.figure(card_id, lang=lang)
    except FileNotFoundError as e:
        if e.filename:                       # bug serveur, pas fiche absente
            raise
        raise HTTPException(404, f"fiche inconnue : {card_id}")


@app.get("/v1/vocabulary", tags=["cards"],
         summary="Valeurs valides des facettes",
         dependencies=[Depends(usage.rate_light)])
def vocabulary():
    """Valeurs valides des facettes de classification, en français et en
    anglais.

    Ce sont exactement les filtres acceptés par `/v1/cards` : de quoi
    construire une requête juste, ou peupler un menu, sans les deviner.
    """
    return {**versions(), "vocabulary": card.vocabulary()}


@app.get("/v1/stations", tags=["stations"],
         summary="Chercher une station par son nom",
         dependencies=[Depends(usage.rate_light)])
def stations(
    libelle: str | None = Query(
        None, json_schema_extra={"example": "Austerlitz"},
        description="Fragment du nom de la station ou de son cours "
                    "d'eau. Exemple : `Austerlitz`, la Seine à Paris."),
    code: str | None = Query(
        None,
        description="Code station Hub'Eau, si vous le connaissez déjà "
                    "(ex. F700000103). Se combine en ET avec les autres "
                    "critères."),
    departement: str | None = Query(
        None,
        description="Numéro de département, sur deux caractères (ex. 07). "
                    "Se combine en ET avec les autres critères."),
    size: int = Query(20, le=100,
                      description="Nombre maximal de stations rendues."),
):
    """Recherche de stations hydrométriques (référentiel Hub'Eau).
    Utile aussi pour retrouver les nouveaux codes : depuis la refonte
    Hydro, les anciens codes Banque Hydro ne sont plus valides."""
    if not any((libelle, code, departement)):
        raise HTTPException(422, "donner au moins libelle, code ou departement")
    try:
        trouvees = hubeau.search_stations(libelle, code, departement, size)
        # Même service que `ids` dans /v1/cards : les codes trouvés, prêts
        # à coller dans le paramètre `stations` d'/v1/extract ou
        # /v1/trend. Une recherche par département en rend vingt ; les
        # recopier un par un est le genre de corvée qui décide de
        # l'abandon.
        return {"codes": ",".join(s["code_station"] for s in trouvees
                                  if s.get("code_station")),
                "stations": trouvees}
    except httpx.HTTPError as e:
        raise HTTPException(
            504, f"Hub'Eau ne répond pas ({type(e).__name__}) : "
                 "réessayez dans quelques minutes",
            headers={"Retry-After": "300"})


def _split(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in value.split(",") if s.strip()]


def _check_cards_q(cd):
    meta_map = _card_meta_map()
    for c in cd:
        m = meta_map.get(c)
        if m is not None and m["input_vars"] != "Q":
            raise HTTPException(
                422, f"la fiche {c} requiert {m['input_vars']} : ce service "
                     "ne fournit que des débits journaliers (Q, Hub'Eau)")


def _check_cards_series(cd):
    meta_map = _card_meta_map()
    for c in cd:
        m = meta_map.get(c)
        if m is not None and m["output"] != "series":
            raise HTTPException(
                422, f"la fiche {c} produit un résultat '{m['output']}' : "
                     "la tendance ne s'applique qu'aux fiches 'series'")


def _parse_lists(stations, cards, prio=None):
    st, cd = _split(stations), _split(cards)
    if not st or not cd:
        raise HTTPException(422, "stations et cards sont requis")
    max_st = jobs.PRIORITY_STATIONS if prio else jobs.JOB_STATIONS
    max_cd = jobs.PRIORITY_CARDS if prio else jobs.JOB_CARDS
    # 0 = sans limite (cf. jobs.py) : un plafond de clé peut vouloir dire
    # « toutes », et l'écrire en nombre le ferait périmer avec le corpus.
    depasse = (max_st > 0 and len(st) > max_st) or \
              (max_cd > 0 and len(cd) > max_cd)
    if depasse:
        hint = ("" if prio else
                " ; besoin plus large : demandez une clé de priorité")
        dit_st = max_st if max_st > 0 else "sans limite"
        dit_cd = max_cd if max_cd > 0 else "sans limite"
        raise HTTPException(
            422, f"au plus {dit_st} stations et {dit_cd} fiches par "
                 f"demande (au-delà de {jobs.SYNC_STATIONS} stations ou "
                 f"{jobs.SYNC_CARDS} fiches, la demande devient un "
                 f"job){hint}")
    _check_cards_q(cd)
    return st, cd


def _job_envelope(job: dict) -> dict:
    """Le ticket en DONNÉES, pas en réponse. Une demande peut basculer en
    file depuis n'importe quelle représentation : le CSV et la figure ont
    eux aussi à annoncer le ticket, chacun dans son medium. Rendre ici un
    objet Response les priverait du numéro."""
    return {
        "job": job["id"],
        "status": job["status"],
        "status_url": f"/v1/jobs/{job['id']}",
        "result_url": f"/v1/jobs/{job['id']}/result",
        "detail": "demande mise en file : suivre status_url, le "
                  "résultat reste disponible "
                  f"{jobs.JOB_TTL_DAYS:g} jours",
    }


def _job_response(envelope: dict) -> JSONResponse:
    """Le ticket en JSON : 202 + Location, forme d'OGC API Processes."""
    return JSONResponse(
        status_code=202,
        headers={"Location": envelope["status_url"]},
        content=envelope)


def _maybe_job(request, endpoint, st, cd, prio=None, **params):
    """Bascule automatique : au-dessus des plafonds synchrones, la
    demande devient un job (202 + ticket) au lieu d'un refus. Une clé
    de priorité met le job en tête de file."""
    if len(st) <= jobs.SYNC_STATIONS and len(cd) <= jobs.SYNC_CARDS:
        return None
    job_params = {"endpoint": endpoint, "stations": st, "cards": cd,
                  **{k: v for k, v in params.items() if v is not None}}
    try:
        job = jobs.submit(job_params,
                          user=usage.ip_hash(usage.client_ip(request)),
                          priority=-1 if prio else 0,
                          key=prio["prefix"] if prio else None)
    except RuntimeError as e:
        raise HTTPException(503, str(e), headers={"Retry-After": "300"})
    extra = {"key": prio["prefix"]} if prio else {}
    usage.log_usage(request, "jobs", job=job["id"], target=endpoint,
                    stations=len(st), cards=cd, **extra)
    return _job_envelope(job)


def _stations_meta(st):
    """Fiches du référentiel Hub'Eau des stations demandées, jointes
    à la réponse sous 'stations_meta' : un résultat autoportant (une
    carte ne demande aucun fichier local ni second appel)."""
    try:
        return hubeau.stations_referential(st)
    except httpx.HTTPError as e:
        raise HTTPException(
            504, f"Hub'Eau ne répond pas ({type(e).__name__}) : "
                 "réessayez dans quelques minutes",
            headers={"Retry-After": "300"})


# ── CSV : le tableur, sans perdre la provenance ────────────────────────
#
# Un CSV ne sait pas porter de bloc `versions`, de SWHID, d'empreinte ni
# de droits. Livré nu, il devient en trois copies un tableau de chiffres
# dont plus personne ne sait d'où il vient, c'est-à-dire exactement ce
# que ce service existe pour éviter. Hub'Eau ne résout pas ce point : son
# CSV n'a qu'une ligne d'en-tête.
#
# La provenance part donc en LIGNES DE COMMENTAIRE `#` en tête de
# fichier. `pandas.read_csv(comment="#")` et `read.csv(comment.char="#")`
# les sautent d'eux-mêmes, et elles survivent à l'enregistrement du
# fichier, contrairement à un en-tête HTTP.
def _dit_sampling(sampling):
    """Le réglage d'échantillonnage, en clair dans un bandeau de CSV.

    Ce réglage décide du JOUR OÙ COMMENCE L'ANNÉE de calcul. La phrase
    doit dire qui varie : « fenêtre propre à chaque fiche » laissait
    croire à une valeur unique par fiche, alors qu'une bonne part du
    corpus calcule ce départ sur la donnée, donc à une date différente
    par couple station-variable.
    """
    if sampling == "preferred":
        return ("départ fixe déclaré par chaque fiche (protocole MAKAHO)")
    if sampling:
        return f"année démarrant le {sampling} pour toutes les fiches"
    return ("départ déclaré par chaque fiche, calculé sur la donnée "
            "pour celles dont la fenêtre est adaptative "
            "(une date par couple station-variable)")


def _csv_sans_virgule(ligne):
    """AUCUNE virgule dans une ligne de provenance.

    Un tableur n'a pas de notion de commentaire : il affiche les lignes
    `#` comme des lignes de données et les DÉCOUPE sur les virgules. Le
    bandeau se retrouvait éparpillé sur huit colonnes, illisible, alors
    qu'il n'a de valeur que lu d'un trait.

    Entourer la ligne de guillemets la garderait en une cellule, mais
    elle ne commencerait plus par `#` : `read_csv(comment="#")` et
    `read.csv(comment.char="#")` cesseraient de la sauter et
    tenteraient de la lire comme une donnée. Le remède serait pire.

    Reste à ne pas produire de virgule du tout. Le bandeau se lit alors
    d'un trait en colonne A dans un tableur, et reste sauté par pandas
    et R.

    Le remplaçant est le POINT-VIRGULE, pas le point médian. Ce dernier
    convient à une énumération de codes, pas à une phrase : le motif d'une
    station écartée donnait « n'en publie pas · cas d'une échelle · que ni
    type_station », qui ne se lit plus. Les listes, elles, sont déjà
    jointes par ` · ` à la construction et ne passent pas par ici.
    """
    return ligne.replace(", ", " ; ").replace(",", " ; ")


def _csv_entete(out, endpoint):
    """Les lignes `#` de provenance, avant la ligne de colonnes."""
    lignes = [
        f"card-api · {endpoint}",
        f"card {out.get('card_version')}"
        + (f" ({out['card_swhid']})" if out.get("card_swhid") else "")
        + f" · stase {out.get('stase_version')}"
        + (f" ({out['stase_swhid']})" if out.get("stase_swhid") else "")
        + f" · api {out.get('api_version')}",
        f"stations : {' · '.join(out['stations'])}",
        f"fiches : {' · '.join(out['cards'])}",
        f"période demandée : {out['period']['start'] or 'depuis le début'}"
        f" → {out['period']['end'] or 'jusqu’à la fin'}",
        f"échantillonnage : {_dit_sampling(out['sampling'])}",
        f"source : {out['source']}",
        f"données lues le {out['data_fetched_at']}"
        f" · empreinte {out['data_fingerprint']}",
        f"droits : {out['rights']['data']['license']} (données)"
        f" · {out['rights']['definitions']['license']} (définitions)",
        f"citer : {out['rights']['cite']}",
    ]
    if out.get("mk"):
        lignes.insert(4, f"test : Mann-Kendall {out['mk']} · "
                         f"seuil {out['level']}")
    # Les stations écartées, DANS le fichier. Un tableur ne verra jamais
    # le JSON : sans ces lignes, un CSV de dix-neuf stations pour une
    # demande de vingt se lit comme complet, et l'absence passe pour un
    # fait. C'est la leçon du ticket de job, qui ne sortait qu'en JSON.
    for o in out.get("stations_omitted") or []:
        lignes.append(f"station écartée : {o['code_station']} "
                      f"({o['reason']}) {o['detail']}")
    return "".join(f"# {_csv_sans_virgule(ligne)}\n" for ligne in lignes)


def _abrege(valeurs, mot, maxi=3):
    """Une liste dans un nom de fichier : en clair si elle est courte,
    comptée sinon. Sans ce garde-fou, douze stations donneraient un nom
    de 150 caractères que personne ne lit et que certains systèmes de
    fichiers refusent."""
    valeurs = list(dict.fromkeys(valeurs))
    if len(valeurs) <= maxi:
        return "-".join(valeurs)
    return f"{len(valeurs)}{mot}"


def _annees(table):
    """Les années réellement couvertes par le tableau rendu.

    Prises sur la DONNÉE et non sur les bornes demandées : une demande
    « depuis 1970 » sur une station ouverte en 2005 donnerait un nom de
    fichier qui ment sur son contenu."""
    for col in ("date", "period_start"):
        if col in table.columns and len(table):
            dates = table[col].astype(str)
            fin = table["period_end"] if "period_end" in table else dates
            return f"{dates.min()[:4]}-{str(fin.max())[:4]}"
    return "sans-date"


def _csv_nom(table, out, endpoint):
    """Nom de fichier : du plus général au plus particulier, pour que
    deux analyses voisines se rangent côte à côte dans un dossier.

        card-api_trend_F700000103_QA-VCN10_AR1_2005-2026_ac9c7eed.csv
        └ producteur                            └ période  └ empreinte

    Les champs sont séparés par `_`, les valeurs d'un même champ par `-`.
    Un identifiant de fiche peut contenir `_` (QMNA_summer) : ce nom se
    lit, il ne se parse pas. Ce qui se parse est l'en-tête `#`.

    L'empreinte des données termine le nom : deux fichiers de même nom
    ont la même source, et deux extractions du même jour séparées par une
    révision Hub'Eau ne s'écrasent pas l'une l'autre. Elle sert mieux
    qu'une date de génération, qui changerait sans que rien ne change.
    """
    morceaux = ["card-api", endpoint,
                _abrege(out["stations"], "stations"),
                _abrege(out["cards"], "variables")]
    if out.get("mk"):
        morceaux.append(str(out["mk"]))
    morceaux.append(_annees(table))
    empreinte = str(out.get("data_fingerprint", "")).split(":")[-1][:8]
    if empreinte:
        morceaux.append(empreinte)
    nom = "_".join(m for m in morceaux if m)
    return re.sub(r"[^A-Za-z0-9._-]", "", nom) + ".csv"


def _csv_response(table, out, endpoint):
    """Le fichier complet : provenance en `#`, puis le tableau.

    Virgule et point décimal : ce sont pandas et R qui lisent ces
    fichiers, les deux clients documentés dans le README. Hub'Eau écrit
    en `;` pour Excel français, au prix d'un fichier que `read_csv` ne
    lit pas sans réglage.
    """
    corps = _csv_entete(out, endpoint) + table.to_csv(index=False)
    return _RawResponse(
        corps.encode("utf-8"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{_csv_nom(table, out, endpoint)}"'})


def _csv_job(out):
    """Une demande passée en file de calcul n'a pas de fichier à rendre :
    on le dit en texte plutôt que de servir un CSV vide."""
    return _RawResponse(
        (f"# demande trop grosse pour une réponse immédiate\n"
         f"# elle est partie en file de calcul, ticket {out['job']}\n"
         f"# suivi : {out['status_url']} · résultat en JSON\n"
         ).encode("utf-8"),
        media_type="text/csv; charset=utf-8", status_code=202,
        headers={"Location": out["status_url"]})


# ── La tendance, DESSINÉE ──────────────────────────────────────────────
#
# Même geste que `/v1/cards/{id}/figure` : la représentation lisible d'un
# résultat que le JSON porte déjà. Il ne s'agit pas d'un second calcul,
# mais d'un second AFFICHAGE du même, ce qui est la définition d'une
# représentation en HTTP. D'où un paramètre `format` sur l'endpoint, et
# non un endpoint jumeau qui redirait ses neuf paramètres.
#
# Ce que la table montre, et pourquoi : la pente de Sen dans l'unité de
# la variable dit l'ampleur, la pente relative en %/an la rend comparable
# entre variables, la p-value dit la confiance, et le verdict traduit le
# `h` booléen en français. Sans cette dernière colonne, il faut savoir
# que `h=true` veut dire « stationnarité rejetée » pour lire le tableau,
# ce que personne ne sait à la première visite.
_FLECHES = {True: "▲", False: "▼"}


def _fmt_nombre(x, chiffres=2):
    if x is None or (isinstance(x, float) and x != x):
        return "-"
    return f"{x:+,.{chiffres}f}".replace(",", " ")


def _trend_figure(out, meta_par_id):
    """Le résultat d'une tendance, en table lisible."""
    lignes = []
    seuil = out["level"]
    lignes.append(f"TENDANCE  Mann-Kendall ({out['mk']}) et pente de Sen, "
                  f"seuil {seuil:.0%}")
    p = out["period"]
    if p["start"] or p["end"]:
        lignes.append(f"          période demandée : {p['start'] or '…'} "
                      f"→ {p['end'] or '…'}")
    lignes.append("")

    cols = ("variable", "période", "pente", "relative", "p", "verdict")
    largeurs = [len(c) for c in cols]
    par_station = {}
    for cid, rows in out["data"].items():
        unite = (meta_par_id.get(cid) or {}).get("unit_fr") or ""
        unite = unite.replace("m^{3}.s^{-1}", "m³/s")
        for r in rows:
            significatif = bool(r.get("h"))
            sens = _FLECHES[(r.get("a") or 0) >= 0]
            ligne = (
                cid,
                f"{str(r.get('period_start'))[:7]} → "
                f"{str(r.get('period_end'))[:7]}",
                f"{_fmt_nombre(r.get('a'))} {unite}/an".strip(),
                f"{_fmt_nombre(r.get('a_relative'))} %/an",
                f"{r.get('p'):.3f}" if r.get("p") is not None else "-",
                (f"{sens} significative" if significatif
                 else "— non significative"),
            )
            par_station.setdefault(r.get("code_station"), []).append(ligne)
            largeurs = [max(w, len(c)) for w, c in zip(largeurs, ligne)]

    def rangee(cellules, remplissage=" "):
        return "  │ " + " │ ".join(
            c.ljust(w, remplissage) for c, w in zip(cellules, largeurs)
        ) + " │"

    filet = "  ├─" + "─┼─".join("─" * w for w in largeurs) + "─┤"
    haut = "  ┌─" + "─┬─".join("─" * w for w in largeurs) + "─┐"
    bas = "  └─" + "─┴─".join("─" * w for w in largeurs) + "─┘"

    for station, lignes_st in par_station.items():
        lignes += [f"  {station}", haut, rangee(cols), filet]
        lignes += [rangee(cellules) for cellules in lignes_st]
        lignes += [bas, ""]

    # Écarter une station est un fait du résultat, pas une note de bas de
    # page : il se lit AVANT la provenance, avec le compte, pour qu'un
    # lecteur pressé sache tout de suite que le lot n'est pas entier.
    omises = out.get("stations_omitted") or []
    if omises:
        lignes.append(f"  {len(omises)} station(s) écartée(s) sur "
                      f"{len(out['stations']) + len(omises)} demandées :")
        for o in omises:
            lignes.append(f"    {o['code_station']} · {o['detail']}")
        lignes.append("")
    lignes.append(f"  source : {out['source']}")
    lignes.append(f"  données lues le {out['data_fetched_at'][:10]} "
                  f"· empreinte {out['data_fingerprint'][:12]}")
    lignes.append(f"  card {out.get('card_version')} · stase "
                  f"{out.get('stase_version')} · api {out.get('api_version')}")
    lignes.append("")
    lignes.append("  Le JSON complet (intervalles, moyenne de période, "
                  "métadonnées) : format=json.")
    return "\n".join(lignes)


def _omission(station: str, reason: str, detail) -> dict:
    """Une station écartée du calcul, dite en clair ET en code.

    `reason` se teste par un programme, `detail` se lit par un humain.
    Le nom de colonne est `code_station`, celui de Hub'Eau, pour que le
    bloc se joigne au référentiel sans traduction (règle du service).
    """
    return {"code_station": station, "reason": reason, "detail": str(detail)}


def _check_sampling(sampling):
    if sampling is not None and not _SAMPLING_RE.match(sampling):
        raise HTTPException(
            422, f"sampling invalide : {sampling!r}. Valeurs acceptées : "
                 "'preferred' (fenêtre fixe déclarée par chaque fiche) "
                 "ou 'MM-JJ' (ex. '09-01')")


def _run_extract(st, cd, start, end, sampling=None):
    """Retourne (résultat de card.extract, empreintes, retenues, omises).

    L'empreinte est prise sur la chronique ENTIÈRE, avant filtre de
    période : la période demandée figure déjà dans la provenance, et ce
    qu'on identifie ici c'est la source.

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
    l'appel (Hub'Eau injoignable) reste une erreur. Sauter le second
    fabriquerait des résultats silencieusement plus petits les jours de
    panne, ce qu'aucun lecteur ne remarquerait.
    """
    frames, empreintes, retenues, omises = [], {}, [], []
    for s in st:
        try:
            df = hubeau.fetch_chronicle(s)
        except hubeau.StationInconnue as e:
            omises.append(_omission(s, "no_series", e))
            continue
        except hubeau.SiteAmbigu as e:
            omises.append(_omission(s, "ambiguous_site", e))
            continue
        except hubeau.HubEauIndisponible as e:
            raise HTTPException(504, str(e), headers={"Retry-After": "300"})
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
        raise HTTPException(
            404, f"aucune des {len(st)} stations demandées n'a de série "
                 f"exploitable : {detail}")
    data = pd.concat(frames, ignore_index=True)
    with jobs.COMPUTE:
        try:
            res = card.extract(data, cards=cd, sampling_period=sampling,
                               verbose=False)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
    return res, empreintes, retenues, omises


class ExtractParams(BaseModel):
    """Les paramètres de l'extraction, déclarés UNE fois. Partagés par
    `/v1/extract` et `/v1/extract.csv` (cf. TrendParams)."""

    stations: str = Field(json_schema_extra=_X_STATIONS,
                          description=_D_STATIONS)
    cards: str = Field(json_schema_extra=_X_CARDS, description=_D_CARDS)
    start: str | None = Field(None, json_schema_extra=_X_START,
                              description=_D_START)
    end: str | None = Field(None, description=_D_END)
    sampling: str | None = Field(None, description=_D_SAMPLING)
    stations_meta: bool = Field(False, description=_D_STATIONS_META)
    orient: _Orient = Field("records", description=_D_ORIENT)


def _extract_result(request: Request, p: ExtractParams, rendu="json"):
    """Le calcul, partagé par les deux représentations d'extract.

    Rend (résultat JSON, données par fiche), ou (ticket, None) si la
    demande a basculé en file de calcul.
    """
    # Résolu ICI et une seule fois : la valeur effective part ensuite
    # partout, y compris dans les paramètres gelés d'un job. Sans quoi
    # une demande sans `start` et le job qu'elle engendre ne porteraient
    # pas la même fenêtre.
    p = p.model_copy(update={"start": p.start or START_DEFAUT})
    _check_sampling(p.sampling)
    prio = usage.priority_of(request)
    st, cd = _parse_lists(p.stations, p.cards, prio)
    ticket = _maybe_job(request, "extract", st, cd, prio, start=p.start,
                        end=p.end, sampling=p.sampling,
                        stations_meta=p.stations_meta or None,
                        orient=p.orient)
    if ticket is not None:
        return ticket, None
    res, empreintes, retenues, omises = _run_extract(
        st, cd, p.start, p.end, p.sampling)

    extracted = res["data"]
    if not isinstance(extracted, dict):
        extracted = {cd[0]: extracted}
    usage.log_usage(request, "extract", stations=len(st), cards=cd,
                    rendu=rendu, omises=len(omises) or None)
    out = {
        **versions(),
        "rights": rights(),
        # `stations` décrit les DONNÉES, pas la demande : ce sont les
        # stations que `data` contient réellement. Recopier la demande
        # annoncerait vingt stations pour dix-neuf séries, et toute
        # jointure faite sur cette liste porterait à faux.
        "stations": retenues,
        "stations_requested": st,
        "stations_omitted": omises,
        "cards": cd,
        "period": {"start": p.start, "end": p.end},
        "sampling": p.sampling,
        "source": SOURCE,
        "data_fetched_at": _fetched_at(retenues),
        "data_fingerprint": hubeau.combine_fingerprints(empreintes),
        "orient": p.orient,
        "meta": serialize(res["meta"]),
        "data": {k: serialize(v, p.orient) for k, v in extracted.items()},
    }
    if p.stations_meta:
        # Le référentiel couvre les stations DEMANDÉES, omises comprises :
        # c'est là qu'on lit pourquoi. Le libellé « échelle aval de Mâcon »
        # explique à lui seul qu'un limnimètre ne publie pas de débit.
        out["stations_meta"] = _stations_meta(st)
    return out, extracted


@app.get("/v1/extract", tags=["data"],
         summary="Chroniques Hub'Eau vers variables CARD",
         dependencies=[Depends(usage.rate_compute)])
def extract(request: Request, p: Annotated[ExtractParams, Query()]):
    """Extrait des variables CARD sur des chroniques Hub'Eau.

    Au-dessus des plafonds synchrones (défaut 10 stations, 20 fiches),
    la demande devient un job : réponse 202 avec un ticket à suivre
    (cf. /v1/jobs/{id}).

    **Une station sans série exploitable est écartée, pas fatale.** Le
    résultat décrit alors ce qu'il contient réellement : `stations` liste
    les stations CALCULÉES, `stations_requested` celles demandées, et
    `stations_omitted` dit lesquelles ont été écartées et pourquoi
    (`no_series` : aucune chronique QmnJ publiée, cas d'une station
    limnimétrique ; `no_data_in_period` : rien dans la fenêtre demandée ;
    `ambiguous_site` : code de site à plusieurs stations parallèles). Le
    bloc est toujours présent, vide quand tout va bien. Si AUCUNE station
    n'a de série, la demande est refusée en 404 : il n'y a rien à rendre.
    Une panne Hub'Eau, elle, reste une erreur (504) et n'est jamais
    silencieusement transformée en omission.

    Pour un fichier ouvrable au tableur : `/v1/extract.csv`, mêmes
    paramètres.
    """
    out, extracted = _extract_result(request, p)
    return _job_response(out) if extracted is None else out


@app.get("/v1/extract.csv", tags=["data"],
         summary="Les mêmes séries, en CSV pour le tableur",
         response_class=_RawResponse,
         responses={200: {"content": {"text/csv": {}}}},
         dependencies=[Depends(usage.rate_compute)])
def extract_csv(request: Request, p: Annotated[ExtractParams, Query()]):
    """Les mêmes données qu'`/v1/extract`, en un seul tableau.

    Forme LONGUE (`code_station, date, variable, value`) et non une colonne par
    variable : deux fiches n'ont pas le même pas de temps ni les mêmes
    années, les mettre côte à côte fabriquerait des trous qui ne sont pas
    dans la donnée. `pandas.pivot` ou `tidyr::pivot_wider` remettent en
    large si besoin.
    """
    out, extracted = _extract_result(request, p, rendu="csv")
    if extracted is None:
        return _csv_job(out)
    longues = []
    for cid, df in extracted.items():
        colonnes = [c for c in df.columns
                    if c not in ("code_station", "date")]
        for col in colonnes:
            part = (df[["code_station", "date", col]]
                    .rename(columns={col: "value"}))
            part.insert(2, "variable", col)
            longues.append(part)
    table = (pd.concat(longues, ignore_index=True) if longues
             else pd.DataFrame(
                 columns=["code_station", "date", "variable", "value"]))
    return _csv_response(table, out, "extract")


class TrendParams(BaseModel):
    """Les paramètres de la tendance, déclarés UNE fois.

    Deux endpoints les partagent : `/v1/trend`, qui rend le résultat, et
    `/v1/trend/figure`, qui le dessine. Les recopier serait la garantie
    qu'ils divergent au premier ajout, et c'est ce qui rendait un
    endpoint séparé plus cher qu'un paramètre `format`. FastAPI accepte
    un modèle comme paramètres de requête (`Annotated[..., Query()]`) et
    les deux opérations produisent alors des `parameters` identiques dans
    le contrat, descriptions et exemples compris.
    """

    stations: str = Field(json_schema_extra=_X_STATIONS,
                          description=_D_STATIONS)
    cards: str = Field(json_schema_extra=_X_CARDS, description=_D_CARDS)
    start: str | None = Field(None, json_schema_extra=_X_START,
                              description=_D_START)
    end: str | None = Field(None, description=_D_END)
    sampling: str | None = Field(None, description=_D_SAMPLING)
    mk: _Mk = Field("AR1", description=_D_MK)
    level: float = Field(0.1, gt=0, lt=1, description=_D_LEVEL)
    series: bool = Field(False, description=_D_SERIES)
    stations_meta: bool = Field(False, description=_D_STATIONS_META)
    orient: _Orient = Field("records", description=_D_ORIENT)


def _trend_result(request: Request, p: TrendParams, rendu="json"):
    """Le calcul, partagé par les deux représentations.

    Rend soit un ticket de job (la demande dépassait les plafonds
    synchrones), soit le couple (résultat JSON, tendances par fiche).
    """
    p = p.model_copy(update={"start": p.start or START_DEFAUT})
    _check_sampling(p.sampling)
    prio = usage.priority_of(request)
    st, cd = _parse_lists(p.stations, p.cards, prio)
    _check_cards_series(cd)
    ticket = _maybe_job(request, "trend", st, cd, prio, start=p.start,
                        end=p.end, sampling=p.sampling, mk=p.mk,
                        level=p.level, series=p.series or None,
                        stations_meta=p.stations_meta or None,
                        orient=p.orient)
    if ticket is not None:
        return ticket, None

    res, empreintes, retenues, omises = _run_extract(
        st, cd, p.start, p.end, p.sampling)
    with jobs.COMPUTE:
        try:
            tr = card.trend(res, level=p.level, dependency=p.mk,
                            seed=LTP_SEED)
        except ValueError as e:
            raise HTTPException(422, str(e))

    usage.log_usage(request, "trend", stations=len(st), cards=cd,
                    mk=p.mk, rendu=rendu, omises=len(omises) or None)
    out = {
        **versions(),
        "rights": rights(),
        "stations": retenues,           # cf. _extract_result : les DONNÉES
        "stations_requested": st,
        "stations_omitted": omises,
        "cards": cd,
        "period": {"start": p.start, "end": p.end},
        "sampling": p.sampling,
        "mk": p.mk, "level": p.level,
        "source": SOURCE,
        "data_fetched_at": _fetched_at(retenues),
        "data_fingerprint": hubeau.combine_fingerprints(empreintes),
        "orient": p.orient,
        "meta": serialize(res["meta"]),
        "data": {cid: serialize(df, p.orient)
                 for cid, df in tr["data"].items()},
    }
    if p.series:
        out["series"] = {cid: serialize(df, p.orient)
                         for cid, df in res["data"].items()}
    if p.stations_meta:
        out["stations_meta"] = _stations_meta(st)
    return out, tr


@app.get("/v1/trend", tags=["data"],
         summary="Tendance et test de stationnarité",
         dependencies=[Depends(usage.rate_compute)])
def trend(request: Request, p: Annotated[TrendParams, Query()]):
    """Diagnostic de stationnarité : extraction CARD puis test de
    Mann-Kendall et pente de Sen (card.trend) sur chaque série.

    Fiches acceptées : sorties de forme `series` uniquement, la tendance
    d'un scalaire ou d'une courbe n'ayant pas de sens. Les analyses
    MAKAHO correspondent à `sampling=preferred`.

    Comme `/v1/extract`, une station sans série exploitable est écartée et
    non fatale : `stations` liste les stations calculées et
    `stations_omitted` dit lesquelles ont sauté et pourquoi.

    Pour lire le résultat sans traverser le JSON : `/v1/trend/figure`,
    mêmes paramètres.
    """
    out, tr = _trend_result(request, p)
    return _job_response(out) if tr is None else out


@app.get("/v1/trend.csv", tags=["data"],
         summary="Les mêmes diagnostics, en CSV pour le tableur",
         response_class=_RawResponse,
         responses={200: {"content": {"text/csv": {}}}},
         dependencies=[Depends(usage.rate_compute)])
def trend_csv(request: Request, p: Annotated[TrendParams, Query()]):
    """Les mêmes diagnostics qu'`/v1/trend`, en un seul tableau : une
    ligne par station et par variable, toutes les colonnes du test.

    Contrairement à la figure, rien n'est retiré : le CSV est le même
    résultat autrement écrit, intervalles de pente compris.
    """
    out, tr = _trend_result(request, p, rendu="csv")
    if tr is None:
        return _csv_job(out)
    table = pd.concat(list(tr["data"].values()), ignore_index=True)
    return _csv_response(table, out, "trend")


@app.get("/v1/trend/figure", tags=["data"],
         summary="Le diagnostic de stationnarité, dessiné",
         response_class=PlainTextResponse,
         dependencies=[Depends(usage.rate_compute)])
def trend_figure(request: Request, p: Annotated[TrendParams, Query()]):
    """La tendance **dessinée** : une ligne par variable, avec le sens,
    l'ampleur, la p-value et le **verdict en clair**.

    Même calcul et mêmes paramètres que `/v1/trend`, autre lecture. Il
    fallait jusqu'ici savoir que `h: true` signifie « stationnarité
    rejetée » pour lire une réponse. Ce que la table ne montre pas (les
    intervalles de pente, la moyenne de période, les métadonnées des
    fiches) reste dans `/v1/trend`.
    """
    out, tr = _trend_result(request, p, rendu="figure")
    if tr is None:                       # la demande est partie en job
        return PlainTextResponse(
            f"Demande trop grosse pour une réponse immédiate : elle est "
            f"partie en file de calcul.\nTicket {out['job']}, suivi sur "
            f"{out['status_url']}.\nLe résultat d'un job est du JSON ; "
            f"cette page ne dessine que les réponses immédiates.",
            status_code=202,
            headers={"Location": out["status_url"]})
    # La table se lit sur `records` quel que soit `orient` : elle parcourt
    # des lignes, pas des colonnes. `orient` ne concerne que la sortie
    # JSON, il n'a pas à changer un dessin.
    lisible = dict(out, data={cid: serialize(df, "records")
                              for cid, df in tr["data"].items()})
    return PlainTextResponse(
        _trend_figure(lisible, {m.get("variable_en"): m for m in out["meta"]}))


# ── Jobs : demandes massives en file de calcul ──────────────────────────────

class JobRequest(BaseModel):
    """Corps d'un dépôt de job : les paramètres de /v1/extract ou de
    /v1/trend, plus le nom de celui qu'on veut faire tourner."""

    endpoint: _Endpoint = Field(
        description="Traitement à exécuter sur la demande.")
    stations: str | list[str] = Field(description=_D_STATIONS)
    cards: str | list[str] = Field(description=_D_CARDS)
    start: str | None = Field(None, description=_D_START)
    end: str | None = Field(None, description=_D_END)
    sampling: str | None = Field(None, description=_D_SAMPLING)
    mk: _Mk = Field("AR1", description=_D_MK)
    level: float = Field(0.1, gt=0, lt=1, description=_D_LEVEL)
    series: bool = Field(False, description=_D_SERIES)
    stations_meta: bool = Field(False, description=_D_STATIONS_META)
    orient: _Orient = Field("records", description=_D_ORIENT)

    # Un corps d'exemple complet : Swagger pré-remplit la zone de saisie
    # avec, donc déposer un vrai job ne demande aucune rédaction.
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "endpoint": "trend",
                "stations": ["F700000103"],
                "cards": ["QA", "VCN10"],
                "start": "1970-01-01",
                "sampling": "preferred",
                "mk": "AR1",
            }],
        },
    }


@app.post("/v1/jobs", status_code=202, tags=["jobs"],
          summary="Déposer une demande massive",
          dependencies=[Depends(usage.rate_compute)])
def create_job(request: Request, req: JobRequest):
    """Dépose une demande massive en file de calcul (public, sans clé).

    Mêmes paramètres que /v1/extract et /v1/trend, plafonds plus hauts
    (défaut 100 stations, 50 fiches). Réponse : 202 + ticket ; suivre
    status_url puis récupérer result_url (résultat gelé avec bloc de
    provenance, conservé quelques jours). Les demandes au-dessus des
    plafonds synchrones passées à /v1/extract ou /v1/trend basculent
    ici automatiquement.
    """
    _check_sampling(req.sampling)
    prio = usage.priority_of(request)
    st, cd = _parse_lists(req.stations, req.cards, prio)
    if req.endpoint == "trend":
        _check_cards_series(cd)
    params = {"endpoint": req.endpoint, "stations": st, "cards": cd}
    if req.start:
        params["start"] = req.start
    if req.end:
        params["end"] = req.end
    if req.sampling:
        params["sampling"] = req.sampling
    if req.stations_meta:
        params["stations_meta"] = True
    if req.endpoint == "trend":
        params.update(mk=req.mk, level=req.level)
        if req.series:
            params["series"] = True
    params["orient"] = req.orient
    try:
        job = jobs.submit(params,
                          user=usage.ip_hash(usage.client_ip(request)),
                          priority=-1 if prio else 0,
                          key=prio["prefix"] if prio else None)
    except RuntimeError as e:
        raise HTTPException(503, str(e), headers={"Retry-After": "300"})
    extra = {"key": prio["prefix"]} if prio else {}
    usage.log_usage(request, "jobs", job=job["id"], target=req.endpoint,
                    stations=len(st), cards=cd, **extra)
    return _job_response(_job_envelope(job))


@app.get("/v1/jobs", tags=["jobs"],
         summary="Mes jobs (clé de priorité requise)",
         dependencies=[Depends(usage.rate_light)])
def job_list(request: Request):
    """Jobs déposés avec la clé de priorité présentée (« mes jobs »,
    forme du GET /jobs d'OGC API Processes restreinte à la clé).

    Réservé aux porteurs de clé : sans comptes, une liste publique
    exposerait les tickets et l'activité de tous. Présenter la clé en
    en-tête X-API-Key de préférence à key= (les URLs finissent dans
    les logs du frontal web)."""
    prio = usage.priority_of(request)
    if prio is None:
        raise HTTPException(
            401, "listing réservé aux porteurs de clé de priorité : "
                 "présentez la vôtre en en-tête X-API-Key (les jobs "
                 "restent consultables un par un via leur ticket)")
    return {"key": prio["prefix"], "jobs": jobs.list_for(prio["prefix"])}


@app.get("/v1/jobs/{job_id}", tags=["jobs"],
         summary="Statut et progression d'un job",
         dependencies=[Depends(usage.rate_light)])
def job_status(
    response: Response,
    job_id: str = PathParam(json_schema_extra=_X_JOB_ID,
                            description=_D_JOB_ID),
):
    """Statut et progression d'un job (queued, running, done, failed)."""
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, f"job inconnu ou expiré : {job_id}")
    if job["status"] in ("queued", "running"):
        response.headers["Retry-After"] = "10"
    return {
        "job": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "created": job["created"],
        "started": job["started"],
        "finished": job["finished"],
        "error": job["error"],
        "result_url": f"/v1/jobs/{job['id']}/result",
    }


@app.get("/v1/jobs/{job_id}/result", tags=["jobs"],
         summary="Résultat d'un job terminé",
         dependencies=[Depends(usage.rate_light)])
def job_result(job_id: str = PathParam(json_schema_extra=_X_JOB_ID,
                                       description=_D_JOB_ID)):
    """Résultat d'un job terminé (même format que l'endpoint synchrone,
    plus un bloc de provenance : paramètres, versions, date des
    données)."""
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, f"job inconnu ou expiré : {job_id}")
    if job["status"] == "failed":
        raise HTTPException(409, f"job en échec : {job['error']}")
    if job["status"] != "done":
        raise HTTPException(
            409, f"job pas encore terminé (statut : {job['status']}), "
                 f"suivre /v1/jobs/{job_id}")
    raw = jobs.result_bytes(job_id)
    if raw is None:
        raise HTTPException(404, f"résultat expiré : {job_id}")
    return Response(content=raw, media_type="application/json")


def _tree_mb(path) -> float:
    total = 0
    if path.exists():
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    return round(total / 1e6, 1)


@app.delete("/v1/jobs/{job_id}", status_code=204, tags=["jobs"],
            summary="Abandonner un job par son ticket",
            dependencies=[Depends(usage.rate_light)])
def job_delete(request: Request,
               job_id: str = PathParam(json_schema_extra=_X_JOB_ID,
                                       description=_D_JOB_ID)):
    """Supprime un job et son résultat sans attendre le TTL (le
    « dismiss » d'OGC API Processes). Le ticket vaut capacité, comme
    pour la lecture. Un job en cours d'exécution n'est pas annulable
    (calcul non interruptible) : réessayer une fois terminé."""
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(404, f"job inconnu ou expiré : {job_id}")
    if job["status"] == "running":
        raise HTTPException(409, "job en cours d'exécution : "
                                 "suppression possible une fois terminé")
    jobs.delete(job_id)
    usage.log_usage(request, "jobs_delete", job=job_id)
    return Response(status_code=204)


@app.get("/v1/health", tags=["service"],
         summary="Sonde de vie et charge")
def health():
    """Sonde de vie et charge (déploiement, supervision), lisible par
    n'importe quelle sonde. `disk` décrit le système de fichiers de la
    VM ENTIÈRE (partagé avec d'autres services : c'est la place
    restante qui borne les jobs, pas notre consommation) ; `data` est
    l'empreinte propre de card-api (cache des chroniques, jobs,
    journal)."""
    d = hubeau.data_dir()
    du = shutil.disk_usage(d)
    return {
        "status": "ok",
        **versions(),
        "jobs": jobs.queue_stats(),
        "disk": {"used_pct": round(du.used / du.total * 100, 1),
                 "free_gb": round(du.free / 1e9, 1)},
        "data": {"total_mb": _tree_mb(d),
                 "cache_mb": _tree_mb(d / "chroniques"),
                 "jobs_mb": _tree_mb(d / "jobs")},
    }

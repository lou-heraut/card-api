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
import json
import os
import re
import shutil

import httpx
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

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


_TAGS = [
    {"name": "service", "description": "Identité, versions et santé du service."},
    {"name": "cards", "description": "Catalogue et détail des fiches CARD."},
    {"name": "data", "description": "Extraction et tendance sur les débits Hub'Eau."},
    {"name": "stations", "description": "Référentiel des stations hydrométriques."},
    {"name": "jobs", "description": "File de calcul asynchrone (grosses demandes)."},
]

app = FastAPI(
    title="card-api",
    version=API_VERSION,
    description=(
        "Variables hydroclimatiques prêtes à l'emploi, calculées sur les "
        "débits Hub'Eau, avec diagnostic de tendance. Façade du projet "
        "CARD : les fiches [card](https://github.com/lou-heraut/card) "
        "définissent les variables, le moteur "
        "[stase](https://github.com/lou-heraut/stase) les calcule, "
        "[Hub'Eau](https://hubeau.eaufrance.fr/) fournit les observations. "
        "Service public de recherche (INRAE, UR RiverLy), accès ouvert. "
        "Chaque réponse porte sa provenance (commit et SWHID de card et "
        "stase, version de chaque fiche) et ses droits. Point d'entrée : "
        "`GET /v1`."
    ),
    contact={"name": "INRAE, UR RiverLy",
             "url": "https://github.com/lou-heraut/card-api"},
    license_info={"name": "GPL-3.0-or-later",
                  "url": "https://www.gnu.org/licenses/gpl-3.0.html"},
    openapi_tags=_TAGS,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
# API publique en lecture : un client navigateur (site web tiers) doit
# pouvoir l'appeler. Origines ouvertes, sans cookies d'identité.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["*"],
)




@app.get("/v1", tags=["service"])
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
        "endpoints": {
            "cards": "/v1/cards", "card_detail": "/v1/cards/{id}",
            "card_figure": "/v1/cards/{id}/figure",
            "vocabulary": "/v1/vocabulary",
            "stations": "/v1/stations", "extract": "/v1/extract",
            "trend": "/v1/trend", "jobs": "/v1/jobs", "health": "/v1/health",
            "openapi": "/openapi.json", "docs": "/docs",
        },
        "reuse": "API pour l'usage ponctuel ; la bibliothèque Python card "
                 "pour le gros volume et l'intégration ; citer une fiche par "
                 "son swhid (présent dans les métadonnées) pour reproduire.",
        "rights": rights(),
    }


@app.get("/v1/cards", tags=["cards"], dependencies=[Depends(usage.rate_light)])
def cards(domain: str | None = None,
          phenomenon: str | None = None,
          aspect: str | None = None,
          season: str | None = None,
          output: str | None = None,
          purpose: str | None = None,
          operator: str | None = None,
          function: str | None = None,
          variable: str | None = None,
          search: str | None = None,
          limit: int = Query(default=1000, le=1000)):
    """Catalogue des fiches (une ligne par variable), filtres par facette
    de classification, dans les deux langues ; mêmes filtres que
    card.list_cards()."""
    df = card.list_cards(domain=domain, phenomenon=phenomenon,
                         aspect=aspect, season=season, output=output,
                         purpose=purpose, operator=operator,
                         function=function, variable=variable,
                         search=search)
    return {
        **versions(),
        "count": int(len(df)),
        "cards": clean(df.head(limit).to_dict(orient="records")),
    }


@app.get("/v1/cards/{card_id}", tags=["cards"], dependencies=[Depends(usage.rate_light)])
def card_detail(card_id: str, lang: str = "fr"):
    """Détail d'une fiche : métadonnées complètes et classification.

    Deux liens vers la définition employée : `yaml` pointe le fichier sur
    GitHub à la révision réellement exécutée, `archive` le même contenu
    dans Software Heritage, qui restera lisible même si le dépôt bouge.
    """
    if lang not in ("fr", "en"):
        raise HTTPException(422, "lang doit être 'fr' ou 'en'")
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
         response_class=PlainTextResponse,
         dependencies=[Depends(usage.rate_light)])
def card_figure(card_id: str, lang: str = "fr"):
    """La fiche **dessinée** : chaîne de calcul, fonctions et réglages,
    fenêtre d'échantillonnage sur douze mois, ce qui est produit.

    Même fiche que `/v1/cards/{id}`, autre représentation : celui-ci reste
    du JSON pour les machines, celui-là est du texte pour comprendre d'un
    coup d'oeil ce que la fiche calcule, sans lire son YAML.
    """
    if lang not in ("fr", "en"):
        raise HTTPException(422, "lang doit être 'fr' ou 'en'")
    try:
        return card.figure(card_id, lang=lang)
    except FileNotFoundError as e:
        if e.filename:                       # bug serveur, pas fiche absente
            raise
        raise HTTPException(404, f"fiche inconnue : {card_id}")


@app.get("/v1/vocabulary", tags=["cards"],
         dependencies=[Depends(usage.rate_light)])
def vocabulary():
    """Valeurs valides des facettes de classification, en français et en
    anglais.

    Ce sont exactement les filtres acceptés par `/v1/cards` : de quoi
    construire une requête juste, ou peupler un menu, sans les deviner.
    """
    return {**versions(), "vocabulary": card.vocabulary()}


@app.get("/v1/stations", tags=["stations"], dependencies=[Depends(usage.rate_light)])
def stations(libelle: str | None = None, code: str | None = None,
             departement: str | None = None, size: int = Query(20, le=100)):
    """Recherche de stations hydrométriques (référentiel Hub'Eau).
    Utile aussi pour retrouver les nouveaux codes : depuis la refonte
    Hydro, les anciens codes Banque Hydro ne sont plus valides."""
    if not any((libelle, code, departement)):
        raise HTTPException(422, "donner au moins libelle, code ou departement")
    try:
        return {"stations": hubeau.search_stations(libelle, code,
                                                   departement, size)}
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
    if len(st) > max_st or len(cd) > max_cd:
        hint = ("" if prio else
                " ; besoin plus large : demandez une clé de priorité")
        raise HTTPException(
            422, f"au plus {max_st} stations et {max_cd} fiches par "
                 f"demande (au-delà de {jobs.SYNC_STATIONS} stations ou "
                 f"{jobs.SYNC_CARDS} fiches, la demande devient un "
                 f"job){hint}")
    _check_cards_q(cd)
    return st, cd


def _job_response(job: dict) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        headers={"Location": f"/v1/jobs/{job['id']}"},
        content={
            "job": job["id"],
            "status": job["status"],
            "status_url": f"/v1/jobs/{job['id']}",
            "result_url": f"/v1/jobs/{job['id']}/result",
            "detail": "demande mise en file : suivre status_url, le "
                      "résultat reste disponible "
                      f"{jobs.JOB_TTL_DAYS:g} jours",
        })


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
    return _job_response(job)


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


def _check_sampling(sampling):
    if sampling is not None and not _SAMPLING_RE.match(sampling):
        raise HTTPException(
            422, f"sampling invalide : {sampling!r}. Valeurs acceptées : "
                 "'preferred' (fenêtre fixe déclarée par chaque fiche) "
                 "ou 'MM-JJ' (ex. '09-01')")


def _run_extract(st, cd, start, end, sampling=None):
    """Retourne (résultat de card.extract, empreintes par station).

    L'empreinte est prise sur la chronique ENTIÈRE, avant filtre de
    période : la période demandée figure déjà dans la provenance, et ce
    qu'on identifie ici c'est la source.
    """
    frames, empreintes = [], {}
    for s in st:
        try:
            df = hubeau.fetch_chronicle(s)
        except hubeau.StationInconnue as e:
            raise HTTPException(404, str(e))
        except hubeau.HubEauIndisponible as e:
            raise HTTPException(504, str(e), headers={"Retry-After": "300"})
        empreintes[s] = hubeau.fingerprint(df)
        if start:
            df = df[df["date"] >= start]
        if end:
            df = df[df["date"] <= end]
        if df.empty:
            raise HTTPException(404, f"{s}: aucune donnée sur la période")
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)
    with jobs.COMPUTE:
        try:
            res = card.extract(data, cards=cd, sampling_period=sampling,
                               verbose=False)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
    return res, empreintes


@app.get("/v1/extract", tags=["data"], dependencies=[Depends(usage.rate_compute)])
def extract(request: Request, stations: str, cards: str,
            start: str | None = None, end: str | None = None,
            sampling: str | None = None,
            stations_meta: bool = False,
            orient: str = "records"):
    """Extrait des variables CARD sur des chroniques Hub'Eau.

    stations : codes séparés par des virgules.
    cards    : ids de fiches séparés par des virgules ;
               fiches à entrée Q uniquement (données hydrométriques).
    Au-dessus des plafonds synchrones (défaut 10 stations, 20 fiches),
    la demande devient un job : réponse 202 avec un ticket à suivre
    (cf. /v1/jobs/{id}).
    start/end: bornes AAAA-MM-JJ optionnelles (défaut : tout).
    sampling : écrase la fenêtre annuelle des fiches. 'preferred' :
               fenêtre fixe déclarée par chaque fiche (reproductible,
               protocole MAKAHO) ; 'MM-JJ' (ex. '09-01') : année
               hydrologique imposée. Défaut : fenêtre de la fiche
               (adaptative par station pour les fiches d'étiage/crue).
    stations_meta : true pour joindre sous 'stations_meta' les fiches
               du référentiel Hub'Eau des stations demandées (libellé,
               longitude/latitude...) : résultat autoportant, une
               carte ne demande aucun fichier local.
    orient   : 'records' (défaut, liste d'objets, style Hub'Eau) ou
               'columns' (colonnaire : {colonne: [valeurs]}, compact).
    """
    if orient not in ("records", "columns"):
        raise HTTPException(422, "orient : 'records' ou 'columns'")
    _check_sampling(sampling)
    prio = usage.priority_of(request)
    st, cd = _parse_lists(stations, cards, prio)
    ticket = _maybe_job(request, "extract", st, cd, prio, start=start,
                        end=end, sampling=sampling,
                        stations_meta=stations_meta or None, orient=orient)
    if ticket is not None:
        return ticket
    res, empreintes = _run_extract(st, cd, start, end, sampling)

    extracted = res["data"]
    if not isinstance(extracted, dict):
        extracted = {cd[0]: extracted}
    data_out = {k: serialize(v, orient) for k, v in extracted.items()}
    usage.log_usage(request, "extract", stations=len(st), cards=cd)
    out = {
        **versions(),
        "rights": rights(),
        "stations": st,
        "cards": cd,
        "period": {"start": start, "end": end},
        "sampling": sampling,
        "source": SOURCE,
        "data_fetched_at": _fetched_at(st),
        "data_fingerprint": hubeau.combine_fingerprints(empreintes),
        "orient": orient,
        "meta": serialize(res["meta"]),
        "data": data_out,
    }
    if stations_meta:
        out["stations_meta"] = _stations_meta(st)
    return out


@app.get("/v1/trend", tags=["data"], dependencies=[Depends(usage.rate_compute)])
def trend(request: Request, stations: str, cards: str,
          start: str | None = None, end: str | None = None,
          sampling: str | None = None,
          mk: str = "AR1", level: float = Query(0.1, gt=0, lt=1),
          series: bool = False,
          stations_meta: bool = False,
          orient: str = "records"):
    """Diagnostic de stationnarité : extraction CARD puis test de
    Mann-Kendall et pente de Sen (card.trend) sur chaque série.

    sampling : écrase la fenêtre annuelle des fiches ('preferred' ou
            'MM-JJ', cf. /v1/extract) ; les analyses MAKAHO
            correspondent à sampling=preferred.
    mk    : 'AR1' (défaut, robuste à l'autocorrélation d'ordre 1,
            fréquente sur les séries annuelles d'étiage ; Hamed & Rao
            1998), 'INDE' (test standard, hypothèse d'indépendance) ou
            'LTP' (mémoire longue, Hamed 2008).
    level : niveau de signification du test (défaut 0.1).
    series: true pour joindre sous 'series' les séries extraites sur
            lesquelles la tendance a été calculée (mêmes données
            garanties : tout vient du même calcul ; pratique pour
            tracer points + tendance sans second appel).
    stations_meta : true pour joindre les fiches du référentiel
            Hub'Eau des stations (cf. /v1/extract).
    Fiches acceptées : sorties de forme 'series' uniquement (la
    tendance d'un scalaire ou d'une courbe n'a pas de sens).
    """
    if orient not in ("records", "columns"):
        raise HTTPException(422, "orient : 'records' ou 'columns'")
    if mk not in ("INDE", "AR1", "LTP"):
        raise HTTPException(422, "mk : 'INDE', 'AR1' ou 'LTP'")
    _check_sampling(sampling)
    prio = usage.priority_of(request)
    st, cd = _parse_lists(stations, cards, prio)
    _check_cards_series(cd)
    ticket = _maybe_job(request, "trend", st, cd, prio, start=start,
                        end=end, sampling=sampling, mk=mk, level=level,
                        series=series or None,
                        stations_meta=stations_meta or None, orient=orient)
    if ticket is not None:
        return ticket

    res, empreintes = _run_extract(st, cd, start, end, sampling)
    with jobs.COMPUTE:
        try:
            tr = card.trend(res, level=level, dependency=mk,
                            seed=LTP_SEED)
        except ValueError as e:
            raise HTTPException(422, str(e))
    trends = {cid: serialize(df, orient) for cid, df in tr["data"].items()}

    usage.log_usage(request, "trend", stations=len(st), cards=cd, mk=mk)
    out = {
        **versions(),
        "rights": rights(),
        "stations": st,
        "cards": cd,
        "period": {"start": start, "end": end},
        "sampling": sampling,
        "mk": mk, "level": level,
        "source": SOURCE,
        "data_fetched_at": _fetched_at(st),
        "data_fingerprint": hubeau.combine_fingerprints(empreintes),
        "orient": orient,
        "meta": serialize(res["meta"]),
        "data": trends,
    }
    if series:
        out["series"] = {cid: serialize(df, orient)
                         for cid, df in res["data"].items()}
    if stations_meta:
        out["stations_meta"] = _stations_meta(st)
    return out


# ── Jobs : demandes massives en file de calcul ──────────────────────────────

class JobRequest(BaseModel):
    endpoint: str                        # "extract" | "trend"
    stations: str | list[str]
    cards: str | list[str]
    start: str | None = None
    end: str | None = None
    sampling: str | None = None
    mk: str = "AR1"
    level: float = 0.1
    series: bool = False                 # trend : joindre les séries extraites
    stations_meta: bool = False          # joindre le référentiel des stations
    orient: str = "records"


@app.post("/v1/jobs", status_code=202, tags=["jobs"],
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
    if req.endpoint not in ("extract", "trend"):
        raise HTTPException(422, "endpoint : 'extract' ou 'trend'")
    if req.orient not in ("records", "columns"):
        raise HTTPException(422, "orient : 'records' ou 'columns'")
    if req.mk not in ("INDE", "AR1", "LTP"):
        raise HTTPException(422, "mk : 'INDE', 'AR1' ou 'LTP'")
    if not (0 < req.level < 1):
        raise HTTPException(422, "level : dans (0, 1)")
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
    return _job_response(job)


@app.get("/v1/jobs", tags=["jobs"], dependencies=[Depends(usage.rate_light)])
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


@app.get("/v1/jobs/{job_id}", tags=["jobs"], dependencies=[Depends(usage.rate_light)])
def job_status(job_id: str, response: Response):
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
         dependencies=[Depends(usage.rate_light)])
def job_result(job_id: str):
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
            dependencies=[Depends(usage.rate_light)])
def job_delete(request: Request, job_id: str):
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


@app.get("/v1/health", tags=["service"])
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

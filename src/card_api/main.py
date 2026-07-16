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

import re
import shutil

import httpx
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
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
    CARD_VERSION = _pkg_version("card")
except Exception:                                    # dev, non installé
    CARD_VERSION = "dev"

app = FastAPI(
    title="card-api",
    version="0.1.0",
    description=(
        "Extraction de variables hydroclimatiques (fiches CARD) sur les "
        "données Hub'Eau. Service public de recherche (INRAE, UR RiverLy). "
        "Code GPL-3 : https://github.com/lou-heraut/card"
    ),
)
app.add_middleware(GZipMiddleware, minimum_size=1024)




@app.get("/v1/cards", dependencies=[Depends(usage.rate_light)])
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
        "card_version": CARD_VERSION,
        "count": int(len(df)),
        "cards": clean(df.head(limit).to_dict(orient="records")),
    }


@app.get("/v1/cards/{card_id}", dependencies=[Depends(usage.rate_light)])
def card_detail(card_id: str, lang: str = "fr"):
    """Détail d'une fiche : métadonnées complètes + classification."""
    if lang not in ("fr", "en"):
        raise HTTPException(422, "lang doit être 'fr' ou 'en'")
    try:
        meta = card.info(card_id, lang=lang)
    except FileNotFoundError:
        raise HTTPException(404, f"fiche inconnue : {card_id}")
    path = meta.pop("path", "")                      # chemin serveur interne
    if "src/card/cards/" in path:
        rel = path.split("src/card/cards/", 1)[1]
        meta["yaml"] = ("https://github.com/lou-heraut/card/blob/main/"
                        f"src/card/cards/{rel}")
    return {"card_version": CARD_VERSION, "lang": lang, "card": meta}


@app.get("/v1/stations", dependencies=[Depends(usage.rate_light)])
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
                          priority=-1 if prio else 0)
    except RuntimeError as e:
        raise HTTPException(503, str(e), headers={"Retry-After": "300"})
    extra = {"key": prio["name"]} if prio else {}
    usage.log_usage(request, "jobs", job=job["id"], target=endpoint,
                    stations=len(st), cards=cd, **extra)
    return _job_response(job)


def _check_sampling(sampling):
    if sampling is not None and not _SAMPLING_RE.match(sampling):
        raise HTTPException(
            422, f"sampling invalide : {sampling!r}. Valeurs acceptées : "
                 "'preferred' (fenêtre fixe déclarée par chaque fiche) "
                 "ou 'MM-JJ' (ex. '09-01')")


def _run_extract(st, cd, start, end, sampling=None):
    frames = []
    for s in st:
        try:
            df = hubeau.fetch_chronicle(s)
        except hubeau.StationInconnue as e:
            raise HTTPException(404, str(e))
        except hubeau.HubEauIndisponible as e:
            raise HTTPException(504, str(e), headers={"Retry-After": "300"})
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
            return card.extract(data, cards=cd, sampling_period=sampling,
                                verbose=False)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))


@app.get("/v1/extract", dependencies=[Depends(usage.rate_compute)])
def extract(request: Request, stations: str, cards: str,
            start: str | None = None, end: str | None = None,
            sampling: str | None = None,
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
    orient   : 'records' (défaut, liste d'objets, style Hub'Eau) ou
               'columns' (colonnaire : {colonne: [valeurs]}, compact).
    """
    if orient not in ("records", "columns"):
        raise HTTPException(422, "orient : 'records' ou 'columns'")
    _check_sampling(sampling)
    prio = usage.priority_of(request)
    st, cd = _parse_lists(stations, cards, prio)
    ticket = _maybe_job(request, "extract", st, cd, prio, start=start,
                        end=end, sampling=sampling, orient=orient)
    if ticket is not None:
        return ticket
    res = _run_extract(st, cd, start, end, sampling)

    extracted = res["data"]
    if not isinstance(extracted, dict):
        extracted = {cd[0]: extracted}
    data_out = {k: serialize(v, orient) for k, v in extracted.items()}
    usage.log_usage(request, "extract", stations=len(st), cards=cd)
    return {
        "card_version": CARD_VERSION,
        "stations": st,
        "cards": cd,
        "period": {"start": start, "end": end},
        "sampling": sampling,
        "source": SOURCE,
        "orient": orient,
        "meta": serialize(res["meta"]),
        "data": data_out,
    }


@app.get("/v1/trend", dependencies=[Depends(usage.rate_compute)])
def trend(request: Request, stations: str, cards: str,
          start: str | None = None, end: str | None = None,
          sampling: str | None = None,
          mk: str = "AR1", level: float = Query(0.1, gt=0, lt=1),
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
                        orient=orient)
    if ticket is not None:
        return ticket

    res = _run_extract(st, cd, start, end, sampling)
    with jobs.COMPUTE:
        try:
            tr = card.trend(res, level=level, dependency=mk)
        except ValueError as e:
            raise HTTPException(422, str(e))
    trends = {cid: serialize(df, orient) for cid, df in tr["data"].items()}

    usage.log_usage(request, "trend", stations=len(st), cards=cd, mk=mk)
    return {
        "card_version": CARD_VERSION,
        "stations": st,
        "cards": cd,
        "period": {"start": start, "end": end},
        "sampling": sampling,
        "mk": mk, "level": level,
        "source": SOURCE,
        "orient": orient,
        "meta": serialize(res["meta"]),
        "data": trends,
    }


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
    orient: str = "records"


@app.post("/v1/jobs", status_code=202,
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
    if req.endpoint == "trend":
        params.update(mk=req.mk, level=req.level)
    params["orient"] = req.orient
    try:
        job = jobs.submit(params,
                          user=usage.ip_hash(usage.client_ip(request)),
                          priority=-1 if prio else 0)
    except RuntimeError as e:
        raise HTTPException(503, str(e), headers={"Retry-After": "300"})
    extra = {"key": prio["name"]} if prio else {}
    usage.log_usage(request, "jobs", job=job["id"], target=req.endpoint,
                    stations=len(st), cards=cd, **extra)
    return _job_response(job)


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(usage.rate_light)])
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


@app.get("/v1/jobs/{job_id}/result",
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


@app.get("/v1/health")
def health():
    """Sonde de vie et charge (déploiement, supervision) : état de la
    file de calcul et du disque, lisible par n'importe quelle sonde."""
    du = shutil.disk_usage(hubeau.data_dir())
    return {
        "status": "ok",
        "card_version": CARD_VERSION,
        "jobs": jobs.queue_stats(),
        "disk": {"used_pct": round(du.used / du.total * 100, 1),
                 "free_gb": round(du.free / 1e9, 1)},
    }

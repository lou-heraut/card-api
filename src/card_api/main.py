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

import math
import re
import threading

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware

import card

from . import hubeau, usage

MAX_STATIONS = 10          # par requête publique (clés de priorité : plus tard)
MAX_CARDS = 20
_SAMPLING_RE = re.compile(r"^(preferred|\d{2}-\d{2})$")
_COMPUTE = threading.Semaphore(2)      # concurrence bornée des calculs


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


def _clean(records):
    """NaN -> null pour le JSON."""
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v)
             for k, v in r.items()} for r in records]


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
        "cards": _clean(df.head(limit).to_dict(orient="records")),
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
    return {"stations": hubeau.search_stations(libelle, code, departement, size)}


def _parse_lists(stations, cards):
    st = [s.strip() for s in stations.split(",") if s.strip()]
    cd = [c.strip() for c in cards.split(",") if c.strip()]
    if not (0 < len(st) <= MAX_STATIONS):
        raise HTTPException(422, f"1 à {MAX_STATIONS} stations par requête")
    if not (0 < len(cd) <= MAX_CARDS):
        raise HTTPException(422, f"1 à {MAX_CARDS} fiches par requête")
    meta_map = _card_meta_map()
    for c in cd:
        m = meta_map.get(c)
        if m is not None and m["input_vars"] != "Q":
            raise HTTPException(
                422, f"la fiche {c} requiert {m['input_vars']} : ce service "
                     "ne fournit que des débits journaliers (Q, Hub'Eau)")
    return st, cd


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
        if start:
            df = df[df["date"] >= start]
        if end:
            df = df[df["date"] <= end]
        if df.empty:
            raise HTTPException(404, f"{s}: aucune donnée sur la période")
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)
    with _COMPUTE:
        try:
            return card.extract(data, cards=cd, sampling_period=sampling,
                                verbose=False)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))


def _serialize(df, orient="records"):
    """records (défaut, style Hub'Eau) ou columns (colonnaire, compact,
    rechargeable en DataFrame d'une ligne)."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    out = out.astype(object).where(out.notna(), None)
    if orient == "columns":
        return {c: out[c].tolist() for c in out.columns}
    return _clean(out.to_dict(orient="records"))


@app.get("/v1/extract", dependencies=[Depends(usage.rate_compute)])
def extract(request: Request, stations: str, cards: str,
            start: str | None = None, end: str | None = None,
            sampling: str | None = None,
            orient: str = "records"):
    """Extrait des variables CARD sur des chroniques Hub'Eau.

    stations : codes séparés par des virgules (max 10).
    cards    : ids de fiches séparés par des virgules (max 20) ;
               fiches à entrée Q uniquement (données hydrométriques).
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
    st, cd = _parse_lists(stations, cards)
    res = _run_extract(st, cd, start, end, sampling)

    extracted = res["data"]
    if not isinstance(extracted, dict):
        extracted = {cd[0]: extracted}
    data_out = {k: _serialize(v, orient) for k, v in extracted.items()}
    usage.log_usage(request, "extract", stations=len(st), cards=cd)
    return {
        "card_version": CARD_VERSION,
        "stations": st,
        "cards": cd,
        "period": {"start": start, "end": end},
        "sampling": sampling,
        "source": "Hub'Eau hydrométrie (eaufrance, Licence Ouverte), QmnJ en m³/s",
        "orient": orient,
        "meta": _serialize(res["meta"]),
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
    st, cd = _parse_lists(stations, cards)
    meta_map = _card_meta_map()
    for c in cd:
        m = meta_map.get(c)
        if m is not None and m["output"] != "series":
            raise HTTPException(
                422, f"la fiche {c} produit un résultat '{m['output']}' : "
                     "la tendance ne s'applique qu'aux fiches 'series'")

    res = _run_extract(st, cd, start, end, sampling)
    with _COMPUTE:
        try:
            tr = card.trend(res, level=level, dependency=mk)
        except ValueError as e:
            raise HTTPException(422, str(e))
    trends = {cid: _serialize(df, orient) for cid, df in tr["data"].items()}

    usage.log_usage(request, "trend", stations=len(st), cards=cd, mk=mk)
    return {
        "card_version": CARD_VERSION,
        "stations": st,
        "cards": cd,
        "period": {"start": start, "end": end},
        "sampling": sampling,
        "mk": mk, "level": level,
        "source": "Hub'Eau hydrométrie (eaufrance, Licence Ouverte), QmnJ en m³/s",
        "orient": orient,
        "meta": _serialize(res["meta"]),
        "data": trends,
    }


@app.get("/v1/health")
def health():
    """Sonde de vie (déploiement, supervision)."""
    return {"status": "ok", "card_version": CARD_VERSION}

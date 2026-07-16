# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""card-api — service web des fiches CARD (v1).

Étape 1 (docs/dev/API.md du repo card) : découverte du catalogue,
sans réseau ni calcul. Les endpoints d'extraction (Hub'Eau) viennent
aux étapes suivantes.
"""

import math
import threading

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware

import card

from . import hubeau

MAX_STATIONS = 10          # par requête publique (clés de priorité : plus tard)
MAX_CARDS = 20
_COMPUTE = threading.Semaphore(2)      # concurrence bornée des calculs


def _input_vars_map():
    """{id de fiche: input_vars} — calculé une fois au premier appel.
    Sert à refuser explicitement les fiches non-débit sur les données
    Hub'Eau (l'affectation automatique de colonnes de la bibliothèque
    mapperait sinon Q sur n'importe quelle variable requise unique)."""
    global _INPUTS
    try:
        return _INPUTS
    except NameError:
        from pathlib import Path
        df = card.list_cards()
        _INPUTS = {Path(p).stem: iv
                   for p, iv in zip(df["script_path"], df["input_vars"])}
        return _INPUTS

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
        "données Hub'Eau. Service public de recherche — INRAE, UR RiverLy. "
        "Code GPL-3 : https://github.com/lou-heraut/card"
    ),
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


def _clean(records):
    """NaN -> null pour le JSON."""
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v)
             for k, v in r.items()} for r in records]


@app.get("/v1/cards")
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
    de classification, dans les deux langues — mêmes filtres que
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


@app.get("/v1/cards/{card_id}")
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


@app.get("/v1/stations")
def stations(libelle: str | None = None, code: str | None = None,
             departement: str | None = None, size: int = Query(20, le=100)):
    """Recherche de stations hydrométriques (référentiel Hub'Eau).
    Utile aussi pour retrouver les nouveaux codes : depuis la refonte
    Hydro, les anciens codes Banque Hydro ne sont plus valides."""
    if not any((libelle, code, departement)):
        raise HTTPException(422, "donner au moins libelle, code ou departement")
    return {"stations": hubeau.search_stations(libelle, code, departement, size)}


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


@app.get("/v1/extract")
def extract(stations: str, cards: str,
            start: str | None = None, end: str | None = None,
            orient: str = "records"):
    """Extrait des variables CARD sur des chroniques Hub'Eau.

    stations : codes séparés par des virgules (max 10).
    cards    : ids de fiches séparés par des virgules (max 20) —
               fiches à entrée Q uniquement (données hydrométriques).
    start/end: bornes AAAA-MM-JJ optionnelles (défaut : tout).
    orient   : 'records' (défaut, liste d'objets, style Hub'Eau) ou
               'columns' (colonnaire : {colonne: [valeurs]}, compact).
    """
    if orient not in ("records", "columns"):
        raise HTTPException(422, "orient : 'records' ou 'columns'")
    st = [s.strip() for s in stations.split(",") if s.strip()]
    cd = [c.strip() for c in cards.split(",") if c.strip()]
    if not (0 < len(st) <= MAX_STATIONS):
        raise HTTPException(422, f"1 à {MAX_STATIONS} stations par requête")
    if not (0 < len(cd) <= MAX_CARDS):
        raise HTTPException(422, f"1 à {MAX_CARDS} fiches par requête")
    inputs = _input_vars_map()
    for c in cd:
        iv = inputs.get(c)
        if iv is not None and iv != "Q":
            raise HTTPException(
                422, f"la fiche {c} requiert {iv} : ce service ne fournit "
                     "que des débits journaliers (Q, Hub'Eau hydrométrie)")

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
            res = card.extract(data, cards=cd, verbose=False)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))

    dataEX = res["dataEX"]
    if isinstance(dataEX, dict):
        data_out = {k: _serialize(v, orient) for k, v in dataEX.items()}
    else:
        data_out = {cd[0]: _serialize(dataEX, orient)}
    return {
        "card_version": CARD_VERSION,
        "stations": st,
        "cards": cd,
        "period": {"start": start, "end": end},
        "source": "Hub'Eau hydrométrie (eaufrance, Licence Ouverte), QmnJ en m³/s",
        "orient": orient,
        "metaEX": _serialize(res["metaEX"]),
        "dataEX": data_out,
    }


@app.get("/v1/health")
def health():
    """Sonde de vie (déploiement, supervision)."""
    return {"status": "ok", "card_version": CARD_VERSION}

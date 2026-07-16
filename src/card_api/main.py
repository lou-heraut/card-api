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

from fastapi import FastAPI, HTTPException, Query

import card

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


@app.get("/v1/health")
def health():
    """Sonde de vie (déploiement, supervision)."""
    return {"status": "ok", "card_version": CARD_VERSION}

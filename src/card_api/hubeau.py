# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Client Hub'Eau hydrométrie (API v2) avec cache local des chroniques.

Points vérifiés sur l'API réelle (2026-07-16) :
- endpoint obs_elab v2, grandeur QmnJ (débit moyen journalier) ;
- resultat_obs_elab est en L/s -> conversion en m3/s ;
- pagination par l'URL `next` ;
- depuis la refonte Hydro, les codes station ont changé (H5920010 ->
  F700000103) : le référentiel sert à retrouver les nouveaux codes.
"""

import os
import re
import time
from pathlib import Path

import httpx
import pandas as pd

BASE = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"
PAGE_SIZE = 20000
CACHE_TTL = 24 * 3600                    # les séries validées bougent peu
_STATION_RE = re.compile(r"^[A-Za-z0-9]{4,12}$")


def data_dir() -> Path:
    d = Path(os.environ.get("CARD_API_DATA", "./data"))
    (d / "chroniques").mkdir(parents=True, exist_ok=True)
    return d


class StationInconnue(ValueError):
    pass


def _fetch_all(url, params):
    """Suit la pagination `next` de Hub'Eau, renvoie la liste des lignes."""
    rows = []
    with httpx.Client(timeout=60) as client:
        r = client.get(url, params=params)
        while True:
            r.raise_for_status()
            payload = r.json()
            rows.extend(payload.get("data") or [])
            nxt = payload.get("next")
            if not nxt:
                return rows
            r = client.get(nxt)


def fetch_chronicle(station: str, refresh: bool = False) -> pd.DataFrame:
    """Chronique journalière complète (id, date, Q en m3/s) d'une station,
    téléchargée puis mise en cache local (TTL 24 h)."""
    if not _STATION_RE.match(station):
        raise StationInconnue(f"code de station invalide : {station!r}")
    cache = data_dir() / "chroniques" / f"{station}.csv.gz"
    if not refresh and cache.exists() \
            and time.time() - cache.stat().st_mtime < CACHE_TTL:
        return pd.read_csv(cache, parse_dates=["date"])

    rows = _fetch_all(f"{BASE}/obs_elab", {
        "code_entite": station,
        "grandeur_hydro_elab": "QmnJ",
        "size": PAGE_SIZE,
        "sort": "asc",
        "fields": "code_station,date_obs_elab,resultat_obs_elab",
    })
    if not rows:
        raise StationInconnue(
            f"aucune chronique QmnJ pour {station!r} — les codes ont changé "
            "depuis la refonte Hydro, cherchez le nouveau code via "
            "/v1/stations"
        )
    df = pd.DataFrame({
        "id": station,
        "date": pd.to_datetime([r["date_obs_elab"] for r in rows]),
        "Q": [r["resultat_obs_elab"] / 1000.0        # L/s -> m3/s
              if r["resultat_obs_elab"] is not None else float("nan")
              for r in rows],
    }).sort_values("date").reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def search_stations(libelle=None, code=None, departement=None, size=20):
    """Recherche dans le référentiel des stations hydrométriques."""
    params = {"size": min(int(size), 100),
              "fields": ("code_station,libelle_station,code_departement,"
                         "en_service,date_ouverture_station,"
                         "longitude_station,latitude_station")}
    if libelle:
        params["libelle_station"] = libelle
    if code:
        params["code_station"] = code
    if departement:
        params["code_departement"] = departement
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{BASE}/referentiel/stations", params=params)
        r.raise_for_status()
        return r.json().get("data") or []

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
import datetime as dt
import hashlib
import time
from pathlib import Path

import httpx
import pandas as pd

BASE = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"
PAGE_SIZE = 20000
# L'empreinte hache AUSSI le nom des colonnes : renommer une colonne la
# change, sur une donnée pourtant identique. C'est le cas prévu par ce
# préfixe. Il n'a pas été incrémenté au renommage `id` → `code_station`
# du 2026-07-28, DÉLIBÉRÉMENT : aucune empreinte n'avait encore été
# publiée à qui que ce soit, donc il n'y avait rien à départager, et
# brûler un numéro sur un changement que personne ne peut observer aurait
# affaibli le signal pour le jour où il servira vraiment.
FINGERPRINT_VERSION = "v1"               # cf. fingerprint()
CACHE_TTL = 24 * 3600                    # les séries validées bougent peu
_STATION_RE = re.compile(r"^[A-Za-z0-9]{4,12}$")


def data_dir() -> Path:
    d = Path(os.environ.get("CARD_API_DATA", "./data"))
    (d / "chroniques").mkdir(parents=True, exist_ok=True)
    return d


class StationInconnue(ValueError):
    pass


class SiteAmbigu(ValueError):
    """Le code demandé donne plusieurs mesures concurrentes pour un même
    jour : c'est un code de SITE dont plusieurs stations mesurent en
    parallèle. Il n'y a pas de doublon à écarter, ce sont des mesures
    réelles et différentes ; choisir laquelle serait un arbitrage
    hydrologique, et le service n'a pas à le prendre à la place de qui
    l'interroge."""


class HubEauIndisponible(RuntimeError):
    """Hub'Eau ne répond pas (timeout ou 5xx persistant après retries)."""


def _get_retry(client, url, params=None, attempts=3):
    """GET avec réessais sur timeout/erreur réseau/5xx (Hub'Eau traîne
    parfois) : pause croissante, puis erreur propre plutôt qu'un
    timeout brut qui remonterait en 500."""
    last = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * attempt)
        try:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            last = exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
    raise HubEauIndisponible(
        f"Hub'Eau ne répond pas ({type(last).__name__}) : "
        "réessayez dans quelques minutes"
    )


def _fetch_all(url, params):
    """Suit la pagination `next` de Hub'Eau, renvoie la liste des lignes."""
    rows = []
    with httpx.Client(timeout=60) as client:
        r = _get_retry(client, url, params)
        while True:
            payload = r.json()
            rows.extend(payload.get("data") or [])
            nxt = payload.get("next")
            if not nxt:
                return rows
            r = _get_retry(client, nxt)


def fingerprint(df: pd.DataFrame) -> str:
    """Empreinte de la donnée d'une chronique.

    Répond à une question et une seule : deux résultats reposent-ils sur
    la même donnée ? Hub'Eau révise ses chroniques, et sans empreinte un
    écart entre deux calculs ne se distingue pas d'un changement de code.

    Calculée sur les octets bruts des colonnes (dates en entiers, valeurs
    en flottants), et non sur le fichier de cache : gzip inscrit un
    horodatage dans son en-tête, donc deux compressions d'une même donnée
    donnent des octets différents. Passer par les tableaux rend aussi
    l'empreinte indépendante du format CSV et des versions de pandas.

    Sur la chronique ENTIÈRE, avant tout filtre de période : la période
    demandée est déjà dans la provenance, et ce qu'on veut identifier
    ici, c'est la source.

    Préfixée par la version de l'algorithme. Cette empreinte est un jeton
    de COMPARAISON, pas une somme de contrôle recalculable de l'extérieur:
    deux valeurs se comparent, elles ne se vérifient pas. Si le calcul
    change un jour, le préfixe change avec lui, et personne ne comparera
    par erreur deux empreintes issues d'algorithmes différents.
    """
    h = hashlib.sha256()
    for col in sorted(df.columns):
        s = df[col]
        h.update(col.encode())
        if pd.api.types.is_datetime64_any_dtype(s):
            h.update(s.to_numpy(dtype="datetime64[ns]").astype("int64").tobytes())
        elif pd.api.types.is_numeric_dtype(s):
            h.update(s.to_numpy(dtype="float64").tobytes())
        else:
            h.update(s.astype(str).str.cat(sep="\x1f").encode())
    return f"{FINGERPRINT_VERSION}:{h.hexdigest()}"


def combine_fingerprints(par_station: dict) -> str:
    """Empreinte d'un lot de chroniques, indépendante de l'ordre de
    demande : c'est l'ensemble des données qui compte, pas la façon dont
    on l'a listé."""
    h = hashlib.sha256()
    for station in sorted(par_station):
        h.update(f"{station}:{par_station[station]}\n".encode())
    return f"{FINGERPRINT_VERSION}:{h.hexdigest()}"


def chronicle_fetched_at(station: str) -> str | None:
    """Date de récupération RÉELLE de la chronique en cache (UTC ISO).

    Hub'Eau révise ses données : deux appels identiques à quelques
    semaines d'écart ne donnent pas les mêmes nombres. Un résultat doit
    donc dire quand la donnée a été lue, et pas quand le calcul a
    tourné : avec un cache de 24 h, les deux diffèrent d'autant.
    """
    cache = data_dir() / "chroniques" / f"{station}.csv.gz"
    if not cache.exists():
        return None
    return (dt.datetime.fromtimestamp(cache.stat().st_mtime, dt.timezone.utc)
            .replace(microsecond=0).isoformat())


def fetch_chronicle(station: str, refresh: bool = False) -> pd.DataFrame:
    """Chronique journalière complète (id, date, Q en m3/s) d'une station,
    téléchargée puis mise en cache local (TTL 24 h)."""
    if not _STATION_RE.match(station):
        raise StationInconnue(f"code de station invalide : {station!r}")
    cache = data_dir() / "chroniques" / f"{station}.csv.gz"
    if not refresh and cache.exists() \
            and time.time() - cache.stat().st_mtime < CACHE_TTL:
        # dtype id : un code tout-numérique relu en int64 ne serait plus
        # détecté comme identifiant de série (détection par type)
        return pd.read_csv(cache, parse_dates=["date"],
                           dtype={"code_station": str})

    rows = _fetch_all(f"{BASE}/obs_elab", {
        "code_entite": station,
        "grandeur_hydro_elab": "QmnJ",
        "size": PAGE_SIZE,
        "sort": "asc",
        "fields": "code_station,date_obs_elab,resultat_obs_elab",
    })
    if not rows:
        raise StationInconnue(
            f"aucune chronique QmnJ pour {station!r} : les codes ont changé "
            "depuis la refonte Hydro, cherchez le nouveau code via "
            "/v1/stations"
        )
    # Hub'Eau sert DEUX FOIS la même mesure quand le code demandé est un
    # code de SITE : une ligne étiquetée avec la station qui l'a produite,
    # une ligne sans étiquette de station. Vérifié sur K0114020 et
    # K0018723 : à une date donnée, les deux lignes ne diffèrent que par
    # `code_station` (rempli / vide) et par leur `date_prod` ; la valeur
    # est identique, sur 365 jours comparés, zéro écart.
    #
    # Ce n'est donc pas un choix entre deux séries, c'est un doublon. Non
    # filtré, il faisait échouer toute demande sur un code de site avec un
    # 422 « dates dupliquées » venu de card, dont le message conseillait
    # un paramètre Python inaccessible depuis HTTP. Or les anciens codes
    # Banque Hydro SONT des codes de site : la panne visait exactement les
    # gens que /v1/stations doit dépanner.
    #
    # Repli si le filtre ne laisse rien : mieux vaut la chronique telle
    # quelle qu'une station soudainement introuvable.
    etiquetees = [r for r in rows if r.get("code_station")]
    if etiquetees:
        rows = etiquetees
    df = pd.DataFrame({
        "code_station": station,
        "date": pd.to_datetime([r["date_obs_elab"] for r in rows]),
        "Q": [r["resultat_obs_elab"] / 1000.0        # L/s -> m3/s
              if r["resultat_obs_elab"] is not None else float("nan")
              for r in rows],
    }).sort_values("date").reset_index(drop=True)
    # Deux mesures pour un même jour APRÈS le filtre ci-dessus : ce n'est
    # plus le doublon site/station, ce sont deux stations du site qui
    # mesurent en parallèle et ne disent pas la même chose. On refuse en
    # nommant les stations, plutôt que de laisser card échouer plus loin
    # sur un message qui parle de paramètres Python.
    #
    # Des stations qui se SUCCÈDENT dans le temps ne déclenchent rien :
    # elles forment un enregistrement continu du même point, ce qui est
    # précisément ce qu'un site désigne.
    if df.duplicated(subset=["date"]).any():
        jours = df.loc[df.duplicated(subset=["date"], keep=False), "date"]
        stations = sorted({r["code_station"] for r in rows
                           if r.get("code_station")})
        raise SiteAmbigu(
            f"{station} est un code de site dont plusieurs stations "
            f"mesurent en parallèle ({', '.join(stations)}) : "
            f"{jours.nunique()} jours portent des valeurs différentes "
            f"selon la station, du {jours.min():%Y-%m-%d} au "
            f"{jours.max():%Y-%m-%d}. Choisir pour vous serait un "
            f"arbitrage. Donnez un code de station : "
            f"/v1/stations?code={station}")
    df.to_csv(cache, index=False)
    return df


def stations_referential(codes: list[str]) -> list[dict]:
    """Fiches du référentiel (libellé, position...) d'une liste de
    codes, par paquets de 100 (plafond de taille Hub'Eau)."""
    out = []
    for i in range(0, len(codes), 100):
        out += search_stations(code=",".join(codes[i:i + 100]), size=100)
    return out


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

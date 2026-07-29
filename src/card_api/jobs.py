# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""File de calcul asynchrone (motif job, forme OGC API Processes).

Les demandes trop grosses pour une réponse synchrone reçoivent un
ticket : 202 + Location, puis GET /v1/jobs/{id} (statut, progression)
et GET /v1/jobs/{id}/result (résultat gelé, bloc de provenance
inclus). Les jobs sont PUBLICS, sans clé, comme le reste du service ;
une clé de priorité met en tête de file, relève les plafonds et
permet de lister ses propres jobs (le job garde le PRÉFIXE du jeton,
jamais le jeton ni le nom).

Mécanique v1 (pas de Redis) : file en mémoire bornée + threads
workers, stockage dans $CARD_API_DATA/jobs/{id}/ (job.json +
result.json.gz), purge TTL. Au redémarrage, les jobs en attente sont
remis en file, ceux qui étaient en cours sont marqués failed.
"""

import gzip
import itertools
import json
import os
import queue
import secrets
import shutil
import threading
import time
from datetime import datetime, timezone

import pandas as pd

from . import hubeau, usage

# Plafonds et réglages d'exploitation (surchager dans .env)
# DEUX seuils de stations, parce que deux coûts très différents se
# cachaient derrière un seul compteur. Mesuré le 2026-07-29 en
# production : télécharger une chronique coûte ~1,2 s, la calculer ~0,04 s,
# soit trente fois moins. Un même nombre de stations vaut donc 24 s à
# froid et 1 s à chaud, et un seuil unique tranchait au mauvais endroit :
# 20 stations déjà en cache partaient en file, avec ticket et aller-retour,
# pour économiser une seconde.
#
# SYNC_STATIONS s'applique aux stations À TÉLÉCHARGER : bas, il borne la
# durée d'une réponse immédiate. SYNC_STATIONS_CACHED s'applique au total :
# haut, il empêche qu'une demande de 500 stations toutes en cache
# monopolise un worker, le calcul restant petit mais pas nul.
SYNC_STATIONS = int(os.environ.get("CARD_API_SYNC_STATIONS", 10))
SYNC_STATIONS_CACHED = int(os.environ.get("CARD_API_SYNC_STATIONS_CACHED", 60))
SYNC_CARDS = int(os.environ.get("CARD_API_SYNC_CARDS", 20))
JOB_STATIONS = int(os.environ.get("CARD_API_JOB_STATIONS", 100))
JOB_CARDS = int(os.environ.get("CARD_API_JOB_CARDS", 50))
JOB_TTL_DAYS = float(os.environ.get("CARD_API_JOB_TTL_DAYS", 7))
JOB_QUEUE_MAX = int(os.environ.get("CARD_API_JOB_QUEUE_MAX", 100))
# Plafonds des porteurs de clé de priorité (tête de file en sus).
#
# **0 vaut SANS LIMITE**, et c'est le défaut pour les fiches. Le défaut
# était 226, c'est-à-dire la taille du corpus au jour où il a été écrit :
# il voulait dire « toutes les fiches » mais redevenait un vrai plafond
# dès que card gagnait une fiche, sans que personne ne l'ait décidé et
# sans que rien ne le signale. Un plafond doit être un choix, pas une
# coïncidence avec une donnée qui bouge ailleurs.
PRIORITY_STATIONS = int(os.environ.get("CARD_API_PRIORITY_STATIONS", 1000))
PRIORITY_CARDS = int(os.environ.get("CARD_API_PRIORITY_CARDS", 0))
WORKERS = 2

# Concurrence de calcul bornée, partagée entre synchrone et jobs
COMPUTE = threading.Semaphore(2)

_queue: queue.PriorityQueue = queue.PriorityQueue()
_seq = itertools.count()
_workers_started = False
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jobs_dir():
    d = hubeau.data_dir() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_json(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load(job_id: str) -> dict | None:
    p = jobs_dir() / job_id / "job.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _save(job: dict):
    _write_json(jobs_dir() / job["id"] / "job.json", job)


def result_bytes(job_id: str) -> bytes | None:
    """Résultat JSON (décompressé) d'un job terminé, None sinon."""
    p = jobs_dir() / job_id / "result.json.gz"
    if not p.exists():
        return None
    return gzip.decompress(p.read_bytes())


def queue_stats() -> dict:
    """Instantané de la file pour /v1/health et le tableau de bord."""
    queued = running = 0
    for d in jobs_dir().iterdir():
        job = load(d.name)
        if job is None:
            continue
        if job["status"] == "queued":
            queued += 1
        elif job["status"] == "running":
            running += 1
    return {"queued": queued, "running": running}


def submit(params: dict, user: str, priority: int = 0,
           key: str | None = None) -> dict:
    """Crée le job sur disque et le met en file. `key` = préfixe du
    jeton de priorité (identifiant pseudonyme, pour GET /v1/jobs).
    RuntimeError si la file est pleine (le service protège sa VM au
    lieu d'accumuler)."""
    ensure_workers()
    purge_expired()
    if _queue.qsize() >= JOB_QUEUE_MAX:
        raise RuntimeError(
            f"file de calcul pleine ({JOB_QUEUE_MAX} jobs en attente) : "
            "réessayez plus tard"
        )
    job_id = secrets.token_hex(8)
    job = {
        "id": job_id,
        "status": "queued",
        "params": params,
        "user": user,
        "key": key,
        "priority": priority,
        "created": _now(),
        "started": None,
        "finished": None,
        "progress": {"done": 0, "total": len(params["stations"]),
                     "phase": "en file"},
        "error": None,
    }
    (jobs_dir() / job_id).mkdir()
    _save(job)
    _queue.put((priority, next(_seq), job_id))
    return job


def list_for(prefix: str) -> list[dict]:
    """Jobs déposés avec la clé de ce préfixe, du plus récent au plus
    ancien (résumé sans les tickets d'autrui : GET /v1/jobs)."""
    out = []
    for d in jobs_dir().iterdir():
        job = load(d.name)
        if job is None or job.get("key") != prefix:
            continue
        p = job["params"]
        out.append({
            "job": job["id"],
            "status": job["status"],
            "created": job["created"],
            "finished": job["finished"],
            "endpoint": p["endpoint"],
            "stations": len(p["stations"]),
            "cards": p["cards"],
            "status_url": f"/v1/jobs/{job['id']}",
            "result_url": f"/v1/jobs/{job['id']}/result",
        })
    return sorted(out, key=lambda j: j["created"], reverse=True)


def delete(job_id: str):
    """Supprime un job et son résultat (dismiss). Un job en file ainsi
    supprimé est simplement sauté par le worker (load -> None)."""
    shutil.rmtree(jobs_dir() / job_id, ignore_errors=True)


def purge_expired():
    """Supprime les jobs plus vieux que JOB_TTL_DAYS."""
    limit = time.time() - JOB_TTL_DAYS * 86400
    for d in jobs_dir().iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def ensure_workers():
    """Démarre les threads workers (une fois) et récupère les jobs
    laissés par un précédent processus."""
    global _workers_started
    with _lock:
        if _workers_started:
            return
        _workers_started = True
        for d in sorted(jobs_dir().iterdir()):
            job = load(d.name)
            if job is None:
                continue
            if job["status"] == "queued":
                _queue.put((job.get("priority", 0), next(_seq), job["id"]))
            elif job["status"] == "running":
                job.update(status="failed", finished=_now(),
                           error="interrompu par un redémarrage du service")
                _save(job)
        for _ in range(WORKERS):
            threading.Thread(target=_worker, daemon=True).start()


def _worker():
    while True:
        _, _, job_id = _queue.get()
        job = load(job_id)
        if job is None or job["status"] != "queued":
            continue
        job.update(status="running", started=_now())
        _save(job)

        def progress(done, total, phase, _job=job):
            _job["progress"] = {"done": done, "total": total, "phase": phase}
            _save(_job)

        t0 = time.time()
        try:
            payload = _execute(job, progress)
            raw = json.dumps(payload, ensure_ascii=False).encode()
            (jobs_dir() / job_id / "result.json.gz").write_bytes(
                gzip.compress(raw))
            job.update(status="done", finished=_now())
        except Exception as exc:
            job.update(status="failed", finished=_now(),
                       error=f"{type(exc).__name__}: {exc}")
        _save(job)
        _wait = (pd.Timestamp(job["started"])
                 - pd.Timestamp(job["created"])).total_seconds()
        usage.log_event(
            "job_done", job=job_id, status=job["status"],
            endpoint=job["params"]["endpoint"],
            stations=len(job["params"]["stations"]),
            cards=job["params"]["cards"],
            wait_s=round(_wait, 1), run_s=round(time.time() - t0, 1),
        )


def _execute(job: dict, progress) -> dict:
    """Exécute un job extract ou trend.

    Ce corps réimplémentait la chaîne des endpoints synchrones, pour la
    seule raison d'afficher la progression. Toute correction faite d'un
    côté n'atteignait donc pas l'autre : le 2026-07-29, les stations sans
    série ont cessé d'être fatales en synchrone et sont restées fatales
    ici. La progression est devenue un PARAMÈTRE de la chaîne partagée
    (`pipeline.compute`), et il ne reste dans cette fonction que ce qui
    distingue vraiment un job d'une réponse immédiate.
    """
    from . import pipeline

    # RENORMALISÉ, même si la demande l'était déjà. Les paramètres gelés
    # sont écrits sans leurs valeurs nulles, pour que le ticket reste
    # lisible : `end` absent n'est pas `end: null`. Le worker doit donc
    # les recompléter, et `normalise` étant idempotent, c'est aussi ce qui
    # garantit qu'un job déposé avant un changement de défaut sera exécuté
    # avec les mêmes règles qu'une demande immédiate d'aujourd'hui.
    p = pipeline.normalise(job["params"])
    total = len(p["stations"])
    brut = pipeline.compute(p, progress=progress, verrou=COMPUTE)
    out = pipeline.sans_prives(brut)

    # Ce qu'un job a de plus, et pourquoi. Un résultat de job est un
    # artefact GELÉ, qu'on archive et qu'on cite : la verbosité y est
    # utile là où elle alourdirait une réponse immédiate. C'est la seule
    # divergence légitime entre les deux portes, et les tests la listent
    # nommément (PROPRES_AU_JOB) pour qu'aucune autre ne s'y glisse.
    out["job"] = {
        "id": job["id"],
        "created": job["created"],
        # Date de LECTURE des chroniques, pas du calcul : avec un cache de
        # 24 h les deux diffèrent d'autant, et c'est la première qui compte
        # puisque Hub'Eau révise ses données.
        "data_fetched_at": out["data_fetched_at"],
        "params": {k: v for k, v in p.items() if v is not None},
    }
    out["data_fingerprints"] = brut["_empreintes"]
    out["ltp_seed"] = pipeline.LTP_SEED if p.get("mk") == "LTP" else None
    if p.get("stations_meta"):
        progress(total, total, "référentiel stations")
        out["stations_meta"] = hubeau.stations_referential(p["stations"])
    return out

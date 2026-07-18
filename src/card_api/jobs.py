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
from .serialize import serialize

# Plafonds et réglages d'exploitation (surchager dans .env)
SYNC_STATIONS = int(os.environ.get("CARD_API_SYNC_STATIONS", 10))
SYNC_CARDS = int(os.environ.get("CARD_API_SYNC_CARDS", 20))
JOB_STATIONS = int(os.environ.get("CARD_API_JOB_STATIONS", 100))
JOB_CARDS = int(os.environ.get("CARD_API_JOB_CARDS", 50))
JOB_TTL_DAYS = float(os.environ.get("CARD_API_JOB_TTL_DAYS", 7))
JOB_QUEUE_MAX = int(os.environ.get("CARD_API_JOB_QUEUE_MAX", 100))
# Plafonds des porteurs de clé de priorité (tête de file en sus)
PRIORITY_STATIONS = int(os.environ.get("CARD_API_PRIORITY_STATIONS", 1000))
PRIORITY_CARDS = int(os.environ.get("CARD_API_PRIORITY_CARDS", 226))
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
    """Exécute un job extract ou trend. Même chaîne que les endpoints
    synchrones, avec progression par station."""
    import card

    p = job["params"]
    frames = []
    total = len(p["stations"])
    for i, s in enumerate(p["stations"]):
        progress(i, total, f"chronique {s}")
        df = hubeau.fetch_chronicle(s)
        if p.get("start"):
            df = df[df["date"] >= p["start"]]
        if p.get("end"):
            df = df[df["date"] <= p["end"]]
        if df.empty:
            raise ValueError(f"{s}: aucune donnée sur la période")
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)
    fetched_at = _now()

    with COMPUTE:
        progress(total, total, "extraction")
        res = card.extract(data, cards=p["cards"],
                           sampling_period=p.get("sampling"), verbose=False)
        extracted = res["data"]
        if p["endpoint"] == "trend":
            progress(total, total, "tendance")
            tr = card.trend(res, level=p.get("level", 0.1),
                            dependency=p.get("mk", "AR1"))
            res = {"data": tr["data"], "meta": res["meta"]}

    orient = p.get("orient", "records")
    from .main import CARD_VERSION, SOURCE
    out = {
        "job": {
            "id": job["id"],
            "created": job["created"],
            "data_fetched_at": fetched_at,
            "params": {k: v for k, v in p.items() if v is not None},
        },
        "card_version": CARD_VERSION,
        "stations": p["stations"],
        "cards": p["cards"],
        "period": {"start": p.get("start"), "end": p.get("end")},
        "sampling": p.get("sampling"),
        "source": SOURCE,
        "orient": orient,
        "meta": serialize(res["meta"]),
        "data": {k: serialize(v, orient) for k, v in res["data"].items()},
    }
    if p["endpoint"] == "trend":
        out["mk"] = p.get("mk", "AR1")
        out["level"] = p.get("level", 0.1)
        if p.get("series"):
            out["series"] = {k: serialize(v, orient)
                             for k, v in extracted.items()}
    return out

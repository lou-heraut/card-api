# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Quotas par IP et journal d'usage anonymisé.

Quota : fenêtre glissante de 60 s par adresse IP, en mémoire (pas de
Redis en v1). En dépassement : 429 + Retry-After.

Journal : une ligne JSON par requête de calcul dans
$CARD_API_DATA/usage.jsonl ; l'IP n'est jamais écrite, seul un hachage
salé (sel = $CARD_API_SALT, sinon aléatoire au démarrage) permet de
compter les utilisateurs distincts sans pouvoir les identifier. Même
principe pour les clés de priorité : le journal reçoit le préfixe du
jeton, jamais le nom (pseudonyme ; le lien préfixe-nom ne vit que
dans keys.json et disparaît à la révocation).
"""

import hashlib
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from . import keys as keys_mod
from .hubeau import data_dir

WINDOW = 60.0                                   # secondes
RATE_COMPUTE = int(os.environ.get("CARD_API_RATE_COMPUTE", 10))
RATE_LIGHT = int(os.environ.get("CARD_API_RATE_LIGHT", 60))

_SALT = os.environ.get("CARD_API_SALT") or secrets.token_hex(8)
_hits: dict = defaultdict(deque)
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    """IP réelle derrière le reverse proxy (Caddy pose X-Forwarded-For)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def ip_hash(ip: str) -> str:
    return hashlib.sha256((_SALT + ip).encode()).hexdigest()[:12]


def priority_of(request: Request) -> dict | None:
    """Clé de priorité de la requête (en-tête X-API-Key ou paramètre
    key=). None sans clé ; 401 explicite si la clé est inconnue (mieux
    qu'une dégradation silencieuse en trafic public). Retourne
    {prefix, name, created} ; seul le préfixe circule ensuite
    (journal, jobs), jamais le nom ni le jeton."""
    token = (request.headers.get("x-api-key")
             or request.query_params.get("key"))
    if not token:
        return None
    info = keys_mod.lookup(token)
    if info is None:
        raise HTTPException(
            401, "clé de priorité inconnue (révoquée ?) : retirez-la "
                 "pour un accès public, ou demandez-en une nouvelle")
    return info


def check_rate(request: Request, limit: int):
    """Fenêtre glissante : au plus `limit` requêtes par IP et par minute."""
    ip = client_ip(request)
    now = time.time()
    with _lock:
        q = _hits[ip]
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= limit:
            retry = int(WINDOW - (now - q[0])) + 1
            raise HTTPException(
                429, f"quota public atteint ({limit} requêtes/minute) : "
                     "réessayez dans quelques instants ; besoin massif : "
                     "demandez une clé de priorité",
                headers={"Retry-After": str(retry)})
        q.append(now)


def rate_compute(request: Request):
    if priority_of(request) is None:
        check_rate(request, RATE_COMPUTE)


def rate_light(request: Request):
    if priority_of(request) is None:
        check_rate(request, RATE_LIGHT)


def _append(entry: dict):
    path = data_dir() / "usage.jsonl"
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_usage(request: Request, endpoint: str, **fields):
    """Journal JSONL anonymisé (jamais l'IP en clair)."""
    _append({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user": ip_hash(client_ip(request)),
        "endpoint": endpoint,
        **fields,
    })


def log_event(kind: str, **fields):
    """Événement de service (fin de job...) : même journal, sans
    requête donc sans utilisateur."""
    _append({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": kind,
        **fields,
    })

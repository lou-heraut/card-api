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

Journal : une ligne JSON par requête de calcul, segmenté par année
($CARD_API_DATA/usage-AAAA.jsonl : la rotation est structurelle, la
rétention se règle en supprimant les vieux fichiers) ; l'IP n'est
jamais écrite, seul un hachage
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
# Plafonds LARGES, et assumés comme tels (relevés le 2026-07-29 depuis
# 10 et 60). Ce qui protège réellement la VM n'est pas ce compteur mais
# le sémaphore `jobs.COMPUTE`, qui sérialise les calculs lourds, plus la
# bascule en file au-delà de SYNC_STATIONS. Un compteur de REQUÊTES est
# de toute façon un mauvais juge du coût : une requête de 10 stations et
# 20 fiches pèse cent fois une requête d'une station, et elles comptent
# pareil. Serrer ici gênerait surtout deux innocents : un établissement
# entier derrière une seule IP publique (DREAL, agence de l'eau), où le
# plafond se partage entre collègues sans que personne n'aille vite, et
# la boucle station par station, premier script que tout le monde écrit.
# Les refus étant désormais journalisés, ces valeurs se règlent à la
# charge observée plutôt qu'à l'intuition : cf. `make stats`.
RATE_COMPUTE = int(os.environ.get("CARD_API_RATE_COMPUTE", 60))
RATE_LIGHT = int(os.environ.get("CARD_API_RATE_LIGHT", 300))

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


def check_rate(request: Request, limit: int, famille: str):
    """Fenêtre glissante : au plus `limit` requêtes par IP et par minute.

    Le refus est journalisé, et il l'est HORS du verrou : `_append` prend
    le même `_lock`, qui n'est pas réentrant, donc écrire depuis la
    section critique bloquerait le service au premier dépassement.
    """
    ip = client_ip(request)
    now = time.time()
    retry = None
    with _lock:
        q = _hits[ip]
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= limit:
            retry = int(WINDOW - (now - q[0])) + 1
        else:
            q.append(now)
    if retry is None:
        return
    log_refusal(request, famille, limit)
    raise HTTPException(
        429, f"quota public atteint ({limit} requêtes/minute) : réessayez "
             "dans quelques instants. Une demande porte une LISTE : "
             "`stations=A,B,C` en un appel plutôt qu'un appel par station, "
             "et au-delà des plafonds synchrones elle bascule d'elle-même "
             "en file de calcul. Besoin massif ou régulier : demandez une "
             "clé de priorité",
        headers={"Retry-After": str(retry)})


def rate_compute(request: Request):
    if priority_of(request) is None:
        check_rate(request, RATE_COMPUTE, "calcul")


# Endpoints légers que l'on NE journalise PAS, et pourquoi. Ce ne sont
# pas des consultations : ce sont des appels répétés par une machine,
# qui gonfleraient le journal sans rien dire de l'usage réel.
#   health          sonde de surveillance, appelée en boucle
#   job_status      un client suit son job en interrogeant sans cesse
#   job_result      idem, et le vrai usage est déjà compté au dépôt
_MUET = {"health", "job_status", "job_result", "landing", "root"}


def rate_light(request: Request):
    """Quota des endpoints légers, ET journal de consultation.

    La consultation du catalogue est un usage aussi réel qu'un calcul :
    l'ignorer faisait sous-estimer l'audience du service, alors que le
    journal sert précisément de preuve d'impact. Journaliser ICI plutôt
    que dans chaque endpoint évite d'ajouter `request` à cinq signatures
    et garantit qu'un endpoint léger ajouté demain sera compté sans
    qu'on y pense.
    """
    if priority_of(request) is None:
        check_rate(request, RATE_LIGHT, "découverte")
    route = request.scope.get("route")
    nom = getattr(route, "name", None)
    if nom and nom not in _MUET:
        log_usage(request, nom, famille="découverte")


def _append(entry: dict):
    path = data_dir() / f"usage-{datetime.now(timezone.utc).year}.jsonl"
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


def log_refusal(request: Request, famille: str, limit: int):
    """Un dépassement de quota, journalisé comme ÉVÉNEMENT.

    Sans cette ligne le plafond était invisible : `check_rate` lève son
    429 avant tout `log_usage`, donc un utilisateur repoussé ne laissait
    aucune trace. On ne pouvait ni savoir si le quota mordait, ni sur qui,
    ni sur quel endpoint, et le régler revenait à deviner. C'est ce qui
    manquait pour arbitrer les valeurs plutôt que de les intuiter.

    Un refus n'est PAS un usage, et ne doit jamais grossir les compteurs
    de `make stats` : il porte `event`, ce qui le tient hors des deux
    familles. L'utilisateur est haché comme partout ailleurs, si bien
    qu'on distingue « une personne bloquée trente fois » de « trente
    personnes bloquées », qui n'appellent pas le même réglage.
    """
    route = request.scope.get("route")
    _append({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user": ip_hash(client_ip(request)),
        "event": "quota",
        "famille": famille,
        "endpoint": getattr(route, "name", None) or "?",
        "limit": limit,
    })


def log_event(kind: str, **fields):
    """Événement de service (fin de job...) : même journal, sans
    requête donc sans utilisateur."""
    _append({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": kind,
        **fields,
    })

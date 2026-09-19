# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Le pool : garder chaud ce qu'on consulte, effacer ce qu'on ne lit plus.

**L'ensemble de travail se définit de lui-même.** Le pool rafraîchit ce qui
est DÉJÀ dans le cache, c'est-à-dire ce que des gens ont demandé. Le
service n'a donc besoin d'aucune liste de stations appartenant à un client,
et continue d'ignorer ce qu'est le RRSE ou un réseau de référence : c'est
voulu, et c'est précisément pour l'éviter que le pool existe sous cette
forme.

Deux gestes par passe, et ils ne répondent pas à la même question.

- **Évincer** ce que personne n'a lu depuis longtemps, dans les deux étages
  du cache, par la même règle et sur la même date de dernière lecture. La
  question est celle de la place.
- **Rafraîchir** les copies qui vieillissent, entières (jamais par morceaux
  recollés, cf. `docs/dev/API.md`). La question est celle de la fraîcheur,
  et le pool est ce qui fait que l'âge réel d'une chronique consultée est
  sa période à lui, non le plafond que le service accepte.

**Poli, par construction.** Les téléchargements s'étalent sur la moitié de
la période de passe, si bien que rien ne part en rafale et qu'une passe
finit toujours avant la suivante. L'espacement se déduit du nombre à faire,
ce n'est donc pas un réglage de plus à tenir. Et le pool attend avant sa
première passe : au démarrage, le service a des requêtes à servir, et
Hub'Eau n'a pas à recevoir deux cents téléchargements à la seconde où
l'image redémarre.

**Le pool ne marque AUCUNE lecture**, et c'est la règle sur laquelle repose
toute l'éviction. Il réécrit les copies, donc écrase leur date de collecte ;
s'il marquait aussi les lectures, toutes les entrées paraîtraient
consultées en permanence et rien ne sortirait jamais du cache. Il passe par
`fetch_chronicle(refresh=True)`, qui ne marque rien.
"""

import os
import threading
import time

from . import cache, hubeau, usage

ENABLED = os.environ.get(
    "CARD_API_POOL", "1").lower() not in ("0", "false", "no", "off")

# Période entre deux passes. C'est elle qui donne l'âge réel d'une
# chronique consultée, bien en deçà de l'âge que le service ACCEPTE.
PASSE_HEURES = float(os.environ.get("CARD_API_POOL_HOURS", 6))

# Au-delà de cet âge, une copie est rafraîchie par la passe suivante.
FRAICHEUR_JOURS = float(os.environ.get("CARD_API_POOL_REFRESH_DAYS", 7))

# Sans lecture depuis ce délai, une entrée sort du cache. Généreux à
# dessein : une station consultée une fois par trimestre ne doit pas être
# évincée la veille du jour où on la redemande, et se tromper ne coûte
# qu'un téléchargement.
EVICTION_JOURS = float(os.environ.get("CARD_API_EVICT_DAYS", 90))

# Attente avant la première passe.
DEPART_S = float(os.environ.get("CARD_API_POOL_START_S", 300))

_demarre = False
_verrou = threading.Lock()


def passe(espacement: float | None = None) -> dict:
    """Une passe complète : évincer, puis rafraîchir en s'étalant.

    `espacement` est en secondes ; `None` l'étale sur la moitié de la
    période de passe. Les tests le mettent à 0, faute de quoi ils
    attendraient des heures.
    """
    bilan = cache.evict(EVICTION_JOURS)
    a_faire = [s for s in cache.cached_stations()
               if not cache.is_fresh(s, FRAICHEUR_JOURS)]
    if espacement is None:
        espacement = (PASSE_HEURES * 3600 * 0.5) / max(len(a_faire), 1)

    faites, echecs = 0, 0
    for i, station in enumerate(a_faire):
        if i and espacement:
            time.sleep(espacement)
        try:
            # Entière, et sans marquer de lecture : les deux garde-fous.
            hubeau.fetch_chronicle(station, refresh=True)
            faites += 1
        except Exception:
            # Une station qui ne répond pas ne doit pas arrêter la passe :
            # le pool repassera, et le service sert la copie en place en
            # attendant. Le compte des échecs suffit à le voir.
            echecs += 1
    bilan.update(rafraichies=faites, echecs=echecs, candidates=len(a_faire))
    usage.log_event("pool", **bilan)
    return bilan


def _boucle():
    time.sleep(DEPART_S)
    while True:
        try:
            passe()
        except Exception as exc:
            # Un pool qui meurt en silence laisserait le disque grossir
            # sans que rien ne le dise : l'échec est journalisé, et la
            # boucle continue.
            usage.log_event("pool_failed",
                            error=f"{type(exc).__name__}: {exc}")
        time.sleep(PASSE_HEURES * 3600)


def ensure_pool() -> bool:
    """Démarre le pool une fois. Rend True s'il tourne désormais."""
    global _demarre
    if not ENABLED:
        return False
    with _verrou:
        if _demarre:
            return True
        _demarre = True
        threading.Thread(target=_boucle, daemon=True,
                         name="pool").start()
        return True

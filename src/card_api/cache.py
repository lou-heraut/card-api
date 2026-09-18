# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Le disque du service, et son seul propriétaire.

Ici vivent les chemins, l'âge d'une copie, la question « est-elle assez
fraîche ? », la lecture et l'écriture des fichiers. `hubeau.py` est un
client Hub'Eau : il sait parler à l'API, il ne sait plus où les octets
atterrissent.

**Pourquoi un propriétaire unique.** « L'âge d'une copie » est une
question de politique, et elle se pose à trois endroits : la décision de
router une demande en réponse immédiate ou en file, le téléchargement
lui-même, et le rafraîchissement périodique. Tant qu'ils la posent
chacun de leur côté, ils peuvent se contredire, et un service qui se
contredit sur la fraîcheur de ses données est une boîte noire. Un seul
appel, un seul critère, une seule valeur.

**Deux dates par entrée, et il ne faut jamais les confondre.**

- la date de **collecte** est celle du fichier lui-même (son mtime),
  c'est-à-dire l'instant où la donnée a été lue chez Hub'Eau. C'est elle
  que le service publie sous `data_fetched_at`, et elle seule dit si une
  copie est périmée ;
- la date de **dernière lecture** dit quand quelqu'un a demandé cette
  entrée pour la dernière fois. Elle vit dans un fichier témoin vide, dans
  `lectures/`, dont la date EST l'information. Les témoins sont à part
  pour que `chroniques/` reste ce qu'il annonce, une entrée un fichier, et
  `ls -lt lectures/` donne alors le classement des entrées les plus
  récemment consultées, c'est-à-dire la question même de l'éviction.

La seconde ne peut pas se déduire de la première : un rafraîchissement
écrit le fichier, donc écrase sa date de collecte. Après un passage du
rafraîchissement périodique, toutes les copies ont le même âge et plus
rien ne distingue celle que personne ne relit jamais de celle qu'on
consulte tous les jours. C'est cette distinction que l'éviction attend.

**Pourquoi un fichier par entrée, et non un registre.** Le choix n'est
pas entre deux rangements, il est entre **rien à coordonner** et un
magasin partagé. Un témoin par entrée : chaque écriture touche son propre
fichier, `touch` est un appel système atomique, aucune lecture préalable,
aucun verrou, et rien qu'une autre lecture puisse écraser. Le pire qui
puisse arriver est de perdre une date, donc d'évincer trop tôt, donc de
retélécharger.

Un registre unique, lui, demanderait un verrou (deux lectures simultanées
ne doivent pas s'écraser), une écriture atomique (une coupure au mauvais
moment perd TOUT le registre, pas une entrée) et un cycle
lire-modifier-réécrire à chaque lecture servie. C'est exactement ce qu'une
base fait, si bien qu'un registre JSON écrit à la main est le plus mauvais
des choix : il a le problème de coordination sans aucune des garanties.

SQLite, donc, ou des fichiers. Elle ne redeviendrait le bon choix que le
jour où il faudrait des statistiques PAR entrée (quelles entrées sont les
plus consultées, combien de fois), que le témoin ne sait pas porter, et
non pour le taux de succès du cache : celui-là a sa place dans le journal
d'usage, déjà écrit une ligne par requête (décidé le 2026-09-18, cf.
`docs/dev/PLAN_CACHE.md`).

**L'écriture est atomique** : fichier temporaire puis renommage. Deux
demandes simultanées sur la même station peuvent télécharger deux fois,
c'est du gaspillage acceptable ; lire un fichier à moitié écrit ne l'est
pas, et rien n'empêche aujourd'hui une lecture de tomber pendant une
écriture.
"""

import datetime as dt
import os
import time
from pathlib import Path

import pandas as pd

# Durée de vie d'une copie de chronique. Les séries Hub'Eau sont de la
# donnée VALIDÉE : ce qui bouge est une révision ponctuelle, pas un flux.
MAX_AGE = 24 * 3600


def data_dir() -> Path:
    """Racine des données du service (cache, file, journal, clés)."""
    d = Path(os.environ.get("CARD_API_DATA", "./data"))
    (d / "chroniques").mkdir(parents=True, exist_ok=True)
    return d


def chronicles_dir() -> Path:
    """Dossier des chroniques journalières en cache."""
    return data_dir() / "chroniques"


def chronicle_path(station: str) -> Path:
    """Emplacement de la copie locale d'une chronique."""
    return chronicles_dir() / f"{station}.csv.gz"


def collected_at(station: str) -> str | None:
    """Date de collecte RÉELLE de la chronique en cache (UTC ISO).

    Hub'Eau révise ses données : deux appels identiques à quelques
    semaines d'écart ne donnent pas les mêmes nombres. Un résultat doit
    donc dire quand la donnée a été LUE CHEZ HUB'EAU, et pas quand le
    calcul a tourné : avec une copie qui peut vivre un jour, les deux
    diffèrent d'autant. C'est ce que le service publie sous
    `data_fetched_at`.
    """
    p = chronicle_path(station)
    if not p.exists():
        return None
    return (dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc)
            .replace(microsecond=0).isoformat())


def is_fresh(station: str) -> bool:
    """La chronique est-elle déjà là, et assez fraîche pour servir ?

    Lecture d'une date de fichier, aucun réseau : la question doit rester
    assez peu coûteuse pour qu'on la pose avant CHAQUE demande, afin de
    décider si elle tient dans une réponse immédiate.

    C'est LA question de fraîcheur du service, écrite une fois : le
    routage et le téléchargement l'appellent tous les deux, donc ne
    peuvent pas se contredire.
    """
    p = chronicle_path(station)
    return p.exists() and time.time() - p.stat().st_mtime < MAX_AGE


def reads_dir() -> Path:
    """Dossier des témoins de lecture."""
    d = data_dir() / "lectures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_marker(station: str) -> Path:
    """Témoin de dernière lecture d'une chronique (fichier vide)."""
    return reads_dir() / station


def mark_read(station: str) -> None:
    """Note que quelqu'un vient de DEMANDER cette entrée.

    À appeler sur le chemin d'une demande, jamais sur celui du
    rafraîchissement périodique : c'est toute la raison d'être de cette
    date. Le pool réécrit les copies, donc écrase leur date de collecte ;
    s'il marquait aussi les lectures, rien ne serait plus jamais évincé.

    L'échec est avalé, et la direction de l'erreur est la bonne : sans
    témoin, l'entrée passe pour n'avoir jamais été lue, donc sort du cache
    plus tôt. On repaie un téléchargement, on ne rend rien de faux.
    """
    try:
        read_marker(station).touch()
    except OSError:
        pass


def last_read(station: str) -> str | None:
    """Date de dernière lecture (UTC ISO), ou None si jamais demandée."""
    p = read_marker(station)
    if not p.exists():
        return None
    return (dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc)
            .replace(microsecond=0).isoformat())


def load_chronicle(station: str) -> pd.DataFrame:
    """Relit une chronique en cache, types compris."""
    # dtype code_station : un code tout-numérique relu en int64 ne serait
    # plus détecté comme identifiant de série (détection par type).
    return pd.read_csv(chronicle_path(station), parse_dates=["date"],
                       dtype={"code_station": str})


def store_chronicle(station: str, df: pd.DataFrame) -> None:
    """Écrit une chronique en cache, de façon atomique.

    Le temporaire est dans le MÊME dossier que sa cible, sans quoi le
    renommage ne serait plus atomique (deux systèmes de fichiers). La
    compression est demandée explicitement : pandas la déduit sinon du
    suffixe, que le nom temporaire n'a pas.
    """
    cible = chronicle_path(station)
    tmp = cible.with_name(f".{cible.name}.{os.getpid()}.tmp")
    try:
        df.to_csv(tmp, index=False, compression="gzip")
        os.replace(tmp, cible)
    finally:
        tmp.unlink(missing_ok=True)

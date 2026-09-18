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
  entrée pour la dernière fois. Elle vit dans un fichier témoin vide, à
  côté de la copie, dont le nom ajoute `.lu` et dont la date EST
  l'information.

La seconde ne peut pas se déduire de la première : un rafraîchissement
écrit le fichier, donc écrase sa date de collecte. Après un passage du
rafraîchissement périodique, toutes les copies ont le même âge et plus
rien ne distingue celle que personne ne relit jamais de celle qu'on
consulte tous les jours. C'est cette distinction que l'éviction attend.

**Pourquoi un témoin plutôt qu'une base.** Il fallait ranger une date par
entrée, et une date de fichier en est déjà une : le témoin ne demande ni
schéma, ni migration, ni dépendance, et un `ls -l` répond à la question
sans outil. Un registre unique, JSON ou SQLite, aurait été le réflexe,
mais le JSON se réécrit en ENTIER à chaque lecture, et une base serait un
mécanisme de comptage de plus dans un service qui n'en a aucun : le taux
de succès du cache a sa place dans le journal d'usage, déjà écrit une
ligne par requête. SQLite ne redeviendrait le bon choix que le jour où il
faudrait des statistiques PAR entrée, ce que personne ne demande
aujourd'hui (décidé le 2026-09-18, cf. `docs/dev/PLAN_CACHE.md`).

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


def read_marker(station: str) -> Path:
    """Fichier témoin de dernière lecture d'une chronique."""
    p = chronicle_path(station)
    return p.with_name(p.name + ".lu")


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

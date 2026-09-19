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
fraîche ? », la lecture et l'écriture des fichiers, et le registre de ce
qui a été demandé. `hubeau.py` est un client Hub'Eau : il sait parler à
l'API, il ne sait plus où les octets atterrissent.

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
  entrée. Elle vit dans le registre décrit plus bas.

La seconde ne peut pas se déduire de la première : un rafraîchissement
écrit le fichier, donc écrase sa date de collecte. Après un passage du
rafraîchissement périodique, toutes les copies ont le même âge et plus
rien ne distingue celle que personne ne relit jamais de celle qu'on
consulte tous les jours. C'est cette distinction que l'éviction attend.
D'où la règle : une DEMANDE marque une lecture, un rafraîchissement
JAMAIS.

**Le registre des lectures est une table SQLite**, `cache.db`, une ligne
par entrée : sa clé, la date de sa dernière lecture, et le nombre de fois
qu'elle a été demandée.

Le choix s'est posé contre un fichier témoin vide par entrée, dont la date
aurait porté l'information. Les deux se valent sur la robustesse de CETTE
donnée, et le témoin ne demande aucune coordination ; ce qui a tranché est
la pérennité. Un témoin ne peut porter qu'UN fait, et il en manquait déjà
un : le journal d'usage enregistre le NOMBRE de stations d'une requête et
non leurs codes, si bien que « quelles entrées sont les plus consultées »
ne se dérive de rien. Le registre le donne sans rien ajouter, et une
question future s'y répond par une colonne plutôt que par un second
mécanisme. Un registre JSON, en revanche, reste le plus mauvais des trois
choix : il aurait le problème de coordination d'un magasin partagé sans
aucune de ses garanties, puisqu'il se réécrit en entier à chaque lecture
et qu'une coupure au mauvais moment le perd tout entier.

Ce que la base coûte, dit franchement : un schéma, donc une migration le
jour où il bouge, et un mode de panne qui n'existait pas, l'écriture
concurrente refusée (`database is locked`). Il est contenu : le registre
est en WAL, une transaction porte une ligne, et `mark_read` avale son
échec. La direction de l'erreur est la bonne, une date perdue faisant
évincer trop tôt, donc retélécharger, jamais rendre un résultat faux.

**L'écriture est atomique** : fichier temporaire puis renommage. Deux
demandes simultanées sur la même entrée peuvent la calculer deux fois,
c'est du gaspillage acceptable ; lire un fichier à moitié écrit ne l'est
pas.

**Deux étages.** Le premier garde la matière première, la chronique
journalière ; le second garde le PRODUIT, la série annuelle déjà agrégée,
sous une clé qui énumère tout ce qui a pu influencer sa valeur (cf.
`pipeline.cle_serie`). L'agrégation était repayée à chaque demande, même
tout en cache, et derrière le sémaphore : mesuré le 2026-09-19 sur 200
stations, 2,4 s pour `QA` et 35 s pour `dtLF`.

Les séries sont en **Parquet**, et c'est un choix mesuré contre le CSV
compressé : seul Parquet rend le cadre IDENTIQUE, types compris. Un CSV
relu perd le dernier bit des flottants, et surtout il ne sait pas qu'une
variable de DATE est une date : `tQJXA` part en `Int64` et revient en
`float64`, si bien qu'une réponse servie par le cache différerait d'une
réponse calculée, en silence. Le prix est connu et assumé : un paquet de
plus (~150 Mo dans l'image) et des fichiers de 4 Kio au lieu de 700
octets, soit moins d'un mégaoctet pour une vue MAKAHO entière.
"""

import datetime as dt
import os
import sqlite3
import threading
import time
from pathlib import Path

import pandas as pd

# Âge maximal accepté par défaut pour une copie, en JOURS, comme le
# paramètre de requête qui peut l'écraser : une seule unité sur tout le
# chemin, donc aucune conversion à retenir. Les séries Hub'Eau sont de la
# donnée VALIDÉE, ce qui bouge est une révision ponctuelle et non un flux ;
# qui a besoin de frais le demande, et le pool repassera de toute façon
# plus souvent que ce défaut.
MAX_AGE_DAYS = float(os.environ.get("CARD_API_MAX_AGE_DAYS", 30))

# Préfixes de clé du registre : les deux familles d'entrées cohabitent
# dans la même table sans pouvoir se confondre, et l'éviction les traite
# de la même façon puisque c'est la même question.
_CHRONIQUE = "chronique:"
_SERIE = "serie:"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lectures (
    cle            TEXT PRIMARY KEY,
    dernier_acces  REAL NOT NULL,
    n_acces        INTEGER NOT NULL
)
"""

_verrou = threading.Lock()
_con: sqlite3.Connection | None = None
_con_chemin: Path | None = None


def data_dir() -> Path:
    """Racine des données du service (cache, registre, file, journal)."""
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


def is_fresh(station: str, max_age: float | None = None) -> bool:
    """Cette copie est-elle assez fraîche POUR CE QUI EST DEMANDÉ ?

    `max_age` est un nombre de JOURS, celui que la requête accepte ;
    `None` prend le défaut de la configuration. `0` est une valeur
    légitime et veut dire « rien d'autre que du frais », donc il ne doit
    jamais être confondu avec l'absence.

    Lecture d'une date de fichier, aucun réseau : la question doit rester
    assez peu coûteuse pour qu'on la pose avant CHAQUE demande, afin de
    décider si elle tient dans une réponse immédiate.

    C'est LA question de fraîcheur du service, écrite une fois. Elle
    était posée à deux endroits avec deux critères, et les deux pouvaient
    se contredire : le routage comparait l'âge à la durée de vie du
    service pendant que le calcul le comparait à ce que la requête
    acceptait. Une demande annoncée immédiate partait alors pour une
    minute de téléchargements, derrière le sémaphore, en bloquant tous
    ceux qui attendaient.
    """
    jours = MAX_AGE_DAYS if max_age is None else max_age
    p = chronicle_path(station)
    return p.exists() and time.time() - p.stat().st_mtime < jours * 86400


# ── Le registre des lectures ─────────────────────────────────────────────────

def _connexion() -> sqlite3.Connection:
    """La connexion au registre, ouverte une fois puis réutilisée.

    Elle est mémorisée AVEC son chemin : `CARD_API_DATA` peut changer
    entre deux appels, ce que fait chaque test, et une connexion gardée
    sans son chemin écrirait dans la base précédente.

    `synchronous=NORMAL` avec WAL : un arrêt brutal de la machine peut
    perdre les dernières lectures notées, jamais la base. C'est le bon
    compromis pour une comptabilité dont la perte coûte un
    téléchargement, et il évite un fsync par ligne.

    À appeler sous `_verrou`.
    """
    global _con, _con_chemin
    chemin = data_dir() / "cache.db"
    if _con is None or _con_chemin != chemin:
        if _con is not None:
            _con.close()
        _con = sqlite3.connect(chemin, check_same_thread=False, timeout=5.0)
        _con.execute("PRAGMA journal_mode=WAL")
        _con.execute("PRAGMA synchronous=NORMAL")
        _con.execute(_SCHEMA)
        _con.commit()
        _con_chemin = chemin
    return _con


def _marque_cle(cle: str) -> None:
    """Note qu'une entrée du registre vient d'être servie.

    L'échec est avalé, et la direction de l'erreur est la bonne : sans
    date, l'entrée passe pour n'avoir jamais été lue, donc sort du cache
    plus tôt. On repaie un calcul, on ne rend rien de faux.
    """
    try:
        with _verrou:
            con = _connexion()
            con.execute(
                "INSERT INTO lectures (cle, dernier_acces, n_acces) "
                "VALUES (?, ?, 1) "
                "ON CONFLICT(cle) DO UPDATE SET "
                "  dernier_acces = excluded.dernier_acces, "
                "  n_acces = n_acces + 1",
                (cle, time.time()))
            con.commit()
    except sqlite3.Error:
        pass


def _ligne_cle(cle: str) -> tuple[float, int] | None:
    with _verrou:
        cur = _connexion().execute(
            "SELECT dernier_acces, n_acces FROM lectures WHERE cle = ?",
            (cle,))
        return cur.fetchone()


def _oublie_cle(cle: str) -> None:
    try:
        with _verrou:
            con = _connexion()
            con.execute("DELETE FROM lectures WHERE cle = ?", (cle,))
            con.commit()
    except sqlite3.Error:
        pass


def mark_read(station: str) -> None:
    """Note que quelqu'un vient de DEMANDER cette chronique.

    À appeler sur le chemin d'une demande, jamais sur celui du
    rafraîchissement périodique : c'est toute la raison d'être de cette
    date. Le pool réécrit les copies, donc écrase leur date de collecte ;
    s'il marquait aussi les lectures, rien ne serait plus jamais évincé.

    L'échec est avalé, et la direction de l'erreur est la bonne : sans
    date, l'entrée passe pour n'avoir jamais été lue, donc sort du cache
    plus tôt. On repaie un téléchargement, on ne rend rien de faux.
    """
    _marque_cle(_CHRONIQUE + station)


def _ligne(station: str) -> tuple[float, int] | None:
    return _ligne_cle(_CHRONIQUE + station)


def last_read(station: str) -> str | None:
    """Date de dernière lecture (UTC ISO), ou None si jamais demandée."""
    ligne = _ligne(station)
    if ligne is None:
        return None
    return (dt.datetime.fromtimestamp(ligne[0], dt.timezone.utc)
            .replace(microsecond=0).isoformat())


def read_age(station: str) -> float | None:
    """Secondes écoulées depuis la dernière demande, None si jamais.

    C'est la question de l'éviction, qui efface ce que personne ne lit
    plus. `None` s'y lit comme « jamais lue », donc comme la première à
    partir.
    """
    ligne = _ligne(station)
    return None if ligne is None else time.time() - ligne[0]


def read_count(station: str) -> int:
    """Nombre de fois que la chronique a été demandée.

    Ce que le journal d'usage ne peut pas dire : il enregistre le NOMBRE
    de stations d'une requête, pas leurs codes.
    """
    ligne = _ligne(station)
    return 0 if ligne is None else ligne[1]


def forget(station: str) -> None:
    """Oublie une entrée du registre, une fois sa copie évincée.

    Sans cela le registre garderait la trace d'entrées qui n'existent
    plus, et son décompte cesserait de décrire le cache.
    """
    _oublie_cle(_CHRONIQUE + station)


# ── Le second étage : les séries déjà agrégées ───────────────────────────────

def series_dir() -> Path:
    """Dossier des séries annuelles déjà calculées."""
    d = data_dir() / "series"
    d.mkdir(parents=True, exist_ok=True)
    return d


def series_path(cle: str) -> Path:
    """Emplacement d'une série, nommée par sa clé.

    La clé étant une empreinte de tout ce qui a pu influencer la valeur,
    un changement d'ingrédient donne un autre nom de fichier : l'ancienne
    entrée n'est plus demandée, donc plus lue. L'invalidation ne demande
    aucun code, c'est l'éviction qui ramasse (`read_age`).
    """
    return series_dir() / f"{cle}.parquet"


def load_series(cle: str) -> pd.DataFrame | None:
    """La série déjà calculée pour cette clé, ou None si elle manque.

    Une lecture est NOTÉE au registre, comme pour une chronique : c'est ce
    que l'éviction attend. Un fichier illisible (écriture interrompue par
    un arrêt brutal, disque abîmé) est traité comme absent et EFFACÉ,
    sans quoi il serait relu éternellement : la série se recalcule, ce qui
    coûte du temps et non de la justesse.
    """
    p = series_path(cle)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        p.unlink(missing_ok=True)
        _oublie_cle(_SERIE + cle)
        return None
    _marque_cle(_SERIE + cle)
    return df


def store_series(cle: str, df: pd.DataFrame) -> None:
    """Garde une série calculée, de façon atomique.

    L'écriture note aussi une lecture : la série vient d'être calculée
    POUR quelqu'un, et sans cette note elle passerait pour n'avoir jamais
    été demandée, donc sortirait du cache avant d'avoir servi. Rien ne
    réécrit une série dans le dos d'une demande, contrairement aux
    chroniques que le pool rafraîchit, donc il n'y a pas ici de second
    chemin à distinguer.

    L'index n'est pas conservé : une série s'identifie par sa clé et se
    lit par ses colonnes, un index de tranche n'aurait aucun sens au
    retour.
    """
    cible = series_path(cle)
    tmp = cible.with_name(f".{cible.name}.{os.getpid()}.tmp")
    try:
        df.reset_index(drop=True).to_parquet(tmp, index=False)
        os.replace(tmp, cible)
        _marque_cle(_SERIE + cle)
    finally:
        tmp.unlink(missing_ok=True)


# ── Les chroniques elles-mêmes ───────────────────────────────────────────────

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

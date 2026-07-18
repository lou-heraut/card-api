#!/usr/bin/env python3
# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Veille de santé de card-api, pour cron.

À lancer depuis une machine EXTÉRIEURE à la VM : une veille installée
sur la VM meurt avec elle et ne signalera jamais sa panne. L'API est
publique, n'importe quel poste allumé régulièrement fait l'affaire
(stdlib seule, aucune dépendance). Exemple de crontab :

    */15 * * * * CARD_API_URL=http://147.100.222.13 \\
        NTFY=un-sujet-difficile-a-deviner \\
        python3 /chemin/vers/veille_sante.py

Silencieux quand tout va bien. En cas d'anomalie (API injoignable,
réponse lente, disque de la VM plein, file de calcul engorgée) :
notification poussée sur https://ntfy.sh/$NTFY si NTFY est défini
(gratuit, sans compte : s'abonner au même sujet depuis l'application
ou le navigateur), et dans tous les cas message sur stderr + sortie
non nulle (cron enverra son mail local s'il est configuré).

Seuils par variables d'environnement (défauts entre parenthèses) :
LENTEUR_S (5) réponse maximale en secondes, DISQUE_PCT (90)
remplissage maximal du disque de la VM, FILE_MAX (50) jobs en attente.
"""

import json
import os
import sys
import time
import urllib.request

URL = os.environ.get("CARD_API_URL", "http://147.100.222.13").rstrip("/")
NTFY = os.environ.get("NTFY", "")
LENTEUR_S = float(os.environ.get("LENTEUR_S", 5))
DISQUE_PCT = float(os.environ.get("DISQUE_PCT", 90))
FILE_MAX = int(os.environ.get("FILE_MAX", 50))


def alerte(message: str):
    texte = f"card-api ({URL}) : {message}"
    if NTFY:
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://ntfy.sh/{NTFY}", data=texte.encode(),
                headers={"Title": "Alerte card-api"}), timeout=10)
        except OSError as e:
            print(f"notification ntfy impossible : {e}", file=sys.stderr)
    print(texte, file=sys.stderr)
    sys.exit(1)


def main():
    t0 = time.time()
    try:
        with urllib.request.urlopen(f"{URL}/v1/health",
                                    timeout=LENTEUR_S + 5) as r:
            corps = json.load(r)
    except OSError as e:
        alerte(f"API injoignable : {e}")
    duree = time.time() - t0

    if corps.get("status") != "ok":
        alerte(f"status = {corps.get('status')!r}")
    if duree > LENTEUR_S:
        alerte(f"réponse lente : {duree:.1f} s (seuil {LENTEUR_S:g} s)")
    if corps["disk"]["used_pct"] > DISQUE_PCT:
        alerte(f"disque de la VM à {corps['disk']['used_pct']} % "
               f"({corps['disk']['free_gb']} Go libres)")
    if corps["jobs"]["queued"] > FILE_MAX:
        alerte(f"file de calcul engorgée : {corps['jobs']['queued']} "
               "jobs en attente")


if __name__ == "__main__":
    main()

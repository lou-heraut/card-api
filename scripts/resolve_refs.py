# Copyright 2021-2026 Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Résout CARD_REF et STASE_REF en identifiants de commit, à la
construction de l'image.

Le numéro de version d'un paquet ne suffit pas à dire ce qui tourne :
quand la ref est une branche, quinze commits successifs annoncent tous
le même numéro. L'identifiant de commit, lui, désigne un état et un
seul. Le service le publie à côté du numéro, si bien qu'un résultat
reste reproductible même si l'image a été construite depuis `main`.

Écrit un JSON sur la sortie standard. Une résolution qui échoue (réseau,
quota GitHub) donne `null` : le service démarre quand même, il annoncera
seulement le numéro de version.
"""

import json
import os
import urllib.request

OWNER = "lou-heraut"
TIMEOUT = 15


def resolve(repo, ref):
    if not ref:
        return None
    url = f"https://api.github.com/repos/{OWNER}/{repo}/commits/{ref}"
    try:
        req = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json",
                          "User-Agent": "card-api-build"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)["sha"][:12]
    except Exception:
        return None


def main():
    out = {}
    for key, repo in (("card", "card"), ("stase", "stase")):
        ref = os.environ.get(f"{key.upper()}_REF")
        out[key] = {"ref": ref, "commit": resolve(repo, ref)}
    print(json.dumps(out))


if __name__ == "__main__":
    main()

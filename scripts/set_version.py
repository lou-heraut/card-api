# Copyright 2021-2026 Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api package.
#
# card-api is free software: you can redistribute it and/or modify it under
# the terms of the license in the LICENSE file of this repository.

"""Propage un numéro de version depuis pyproject.toml.

Une version vit à trois endroits : `pyproject.toml` (la source),
`CITATION.cff` et `codemeta.json` (les métadonnées de citation). Les
recopier à la main, c'est se garantir un oubli. Ce script les accorde,
et `tests/test_citation.py` vérifie qu'ils le sont restés.

Usage (depuis la racine du dépôt) :
    python scripts/set_version.py 0.3.0   # fixe la version partout
    python scripts/set_version.py         # propage celle du pyproject
"""

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lire_version():
    m = re.search(r'^version\s*=\s*"([^"]+)"',
                  (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    if not m:
        sys.exit("version introuvable dans pyproject.toml")
    return m.group(1)


def ecrire(chemin, motif, remplacement):
    p = ROOT / chemin
    texte = p.read_text(encoding="utf-8")
    neuf, n = re.subn(motif, remplacement, texte, count=1, flags=re.M)
    if not n:
        sys.exit(f"motif introuvable dans {chemin}")
    if neuf != texte:
        p.write_text(neuf, encoding="utf-8")
        return True
    return False


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else lire_version()
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", version):
        sys.exit(f"version '{version}' mal formée : attendu majeur.mineur[.patch]")
    aujourd_hui = dt.date.today().isoformat()

    change = []
    if ecrire("pyproject.toml", r'^version\s*=\s*"[^"]+"',
              f'version = "{version}"'):
        change.append("pyproject.toml")
    if ecrire("CITATION.cff", r'^version:\s*"[^"]+"', f'version: "{version}"'):
        change.append("CITATION.cff")
    if ecrire("CITATION.cff", r'^date-released:\s*"[^"]+"',
              f'date-released: "{aujourd_hui}"'):
        change.append("CITATION.cff (date)")

    p = ROOT / "codemeta.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    if (d.get("version"), d.get("datePublished")) != (version, aujourd_hui):
        d["version"] = version
        d["datePublished"] = aujourd_hui
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")
        change.append("codemeta.json")

    print(f"version {version} : " +
          (", ".join(change) + " mis à jour" if change else "déjà partout"))
    print("Pensez à la section du CHANGELOG, puis :")
    print(f"    git commit -am \"{'card-api'} {version} : ...\" "
          f"&& git tag -a v{version} -m \"{'card-api'} {version}\"")


if __name__ == "__main__":
    main()

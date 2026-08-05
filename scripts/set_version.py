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
    python scripts/set_version.py --etat  # faut-il couper une version ?
    python scripts/set_version.py 0.3.0   # fixe la version partout
    python scripts/set_version.py         # propage celle du pyproject

`--etat` ne décide rien : couper une version est un jugement, et la règle
qui le guide est le paragraphe « Numérotation » de `CHANGELOG.md`. Il
pose seulement les faits sous les yeux au moment où la question se pose.
Ici le numéro est plus exposé qu'ailleurs : `API_VERSION` le lit dans les
métadonnées du paquet, et il part dans CHAQUE réponse ainsi que dans le
contrat OpenAPI. Le même mode existe dans card et dans stase : trente
lignes recopiées dans trois dépôts cloisonnés coûtent moins cher que le
couplage qu'un outil commun imposerait.
"""

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args):
    """Sortie d'une commande git, ou None si elle échoue (dépôt sans tag,
    archive sans .git)."""
    try:
        out = subprocess.run(("git", "-C", str(ROOT)) + args,
                             capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.strip()


def etat():
    """Les faits qui portent la décision de couper une version."""
    print(f"version du paquet    : {lire_version()}")

    tag = _git("describe", "--tags", "--abbrev=0")
    if tag:
        date = _git("log", "-1", "--format=%ad", "--date=short", tag)
        print(f"dernier tag          : {tag} ({date})")
        print(f"commits depuis       : "
              f"{_git('rev-list', '--count', f'{tag}..HEAD')}")
    else:
        print("dernier tag          : aucun")

    texte = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(r"^## Non publié\n(.*?)(?=^## )", texte, re.M | re.S)
    entrees = re.findall(r"^- \*\*", section.group(1), re.M) if section else []
    print(f"entrées non publiées : {len(entrees)}")
    print()
    print("Couper ou non : cf. « Numérotation » en tête du CHANGELOG.")
    print("En deux mots : on ne coupe que si ce qu'un client VOIT change")
    print("(route, champ, empreinte, quota), parce que le numéro part dans")
    print("chaque réponse. Sinon le commit publié suffit, et laisser le")
    print("numéro en place est le bon comportement.")


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
    if len(sys.argv) > 1 and sys.argv[1] in ("--etat", "--état"):
        etat()
        return
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

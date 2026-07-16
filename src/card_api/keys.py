# Copyright 2026      Louis Héraut <louis.heraut@inrae.fr>*1
#
# *1 INRAE, UR RiverLy, Villeurbanne, France
#
# This file is part of the card-api service.
#
# card-api is free software: you can redistribute it and/or modify it
# under the terms of the license in the LICENSE file of this repository.

"""Clés de priorité : attribution manuelle, gratuite, à la demande.

Une clé ne conditionne PAS l'accès (le service est public) : elle
lève les quotas par minute, relève les plafonds de jobs et fait passer
les jobs en tête de file. Stockage : $CARD_API_DATA/keys.json (jamais
sous git). Gestion sur la VM :

    make key name="Prénom Nom, labo"     # crée et affiche un jeton
    make keys                            # liste (jetons tronqués)
    make key-revoke key=<jeton, préfixe ou nom>   # révoque
"""

import json
import secrets
import sys
from datetime import datetime, timezone

from .hubeau import data_dir


def _path():
    return data_dir() / "keys.json"


def load() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(keys: dict):
    _path().write_text(json.dumps(keys, ensure_ascii=False, indent=1),
                       encoding="utf-8")


def add(name: str) -> str:
    keys = load()
    token = secrets.token_urlsafe(24)
    keys[token] = {"name": name,
                   "created": datetime.now(timezone.utc)
                   .isoformat(timespec="seconds")}
    _save(keys)
    return token


def revoke(ref: str) -> str:
    """Révoque par jeton complet, préfixe unique (ce que `make keys`
    affiche) ou nom exact. Retourne un message lisible : l'ambiguïté
    ne révoque rien."""
    keys = load()
    matches = [t for t in keys
               if t == ref or t.startswith(ref)
               or keys[t]["name"] == ref]
    if not matches:
        return "aucune clé ne correspond"
    if len(matches) > 1:
        return (f"{len(matches)} clés correspondent, rien de révoqué : "
                "précisez (préfixe plus long ou nom exact)")
    name = keys[matches[0]]["name"]
    del keys[matches[0]]
    _save(keys)
    return f"révoquée : {name}"


def main():
    args = sys.argv[1:]
    if args[:1] == ["add"] and len(args) == 2:
        token = add(args[1])
        print(f"clé créée pour « {args[1]} » :\n\n    {token}\n\n"
              "à transmettre au demandeur ; usage : en-tête X-API-Key "
              "ou paramètre key=")
    elif args[:1] == ["list"]:
        keys = load()
        if not keys:
            print("aucune clé")
        for token, info in keys.items():
            print(f"  {token[:8]}…  {info['name']}  ({info['created']})")
    elif args[:1] == ["revoke"] and len(args) == 2:
        print(revoke(args[1]))
    else:
        print("usage : python -m card_api.keys add \"Nom, labo\" | list | "
              "revoke <jeton|préfixe|nom>")
        sys.exit(2)


if __name__ == "__main__":
    main()

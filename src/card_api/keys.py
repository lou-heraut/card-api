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
lève les quotas par minute, relève les plafonds de jobs, fait passer
les jobs en tête de file et permet de lister ses jobs (GET /v1/jobs).

Le jeton n'est affiché qu'à sa création et n'est stocké nulle part :
$CARD_API_DATA/keys.json (jamais sous git) garde son SHA-256 sous le
préfixe (8 premiers caractères). Le préfixe sert d'identifiant public
partout (journal, jobs, listing) : il ne permet pas de s'authentifier
et n'est pas nominatif ; seul keys.json relie préfixe et nom, et
l'entrée disparaît à la révocation. Gestion sur la VM :

    make key name="Prénom Nom, labo"     # crée et affiche LE jeton
    make keys                            # liste (préfixes)
    make key-revoke key=<jeton, préfixe ou nom>   # révoque
"""

import hashlib
import json
import secrets
import sys
from datetime import datetime, timezone

from .hubeau import data_dir

PREFIX = 8


def _path():
    return data_dir() / "keys.json"


def _hash(token: str) -> str:
    # SHA-256 nu : le jeton est aléatoire à haute entropie (~190 bits),
    # pas un mot de passe, un hachage lent n'apporterait rien.
    return hashlib.sha256(token.encode()).hexdigest()


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
    while True:                    # collision de préfixe : improbable
        token = secrets.token_urlsafe(24)
        prefix = token[:PREFIX]
        if prefix not in keys:
            break
    keys[prefix] = {"hash": _hash(token), "name": name,
                    "created": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")}
    _save(keys)
    return token


def lookup(token: str) -> dict | None:
    """Info d'une clé ({prefix, name, created}) si le jeton est valide,
    None sinon."""
    info = load().get(token[:PREFIX])
    if info is None or _hash(token) != info["hash"]:
        return None
    return {"prefix": token[:PREFIX], "name": info["name"],
            "created": info["created"]}


def revoke(ref: str) -> str:
    """Révoque par jeton complet, préfixe (ce que `make keys` affiche,
    même abrégé) ou nom exact. Retourne un message lisible :
    l'ambiguïté ne révoque rien."""
    keys = load()
    if not ref:
        return "aucune clé ne correspond"
    matches = [p for p in keys
               if p.startswith(ref) or p == ref[:PREFIX]
               or keys[p]["name"] == ref]
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
              "ou paramètre key=. Le jeton n'est affiché que "
              "maintenant (seul son hachage est conservé) : perdu = "
              "en réémettre un.")
    elif args[:1] == ["list"]:
        keys = load()
        if not keys:
            print("aucune clé")
        for prefix, info in keys.items():
            print(f"  {prefix}  {info['name']}  ({info['created']})")
    elif args[:1] == ["revoke"] and len(args) == 2:
        print(revoke(args[1]))
    else:
        print("usage : python -m card_api.keys add \"Nom, labo\" | list | "
              "revoke <jeton|préfixe|nom>")
        sys.exit(2)


if __name__ == "__main__":
    main()

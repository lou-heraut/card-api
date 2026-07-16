# card-api

Service web des fiches [card](https://github.com/lou-heraut/card) :
extraction de variables hydroclimatiques sur les débits Banque Hydro
(via [Hub'Eau](https://hubeau.eaufrance.fr/)) et diagnostic de
stationnarité (via [stase](https://github.com/lou-heraut/stase)).

Service public de recherche, ouvert et sans inscription (quota par
IP) ; conception : `card/docs/dev/API.md`.

## État

Étape 1 — découverte du catalogue, sans réseau :

- `GET /v1/cards` — catalogue filtrable par facettes de classification
  (`?phenomenon=basses eaux&output=série`, `&operator=delta`...) ;
- `GET /v1/cards/{id}` — détail d'une fiche (`?lang=fr|en`) ;
- `GET /v1/health` — sonde de vie ;
- `/docs` — documentation interactive (OpenAPI).

À venir (cf. API.md) : `/v1/stations`, `/v1/extract`, `/v1/trend`,
quotas, cache, journal d'usage.

## Développement

```bash
.python_env/bin/uvicorn card_api.main:app --reload   # http://127.0.0.1:8000/docs
.python_env/bin/python -m pytest
```

(card et stase sont rendus importables par `tests/conftest.py` en dev ;
en image Docker ils sont installés depuis GitHub à révision épinglée.)

## Déploiement (VM)

```bash
# éditer Caddyfile : y mettre le nom de domaine de la VM
docker compose up -d --build
```

Mise à jour : `git pull && docker compose up -d --build`.

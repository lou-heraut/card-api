# card-api

Service web des fiches [card](https://github.com/lou-heraut/card) :
extraction de variables hydroclimatiques sur les débits Banque Hydro
(via [Hub'Eau](https://hubeau.eaufrance.fr/)) et diagnostic de
stationnarité (via [stase](https://github.com/lou-heraut/stase)).

Service public de recherche, ouvert et sans inscription (quota par
IP) ; conception : `card/docs/dev/API.md`.

## État

Étapes 1 et 2 :

- `GET /v1/cards` — catalogue filtrable par facettes de classification
  (`?phenomenon=basses eaux&output=série`, `&operator=delta`...) ;
- `GET /v1/cards/{id}` — détail d'une fiche (`?lang=fr|en`) ;
- `GET /v1/stations?libelle=Austerlitz` — référentiel Hub'Eau (les
  codes ont changé depuis la refonte Hydro : chercher ici) ;
- `GET /v1/extract?stations=F700000103&cards=QA,VCN10&start=&end=` —
  chroniques Hub'Eau (QmnJ, converties en m³/s) → extraction card ;
  cache local 24 h par station ; fiches à entrée Q uniquement ;
- `GET /v1/health` — sonde de vie ;
- `/docs` — documentation interactive (OpenAPI).

À venir (cf. API.md) : `/v1/trend`, quotas IP, motif job, journal
d'usage. Test live : `CARD_API_LIVE=1 pytest tests/test_live_hubeau.py`.

## Développement

Une fois (installe card, stase et card-api en mode éditable dans le
venv — les modifications des trois repos sont prises en compte sans
réinstaller) :

```bash
python3 -m venv .python_env
.python_env/bin/pip install -e ../../EXstat_project/stase -e ../card -e .[dev]
```

Puis :

```bash
.python_env/bin/uvicorn card_api.main:app --reload   # http://127.0.0.1:8000/docs
.python_env/bin/python -m pytest
```

(En image Docker, card et stase sont installés depuis GitHub à
révision épinglée — cf. Dockerfile.)

## Déploiement (VM)

```bash
# éditer Caddyfile : y mettre le nom de domaine de la VM
docker compose up -d --build
```

Mise à jour : `git pull && docker compose up -d --build`.

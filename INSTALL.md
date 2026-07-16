# INSTALL — développement et déploiement

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
.python_env/bin/python -m pytest                     # suite hors-ligne (Hub'Eau simulé)
CARD_API_LIVE=1 .python_env/bin/python -m pytest tests/test_live_hubeau.py
```

## Déploiement (VM)

```bash
# éditer Caddyfile : y mettre le nom de domaine de la VM
docker compose up -d --build
```

Mise à jour : `git pull && docker compose up -d --build`.

L'image installe card et stase depuis GitHub à révision épinglée
(arguments `CARD_REF`/`STASE_REF` du Dockerfile) : chaque déploiement
est traçable.

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `CARD_API_DATA` | `./data` (`/data` en Docker) | cache des chroniques + journal d'usage |
| `CARD_API_RATE_COMPUTE` | 10 | requêtes de calcul (extract/trend) par IP et par minute |
| `CARD_API_RATE_LIGHT` | 60 | requêtes de catalogue par IP et par minute |
| `CARD_API_SALT` | aléatoire au démarrage | sel du hachage des IP dans le journal — le fixer pour des statistiques d'utilisateurs distincts stables entre redémarrages |

## Journal d'usage

`$CARD_API_DATA/usage.jsonl` — une ligne JSON par requête de calcul
servie : horodatage, hachage salé de l'IP (jamais l'IP en clair),
endpoint, nombre de stations, fiches demandées. Sert aux statistiques
d'usage (bilans, dossiers de financement) sans identifier personne.

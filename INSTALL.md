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

Le Makefile est l'interface ; la configuration vit dans `.env`
(gitignoré — rien de propre à la VM n'est dans le code) :

```bash
sudo git clone git@github.com:lou-heraut/card-api.git /opt/card-api
cd /opt/card-api
make env        # crée .env (sel aléatoire généré) — éditer DOMAIN
make up         # construit et lance (api + caddy, HTTPS automatique)
```

Au quotidien :

```bash
make update     # git pull + reconstruction + redéploiement + statut
make logs       # suivre les logs de l'API
make status     # conteneurs + sonde de vie
make stats      # statistiques d'usage (requêtes, utilisateurs, fiches)
make down       # arrêt
```

L'image installe card et stase depuis GitHub à révision épinglée
(`CARD_REF`/`STASE_REF` dans `.env`) : chaque déploiement est
traçable. Docker (`restart: unless-stopped`) relance les conteneurs
au démarrage de la VM — pas de systemd à écrire.

## Variables d'environnement

Tout se règle dans `.env` (lu par docker compose ; cf. `.env.example`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `DOMAIN` | — (requis) | domaine public, injecté dans le Caddyfile |
| `CARD_API_SALT` | — (requis, généré par `make env`) | sel du hachage des IP du journal — fixe en prod pour des comptes d'utilisateurs distincts stables |
| `CARD_API_RATE_COMPUTE` | 10 | requêtes de calcul (extract/trend) par IP/minute |
| `CARD_API_RATE_LIGHT` | 60 | requêtes de catalogue par IP/minute |
| `CARD_REF` / `STASE_REF` | main | révisions de card/stase dans l'image |
| `CARD_API_DATA` | `/data` (volume) | cache des chroniques + journal (ne pas toucher en Docker) |

## Journal d'usage

`$CARD_API_DATA/usage.jsonl` — une ligne JSON par requête de calcul
servie : horodatage, hachage salé de l'IP (jamais l'IP en clair),
endpoint, nombre de stations, fiches demandées. Sert aux statistiques
d'usage (bilans, dossiers de financement) sans identifier personne.

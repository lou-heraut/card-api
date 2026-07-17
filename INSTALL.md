# INSTALL : développement et déploiement

## Développement

Une fois (installe card, stase et card-api en mode éditable dans le
venv : les modifications des trois repos sont prises en compte sans
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

Prérequis sur une VM nue : Docker + le plugin compose v2 (la
sous-commande `docker compose` du Makefile ; le paquet
`docker-compose` sans -v2 est l'ancienne v1, insuffisante).

```bash
# Ubuntu : tout est dans les dépôts
sudo apt update
sudo apt install docker.io docker-compose-v2
# docker-compose-v2 introuvable ? activer le dépôt universe :
#   sudo add-apt-repository universe && sudo apt update

# Debian (ou Ubuntu via le dépôt officiel Docker) : suivre
# docs.docker.com/engine/install/<debian|ubuntu>, puis
sudo apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin

# dans les deux cas :
sudo usermod -aG docker "$USER"    # puis se déconnecter/reconnecter
```

(Le script `curl -fsSL https://get.docker.com | sudo sh` automatise
la mise en place du dépôt officiel si l'on préfère.)

Il faut aussi que le DNS du futur `DOMAIN` pointe vers la VM et que
les ports 80 et 443 soient ouverts en entrée (certificat HTTPS
automatique de Caddy) ; sur une VM institutionnelle, penser au
pare-feu.

Le Makefile est l'interface ; la configuration vit dans `.env`
(gitignoré, rien de propre à la VM n'est dans le code).

Clone en HTTPS, jamais en SSH : le repo est public, la VM n'a besoin
d'aucun identifiant et ne doit jamais en porter (une clé SSH
personnelle sur un serveur donnerait à ce serveur le droit d'écrire
sur vos repos). Le dossier appartient à l'utilisateur courant pour
que `make update` tourne ensuite sans sudo :

```bash
sudo mkdir -p /opt/card-api && sudo chown "$USER": /opt/card-api
git clone https://github.com/lou-heraut/card-api.git /opt/card-api
cd /opt/card-api
make env        # crée .env (sel aléatoire généré), éditer DOMAIN
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
au démarrage de la VM, pas de systemd à écrire.

## Variables d'environnement

Tout se règle dans `.env` (lu par docker compose ; cf. `.env.example`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `DOMAIN` | aucun (requis) | domaine public, injecté dans le Caddyfile |
| `CARD_API_SALT` | aucun (requis, généré par `make env`) | sel du hachage des IP du journal ; fixe en prod pour des comptes d'utilisateurs distincts stables |
| `CARD_API_RATE_COMPUTE` | 10 | requêtes de calcul (extract/trend/jobs) par IP/minute |
| `CARD_API_RATE_LIGHT` | 60 | requêtes de catalogue par IP/minute |
| `CARD_API_SYNC_STATIONS` / `CARD_API_SYNC_CARDS` | 10 / 20 | plafonds des réponses immédiates ; au-delà, bascule en job |
| `CARD_API_JOB_STATIONS` / `CARD_API_JOB_CARDS` | 100 / 50 | plafonds des jobs (public ; les clés de priorité les lèveront) |
| `CARD_API_JOB_TTL_DAYS` | 7 | rétention des résultats de jobs |
| `CARD_API_JOB_QUEUE_MAX` | 100 | taille de la file (au-delà : 503 + Retry-After) |
| `CARD_API_PRIORITY_STATIONS` / `CARD_API_PRIORITY_CARDS` | 1000 / 226 | plafonds des porteurs de clé de priorité |
| `CARD_REF` / `STASE_REF` | main | révisions de card/stase dans l'image |
| `CARD_API_DATA` | `/data` (volume) | cache des chroniques, jobs et journal (ne pas toucher en Docker) |

Suivi : `make status` (santé, file, disque via /v1/health), `make stats`
(tableau de bord terminal : activité 30 jours, heatmap, file de
calcul), `make watch` (le même, rafraîchi en continu).

Clés de priorité (attribution manuelle, demandées via l'issue
« Clé de priorité » du repo) : `make key name="Prénom Nom, labo"`
crée et affiche le jeton à transmettre, `make keys` liste,
`make key-revoke key=<jeton, préfixe affiché par make keys, ou nom>` révoque. Stockage :
`$CARD_API_DATA/keys.json` (jamais sous git). Le porteur la passe en
en-tête `X-API-Key` ou en paramètre `key=` : quotas par minute levés,
plafonds `PRIORITY_*`, jobs en tête de file. Le journal enregistre le
nom de la clé, jamais le jeton.

## Journal d'usage

`$CARD_API_DATA/usage.jsonl` : une ligne JSON par requête de calcul
servie : horodatage, hachage salé de l'IP (jamais l'IP en clair),
endpoint, nombre de stations, fiches demandées. Sert aux statistiques
d'usage (bilans, dossiers de financement) sans identifier personne.

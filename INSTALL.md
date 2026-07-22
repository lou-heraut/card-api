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
make up         # construit et lance l'API sur 127.0.0.1:8000
```

`DOMAIN` dans `.env` = le nom de domaine public, ou l'IP de la VM en
attendant d'en avoir un (dans ce cas HTTP seulement : aucun
certificat ne peut être émis pour une IP nue).

À ce stade l'API tourne mais n'écoute que la boucle locale
(`curl http://127.0.0.1:8000/v1/health` pour vérifier). C'est le
frontal web qui l'expose au monde ; deux cas :

### La VM a déjà un serveur Apache (cas classique)

```bash
make apache     # génère le vhost depuis DOMAIN, l'active, recharge Apache
```

La cible écrit `/etc/apache2/sites-available/card-api.conf` (un
reverse proxy `*:80` vers `127.0.0.1:8000`), active `mod_proxy`,
vérifie la syntaxe et recharge Apache sans toucher aux autres sites.
Elle est rejouable : changement de domaine = éditer `DOMAIN` dans
`.env` puis relancer `make apache`.

HTTPS, dès qu'un vrai nom de domaine pointe sur la VM :

```bash
sudo apt install certbot python3-certbot-apache   # une fois
sudo certbot --apache -d $DOMAIN                  # crée le vhost 443
```

certbot renouvelle ensuite le certificat tout seul.

### VM nue, sans serveur web : frontal Caddy autoportant

Décommenter `COMPOSE_PROFILES=caddy` dans `.env`, puis `make up` :
docker compose lance aussi un conteneur Caddy qui prend les ports 80
et 443 avec HTTPS automatique. Prérequis : le DNS de `DOMAIN` pointe
vers la VM (pas d'IP dans ce mode), ports 80/443 ouverts en entrée
(sur une VM institutionnelle, penser au pare-feu).

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

### Savoir ce qui tourne

`CARD_REF` et `STASE_REF` valent `main` : chaque construction prend le
dernier état du corpus et du moteur, donc une correction de fiche part en
ligne au `make update` suivant. Ce qui rend un résultat traçable n'est
pas une ref figée, c'est le **commit**, résolu à la construction et
publié par le service :

```bash
curl -s https://$DOMAIN/v1/health | python3 -m json.tool | grep -E "version|commit"
```

Chaque réponse porte les mêmes champs, et les métadonnées portent en plus
la version de chaque fiche employée. Un résultat archivé dit donc
exactement ce qui l'a produit, sans qu'aucun geste manuel ait été
nécessaire.

Les champs `card_swhid` et `stase_swhid` sont des identifiants pérennes
Software Heritage : `swh:1:rev:` suivi du hash du commit, parce que SWH
calcule ses identifiants de révision comme git. Ils s'ouvrent directement
(`https://archive.softwareheritage.org/swh:1:rev:...`) et sont citables
tels quels, les trois dépôts y étant archivés depuis le 2026-07-22.

Épingler une ref précise (`CARD_REF=v0.2.0`) reste possible, par exemple
pour reproduire un résultat ancien, mais ce n'est pas le mode normal.


## Variables d'environnement

Tout se règle dans `.env` (lu par docker compose ; cf. `.env.example`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `DOMAIN` | aucun (requis) | domaine public (ou IP de la VM, HTTP seulement) ; lu par `make apache` et par le Caddyfile |
| `CARD_API_PORT` | 8000 | port hôte (boucle locale) du conteneur ; à changer si 8000 est déjà pris, `make apache` suit |
| `COMPOSE_PROFILES` | absent | `caddy` pour activer le frontal Caddy autoportant (VM nue) ; absent = frontal Apache de la VM (`make apache`) |
| `CARD_API_SALT` | aucun (requis, généré par `make env`) | sel du hachage des IP du journal ; fixe en prod pour des comptes d'utilisateurs distincts stables |
| `CARD_API_RATE_COMPUTE` | 10 | requêtes de calcul (extract/trend/jobs) par IP/minute |
| `CARD_API_RATE_LIGHT` | 60 | requêtes de catalogue par IP/minute |
| `CARD_API_SYNC_STATIONS` / `CARD_API_SYNC_CARDS` | 10 / 20 | plafonds des réponses immédiates ; au-delà, bascule en job |
| `CARD_API_JOB_STATIONS` / `CARD_API_JOB_CARDS` | 100 / 50 | plafonds des jobs (public ; les clés de priorité les lèveront) |
| `CARD_API_JOB_TTL_DAYS` | 7 | rétention des résultats de jobs |
| `CARD_API_JOB_QUEUE_MAX` | 100 | taille de la file (au-delà : 503 + Retry-After) |
| `CARD_API_LTP_SEED` | 0 | graine du départage des ex-æquo en LTP ; fixée pour que deux calculs identiques donnent le même résultat |
| `CARD_API_PRIORITY_STATIONS` / `CARD_API_PRIORITY_CARDS` | 1000 / 226 | plafonds des porteurs de clé de priorité |
| `CARD_REF` / `STASE_REF` | main | état de card/stase installé dans l'image ; le commit résolu est publié par le service |
| `CARD_API_DATA` | `/data` (volume) | cache des chroniques, jobs et journal (ne pas toucher en Docker) |

Suivi : `make status` (santé, file, disque via /v1/health), `make stats`
(tableau de bord terminal : activité 30 jours, heatmap, file de
calcul), `make watch` (le même, rafraîchi en continu). Dans
/v1/health, `disk` décrit le disque de la VM entière (c'est la place
restante qui borne les jobs, le stockage des autres services compte
dedans) et `data` l'empreinte propre de card-api.

Alertes sans surveillance active (optionnel) :
`scripts/veille_sante.py`, une sonde pour cron à lancer depuis une
machine EXTÉRIEURE à la VM (une veille installée sur la VM meurt avec
elle) ; seuils et notification ntfy.sh dans l'en-tête du script.

Clés de priorité (attribution manuelle, demandées via l'issue
« Clé de priorité » du repo) : `make key name="Prénom Nom, labo"`
crée et affiche le jeton à transmettre, `make keys` liste,
`make key-revoke key=<jeton, préfixe affiché par make keys, ou nom>` révoque. Stockage :
`$CARD_API_DATA/keys.json` (jamais sous git), qui ne garde que le
hachage du jeton : il n'est affiché qu'à la création, perdu = en
réémettre un. Le porteur le passe en en-tête `X-API-Key` (préférer
l'en-tête à `key=`, qui laisse le jeton dans les logs du frontal) :
quotas par minute levés, plafonds `PRIORITY_*`, jobs en tête de file,
et `GET /v1/jobs` liste ses jobs. Le journal et les jobs
n'enregistrent que le préfixe du jeton, jamais le jeton ni le nom.

## Journal d'usage

`$CARD_API_DATA/usage-AAAA.jsonl`, un fichier par année (la rotation
est structurelle ; la rétention se règle en supprimant les vieux
fichiers, `make stats` lit tous les `usage*.jsonl` présents) : une
ligne JSON par requête de calcul servie : horodatage, hachage salé de
l'IP (jamais l'IP en clair), endpoint, nombre de stations, fiches
demandées, préfixe de la clé de priorité le cas échéant. Sert aux
statistiques d'usage (bilans, dossiers de financement) sans
identifier personne.

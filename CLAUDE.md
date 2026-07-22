# CLAUDE.md (card-api)

Service web FastAPI des fiches [card](../card/) sur les débits Hub'Eau,
avec diagnostic de stationnarité via [stase](../../EXstat_project/stase/).
Où lire quoi. Un rôle par fichier, chacun l'annonce dans un bandeau de
statut en tête ; ne jamais recopier d'un fichier à l'autre, renvoyer.
- `README.md` : ce que le service fait, endpoints et parcours d'usage.
- `CHANGELOG.md` : ce qui a changé, quand, et où lire le détail.
- `INSTALL.md` : développement et déploiement.
- `docs/dev/API.md` : conception et arbitrages (accès public sans clé,
  quotas IP, journal anonymisé, aspect commercial écarté).
- `docs/dev/CHANTIERS.md` : pistes ouvertes du service, seulement.

## Structure

```
src/card_api/
  main.py       # endpoints /v1 : cards, cards/{id}, stations, extract,
                #   trend (mk défaut AR1, sampling=preferred|MM-JJ,
                #   series=true joint les séries extraites au diagnostic ;
                #   stations_meta=true joint le référentiel Hub'Eau des
                #   stations : résultat autoportant), jobs (POST + statut
                #   + result + DELETE dismiss par ticket ; GET /v1/jobs =
                #   « mes jobs » par clé, 401 sinon), health (file,
                #   disque VM entière vs empreinte data du service)
  jobs.py       # file de calcul asynchrone (forme OGC API Processes) :
                #   202+Location, progression, résultat gelé avec bloc
                #   de provenance, TTL ; plafonds SYNC_*/JOB_* du .env ;
                #   bascule auto des demandes > plafonds synchrones
  hubeau.py     # client Hub'Eau v2 (obs_elab QmnJ, L/s -> m3/s,
                #   pagination next, codes post-refonte) + cache 24 h
  usage.py      # quotas IP (fenêtre glissante, 429+Retry-After),
                #   priority_of (X-API-Key/key=, 401 si inconnue),
                #   journal usage-AAAA.jsonl (rotation annuelle ; IP
                #   hachée salée, préfixe de clé, log_event)
  keys.py       # clés de priorité : jeton affiché UNE fois, keys.json
                #   ne garde que {préfixe: hash SHA-256 + nom} ; le
                #   préfixe est l'identifiant public (journal, job,
                #   listing), le nom ne sort jamais de keys.json ; CLI
                #   add/list/revoke (make key/keys/key-revoke) ; effet =
                #   quotas levés, PRIORITY_*, tête de file, GET /v1/jobs
  serialize.py  # DataFrame -> JSON (records|columns), partagé sync/jobs
  stats.py      # tableau de bord terminal (make stats / make watch) :
                #   sparklines, heatmap 12 semaines, file, disque
tests/          # hors-ligne (Hub'Eau simulé ; jobs ; clés ; retry ;
                #   validation MAKAHO, précision machine) + live
scripts/        # veille_sante.py : sonde cron à lancer HORS VM
                #   (ntfy.sh optionnel ; une veille sur la VM meurt
                #   avec elle)
docs/dev/       # API.md : conception et arbitrages du service ;
                #   CHANTIERS.md : chantiers
                #   ouverts propres au service
.github/        # template d'issue « clé de priorité » (mention RGPD)
CITATION.cff    # citabilité ; codemeta.json = canal Software
                #   Heritage / HAL (pas de Zenodo, choix utilisateur)
Makefile        # ops : make env/up/apache/update/logs/status/stats/watch
compose.yaml    # api sur 127.0.0.1:8000 ; frontal = Apache de la VM
                #   (make apache, vhost généré depuis DOMAIN) ou profil
                #   caddy (COMPOSE_PROFILES=caddy, VM nue) ; .env
```

Dev : `pip install -e ../../EXstat_project/stase -e ../card -e .[dev]`
dans `.python_env/` (cf. INSTALL.md), puis `uvicorn card_api.main:app
--reload` et `pytest`.

> ## À NE JAMAIS FAIRE
>
> - **`note.txt` (et tout fichier de notes de l'utilisateur) : NE PAS
>   L'OUVRIR.** Ni Read, ni `cat`, ni `grep`, ni au détour d'un `git add`.
>   C'est son brouillon personnel : pas de lecture, pas de résumé, pas de
>   « au passage j'ai vu que ». Il n'entre dans aucune tâche sans une
>   demande explicite de sa part, fichier par fichier. Un en-tête qui dit
>   de ne pas lire est un ordre, pas une mise en garde à évaluer.
> - **Pas de `git add -A` ni de `git add .`** : stager nommément les
>   fichiers que l'on a soi-même modifiés. Ce qui traîne dans l'arbre de
>   travail appartient à l'utilisateur.

## Règles propres au service

- Fiches à entrée `Q` uniquement (refus explicite sinon : l'auto-mapping
  de colonnes de card masquerait l'erreur) ; tendance sur les fiches
  `output: series` uniquement (validation par la classification).
- Public par défaut, jamais d'inscription ; le journal ne stocke JAMAIS
  d'IP en clair. Aspect commercial écarté (stats d'usage = preuve
  d'impact pour les financements).
- **La production suit `main`** (`CARD_REF`/`STASE_REF` dans .env) :
  une fiche corrigée part en ligne au `make update` suivant, sans geste
  intermédiaire. Ce qui rend le résultat traçable n'est pas une ref
  figée mais le **commit** résolu à la construction
  (`scripts/resolve_refs.py`), publié par `versions()` dans chaque
  réponse. Ne jamais recopier un numéro de version à la main dans une
  réponse : passer par `versions()`, sinon un point de sortie finira par
  mentir.
- Pas de tiret quadratin (—) dans la prose (docs, messages, commentaires,
  réponses) : reformuler. Perçu comme un marqueur de texte IA.

## État (2026-07-22)

Le service est **déployé** depuis le 2026-07-17 sur la VM de
l'utilisateur, derrière l'Apache qui y sert déjà d'autres services
(`make apache`, port local 8001 via `CARD_API_PORT`, 8000 étant pris).
`DOMAIN` vaut l'IP en attendant un nom de domaine, donc HTTP.

Ce qui a été livré et quand se lit dans `CHANGELOG.md`, ce qui reste
ouvert dans `docs/dev/CHANTIERS.md`. Ces deux fichiers font foi : ne pas
les paraphraser ici, cette section ne doit pas regonfler à chaque
chantier.

**Reste, et c'est bloquant pour la diffusion des clés** : nom de domaine
puis certbot, dont l'utilisateur se charge. Tant qu'on est en HTTP, un
jeton transite en clair.

Deux points à ne pas reperdre :
- le durcissement des clés du 2026-07-18 n'est **pas rétroactif** : au
  prochain déploiement, recréer les clés (`make key`), et les jobs
  antérieurs ne sont pas listables par clé ;
- la sauvegarde du volume a été écartée volontairement : les clés sont
  réémissibles, les jobs éphémères, le journal petit.

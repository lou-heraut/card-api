# CLAUDE.md (card-api)

Service web FastAPI des fiches [card](../card/) sur les débits Hub'Eau,
avec diagnostic de stationnarité via [stase](../../EXstat_project/stase/).
**Conception et arbitrages : `../card/docs/dev/API.md`** (accès public
sans clé, quotas IP, journal anonymisé, commercial écarté).

## Structure

```
src/card_api/
  main.py       # endpoints /v1 : cards, cards/{id}, stations, extract,
                #   trend (mk défaut AR1, sampling=preferred|MM-JJ,
                #   series=true joint les séries extraites au diagnostic),
                #   jobs (POST + statut + result), health (file, disque)
  jobs.py       # file de calcul asynchrone (forme OGC API Processes) :
                #   202+Location, progression, résultat gelé avec bloc
                #   de provenance, TTL ; plafonds SYNC_*/JOB_* du .env ;
                #   bascule auto des demandes > plafonds synchrones
  hubeau.py     # client Hub'Eau v2 (obs_elab QmnJ, L/s -> m3/s,
                #   pagination next, codes post-refonte) + cache 24 h
  usage.py      # quotas IP (fenêtre glissante, 429+Retry-After),
                #   priority_of (X-API-Key/key=, 401 si inconnue),
                #   journal usage.jsonl (IP hachée salée, log_event)
  keys.py       # clés de priorité : data/keys.json, CLI add/list/revoke
                #   (make key/keys/key-revoke) ; effet = quotas levés,
                #   plafonds PRIORITY_*, jobs en tête de file
  serialize.py  # DataFrame -> JSON (records|columns), partagé sync/jobs
  stats.py      # tableau de bord terminal (make stats / make watch) :
                #   sparklines, heatmap 12 semaines, file, disque
tests/          # 27 hors-ligne (Hub'Eau simulé ; jobs ; clés ; retry ;
                #   validation MAKAHO, précision machine) + 2 live
.github/        # template d'issue « clé de priorité »
Makefile        # ops : make env/up/apache/update/logs/status/stats/watch
compose.yaml    # api sur 127.0.0.1:8000 ; frontal = Apache de la VM
                #   (make apache, vhost généré depuis DOMAIN) ou profil
                #   caddy (COMPOSE_PROFILES=caddy, VM nue) ; .env
```

Dev : `pip install -e ../../EXstat_project/stase -e ../card -e .[dev]`
dans `.python_env/` (cf. INSTALL.md), puis `uvicorn card_api.main:app
--reload` et `pytest`.

## Règles propres au service

- Fiches à entrée `Q` uniquement (refus explicite sinon : l'auto-mapping
  de colonnes de card masquerait l'erreur) ; tendance sur les fiches
  `output: series` uniquement (validation par la classification).
- Public par défaut, jamais d'inscription ; le journal ne stocke JAMAIS
  d'IP en clair. Aspect commercial écarté (stats d'usage = preuve
  d'impact pour les financements).
- L'image Docker épingle card/stase par révision (`CARD_REF`/`STASE_REF`
  dans .env) : mise à jour des versions = choix délibéré.
- Pas de tiret quadratin (—) dans la prose (docs, messages, commentaires,
  réponses) : reformuler. Perçu comme un marqueur de texte IA.

## État (2026-07-17) et suite

Étapes 1–3 d'API.md faites (catalogue, stations, extract, trend,
quotas, journal, .env + Makefile) ; validation croisée MAKAHO
(tests/test_makaho.py) et paramètre sampling= ; **motif job fait**
(jobs publics, bascule auto, provenance, health enrichi, tableau de
bord stats.py) ; clés de priorité faites (keys.py, issue template) ;
Hub'Eau durci (retry x3 puis 504 propre, HubEauIndisponible).
**DÉPLOYÉ le 2026-07-17** sur la VM de l'utilisateur derrière son
Apache existant (make apache ; port local 8001 via CARD_API_PORT,
8000 étant pris par une autre API ; DOMAIN = IP en attendant le nom
de domaine, donc HTTP). /v1/trend accepte series=true (séries
extraites jointes au diagnostic) ; examples/carte_tendance_QA.R =
parcours complet clé + job 228 stations RRSE + carte (reprise par
ticket via JOB, jeton dans examples/cle_locale.txt gitignoré).
**Questions ouvertes** (arbitrages à venir, détail :
../card/docs/dev/CHANTIERS.md §1) : listing des jobs par clé,
entropie des tickets, RGPD des clés nominatives (le journal stocke
le nom de la clé). **Reste aussi** : nom de domaine + certbot.

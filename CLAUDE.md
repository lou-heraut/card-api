# CLAUDE.md (card-api)

Service web FastAPI des fiches [card](../card/) sur les débits Hub'Eau,
avec diagnostic de stationnarité via [stase](../../EXstat_project/stase/).
**Conception et arbitrages : `../card/docs/dev/API.md`** (accès public
sans clé, quotas IP, journal anonymisé, commercial écarté).

## Structure

```
src/card_api/
  main.py     # endpoints /v1 : cards, cards/{id}, stations, extract,
              #   trend (mk défaut AR1), health ; réponses {data, meta}
  hubeau.py   # client Hub'Eau v2 (obs_elab QmnJ, L/s -> m3/s,
              #   pagination next, codes post-refonte) + cache 24 h
  usage.py    # quotas IP (fenêtre glissante, 429+Retry-After)
              #   + journal usage.jsonl (IP hachée salée)
tests/        # 11 hors-ligne (Hub'Eau simulé) + 1 live (CARD_API_LIVE=1)
Makefile      # interface ops : make env/up/update/logs/status/stats
compose.yaml  # api + caddy (HTTPS auto) ; config dans .env (cf. .env.example)
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

## État (2026-07-16) et suite

Étapes 1–3 d'API.md faites : catalogue, stations, extract, trend,
quotas, journal, .env + Makefile. **Reste (étape 4)** : motif job
(`/v1/jobs/{id}`) pour les grosses demandes, clés de priorité
(passage devant + plafonds levés, attribution manuelle), premier
déploiement réel sur la VM utilisateur (make env / make up).

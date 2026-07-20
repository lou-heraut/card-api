# API — architecture de l'écosystème et ébauche du service

> Réflexion du 2026-07-16, **arbitrée le jour même** : repo `card-api`,
> service full public sans clé (modèle Hub'Eau) avec quota par IP,
> file d'attente bornée + motif job pour les grosses demandes, clés de
> priorité gratuites à la demande pour les besoins massifs ; extract
> ET trend en v1, multi-stations + plage temporelle + liste de fiches ;
> données utilisateur (POST) reportées. Aspect commercial écarté (les
> statistiques d'usage valent plus, comme preuve d'impact pour les
> financements, que des recettes de niche).

## 1. Où ranger quoi — la carte de l'écosystème

Principe : **card reste une bibliothèque de calcul pure** (installable,
légère, sans dépendance service). Tout ce qui est *service* (réseau,
cache, clés, déploiement) vit dans un repo séparé, comme stase et card
sont déjà séparés par nature (moteur / fiches).

```
stase        moteur d'extraction/stationnarité         (repo existant)
  ▲
card         fiches + classification + fonctions hydro (repo existant)
  │            ├─ scripts/generate_catalog.py → docs/CARDS.md   (Pages)
  │            └─ scripts/generate_skos.py    → docs/card.ttl   (Pages, chantier §4)
  ▼
card-api     service web FastAPI                       (NOUVEAU repo, VM)
               ├─ hubeau.py    client Hub'Eau + cache des chroniques
               ├─ main.py      endpoints v1
               ├─ auth/quotas  clés d'API (statistiques d'usage)
               └─ Dockerfile / systemd (déploiement VM)

Skosmos      navigateur de thésaurus (VM, optionnel)   lit docs/card.ttl
```

Pourquoi un repo séparé (`card-api`, nom de travail) :
- cycles de vie différents (une fiche corrigée ≠ un redéploiement ;
  une évolution d'endpoint ≠ une release card) ;
- dépendances contenues : card garde numpy/pandas/yaml ; l'API ajoute
  fastapi/uvicorn/httpx sans alourdir les utilisateurs de la
  bibliothèque ;
- le déploiement (Docker, secrets, logs) ne pollue pas le package
  scientifique ;
- même logique de frontière que stase/card : la donnée nationale et le
  réseau sont un métier, le calcul en est un autre.

## 2. Ébauche de l'API v1

Toutes les réponses JSON portent `card_version`, `stase_version` et la
`version` de chaque fiche utilisée (discipline de versions en place).
Préfixe `/v1` dès le départ.

### Découverte

- `GET /v1/cards` — le catalogue (metaEX). Filtres = les facettes de
  la classification, dans les deux langues, identiques à
  `card.list_cards()` : `?phenomenon=basses eaux&output=série`,
  `&operator=delta`, `&function=baseflow`, `&search=étiage`, `&lang=`.
- `GET /v1/cards/{id}` — détail d'une fiche (info + lien vers le YAML
  source sur GitHub).
- `GET /v1/stations?dept=07&river=Ardèche&bbox=...` — recherche de
  stations (proxy du référentiel Hub'Eau) pour ne pas obliger à
  connaître les codes à l'avance.

### Calcul

- `GET /v1/extract?stations=H5920010,K0550010&cards=QA,VCN10&start=1970-09-01&end=2020-08-31`
  — télécharge les chroniques journalières Hub'Eau
  (`hydrometrie/obs_elab`, QmnJ), exécute card, renvoie
  `{meta, metaEX, dataEX}` ; `&format=csv` possible. `stations` est
  une liste (plafonnée en public, déplafonnée avec clé de priorité) ;
  `start`/`end` optionnels (défaut : chronique complète).
- `GET /v1/trend?stations=...&cards=QA,VCN10&mk=INDE` — enchaîne
  extraction + `stase.trend` (Mann-Kendall/Sen) : le diagnostic de
  stationnarité complet, à la MAKAHO. Mêmes paramètres qu'extract.
- Grosses demandes (au-delà d'un seuil stations×fiches) : motif
  **job** — la requête renvoie `{job_id}`, résultat sur
  `GET /v1/jobs/{id}` quand il est prêt.
- (reporté) `POST /v1/extract` sur données fournies par l'utilisateur.

### Infrastructure — accès en trois étages (modèle Hub'Eau)

1. **Public sans clé** (défaut) : quota par IP (requêtes/minute) et
   plafond de stations par appel — zéro friction.
2. **File d'attente bornée** avec travailleurs pour les endpoints de
   calcul : en saturation le service fait patienter (429 +
   Retry-After, ou motif job), il ne s'écroule pas.
3. **Clés de priorité** gratuites, attribuées à la demande (manuel au
   début) : passage devant dans la file + plafonds levés, pour les
   besoins massifs (en-tête `X-API-Key`). Pas d'inscription pour
   l'usage normal.

- **Journal d'usage** anonymisé (IP hachée, endpoint, stations,
  fiches, date) → la matière première des bilans d'impact pour les
  dossiers de financement, sans gestion de comptes.
- **Cache à deux étages** : chroniques par station (TTL quotidien —
  les séries validées bougent peu) ; résultats d'extraction par
  (station, fiche, version de fiche) — l'invalidation est offerte par
  la discipline de versions.
- Respecter la politique de débit Hub'Eau (taille de page, pauses) ;
  bannière de provenance des données (Licence Ouverte, eaufrance).
- **Formats de réponse (arbitré 2026-07-16)** : JSON `records` par
  défaut (convention de l'écosystème, Hub'Eau compris) + option
  `orient=columns` (colonnaire, compact, rechargeable en DataFrame) ;
  gzip systématique. Le caractère FAIR vient de l'auto-description
  (metaEX avec unités/labels bilingues, source, licence, versions dans
  chaque réponse), pas de l'orientation. Évolution possible si une
  demande d'interopérabilité géo/climat se présente : **CoverageJSON**
  via le patron OGC API-EDR (le standard des séries temporelles
  environnementales) — non prioritaire.

## 2 bis. Déploiement : Docker (arbitré 2026-07-16)

`docker compose` à deux services sur la VM :
- **api** : image card-api (uvicorn+FastAPI) qui installe card et
  stase depuis GitHub à révision épinglée (traçabilité : API x.y =
  card @tag + stase @tag) ; concurrence bornée en-process (sémaphore
  sur les endpoints de calcul) — pas de Redis/worker externe en v1 ;
- **caddy** : reverse proxy, HTTPS automatique (Let's Encrypt) ;
- volume persistant pour le cache des chroniques et le journal d'usage.
Mise à jour = `docker compose pull && up -d` ; SKOS mis de côté pour
l'instant (chantier indépendant, cf. §4 et CHANTIERS §6).

## 3. Étapes proposées

1. Squelette card-api : FastAPI + `GET /v1/cards` (zéro réseau, juste
   card) — déployable immédiatement, valide la chaîne VM.
2. Client Hub'Eau + cache + `GET /v1/extract` sur quelques fiches.
3. Quotas IP + file bornée + journal, puis `/v1/trend` et le motif
   job ; clés de priorité en dernier (config manuelle).
4. Page de doc auto (OpenAPI/Swagger, gratuite avec FastAPI) liée
   depuis les Pages card.

## 4. Articulation avec l'export SKOS

Le SKOS n'est **pas** un service : c'est un artefact de publication de
la classification, qui vit dans card (source de vérité :
`src/card/topics.yaml` + les blocs classification).

La conception de l'export (generate_skos.py, concept schemes par
facette, publication `docs/card.ttl` sur GitHub Pages, URIs w3id.org,
Skosmos optionnel) était décrite ici par accident de rangement. Elle a
été rapatriée le 2026-07-20 dans card, `docs/dev/CHANTIERS.md` §6, avec
le reste du sujet.

Ce qui reste du ressort du service : l'API pourrait exposer un
`GET /v1/concepts` renvoyant vers ces URIs. C'est un renvoi, pas une
source, et rien ne presse tant que l'export n'existe pas.

## 5. Arbitrages (rendus le 2026-07-16)

1. Nom du repo : **card-api**.
2. `POST /v1/extract` (données utilisateur) : **reporté**.
3. `/v1/trend` : **en v1** avec extract ; multi-stations, plage
   temporelle et liste de fiches sur les deux.
4. Accès : **full public sans clé** (quota IP bas) + file d'attente
   bornée/motif job en cas de charge + **clés de priorité gratuites à
   la demande** pour les besoins massifs (attribution manuelle).
5. w3id.org pour les URIs SKOS : à confirmer le moment venu (pas
   bloquant).

## 6. État d'avancement (2026-07-16)

Tout est réalisé dans le repo card-api sauf le déploiement VM :
catalogue, stations, extract, trend (défaut AR1), quotas + journal
anonymisé, paramètre `sampling=preferred|MM-JJ` (écrase la fenêtre
annuelle des fiches, protocole MAKAHO, validé contre leurs exports à
la précision machine), motif job PUBLIC en forme OGC API Processes
(202 + Location, bascule automatique au-dessus des plafonds
synchrones, résultat gelé avec bloc de provenance, seuils dans .env),
clés de priorité (attribution manuelle via issue, quotas levés +
plafonds relevés + tête de file), retry/504 Hub'Eau, tableau de bord
terminal (make stats/watch). Détails : CLAUDE.md et INSTALL.md de
card-api.

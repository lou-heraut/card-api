# Journal des modifications

Évolutions notables de `card-api`, le service web qui expose les fiches
CARD sur les chroniques Hub'Eau. Format inspiré de [Keep a
Changelog](https://keepachangelog.com/fr/1.1.0/). Les paquets `card` et
`stase` tiennent chacun le leur.

**Numérotation.** Le service n'est pas une bibliothèque : personne ne
l'importe, il est déployé. Il suit `main` pour card comme pour stase, si
bien qu'une correction arrive en ligne au `make update` suivant. Ce qui
rend un résultat reproductible n'est donc pas un numéro figé mais le
**commit** que chaque réponse publie, résolu à la construction de
l'image, accompagné de son identifiant pérenne Software Heritage
(`swh:1:rev:<commit>`). Les trois dépôts sont archivés sur Software
Heritage depuis le 2026-07-22, donc ces identifiants résolvent. Publier
une version tient en une commande : `python scripts/set_version.py
0.3.0`, qui accorde `pyproject.toml`, `CITATION.cff` et
`codemeta.json`.
Chaque entrée dit ce qui a changé et renvoie au document qui l'explique.
Rien n'est recopié ici : une information recopiée finit par mentir à un
des deux endroits.

## Non publié

### Ajouté

- **Revue FAIR (2026-07-24) et premiers correctifs.** Aucun changement
  récent de card ne casse le service (les 41 tests hors-ligne passent
  contre le card à jour : le rangement des fiches par régime et les
  renommages remontent par l'API Python, jamais par des chemins). Livré
  en phase 1 :
  - **route d'accueil `GET /v1`** : décrit le service, relie l'écosystème
    (card définit, stase calcule, Hub'Eau fournit) et pointe la
    réutilisation (API ponctuelle, lib Python, citation par swhid) ;
  - **bloc `rights`** dans les réponses de résultat et l'accueil : données
    Hub'Eau en Licence Ouverte / Etalab 2.0, définitions en GPL-3.0,
    résultat citable. Le trou FAIR-Reusable le plus réel (les droits sur
    la sortie n'étaient énoncés nulle part) ;
  - **CORS** ouvert (lecture) : un site web tiers peut appeler le service ;
  - **OpenAPI enrichi** : description qui situe le projet, `contact`,
    `license_info`, endpoints groupés par tags (service, cards, data,
    stations, jobs).

  Plan complet et phases suivantes : `docs/dev/PLAN_FAIR.md`.

- **Thème de `/docs`, validé sur maquette avant d'être appliqué.** Le
  Swagger par défaut était blanc, pleine largeur et exigeait un clic
  « Try it out » à chaque essai. La page est désormais servie par le
  service : sombre, colonne centrée, champs éditables d'emblée, exemples
  pré-remplis (on ouvre `/docs` et on exécute une vraie requête sans rien
  chercher). Trois partis pris, chacun venu d'un retour :
  - **gris strictement neutres et gamme ouverte** (creux `#0e0e0e`, fond
    `#131313`, bloc `#1d1d1d`, filet `#383838`, texte `#ececec`) : des
    valeurs tassées près du noir donnaient un effet de filtre basse
    luminosité, ce sont les paliers qui font le relief ;
  - **la couleur ne sert qu'aux méthodes HTTP, et jamais seule.** Elle
    évite l'axe rouge/vert pour rester lisible en cas de daltonisme (POST
    vers le bleu-vert, DELETE vers l'orange) ; le mot GET, POST ou DELETE
    reste le repère, la teinte n'est qu'un renfort ;
  - **hiérarchie par la typographie** (taille, graisse, sans contre mono)
    plutôt que par la couleur.

  La palette vit en variables CSS en tête de `_DOCS_CSS` : la retoucher ne
  demande pas de lire le reste. La barre de couleur au bord des blocs est
  retirée mais laissée en commentaire, pour y revenir sans la réécrire.

- **La fiche dessinée et le vocabulaire, servis** (phase 2). Deux
  représentations d'une même fiche, sans mélanger les publics :
  - `GET /v1/cards/{id}` reste **JSON**, pour les machines ;
  - `GET /v1/cards/{id}/figure` rend la fiche **dessinée** en
    `text/plain` : chaîne de calcul, réglages, fenêtre sur douze mois,
    sorties. On comprend ce qu'une fiche calcule sans lire son YAML.
  - `GET /v1/vocabulary` donne les valeurs valides de chaque facette
    (fr/en), c'est-à-dire les filtres acceptés par `/v1/cards` : de quoi
    construire une requête juste ou peupler un menu sans deviner.

  Au passage, le détail d'une fiche appelle `card.info(quiet=True)` : la
  figure ne part plus dans les logs du serveur à chaque requête, calculée
  pour rien. Nécessite card ≥ le commit qui ouvre `card.figure` et
  `card.vocabulary`.

### Modifié

- README : les cinq exemples Python et les quatre exemples R sont
  rejoués contre une instance locale à Hub'Eau simulé, ce qui n'avait
  plus été fait depuis leur écriture. Tous passent. Ajoutés :
  `stations_meta=true`, qui rend un résultat autoportant et n'était pas
  documenté, les deux liens vers la définition d'une fiche, et une
  section « Citer » qui reflète la provenance réellement publiée plutôt
  que la seule version de card.

### Ajouté

- **Empreinte des données d'entrée** (`data_fingerprint`), qui répond à
  une question et une seule : deux résultats reposent-ils sur la même
  donnée ? Hub'Eau révise ses chroniques, et sans elle un écart entre
  deux calculs ne se distinguait pas d'un changement de code, il fallait
  enquêter. Le résultat gelé d'un job porte en plus le détail par station
  (`data_fingerprints`), la verbosité étant utile dans l'artefact qu'on
  archive et déplacée dans une réponse immédiate.

  Calculée sur les octets des colonnes et non sur le fichier de cache :
  gzip inscrit un horodatage dans son en-tête, donc deux compressions
  d'une même donnée donnent des octets différents. Passer par les
  tableaux rend aussi l'empreinte indépendante du format CSV et des
  versions de pandas. Prise sur la chronique entière, avant tout filtre
  de période, puisque c'est la source qu'on identifie. Coût mesuré :
  2 ms par station, soit un demi-dixième de seconde pour les 228 stations
  du RRSE.

### Corrigé

- **Le LTP n'était pas reproductible.** Il départage les ex-æquo au
  hasard, choix documenté dans le `tools.R` d'origine, et `stase` permet
  de fixer la graine ; le service ne la passait pas. Deux appels
  identiques rendaient donc des p-values différentes (mesuré : 0.90398,
  0.90446, 0.90401 sur la même série). Une graine est désormais fixée
  en dur, et publiée dans la provenance d'un
  job, pour qu'un calcul puisse être rejoué.
- **`data_fetched_at` datait le calcul, pas la lecture des données.** Le
  cache des chroniques vit 24 h : les deux pouvaient différer d'autant,
  alors que Hub'Eau révise ses données et que c'est la date de lecture
  qui rend deux résultats comparables. La date vient maintenant du cache
  lui-même, et à défaut d'information, de l'instant courant, qui reste
  une borne vraie.

### Ajouté

- Les réponses **synchrones** portent `data_fetched_at`, qui n'existait
  que dans les jobs. Un résultat immédiat est tout aussi archivable
  qu'un résultat de job, il doit dire la même chose.

## 0.2.0 (2026-07-22)

### Corrigé

- La validation croisée MAKAHO échouait sur `tQJXA` et `dtLF` depuis
  stase 0.4.0, sans que personne le voie : le test comparait
  `a_relative` au `a_normalise` de R pour des variables **non
  relatives**. Or 0.4.0 a délibérément séparé les registres, et
  `a_relative` vaut désormais NaN dans ce cas, là où R recopiait la
  pente absolue. Le test vérifie maintenant le contrat réel, en prouvant
  au passage que la copie de R était bien redondante avec `a` (aucune
  information perdue). La parité de fond, `a`, `p` et `H` contre MAKAHO
  à 1e-12 sur 228 stations, n'a jamais bougé.

### Modifié

- Documentation restructurée comme dans card et stase : un rôle par
  fichier, un bandeau de statut en tête. `docs/dev/API.md` perd son
  état d'avancement figé au 2026-07-16 (il annonçait encore le
  déploiement comme restant à faire) et ses étapes, toutes réalisées,
  au profit de ce journal ; il garde la carte de l'écosystème, le modèle
  d'accès et les arbitrages, qui engagent encore le code.

## 2026-07-20

### Corrigé

- `GET /v1/cards/{id}` déguisait un bug serveur en fiche inconnue.
  `card.info()` lève `FileNotFoundError` pour deux causes sans rapport,
  la fiche absente du corpus ou un fichier de données du paquet
  illisible ; le `except` attrapait les deux et répondait 404, ce qui a
  fait chercher l'erreur du côté de l'identifiant demandé alors que
  l'empaquetage de card était en cause. Seule la première reste un 404,
  la seconde repart en 500 avec sa trace.

### Modifié

- La conception du service est rapatriée dans ce dépôt, et la conception
  de l'export SKOS repart dans card, dont la classification est la
  source de vérité. Chaque sujet chez son propriétaire.

## 2026-07-18

### Ajouté

- `GET /v1/jobs` liste les jobs de l'appelant, sur présentation de sa
  clé. Pas de listing public.
- `DELETE /v1/jobs/{id}` (dismiss OGC), le ticket faisant capacité, avec
  un 409 tant que le calcul tourne : le calcul n'est pas interruptible.
- `stations_meta=true` sur extract, trend et jobs joint les
  enregistrements du référentiel Hub'Eau, ce qui rend un résultat
  autoportant. La carte d'exemple n'a plus besoin d'une seconde série
  d'appels.
- `CITATION.cff` et `codemeta.json` (voie Software Heritage et HAL, pas
  de Zenodo, choix de l'utilisateur), plus une section « Citer » au
  README.
- `scripts/veille_sante.py` : surveillance de santé à lancer **hors de
  la VM** par cron, une sentinelle hébergée sur la machine surveillée
  mourant avec elle. Seuils par variables d'environnement, notification
  ntfy.sh optionnelle.

### Modifié

- **Clés de priorité durcies.** `keys.json` ne stocke plus que
  `{préfixe: sha256, nom}` : le jeton n'est montré qu'une fois, à la
  création, et la recherche se fait par empreinte. Le journal et les
  jobs enregistrent le préfixe et jamais le nom, si bien que le lien
  entre préfixe et personne ne vit que dans `keys.json` et meurt avec la
  révocation. Mention RGPD ajoutée au formulaire de demande. Tickets de
  job portés à 64 bits. **Non rétroactif** : les clés sont à recréer au
  déploiement.
- Journal segmenté par année (`usage-AAAA.jsonl`) : la rotation devient
  structurelle, la rétention redevient de la gestion de fichiers.
- `/v1/health` distingue le disque de la VM entière, qui est ce qui
  borne les jobs et qui est partagé avec les autres services, de
  l'empreinte propre du service (cache, jobs, journal). Fin de la
  confusion « le disque a l'air plein ».

## 2026-07-17

### Ajouté

- **Premier déploiement**, sur la VM de l'utilisateur. Le frontal n'est
  pas Caddy mais l'Apache déjà en place, qui sert d'autres services :
  `make apache` génère le vhost reverse-proxy depuis `DOMAIN`, le
  conteneur n'écoute que sur `127.0.0.1`, et `CARD_API_PORT` rend le
  port hôte configurable (8000 était déjà pris). Caddy devient un profil
  compose optionnel, pour le cas d'une VM nue.
- `GET /v1/trend?series=true` joint les séries extraites du calcul qui a
  produit la tendance, ce qui lève le doute entre cache et révisions de
  données quand on compare deux appels.
- `examples/carte_tendance_QA.R` : carte de tendance sur les 228
  stations du RRSE, de bout en bout par le motif job.

### Corrigé

- `/v1/health` annonçait la version « dev » : `CARD_VERSION` cherchait
  une distribution nommée `card` alors qu'elle s'appelle `card-stase`,
  le nom PyPI étant en attente.

### Modifié

- README réécrit autour des parcours d'usage, chaque exemple vérifié par
  exécution contre une instance locale.

## 2026-07-16

Création du service, de l'ébauche au dépôt complet.

### Ajouté

- `GET /v1/cards` et `/v1/cards/{id}` : le catalogue, filtrable par les
  facettes de la classification dans les deux langues.
- `GET /v1/stations` : recherche dans le référentiel Hub'Eau, pour ne
  pas avoir à connaître les codes à l'avance. Les codes ont changé à la
  refonte Hydro, ce qui rend le service d'autant plus utile.
- `GET /v1/extract` : chroniques journalières Hub'Eau (`obs_elab`,
  QmnJ) mises en cache, puis exécution des fiches. Les fiches dont
  l'entrée n'est pas un débit sont refusées explicitement, faute de quoi
  l'affectation automatique de colonne de card calculerait une variable
  de pluie sur du débit, en silence.
- `GET /v1/trend` : extraction puis `stase.trend`, sur les seules fiches
  `output: series`, ce que la classification permet de vérifier. AR1 par
  défaut, les étiages étant autocorrélés.
- `sampling=preferred|MM-JJ` : impose la fenêtre annuelle déclarée par
  la fiche, ce qui reproduit le protocole de MAKAHO et rend les stations
  comparables entre elles.
- **Motif job** en forme OGC API Processes : `POST /v1/jobs` répond 202
  et Location, le suivi donne l'avancement par station, et le résultat
  est gelé avec un bloc de provenance (paramètres, versions, date de
  récupération des données) qui le rend citable. Une demande synchrone
  trop grosse bascule automatiquement en job au lieu d'être refusée.
  File bornée en mémoire et fils d'exécution, sans Redis.
- **Quotas par IP** en fenêtre glissante, avec 429 et Retry-After, et
  journal d'usage anonymisé : l'IP n'est jamais stockée en clair, elle
  est hachée avec un sel. C'est la matière première des bilans d'impact
  pour les dossiers de financement.
- **Clés de priorité** gratuites, attribuées à la main sur demande :
  quotas par minute sautés, plafonds relevés, et tête de file.
- Tableau de bord terminal (`make stats`, `make watch`).
- Client Hub'Eau durci : trois tentatives à pause croissante sur
  expiration, erreur de transport ou 5xx, puis un 504 propre avec
  Retry-After plutôt qu'un 500 brut.
- **Validation croisée MAKAHO** : `stase.trend` sur leurs séries
  agrégées reproduit leurs tendances à la précision machine (1e-12, 228
  stations). Point de protocole découvert à cette occasion : MAKAHO
  n'utilise pas l'échantillonnage adaptatif des fiches, il impose leur
  fenêtre préférée partout.

Détail de la conception : `docs/dev/API.md`. Déploiement et variables
d'environnement : `INSTALL.md`.

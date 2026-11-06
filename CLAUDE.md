# CLAUDE.md (card-api)

Service web FastAPI des fiches [card](../card/) sur les débits Hub'Eau,
avec diagnostic de stationnarité par [stase](../../EXstat_project/stase/).

## Où lire quoi

Un rôle par fichier, chacun l'annonce dans un bandeau de statut en tête ;
ne jamais recopier d'un fichier à l'autre, renvoyer.

- `README.md` : ce que le service fait, endpoints et parcours d'usage.
- `INSTALL.md` : développement et déploiement, variables d'environnement.
- `ROADMAP.md` : ce qui reste à faire, et dans quel ordre.
- `CHANGELOG.md` : ce qui a été fait, quand, et où lire le détail ; la
  doctrine des numéros de version est en tête.
- `dev/decisions.md` : les repères du service avec leur date et leur
  raison (accès public, représentations, CSV, fraîcheur, exploitation,
  diffusion). Les raisons propres à un module sont dans sa docstring.
- `dev/docs-theme.md` : le thème de `/docs`, comment il se fabrique et se
  vérifie.
- `dev/plans/` : les plans datés, chacun avec son état en tête. Pour le
  cache : `2026-09-18_cache.md` garde les mesures qui ont commandé chaque
  décision et la règle de la clé, `2026-09-19_cache-followup.md` ce qui
  reste. C'est là qu'on regarde avant de toucher au cache.
- `dev/audits/` : états des lieux datés, figés une fois écrits ; leurs
  suites partent dans `ROADMAP.md`.

## Structure

Une ligne par module : ce qu'il fait, et ce qu'il ne faut pas casser. Le
pourquoi est dans sa docstring.

```
src/card_api/
  pipeline.py  LA chaîne de calcul, écrite une fois, appelée par les deux
               portes (réponse immédiate et file). Ne connaît rien de HTTP.
               `normalise` applique défauts et validations AVANT la
               bifurcation. Ne jamais refaire de boucle de chroniques
               ailleurs. Porte la clé du second étage de cache (`cle_serie`) :
               tout paramètre ajouté à l'extraction y entre le même jour.
               `extraction()` calcule les manquants en un seul appel groupé
               et recolle dans l'ordre trié du moteur.
  main.py      les routes. Une représentation = une URL, jamais un paramètre
               `format` ; les `.csv` portent leur provenance en lignes `#` ;
               paramètres déclarés une fois (`TrendParams`, `ExtractParams`).
               Dans `/v1/cards`, `id` est le nom du FICHIER de fiche, pas
               `variable_en`. `/docs` est Swagger UI habillé.
  static/      swagger-colors.css GÉNÉRÉ par scripts/build_theme.py (à refaire
               seulement à une montée de Swagger UI) ; theme-identity.css
               ÉCRIT À LA MAIN, c'est lui qu'on retouche ; inrae.svg.
  jobs.py      la file (forme OGC API Processes) et les plafonds : au-delà
               d'un seuil, la demande devient un job. Une même URL peut partir
               en file puis répondre en direct : c'est voulu.
  hubeau.py    le client Hub'Eau. Colonne `code_station`, le nom de la
               source. L'empreinte hache aussi le NOM des colonnes.
  cache.py     le disque, et son seul propriétaire. Deux dates à ne jamais
               confondre : la collecte (fraîcheur) et la dernière lecture
               (éviction). Une DEMANDE marque la lecture, un rafraîchissement
               jamais. Le cache accélère, il ne doit jamais être une
               dépendance.
  pool.py      tâche de fond : rafraîchit ce qui est déjà en cache, un peu
               avant l'âge accepté, et évince ce que personne ne lit. Ne
               marque aucune lecture.
  usage.py     quotas par IP, larges à dessein ; un refus est journalisé
               comme ÉVÉNEMENT, jamais comme usage. Journal sans IP en clair.
  keys.py      clés de priorité : jeton affiché une fois, seul son hachage
               est gardé ; le nom ne sort jamais de keys.json.
  stats.py     `make stats` : calcul et découverte ne s'additionnent jamais,
               toutes les lignes restent affichées, zéro compris.
tests/         hors ligne (Hub'Eau simulé) + live. Garde-fous à connaître :
               `test_les_deux_portes_rendent_le_meme_contrat` compare les
               enveloppes ; aucun job ne doit survivre à son test (conftest) ;
               simuler `jobs.submit` quand seule l'enveloppe compte. Un test
               qui protège l'ancien comportement et reste vert après un
               changement de comportement est un SIGNAL D'ARRÊT.
scripts/       veille_sante.py, sonde à lancer HORS de la VM ;
               resolve_refs.py, set_version.py, build_theme.py.
Makefile       `make` liste les cibles ; `make lint` passe par le ruff du
               venv, jamais celui du PATH.
compose.yaml   api sur 127.0.0.1 ; frontal = l'Apache de la VM (`make
               apache`) ou le profil caddy sur une VM nue.
```

Dev : `pip install -e ../../EXstat_project/stase -e ../card -e .[dev]`
dans `.python_env/` (cf. INSTALL.md), puis `uvicorn card_api.main:app
--reload`, `pytest` et `make lint`.

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
> - **Ne JAMAIS signaler un fichier non suivi.** Un fichier non suivi est
>   à l'utilisateur : brouillon, essai, sortie jetable. Il a le droit d'en
>   avoir, il n'a pas à s'en justifier, et le lui rappeler est une
>   nuisance. Pas de « au passage, j'ai vu que », pas de « je n'y touche
>   pas », pas de récapitulatif en fin de réponse. On n'en parle que s'il
>   en parle le premier. Le répertoire `bac/` est ignoré par git : c'est
>   là qu'on lui propose de déposer ce qu'il veut faire disparaître du
>   `git status`, une fois, sans y revenir.

## Règles propres au service

- Fiches à entrée `Q` uniquement, avec un refus explicite : l'auto-mapping
  de colonnes de card masquerait l'erreur. Tendance sur les fiches
  `output: series` uniquement.
- Public par défaut, jamais d'inscription ; le journal ne stocke JAMAIS
  d'IP en clair.
- La production suit `main` ; ne jamais recopier un numéro de version à
  la main dans une réponse, passer par `versions()`. Le déploiement reste
  un geste manuel (`dev/decisions.md`).
- **Jamais de fenêtre de choix à cocher** (outil de question à options) :
  elle coupe la conversation. Une décision à prendre s'expose en prose,
  avec une recommandation, et se discute dans le fil.
- Pas de tiret quadratin (—) dans la prose (docs, messages, commentaires,
  réponses) : reformuler. Perçu comme un marqueur de texte IA.
- **Aucun décompte ni plafond écrit en clair dans une description
  d'API.** La phrase reste, la valeur bouge, et le contrat ment sans que
  rien ne rougisse : c'est arrivé deux fois, les 2026-07-28 et 29. Une
  description dit la règle ; les valeurs se lisent dans `/v1` (bloc
  `limits`), alimenté par les modules qui les appliquent. Deux tests le
  tiennent, dans `tests/test_api.py`.

## Versions et citation

Doctrine complète en tête de `CHANGELOG.md`. Ce qu'il ne faut pas rater :

- **Au quotidien : rien**, sauf l'entrée `## Non publié` du CHANGELOG.
  **La proposer soi-même**, l'utilisateur ne le demandera pas.
- **Le numéro est un contrat** : `api_version` part dans chaque réponse et
  dans l'OpenAPI, donc un changement de ce qu'un client voit (route,
  champ, empreinte, quota) se publie le jour où il est livré. **Le
  proposer soi-même** : l'utilisateur l'a demandé explicitement le
  2026-08-05. `python scripts/set_version.py --etat` donne les faits.
- **Publier** : `python scripts/set_version.py 0.9.0` accorde
  `pyproject.toml`, `CITATION.cff` et `codemeta.json` ; jamais un numéro
  à la main (`tests/test_citation.py` refuse le désaccord). Puis section
  de CHANGELOG, commit, `git tag -a vX.Y.Z`, `git push --tags`.
- **SWHID** : `swh:1:rev:<commit>` est calculable sans appel d'API, et
  résout puisque le dépôt est archivé.

## État

Déployé depuis le 2026-07-17 sur la VM de l'utilisateur, derrière l'Apache
qui y sert d'autres services (`make apache`, port local 8001 par
`CARD_API_PORT`). En HTTPS sur `card-api.riverly.inrae.fr` depuis le
2026-07-28. `CARD_API_PUBLIC_URL` reste VIDE en développement, sinon le
« Try it out » d'une instance locale part sur la production.

Ce qui a été livré se lit dans `CHANGELOG.md`, ce qui reste dans
`ROADMAP.md`. Ces deux fichiers font foi : ne pas les paraphraser ici.

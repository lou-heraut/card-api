# Plan : rendre card-api FAIR pour de vrai (en cours)

> **Statut : plan de travail vivant.** Issu de la revue FAIR du
> 2026-07-24. Une phase livrée sort d'ici et devient une entrée de
> `CHANGELOG.md`. Ne pas paraphraser dans d'autres fichiers, renvoyer.

## Constat de la revue

- **Aucune casse** venue des changements récents de card (renommages
  `QJD`/`QJDC10`, rangement des fiches par régime, reclassements
  `QM`→curve / `Bias`→scalar, 3 nouveaux phénomènes). Vérifié : les 41
  tests hors-ligne passent contre le card éditable. card-api n'appelle
  que l'API Python de card (`list_cards`/`extract`/`info`/`trend`),
  jamais de chemins ; `Path(script_path).stem` reste juste quelle que
  soit la profondeur du dossier.
- **Base FAIR déjà solide** : provenance dans chaque réponse
  (`versions()` = commit + SWHID card/stase), swhid par fiche, liens
  `yaml` (GitHub au commit exact) + `archive` (Software Heritage), accès
  ouvert sans clé, OpenAPI auto, `CITATION.cff` + `codemeta.json` dans
  les trois dépôts, jobs en forme OGC API Processes.
- **Trous « FAIR en pratique »** : droits sur les *données* absents des
  réponses (seule la licence du code est citée) ; vocabulaire de
  classification non exposé ; service non trouvable comme jeu de données
  (pas de route d'accueil) ; la figure `card.info` n'est pas servie ;
  pas de CORS ; OpenAPI maigre.

## Décisions (utilisateur, 2026-07-24)

- **Figure** : `/v1/cards/{id}` reste **JSON par défaut** ; l'ASCII art
  passe par un **endpoint séparé** (`/v1/cards/{id}/figure`, `text/plain`),
  pas dans le dict. Les deux existent, le dict est le défaut.
- **CORS** : oui, usage navigateur voulu (connecter un site web).
- **Droits/citation** : les fichiers de citation existent déjà dans les
  trois paquets ; il faut les **surfacer** (bloc `rights`/`cite` dans les
  réponses), et énoncer la licence des données Hub'Eau.
- **Différé** (comme UCUM) : **SKOS, JSON-LD, DCAT**. On verra après.
  UCUM est une piste *de card* (notée dans son CHANTIERS).
- `QM`/`Bias` hors tendance : normal et automatique, ne pas traiter.
  Limite structurelle notée dans le CHANTIERS de card.

## Phases

- **Phase 0 — hygiène** : ne plus laisser `card.info` imprimer la figure
  dans les logs du serveur à chaque `GET /v1/cards/{id}` (calcul jeté).
  Se règle avec la phase 2 (une fonction card qui *rend* la figure sans
  l'imprimer).
- **Phase 1 — FAIR quick wins** (card-api seul, sûr) :
  - CORS (public, GET + POST + DELETE) ;
  - OpenAPI enrichi : `contact`, `license_info`, `openapi_tags` +
    tag par endpoint, `externalDocs` ;
  - route d'accueil `GET /v1` : décrit le service et relie l'écosystème
    (card, stase, Hub'Eau), JSON simple (pas de DCAT pour l'instant) ;
  - bloc `rights` : données = Licence Ouverte Etalab 2.0 (via Hub'Eau),
    définitions = GPL-3.0, résultat = œuvre dérivée citable ; inclus dans
    les réponses de résultat (extract, trend, jobs) et l'accueil.
- **Phase 2 — complétude** (touche card) :
  - rendre `card.figure()` public (retourne la chaîne, sans imprimer) et
    `card.info` cesse d'imprimer quand on ne veut que le dict ;
  - `GET /v1/cards/{id}/figure` → `text/plain` ;
  - `GET /v1/vocabulary` : valeurs valides par facette (fr/en) depuis
    `topics.yaml` de card (petit accesseur côté card, ou lecture du
    fichier packagé).
- **Phase 3 — doc** : README/API.md, écosystème explicite (card définit ↔
  stase calcule ↔ card-api sert ↔ Hub'Eau fournit) + pistes de
  réutilisation (API ponctuelle ; lib Python pour le gros ; citer les
  fiches par swhid) + schéma mermaid.
- **Phase 4 — FAIR lourd** (plus tard, sur décision) : UCUM (card),
  JSON-LD/SKOS, catalogue DCAT pour moissonneurs.

## Avancement

- [x] Phase 0 — `card.info(quiet=True)` : plus de figure dans les logs
      (2026-07-24)
- [x] Phase 1 — CORS, OpenAPI enrichi + tags, route `/v1`, bloc `rights`
      (2026-07-24)
- [x] Phase 2 — `card.figure`/`card.vocabulary` ouverts côté card ;
      `/v1/cards/{id}/figure` (text/plain) et `/v1/vocabulary`
      (2026-07-24)
- [x] Phase 3 — README : URL finale card-api.riverly.inrae.fr, schéma
      mermaid de l'écosystème, tableau « quelle porte prendre » avec des
      liens qui montrent. Le champ `reuse` reste une phrase, choix acté :
      la version structurée n'apportait rien (2026-07-24)
- [x] Thème de /docs — raté le 2026-07-24 au matin, livré le même jour.
      Le premier essai (~130 règles écrites à la main) ne recouvrait
      qu'une fraction du CSS de Swagger : fond sombre, moitié des
      composants restés clairs, pire que le défaut. Il avait été
      « vérifié » en constatant que le CSS était *injecté*, jamais que la
      page *rendait*. Le second part du CSS réel de Swagger et se juge
      sur des captures d'écran. Conception, palette et façon de vérifier :
      `docs/dev/THEME_DOCS.md`.

- [ ] Phase 4 (réserve) — UCUM, JSON-LD/SKOS, DCAT

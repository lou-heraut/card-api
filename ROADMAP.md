> **Statut : registre vivant.** Ce fichier ne contient que des pistes
> **ouvertes**, et seulement celles du service web : celles du corpus de
> fiches vivent dans card, celles du moteur dans stase. Un chantier livré
> en sort et devient une entrée de `CHANGELOG.md`, à la racine du dépôt,
> qui renvoie au document expliquant le détail.

# CHANTIERS : pistes ouvertes du service (mise à jour 2026-11-06)

L'ordre retenu, puis trois entrées : ce qui reste du cache, renvoyé au
document qui le porte ; les suites de l'audit du 2026-10-11 ; un objectif
de fond. En réserve, sans date : la phase 4 de `PLAN_FAIR.md`.
Ce qui a quitté ce fichier le 2026-07-29 est parti dans le document qui en
porte la matière, pas à la corbeille :

- le **thème de `/docs`** est refermé. Le bouton « Télécharger » a été
  repris par l'utilisateur, la fenêtre « Authorize » a été vérifiée. Le
  couplage des deux boutons d'un bloc de code, seul reste technique, est
  désormais commenté à l'endroit qui compte, dans
  `static/theme-identity.css`. La doctrine du thème (rien qui ne soit une
  règle CSS, Swagger plutôt qu'une page maison, ce que le calque masque
  et pourquoi) vit dans `THEME_DOCS.md`, où elle sert en travaillant ;
- le **déploiement depuis le CI** n'est pas une piste ouverte, c'est une
  décision prise : réserve explicite de l'utilisateur, `make update`
  reste un geste conscient. Elle est consignée dans `CLAUDE.md`, à ne pas
  reproposer comme une évidence. Le volet tests du CI, lui, est livré ;
- la **veille sur les décomptes écrits dans les textes** est devenue une
  règle de `CLAUDE.md`, avec ses deux tests. Une chose qu'il faut tenir à
  chaque écriture n'est pas un chantier qu'on finira un jour : c'est une
  règle, et sa place est là où on lit les règles.

## L'ordre retenu le 2026-11-05

Le but est que MAKAHO (`../../MAKAHO_project/MAKAHO-next/`) puisse
s'appuyer sur le service. D'où cet ordre, chaque étape renvoyant au
document qui la porte :

```
  1. aligner card-api sur la structure commune (campagne du
     2026-11-06, plan dans ../card/dev/plans/2026-11-06_layout-
     alignment.md) : ce registre devient ROADMAP.md, docs/dev/
     devient dev/, et le CLAUDE.md s'allège
  2. contrat : refus natif des paramètres inconnus, `?key=` retiré,
     B3 (date du pool dans /v1/health), et B5 déjà livré dans le
     dépôt                              une seule version mineure
  3. première clé de priorité : celle de MAKAHO, qui demande plus de
     stations que le plafond public ; les versions redeviennent alors
     des engagements (CLAUDE.md)
  4. MAKAHO-next, chantier M1, depuis son propre dossier. Son PLAN.md
     date du 2026-09-18 : il dit encore « rien n'est commencé » et
     liste A1 à A8, tous livrés depuis. Le remettre à jour d'abord.
```

B5 et B6 (`PLAN_CACHE_SUITE.md`) sont livrés le 2026-11-06. Au
déploiement de la version, corriger `CARD_API_SYNC_STATIONS` dans le
`.env` de production et y retirer `CARD_API_POOL_REFRESH_DAYS`.

## Le cache, et ce qu'il reste après lui

Le chantier « ce qui manque pour qu'un client puisse dépendre du service »,
instruit le 2026-09-18 depuis l'audit de migration de MAKAHO, est
**entièrement livré** (service 0.5.0 à 0.8.0, moteur 0.6.5) : il a quitté ce
fichier pour `CHANGELOG.md`, qui dit quand chaque morceau est tombé, et
`PLAN_CACHE.md`, qui garde les mesures et les raisons.

Ce qui reste ouvert est dans **`PLAN_CACHE_SUITE.md`**, écrit après l'audit
du 2026-09-19 et repris le 2026-11-05. Rien n'en est recopié ici : chaque
chantier y porte son état, dans le tableau de tête.

## Les suites de l'audit du 2026-10-11

`audits/2026-10-11_docs-outage-and-complexity.md` : la page `/docs` en
panne, ce qu'elle dit de la complexité du service, et l'envie d'agréger
davantage de données. Sur ses cinq propositions, deux sont faites le jour
même (FastAPI et Swagger UI épinglés, `/docs` ouverte après chaque
`make update`). Restent trois chantiers :

- **Alléger la prose** : `CLAUDE.md` et les récits datés dans le code.
  Se fait dans la phase D de l'alignement, étape 1 de l'ordre ci-dessus.
- **Remplacer le refus maison des paramètres inconnus par celui de
  FastAPI** (`extra="forbid"` sur les modèles de paramètres, ce qui
  suppose d'en faire un aussi pour les filtres de `/v1/cards`), la clé
  ne passant plus que par l'en-tête `X-API-Key`. Changement de contrat,
  donc version mineure. La question préalable est tranchée le
  2026-11-05 : aucune clé n'a été distribuée, `?key=` peut disparaître
  sans casser personne.
- **Écrire le projet d'agrégation avant d'y toucher** : quelles données,
  pour quels usagers, où cela vit, qui l'entretient. L'audit recommande
  un composant à part, que le service lirait comme il lit Hub'Eau.

## Rendre le catalogue lisible, pas seulement exact

Objectif de fond, formulé par l'utilisateur le 2026-07-20 : faire de la
consultation des fiches la partie la plus agréable du service. Aider
quelqu'un à comprendre ce que fait une fiche sans cloner le dépôt.

Le volet « lien citable » est **livré le 2026-07-22** (cf. CHANGELOG) :
chemin dans le corpus au lieu du chemin serveur, lien GitHub vers la
révision réellement exécutée, lien Software Heritage vers le contenu
exact, version et SWHID de chaque fiche dans les métadonnées. Reste le
volet lisibilité.

### Pistes de confort à instruire ensuite

La demande initiale est plus large que le lien. Rendre les fonctions
employées lisibles depuis le catalogue : la colonne `functions` est
aujourd'hui une liste de noms nus (`rollmean_center, nanmin,
return_level`) qui ne dit pas ce que fait chacun. Et donner à lire la
chaîne de traitement d'une fiche, que `method` décrit déjà en prose
numérotée. À instruire avec le chantier documentation de card plutôt
qu'en isolé, puisque la matière vient des fiches.

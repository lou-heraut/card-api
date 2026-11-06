> **Statut : ce qui reste à faire, et seulement cela,** pour le service
> web : le corpus de fiches a son registre dans card, le moteur dans stase.
> Ce qui est fait en sort et devient une entrée de `CHANGELOG.md`, qui
> renvoie au document expliquant le détail. Un point devenu trop lourd
> ouvre un plan daté dans `dev/plans/`, vers lequel ce fichier renvoie
> tant qu'il est en cours.

# Feuille de route de card-api (mise à jour 2026-11-06)

## Vers MAKAHO

Le but est que MAKAHO (`../../MAKAHO_project/MAKAHO-next/`) prenne tout
son contenu scientifique au service. D'où cet ordre :

```
  1. contrat : refus natif des paramètres inconnus, `?key=` retiré,
     date de la dernière passe du pool dans /v1/health (B3),
     et le plafond à froid déjà livré (B5)   une seule version mineure
  2. première clé de priorité : celle de MAKAHO, qui demande plus de
     stations que le plafond public ; les versions redeviennent alors
     des engagements (dev/decisions.md)
  3. MAKAHO-next, chantier M1, depuis son propre dossier. Son PLAN.md
     date du 2026-09-18 : il dit encore « rien n'est commencé » et
     liste A1 à A8, tous livrés depuis. Le remettre à jour d'abord.
```

**Le contrat (étape 1).** Remplacer le refus maison des paramètres
inconnus par celui de FastAPI (`extra="forbid"` sur les modèles de
paramètres, ce qui suppose d'en faire un aussi pour les filtres de
`/v1/cards`), la clé ne passant plus que par l'en-tête `X-API-Key`. C'est
la règle maison qui a cassé `/docs` deux fois (audit du 2026-10-11). Aucune
clé n'a été distribuée (vérifié auprès de l'utilisateur le 2026-11-05),
donc `?key=` peut disparaître sans casser personne. Au déploiement de la
version, corriger `CARD_API_SYNC_STATIONS` dans le `.env` de production
(B5) et y retirer `CARD_API_POOL_REFRESH_DAYS`, qui ne sert plus (B6).

**Ce qui reste du cache** est dans `dev/plans/2026-09-19_cache-followup.md`,
chaque chantier avec son état dans le tableau de tête. Rien n'en est
recopié ici.

## Le projet d'agrégation, à écrire avant d'y toucher

L'envie est formulée : faire du service un lieu qui rassemble des données
environnementales de plusieurs sources. L'audit du 2026-10-11
(`dev/audits/2026-10-11_docs-outage-and-complexity.md`, section 4)
recommande un composant à part, que le service lirait comme il lit
Hub'Eau. Questions à trancher avant toute ligne de code : quelles données,
pour quels usagers, où cela vit, qui l'entretient.

## Rendre le catalogue lisible, pas seulement exact

Objectif de fond, formulé par l'utilisateur le 2026-07-20 : faire de la
consultation des fiches la partie la plus agréable du service, et aider
quelqu'un à comprendre ce que fait une fiche sans cloner le dépôt. Le
volet « lien citable » est livré (2026-07-22, cf. CHANGELOG). Reste la
lisibilité : la colonne `functions` est une liste de noms nus
(`rollmean_center, nanmin, return_level`) qui ne dit pas ce que fait
chacun, et la chaîne de traitement d'une fiche, que `method` décrit déjà
en prose, pourrait se donner à lire. À instruire avec le chantier
documentation de card, puisque la matière vient des fiches.

## Les mentions légales, à faire valider

Les mentions légales du README sont rédigées d'après ce que le code fait.
Éditeur, responsable de publication et hébergeur gagneraient une
validation par le service compétent d'INRAE.

## En réserve, sans date

La phase 4 de la revue FAIR (`dev/plans/2026-07-24_fair.md`) : unités
UCUM, JSON-LD et SKOS, catalogue DCAT pour les moissonneurs. Sur décision,
si un besoin d'interopérabilité se présente.

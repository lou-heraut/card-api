> **Statut : ce qui reste à faire, et seulement cela,** pour le service
> web : le corpus de fiches a son registre dans card, le moteur dans stase.
> Ce qui est fait en sort et devient une entrée de `CHANGELOG.md`, qui
> renvoie au document expliquant le détail. Un point devenu trop lourd
> ouvre un plan daté dans `dev/plans/`, vers lequel ce fichier renvoie
> tant qu'il est en cours.

# Feuille de route de card-api (mise à jour 2026-11-10)

## Vers MAKAHO

Le but est que MAKAHO (`../../MAKAHO_project/MAKAHO-next/`) prenne tout
son contenu scientifique au service. Reste le chantier M1 de
MAKAHO-next, à mener depuis son propre dossier : son `CLAUDE.md` et son
`PLAN.md` disent où il en est, ne pas le redire ici.

Le contrat que MAKAHO attendait est publié en 0.9.0, déployé le
2026-11-09, et complété en 0.9.1 (`CHANGELOG.md`), qui part en
production au prochain `make update` (aucun réglage à changer).

## Une surveillance, plus tard et hors de card-api

La sonde (`scripts/veille_sante.py`) lit `/v1/health`, échéance du pool
comprise, mais rien ne la lance. Remis à plus tard le 2026-11-09 :
l'utilisateur envisage une surveillance commune à ses services, à part
(un outil du genre Uptime Kuma), qui lirait `/v1/health`.

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

## Le dépôt HAL, annoncé par la citation

`CITATION.cff` et le README annoncent un identifiant pérenne à venir,
« dépôt HAL adossé à Software Heritage » ; la citation passe par ces deux
canaux (`dev/decisions.md`). Le dépôt est archivé sur Software Heritage
depuis le 2026-07-22 ; rien dans le dépôt ne dit que le dépôt HAL est
fait (à confirmer). Geste de l'utilisateur, avec son compte HAL ; une fois
fait, son identifiant remplace l'annonce dans les deux fichiers.

## Les mentions légales, à faire valider

Les mentions légales du README sont rédigées d'après ce que le code fait.
Éditeur, responsable de publication et hébergeur gagneraient une
validation par le service compétent d'INRAE.

## Un test pour les valeurs par défaut

Chaque réglage a sa valeur par défaut écrite à quatre endroits : le code,
`compose.yaml`, `.env.example` et le tableau d'`INSTALL.md`. Vérifiées
identiques le 2026-11-10, mais rien ne les y oblige, et le plafond à froid
de B5 était recopié dans huit fichiers. Retenu le 2026-11-10 : un test qui
les compare, sur le modèle de `tests/test_citation.py` pour le numéro de
version, plutôt que retirer des copies. À faire plus tard.

## En réserve, sans date

La phase 4 de la revue FAIR (`dev/plans/2026-07-24_fair.md`) : unités
UCUM, JSON-LD et SKOS, catalogue DCAT pour les moissonneurs. Sur décision,
si un besoin d'interopérabilité se présente.

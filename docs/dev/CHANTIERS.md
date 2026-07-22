> **Statut : registre vivant.** Ce fichier ne contient que des pistes
> **ouvertes**, et seulement celles du service web : celles du corpus de
> fiches vivent dans card, celles du moteur dans stase. Un chantier livré
> en sort et devient une entrée de `CHANGELOG.md`, à la racine du dépôt,
> qui renvoie au document expliquant le détail.

# CHANTIERS : pistes ouvertes du service (mise à jour 2026-07-22)

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

## Intégration continue, et faut-il déployer depuis le CI

Ouvert le 2026-07-22. Le dépôt n'a aucun workflow : ses 41 tests ne
tournent que sur la machine de l'utilisateur, alors que card et stase
lancent pytest et ruff à chaque push. Un test qui ne tourne que chez soi
finit par ne plus tourner du tout.

Deux niveaux à ne pas confondre, et l'utilisateur ne veut pas du second :

- **exécuter les tests** à chaque push, ce qui n'engage rien et vaut pour
  ce dépôt comme pour les deux autres. Attention aux tests réseau, à
  garder derrière `CARD_API_LIVE` ;
- **déployer** depuis le CI. **Réserve explicite de l'utilisateur le
  2026-07-22 : il n'aime pas.** Ne pas le proposer comme une évidence.
  Le déploiement reste `make update` sur la VM, un geste conscient, ce
  qui est cohérent avec le reste : la production suit `main`, mais c'est
  lui qui décide du moment.

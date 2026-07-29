> **Statut : registre vivant.** Ce fichier ne contient que des pistes
> **ouvertes**, et seulement celles du service web : celles du corpus de
> fiches vivent dans card, celles du moteur dans stase. Un chantier livré
> en sort et devient une entrée de `CHANGELOG.md`, à la racine du dépôt,
> qui renvoie au document expliquant le détail.

# CHANTIERS : pistes ouvertes du service (mise à jour 2026-07-29)

Il n'en reste qu'une. Ce qui a quitté ce fichier le 2026-07-29 est parti
dans le document qui en porte la matière, pas à la corbeille :

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

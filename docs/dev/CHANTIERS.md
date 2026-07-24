> **Statut : registre vivant.** Ce fichier ne contient que des pistes
> **ouvertes**, et seulement celles du service web : celles du corpus de
> fiches vivent dans card, celles du moteur dans stase. Un chantier livré
> en sort et devient une entrée de `CHANGELOG.md`, à la racine du dépôt,
> qui renvoie au document expliquant le détail.

# CHANTIERS : pistes ouvertes du service (mise à jour 2026-07-24)

## Thème de `/docs` : reprendre composant par composant

**Où on en est.** Un premier thème écrit à la main a échoué (recouvrement
partiel du CSS de Swagger). Le second, livré le 2026-07-24, est généré
depuis le CSS réel de Swagger : il tient la **gamme et la typographie**,
vérifiées à la capture d'écran, relevé de pixels à l'appui. Fabrication
et façon de vérifier : `THEME_DOCS.md`.

**Ce qui n'est pas fait**, et c'est le vrai reste à faire : le passage
**composant par composant** contre la maquette. Le thème actuel s'est
arrêté à la peau (couleurs, fontes, gouttière) sans reprendre la forme
de chaque élément. D'où la liste de ratés ci-dessous.

Maquette de référence, à garder ouverte à côté de la page :
https://claude.ai/code/artifact/05776a99-5691-442b-87a3-b3a46582fea1

**Retours de l'utilisateur, 2026-07-24, à traiter un par un :**

1. **Pastilles de version** à côté du titre : contour et fonte à revoir.
2. **En-tête.** La description doit être *simple et sans lien*, comme
   dans la maquette, et les liens passent **dessous**, en ligne. Ajouter
   par rapport à la maquette un lien vers le paquet `card`. Attention :
   ces liens viennent aujourd'hui du champ `description` de l'OpenAPI
   (donc du code, pas du CSS) : c'est `main.py` qu'il faut reprendre,
   pas seulement la feuille de style.
3. **Boîtes d'opération.** Le badge de méthode doit être **plus petit et
   mieux dessiné**, comme dans la maquette. Surtout : **pas de chevron**,
   mais **un texte qui dit ce que contient la boîte** (dans la maquette,
   la description courte alignée à droite) : jugé nettement meilleur.
   L'état sélectionné/actif de la boîte ressort en blanc, ce qui est
   perturbant.
4. **Corps déplié : rien n'est repris.** Bouton Execute, tableau de
   paramètres, rendu de la sortie. Et un artefact à supprimer : une ligne
   horizontale d'onglet qui traîne sous le mot « Parameters ».

**La question posée, et la réponse honnête.** Non, ce n'est pas un
exercice exotique : tout ce qui est listé ci-dessus est atteignable en
CSS sur Swagger, sauf le point 2 qui est du contenu OpenAPI. Le badge,
le chevron remplacé par du texte, l'onglet « Parameters », le bouton
Execute, le tableau : ce sont des composants identifiables, leurs classes
se lisent dans le CSS de Swagger (`swagger-ui.css`) et dans le DOM rendu
(`chromium --dump-dom`). Rien n'est caché. Ce qui manque, c'est le
travail élément par élément, chacun avec sa règle et sa capture d'écran
de contrôle. Le générateur a réglé la couverture des couleurs, il ne
remplace pas ce passage-là.

Deux voies, à trancher au début de la reprise :

1. **Continuer sur Swagger**, composant par composant. On garde
   l'exécution des requêtes, la génération depuis l'OpenAPI, le
   deep-linking. On accepte de ne jamais être au pixel près sur la mise
   en page, qui appartient à Swagger.
2. **Page de doc maison**, rendue depuis `/openapi.json`. Rendu exactement
   conforme à la maquette, mais il faut réimplémenter le « try it out »
   (formulaire, appel, affichage de la réponse, curl) que Swagger donne
   gratuitement.

**Outillage déjà en place pour reprendre vite** (détail dans
`THEME_DOCS.md`) : `python scripts/build_theme.py` reconstruit le calque ;
les retouches se font dans `scripts/theme-identity.css` ; la boucle de
vérification est une capture `chromium --headless --screenshot`, à faire
**page dépliée et requête exécutée**, sans quoi on ne voit rien des
défauts réels.

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

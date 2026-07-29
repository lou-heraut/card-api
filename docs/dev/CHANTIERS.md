> **Statut : registre vivant.** Ce fichier ne contient que des pistes
> **ouvertes**, et seulement celles du service web : celles du corpus de
> fiches vivent dans card, celles du moteur dans stase. Un chantier livré
> en sort et devient une entrée de `CHANGELOG.md`, à la racine du dépôt,
> qui renvoie au document expliquant le détail.

# CHANTIERS : pistes ouvertes du service (mise à jour 2026-07-28)

## Thème de `/docs` : quasiment refermé

**Où on en est.** Un premier thème écrit à la main a échoué (recouvrement
partiel du CSS de Swagger). Le second, livré le 2026-07-24, est généré
depuis le CSS réel de Swagger et tient la gamme et la typographie. Le
passage **composant par composant**, qui était le vrai reste à faire, a
été mené les 2026-07-27 et 2026-07-28 : en-tête, badges, corps déplié,
tableaux, boutons, petits écrans, logo et favicon. Fabrication et façon
de vérifier : `THEME_DOCS.md`.

Ce chantier n'est donc plus une reprise de fond mais une **liste courte
de finitions**, ci-dessous.

Maquette de référence, à garder ouverte à côté de la page :
https://claude.ai/code/artifact/05776a99-5691-442b-87a3-b3a46582fea1

**Retours de l'utilisateur du 2026-07-24 : les quatre sont traités**
(2026-07-27 et 2026-07-28, détail dans `CHANGELOG.md`). Pastilles de
version ramenées à un seul cadre ; en-tête réduit à un paragraphe de
prose suivi de deux lignes de liens, licence et contact compris ; badges
de méthode réduits, chevrons supprimés, remplacés par le `summary` de
l'opération aligné à droite ; corps déplié repris (Execute à la taille
d'un bouton, tableau de paramètres, filet d'onglet retiré sous
« Parameters », blocs de code et boutons de copie).

**Ce qui reste sur le thème**, et c'est peu :

- **Le bouton « Download file »** : l'utilisateur le reprend lui-même
  (2026-07-28). Ne pas y toucher sans lui.
- **La fenêtre d'autorisation** (clic sur « Authorize ») n'a **jamais été
  regardée**. Le calque engendré couvre `.dialog-ux`, donc elle doit être
  sombre, mais c'est une déduction et non une observation : la capture
  headless ne clique pas. À vérifier d'un coup d'œil.
- **Les deux boutons posés sur un bloc de code** se calent par un
  `right:85px` en dur sur « Copier », valeur choisie pour la largeur de
  « Télécharger ». Toute retouche de l'un demande de revérifier l'autre.

**La question « Swagger ou page maison » est tranchée par les faits.**
Elle restait ouverte en juillet ; le passage composant par composant a
été fait sur Swagger, en CSS seul, et il a suffi. On garde donc
l'exécution des requêtes, la génération depuis l'OpenAPI et le
deep-linking, en acceptant de ne pas être au pixel près sur une mise en
page qui appartient à Swagger. Une page maison demanderait de
réimplémenter le « try it out » entier pour ce seul gain : à ne rouvrir
que si une contrainte nouvelle l'impose.

**La règle qui a tenu tout du long**, et qu'il faut garder : *rien qui ne
soit une règle CSS ou une chaîne de caractères.* Aucune balise injectée
dans le HTML de Swagger, aucun greffon accroché à ses composants
internes. Le logo et la favicon eux-mêmes passent par un pseudo-élément
et une URL `data:`. Une règle qui cesse de s'appliquer après une montée
de version laisse la page reprendre son apparence d'origine ; un greffon
casse.

**Outillage déjà en place pour reprendre vite** (détail dans
`THEME_DOCS.md`) : `python scripts/build_theme.py` reconstruit le calque ;
les retouches se font dans `src/card_api/static/theme-identity.css`,
sans rien reconstruire ; la boucle de
vérification est une capture `chromium --headless --screenshot`, à faire
**page dépliée et requête exécutée**, sans quoi on ne voit rien des
défauts réels.

## À surveiller : les décomptes écrits dans les textes

Retirés des descriptions d'API le 2026-07-28, et un test refuse
désormais le motif. Il en reste dans les entrées de `CHANGELOG.md`, et
c'est justifié : une entrée datée décrit un état à une date, elle n'a pas
à suivre le corpus.

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

## Intégration continue : le volet tests est livré, le déploiement reste manuel

Ouvert le 2026-07-22, **volet tests livré le 2026-07-28**
(`.github/workflows/tests.yml`) : pytest sur 3.11 et 3.12, ruff avec la
version épinglée du `pyproject.toml`. card-api rejoint ainsi card et
stase, et l'écart entre les trois dépôts est refermé.

Le sujet n'était pas théorique : le lint de stase était **rouge depuis
une sortie de ruff**, sans qu'une ligne de code ait bougé, parce que le
workflow installait `ruff` sans version. Les trois épinglent désormais la
version et déclarent leur jeu de règles au même endroit.

**Le déploiement depuis le CI reste écarté** (réserve explicite de
l'utilisateur, 2026-07-22, non rediscutée) : `make update` sur la VM
reste un geste conscient. La production suit `main`, mais c'est lui qui
décide du moment. Ne pas le proposer comme une évidence.

**Ce que le CI ne couvre pas, et qu'il faut savoir :** les tests `live`
(Hub'Eau réel) restent derrière `CARD_API_LIVE`, volontairement. Un CI
qui dépend d'un service tiers vire rouge un jour de maintenance, et
personne ne regarde plus les rouges. Ces tests-là se lancent à la main
avant un déploiement qui touche au client Hub'Eau.

Deux niveaux à ne pas confondre, et l'utilisateur ne veut pas du second :

- **exécuter les tests** à chaque push, ce qui n'engage rien et vaut pour
  ce dépôt comme pour les deux autres. Attention aux tests réseau, à
  garder derrière `CARD_API_LIVE` ;
- **déployer** depuis le CI. **Réserve explicite de l'utilisateur le
  2026-07-22 : il n'aime pas.** Ne pas le proposer comme une évidence.
  Le déploiement reste `make update` sur la VM, un geste conscient, ce
  qui est cohérent avec le reste : la production suit `main`, mais c'est
  lui qui décide du moment.

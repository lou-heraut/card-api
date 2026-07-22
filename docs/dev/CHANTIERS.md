> **Statut : registre vivant.** Ce fichier ne contient que des pistes
> **ouvertes**, et seulement celles du service web : celles du corpus de
> fiches vivent dans card, celles du moteur dans stase. Un chantier livré
> en sort et devient une entrée de `CHANGELOG.md`, à la racine du dépôt,
> qui renvoie au document expliquant le détail.

# CHANTIERS : pistes ouvertes du service (mise à jour 2026-07-22)

## 1. Consultation des fiches : du chemin serveur au lien citable

Objectif de fond, formulé par l'utilisateur le 2026-07-20 : faire de la
consultation des fiches la partie la plus agréable du service. Aider
quelqu'un à comprendre ce que fait une fiche et à retrouver les
fonctions employées, sans avoir à cloner le dépôt. Le catalogue est
aujourd'hui un dump de métadonnées, la cible est un objet qui se lit.

### Deux constats vérifiés dans le code le 2026-07-20

`/v1/cards` renvoie `script_path`, le chemin absolu du YAML sur la
machine qui exécute. Le champ vient de card (`extraction.py:222`) et
`main.py:98-101` reverse le DataFrame tel quel, `clean()` ne faisant
que NaN vers null. En production cela donne
`/usr/local/lib/python3.12/site-packages/card/cards/flow/series/dtBF.yaml`,
sans usage pour un client, et cela expose l'arborescence du conteneur.
Le champ reste utile en interne (`main.py:49-51` s'en sert pour
retrouver le nom de fichier d'une fiche), donc il s'agit de ne pas le
sortir dans la réponse, pas de le supprimer.

`/v1/cards/{id}` construit bien un lien GitHub vers le YAML, mais en
cherchant la sous-chaîne `src/card/cards/` dans le chemin
(`main.py:115-118`). Cette sous-chaîne n'existe qu'en installation
éditable. En production la condition est fausse et le lien disparaît
en silence, vérifié. D'où la situation actuelle : le chemin interne là
où il ne sert à rien, et pas de lien public là où il servirait.

### Direction proposée

Calculer le chemin relatif au dossier `cards/` du package plutôt que
par recherche de sous-chaîne : identique en dev et en prod, donne
`flow/series/dtBF.yaml` dans les deux cas. Une seule fonction partagée
par les deux endpoints, remplaçant `script_path` par un `yaml` public
dans les réponses.

Question ouverte, à trancher avant d'écrire : vers quelle révision
pointer. Aujourd'hui `blob/main`, donc un lien qui bouge avec le
corpus, une fiche consultée aujourd'hui pouvant ne plus correspondre
demain. L'image épingle déjà `CARD_REF` : pointer vers cette révision
rendrait le lien stable et reproductible, ce qui vaut mieux pour un
service de recherche.

### SWHID, après et pas avant

L'identifiant de contenu Software Heritage (`swh:1:cnt:<sha1_git>`) se
calcule hors ligne, c'est le hash git du blob, donc aucun coût réseau.
Ce qui manque est l'archivage du dépôt dans Software Heritage pour que
l'identifiant se résolve. `codemeta.json` vise déjà ce canal. Ordre
naturel : archiver, puis ajouter le champ. L'inverse publierait des
identifiants qui ne résolvent pas.

### Pistes de confort à instruire ensuite

La demande initiale est plus large que le lien. Rendre les fonctions
employées lisibles depuis le catalogue : la colonne `functions` est
aujourd'hui une liste de noms nus (`rollmean_center, nanmin,
return_level`) qui ne dit pas ce que fait chacun. Et donner à lire la
chaîne de traitement d'une fiche, que `method` décrit déjà en prose
numérotée. À instruire avec le chantier documentation de card plutôt
qu'en isolé, puisque la matière vient des fiches.

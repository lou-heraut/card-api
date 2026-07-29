# Le thème de `/docs`

> **Statut : norme en vigueur.** Décrit le thème sombre de la page
> `/docs`, comment il est fabriqué et comment on le vérifie. Ce qui a
> changé et quand se lit dans `CHANGELOG.md`, l'avancement FAIR dans
> `PLAN_FAIR.md`. Ne rien recopier d'ici : renvoyer.

## Ce que c'est

`/docs` reste Swagger UI. Le thème est un **calque** posé après le CSS de
Swagger, pas un remplacement : Swagger garde sa mise en page, son
exécution de requêtes, ses composants. On ne retouche que ce qui se voit.

Trois fichiers, un seul rôle chacun :

| Fichier | Rôle |
|---|---|
| `scripts/build_theme.py` | fabrique le calque de couleurs à partir du CSS réel de Swagger |
| `src/card_api/static/swagger-colors.css` | **généré**, ne pas éditer |
| `src/card_api/static/theme-identity.css` | **écrit à la main** : gamme, typographie, gouttière, densité, forme, états |

Les deux feuilles sont servies dans cet ordre, l'identité en dernier,
donc c'est elle qui tranche.

## Deux marques, et pourquoi elles ne sont pas des balises

Le logo INRAE et l'émoji d'onglet auraient pu s'obtenir en injectant du
HTML dans la page de FastAPI. Ils ne le sont pas, et c'est la même règle
que pour le reste du thème : **rien qui ne soit une règle CSS ou une
chaîne de caractères.**

| Marque | Comment | Où |
|---|---|---|
| logo INRAE | pseudo-élément `::after` du titre, en image de fond | `theme-identity.css`, section 3 |
| émoji `🎴` de l'onglet | `swagger_favicon_url`, en URL `data:` | `main.py`, `_FAVICON` |

Le logo est un SVG servi par sa propre route (`/static/inrae.svg`) et
appelé en URL relative depuis la feuille, qui est servie depuis le même
dossier. Il est posé en **masque**, pas en image de fond : le fichier ne
sert que de découpe, et la couleur vient de `background`, donc de la
gamme. En image de fond, le blanc pur du SVG restait du blanc pur, plus
clair que le titre juste à côté ; en masque il suit `--text` sans qu'on
touche au fichier, et une retouche de la gamme l'emmène avec elle.

Le titre est passé en `flex` : le logo pousse à droite par
`margin-left:auto` sur grand écran, et repasse au-dessus du titre sous
640 px (`order:-1` et `flex-basis:100%`, cf. section 12). Faire basculer
le conteneur en `column-reverse` aurait été plus court, mais aurait aussi
retourné les pastilles de version, qui doivent suivre le titre.

## Ce que le calque MASQUE, et ce qu'il ne supprime pas

Règle de partage entre le contrat et la page : **`openapi.json` porte
tout, `/docs` ne montre que ce qui aide à lire.** Un champ de plus dans
le contrat ne coûte rien à personne et sert une machine ; une ligne de
plus à l'écran coûte à chaque visiteur.

| Champ de `info` | Pourquoi il est déclaré | Pourquoi il ne s'affiche pas |
|---|---|---|
| `summary` | un catalogue d'API l'affiche **seul**, sans la description | Swagger le pose juste au-dessus de la description, dont il redit la première phrase |
| `termsOfService` | champ prévu pour les conditions d'usage (quotas, `429`, clé) | pointe une section du README, dont le dépôt est déjà dans la ligne de ressources |
| `contact` | qui tient le service | rendu suivi d'un « - Website » écrit en dur dans le code de Swagger, qu'aucun sélecteur n'atteint |
| `license` | **c'est là qu'un moissonneur lit sous quels droits réutiliser** | rendu en lien nu, une troisième présentation |

Les deux derniers sont repris en fin de description, sous la même forme
que les autres liens. Sans ce regroupement, la page offrait trois
présentations d'une même chose sur quinze centimètres.

**Le sélecteur de serveur** relève de la même règle (masqué le
2026-07-29). Swagger le rend dès qu'un bloc `servers` existe, même avec
une seule entrée : un menu déroulant qui ne sélectionne rien et qui
répète l'adresse de la page qu'on est en train de lire. Mais `servers`
est ce qui donne au contrat une adresse **absolue**, la seule dont
dispose un générateur de client ou quiconque lit `openapi.json` ailleurs
que sur cette page ; le retirer produirait des clients pointant sur `/`,
pour gagner trente pixels. On masque donc `.servers-title` et `.servers`,
et pas `.scheme-container`, qui porte aussi le bouton « Authorize ».

Ce masque suppose **un seul serveur**. Le jour où une adresse de
préproduction s'ajoute au contrat, il cache un vrai choix : il faut alors
le lever.

**Masqué n'est pas supprimé.** Retirer un de ces champs du contrat pour
gagner une ligne d'affichage serait un mauvais échange : la machine ne
lit pas la prose d'une description. `tests/test_docs_theme.py` tient les
deux bouts, la déclaration dans `openapi.json` et le masquage dans le
calque.

La favicon est un SVG d'une ligne portant l'émoji, en URL `data:`
échappée : aucun fichier à servir, aucun appel réseau. Sans elle, la page
arbore celle de FastAPI.

Si l'une ou l'autre cesse un jour de s'appliquer, la page rend un titre
sans logo et un onglet sans icône. Elle ne casse pas : c'est toute la
différence avec un greffon accroché aux noms de composants internes.

## Retoucher l'apparence

**Éditer `src/card_api/static/theme-identity.css`, puis recharger la
page.** Rien d'autre. Pas de reconstruction, pas de vidage de cache : le
`<link>` porte une empreinte du fichier, qui change quand le fichier
change.

C'est la raison d'être de la séparation en deux fichiers. Ils ont été
concaténés jusqu'au 2026-07-27, ce qui obligeait à relancer le
générateur pour la moindre virgule de style, et l'oubli se manifestait
par « ma règle ne marche pas » alors qu'elle n'était simplement jamais
partie au navigateur.

Le générateur, lui, ne se relance qu'à une **montée de version de
Swagger UI** :

```sh
python scripts/build_theme.py
```

Pour chercher une valeur (une marge, une taille), passer par
l'inspecteur du navigateur et ne reporter dans le fichier que la valeur
retenue : c'est instantané, alors qu'un aller-retour par le fichier ne
l'est jamais tout à fait.

Un dernier piège, celui-là silencieux : un **commentaire mal refermé**
fait avaler la règle suivante par le navigateur, sans message. Le
`check()` du générateur retire les commentaires avant de valider, donc
il ne voit pas ce cas.

## Pourquoi c'est généré

Swagger UI embarque 179 ko de CSS et 726 déclarations de couleur. Un
thème écrit à la main en oublie forcément, et un thème **à moitié
appliqué est pire qu'un thème absent** : c'est l'échec du 2026-07-24 au
matin, une centaine de règles posées à l'estime, un fond sombre et la
moitié des composants restés clairs.

Le générateur ne devine donc aucune classe. Il relit le CSS de Swagger
et, pour chaque règle qui pose une couleur, ré-émet la même règle avec la
couleur transposée. Les sélecteurs sont ceux de Swagger, donc de
spécificité égale : c'est l'ordre de chargement qui tranche, et le calque
est chargé après. Couverture : environ 420 règles.

Deux garde-fous, tous deux nés d'un défaut vu à l'écran :

- **une règle qui peint déjà une surface sombre est laissée intacte.**
  Swagger peint ses blocs de code en `#333` avec du texte blanc ;
  transposés, ils repartaient en clair avec du texte noir, illisibles.
- **le mode sombre natif de Swagger (`html.dark-mode`) est ignoré.** On
  ne l'active pas ; le transposer n'ajouterait que du bruit et le
  casserait pour qui l'activerait.

Ce que la substitution ne sait pas faire vit dans le calque d'identité :
la gamme de gris, les deux familles de caractères, la gouttière, la
densité, le badge de méthode, les états d'erreur, et les rares couleurs
que Swagger écrit en toutes lettres (`border-color:green`), invisibles
pour un remplacement qui ne lit que `#` et `rgb()`.

## La gamme

Volontairement **mono-univers** : le sujet est un thème sombre, il n'y a
pas de variante claire. Gris strictement neutres et gamme **ouverte** :
ce sont les paliers qui font le relief, les tasser près du noir donne
l'impression d'un filtre basse luminosité plutôt que d'un thème.

| Rôle | Valeur | Où |
|---|---|---|
| creux | `#0e0e0e` | champs, blocs de code |
| fond | `#131313` | page, corps d'une opération dépliée |
| bloc | `#1d1d1d` | une opération |
| filet | `#383838` | bordures |
| texte | `#ececec` | texte courant |

La couleur ne sert qu'aux méthodes HTTP, et **jamais seule** : le mot
GET / POST / DELETE reste le repère, la teinte n'est qu'un renfort. Les
trois sont choisies hors de l'axe rouge/vert, distinctes en vision
deutéranope.

| Méthode | Valeur |
|---|---|
| GET | `#8ab4dc` |
| POST | `#72b3a2` |
| DELETE | `#e09b78` |
| PUT / PATCH | `#d9c07f` |

Le fond d'une opération reste gris quelle que soit la méthode. Swagger
teinte tout le bloc ; sur fond sombre ces aplats colorés font sale et
redonnent à la couleur le rôle de repère principal.

Une barre de couleur en bord gauche de bloc a été essayée puis écartée
(elle rendait mal, étirée sur toute la hauteur d'un bloc déplié). Le code
mis de côté est conservé en commentaire dans `theme-identity.css`, avec
la variante courte et détachée qui n'a pas été retenue non plus.

## Comment on vérifie

**Regarder la page.** C'est la leçon de l'échec : constater que le CSS
est *injecté* ne dit rien de ce qui *rend*. La boucle, sans dépendance à
installer, avec le chromium du système :

```sh
python -m uvicorn card_api.main:app --port 8077 &
chromium --headless --no-sandbox --hide-scrollbars \
  --window-size=1280,1700 --virtual-time-budget=12000 \
  --screenshot=$HOME/snap/chromium/common/theme/docs.png \
  http://127.0.0.1:8077/docs
```

Le chromium empaqueté en snap n'écrit ni dans `/tmp` ni dans un dossier
caché du home : viser `~/snap/chromium/common/`.

Une capture ne montre que la page repliée. Ce qui compte se voit **une
opération dépliée et une requête exécutée** : c'est là qu'ont été
trouvés les vrais défauts (« Request URL » en sombre sur sombre, boutons
copier/télécharger restés clairs, champ invalide viré au saumon). Pour
s'y rendre sans cliquer, une page de test qui charge le même thème,
déplie une opération et appelle `Execute` par script : elle est décrite
dans l'historique du chantier, se réécrit en dix lignes, et n'a pas sa
place dans le dépôt.

Enfin, une réponse `text/plain` passe quand même au coloriseur de
Swagger : sur la fiche dessinée de `/v1/cards/{id}/figure`, il prenait
les nombres pour des littéraux et barbouillait la barre de calendrier.
Le calque neutralise ce cas (`code:not([class])`), c'est le genre de
défaut qu'aucun test ne voit.

## Ce que les tests garantissent

`tests/test_docs_theme.py`, dont chaque cas correspond à quelque chose
que le thème raté aurait laissé passer : l'ordre de chargement, la santé
syntaxique de la feuille (une `url("data:…;…")` coupée sur son
point-virgule laisse un guillemet ouvert, et le navigateur avale
silencieusement tout ce qui suit), un plancher de couverture, la palette,
l'absence de `dark-mode`, et le garde-fou « déjà sombre ».

Ils ne remplacent pas le fait de regarder la page.

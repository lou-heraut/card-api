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
| `scripts/build_theme.py` | fabrique le calque à partir du CSS réel de Swagger |
| `scripts/theme-identity.css` | ce qui ne se déduit pas d'une couleur : gamme, typographie, gouttière, densité, états |
| `src/card_api/static/swagger-theme.css` | **généré**, ne pas éditer ; c'est ce que sert la route |

Reconstruire après une montée de version de Swagger UI :

```sh
python scripts/build_theme.py
```

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

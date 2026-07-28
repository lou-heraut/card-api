# Journal des modifications

Évolutions notables de `card-api`, le service web qui expose les fiches
CARD sur les chroniques Hub'Eau. Format inspiré de [Keep a
Changelog](https://keepachangelog.com/fr/1.1.0/). Les paquets `card` et
`stase` tiennent chacun le leur.

**Numérotation.** Le service n'est pas une bibliothèque : personne ne
l'importe, il est déployé. Il suit `main` pour card comme pour stase, si
bien qu'une correction arrive en ligne au `make update` suivant. Ce qui
rend un résultat reproductible n'est donc pas un numéro figé mais le
**commit** que chaque réponse publie, résolu à la construction de
l'image, accompagné de son identifiant pérenne Software Heritage
(`swh:1:rev:<commit>`). Les trois dépôts sont archivés sur Software
Heritage depuis le 2026-07-22, donc ces identifiants résolvent. Publier
une version tient en une commande : `python scripts/set_version.py
0.3.0`, qui accorde `pyproject.toml`, `CITATION.cff` et
`codemeta.json`.
Chaque entrée dit ce qui a changé et renvoie au document qui l'explique.
Rien n'est recopié ici : une information recopiée finit par mentir à un
des deux endroits.

## Non publié

### Ajouté

- **Les listes se collent au lieu de se recopier (2026-07-28).**
  Enchaîner deux endpoints demandait de relever les identifiants un par
  un dans une réponse JSON puis de les rejoindre par des virgules à la
  main : quinze copier-coller pour une sélection de stations, autant
  pour les variables, et une faute de frappe donnait un 404 sans dire
  laquelle. `/v1/stations` rend désormais `codes` et `/v1/cards` rend
  `ids` : la sélection déjà jointe, à coller telle quelle dans le
  paramètre de l'endpoint suivant. Rien de plus qu'une chaîne de
  caractères dans la réponse, mais c'est la corvée qui décidait de
  l'abandon.

- **La fenêtre d'analyse démarre en 1968 (2026-07-28).** Sans `start`,
  le service prenait toute la chronique, et `/docs` pré-remplissait
  `1970-01-01 → 2020-12-31`, une fenêtre arbitraire close six ans avant
  aujourd'hui. Le défaut du SERVICE devient **`1968-01-01`** : la borne
  d'analyse du projet, celle des validations MAKAHO, et le point à partir
  duquel le réseau hydrométrique français est assez fourni pour que des
  stations se comparent entre elles. Laisser courir jusqu'aux plus
  anciennes séries donnait, sans que personne ne l'ait demandé, des
  périodes de longueurs très différentes d'une station à l'autre.

  **Pas de borne de fin symétrique** : on veut suivre la chronique
  jusqu'à son dernier jour disponible, donc ne pas en poser. Conséquence
  assumée : les mesures antérieures à 1968 ne sont plus reprises par
  défaut ; elles s'obtiennent en donnant `start`, et la période effective
  est publiée dans chaque réponse, donc un résultat dit toujours sur quoi
  il porte.

- **Le tableur, sans perdre la provenance (2026-07-28) :**
  `/v1/extract.csv` et `/v1/trend.csv` rendent les mêmes données qu'à
  l'URL nue, en fichier ouvrable au tableur. Virgule et point décimal,
  pas le `;` de Hub'Eau : les clients documentés dans le README sont
  pandas et R.

  Le point qui décidait de l'intérêt de la chose : **un CSV ne sait pas
  porter de bloc `versions`, de SWHID, d'empreinte ni de droits.** Livré
  nu, il devient en trois copies un tableau de chiffres dont plus
  personne ne sait d'où il vient, c'est-à-dire ce que ce service existe
  pour éviter, et Hub'Eau ne résout pas ce point. La provenance part donc
  en **lignes de commentaire `#`** en tête de fichier, que
  `read_csv(comment="#")` et `read.csv(comment.char="#")` sautent d'elles-
  mêmes et qui survivent à l'enregistrement, contrairement à un en-tête
  HTTP.

  Le nom proposé au téléchargement porte l'analyse, du plus général au
  plus particulier :
  `card-api_trend_F700000103_QA-VCN10_AR1_2005-2026_ac9c7eed.csv`. La
  période y vient de la **donnée** et non de la demande (« depuis 1970 »
  sur une station ouverte en 2005 mentirait), et le nom se termine par
  l'**empreinte des données** plutôt que par une date de génération :
  deux fichiers de même nom ont la même source, et deux extractions
  séparées par une révision Hub'Eau ne s'écrasent pas. Détail et
  arbitrages dans `docs/dev/API.md`.

  **Aucune virgule dans le bandeau `#`.** Un tableur n'a pas de notion de
  commentaire : il affiche ces lignes comme des données et les découpe
  sur les virgules, éparpillant la provenance sur huit colonnes. Les
  quoter la garderait en une cellule, mais la ligne ne commencerait plus
  par `#` et pandas cesserait de la sauter : le remède serait pire. Le
  bandeau n'emploie donc que `·`, y compris pour les listes de stations
  et de fiches. Un test le garantit.

- **La tendance se lit aussi dessinée (2026-07-28) :**
  `GET /v1/trend/figure` rend le **même** résultat en table, une ligne
  par variable, avec le sens, l'ampleur dans l'unité de la variable, la
  pente relative en %/an, la p-value et le **verdict en clair**. Jusqu'ici
  il fallait savoir que `h: true` signifie « stationnarité rejetée » pour
  lire une réponse, ce que personne ne sait à la première visite.

  Livré le matin en `format=text` sur `/v1/trend`, **refait le jour même
  en endpoint séparé.** La raison est le contrat : OpenAPI ne sait pas
  dire « `text/plain` quand `format=text` », si bien que l'opération
  annonçait du JSON en rendant du texte. Aucune précaution ne rattrape
  ça, c'est une limite du format. Ce qui rendait le paramètre tentant,
  la peur de recopier neuf paramètres, n'existait pas : FastAPI accepte
  un modèle Pydantic comme paramètres de requête, les deux endpoints les
  déclarent donc **une** fois et le contrat les rend identiques. La règle
  qui en sort, écrite dans `docs/dev/API.md` : **une représentation, une
  URL**, extension de chemin quand seul l'encodage change
  (`/v1/trend.csv`), sous-ressource quand l'information change
  (la figure retire les intervalles et ajoute un verdict).

- **HTTPS sur `card-api.riverly.inrae.fr`, et le contrat le dit
  (2026-07-28).** Le nom de domaine et certbot étant en place, ce qui
  bloquait la diffusion des clés est levé : un jeton ne transite plus en
  clair. L'adresse est publiée dans le bloc `servers` d'`openapi.json`,
  d'où deux effets : `/docs` affiche l'adresse réelle du service, et un
  client à qui l'on envoie le seul fichier de contrat sait où taper,
  alors qu'il devait jusqu'ici la déduire de l'endroit d'où il l'avait
  chargé. Elle vient de `CARD_API_PUBLIC_URL` et **pas** d'une constante
  du code : vide en développement, sinon le « Try it out » d'une
  instance locale part sur la production. Deux variables et non une
  (`DOMAIN` sert au frontal) parce que le schéma ne se déduit pas d'un
  nom : une IP nue reste en HTTP.

- **La clé de priorité existe enfin dans le contrat (2026-07-28).** Elle
  fonctionnait depuis le début, mais `usage.priority_of` lisait
  l'en-tête à la main, sans qu'aucun schéma de sécurité ne la déclare.
  Deux conséquences invisibles depuis le code : un client ne pouvait pas
  découvrir que le service accepte une clé, et un porteur de clé n'avait
  **aucun moyen de la présenter depuis `/docs`**, où `GET /v1/jobs`
  rendait donc 401 sans recours. Déclarée en `apiKey`/`header`, elle
  fait apparaître le bouton « Authorize » et part dans toutes les
  requêtes de la page. Elle reste **facultative** (`auto_error=False`) :
  c'est ce qui garde le service public, et rien ne change côté serveur.
  Le cadenas que Swagger ajoute alors sur chacune des quinze opérations
  est masqué : identique partout, il ne distingue rien et suggère le
  contraire de la vérité.

- **L'ordre des sections de `/docs` suit le parcours (2026-07-28) :**
  `stations` passe avant `data`. On choisit une station avant
  d'extraire, et c'est le code trouvé là qui remplit le champ `stations`
  d'`extract`. L'ordre de la page est celui de la liste `_TAGS`, ni
  alphabétique ni celui des routes.

- **La durée de chaque requête s'affiche (2026-07-28).** Sur une API où
  une extraction prend quelques secondes et une tendance davantage,
  c'est ce qui dit s'il faut passer par un job. Elle se lisait
  jusqu'ici en devinant.

- **`GET /` cesse de rendre 404 (2026-07-28).** Taper le nom de domaine
  dans une barre d'adresse renvoyait `{"detail": "Not Found"}` : correct,
  mais désobligeant pour quelqu'un qui n'a rien fait de mal. La racine
  rend désormais un **panneau indicateur** dans la forme des « landing
  pages » d'OGC API : un titre, une phrase, et un tableau `links` où
  chaque entrée porte sa **relation** (`service-desc` pour le contrat,
  `service-doc` pour la documentation, `latest-version` pour `/v1`). Un
  client générique sait suivre ces relations sans rien connaître du
  service, ce qu'une redirection vers `/docs` ne permettrait pas. Le
  détail reste dans `/v1` : la racine renvoie, elle ne redit pas. Le
  dessin n'est pas choisi au hasard, la file de calcul suit déjà OGC API
  Processes.

- **Le lint est reproductible, ou il ne sert à rien (2026-07-28).** Le
  service n'avait ni ruff dans ses dépendances de développement, ni jeu
  de règles déclaré : `ruff check` appliquait les défauts de la version
  attrapée sur la machine, qui s'élargissent au fil des sorties. C'est
  le mécanisme exact des échecs de CI à répétition rencontrés sur card.
  Deux verrous, tous deux nécessaires : la **version est épinglée** dans
  `pyproject.toml` (`[dev]`), le **jeu de règles est déclaré** dans le
  même fichier (`E4`, `E7`, `E9`, `F`, comme card et stase). Un seul
  endroit les porte : recopier le numéro dans un fichier de CI, comme le
  fait card, recrée l'écart d'un cran plus loin. `make lint` passe par
  le ruff du venv, jamais par celui du PATH.

- **Une identité visuelle sur `/docs` (2026-07-28) :** le logo INRAE
  aligné à droite du titre, qui repasse au-dessus sous 640 px, et
  l'émoji 🎴 dans l'onglet du navigateur, là où figurait celui de
  FastAPI. Aucun des deux n'est une balise injectée dans la page :
  le logo est un pseudo-élément du titre posé en **masque** (le SVG ne
  sert que de découpe, la couleur vient de la gamme, donc le logo est du
  même gris que le titre et suivra `--text` si elle change), la favicon
  une URL `data:`. Même règle que le reste du thème, et même conséquence :
  si l'une cesse un jour de s'appliquer, la page rend un titre sans logo,
  elle ne casse pas. Détail dans `docs/dev/THEME_DOCS.md`.

- **L'en-tête de `/docs` redevient lisible (2026-07-28).** La description
  charriait quatre liens au fil des phrases et une phrase sur la
  provenance des réponses : on ne savait plus si on lisait un texte ou un
  sommaire. Elle est maintenant **un paragraphe de prose** (ce que fait
  le service, pour qui, par où commencer) suivi de **deux lignes de
  liens de même forme** : où aller lire, puis à qui écrire (bug, demande
  de clé de priorité, courriel). La mécanique interne (commit, SWHID,
  droits) est retirée : ces champs voyagent dans chaque réponse, où ils
  servent.

  Les deux lignes absorbent la **licence** et le **contact**, que Swagger
  rendait chacun à sa façon, l'un suivi d'un « - Website » écrit en dur
  dans son code. Trois présentations d'une même chose sur quinze
  centimètres de page, c'en est une de trop.

  D'où la règle qui s'est dégagée, et qui vaut au-delà de ces deux
  champs : **`openapi.json` porte tout, `/docs` ne montre que ce qui aide
  à lire.** Un champ de plus dans le contrat ne coûte rien à personne et
  sert une machine ; une ligne de plus à l'écran coûte à chaque
  visiteur. Le bloc `info` est donc désormais **complet** (`summary`,
  `termsOfService` renvoyant aux quotas, `contact`, `license`), et
  quatre de ces champs sont **masqués par le calque**, pas retirés :
  `summary` redit la première phrase de la description, mais un
  catalogue d'API l'affiche seul ; `license` est le seul endroit où un
  moissonneur lit sous quels droits réutiliser, et il ne lit pas de la
  prose. Un test tient les deux bouts.

- **Le contrat OpenAPI pré-mâche le formulaire (2026-07-27).** Le travail
  a porté sur `openapi.json`, pas sur l'habillage : ce qu'on y écrit sert
  à la fois la personne qui remplit un champ dans `/docs` et la machine
  qui lit le contrat, alors qu'une règle de CSS ne sert que la première.
  - **Les six facettes de classification deviennent des énumérations**,
    dérivées de `card.vocabulary()` et donc jamais recopiées ici. Swagger
    les rend en **menus déroulants** au lieu d'une saisie libre que
    personne ne pouvait deviner, et un client connaît les valeurs sans
    appeler `/v1/vocabulary`. `lang`, `orient`, `mk` et `endpoint` de
    même : **neuf vérifications écrites à la main disparaissent**, le 422
    devient automatique et annonce les valeurs acceptées.
  - **La documentation des paramètres passe de la prose à chaque champ**,
    où elle se lit au moment de le remplir. Les facettes portent en plus
    la glose française de chaque slug, sans quoi le menu n'afficherait
    que `low-flows`.
  - **Le corps de `POST /v1/jobs` porte un exemple complet**, donc
    déposer un job ne demande plus de rédiger du JSON.

  Côté affichage, trois réglages de Swagger et rien d'autre :
  `docExpansion: "none"` (on arrive sur un index replié au lieu d'une
  page entièrement dépliée), `showCommonExtensions` et `showExtensions`
  remis à `false`, que **FastAPI** allume par défaut et qui imprimaient
  `pattern`, `maxLength`, `minimum` sur chaque paramètre. Aucun de ces
  réglages ne touche `openapi.json` : le contrat reste complet, c'est la
  page qui choisit ce qu'elle montre d'emblée.

- **Passe de forme sur `/docs`**, uniquement du CSS dans
  `theme-identity.css` et des `summary` de routes. La barre
  repliée d'une opération porte maintenant **ce que fait l'action**
  (« Catalogue, filtrable par facette ») alignée à droite, au lieu du
  nom de la fonction Python que FastAPI dérivait faute de `summary`. On
  lit les quatorze actions sans en dérouler aucune. Chevrons supprimés,
  badges de méthode réduits, pastilles de version ramenées à un seul
  cadre, `Execute` rendu à la taille d'un bouton, barre de couleur sous
  « Parameters » et doubles filets retirés.

  Finitions du 2026-07-28 : un paramètre obligatoire n'est plus signalé
  deux fois (l'étoile rouge collée au nom disparaît, la mention
  « required » se range en pile sous lui), le survol d'un titre de
  section passe de l'aplat à un simple retrait d'intensité, les boutons
  « Copier » et « Télécharger » d'un bloc de code cessent de se
  chevaucher, et une première règle de largeur de fenêtre rend la barre
  repliée d'une opération lisible sous 640 px.

  La règle de travail vaut d'être notée : **rien qui ne soit une règle
  CSS ou une chaîne de caractères.** Une règle qui cesse de s'appliquer
  après une montée de Swagger laisse la page reprendre son apparence
  d'origine, elle ne casse rien. C'est la différence de nature avec un
  greffon, qui s'accroche à des noms de composants internes.

- **Le thème se retouche à la main, sans rien reconstruire.** Le calque
  écrit à la main était *concaténé* au calque de couleurs engendré :
  toute retouche de style, même d'une virgule, exigeait de relancer
  `build_theme.py`, et l'oublier se manifestait par « ma règle ne marche
  pas » alors qu'elle n'était jamais partie au navigateur. Ce sont
  désormais **deux feuilles servies l'une après l'autre** :
  `static/swagger-colors.css` (engendré, ne bouge qu'à une montée de
  version de Swagger) et `static/theme-identity.css` (écrit à la main,
  servi tel quel). Retoucher l'apparence tient en deux gestes : éditer
  le second, recharger la page.

  Chaque `<link>` porte en plus une **empreinte du contenu du fichier**,
  d'où deux effets : le navigateur ne sert plus une version périmée une
  heure durant, et en production un `make update` prend effet tout de
  suite au lieu d'attendre l'expiration chez chaque visiteur.

  Le calque à la main a ensuite été rangé : sept sélecteurs étaient
  déclarés deux ou trois fois et n'agissaient que par leur dernière
  occurrence, un filet était posé puis retiré. 105 blocs sont devenus
  92, à rendu strictement identique (comparaison des captures pixel à
  pixel, avec témoins de stabilité des deux côtés).

  Deux pièges rencontrés, tous deux invisibles hors de l'écran : le CSS
  de Swagger vendorisé par un autre service n'a pas les mêmes règles que
  celui du CDN (il faut lire le bon), et un commentaire mal refermé dans
  le calque fait avaler la règle suivante sans le moindre message. Le
  `check()` de `build_theme.py` retire les commentaires avant de valider,
  donc il ne voit pas ce cas.

  Tenté puis **retiré le même jour** : replier le tableau des réponses
  documentées derrière un bouton. Swagger n'expose aucun réglage pour
  ça, et y arriver demandait d'empiler un greffon React injecté par
  remplacement de chaîne dans le gabarit HTML de FastAPI, un sélecteur
  CSS disputant une classe que Swagger partage entre le tableau
  documenté et la réponse réelle, et un correctif d'encodage pour les
  libellés français du greffon. Trois bricolages pour replier un
  tableau, et le bouton n'a même pas été vérifié au clic. Sur Swagger,
  la couleur et la configuration sont bon marché, la **forme** ne l'est
  pas : c'est le constat d'entrée de la session, et l'avoir éprouvé une
  seconde fois ne l'a pas changé.

### Modifié

- **La colonne de station devient `code_station` (2026-07-28),** et la
  colonne de valeurs d'`extract.csv` devient `value`. Avec la règle qui
  les décide, écrite dans `docs/dev/API.md` : une colonne porte un nom
  **anglais snake_case**, sauf lorsqu'elle **relaie telle quelle** une
  donnée d'une source extérieure, auquel cas elle garde le nom de la
  source pour qu'une jointure se fasse sans traduction.

  Le code station n'est pas une valeur que le service calcule, c'est une
  valeur que Hub'Eau donne et qu'il transporte : joindre un `trend.csv`
  au référentiel obtenu par `stations_meta=true` s'écrit désormais
  `pd.merge(trend, meta)`, sans `left_on`/`right_on`. `id` ne disait pas
  l'identifiant de quoi, et `station` aurait été une métonymie : une
  station a un libellé et des coordonnées, la colonne n'en porte que le
  code. `valeur` était du français isolé au milieu de `date` et
  `variable`, une inattention de la veille.

  **L'empreinte des données change, et son préfixe reste `v1`.** Elle
  hache aussi le NOM des colonnes : une même chronique donne donc une
  empreinte différente d'avant sans que la donnée ait bougé. C'est le cas
  prévu par le préfixe de version, mais il n'a pas été incrémenté, et
  c'est délibéré : aucune empreinte n'avait encore été publiée à
  quiconque, il n'y avait donc rien à départager, et brûler un numéro sur
  un changement que personne ne peut observer aurait affaibli le signal
  pour le jour où il servira.

  **Au déploiement : vider `data/chroniques/` avant `make update`.** Les
  fichiers de cache portent l'ancien en-tête ; ils se retéléchargent
  seuls, rien n'est perdu.

- **La colonne `H` de la tendance devient `h` (2026-07-28),** en suivant
  stase où le renommage a eu lieu. C'était le dernier reste du portage R
  au milieu de `level`, `p`, `a`, `b`, `period_start` : dans le même
  dictionnaire de sortie, `P`, `STAT` et `TREND` avaient déjà été mis en
  minuscules, `H` avait été oublié. Rupture assumée, faite maintenant
  parce que les trois dépôts n'ont pas encore d'utilisateur extérieur.

  Les CSV de référence MAKAHO engendrés par R **ne sont pas touchés** :
  la traduction se fait à la lecture, dans `tests/test_makaho.py`. La
  validation contre ces goldens passe donc à l'identique, ce qui est la
  preuve que le renommage n'a rien changé au calcul.

### Corrigé

- **`/v1` cachait une partie du service (2026-07-28).** Sa liste
  `endpoints` était recopiée à la main : les trois endpoints ajoutés le
  jour même (`extract.csv`, `trend.csv`, `trend/figure`) n'y figuraient
  pas, ni la racine `/`. La porte d'entrée annonçait donc moins que ce
  que le service offre. Elle est désormais **dérivée des routes
  déclarées**, comme `versions()` l'est des métadonnées, et un test
  vérifie qu'aucune route `/v1` n'en est absente. Même leçon que partout
  ailleurs : un point de sortie recopié à la main finit par mentir.

- **Le service annonçait `0.1.0` pour les trois paquets (2026-07-28)**
  alors que les dépôts étaient en 0.5.0 et 0.2.0. `versions()` lit les
  métadonnées de l'**installation**, et une installation éditable faite
  avant un changement de version garde l'ancien numéro : chaque réponse,
  chaque bandeau de CSV et la pastille de `/docs` répétaient le mauvais.
  Le cas est local (l'image Docker est reconstruite), mais un résultat
  qui se cite avec un mauvais numéro est exactement ce que la discipline
  de versions doit empêcher : un test le refuse désormais.

- **Des décomptes de fiches figés dans les descriptions d'API
  (2026-07-28) :** « 72 des 226 fiches ». Le corpus grandit, la phrase
  serait restée. Les descriptions disent la règle, pas le décompte, et un
  test refuse le motif.

- **« fenêtre propre à chaque fiche » ne voulait rien dire
  (2026-07-28).** La phrase apparaissait dans le bandeau des CSV et,
  sous une autre forme, dans la description du paramètre `sampling`.
  Elle laissait croire à une valeur unique par fiche, sans dire ce qui
  variait. Ce réglage décide en réalité du **jour où commence l'année de
  calcul**, et **72 des 226 fiches** le calculent sur la donnée : leur
  année démarre à une date propre à **chaque couple station-variable**.
  La description disait en outre « pour les fiches d'étiage et de crue »,
  alors que les pluies extrêmes et la sensibilité climatique sont aussi
  concernées.

- **La colonne `id` du catalogue était annoncée partout sans être rendue
  (2026-07-28).** La description de `cards`, celle de `/v1/cards/{id}` et
  le README renvoyaient tous à « la colonne `id` de /v1/cards » ; cette
  colonne n'existait pas dans la réponse. On devinait donc `variable_en`,
  qui est le bon identifiant pour 129 fiches sur 472 et le mauvais pour
  les 343 autres : `ETPMA_month.yaml` produit `ETPMA_jan` à `ETPMA_dec`,
  et c'est le nom du FICHIER qu'attendent les endpoints. Le catalogue
  rend maintenant cette colonne. Cherché en ajoutant `ids`, trouvé en
  se demandant quel identifiant y mettre : la fonctionnalité a révélé le
  défaut.

- **Les exemples ne pré-remplissaient rien.** L'entrée du 2026-07-24
  annonçait des champs pré-remplis permettant d'exécuter une requête
  « sans rien chercher » : à l'écran, `stations` et `cards` affichaient
  un placeholder gris. En cause, `examples=` de FastAPI, qui range la
  valeur dans le **schéma** du paramètre, là où Swagger ne la lit pas.
  `openapi_examples=` remplit bien, mais produit des `examples`
  **nommés au niveau du paramètre**, que Swagger surmonte d'un **menu
  déroulant**. Avec un seul exemple, ce menu n'affichait que le libellé
  de la valeur déjà présente dans la case juste en dessous (« Étiage
  VCN10 » au-dessus de `VCN10`) : une ligne de plus à lire pour rien.
  La forme retenue est `json_schema_extra={"example": ...}`, soit
  `example` **au singulier** dans le schéma, la seule des trois que
  Swagger recopie dans le champ **sans rien poser au-dessus**. Le mot
  n'existe pas dans JSON Schema 2020-12, qui n'a qu'`examples` : un
  validateur strict l'ignore comme annotation inconnue, c'est le prix
  du pré-remplissage sans menu. La glose de chaque valeur, qui vivait
  dans le libellé du menu, est passée dans la `description` du
  paramètre, où elle se lit à côté du champ. Même leçon que le thème
  raté de juillet : constater qu'une chose est déclarée ne dit rien de
  ce qui rend, ça se regarde.

### Modifié

- **Les facettes de `/v1/cards` filtrent par slug, et par lui seul**
  (rupture assumée : `?phenomenon=basses eaux` renvoie désormais 422 avec
  la liste des valeurs valides). Une requête désigne un concept, donc par
  un identifiant neutre ; une réponse le présente, donc dans une langue.
  Les libellés restent dans le résultat, dans `/v1/vocabulary` et sous
  `lang=`. La bibliothèque `card.list_cards()` reste plus permissive et
  accepte les libellés. Sans ce resserrement, un même concept avait trois
  orthographes et le contrat ne pouvait plus annoncer ses valeurs.

- **Revue FAIR (2026-07-24) et premiers correctifs.** Aucun changement
  récent de card ne casse le service (les 41 tests hors-ligne passent
  contre le card à jour : le rangement des fiches par régime et les
  renommages remontent par l'API Python, jamais par des chemins). Livré
  en phase 1 :
  - **route d'accueil `GET /v1`** : décrit le service, relie l'écosystème
    (card définit, stase calcule, Hub'Eau fournit) et pointe la
    réutilisation (API ponctuelle, lib Python, citation par swhid) ;
  - **bloc `rights`** dans les réponses de résultat et l'accueil : données
    Hub'Eau en Licence Ouverte / Etalab 2.0, définitions en GPL-3.0,
    résultat citable. Le trou FAIR-Reusable le plus réel (les droits sur
    la sortie n'étaient énoncés nulle part) ;
  - **CORS** ouvert (lecture) : un site web tiers peut appeler le service ;
  - **OpenAPI enrichi** : description qui situe le projet, `contact`,
    `license_info`, endpoints groupés par tags (service, cards, data,
    stations, jobs).

  Plan complet et phases suivantes : `docs/dev/PLAN_FAIR.md`.

- **`/docs` : champs éditables d'emblée et exemples pré-remplis.** Il
  fallait cliquer « Try it out » avant chaque essai, et les champs étaient
  vides. On ouvre maintenant `/docs`, on déplie `/v1/extract` et on exécute
  une vraie requête sans rien chercher (`F700000103`, `QA,VCN10`). Le pavé
  « Schemas » est masqué, il noyait la page. Les endpoints sont groupés par
  tags, le contact dit ce qu'il est (dépôt GitHub du service, il annonçait
  « INRAE, UR RiverLy » en pointant un dépôt personnel).

- **Thème sombre de `/docs`**, à la deuxième tentative. La première,
  le matin même, posait une centaine de règles écrites à l'estime : elles
  ne recouvraient qu'une fraction des 179 ko de CSS de Swagger, d'où un
  fond sombre avec la moitié des composants restés clairs, pire que le
  thème par défaut. Elle avait été « vérifiée » en constatant que le CSS
  était *injecté*, jamais que la page *rendait*.

  Le thème livré ne devine plus aucune classe : `scripts/build_theme.py`
  relit le CSS réel de Swagger et ré-émet chacune de ses règles de
  couleur transposée dans la gamme sombre, ce qui en couvre environ 420.
  Il s'est jugé à la capture d'écran, page dépliée et requête exécutée,
  ce qui a fait ressortir ce qu'aucun test n'aurait vu : « Request URL »
  en sombre sur sombre, boutons copier/télécharger restés clairs, champ
  invalide viré au saumon, et le coloriseur de Swagger qui barbouillait
  la barre de calendrier de la fiche dessinée.

  Gris neutres à gamme ouverte, couleur réservée aux méthodes HTTP et
  jamais seule porteuse de l'information, hors axe rouge/vert. Conception,
  palette et façon de vérifier : `docs/dev/THEME_DOCS.md`.

### Modifié

- README : les cinq exemples Python et les quatre exemples R sont
  rejoués contre une instance locale à Hub'Eau simulé, ce qui n'avait
  plus été fait depuis leur écriture. Tous passent. Ajoutés :
  `stations_meta=true`, qui rend un résultat autoportant et n'était pas
  documenté, les deux liens vers la définition d'une fiche, et une
  section « Citer » qui reflète la provenance réellement publiée plutôt
  que la seule version de card.

### Ajouté

- **Empreinte des données d'entrée** (`data_fingerprint`), qui répond à
  une question et une seule : deux résultats reposent-ils sur la même
  donnée ? Hub'Eau révise ses chroniques, et sans elle un écart entre
  deux calculs ne se distinguait pas d'un changement de code, il fallait
  enquêter. Le résultat gelé d'un job porte en plus le détail par station
  (`data_fingerprints`), la verbosité étant utile dans l'artefact qu'on
  archive et déplacée dans une réponse immédiate.

  Calculée sur les octets des colonnes et non sur le fichier de cache :
  gzip inscrit un horodatage dans son en-tête, donc deux compressions
  d'une même donnée donnent des octets différents. Passer par les
  tableaux rend aussi l'empreinte indépendante du format CSV et des
  versions de pandas. Prise sur la chronique entière, avant tout filtre
  de période, puisque c'est la source qu'on identifie. Coût mesuré :
  2 ms par station, soit un demi-dixième de seconde pour les 228 stations
  du RRSE.

### Corrigé

- **Le LTP n'était pas reproductible.** Il départage les ex-æquo au
  hasard, choix documenté dans le `tools.R` d'origine, et `stase` permet
  de fixer la graine ; le service ne la passait pas. Deux appels
  identiques rendaient donc des p-values différentes (mesuré : 0.90398,
  0.90446, 0.90401 sur la même série). Une graine est désormais fixée
  en dur, et publiée dans la provenance d'un
  job, pour qu'un calcul puisse être rejoué.
- **`data_fetched_at` datait le calcul, pas la lecture des données.** Le
  cache des chroniques vit 24 h : les deux pouvaient différer d'autant,
  alors que Hub'Eau révise ses données et que c'est la date de lecture
  qui rend deux résultats comparables. La date vient maintenant du cache
  lui-même, et à défaut d'information, de l'instant courant, qui reste
  une borne vraie.

### Ajouté

- Les réponses **synchrones** portent `data_fetched_at`, qui n'existait
  que dans les jobs. Un résultat immédiat est tout aussi archivable
  qu'un résultat de job, il doit dire la même chose.

## 0.2.0 (2026-07-22)

### Corrigé

- La validation croisée MAKAHO échouait sur `tQJXA` et `dtLF` depuis
  stase 0.4.0, sans que personne le voie : le test comparait
  `a_relative` au `a_normalise` de R pour des variables **non
  relatives**. Or 0.4.0 a délibérément séparé les registres, et
  `a_relative` vaut désormais NaN dans ce cas, là où R recopiait la
  pente absolue. Le test vérifie maintenant le contrat réel, en prouvant
  au passage que la copie de R était bien redondante avec `a` (aucune
  information perdue). La parité de fond, `a`, `p` et `H` contre MAKAHO
  à 1e-12 sur 228 stations, n'a jamais bougé.

### Modifié

- Documentation restructurée comme dans card et stase : un rôle par
  fichier, un bandeau de statut en tête. `docs/dev/API.md` perd son
  état d'avancement figé au 2026-07-16 (il annonçait encore le
  déploiement comme restant à faire) et ses étapes, toutes réalisées,
  au profit de ce journal ; il garde la carte de l'écosystème, le modèle
  d'accès et les arbitrages, qui engagent encore le code.

## 2026-07-20

### Corrigé

- `GET /v1/cards/{id}` déguisait un bug serveur en fiche inconnue.
  `card.info()` lève `FileNotFoundError` pour deux causes sans rapport,
  la fiche absente du corpus ou un fichier de données du paquet
  illisible ; le `except` attrapait les deux et répondait 404, ce qui a
  fait chercher l'erreur du côté de l'identifiant demandé alors que
  l'empaquetage de card était en cause. Seule la première reste un 404,
  la seconde repart en 500 avec sa trace.

### Modifié

- La conception du service est rapatriée dans ce dépôt, et la conception
  de l'export SKOS repart dans card, dont la classification est la
  source de vérité. Chaque sujet chez son propriétaire.

## 2026-07-18

### Ajouté

- `GET /v1/jobs` liste les jobs de l'appelant, sur présentation de sa
  clé. Pas de listing public.
- `DELETE /v1/jobs/{id}` (dismiss OGC), le ticket faisant capacité, avec
  un 409 tant que le calcul tourne : le calcul n'est pas interruptible.
- `stations_meta=true` sur extract, trend et jobs joint les
  enregistrements du référentiel Hub'Eau, ce qui rend un résultat
  autoportant. La carte d'exemple n'a plus besoin d'une seconde série
  d'appels.
- `CITATION.cff` et `codemeta.json` (voie Software Heritage et HAL, pas
  de Zenodo, choix de l'utilisateur), plus une section « Citer » au
  README.
- `scripts/veille_sante.py` : surveillance de santé à lancer **hors de
  la VM** par cron, une sentinelle hébergée sur la machine surveillée
  mourant avec elle. Seuils par variables d'environnement, notification
  ntfy.sh optionnelle.

### Modifié

- **Clés de priorité durcies.** `keys.json` ne stocke plus que
  `{préfixe: sha256, nom}` : le jeton n'est montré qu'une fois, à la
  création, et la recherche se fait par empreinte. Le journal et les
  jobs enregistrent le préfixe et jamais le nom, si bien que le lien
  entre préfixe et personne ne vit que dans `keys.json` et meurt avec la
  révocation. Mention RGPD ajoutée au formulaire de demande. Tickets de
  job portés à 64 bits. **Non rétroactif** : les clés sont à recréer au
  déploiement.
- Journal segmenté par année (`usage-AAAA.jsonl`) : la rotation devient
  structurelle, la rétention redevient de la gestion de fichiers.
- `/v1/health` distingue le disque de la VM entière, qui est ce qui
  borne les jobs et qui est partagé avec les autres services, de
  l'empreinte propre du service (cache, jobs, journal). Fin de la
  confusion « le disque a l'air plein ».

## 2026-07-17

### Ajouté

- **Premier déploiement**, sur la VM de l'utilisateur. Le frontal n'est
  pas Caddy mais l'Apache déjà en place, qui sert d'autres services :
  `make apache` génère le vhost reverse-proxy depuis `DOMAIN`, le
  conteneur n'écoute que sur `127.0.0.1`, et `CARD_API_PORT` rend le
  port hôte configurable (8000 était déjà pris). Caddy devient un profil
  compose optionnel, pour le cas d'une VM nue.
- `GET /v1/trend?series=true` joint les séries extraites du calcul qui a
  produit la tendance, ce qui lève le doute entre cache et révisions de
  données quand on compare deux appels.
- `examples/carte_tendance_QA.R` : carte de tendance sur les 228
  stations du RRSE, de bout en bout par le motif job.

### Corrigé

- `/v1/health` annonçait la version « dev » : `CARD_VERSION` cherchait
  une distribution nommée `card` alors qu'elle s'appelle `card-stase`,
  le nom PyPI étant en attente.

### Modifié

- README réécrit autour des parcours d'usage, chaque exemple vérifié par
  exécution contre une instance locale.

## 2026-07-16

Création du service, de l'ébauche au dépôt complet.

### Ajouté

- `GET /v1/cards` et `/v1/cards/{id}` : le catalogue, filtrable par les
  facettes de la classification dans les deux langues.
- `GET /v1/stations` : recherche dans le référentiel Hub'Eau, pour ne
  pas avoir à connaître les codes à l'avance. Les codes ont changé à la
  refonte Hydro, ce qui rend le service d'autant plus utile.
- `GET /v1/extract` : chroniques journalières Hub'Eau (`obs_elab`,
  QmnJ) mises en cache, puis exécution des fiches. Les fiches dont
  l'entrée n'est pas un débit sont refusées explicitement, faute de quoi
  l'affectation automatique de colonne de card calculerait une variable
  de pluie sur du débit, en silence.
- `GET /v1/trend` : extraction puis `stase.trend`, sur les seules fiches
  `output: series`, ce que la classification permet de vérifier. AR1 par
  défaut, les étiages étant autocorrélés.
- `sampling=preferred|MM-JJ` : impose la fenêtre annuelle déclarée par
  la fiche, ce qui reproduit le protocole de MAKAHO et rend les stations
  comparables entre elles.
- **Motif job** en forme OGC API Processes : `POST /v1/jobs` répond 202
  et Location, le suivi donne l'avancement par station, et le résultat
  est gelé avec un bloc de provenance (paramètres, versions, date de
  récupération des données) qui le rend citable. Une demande synchrone
  trop grosse bascule automatiquement en job au lieu d'être refusée.
  File bornée en mémoire et fils d'exécution, sans Redis.
- **Quotas par IP** en fenêtre glissante, avec 429 et Retry-After, et
  journal d'usage anonymisé : l'IP n'est jamais stockée en clair, elle
  est hachée avec un sel. C'est la matière première des bilans d'impact
  pour les dossiers de financement.
- **Clés de priorité** gratuites, attribuées à la main sur demande :
  quotas par minute sautés, plafonds relevés, et tête de file.
- Tableau de bord terminal (`make stats`, `make watch`).
- Client Hub'Eau durci : trois tentatives à pause croissante sur
  expiration, erreur de transport ou 5xx, puis un 504 propre avec
  Retry-After plutôt qu'un 500 brut.
- **Validation croisée MAKAHO** : `stase.trend` sur leurs séries
  agrégées reproduit leurs tendances à la précision machine (1e-12, 228
  stations). Point de protocole découvert à cette occasion : MAKAHO
  n'utilise pas l'échantillonnage adaptatif des fiches, il impose leur
  fenêtre préférée partout.

Détail de la conception : `docs/dev/API.md`. Déploiement et variables
d'environnement : `INSTALL.md`.

# La page /docs en panne, et ce qu'elle dit de la complexité du service

> **Statut : audit du 2026-10-11, figé.** Il constate et ne change plus.
> Ce qui a été corrigé est dans `CHANGELOG.md` (0.8.1). Les choix qui en
> sortent vont dans `CLAUDE.md` ou `API.md`, ses tâches dans
> `CHANTIERS.md`. Les chiffres datent du jour : ils ne sont tenus à jour
> nulle part, ils disent sur quoi la lecture repose.

## 1. L'incident

La page `/docs` s'affichait sans son thème, et les routes de calcul n'y
proposaient plus aucun champ. L'API, elle, répondait juste.

### Chronologie

| date                    | fait                                                                 |
|-------------------------|----------------------------------------------------------------------|
| 2026-07-27              | la page appelle ses feuilles avec une empreinte (`?v=`)              |
| 2026-07-29              | clés par courriel ; la fenêtre « Authorize » garde l'ancien texte    |
| 2026-08-13              | refus des paramètres inconnus (0.4.0), `?key=` déclaré pour le quota |
| au plus tard 2026-09-18 | les deux défauts sont en ligne (production en 0.5.0)                 |
| 2026-09-18 au 10-11     | production arrêtée à 0.5.0 : 0.6.0 à 0.8.0 non déployées             |
| 2026-10-11              | correction, `.env` aligné sur l'exemple, déploiement de 0.8.1        |

### Les trois défauts

1. **Le thème.** La route des feuilles ne déclarait pas `v`. Le refus des
   paramètres inconnus lui faisait répondre 422, et le navigateur écartait
   la feuille sans rien signaler.
2. **Les champs.** FastAPI ne déplie un modèle de paramètres
   (`p: Annotated[TrendParams, Query()]`) dans le contrat que s'il est le
   seul paramètre de requête de la route, dépendances comprises.
   Déclarer `?key=` dans la dépendance de quota, même masqué du schéma,
   suffisait : sept routes n'annonçaient plus qu'un objet `p`. Les appels
   marchaient, FastAPI lisant une requête dépendance par dépendance.
3. **Le texte de la fenêtre « Authorize ».** Il envoyait vers une issue
   du dépôt, retirée deux semaines plus tôt.

Les deux premiers viennent du même commit (`2bd3b92`), une règle de
sûreté ajoutée pour une bonne raison : un filtre mal orthographié rendait
tout le catalogue en silence.

### Pourquoi rien n'a rougi

Les tests vérifiaient un intermédiaire, pas ce qu'on voit. Ils
demandaient la feuille à son adresse nue, pas à celle que la page émet ;
ils vérifiaient que les appels répondaient, pas que le contrat annonçait
les champs. Les tests ajoutés en 0.8.1 vérifient le résultat visible, et
chacun échouait avant son correctif.

Deux des trois défauts venaient avec un commentaire faux ou périmé : la
règle disait les routes statiques « sans contrat déclaré », et la fenêtre
parlait encore d'issue. Personne n'a regardé `/docs` en production
pendant plusieurs semaines.

## 2. Mesures

Lignes portant du code, de commentaire ou de docstring dans
`src/card_api/`, lues par le module `tokenize` de Python à chaque tag ;
lignes des fichiers de `tests/` ; taille des deux fichiers de suivi.
Les docstrings des routes sont aussi les descriptions de l'OpenAPI.

| version | date       | code | commentaires et docstrings | tests | CLAUDE.md | CHANGELOG |
|---------|------------|-----:|---------------------------:|------:|----------:|----------:|
| 0.2.0   | 2026-07-22 | 1052 |                        278 |   692 |    6,2 Ko |    8,3 Ko |
| 0.3.0   | 2026-08-05 | 1885 |                       1252 |  2197 |   19,1 Ko |   65,2 Ko |
| 0.4.0   | 2026-08-13 | 1923 |                       1302 |  2264 |   19,1 Ko |   70,2 Ko |
| 0.5.0   | 2026-09-18 | 1923 |                       1313 |  2303 |   19,6 Ko |   72,7 Ko |
| 0.6.0   | 2026-09-18 | 2038 |                       1484 |  2546 |   21,6 Ko |   79,9 Ko |
| 0.7.0   | 2026-09-19 | 2371 |                       1923 |  3282 |   25,0 Ko |   90,7 Ko |
| 0.8.0   | 2026-09-19 | 2447 |                       2024 |  3444 |   26,2 Ko |   96,8 Ko |
| 0.8.1   | 2026-10-11 | 2447 |                       2040 |  3502 |   26,5 Ko |   99,1 Ko |

Par module, en 0.8.1 :

| module       | code | commentaires | docstrings |
|--------------|-----:|-------------:|-----------:|
| main.py      | 1124 |          360 |        450 |
| pipeline.py  |  298 |          118 |        224 |
| cache.py     |  242 |           66 |        291 |
| stats.py     |  219 |           64 |         36 |
| jobs.py      |  188 |           66 |         38 |
| hubeau.py    |  132 |           63 |         59 |
| usage.py     |   98 |           39 |         53 |
| keys.py      |   79 |           10 |         22 |
| pool.py      |   53 |           28 |         40 |
| serialize.py |   14 |            8 |          5 |

La surface : 22 opérations publiques dans le contrat, 21 réglages dans
`.env.example`, 15 cibles `make`, 256 Ko de documentation Markdown.

L'usage : la sonde de production annonçait 3,0 Mo de cache avant le
déploiement de 0.8.1, pour un plafond de 5 Go, et 0,1 Mo après, les
copies à l'ancien format ayant été évincées. Le journal d'usage est sur
la VM, `make stats` le donne ; il n'a pas été lu pour cet audit.

Ce qui bouge sans commit : `fastapi` n'est pas épinglé dans
`pyproject.toml` ; la page charge Swagger UI en `swagger-ui-dist@5`, qui
servait la 5.33.1 le jour de l'audit ; le calque de couleurs généré ne
note que `@5`, donc on ne sait plus de quelle version il a été tiré.

## 3. Lecture

1. **L'incident ne vient pas du chantier du cache.** Il vient d'une
   règle de sûreté transversale et d'un texte resté en arrière.
2. **La plus forte croissance est celle de 0.2.0 à 0.3.0** (fin
   juillet : file de calcul, clés, thème, journal), pas celle du cache.
   Le cache (0.5.0 à 0.8.0, deux jours) a ajouté 524 lignes de code, 711
   de commentaires et 1 141 de tests.
3. **Le cache répond à une mesure.** Aller chercher une chronique coûte
   une trentaine de fois ce que coûte la calculer, et une fiche d'étiage
   prend 35 s sur 200 stations (`PLAN_CACHE.md`). Une partie est en
   revanche taillée pour un usage à venir : l'éviction par la place, le
   registre des lectures, la tâche de fond qui rafraîchit. Elle se juge
   sur `make stats` quand un client à l'échelle de MAKAHO interrogera la
   production, comme `PLAN_CACHE.md` le prévoit déjà.
4. **Le poids est dans la prose autant que dans le code.** Dans
   `src/card_api/`, commentaires et docstrings font presque autant de
   lignes que le code. Une partie raconte l'histoire (« constaté le … »),
   que git et le CHANGELOG portent déjà. Un commentaire dérive comme du
   code, et aucun test ne l'exécute : c'est ce qui s'est passé deux fois
   ici.
5. **Les points fragiles sont ceux qui contournent le framework.** La
   règle des paramètres inconnus refait une partie de ce que fait
   FastAPI (`_params_declares`), et elle a cassé deux fois. Le thème est
   généré pour une version de Swagger que la page ne fixe pas. FastAPI
   sait refuser lui-même un paramètre inconnu sur un modèle de paramètres
   (`model_config = {"extra": "forbid"}`) en gardant le contrat déplié :
   essayé le 2026-10-11 sur FastAPI 0.139.0. Le seul obstacle est
   `?key=`, qu'un modèle devrait alors déclarer.
6. **Ce qui grimpe, c'est le nombre de choses qui doivent rester vraies,
   rapporté à l'attention d'une seule personne.** Trois versions non
   déployées et une page cassée plusieurs semaines sans être vue en sont
   le signe, plus que le nombre de lignes.

## 4. Si le service doit agréger davantage

L'envie est formulée : faire de ce service un lieu qui rassemble des
données environnementales de plusieurs sources, pour aider à comprendre
l'environnement et les changements en cours.

Ce qui fait tenir l'écosystème aujourd'hui est son découpage : `card`
définit les variables, `stase` les calcule, `card-api` les sert. Le
service est une façade, et sa propre règle le dit : la chaîne de calcul
n'est écrite qu'une fois, ailleurs que dans les routes.

Agréger, c'est un autre métier : collecter, stocker, rafraîchir,
contrôler, tracer la provenance. Chaque source apporte l'équivalent de
`hubeau.py`, ses particularités (site ou station, unités, pagination),
ses pannes, sa licence et son rythme de mise à jour. Le stockage passe
du mégaoctet au gigaoctet, les mises à jour deviennent des traitements
planifiés. Logé dans `card-api`, tout cela ferait porter un entrepôt à
une façade.

Si l'envie se confirme, l'audit recommande de garder le découpage : un
composant à part, avec son dépôt et une seule responsabilité (collecter
et conserver la donnée avec sa provenance), que `card-api` lirait comme
il lit Hub'Eau. Et, avant de le construire, de regarder qui agrège déjà
ce dont on a besoin : Hub'Eau en est lui-même un.

Ce que l'incident enseigne pour cette suite : ce qui casse, ce sont les
règles appliquées à toutes les routes et les contournements du
framework, et ils se multiplient avec la surface.

Questions à trancher avant toute ligne de code : quelles données, pour
quels usagers, où cela vit, et qui l'entretient.

## 5. Ce que l'audit propose

À trancher, puis à reporter dans `CHANTIERS.md` pour ce qui est retenu.

1. **Épingler FastAPI et la version de Swagger UI**, et noter dans le
   calque généré la version dont il est tiré. Ni le contrat ni le thème
   ne bougeraient plus sans commit.
2. **Après un `make update`, ouvrir `/docs`.** Un geste, pas un outil :
   c'est déjà la règle de `THEME_DOCS.md` (« regarder la page »).
3. **Alléger la prose** (`CLAUDE.md`, récits datés dans le code) par la
   procédure commune de `../card/docs/dev/NETTOYAGE.md`.
4. **Remplacer la règle maison par le refus natif de FastAPI**, la clé ne
   passant plus que par en-tête. Changement de contrat, donc nouvelle
   version mineure, à instruire avant.
5. **Écrire le projet d'agrégation** (données, usagers, lieu,
   entretien) avant d'y toucher.

> **Statut : norme en vigueur.** Conception du service : la carte de
> l'écosystème à trois dépôts, le modèle d'accès et les arbitrages qui
> engagent encore le code. Ce que le service FAIT aujourd'hui se lit dans
> le README ; ce qui a changé et quand, dans `CHANGELOG.md` à la racine.

# Conception du service card-api

> Réflexion du 2026-07-16, **arbitrée le jour même** : repo `card-api`,
> service full public sans clé (modèle Hub'Eau) avec quota par IP,
> file d'attente bornée + motif job pour les grosses demandes, clés de
> priorité gratuites à la demande pour les besoins massifs ; extract
> ET trend en v1, multi-stations + plage temporelle + liste de fiches ;
> données utilisateur (POST) reportées. Aspect commercial écarté (les
> statistiques d'usage valent plus, comme preuve d'impact pour les
> financements, que des recettes de niche).

## Où ranger quoi : la carte de l'écosystème

Principe : **card reste une bibliothèque de calcul pure** (installable,
légère, sans dépendance service). Tout ce qui est *service* (réseau,
cache, clés, déploiement) vit dans un repo séparé, comme stase et card
sont déjà séparés par nature (moteur / fiches).

```
stase        moteur d'extraction/stationnarité         (repo existant)
  ▲
card         fiches + classification + fonctions hydro (repo existant)
  │            ├─ scripts/generate_catalog.py → docs/CARDS.md   (Pages)
  │            └─ scripts/generate_skos.py    → docs/card.ttl   (Pages, chantier §4)
  ▼
card-api     service web FastAPI                       (NOUVEAU repo, VM)
               ├─ hubeau.py    client Hub'Eau + cache des chroniques
               ├─ main.py      endpoints v1
               ├─ auth/quotas  clés d'API (statistiques d'usage)
               └─ Dockerfile / systemd (déploiement VM)

Skosmos      navigateur de thésaurus (VM, optionnel)   lit docs/card.ttl
```

Pourquoi un repo séparé (`card-api`, nom de travail) :
- cycles de vie différents (une fiche corrigée ≠ un redéploiement ;
  une évolution d'endpoint ≠ une release card) ;
- dépendances contenues : card garde numpy/pandas/yaml ; l'API ajoute
  fastapi/uvicorn/httpx sans alourdir les utilisateurs de la
  bibliothèque ;
- le déploiement (Docker, secrets, logs) ne pollue pas le package
  scientifique ;
- même logique de frontière que stase/card : la donnée nationale et le
  réseau sont un métier, le calcul en est un autre.

## Modèle de l'API v1

Toutes les réponses JSON portent `card_version`, `stase_version` et la
`version` de chaque fiche utilisée (discipline de versions en place).
Préfixe `/v1` dès le départ.

### Découverte

- `GET /v1/cards` : le catalogue des fiches. Filtres = les facettes de
  la classification, désignées par leur **slug** (listes fermées
  annoncées dans l'OpenAPI, donc rendues en menus déroulants) :
  `?phenomenon=low-flows&output=series`, `&operator=delta`,
  `&function=baseflow`, `&search=étiage`. La langue ne filtre pas, elle
  s'affiche : les libellés fr/en sont dans le résultat, dans
  `/v1/vocabulary`, et `lang=` choisit celle du rendu. La bibliothèque
  `card.list_cards()` reste plus permissive et accepte les libellés.
- `GET /v1/cards/{id}` : détail d'une fiche (info + lien vers le YAML
  source sur GitHub).
- `GET /v1/stations?dept=07&river=Ardèche&bbox=...` : recherche de
  stations (proxy du référentiel Hub'Eau) pour ne pas obliger à
  connaître les codes à l'avance.

### Calcul

- `GET /v1/extract?stations=H5920010,K0550010&cards=QA,VCN10&start=1970-09-01&end=2020-08-31`
  : télécharge les chroniques journalières Hub'Eau
  (`hydrometrie/obs_elab`, QmnJ), exécute card, renvoie
  `{data, meta}`. Le CSV était prévu ici en `&format=csv` ; il est servi
  par `/v1/extract.csv`, cf. « Une représentation, une URL ». `stations` est
  une liste (plafonnée en public, déplafonnée avec clé de priorité) ;
  `start`/`end` optionnels (défaut : chronique complète).
- `GET /v1/trend?stations=...&cards=QA,VCN10&mk=INDE` : enchaîne
  extraction + `stase.trend` (Mann-Kendall/Sen) : le diagnostic de
  stationnarité complet, à la MAKAHO. Mêmes paramètres qu'extract.
- Grosses demandes (au-delà d'un seuil stations×fiches) : motif
  **job** : la requête renvoie `{job_id}`, résultat sur
  `GET /v1/jobs/{id}` quand il est prêt.
- (reporté) `POST /v1/extract` sur données fournies par l'utilisateur.

### Infrastructure : accès en trois étages (modèle Hub'Eau)

1. **Public sans clé** (défaut) : quota par IP (requêtes/minute) et
   plafond de stations par appel : zéro friction.
2. **File d'attente bornée** avec travailleurs pour les endpoints de
   calcul : en saturation le service fait patienter (429 +
   Retry-After, ou motif job), il ne s'écroule pas.
3. **Clés de priorité** gratuites, attribuées à la demande (manuel au
   début) : passage devant dans la file + plafonds levés, pour les
   besoins massifs (en-tête `X-API-Key`). Pas d'inscription pour
   l'usage normal.

**Où porte réellement la protection (revu le 2026-07-29).** Le quota par
IP a d'abord été posé bas, par prudence. C'est l'étage 2 qui protège
vraiment : le sémaphore de calcul sérialise les traitements lourds et la
bascule en job absorbe les grosses demandes, quel que soit le rythme des
appels. Le compteur par minute, lui, compte des requêtes et non leur
coût, alors qu'une requête de 10 stations et 20 fiches pèse cent fois
une requête d'une station. Serré, il ne réduit donc pas la charge de
manière fiable, mais il gêne deux innocents : un établissement entier
derrière une seule IP publique, où le plafond se partage entre collègues
sans que personne n'aille vite, et la boucle station par station, premier
script que tout le monde écrit. D'où des plafonds larges, et surtout le
choix de les rendre MESURABLES : un refus est journalisé comme événement
(jamais comme usage) et `make stats` affiche combien d'IP distinctes sont
repoussées. Une personne bloquée trente fois est un script à qui il faut
expliquer la liste ; trente personnes bloquées une fois est un plafond
trop bas. Les valeurs se règlent désormais sur cette observation.

- **Journal d'usage** anonymisé (IP hachée, endpoint, stations,
  fiches, date) → la matière première des bilans d'impact pour les
  dossiers de financement, sans gestion de comptes.
- **Cache à deux étages** : chroniques par station (TTL quotidien,
  les séries validées bougent peu) ; résultats d'extraction par
  (station, fiche, version de fiche) : l'invalidation est offerte par
  la discipline de versions.
- Respecter la politique de débit Hub'Eau (taille de page, pauses) ;
  bannière de provenance des données (Licence Ouverte, eaufrance).
- **Formats de réponse (arbitré 2026-07-16)** : JSON `records` par
  défaut (convention de l'écosystème, Hub'Eau compris) + option
  `orient=columns` (colonnaire, compact, rechargeable en DataFrame) ;
  gzip systématique. Le caractère FAIR vient de l'auto-description
  (métadonnées avec unités et labels bilingues, source, licence,
  versions dans chaque réponse), pas de l'orientation. Évolution possible si une
  demande d'interopérabilité géo/climat se présente : **CoverageJSON**
  via le patron OGC API-EDR (le standard des séries temporelles
  environnementales) : non prioritaire.

## Une station muette n'annule pas le lot (arbitré 2026-07-29)

Une demande de vingt stations échouait entièrement dès que l'une d'elles
n'avait pas de série, le travail déjà fait compris. Le cas rencontré :
`U430003001`, la Saône à Dracé, échelle aval de Mâcon. Le référentiel la
donne `en_service: true`, jamais fermée, fiche mise à jour cinq mois plus
tôt, et Hub'Eau ne publie aucun QmnJ pour elle, ni pour son site. C'est
une échelle limnimétrique : elle mesure une hauteur, et sans courbe de
tarage une hauteur ne devient pas un débit.

**On ne peut pas l'éviter en amont.** `/v1/stations` proxie
`referentiel/stations`, un registre administratif des stations qui
existent, pas un catalogue des séries disponibles. Les deux champs qui
sembleraient servir n'en disent rien :

| station | `type_station` | `en_service` | QmnJ |
|---|---|---|---|
| K066331001 | STD | true | 20435 |
| U430003001 | STD | true | **0** |
| U471001001 | STD | **false** | 20437 |

`type_station` ne discrimine pas, et `en_service` est à contre-emploi :
une station fermée garde son historique, ce qu'une étude de tendance veut
précisément. Demander la série est le seul test. Sonder chaque code avant
le calcul a été envisagé puis écarté : cela double les appels à Hub'Eau et
ne fait qu'anticiper un refus, sans régler le fond, qui est qu'une station
muette ne devrait pas coûter les dix-neuf autres.

**La ligne de partage retenue n'est pas la gravité, c'est la
reproductibilité.** Ce qui est vrai de la station elle-même (pas de série
publiée, rien dans la période, code de site ambigu) est un fait stable :
il se rapporte dans `stations_omitted` et le calcul continue. Ce qui tient
à l'instant de l'appel (Hub'Eau injoignable) reste une erreur `504`.
Sauter le second fabriquerait, les jours de panne, des résultats
silencieusement plus petits, noyés au milieu d'omissions d'apparence
banale : personne ne le remarquerait.

Trois conséquences tenues comme des règles. `stations` décrit désormais
les DONNÉES et non la demande, sans quoi une jointure faite sur cette
liste porte à faux ; `stations_requested` garde la demande. Le bloc
`stations_omitted` est toujours présent, vide quand tout va bien : une
clé qui n'apparaît qu'en cas de problème oblige chaque client à tester sa
présence et laisse croire à celui qui l'ignore que le cas n'existe pas.
Et l'omission voyage dans TOUTES les représentations, lignes `#` du CSV
et figure comprises : c'est la leçon du ticket de job, qui ne sortait
qu'en JSON et rendait un 500 partout ailleurs.

Reste une piste, écartée pour l'instant : mémoriser qu'une station n'a
pas de QmnJ permettrait à `/v1/stations` d'annoncer la disponibilité sans
appel supplémentaire, et le catalogue se corrigerait à l'usage. Écarté
parce qu'un cache de cette nature devient faux le jour où Hub'Eau publie
enfin la série, et qu'un état explicite au moment de la demande vaut
mieux qu'une prédiction qui vieillit.

## Une représentation, une URL (arbitré 2026-07-28)

Question posée par la tendance dessinée : sous-endpoint ou paramètre
`format` ? Elle revient à chaque fois qu'un résultat peut se lire de
plusieurs façons, la règle est donc écrite une fois pour toutes.

> **Le critère : l'information change-t-elle, ou seulement son encodage ?**
>
> - Seulement l'encodage → **extension de chemin** (`/v1/trend.csv`).
> - L'information change (on retire, on ajoute, on interprète) →
>   **sous-ressource** (`/v1/trend/figure`).
>
> Dans les deux cas, une représentation a **son URL**. Jamais un
> paramètre de requête.

Ce qui interdit le paramètre `format` n'est pas une préférence de style,
c'est le contrat : **OpenAPI ne sait pas dire « `text/plain` quand
`format=text` »**. Une opération déclare son type de média, point. Un
`format=text` fait donc annoncer du JSON à une réponse en texte, et
aucune précaution ne le rattrape. C'est une limite du format, pas du
code. Essayé le 2026-07-28, retiré le jour même.

Application :

| Représentation | Forme | Pourquoi |
|---|---|---|
| tendance, résultat complet | `/v1/trend` | l'URL nue rend du JSON |
| tendance, lecture humaine | `/v1/trend/figure` | retire les intervalles et les métadonnées, **ajoute** un verdict déduit de `h` : autre objet |
| fiche, détail | `/v1/cards/{id}` | |
| fiche, chaîne de calcul | `/v1/cards/{id}/figure` | même raisonnement |
| tabulaire | `/v1/trend.csv`, `/v1/extract.csv` | mêmes lignes, mêmes colonnes, autre écriture : encodage |

Deux conséquences assumées :

- **`extract` n'a pas de figure.** La règle est « un dessin existe là où
  il aide », pas « tout endpoint a son dessin » : cinquante ans de série
  ne se lisent pas en table.
- **Les paramètres se déclarent une fois.** Deux endpoints qui partagent
  neuf paramètres les recopieraient et divergeraient au premier ajout.
  FastAPI accepte un modèle Pydantic comme paramètres de requête
  (`Annotated[TrendParams, Query()]`) et les deux opérations produisent
  des `parameters` identiques dans le contrat. Sans cela, le
  sous-endpoint coûtait plus cher qu'il ne valait, et c'est ce coût
  supposé qui avait fait choisir `format` en premier lieu.

Précédent dans l'écosystème : l'API écoulement de Hub'Eau sert
`/observations` en JSON et `/observations.csv` en `text/csv`, avec un
`Content-Disposition` qui donne son nom au fichier enregistré. Leurs
autres API (hydrométrie, qualité, piézométrie) refusent `format=csv` :
c'est l'extension qui est leur convention, pas le paramètre.

## Le CSV : provenance et nom de fichier (arbitré 2026-07-28)

Un CSV ne sait pas porter de bloc `versions`, de SWHID, d'empreinte ni
de droits. Livré nu, il devient en trois copies un tableau de chiffres
dont plus personne ne sait d'où il vient, c'est-à-dire exactement ce que
ce service existe pour éviter. Hub'Eau ne résout pas ce point, son CSV
n'a qu'une ligne d'en-tête.

**La provenance part en lignes de commentaire `#`**, avant la ligne de
colonnes : versions et SWHID de card et de stase, stations, fiches,
période demandée, échantillonnage, test et seuil pour la tendance,
source, date de lecture, empreinte des données, droits, référence de
citation. `pandas.read_csv(comment="#")` et `read.csv(comment.char="#")`
les sautent d'eux-mêmes, et elles survivent à l'enregistrement du
fichier, contrairement à un en-tête HTTP.

**Virgule et point décimal**, pas le point-virgule de Hub'Eau : les deux
clients documentés dans le README sont pandas et R, où la virgule est la
norme. Le `;` sert Excel français, au prix d'un fichier que `read_csv` ne
lit pas sans réglage.

### Le nom du fichier

```
card-api_trend_F700000103_QA-VCN10_AR1_2005-2026_ac9c7eed.csv
└ producteur
        └ analyse
                └ stations
                            └ variables
                                       └ test (tendance seulement)
                                           └ période  └ empreinte
```

Les champs sont séparés par `_`, les valeurs d'un même champ par `-`.

L'ordre va **du plus général au plus particulier**, pour que deux
analyses voisines se rangent côte à côte dans un dossier trié par nom.
C'est le principe des conventions de nommage climatiques (CMIP et
consorts), et il vaut ici pour la même raison.

Quatre décisions valent d'être notées :

- **La période vient de la DONNÉE, pas de la demande.** Demander
  « depuis 1970 » sur une station ouverte en 2005 donnerait un nom qui
  ment sur son contenu.
- **L'empreinte termine le nom, et non une date de génération.** Deux
  fichiers de même nom ont la même source ; deux extractions du même jour
  séparées par une révision Hub'Eau ne s'écrasent pas l'une l'autre. Une
  date, elle, changerait sans que rien ne change.
- **Au-delà de trois valeurs, une liste est comptée** (`12stations`,
  `8variables`). Sans ce garde-fou, douze stations donnent un nom de
  150 caractères que personne ne lit et que certains systèmes de fichiers
  refusent.
- **Ce nom se lit, il ne se parse pas.** Un identifiant de fiche peut
  contenir `_` (`QMNA_summer`), ce qui casse la séparation des champs. Ce
  qui se parse est l'en-tête `#`, exhaustif et sans ambiguïté.

`Content-Disposition: attachment; filename=...` accompagne la réponse,
comme chez Hub'Eau : le navigateur enregistre un fichier nommé au lieu
d'afficher du texte.

### Le nom des colonnes (arbitré 2026-07-28)

> Une colonne porte un nom **anglais snake_case**, sauf lorsqu'elle
> **relaie telle quelle** une donnée d'une source extérieure : elle garde
> alors le nom de la source, pour qu'une jointure se fasse sans
> traduction.

D'où `code_station` et non `station` ni `station_code` : ce code n'est
pas une valeur que le service calcule, c'est une valeur que Hub'Eau
donne et que le service transporte. Quelqu'un qui joint son `trend.csv`
au référentiel obtenu par `stations_meta=true` ou par `/v1/stations`
écrit alors `pd.merge(trend, meta)`, sans `left_on`/`right_on`. C'est le
geste le plus fréquent, et il vaut le seul nom français du schéma.

`station` seul aurait été une métonymie : une station a un libellé, des
coordonnées, une date d'ouverture ; la colonne n'en porte que
l'identifiant.

La règle explique aussi pourquoi tout le reste est anglais
(`period_start`, `mean_period`, `a_relative`, `value`) : ce sont des
grandeurs que le service produit, elles n'existent nulle part ailleurs.
Et pourquoi `ids` et `codes`, les listes prêtes à coller, restent en
anglais : ce sont des chaînes que le service fabrique, pas des relais.

### La forme du tableau

`trend.csv` est direct, une ligne par station et par variable, toutes les
colonnes du test. **Rien n'est retiré**, contrairement à la figure : le
CSV est le même résultat autrement écrit, intervalles de pente compris.

`extract.csv` est en forme **longue** (`code_station, date, variable, value`) et
non une colonne par variable : deux fiches n'ont ni le même pas de temps
ni les mêmes années, les mettre côte à côte fabriquerait des trous qui ne
sont pas dans la donnée. `pandas.pivot` et `tidyr::pivot_wider` remettent
en large quand c'est voulu.

## Déploiement : Docker (arbitré 2026-07-16)

`docker compose` à deux services sur la VM :
- **api** : image card-api (uvicorn+FastAPI) qui installe card et
  stase depuis GitHub à révision épinglée (traçabilité : API x.y =
  card @tag + stase @tag) ; concurrence bornée en-process (sémaphore
  sur les endpoints de calcul) : pas de Redis/worker externe en v1 ;
- volume persistant pour le cache des chroniques et le journal d'usage.

**Révision du 2026-07-17** : le frontal n'est pas Caddy mais l'**Apache
déjà en place sur la VM**, qui sert d'autres services. Le conteneur api
n'écoute que sur `127.0.0.1`, `make apache` génère le vhost
reverse-proxy, et Caddy est devenu un profil compose optionnel pour le
cas d'une VM nue. Chemin détaillé : INSTALL.md.

## Articulation avec l'export SKOS

Le SKOS n'est **pas** un service : c'est un artefact de publication de
la classification, qui vit dans card (source de vérité :
`src/card/topics.yaml` + les blocs classification).

La conception de l'export (generate_skos.py, concept schemes par
facette, publication `docs/card.ttl` sur GitHub Pages, URIs w3id.org,
Skosmos optionnel) était décrite ici par accident de rangement. Elle a
été rapatriée le 2026-07-20 dans card, `docs/dev/CHANTIERS.md`, avec
le reste du sujet.

Ce qui reste du ressort du service : l'API pourrait exposer un
`GET /v1/concepts` renvoyant vers ces URIs. C'est un renvoi, pas une
source, et rien ne presse tant que l'export n'existe pas.

## Arbitrages (rendus le 2026-07-16)

1. Nom du repo : **card-api**.
2. `POST /v1/extract` (données utilisateur) : **reporté**.
3. `/v1/trend` : **en v1** avec extract ; multi-stations, plage
   temporelle et liste de fiches sur les deux.
4. Accès : **full public sans clé** (quota IP bas) + file d'attente
   bornée/motif job en cas de charge + **clés de priorité gratuites à
   la demande** pour les besoins massifs (attribution manuelle).
5. w3id.org pour les URIs SKOS : à confirmer le moment venu (pas
   bloquant).

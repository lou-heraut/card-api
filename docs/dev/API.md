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
  `{data, meta}` ; `&format=csv` possible. `stations` est
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
| tendance, lecture humaine | `/v1/trend/figure` | retire les intervalles et les métadonnées, **ajoute** un verdict déduit de `H` : autre objet |
| fiche, détail | `/v1/cards/{id}` | |
| fiche, chaîne de calcul | `/v1/cards/{id}/figure` | même raisonnement |
| tabulaire (à venir) | `/v1/trend.csv` | mêmes lignes, mêmes colonnes, autre écriture : encodage |

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

**Si un CSV est ajouté**, il devra porter sa provenance, sous peine de
défaire ce que le service construit : un tableur qui ne sait plus d'où
viennent ses chiffres. Le moyen retenu sera des lignes de commentaire
`#` en tête (versions, SWHID, empreinte, source, droits), que
`pandas.read_csv(comment="#")` et `read.csv(comment.char="#")` sautent
d'eux-mêmes. Les en-têtes HTTP ne conviennent pas : ils disparaissent
dès l'enregistrement du fichier.

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

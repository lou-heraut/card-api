# card-api

Service web des fiches [card](https://github.com/lou-heraut/card) :
extraction de variables hydroclimatiques sur les débits de la Banque
Hydro (via [Hub'Eau](https://hubeau.eaufrance.fr/)) et diagnostic de
stationnarité Mann-Kendall / pente de Sen (via
[stase](https://github.com/lou-heraut/stase)).

**Documentation interactive : [https://API/docs](https://API/docs)**
(essai des requêtes dans le navigateur, schémas de réponse).

Service public de recherche (INRAE, UR RiverLy). Ouvert, sans
inscription ; code GPL-3, données Hub'Eau en Licence Ouverte.
Déploiement et développement : [INSTALL.md](INSTALL.md).

## Les endpoints

| Endpoint | Rôle |
|---|---|
| `GET /v1/cards` | catalogue des fiches CARD, filtrable par facettes |
| `GET /v1/cards/{id}` | détail d'une fiche (fr/en) + lien vers son YAML |
| `GET /v1/stations` | recherche de stations hydrométriques |
| `GET /v1/extract` | chroniques Hub'Eau → variables CARD |
| `GET /v1/trend` | extraction + test de Mann-Kendall et pente de Sen |
| `POST /v1/jobs` | grosses demandes en file de calcul (202 + ticket) |
| `GET /v1/jobs/{id}` | statut et progression ; `/result` : résultat gelé |
| `GET /v1/health` | santé du service (file de calcul, disque) |
| `/docs` | documentation interactive (OpenAPI) |

Chaque réponse est en JSON et se suffit à elle-même : `data` (les
résultats), `meta` (unités, noms français et anglais, classification),
la source des données et les versions des logiciels. Deux formats au
choix : `orient=records` (défaut, une liste d'objets, comme Hub'Eau)
ou `orient=columns` (colonnaire, `{colonne: [valeurs]}`, plus
compact).

## Préparer sa demande

### La station

La recherche interroge le référentiel hydrométrique Hub'Eau par nom,
code ou département, et renvoie pour chaque station son code, son
libellé, ses coordonnées et son état de service. C'est aussi le moyen
de retrouver le code actuel d'une station connue sous son ancien code
Banque Hydro.

```bash
curl "https://API/v1/stations?libelle=Austerlitz"
# → F700000103 | La Seine à Paris - Austerlitz [>2006]
curl "https://API/v1/stations?departement=07&size=100"
```

### Les fiches

Chaque fiche définit une variable calculable sur la chronique de
débit : module, étiages, crues, saisonnalité... Le catalogue se
filtre par facettes de classification (`domain`, `phenomenon`,
`season`, `output`...) ou par texte libre, en français ou en anglais :

```bash
curl "https://API/v1/cards?phenomenon=basses%20eaux&output=série"
curl "https://API/v1/cards?operator=delta&search=VCN"
curl "https://API/v1/cards/VCN10?lang=fr"      # détail d'une fiche
```

## Cas d'usage

Le même fil en Python puis en R : extraire des indicateurs annuels,
en tracer un, puis diagnostiquer sa tendance et superposer points et
droite de Sen. Les indicateurs annuels se tracent en points (une
valeur par an), pas en ligne continue.

Deux paramètres méritent un mot :

- `sampling=preferred` fige la fenêtre annuelle de calcul sur celle
  que chaque fiche déclare (par exemple l'année hydrologique 09-01
  pour les crues). Par défaut, les fiches d'étiage et de crue adaptent
  leur fenêtre à chaque station ; `preferred` rend les résultats
  directement comparables entre stations et reproductibles.
- `series=true` sur `/v1/trend` joint à la réponse, sous `series`,
  les séries extraites sur lesquelles la tendance a été calculée :
  points et diagnostic issus du même calcul, sans second appel.

### En Python

Extraction : module (QA) et étiage (VCN10) de la Seine à Paris.

```python
import requests, pandas as pd

r = requests.get("https://API/v1/extract", params={
    "stations": "F700000103",
    "cards": "QA,VCN10",
    "start": "1990-01-01",
    "orient": "columns",              # directement ingérable par pandas
}).json()
```

Figure, avec l'unité lue dans les métadonnées :

```python
import matplotlib.pyplot as plt

vcn10 = pd.DataFrame(r["data"]["VCN10"])
meta = pd.DataFrame(r["meta"])
unit = meta.loc[meta.variable_en == "VCN10", "unit_fr"].iloc[0]
vcn10.plot(x="date", y="VCN10", style="o", ylabel=f"VCN10 [{unit}]")
plt.show()
```

Tendance du VCN10 : une ligne par station (H : tendance
significative ? p-value, pente de Sen absolue `a` et relative).

```python
r = requests.get("https://API/v1/trend", params={
    "stations": "F700000103",
    "cards": "VCN10",
    "sampling": "preferred",
    "series": "true",
}).json()

tr = pd.DataFrame(r["data"]["VCN10"]).iloc[0]
```

Points et droite de Sen sur la même figure :

```python
s = pd.DataFrame(r["series"]["VCN10"])
dates = pd.to_datetime(s["date"])
years = (dates - pd.Timestamp("1970-01-01")).dt.days / 365.25
plt.plot(dates, s["VCN10"], "o")
plt.plot(dates, tr["a"] * years + tr["b"], "--")
plt.show()
```

### En R

Extraction : module (QA) et étiage (VCN10) de la Seine à Paris
(format `records` par défaut : `fromJSON` en fait des data.frame).

```r
library(jsonlite)

r <- fromJSON(paste0("https://API/v1/extract?stations=F700000103",
                     "&cards=QA,VCN10&start=1990-01-01"))
```

Figure, avec l'unité lue dans les métadonnées :

```r
vcn10 <- r$data$VCN10
unit <- r$meta$unit_fr[r$meta$variable_en == "VCN10"]
plot(as.Date(vcn10$date), vcn10$VCN10,
     ylab = paste0("VCN10 [", unit, "]"))
```

Tendance du VCN10 : une ligne par station (H : tendance
significative ? p-value, pente de Sen absolue `a` et relative).

```r
r <- fromJSON(paste0("https://API/v1/trend?stations=F700000103",
                     "&cards=VCN10&sampling=preferred&series=true"))
tr <- r$data$VCN10[1, ]
```

Points et droite de Sen sur la même figure :

```r
s <- r$series$VCN10
dates <- as.Date(s$date)
years <- as.numeric(dates) / 365.25
plot(dates, s$VCN10)
lines(dates, tr$a * years + tr$b, lty = 2)
```

### Grosses demandes : les jobs

Au-dessus de 10 stations ou 20 fiches, la demande devient un job,
sans inscription : la réponse `202` donne un ticket, le calcul se
fait en file, le résultat reste téléchargeable plusieurs jours avec
un bloc de provenance (paramètres, versions, date des données) qui le
rend citable et reproductible.

```python
job = requests.post("https://API/v1/jobs", json={
    "endpoint": "trend",
    "stations": liste_de_codes,       # jusqu'à 100
    "cards": ["QA", "VCN10"],
    "sampling": "preferred",
}).json()
# suivre job["status_url"] (queued -> running -> done, avec progression)
# puis récupérer job["result_url"]
```

Les appels `GET /v1/extract` et `/v1/trend` trop gros basculent
automatiquement sur ce circuit (réponse `202` au lieu d'un refus).

## Quotas et clés de priorité

Le service est public avec un quota par IP et par minute ; en cas de
dépassement (`429`), l'en-tête `Retry-After` indique quand réessayer.
Les chroniques sont mises en cache 24 h côté serveur : répéter une
requête ne re-télécharge rien depuis Hub'Eau.

Pour un besoin massif ou récurrent (centaines de stations, chaînes de
traitement), demandez une clé de priorité gratuite en
[ouvrant une issue](../../issues/new?template=cle-de-priorite.yml).
Elle se passe en en-tête `X-API-Key` (de préférence à `key=`, qui
laisse la clé dans les logs web) : quotas par minute levés, plafonds
relevés (jusqu'à 1000 stations par job), jobs en tête de file, et
`GET /v1/jobs` liste vos jobs déposés avec la clé (tickets compris :
pratique pour retrouver un résultat dont le ticket est égaré).

Le jeton n'est communiqué qu'une fois, à la création (le serveur n'en
garde qu'un hachage) : conservez-le, un jeton perdu se remplace. Le
journal du service ne stocke jamais votre nom, seulement le préfixe
du jeton.

## Périmètre

Le service ne fournit que des débits journaliers (fiches à entrée
`Q`) ; le diagnostic de tendance ne s'applique qu'aux fiches de forme
`series` (la tendance d'un scalaire ou d'une courbe n'a pas de sens).

## Citer

Les métadonnées de citation sont dans [CITATION.cff](CITATION.cff)
(bouton « Cite this repository » de GitHub) et
[codemeta.json](codemeta.json) (moissonné par Software Heritage et
HAL ; identifiant pérenne à venir par ce canal). Dans une
publication, citez aussi la source des données (Hub'Eau hydrométrie,
eaufrance, Licence Ouverte) et la version de card utilisée : chaque
réponse du service la porte (`card_version`), les résultats de jobs y
ajoutent un bloc de provenance complet (paramètres, date des
données).

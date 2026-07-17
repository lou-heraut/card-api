# card-api

Service web des fiches [card](https://github.com/lou-heraut/card) :
extraction de variables hydroclimatiques sur les débits de la Banque
Hydro (via [Hub'Eau](https://hubeau.eaufrance.fr/)) et diagnostic de
stationnarité Mann-Kendall / pente de Sen (via
[stase](https://github.com/lou-heraut/stase)).

Service public de recherche (INRAE, UR RiverLy). Ouvert, sans
inscription (quota par IP) ; code GPL-3, données Hub'Eau en Licence
Ouverte. Déploiement et développement : [INSTALL.md](INSTALL.md).

## Les endpoints

| Endpoint | Rôle |
|---|---|
| `GET /v1/cards` | catalogue des 226 fiches, filtrable par facettes |
| `GET /v1/cards/{id}` | détail d'une fiche (fr/en) + lien vers son YAML |
| `GET /v1/stations` | recherche de stations hydrométriques |
| `GET /v1/extract` | chroniques Hub'Eau → variables CARD |
| `GET /v1/trend` | extraction + test de Mann-Kendall et pente de Sen |
| `POST /v1/jobs` | grosses demandes en file de calcul (202 + ticket) |
| `GET /v1/jobs/{id}` | statut et progression ; `/result` : résultat gelé |
| `GET /v1/health` | santé du service (file de calcul, disque) |
| `/docs` | documentation interactive (OpenAPI) |

## Exemples

### Trouver sa station (les codes ont changé depuis la refonte Hydro !)

```bash
curl "https://API/v1/stations?libelle=Austerlitz"
# → F700000103 | La Seine à Paris - Austerlitz [>2006]
```

### Trouver ses fiches par facette de classification

```bash
curl "https://API/v1/cards?phenomenon=basses%20eaux&output=série"
curl "https://API/v1/cards?operator=delta&search=VCN"
curl "https://API/v1/cards/VCN10?lang=fr"
```

### Extraire en Python

```python
import requests, pandas as pd
import matplotlib.pyplot as plt

r = requests.get("https://API/v1/extract", params={
    "stations": "F700000103",
    "cards": "QA,VCN10",
    "start": "1990-01-01",
    "orient": "columns",          # directement ingérable par pandas
}).json()

vcn10 = pd.DataFrame(r["data"]["VCN10"])
meta = pd.DataFrame(r["meta"])    # unités, noms fr/en, classification
unit = meta.loc[meta.variable_en == "VCN10", "unit_fr"].iloc[0]
vcn10.plot(x="date", y="VCN10", style="o",  # points : une valeur par an,
           ylabel=f"VCN10 [{unit}]")           # pas un signal continu
plt.show()
```

### Extraire en R

```r
library(jsonlite)
r <- fromJSON(paste0("https://API/v1/extract?",
                     "stations=F700000103&cards=QA&orient=columns"))
qa <- as.data.frame(r$data$QA)
plot(as.Date(qa$date), qa$QA,   # des points : une valeur par an
     ylab = r$meta$unit_fr[r$meta$variable_en == "QA"])
```

### Tendance (à la MAKAHO)

```python
r = requests.get("https://API/v1/trend", params={
    "stations": "F700000103,K0550010",
    "cards": "VCN10",
    "sampling": "preferred",      # fenêtre fixe de chaque fiche
                                  # (protocole MAKAHO) ; défaut : fenêtre
                                  # de la fiche, adaptative par station
                                  # pour les fiches d'étiage/crue ;
                                  # ou "MM-JJ" pour l'imposer (ex. 09-01)
    "mk": "AR1",                  # défaut ; ou INDE, LTP
    "level": 0.1,
    "series": "true",             # joint les séries extraites sous
                                  # 'series' : points et tendance issus
                                  # du même calcul, aucun doute possible
}).json()
pd.DataFrame(r["data"]["VCN10"])
# → une ligne par station : H (tendance significative ?), p-value,
#   pente de Sen (absolue et relative), période analysée
```

Figure points + tendance (une station) :

```python
tr = pd.DataFrame(r["data"]["VCN10"]).set_index("id").loc["F700000103"]
s = pd.DataFrame(r["series"]["VCN10"]).query("id == 'F700000103'")
dates = pd.to_datetime(s["date"])
plt.plot(dates, s["VCN10"], "o")            # points : une valeur par an
years = (dates - pd.Timestamp("1970-01-01")).dt.days / 365.25
plt.plot(dates, tr["a"] * years + tr["b"], "--")     # droite de Sen
plt.show()
```

### Grosses demandes : le motif job

Au-dessus de 10 stations ou 20 fiches, la demande devient un job (sans
inscription, comme tout le reste) : la réponse `202` donne un ticket,
le calcul se fait en file, le résultat reste téléchargeable plusieurs
jours avec un bloc de provenance (paramètres, versions, date des
données) qui le rend citable et reproductible.

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

Deux formats de réponse : `orient=records` (défaut, liste d'objets,
comme Hub'Eau) ou `orient=columns` (colonnaire : `{colonne:
[valeurs]}`, plus compact, une ligne pour recharger en DataFrame).
Chaque réponse embarque `meta` (unités, noms bilingues,
classification), la source des données et les versions : elle se
suffit à elle-même.

## Bon voisinage

- Quota public par IP ; en cas de `429`, l'en-tête `Retry-After`
  indique quand réessayer. Besoin massif (centaines de stations,
  usage récurrent) : demandez une clé de priorité gratuite en
  [ouvrant une issue](../../issues/new?template=cle-de-priorite.yml),
  puis passez-la en en-tête `X-API-Key` (ou paramètre `key=`) : quotas
  levés, plafonds relevés, jobs en tête de file.
- Les chroniques sont mises en cache 24 h côté serveur : répéter une
  requête ne re-télécharge pas Hub'Eau.
- Fiches à entrée `Q` uniquement (le service ne fournit que des
  débits) ; la tendance ne s'applique qu'aux fiches de forme `series`.

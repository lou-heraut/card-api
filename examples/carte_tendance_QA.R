# Carte des tendances du module (QA) sur le réseau de référence RRSE
# (228 stations) : dépôt d'un job /v1/jobs, suivi, puis carte des
# pentes de Sen relatives avec la palette déclarée par la fiche QA
# (10 couleurs divergentes brun -> vert, classes centrées sur zéro,
# classes extrêmes ouvertes vers +/- l'infini).
#
# Préparation :
#   - une clé de priorité est NÉCESSAIRE ici : 228 stations dépassent
#     le plafond public des jobs (100). L'administrateur la crée sur
#     la VM :  make key name="Prénom Nom, labo"
#     puis :   export CARD_API_KEY=<jeton>
#   - adresse du service :  export CARD_API_URL=http://...
#
# Usage, depuis la racine du repo (pour tests/data/makaho/QA/meta.csv) :
#   Rscript examples/carte_tendance_QA.R

library(jsonlite)
library(httr)

API <- Sys.getenv("CARD_API_URL", "http://147.100.222.13")
KEY <- Sys.getenv("CARD_API_KEY", "")
if (KEY == "") stop("définir CARD_API_KEY (cf. en-tête du script)")

# ── Les stations : réseau RRSE du jeu de validation MAKAHO ──────────────────
meta <- read.csv("tests/data/makaho/QA/meta.csv")
cat(nrow(meta), "stations RRSE\n")

# ── Dépôt du job : tendance de QA, fenêtre fixe des fiches ──────────────────
r <- POST(paste0(API, "/v1/jobs"),
          add_headers(`X-API-Key` = KEY),
          body = list(endpoint = "trend",
                      stations = meta$code,
                      cards = "QA",
                      sampling = "preferred"),  # fenêtre fixe déclarée (09-01)
          encode = "json")                      # -> comparable entre stations
stopifnot(status_code(r) == 202)
ticket <- content(r)
cat("job", ticket$job, "déposé\n")

# ── Suivi jusqu'au résultat ──────────────────────────────────────────────────
repeat {
  st <- fromJSON(paste0(API, ticket$status_url, "?key=", KEY))
  cat(sprintf("\r%s : %d/%d (%s)      ", st$status,
              st$progress$done, st$progress$total, st$progress$phase))
  if (st$status %in% c("done", "failed")) break
  Sys.sleep(2)
}
cat("\n")
stopifnot(st$status == "done")

res <- fromJSON(paste0(API, ticket$result_url, "?key=", KEY))
tr <- res$data$QA                     # une ligne par station : H, p, a...

# ── Palette de la fiche QA (voyage dans le meta de la réponse) ───────────────
pal <- strsplit(res$meta$palette[res$meta$variable_en == "QA"], " ")[[1]]

# ── Classes : centrées sur 0, ouvertes aux extrêmes ─────────────────────────
# a_relative est déjà en % de la moyenne par an ; a_relative_min/max =
# quantiles 1 % / 99 % des pentes relatives entre stations
# (extremes_prob = 0.01 de stase.trend) : borne symétrique robuste
# aux stations aberrantes.
rel <- tr$a_relative                                    # % / an
b <- max(abs(c(tr$a_relative_min, tr$a_relative_max)))
edges <- seq(-b, b, length.out = length(pal) - 1)
classe <- cut(rel, breaks = c(-Inf, edges, Inf))

# ── Carte : points pleins si tendance significative (H), vides sinon ─────────
xy <- meta[match(tr$id, meta$code), c("lon_deg", "lat_deg")]
png("carte_tendance_QA.png", width = 800, height = 800)
plot(xy$lon_deg, xy$lat_deg, asp = 1.4, pch = 21, cex = 1.4,
     bg = ifelse(tr$H, pal[classe], "white"), col = pal[classe], lwd = 2,
     xlab = "Longitude", ylab = "Latitude",
     main = "Tendance du module QA, pente de Sen relative (% / an)")
labs <- c(sprintf("< %.2f", edges[1]),
          sprintf("%.2f à %.2f", head(edges, -1), tail(edges, -1)),
          sprintf("> %.2f", edges[length(edges)]))
legend("bottomleft", legend = rev(labs), fill = rev(pal), bty = "n",
       title = "% / an", cex = 0.8)
legend("topright", legend = c("significative (H)", "non significative"),
       pt.bg = c("grey40", "white"), col = "grey40", pch = 21, bty = "n")
invisible(dev.off())
cat("carte écrite : carte_tendance_QA.png\n")

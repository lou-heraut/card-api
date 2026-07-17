# Carte des tendances du module (QA) sur le réseau de référence RRSE
# (228 stations) : dépôt d'un job /v1/jobs, suivi, puis carte des
# pentes de Sen relatives avec la palette déclarée par la fiche QA
# (10 couleurs divergentes brun -> vert, classes centrées sur zéro,
# classes extrêmes ouvertes vers +/- l'infini).
#
# Paramètres : le bloc ci-dessous (pensé pour un lancement depuis un
# IDE, depuis la racine du repo ; Rscript examples/... marche aussi).
#
#   - le jeton de clé de priorité va dans examples/cle_locale.txt
#     (une seule ligne, fichier gitignoré) : JAMAIS de secret dans un
#     fichier suivi par git. La clé est nécessaire au dépôt : 228
#     stations dépassent le plafond public des jobs (100).
#     L'administrateur la crée sur la VM : make key name="Prénom Nom, labo"
#   - reprise : le calcul tourne côté serveur et le résultat reste
#     disponible plusieurs jours. Pour récupérer plus tard un job déjà
#     déposé (ordinateur éteint entre-temps...), renseigner JOB avec
#     le ticket affiché au dépôt : le script saute le dépôt et va
#     directement au résultat. Pas besoin de clé pour ça.

library(jsonlite)
library(httr)

API <- "http://147.100.222.13"
JOB <- ""     # ticket d'un job déjà déposé, ex. "a1b2c3d4" ; "" = déposer
KEY <- if (file.exists("examples/cle_locale.txt"))
  trimws(readLines("examples/cle_locale.txt", n = 1)) else ""

# ── Les stations : réseau RRSE du jeu de validation MAKAHO ──────────────────
meta <- read.csv("tests/data/makaho/QA/meta.csv")

# ── Dépôt du job : tendance de QA, fenêtre fixe des fiches ──────────────────
if (JOB == "") {
  if (KEY == "") stop("jeton manquant : examples/cle_locale.txt (cf. en-tête)")
  cat(nrow(meta), "stations RRSE\n")
  r <- POST(paste0(API, "/v1/jobs"),
            add_headers(`X-API-Key` = KEY),
            body = list(endpoint = "trend",
                        stations = meta$code,
                        cards = "QA",
                        sampling = "preferred"), # fenêtre fixe déclarée (09-01)
            encode = "json")                     # -> comparable entre stations
  stopifnot(status_code(r) == 202)
  JOB <- content(r)$job
  cat("job", JOB, "déposé : noter ce ticket pour reprendre plus tard\n")
}

# ── Suivi jusqu'au résultat ──────────────────────────────────────────────────
job_url <- paste0(API, "/v1/jobs/", JOB)
repeat {
  st <- fromJSON(job_url)
  cat(sprintf("\r%s : %d/%d (%s)      ", st$status,
              st$progress$done, st$progress$total, st$progress$phase))
  if (st$status %in% c("done", "failed")) break
  Sys.sleep(2)
}
cat("\n")
stopifnot(st$status == "done")

res <- fromJSON(paste0(job_url, "/result"))
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

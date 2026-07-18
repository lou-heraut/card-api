# Carte des tendances du module (QA) sur le réseau de référence RRSE
# (228 stations) : dépôt d'un job /v1/jobs, suivi, puis carte ggplot2
# des pentes de Sen relatives avec la palette déclarée par la fiche QA
# (10 couleurs divergentes brun -> vert, classes centrées sur zéro,
# classes extrêmes ouvertes vers +/- l'infini). Symbologie MAKAHO :
# triangle haut/bas = tendance significative à la hausse/baisse,
# rond = non significative ; couleur = classe de pente dans tous les
# cas. START/END par défaut = fenêtre des exports MAKAHO du jeu de
# validation (même agrégation, même test : les cartes deviennent
# comparables, aux révisions de données près, cf. tests/test_makaho.py).
#
# Paramètres : le bloc ci-dessous (pensé pour un lancement depuis un
# IDE, depuis la racine du repo ; Rscript examples/... marche aussi).
#
#   - le jeton de clé de priorité va dans examples/.env (fichier
#     gitignoré, modèle : examples/.env.example) sous la forme
#     CARD_API_KEY=... : JAMAIS de secret dans un fichier suivi par
#     git. La clé est nécessaire au dépôt : 228 stations dépassent le
#     plafond public des jobs (100). L'administrateur la crée sur la
#     VM : make key name="Prénom Nom, labo"
#   - reprise : le calcul tourne côté serveur et le résultat reste
#     disponible plusieurs jours. Pour récupérer plus tard un job déjà
#     déposé (ordinateur éteint entre-temps...), renseigner JOB avec
#     le ticket affiché au dépôt : le script saute le dépôt et va
#     directement au résultat. Pas besoin de clé pour ça.

library(jsonlite)
library(httr)
library(tibble)
library(ggplot2)

API <- "http://147.100.222.13"
JOB <- ""     # ticket d'un job déjà déposé ; "" = déposer
START <- "1968-09-01"   # fenêtre MAKAHO RRSE ; "" = toute la chronique
END   <- "2024-08-31"
if (file.exists("examples/.env")) readRenviron("examples/.env")
KEY <- Sys.getenv("CARD_API_KEY")

# ── Les stations : réseau RRSE du jeu de validation MAKAHO ──────────────────
# Seuls les codes sont lus : l'appartenance au RRSE est un choix
# d'étude (aucun flag dans Hub'Eau), mais tout le reste (positions...)
# vient du référentiel Hub'Eau via l'API, jamais d'un fichier local.
codes <- read.csv("tests/data/makaho/QA/meta.csv")$code

# ── Dépôt du job : tendance de QA, fenêtre fixe des fiches ──────────────────
if (JOB == "") {
  if (KEY == "") stop("jeton manquant : CARD_API_KEY dans examples/.env (cf. en-tête)")
  cat(length(codes), "stations RRSE\n")
  corps <- list(endpoint = "trend",
                stations = codes,
                cards = "QA",
                sampling = "preferred")  # fenêtre fixe déclarée (09-01),
  if (nzchar(START)) corps$start <- START  # -> comparable entre stations
  if (nzchar(END)) corps$end <- END
  r <- POST(paste0(API, "/v1/jobs"),
            add_headers(`X-API-Key` = KEY),
            body = corps, encode = "json")
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

# ── Positions : référentiel Hub'Eau via /v1/stations, 100 codes par appel ────
pos <- do.call(rbind, lapply(
  split(tr$id, (seq_along(tr$id) - 1) %/% 100),
  function(chunk) fromJSON(content(GET(
    paste0(API, "/v1/stations"),
    query = list(code = paste(chunk, collapse = ","), size = 100)),
    "text", encoding = "UTF-8"))$stations))
xy <- pos[match(tr$id, pos$code_station), ]
stopifnot(!anyNA(xy$longitude_station))

# ── Classes : centrées sur 0, ouvertes aux extrêmes ─────────────────────────
# a_relative est déjà en % de la moyenne par an ; a_relative_min/max =
# quantiles 1 % / 99 % des pentes relatives entre stations
# (extremes_prob = 0.01 de stase.trend) : borne symétrique robuste
# aux stations aberrantes.
rel <- tr$a_relative                                    # % / an
b <- max(abs(c(tr$a_relative_min, tr$a_relative_max)))
edges <- seq(-b, b, length.out = length(pal) - 1)
labs <- c(sprintf("< %.2f", edges[1]),
          sprintf("%.2f à %.2f", head(edges, -1), tail(edges, -1)),
          sprintf("> %.2f", edges[length(edges)]))

# ── Tableau de tracé : une ligne par station ────────────────────────────────
carte <- tibble(
  lon = xy$longitude_station,
  lat = xy$latitude_station,
  classe = cut(rel, breaks = c(-Inf, edges, Inf), labels = labs),
  sens = factor(ifelse(!tr$H, "ns",
                       ifelse(tr$a > 0, "hausse", "baisse")),
                levels = c("hausse", "ns", "baisse")),
)

# ── Carte : triangle haut/bas = signif hausse/baisse, rond = non signif ──────
prm <- res$job$params
periode <- if (is.null(prm$start)) "toute la chronique" else
  paste(prm$start, "à", prm$end)
p <- ggplot(carte, aes(lon, lat, shape = sens, fill = classe)) +
  geom_point(size = 2.6, colour = "grey25", stroke = 0.3) +
  scale_shape_manual(
    values = c(hausse = 24, ns = 21, baisse = 25),
    labels = c(hausse = "hausse significative (H)",
               ns = "non significative",
               baisse = "baisse significative (H)"),
    name = NULL) +
  scale_fill_manual(values = setNames(pal, labs), name = "% / an",
                    drop = FALSE) +
  guides(fill = guide_legend(override.aes = list(shape = 21),
                             reverse = TRUE, order = 2),
         shape = guide_legend(override.aes = list(fill = "grey65"),
                              order = 1)) +
  coord_quickmap() +
  labs(title = "Tendance du module QA, pente de Sen relative (% / an)",
       subtitle = paste0("RRSE, ", periode,
                         ", Mann-Kendall Hamed-Rao AR1, niveau 0.1"),
       x = "Longitude", y = "Latitude") +
  theme_minimal()
ggsave("carte_tendance_QA.png", p, width = 7.5, height = 8, dpi = 300,
       bg = "white")
cat("carte écrite : carte_tendance_QA.png\n")

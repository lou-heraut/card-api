# CLAUDE.md (card-api)

Service web FastAPI des fiches [card](../card/) sur les débits Hub'Eau,
avec diagnostic de stationnarité via [stase](../../EXstat_project/stase/).
Où lire quoi. Un rôle par fichier, chacun l'annonce dans un bandeau de
statut en tête ; ne jamais recopier d'un fichier à l'autre, renvoyer.
- `README.md` : ce que le service fait, endpoints et parcours d'usage.
- `CHANGELOG.md` : ce qui a changé, quand, et où lire le détail.
- `INSTALL.md` : développement et déploiement.
- `docs/dev/API.md` : conception et arbitrages (accès public sans clé,
  quotas IP, journal anonymisé, aspect commercial écarté).
- `docs/dev/CHANTIERS.md` : pistes ouvertes du service, seulement.
- Ménage documentaire : la procédure est commune aux trois dépôts et vit
  dans `../card/docs/dev/NETTOYAGE.md`, avec l'état de la campagne en
  cours. Rien à en recopier ici.

## Structure

```
src/card_api/
  pipeline.py   # LA chaîne de calcul, écrite UNE fois, et l'identité
                #   qu'elle publie (versions/rights/SOURCE/LTP_SEED/
                #   START_DEFAUT). Ne connaît RIEN de HTTP : lève des
                #   exceptions neutres que main traduit (_traduit) et que
                #   jobs enregistre. C'est ce qui permet aux DEUX portes
                #   d'appeler le même code. Existe à cause d'un bug : la
                #   chaîne était écrite deux fois, main pour le synchrone
                #   et jobs pour la file, et une correction d'un côté
                #   n'atteignait pas l'autre (2026-07-29, stations muettes
                #   fatales en job seulement). `normalise` applique
                #   défauts et validations AVANT la bifurcation sync/job :
                #   sans quoi un POST /v1/jobs sans `start` calculait sur
                #   une autre fenêtre qu'un GET /v1/extract, en silence.
                #   `compute` prend `progress` en PARAMÈTRE : c'est la
                #   seule chose que la file avait de plus, et la seule
                #   raison qu'avait la copie d'exister.
                #   NE JAMAIS refaire de boucle chroniques ailleurs.
  main.py       # endpoints : racine / (panneau indicateur, forme des
                #   « landing pages » OGC API : liens typés service-desc,
                #   service-doc, latest-version ; le détail reste dans
                #   /v1, pas maintenu à deux endroits), puis /v1
                #   (écosystème, réutilisation,
                #   droits), cards (champ `ids` = la sélection prête à
                #   COLLER dans le paramètre cards ; colonne `id` = le nom
                #   du FICHIER, pas variable_en, les deux diffèrent pour
                #   343 fiches sur 472), cards/{id}, cards/{id}/figure (la
                #   fiche DESSINÉE en text/plain ; le détail reste du
                #   JSON), vocabulary (valeurs de facette valides =
                #   filtres de cards), stations (champ `codes`, même
                #   service que `ids`), extract + extract.csv,
                #   trend + trend.csv + trend/figure (le MÊME
                #   diagnostic ; paramètres déclarés UNE fois dans
                #   TrendParams/ExtractParams, partagés ; une
                #   représentation = une URL, jamais un paramètre
                #   `format` : cf. docs/dev/API.md ; les .csv portent
                #   leur provenance en lignes `#`, sinon un tableur ne
                #   sait plus d'où viennent ses chiffres ; mk défaut AR1,
                #   sampling=preferred|MM-JJ,
                #   series=true joint les séries extraites au diagnostic ;
                #   stations_meta=true joint le référentiel Hub'Eau des
                #   stations : résultat autoportant), jobs (POST + statut
                #   + result + DELETE dismiss par ticket ; GET /v1/jobs =
                #   « mes jobs » par clé, 401 sinon), health (file,
                #   disque VM entière vs empreinte data du service).
                #   CORS ouvert en lecture (usage navigateur) ; bloc rights
                #   dans les résultats (données Etalab, définitions GPL) ;
                #   /docs = Swagger UI habillé, try-it-out actif et
                #   exemples pré-remplis ; le thème sombre est un calque
                #   GÉNÉRÉ depuis le CSS réel de Swagger, jamais écrit à
                #   la main, et se juge à la CAPTURE D'ÉCRAN, pas à
                #   l'injection : docs/dev/THEME_DOCS.md
  static/       # deux feuilles servies dans cet ordre, plus le logo :
                #   swagger-colors.css   GÉNÉRÉ (scripts/build_theme.py),
                #     à refaire seulement quand Swagger monte de version
                #   theme-identity.css   ÉCRIT À LA MAIN : c'est CE
                #     fichier qu'on retouche, puis on recharge la page,
                #     rien à reconstruire (cf. docs/dev/THEME_DOCS.md)
                #   inrae.svg            logo, posé en image de fond par
                #     le calque : pas de balise injectée dans Swagger
  jobs.py       # file de calcul asynchrone (forme OGC API Processes) :
                #   202+Location, progression, résultat gelé avec bloc
                #   de provenance, TTL ; plafonds SYNC_*/JOB_* du .env ;
                #   bascule auto des demandes > plafonds synchrones.
                #   DEUX seuils de stations : SYNC_STATIONS compte les
                #   stations À TÉLÉCHARGER (bas), SYNC_STATIONS_CACHED le
                #   total (haut). Mesuré : ~1,2 s de téléchargement contre
                #   ~0,04 s de calcul par station, soit 24 s à froid et 1 s
                #   à chaud pour les mêmes 20 stations. Compter les
                #   stations sans regarder le cache tranchait au mauvais
                #   endroit. La même URL peut donc partir en file au 1er
                #   appel et répondre en direct au 2e : c'est VOULU.
                #   Une station sans série est ÉCARTÉE, pas fatale :
                #   `stations` = ce qui est CALCULÉ (pas la demande, sinon
                #   une jointure porte à faux), `stations_requested` = la
                #   demande, `stations_omitted` = les écartées avec
                #   `reason` (no_series / no_data_in_period /
                #   ambiguous_site), bloc TOUJOURS présent même vide.
                #   Ligne de partage : la REPRODUCTIBILITÉ, pas la
                #   gravité. Un fait de la station se rapporte, une panne
                #   Hub'Eau reste un 504. Tout omettre = 404, un résultat
                #   vide se lisant comme un résultat. Cf. docs/dev/API.md
  hubeau.py     # colonne de station = `code_station`, le nom de Hub'Eau :
                #   une colonne relayée garde le nom de sa source, pour
                #   que la jointure au référentiel se fasse sans
                #   traduction (règle dans docs/dev/API.md ; tout ce que
                #   le service CALCULE est en anglais snake_case).
                #   L'empreinte hache aussi le NOM des colonnes :
                #   renommer une colonne la change. Préfixe laissé à v1
                #   au renommage du 2026-07-28, aucune empreinte n'ayant
                #   encore été publiée.
                #   client Hub'Eau v2 (obs_elab QmnJ, L/s -> m3/s,
                #   pagination next, codes post-refonte) + cache 24 h
  usage.py      # quotas IP (fenêtre glissante, 429+Retry-After) ;
                #   plafonds LARGES à dessein : ce compteur compte des
                #   requêtes, pas leur coût, et la charge est tenue par
                #   le sémaphore de calcul et la bascule en job. Un refus
                #   est journalisé (log_refusal) comme ÉVÉNEMENT, jamais
                #   comme usage : sinon le plafond est invisible et se
                #   règle à l'aveugle. Écrit HORS du verrou, `_lock`
                #   n'étant pas réentrant.
                #   priority_of (X-API-Key/key=, 401 si inconnue),
                #   journal usage-AAAA.jsonl (rotation annuelle ; IP
                #   hachée salée, préfixe de clé, log_event)
  keys.py       # clés de priorité : jeton affiché UNE fois, keys.json
                #   ne garde que {préfixe: hash SHA-256 + nom} ; le
                #   préfixe est l'identifiant public (journal, job,
                #   listing), le nom ne sort jamais de keys.json ; CLI
                #   add/list/revoke (make key/keys/key-revoke) ; effet =
                #   quotas levés, PRIORITY_*, tête de file, GET /v1/jobs
  serialize.py  # DataFrame -> JSON (records|columns), partagé sync/jobs
  stats.py      # tableau de bord terminal (make stats / make watch) :
                #   DEUX familles jamais additionnées, calcul et
                #   découverte, VENTILÉES l'une comme l'autre ; un
                #   ÉVÉNEMENT n'est ni l'un ni l'autre (job_done porte un
                #   `endpoint` : le compter faisait deux appels pour un
                #   job). TOUTES les lignes sont toujours là, zéro
                #   compris (listes FIXES ENDPOINTS_*/RENDUS) : une ligne
                #   qui n'apparaît qu'au-dessus de zéro fait changer le
                #   tableau de forme et confond « personne n'a appelé »
                #   avec « je ne sais pas ». Ligne REFUS en IP
                #   DISTINCTES : une personne bloquée 30 fois est un
                #   script, 30 personnes bloquées une fois est un plafond
                #   trop bas. Gouttière commune (GOUTTIERE) : c'est
                #   l'alignement qui rend deux courbes comparables.
                #   `_paquets` mesure avant d'écrire, `_box` marque d'un
                #   … ce qu'il coupe (« ✗ 5 échecs » se lisait « ✗ 5 éc »)
                #   sparklines, heatmap 12 semaines, file, disque
tests/          # hors-ligne (Hub'Eau simulé ; jobs ; clés ; retry ;
                #   validation MAKAHO, précision machine) + live.
                #   test_jobs.py::test_les_deux_portes_rendent_le_meme_
                #   contrat compare les ENVELOPPES sync et job, pas
                #   seulement `data` : c'est le garde-fou contre le retour
                #   de la duplication. PROPRES_AU_JOB y liste les seuls
                #   champs autorisés à différer. Un test qui protège
                #   l'ancien comportement et reste vert après un
                #   changement de comportement est un SIGNAL D'ARRÊT :
                #   c'est ce qui a masqué le bug du 2026-07-29.
scripts/        # veille_sante.py : sonde cron à lancer HORS VM
                #   (ntfy.sh optionnel ; une veille sur la VM meurt
                #   avec elle)
docs/dev/       # API.md : conception et arbitrages du service ;
                #   CHANTIERS.md : chantiers
                #   ouverts propres au service
.github/        # workflows CI (pytest + ruff). Le gabarit d'issue
                #   « clé de priorité » a été RETIRÉ : une issue de
                #   dépôt public est publique, le jeton ne peut pas
                #   en revenir. Les clés se demandent par courriel.
CITATION.cff    # citabilité ; codemeta.json = canal Software
                #   Heritage / HAL (pas de Zenodo, choix utilisateur)
Makefile        # ops : make env/up/apache/update/logs/status/stats/watch
                #   + make test / make lint (ruff du venv, JAMAIS celui
                #   du PATH : version épinglée et règles déclarées dans
                #   pyproject.toml, sinon le verdict change avec la
                #   version installée)
compose.yaml    # api sur 127.0.0.1:8000 ; frontal = Apache de la VM
                #   (make apache, vhost généré depuis DOMAIN) ou profil
                #   caddy (COMPOSE_PROFILES=caddy, VM nue) ; .env
```

Dev : `pip install -e ../../EXstat_project/stase -e ../card -e .[dev]`
dans `.python_env/` (cf. INSTALL.md), puis `uvicorn card_api.main:app
--reload`, `pytest` et `make lint`.

> ## À NE JAMAIS FAIRE
>
> - **`note.txt` (et tout fichier de notes de l'utilisateur) : NE PAS
>   L'OUVRIR.** Ni Read, ni `cat`, ni `grep`, ni au détour d'un `git add`.
>   C'est son brouillon personnel : pas de lecture, pas de résumé, pas de
>   « au passage j'ai vu que ». Il n'entre dans aucune tâche sans une
>   demande explicite de sa part, fichier par fichier. Un en-tête qui dit
>   de ne pas lire est un ordre, pas une mise en garde à évaluer.
> - **Pas de `git add -A` ni de `git add .`** : stager nommément les
>   fichiers que l'on a soi-même modifiés. Ce qui traîne dans l'arbre de
>   travail appartient à l'utilisateur.
> - **Ne JAMAIS signaler un fichier non suivi.** Un fichier non suivi est
>   à l'utilisateur : brouillon, essai, sortie jetable. Il a le droit d'en
>   avoir, il n'a pas à s'en justifier, et le lui rappeler est une
>   nuisance. Pas de « au passage, j'ai vu que », pas de « je n'y touche
>   pas », pas de récapitulatif en fin de réponse. On n'en parle que s'il
>   en parle le premier. Le répertoire `bac/` est ignoré par git : c'est
>   là qu'on lui propose de déposer ce qu'il veut faire disparaître du
>   `git status`, une fois, sans y revenir.

## Règles propres au service

- Fiches à entrée `Q` uniquement (refus explicite sinon : l'auto-mapping
  de colonnes de card masquerait l'erreur) ; tendance sur les fiches
  `output: series` uniquement (validation par la classification).
- Public par défaut, jamais d'inscription ; le journal ne stocke JAMAIS
  d'IP en clair. Aspect commercial écarté (stats d'usage = preuve
  d'impact pour les financements).
- **La production suit `main`** (`CARD_REF`/`STASE_REF` dans .env) :
  une fiche corrigée part en ligne au `make update` suivant, sans geste
  intermédiaire. Ce qui rend le résultat traçable n'est pas une ref
  figée mais le **commit** résolu à la construction
  (`scripts/resolve_refs.py`), publié par `versions()` dans chaque
  réponse. Ne jamais recopier un numéro de version à la main dans une
  réponse : passer par `versions()`, sinon un point de sortie finira par
  mentir. Cf. « Versions et citation » plus bas.
- **Jamais de fenêtre de choix à cocher** (outil de question à options) :
  elle coupe la conversation. Une décision à prendre s'expose en prose
  dans la réponse, avec une recommandation, et se discute dans le fil.
- Pas de tiret quadratin (—) dans la prose (docs, messages, commentaires,
  réponses) : reformuler. Perçu comme un marqueur de texte IA.
- **Aucun décompte ni plafond écrit en clair dans une description
  d'API.** « 226 fiches », « défaut 10 stations, 20 fiches » : la phrase
  reste, la valeur bouge, et le contrat ment sans que rien ne rougisse.
  C'est arrivé deux fois, le 2026-07-28 pour la taille du corpus et le
  2026-07-29 pour les plafonds synchrones. Une description dit la
  **règle** ; les **valeurs** se lisent dans `/v1` (bloc `limits`,
  alimenté par les modules qui les appliquent) comme les numéros de
  version passent par `versions()`. Deux tests le tiennent, dans
  `tests/test_api.py`. Même raison, même remède : ne jamais recopier à la
  main un nombre qui vit ailleurs.

## Versions et citation

Doctrine complète : « Numérotation », en tête de `CHANGELOG.md` (card et
stase ont la leur, plus exigeante, puisqu'on les installe). Ce qu'il ne
faut pas rater :

- **Au quotidien : rien.** La production suit `main`, le service publie
  le commit et le SWHID de card et de stase dans chaque réponse. Le seul
  geste régulier est l'entrée `## Non publié` du CHANGELOG. **Le
  proposer soi-même**, l'utilisateur ne le demandera pas.
- **Publier une version** (rare : PyPI, dépôt citable) :
  `python scripts/set_version.py 0.3.0` accorde `pyproject.toml`,
  `CITATION.cff` et `codemeta.json`. Ne JAMAIS y écrire un numéro à la
  main : `tests/test_citation.py` refuse le désaccord. Puis section de
  CHANGELOG, commit, `git tag -a vX.Y.Z`, `git push --tags`.
- **SWHID** : `swh:1:rev:<hash du commit>` EST l'identifiant Software
  Heritage d'une révision git, calculable sans aucun appel d'API. Il ne
  résout que si le dépôt est archivé : fait le 2026-07-22 pour les trois,
  et SWH revisite tout seul ensuite. Rien à refaire par version.
- Le service n'a pas besoin d'être tagué au rythme des correctifs :
  personne ne l'installe, et ce qui l'identifie dans un résultat est son
  commit. **Une exception, le contrat** : `api_version` part dans chaque
  réponse et dans l'OpenAPI, donc un changement de ce qu'un client voit
  (route, champ, empreinte, quota) se publie le jour où il est livré.
  Sinon, laisser le numéro en place est le bon comportement.
  `python scripts/set_version.py --etat` donne les faits. **Le proposer
  soi-même** quand le contrat bouge : l'utilisateur ne le demandera pas,
  il l'a dit explicitement le 2026-08-05.


## État

Le service est **déployé** depuis le 2026-07-17 sur la VM de
l'utilisateur, derrière l'Apache qui y sert déjà d'autres services
(`make apache`, port local 8001 via `CARD_API_PORT`, 8000 étant pris).

**En HTTPS sur `card-api.riverly.inrae.fr` depuis le 2026-07-28**
(certbot). Ce qui bloquait la diffusion des clés est donc levé : un
jeton ne transite plus en clair. L'adresse est publiée dans le contrat
(`CARD_API_PUBLIC_URL` du .env, bloc `servers` d'openapi.json) ; la
laisser VIDE en développement, sinon le « Try it out » d'une instance
locale part sur la production.

Ce qui a été livré et quand se lit dans `CHANGELOG.md`, ce qui reste
ouvert dans `docs/dev/CHANTIERS.md`. Ces deux fichiers font foi : ne pas
les paraphraser ici, cette section ne doit pas regonfler à chaque
chantier.

Trois points qui ne se déduisent pas du code :

- **Les clés se demandent par COURRIEL**, plus par une issue GitHub : le
  gabarit a été retiré parce qu'un jeton ne peut pas repartir par une
  page publique. Ne pas le réintroduire.
- **Les mentions légales** (README) sont rédigées d'après ce que le code
  fait ; éditeur, responsable de publication et hébergeur gagneraient une
  validation par le service compétent d'INRAE.
- **Un code de SITE Hub'Eau** n'est pas un code de station : le client
  écarte le doublon que Hub'Eau sert alors, et refuse en 422 nommant les
  stations quand plusieurs mesurent en parallèle (cf. `hubeau.py`).

À partir de la diffusion des premières clés, les numéros de version
redeviennent des engagements : `FINGERPRINT_VERSION` s'incrémente à tout
changement du calcul d'empreinte, et un renommage de colonne devient une
rupture d'API.

Deux points à ne pas reperdre :
- le durcissement des clés du 2026-07-18 n'est **pas rétroactif** : au
  prochain déploiement, recréer les clés (`make key`), et les jobs
  antérieurs ne sont pas listables par clé ;
- la sauvegarde du volume a été écartée volontairement : les clés sont
  réémissibles, les jobs éphémères, le journal petit.

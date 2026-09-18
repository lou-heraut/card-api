> **Statut : plan de chantier, ouvert.** Ce que le service doit gagner
> pour qu'un client puisse en dépendre, chantier par chantier, avec la
> décision retenue et ce qui la justifie. Ce qui est livré en sort et
> devient une entrée de `CHANGELOG.md`. Les pistes ouvertes qui ne
> relèvent pas de ce chantier restent dans `CHANTIERS.md`. Les
> arbitrages permanents du service restent dans `API.md` : ce plan y
> renvoie et n'en recopie rien.

# Ce qui manque pour qu'un client puisse dépendre du service

## D'où ça vient

L'audit de migration de MAKAHO (R Shiny vers un front branché sur ce
service) a produit trois consignes de passation, une par dépôt, dans
`../../../../MAKAHO_project/MAKAHO-next/docs/dev/passation/`. Elles sont
datées du 2026-09-18 et ne sont pas modifiées : c'est la trace de ce qui
a été transmis.

Ce document est **la version retenue après instruction**. Il en diffère
sur cinq points, chacun signalé à sa place. La plupart des chantiers ne
sont pas des demandes de MAKAHO : ils corrigent ce qui gêne tout usager
du service. Là où MAKAHO est la raison, c'est dit.

Le fait qui commande l'architecture, mesuré et publié par le service :
**aller chercher une chronique coûte environ trente fois ce que coûte la
calculer.**

## La règle qui commande tout le reste

Le second étage de cache (A5) pose une question de clé : quels
ingrédients y font entrer. Elle se tranche sans hésiter, parce que les
deux erreurs possibles ne sont pas symétriques :

> **Une clé trop complète ne coûte que des recalculs. Une clé incomplète
> rend des résultats faux, en silence, et personne ne le voit.**

Il n'y a donc aucune raison d'être malin. On énumère tout ce qui peut
influencer un résultat, on met tout, et dans le doute on ajoute. Cette
règle vaut aussi pour la suite : tout paramètre ajouté un jour à
l'extraction entre dans la clé le même jour.

## A1 et A3. Un seul bouton : l'âge accepté

**La passation en fait deux chantiers. Ils sont fusionnés ici.**

### Le constat

La durée de vie du cache des chroniques est écrite en dur dans
`hubeau.py`. Le défaut principal n'est pas la valeur : c'est qu'une
décision de politique ne soit pas réglable alors que tous les autres
plafonds du service sont dans `.env`.

La passation propose en plus un paramètre de requête `max_age=<jours>`,
« je n'accepte pas une copie plus vieille que N jours ». La forme est la
bonne : elle dit le **besoin** là où un `refresh=true` dirait l'**action**
et finirait dans une boucle qui tape sur Hub'Eau à travers le service.
C'est aussi la sémantique de `Cache-Control: max-age`, donc rien à
inventer.

### Pourquoi les deux ne font qu'un

Deux mécanismes séparés créent un bug de routage, et il n'est pas
théorique. Le service décide avant de calculer si une demande part en
réponse immédiate ou en file d'attente, en comptant les stations **à
télécharger** d'un côté et le total de l'autre. C'est `en_cache()` qui
répond à « celle-ci est-elle déjà là ? ».

```
  requête : 60 stations, max_age=2 jours
  copies sur disque : 10 jours d'âge

  en_cache()  compare 10 jours à la durée de vie (30 j)  -> "oui, en cache"
  le routage  compte donc 0 station à télécharger        -> réponse IMMÉDIATE
  le calcul   compare 10 jours à max_age (2 jours)       -> 60 téléchargements
```

Une réponse annoncée immédiate qui part pour plus d'une minute, derrière
le sémaphore, donc en bloquant tous les autres.

### La décision

Une seule question, posée à un seul endroit : **cette copie est-elle
assez fraîche pour ce qui est demandé ?** L'âge maximal vient de la
requête, son défaut vient de la configuration. Le routage et le calcul
l'appellent avec la même valeur, donc ne peuvent plus se contredire.

La durée de vie ne disparaît pas : elle devient le défaut d'un paramètre.

Le chantier est petit : `en_cache()` n'a qu'un seul appelant hors tests,
la décision de routage de `main.py`. Un test existant vérifie qu'elle
respecte la durée de vie et devra dire la nouvelle règle.

### La valeur du défaut, et sa vraie justification

Le mois est retenu. **La justification de la passation est écartée** :
elle dit qu'aucune fiche ne produit une série plus fine que le mois, donc
qu'un rafraîchissement plus fréquent ne peut rien changer. C'est un
raisonnement faux, qui confond le grain de la sortie avec la sensibilité
à la source : Hub'Eau révise n'importe quel point de l'historique (cf.
A2), et une révision de 1987 change la valeur de 1987 quel que soit le
grain.

Ce que le mois achète réellement, et qui tient :

- une chronique Hub'Eau est de la donnée **validée** : ce qui bouge est
  une révision ponctuelle, pas un flux ;
- celui qui a besoin de frais le demande, donc la durée n'arbitre plus
  entre deux besoins incompatibles ;
- et le pool (A4) repassera plus souvent que le mois, si bien que l'âge
  réel d'une chronique consultée sera la période du pool.

La règle s'écrit dans `API.md`, la valeur dans `.env`, et elle se lit
dans `/v1` comme les autres. Jamais recopiée dans une description.

Le contrat gagne un paramètre, donc `api_version`.

*État : accepté.*

## A2. La chronique se télécharge entière

### La règle

**Une chronique se télécharge entière, jamais par morceaux recollés.**

Hub'Eau révise n'importe quel point de l'historique, pas seulement la
queue récente. Un rafraîchissement partiel ne donnerait donc pas une
donnée « un peu périmée » : il donnerait **une chronique qui n'a jamais
existé chez Hub'Eau**, un corps historique d'une révision recollé à une
queue d'une autre. Et `data_fingerprint`, calculée sur les octets des
colonnes, signerait cet assemblage : une empreinte stable, reproductible,
et qui ne désigne aucun état réel de la source. C'est le contraire de ce
à quoi elle sert.

Ce n'est pas une optimisation à instruire plus tard, c'est une règle à
écrire **pour que personne ne la retrouve** : l'idée de ne rafraîchir que
la queue revient dès qu'on regarde une facture de bande passante.

### La décision

La règle et son raisonnement complet vont dans `API.md`. Le code ne
permet déjà pas de faire autrement ; un test le tient, en vérifiant que
la demande envoyée à Hub'Eau ne porte aucune borne de date.

*État : accepté, sans réserve.*

## A4. Le pool qui se garde chaud tout seul

### Le constat

Rafraîchir périodiquement **ce qui est déjà dans le cache**. L'ensemble
de travail se définit alors de lui-même : ce que les gens consultent
reste chaud, et le service n'a besoin d'aucune liste de stations
appartenant à un client. Il continue d'ignorer ce qu'est le RRSE, ce qui
est voulu.

### Ce que la passation n'a pas vu

L'éviction proposée est « une station qu'on n'a pas demandée depuis N
mois en sort ». Le service ne peut pas répondre à cette question : la
date du fichier de cache est la date de **collecte**, et le
rafraîchissement l'écrase. Après le premier passage du pool, toutes les
chroniques ont le même âge et plus rien ne distingue celle que personne
ne consulte.

Il faut donc une **date de dernière lecture**, distincte de la date de
collecte, que le service ne tient pas aujourd'hui.

### La décision

Un module `cache.py` possède le disque : les chemins, l'âge, la dernière
lecture, l'éviction, et la même chose pour le second étage (A5).
`hubeau.py` redevient un client Hub'Eau.

C'est la fondation de A1, A3 et A5 : tant que « l'âge d'une copie »
n'a pas un seul propriétaire, chacun de ces chantiers pose son bout de
politique dans un coin différent, et c'est ainsi qu'on fabrique une boîte
noire.

La dernière lecture vit dans une **table SQLite**, `data/cache.db`, une
ligne par entrée : sa clé, la date de sa dernière lecture, le nombre de
fois qu'elle a été demandée. La clé porte un préfixe de famille
(`chronique:`), si bien que le second étage de A5 y logera ses propres
entrées sans pouvoir les confondre.

**L'arbitrage était binaire : plusieurs fichiers indépendants, ou un
magasin coordonné.** Un fichier témoin vide par entrée, dont la DATE
aurait porté l'information, ne demandait aucun verrou : chaque écriture
touche son propre fichier, `touch` est atomique, il n'y a ni lecture
préalable ni état commun qu'une autre écriture puisse écraser. Sur la
robustesse de CETTE donnée les deux se valent donc, et le témoin est plus
simple. Un registre JSON, lui, est le plus mauvais des trois choix dans
tous les cas : il a le problème de coordination d'un magasin partagé sans
aucune de ses garanties, se réécrivant en entier à chaque lecture, et une
coupure au mauvais moment le perd tout entier au lieu d'une ligne.

**Ce qui a tranché est la pérennité, et un fait vérifié le 2026-09-18** :
un témoin ne peut porter qu'UN fait, et il en manquait déjà un. Le journal
d'usage enregistre le NOMBRE de stations d'une requête et non leurs codes
(`main.py`, appels à `log_usage`), si bien que « quelles entrées sont les
plus consultées » ne se dérive de rien, ni du journal ni des témoins. La
table le donne sans rien ajouter, et la question suivante s'y répondra par
une colonne plutôt que par un second mécanisme. C'est ce qui a fait
revenir sur le choix des témoins, écrits puis remplacés le même jour.

**Ce que la base coûte, dit franchement** : un schéma, donc une discipline
de migration le jour où il bouge, et un mode de panne qui n'existait pas,
l'écriture concurrente refusée (`database is locked`). Il est contenu par
trois choses : le registre est en WAL, une transaction porte une ligne, et
`mark_read` avale son échec. La direction de l'erreur reste la bonne : une
date perdue fait évincer trop tôt, donc retélécharger, jamais rendre un
résultat faux. `synchronous=NORMAL` complète le compromis, un arrêt brutal
de la machine pouvant perdre les dernières lectures notées, jamais la
base.

### Deux garde-fous

- le rafraîchissement retélécharge **la chronique entière** (A2) ;
- il est **poli** : les téléchargements s'étalent, ils ne partent pas en
  rafale au démarrage, et ils passent par le réessai déjà en place.

### Ce qui prouve que c'est fait

Le pool tourne, l'éviction est testée, `make stats` montre sa taille et
`/v1/health` la place occupée.

*État : **A4a livré le 2026-09-18** (le module, les deux dates, l'écriture
atomique) ; le pool et l'éviction restent, cf. A4b dans l'ordre de
livraison. Le registre de lectures est un ajout à la passation, en
table SQLite, le choix étant
arbitré sur la pérennité plutôt que sur la simplicité.*

## A5. Le second étage du cache

**Le chantier qui compte le plus.** Prévu de longue date dans `API.md`
sous « cache à deux étages ».

### Ce que c'est

Le service garde aujourd'hui la **matière première**, la chronique
journalière de chaque station. Il ne garde rien du **produit**.

```
  une demande de tendance, 228 stations, une fiche

  télécharger les chroniques    ~1,2 s par station   <- évité par le cache actuel
  agréger en série annuelle     ~0,04 s par station  <- payé À CHAQUE FOIS
  tester la tendance            microsecondes
```

L'agrégation est payée même quand tout est en cache, à chaque changement
de variable, et comme les calculs lourds passent un par un derrière le
sémaphore, elle est payée par tous ceux qui attendent derrière. C'est la
différence entre un service qu'on essaie et un service dont on dépend.

Le second étage garde la **série annuelle**. Une série de cinquante-sept
valeurs pèse quelques centaines d'octets.

### La clé

La passation propose (station, fiche, version de fiche, fenêtre
d'échantillonnage). **Trois changements.**

D'abord, la **version** de fiche est remplacée par son **SWHID**, qui est
un hash du contenu du fichier : une version se bosse à la main, un SWHID
non. Il voyage déjà dans `meta`, colonne `swhid`, donc il ne coûte rien à
obtenir.

Ensuite, la clé porte **la période**, parce que 21 fiches `output: series`
sur 99 ont une valeur qui dépend de la fenêtre d'extraction entière
(mesuré le 2026-09-18, cf. la section des mesures en fin de document).
Ce ne sont pas des cas marginaux : ce sont les durées, dates et volumes
d'étiage, dont le seuil est le maximum de tous les VCN10 de la période.
Changer la fenêtre déplace le seuil et toute la série avec lui.

Enfin, elle porte **l'identité de la construction de l'image**, et pas
seulement les commits de card et de stase. Deux choses changent le
résultat sans changer un commit : la bascule `CARD_ROLL_COMPAT=rcpp`,
documentée dans l'`ORIGINE_R.md` de card, qui modifie la moyenne mobile
donc VCN10 et tout ce qui en découle ; et une reconstruction qui tire un
numpy ou un pandas plus récent. Lier la clé à la construction ferme les
deux d'un coup, sans demander aucune discipline.

```
  clé = empreinte(
          code de la station
          empreinte de sa chronique        révision Hub'Eau
          SWHID de la fiche                contenu exact du YAML
          période                          [start, end]
          fenêtre d'échantillonnage        absente | preferred | MM-JJ
          identité de construction         card, stase, et l'environnement
        )
```

**Où prendre l'identité de construction.** `scripts/resolve_refs.py`
écrit déjà `build_refs.json` au moment de construire l'image : il suffit
d'y ajouter l'instant de construction. C'est ce qui couvre l'environnement
entier, dépendances comprises, sans rien avoir à énumérer.

Et il faut prévoir le cas où elle **manque** : la résolution des commits
part sur le réseau et rend `null` en cas d'échec, et en développement il
n'y a pas d'image du tout. Une clé amputée d'un ingrédient ferait
collisionner deux états différents du code. **Sans identité de
construction, le second étage est désactivé**, pas dégradé. L'instant de
construction, lui, est écrit localement et ne peut pas échouer, ce qui
rend le cas rare.

**La fenêtre d'échantillonnage a trois états, pas deux**, et les
confondre serait un bug silencieux. Absente, la fiche emploie la fenêtre
qu'elle déclare, qui peut être **adaptative**, calculée par série ;
`preferred` la remplace par la date fixe que la fiche déclare à côté.
Pour une fiche adaptative les deux ne coïncident pas : mesuré le
2026-09-18, `dtLF` rend 42 lignes sans paramètre et 41 avec
`preferred`. La clé porte donc la valeur **telle que demandée**, l'absence
comprise, sans jamais la normaliser.

### Ce qui reste DEHORS, et c'est tout l'intérêt

`level` (le alpha de MAKAHO), `mk`, `series`, `orient`, `stations_meta` :
ils ne touchent que le test ou la mise en forme. Le curseur alpha devient
donc gratuit, alors qu'il relance aujourd'hui toute l'agrégation.

### Ce qui a été vérifié pour que ce soit légitime

- **L'extraction est indépendante d'une station à l'autre** (mesuré, cf.
  fin de document), y compris pour les deux familles à seuil. Sans cela
  un cache par station serait faux dès le départ.
- **Et indépendante d'une fiche à l'autre** : `dtLF` rend la même série
  qu'elle soit demandée seule ou avec d'autres. Sans cela, une clé par
  couple (station, fiche) serait fausse elle aussi.
- **`meta` ne dépend pas des stations**, et s'obtient sans données par
  `metadata_only=True`. Une réponse assemblée depuis le cache peut donc
  porter le même bloc `meta` qu'une réponse calculée.

### Ce qu'il faut régler en chemin

- **La forme de l'appel change.** Aujourd'hui `pipeline.compute` fait un
  appel monolithique à `card.extract`. Il devra chercher chaque couple
  (station, fiche) dans le cache, ne calculer que les manquants, et
  réassembler. Le réassemblage doit rendre exactement ce qu'un calcul
  complet aurait rendu.
- **Le format de stockage.** Ni pyarrow ni fastparquet ne sont installés,
  et les ajouter pour cela serait cher. Le repli est le format déjà
  éprouvé pour les chroniques, CSV compressé avec les types déclarés à la
  relecture, à condition de prouver que l'aller-retour est exact au bit
  près : la parité MAKAHO est tenue à 1e-12, on ne peut pas se permettre
  une perte de précision à l'écriture.
- **L'écriture doit être atomique** (fichier temporaire puis renommage),
  sinon une lecture concurrente peut tomber sur un fichier à moitié
  écrit. Deux demandes identiques simultanées peuvent calculer deux fois,
  c'est acceptable ; lire un fichier tronqué ne l'est pas.

### L'invalidation et l'éviction sont deux choses

Elles se confondent facilement et méritent d'être séparées noir sur
blanc.

**Quand la clé change, rien n'est supprimé.** L'ancienne entrée cesse
simplement d'être demandée : plus personne ne calcule cette clé-là, donc
plus personne ne la lit. C'est l'invalidation, elle est automatique et
gratuite, et surtout elle ne peut pas se tromper puisqu'il n'y a aucun
code à écrire pour qu'elle marche.

**Mais l'orpheline reste sur le disque.** L'effacer est une question
matérielle, séparée : c'est l'éviction.

Et une orpheline est, par définition, quelque chose qu'on ne lira plus
jamais. **Une seule règle les ramasse donc toutes** : effacer ce qui n'a
pas été **lu** depuis N jours. Aucune liste à tenir de ce qu'un
changement a périmé, aucun cas particulier. C'est la même règle que
l'éviction des chroniques en A4, sur la même information, d'où le module
commun.

Conséquence à écrire pour que personne ne s'en étonne : une
reconstruction d'image orpheline **la totalité** du second étage d'un
coup. C'est le comportement recherché, mais les premières demandes après
une mise à jour repaient le plein tarif.

### Utile, et mesuré comme tel

L'espace possible est grand (stations fois fiches fois périodes fois
fenêtres). Mais on ne garde jamais l'espace, on garde ce qui a été
**visité**, et l'éviction efface le reste. Celui qui déplace le curseur
de période paie une fois pour cette fenêtre puis frappe chaud tant qu'il
y reste.

Cela dit, ce raisonnement reste une prévision. **Le taux de succès du
cache est publié par `make stats`**, comme les refus de quota le sont
déjà : si la mesure montre qu'il ne sert à rien, on le saura. C'est la
doctrine du service, les valeurs se règlent sur l'observation plutôt que
sur l'intuition.

### Ce qui prouve que c'est fait

- un second appel identique ne recalcule rien ;
- un changement de chacun des ingrédients de la clé invalide, **tenu par
  un test qui les énumère** : ajouter demain un paramètre à l'extraction
  sans l'ajouter à la clé casse ce test ;
- ce test emploie une fiche à fenêtre **adaptative**, `dtLF` par exemple,
  et non `QA`. Sans cette précision la garde est aveugle : `QA` déclare
  `09-01` et sa fenêtre préférée est `09-01`, donc l'absence de paramètre
  et `preferred` y donnent le même résultat, et le test passe au vert en
  laissant le bug entier. Même famille d'erreur que la vérification qui
  portait sur le cas ne discriminant pas, cf. `CLAUDE.md` de card ;
- et surtout, **cache actif et cache éteint rendent le même résultat**,
  comparé sur un échantillon réel. C'est le test le plus important du
  chantier.

*État : accepté, avec la clé revue sur trois points.*

## A6. Mesurer, puis relever le plafond synchrone

Une fois A5 en place : combien coûte réellement une demande de 228
stations tout en cache ? La réponse commande `SYNC_STATIONS_CACHED`.

**Mesurer avant de régler.** C'est déjà la doctrine du service pour les
quotas par IP, elle vaut ici aussi.

Ici MAKAHO est bien la raison : il demande 228 stations dans sa vue par
défaut, et un passage en file à chaque changement de variable serait une
régression d'ergonomie franche par rapport à l'application R actuelle.

*Fin :* la mesure est consignée, la valeur est dans `.env`, `/v1` la
publie comme les autres. Jamais recopiée dans une description.

*État : accepté, sans réserve. À faire en dernier.*

## A7. Exposer la chronique journalière

### Pourquoi, et l'ordre des raisons compte

La passation met en avant le coût évité. **La vraie raison est la
provenance.**

Si un client trace la chronique en interrogeant Hub'Eau lui-même, la même
page affiche deux choses qui ne viennent pas du même endroit : une carte
calculée sur une copie lue il y a trois semaines, et un graphe lu à
l'instant, éventuellement révisé entre-temps. Les deux peuvent diverger
sans que rien ne le signale, et aucune ne porte l'empreinte de l'autre.

En passant par le service, les deux lisent **la même copie**, avec la
même `data_fetched_at` et la même `data_fingerprint`. C'est ce que le
service est fait pour garantir, et c'est ce qui rend un export citable.

Le service la détient déjà : aucune fiche à entrée `Q` ne restitue la
chronique brute.

### La forme

Le contrat maison décide seul : une représentation une URL, donc un
jumeau `.csv` et jamais un paramètre `format` ; le bloc d'omission,
`data_fetched_at` et `data_fingerprint` voyagent comme partout ailleurs ;
l'âge accepté de A1 et A3 s'applique ici comme au reste.

Deux points à ne pas oublier :

- **le plafond de stations doit être bas**, une chronique pesant des
  dizaines de milliers de lignes. Ce n'est pas un calcul, donc pas le
  sémaphore, mais c'est un gros transfert ;
- **`stats.py` tient des listes FIXES d'endpoints** pour qu'une ligne
  apparaisse toujours, zéro compris. Un endpoint ajouté sans y être
  inscrit n'apparaît jamais dans le tableau de bord.

C'est aussi le premier point de sortie qui rend de la donnée **source**
plutôt qu'un résultat calculé : le service devient un miroir partiel de
Hub'Eau. C'est défendable, les droits Etalab étant déjà publiés dans
chaque réponse, mais ça se dit dans `API.md` plutôt que de se découvrir
plus tard.

Le contrat gagne une route, donc `api_version`.

*État : accepté, avec l'ordre des raisons inversé.*

## A8. Remonter le nombre de points

Dépend de **S1** dans `stase`.

`card/trend.py` ne sélectionne aucune colonne et `serialize.py` sérialise
ce qui est présent : le champ devrait traverser sans rien changer. **Le
vérifier**, et poser un test, sans quoi une future mise en forme de la
table le fera disparaître en silence.

Ce que ça apporte, indépendamment de MAKAHO : une pente sur 12 points ne
se lit pas comme une pente sur 55, et rien dans la réponse actuelle ne
permet de faire la différence, `period_start` et `period_end` prenant les
bornes de dates sans regarder les lacunes.

Le contrat gagne un champ, donc `api_version`, et l'OpenAPI le dit.

*État : accepté, sans réserve.*

## Les chantiers des autres dépôts

Ils ne sont pas décrits ici, seulement nommés, avec le renvoi vers le
dépôt qui les exécute. **Les trois sont livrés le 2026-09-18**, donc A8
n'attend plus rien.

- **S1, dans `stase`** : livré par `stase` 0.6.5. La tendance rend une
  colonne `n`, le nombre de valeurs sur lesquelles le test a réellement
  porté, mesurée sur une série trouée et sur deux fenêtres. Le journal du
  moteur porte le détail et la raison.
- **C1, dans `card`** : livré. Le refus d'une fenêtre intra-annuelle que
  CARD-R acceptait est consigné, avec sa raison et sa mesure sur les 228
  chroniques du RRSE, dans la section « Divergences assumées avec le R »
  de son `docs/dev/ORIGINE_R.md`.
- **C2, dans `card`** : livré. Un test constate que `n` traverse
  `card.trend`, et le plancher du paquet passe à `stase>=0.6.5`.

## Ce qu'il ne faut pas faire

- **Ne pas** donner au service la moindre notion de RRSE, de réseau de
  référence, ou de liste de stations d'un client. A4 existe précisément
  pour l'éviter.
- **Ne pas** ajouter d'indicateur de qualité de chronique. La règle des
  30 ans est un choix éditorial de MAKAHO. Le service rend des faits
  (A8), l'interprétation appartient à l'appelant.
- **Ne pas** écrire une valeur de plafond, de durée ou de décompte en
  clair dans une description d'API. La règle existe dans `CLAUDE.md`, et
  elle a été payée deux fois.
- **Ne pas** introduire une seconde fenêtre, dite d'analyse, appliquée
  après l'extraction pour rendre le cache plus efficace. Proposé puis
  retiré pendant l'instruction : avec 21 % des fiches `series` dont la
  valeur dépend de la fenêtre entière, elle calculerait des seuils sur
  une période que personne n'a demandée, et rendrait un `dtLF` qui n'est
  pas celui de la fenêtre affichée. Faux, et invisible.

## Ordre de livraison

```
  A4a  le module cache.py                  fondation de tout le reste
  A1+A3  l'âge accepté                     contrat : api_version
  A2   la règle de la chronique entière    du pur écrit
  A5   le second étage                     le gros morceau
  A4b  le pool et l'éviction               dépend de la forme de A5
  A7   la chronique exposée                contrat : api_version
  A6   le plafond                          après mesure, donc en dernier
```

`S1`, `C1` et `C2` sont livrés (cf. plus haut). `A8` ne dépend donc plus
de rien, mais il change le contrat : il part avec la prochaine coupe
d'`api_version` plutôt que seul.

**Versions.** Le service se coupe une version le jour où ce qu'un client
voit change. Ici : A1 et A3 (un paramètre), A7 (une route), A8 (un
champ). Grouper ce qui part ensemble et
couper une fois par livraison. `python scripts/set_version.py --etat`
donne les faits.

## Mesures faites pour écrire ce plan

Toutes le 2026-09-18, sur le corpus et le code du jour. Elles ne sont pas
tenues à jour : elles disent sur quoi les décisions reposent.

- **21 fiches `output: series` sur 99** ont une valeur qui dépend de la
  fenêtre d'extraction entière : `fQ01A`, `fQ05A`, `fQ10A` (seuil pris
  comme quantile de toute la chronique) et les quinze fiches d'étiage
  `dtLF`, `startLF`, `endLF`, `vLF`, `centerLF`, `allLF` avec leurs
  variantes saisonnières (seuil pris comme maximum de tous les VCN10 de
  la période). Critère : un process sans agrégation temporelle dont la
  fonction **réduit** au lieu de transformer, ce que l'attribut
  `is_transform` déclare à côté de la fonction.
- **L'extraction est indépendante d'une station à l'autre** : `QA`,
  `dtLF` et `fQ01A` donnent exactement la même série pour une station
  qu'elle soit extraite seule ou dans un lot.
- **L'extraction est indépendante d'une fiche à l'autre** : `dtLF` rend
  la même série seule ou demandée avec `QA` et `fQ01A`.
- **`meta` ne dépend pas des stations** et s'obtient sans données par
  `metadata_only=True`.
- **`sampling_period` absent et `preferred` ne sont pas la même chose**
  pour une fiche à fenêtre adaptative : `dtLF` rend 42 lignes sans
  paramètre, 41 avec `preferred`. Pour `QA`, dont la fenêtre déclarée est
  déjà la préférée, les deux coïncident, ce qui rend la confusion facile.
- **Aucune fiche du corpus ne déclare de période propre** sur un
  process, mais le mécanisme existe dans le moteur.
- **Deux entrées échappent aux commits** : `CARD_ROLL_COMPAT` et les
  versions des dépendances. D'où l'identité de construction dans la clé.
- **Couper l'entrée ou transmettre la période au moteur ne donnaient pas
  le même résultat**, mesuré sur 232 chroniques RRSE réelles et neuf
  fiches, période 1968 à 2026-07-27 : sept stations voyaient leur fenêtre
  adaptative se déplacer sur `QJXA` et `tQJXA`, dont trois changeaient de
  valeur, d'un facteur. Les seuils (`upLim`, `lowLim`) étaient indemnes.
  C'est cette mesure qui a fait trouver le défaut du moteur ; il est
  corrigé, et la même mesure rejouée ne montre plus aucun écart de valeur
  ni aucune ligne perdue. Détail : `CHANGELOG.md`.
- **Aucun test de `card` ne passait de période** à `card.extract`, donc
  le correctif du moteur n'a fait bouger aucun golden.

Deux affirmations de la passation et de l'audit ont été **vérifiées et
trouvées fausses** ; elles ne sont pas reprises ici :

- « aucune fiche ne produit une série plus fine que le mois, donc un
  rafraîchissement plus fréquent ne peut rien changer » : confond le
  grain de la sortie avec la sensibilité à la source (cf. A1) ;
- « le curseur de période d'analyse n'affecte que le test, donc une série
  agrégée unique couvre toutes les périodes » (audit, section 5.5) :
  MAKAHO passe le curseur **aux deux**, `period_default` à l'extraction
  et `period_trend` à la tendance (`server.R`, section 6.2.3 et 6.2.4).
  Le dimensionnement de cache qu'en tire l'audit est donc à refaire, et
  il n'y a **aucune divergence de parité** à craindre de ce côté :
  MAKAHO coupe à l'extraction, le service aussi.

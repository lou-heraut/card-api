> **Statut : terminé le 2026-11-09.** Chaque chantier est livré ou
> refermé, son état dans le tableau ci-dessous. Ce qui restait du cache
> APRÈS que `dev/plans/2026-09-18_cache.md` a été entièrement livré
> (service 0.5.0 à 0.8.0, moteur 0.6.5). Il ne redit rien de ce document : les
> mesures qui ont commandé l'architecture, la règle de la clé et ce qui a
> été vérifié dans le moteur sont là-bas. Ici, ce que l'audit du 2026-09-19
> a trouvé, et ce qu'il a laissé ouvert. Ce qui est livré en sort et devient
> une entrée de `CHANGELOG.md`.
>
> | chantier                            | état                                               |
> |-------------------------------------|----------------------------------------------------|
> | B1, évincer par la place            | **livré** le 2026-09-19                            |
> | B2a, les chroniques en Parquet      | **livré**, card-api 0.8.0                          |
> | B2b, ne plus relire la chronique    | **non retenu** le 2026-11-05, rouvrable sur mesure |
> | B3, faire surveiller le pool        | **livré** le 2026-11-09                            |
> | B4, l'indépendance par station      | **refermé**, c'est une propriété du moteur         |
> | B5, le plafond des demandes à froid | **livré** le 2026-11-06, en production le 11-09  |
> | B6, le seuil de rafraîchissement    | **livré** le 2026-11-06                            |

# Ce qui reste du cache, après l'audit

## D'où ça vient

Le plan de cache livré, l'audit a consisté à **chercher à casser** ce qui
venait de l'être, plutôt qu'à relire ce qu'on croyait avoir écrit. Quatre
défauts en sont sortis, tous corrigés le jour même (détail dans
`CHANGELOG.md`) : un disque qui refuse l'écriture cassait chaque calcul,
l'éviction pouvait effacer sur une information absente, deux fils pouvaient
écrire dans le même fichier temporaire, et un ingrédient manquait à la clé
(`CARD_ROLL_COMPAT`).

Ce qui en est sorti est de natures différentes, et les distinguer évite de
tout traiter avec la même urgence : **une décision prise dont le seuil était
à fixer** (B1, livré), **une question mal posée au départ qu'il a fallu
reprendre** (B2, dont la première moitié est livrée et corrige une faute de
justesse), **un besoin d'exploitation à instruire** (B3), **une garantie à
mesurer plus large** (B4, refermée par un argument structurel), et **un
plafond taillé sur une mesure périmée**, trouvé en chemin et qui ne concerne
pas le cache mais le routage (B5).

## B1. Évincer par la place : livré le 2026-09-19

L'éviction était temporelle, elle effaçait ce que personne n'avait lu depuis
quatre-vingt-dix jours. Rien ne bornait donc la TAILLE du cache : si l'usage
explose, le disque se remplit avant que la première entrée ne devienne
évinçable.

### La règle

Au-delà d'un plafond, effacer les entrées **les moins récemment lues**
jusqu'à repasser dessous. C'est la même information que l'éviction
temporelle, dans le même registre : une seule question posée deux fois, avec
deux réponses différentes (« plus personne ne veut de ça » et « je n'ai plus
la place »).

### Le seuil : absolu, et pas une fraction du disque

La question s'est posée d'un plafond relatif à la place disponible. **Écarté,
et la raison est qu'il rend le comportement imprévisible** : la VM est
partagée avec d'autres services, si bien qu'un plafond en pourcentage ferait
évincer le cache parce qu'un AUTRE service a rempli le disque. L'éviction se
déclencherait alors pour une raison qui ne la regarde pas, et le jour où
quelqu'un cherchera pourquoi ses demandes sont redevenues lentes, il n'aura
aucun moyen de le relier à la cause.

Un plafond absolu, en gigaoctets, dans `.env` comme les autres, est
prévisible et se relit. Et il n'a pas besoin d'être malin : mesuré, une
chronique pèse ~100 Kio et une série ~4 Kio, donc quelques gigaoctets
tiennent des dizaines de milliers de chroniques et des centaines de milliers
de séries, très au-delà de tout usage plausible. Le plafond n'est pas là
pour arbitrer une place rare, il est là pour qu'une dérive ait une borne.

`/v1/health` publie déjà la taille de chaque étage ET l'état du disque de la
VM : de quoi voir le rapport entre les deux sans qu'on ait à le coder.

**Une suite possible, non prise pour l'instant** : reculer aussi quand la
place LIBRE du disque descend sous un plancher. C'est une autre question
(protéger la VM, pas borner notre empreinte), et elle ne se pose pas
aujourd'hui, la VM ayant 530 Go libres.

## B2. Le plancher de relecture : la question était mal posée

Une demande de 200 stations tout en cache coûte ~5,7 s, dont l'essentiel est
**la relecture des chroniques et leur signature**, que le second étage ne
supprime pas puisque l'empreinte entre dans sa clé.

La première proposition était d'enregistrer l'empreinte à côté du fichier
pour ne plus avoir à le relire. **C'était traiter le symptôme.** La question
posée à l'endroit qu'il fallait est : pourquoi une relecture coûte-t-elle
18 ms ? Mesuré le 2026-09-19 sur une chronique réelle de 22 335 jours :

| format | taille | écrire | relire |
|---|---|---|---|
| `csv.gz` (actuel) | 102 Kio | 138,7 ms | **18,4 ms** |
| csv nu | 605 Kio | 32,0 ms | 16,6 ms |
| **parquet** | 253 Kio | 7,5 ms | **4,2 ms** |
| feather | 349 Kio | 4,3 ms | 2,4 ms |

Plus l'empreinte, 3,7 ms, qui ne dépend pas du format.

### B2a, le format : livré le 2026-09-19, et c'était une correction

Passer les chroniques en Parquet a été fait, et la mesure a montré en chemin
que ce n'était pas une optimisation mais **une correction de justesse**.

**Le défaut trouvé.** L'aller-retour par un CSV perdait le dernier bit de
16 % des valeurs (1 ulp, 2,5e-16), assez pour changer l'empreinte : la MÊME
chronique portait donc deux empreintes selon qu'elle venait du réseau ou du
disque. Trois conséquences, toutes silencieuses. Un client voyait deux
`data_fingerprint` pour une donnée identique, alors que ce champ existe
précisément pour identifier l'état de la source. La clé du second étage
contenant l'empreinte, elle changeait après chaque rafraîchissement, donc
une série était recalculée pour rien. Et un résultat n'était pas
reproductible au bit près selon l'état du cache.

Parquet restitue le cadre exactement, empreinte comprise : vérifié, zéro
valeur modifiée. `FINGERPRINT_VERSION` passe donc à `v2`, parce que les
empreintes publiées jusqu'ici décrivaient la donnée telle que le cache la
rendait : vu du dehors, une donnée identique change de signature, et c'est
exactement ce que ce préfixe sert à départager.

**Le gain de temps, mesuré sur la vue MAKAHO réelle** (200 stations) : un
rechargement passe de 5,7 s à 3,1 s, le curseur alpha de 5,7 s à 2,9 s, la
première ouverture de 11,8 s à 8,9 s. La place passe de 21 à 54 Mo pour 200
chroniques, et l'écriture est dix-huit fois plus rapide, ce qui allège le
pool.

### B2b, ne plus relire du tout : le profil dit ce qu'il reste à gagner

Une demande de 200 stations tout en cache, une fiche, se décompose ainsi
(mesuré le 2026-09-19, après B2a) :

| ce qui prend le temps | durée | part |
|---|---|---|
| lire les chroniques et les signer | 1,84 s | 61 % |
| relire les 200 séries du second étage | 0,71 s | 23 % |
| la tendance (Mann-Kendall et Sen) | 0,46 s | 15 % |
| sérialiser | 0,02 s | 0 % |

B2b (enregistrer l'empreinte et les bornes de dates à l'écriture) viserait
donc les 61 %, et ferait tomber la demande vers ~1,2 s. Le risque reste
celui dit plus haut : un état dérivé qui peut mentir, à fermer en
enregistrant aussi taille et date du fichier.

Deux remarques que le profil apporte :

- **la tendance et la relecture des séries sont maintenant du même ordre**
  que ce qu'on chercherait à supprimer ; passé B2b, le plancher serait à
  ~1,2 s et il n'y aurait plus de gros terme à retirer ;
- les 0,71 s de relecture des séries sont **deux cents petits fichiers**,
  dont le coût est surtout de l'ouverture. Les regrouper par fiche ferait
  gagner, mais casserait le modèle de clé par station qui permet les
  succès partiels. À ne pas faire pour un gain de cet ordre.

**Non retenu le 2026-11-05.** Le gain (de ~3 s à ~1,2 s pour 200 stations
en cache) ne justifie pas un état dérivé qui peut diverger du fichier tant
qu'aucun client réel n'a montré que ~3 s le gêne. À rouvrir si les durées
de production, lues dans `make stats` une fois MAKAHO branché, le
demandent.

## B3. Faire surveiller le pool

Un pool mort ne se voit qu'en regardant `make stats`. Il journalise ses
passes (`event: pool`) et ses échecs (`pool_failed`), donc l'information
existe ; personne ne la lit.

`scripts/veille_sante.py` est une sonde qui tourne **hors de la VM** (une
veille qui tourne sur la VM meurt avec elle) et qui interroge le service. Ce
chantier consiste à lui faire vérifier une chose de plus : qu'une passe de
pool a bien eu lieu récemment. Ce qui suppose de décider **par où elle le
voit**, et c'est la seule vraie question : le journal d'usage n'est pas
exposé par l'API, donc soit `/v1/health` publie la date de la dernière passe
(un champ de plus, donc une version à couper), soit la sonde se contente de
ce qu'elle peut déjà voir.

**Décidé le 2026-11-05 : `/v1/health` publie la date de la dernière passe
du pool, et la sonde la vérifie.** C'est la seule voie par laquelle une
sonde extérieure voit le pool sans lire le journal, et le champ ne coûte
presque rien. Le contrat bouge : il part dans la même version mineure que
le refus natif des paramètres inconnus (`ROADMAP.md`).

**Livré le 2026-11-09, sous une forme précisée en route.** La date seule
ne suffisait pas : pour la juger trop vieille, la sonde aurait dû connaître
le rythme du pool (période réglable, passe étalée sur la moitié de la
période, attente au démarrage), et après un redémarrage aucune passe ne
finit avant trois heures environ. `/v1/health` publie donc aussi
`next_pass_by`, l'heure avant laquelle la prochaine passe doit être finie,
que le pool calcule depuis son propre rythme : une période de sommeil, plus
une période pour la passe. La sonde la compare à l'heure qu'il est et n'a
aucun seuil à régler. Une passe qui échoue ne repousse pas l'échéance, et
un pool coupé le dit, puisque plus rien n'est alors évincé. Écarté :
publier la date de démarrage et laisser la sonde fixer un seuil, qui
crierait au loup le jour où la période change. Les deux dates vivent en
mémoire, le pool tournant dans le processus du service.

## B4. L'indépendance par station : refermé le 2026-09-19

Tout le second étage repose sur une hypothèse : **la série d'une station ne
dépend pas des autres stations de la demande.** Elle tenait sur sept fiches
mesurées. Elle tient maintenant sur deux choses, et la première vaut mieux
que n'importe quelle mesure.

**L'argument structurel.** Le moteur groupe TOUJOURS par identifiant de
série avant d'appliquer une fonction : chaque appel d'agrégation passe
`[id_col, ...]` comme clés de groupement (`stase/extraction.py`, les trois
chemins d'agrégation). Une fonction de fiche ne reçoit donc jamais les
données de deux stations ensemble. Une fiche inter-stations ne serait pas une
fiche inhabituelle, ce serait un changement du MOTEUR.

**La mesure élargie.** Une fiche par combinaison (phénomène, aspect, purpose,
forme de sortie) parmi les 133 fiches à entrée `Q`, soit 19 familles
distinctes, comparées seule contre lot sur trois stations de longueurs
différentes : **aucun écart**, en 16 secondes. C'est ce qui couvre les
familles que sept fiches ne touchaient pas, sans faire tourner les 472.

**Ce qui resterait à faire, et seulement si le besoin apparaît** : une
propriété DÉCLARÉE côté card, sur le modèle de `is_transform`, par laquelle
une fiche dirait qu'elle est inter-stations, et que le service refuserait de
mettre en cache. Ça ne se justifie que le jour où une telle fiche est
envisagée, et ce jour-là c'est le moteur qu'il faudra changer d'abord.

## B5. Le plafond des demandes à froid est taillé sur une mesure périmée

Trouvé le 2026-09-19 en instruisant B2, et ça ne concerne pas le cache mais
le **routage**.

`SYNC_STATIONS` (10) borne les stations À TÉLÉCHARGER dans une réponse
immédiate. Il a été fixé sur une mesure de juillet, ~1,2 s par chronique.
Mesuré à nouveau, chronique entière et pagination suivie :

| station | jours | durée |
|---|---|---|
| K0550010 | 39 343 (108 ans) | **24,7 s** |
| K0403010 | 24 014 (66 ans) | **11,8 s** |

Soit dix à vingt fois la mesure de juillet. Une demande de dix stations à
froid tiendrait donc deux à quatre MINUTES en réponse immédiate, sans rien
renvoyer ni montrer d'avancement, là où un job donne un ticket et sa
progression : exactement ce que le plafond doit empêcher. (Corrigé le
2026-11-06 : ce paragraphe disait aussi qu'elle bloquerait les autres
demandes derrière le sémaphore. C'est faux, les téléchargements se font
avant de le prendre, dans `pipeline.compute`.)

**Ce qui commande le coût est le nombre de LIGNES, pas le nombre d'appels.**
Vérifié : `obs_elab` accepte plusieurs stations en un seul appel
(`code_entite=A,B,C`), et le coût par ligne est identique aux appels séparés,
0,295 ms. Grouper ne gagnerait donc rien. Le JSON n'est pas en cause non plus,
le décoder coûte 0,4 % de l'appel, et la réponse arrive déjà en gzip.
`format=csv` n'existe pas sur cet endpoint (400).

### Ce qu'il faut faire, et dans quel ordre

1. **Remesurer proprement**, une dizaine de stations à un moment calme : deux
   stations à un instant donné ne suffisent pas à retailler un plafond, et
   Hub'Eau peut simplement avoir une mauvaise journée.
2. Puis **abaisser `SYNC_STATIONS`** pour qu'une réponse immédiate à froid
   reste sous la minute, sans doute autour de 3. Ce n'est pas une perte de
   service : au-delà, la demande devient un job, ce qui est précisément à
   quoi sert la file, et le pool rend les demandes à froid rares.
3. Et **noter que la durée dépend de la LONGUEUR de la chronique**, qui va de
   66 à 108 ans dans cet échantillon. Un plafond en nombre de stations ne
   peut donc pas borner une durée finement ; il n'a pas à le faire, il doit
   seulement éviter l'ordre de grandeur de la minute.

### La mesure du 2026-11-06, et ce qui en sort

Faite vers minuit, heure calme : une station du RRSE sur 23, dix en tout,
chacune téléchargée entière en séquence. Deux colonnes, parce que les deux
chemins ne coûtent pas pareil : depuis un poste de développement
(`hubeau.fetch_chronicle` seul), et en production (un appel
`/v1/trend?cards=QA` à froid, donc téléchargement, écriture, extraction et
tendance compris, depuis la VM).

| station    | jours  | poste  | production |
|------------|-------:|-------:|-----------:|
| A234021001 | 22 447 |  5,9 s |     16,7 s |
| H032103001 | 21 590 |  5,6 s |     12,6 s |
| J561301001 | 21 063 |  8,7 s |     20,4 s |
| K326401001 | 18 417 |  4,2 s |      8,4 s |
| M024301010 | 14 326 |  4,3 s |     10,3 s |
| O300671001 | 27 685 | 11,4 s |     21,9 s |
| P011501001 | 29 690 |  8,7 s |     10,1 s |
| S223561001 | 21 519 |  5,8 s |      9,3 s |
| V101501001 | 22 218 |  5,8 s |     12,1 s |
| X113000101 | 18 871 |  4,4 s |      8,7 s |

Médiane en production ~11 s, maximum ~22 s sur des chroniques de 40 à 80
ans ; la plus longue du RRSE (108 ans) se situerait vers 30 à 40 s. Le
coût par ligne depuis le poste (0,23 à 0,41 ms) retrouve celui de septembre
(0,295 ms) : la règle « le coût suit le nombre de lignes » tient, et la
production paie environ le double, le chemin réseau de la VM et le calcul
s'ajoutant.

**`SYNC_STATIONS` passe de 10 à 3** : les téléchargements d'une demande se
suivent (`pipeline.py`), donc trois stations à froid font ~35 s dans le cas
courant et rarement plus d'une minute, quand quatre la dépasseraient
souvent. Au-delà, la demande devient un job. La valeur publiée par `/v1`
change : elle part dans la prochaine version, et la production ne la prend
qu'une fois `CARD_API_SYNC_STATIONS` corrigé dans son `.env`.

Le chiffre de juillet (~1,2 s, « trente fois le calcul ») était recopié dans
huit fichiers, dont deux textes que lit un client. Il est retiré partout :
les textes disent la règle (« bien plus cher à rapatrier qu'à calculer ») et
renvoient ici pour les mesures.

## B6. Le seuil de rafraîchissement du pool n'a pas de raison écrite

Trouvé le 2026-11-05. Deux âges se côtoient et ne répondent pas à la même
question :

- `CARD_API_MAX_AGE_DAYS` (aujourd'hui 30) : l'âge qu'une **requête**
  accepte. Au-delà, elle retélécharge avant de répondre, donc compte la
  station comme à télécharger et peut basculer en job ;
- `CARD_API_POOL_REFRESH_DAYS` (7, retiré par B6) : l'âge au-delà duquel le
  **pool** rafraîchit une copie en tâche de fond. Son seul rôle est
  qu'aucune requête ne rencontre une copie plus vieille que l'âge accepté.

Le second doit donc rester sous le premier, avec une marge qui couvre
l'intervalle entre deux passes et une panne de Hub'Eau de quelques jours.
Rien ne justifie 7, ni mesure ni argument, dans aucun document ni commit.
À 7 jours le pool retélécharge chaque chronique quatre fois par mois, alors
que ce qui fonde le mois (donnée validée, révisions ponctuelles) vaut aussi
pour lui : pour les 228 stations de MAKAHO, ~1 000 téléchargements par mois
contre ~270 à 25 jours.

Une phrase était fausse au passage, dans `pool.py`, `.env.example` et
`dev/plans/2026-09-18_cache.md` (A1) : l'âge réel d'une chronique consultée n'est pas la
période des passes, c'est ce seuil, à une passe près. Corrigée avec B6.

**Livré le 2026-11-06** : le seuil se déduit de l'âge accepté (25 jours
pour 30, `pool.seuil_jours`) et le réglage séparé disparaît, pour que les
deux ne puissent plus se contredire. Rien ne change pour un client. Un test
place une copie dans la marge et vérifie que le pool la renouvelle alors
qu'une requête la servirait encore.

C'est le schéma classique d'un cache, sous les noms de Caffeine (Java) :
l'âge accepté est `expireAfterWrite`, le seuil du pool `refreshAfterWrite`,
les 90 jours sans lecture `expireAfterAccess`, le plafond de place
`maximumWeight`. Un écart, voulu : Caffeine ne rafraîchit une entrée que
quand on la lit, le pool rafraîchit tout ce qui est en cache. D'où la règle
« le pool ne marque aucune lecture » : un rafraîchissement compté comme une
lecture empêcherait toute entrée de sortir.

## Ce qu'il ne faut pas faire

- **Ne pas** rendre le cache obligatoire au bon fonctionnement. La règle est
  en tête de `cache.py` et l'audit a montré ce qu'elle coûte quand elle
  manque : le cache est une accélération, jamais une dépendance.
- **Ne pas** ajouter un ingrédient à l'extraction sans l'ajouter à la clé le
  même jour. Un test énumère les ingrédients pour que l'oubli casse quelque
  chose ; `CARD_ROLL_COMPAT` était passé à travers parce qu'il n'est pas un
  paramètre de requête mais une variable d'environnement.
- **Ne pas** faire évincer le cache par un pourcentage de place disponible
  (cf. B1) : il se déclencherait pour une raison qui ne le regarde pas.
- **Ne pas** enregistrer d'état dérivé à côté d'un fichier sans un moyen de
  détecter qu'il a divergé (cf. B2b).

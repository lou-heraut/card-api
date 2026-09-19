> **Statut : plan de chantier, trois restes ouverts** au 2026-09-19. Ce qui
> reste du cache APRÈS que `PLAN_CACHE.md` a été entièrement livré (service
> 0.5.0 à 0.8.0, moteur 0.6.5). Il ne redit rien de ce document : les
> mesures qui ont commandé l'architecture, la règle de la clé et ce qui a
> été vérifié dans le moteur sont là-bas. Ici, ce que l'audit du 2026-09-19
> a trouvé, et ce qu'il a laissé ouvert. Ce qui est livré en sort et devient
> une entrée de `CHANGELOG.md`.
>
> | chantier | état |
> |---|---|
> | B1, évincer par la place | **livré** le 2026-09-19 |
> | B2a, les chroniques en Parquet | **livré**, card-api 0.8.0 |
> | B2b, ne plus relire la chronique | ouvert, chiffré, **non décidé** |
> | B3, faire surveiller le pool | ouvert, une question de forme à trancher |
> | B4, l'indépendance par station | **refermé**, c'est une propriété du moteur |
> | B5, le plafond des demandes à froid | ouvert, **à remesurer d'abord** |

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

**Rien n'est décidé sur B2b** : à juger sur des durées de production.

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

À instruire, pas encore tranché.

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
froid tiendrait donc deux à quatre MINUTES en réponse immédiate, derrière le
sémaphore, en bloquant tous ceux qui attendent : exactement ce que le
plafond doit empêcher.

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

Rien n'est changé pour l'instant : un plafond se retaille sur une mesure,
pas sur deux points.

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

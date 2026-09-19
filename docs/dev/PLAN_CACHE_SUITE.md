> **Statut : plan de chantier, ouvert.** Ce qui reste du cache APRÈS que
> `PLAN_CACHE.md` a été entièrement livré (service 0.5.0 à 0.7.0, moteur
> 0.6.5). Il ne redit rien de ce document : les mesures qui ont commandé
> l'architecture, la règle de la clé et ce qui a été vérifié dans le moteur
> sont là-bas. Ici, ce que l'audit du 2026-09-19 a trouvé, et les quatre
> questions qu'il a laissées ouvertes. Ce qui est livré en sort et devient
> une entrée de `CHANGELOG.md`.

# Ce qui reste du cache, après l'audit

## D'où ça vient

Le plan de cache livré, l'audit a consisté à **chercher à casser** ce qui
venait de l'être, plutôt qu'à relire ce qu'on croyait avoir écrit. Quatre
défauts en sont sortis, tous corrigés le jour même (détail dans
`CHANGELOG.md`) : un disque qui refuse l'écriture cassait chaque calcul,
l'éviction pouvait effacer sur une information absente, deux fils pouvaient
écrire dans le même fichier temporaire, et un ingrédient manquait à la clé
(`CARD_ROLL_COMPAT`).

Ce qui reste est de quatre natures différentes, et il faut les distinguer :
**une décision prise dont le seuil est à fixer** (B1), **une question
d'architecture mal posée au départ et qu'il faut reprendre** (B2), **un
besoin d'exploitation à instruire** (B3), et **une garantie à mesurer plus
large** (B4).

## B1. Évincer par la place, pas seulement par le temps

**Décidé : à faire.** L'éviction actuelle est temporelle, elle efface ce que
personne n'a lu depuis quatre-vingt-dix jours. Rien ne borne donc la TAILLE
du cache : si l'usage explose, le disque se remplit avant que la première
entrée ne devienne évinçable. C'est visible dans `/v1/health` et dans
`make stats`, ce n'est pas borné.

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

### Deux portes, et elles ne se valent pas

**B2a, le format.** Passer les chroniques en Parquet ferait tomber le
plancher de 200 stations de ~5,1 s à ~1,4 s. Aucune comptabilité nouvelle,
aucun risque de cohérence, et l'écriture devient dix-huit fois plus rapide,
ce qui compte pour le pool qui réécrit tout le cache chaque semaine. Le prix
est 2,5 fois plus de place (100 Kio contre 253 Kio par chronique, soit
~59 Mo au lieu de ~24 Mo pour 233 stations) et un retéléchargement unique,
la marque de format du nom changeant. Parquet plutôt que feather parce que
le second étage l'emploie déjà : un format pour les deux étages, et pas deux
formats à connaître pour un gain de 2 ms.

**B2b, ne plus relire du tout.** Enregistrer l'empreinte et les bornes de
dates au moment d'écrire une chronique. Le gain restant après B2a serait de
1,4 s à ~0,7 s, la moitié venant de l'empreinte. Mais il introduit un état
qui peut mentir : une empreinte enregistrée qui ne correspond plus au
fichier ferait servir une série périmée, en silence, ce qui est la seule
faute que ce chantier ne doit pas commettre. Elle se ferme en enregistrant
aussi taille et date du fichier et en recalculant si elles ne correspondent
plus, mais c'est de la machinerie pour un facteur deux.

**Ordre retenu : B2a, puis on regarde.** B2a est un changement de format
mesuré, sans état nouveau. B2b ne se justifie que si 1,4 s gêne encore, et il
se décidera alors sur des chiffres de production.

### Ce qu'il faudra vérifier en faisant B2a

- **l'empreinte ne doit pas changer de valeur** pour une même chronique
  (elle hache les octets des colonnes, or Parquet restitue les types
  exactement là où le CSV les reconstruit) ; si elle change, toutes les clés
  du second étage changent une fois, ce qui est acceptable mais doit être
  dit et non découvert ;
- la marque de format `_FORMAT` de `cache.py` passe à `v3`, donc les copies
  actuelles ne sont plus trouvées et sont retéléchargées une fois ;
- `_COLONNES` garde son rôle : un fichier du bon format mais du mauvais
  contenu reste traité comme absent.

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

## B4. L'indépendance, mesurée sur tout le corpus

Tout le second étage repose sur une hypothèse : **la série d'une station ne
dépend pas des autres stations de la demande.** Elle est mesurée sur sept
fiches couvrant les quatre formes de sortie, fenêtres adaptatives et valeur
de date comprises, sans aucun écart (détail dans `PLAN_CACHE.md`, A5).

Le risque résiduel est une fiche qui normaliserait entre stations, un indice
régional par exemple : le cache la casserait en silence. **Aucune fiche du
corpus ne fait cela aujourd'hui**, et c'est ce qui rend ce chantier
optionnel plutôt qu'urgent. Deux façons de le fermer :

- une mesure unique sur les 472 fiches, longue mais sans risque, qui
  transforme un pari en fait ;
- ou une propriété DÉCLARÉE côté card, sur le modèle de `is_transform` : une
  fiche dit si elle est inter-stations, et le service refuse de la mettre en
  cache. C'est plus durable, puisque ça couvre aussi les fiches futures, et
  ça demande une décision dans card.

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

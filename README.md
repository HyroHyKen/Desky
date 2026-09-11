# Desky — lots L0 à L8

Implémentation du [cahier des charges](CDC_desktop_pet.md), découpée en dix lots.

- **L0 — spike de faisabilité** : lever le risque technique principal, à savoir
  une fenêtre translucide sans bordure, toujours au premier plan, affichant un
  rendu ModernGL offscreen composé par `QPainter`, cliquable uniquement sur ses
  pixels opaques et n'attrapant jamais le focus. *Terminé, verdict GO.*
- **L1 — socle applicatif** : cadence adaptative, multi-écran, sol et
  déplacement, plein écran, persistance atomique, journal catégoriel. *Terminé.*
- **L2 — génome et géométrie** : schéma borné et versionné, tirage déterministe
  avec validation de cohérence, superellipsoïde à normales analytiques,
  assemblage hiérarchique, migration additive. *Terminé.*
- **L3 — rendu** : contour par inverted hull, ombre de contact, visage SDF
  piloté par uniformes. *Terminé.*
- **L4 — vie** : ressorts amortis exacts, couches idle / look-at / action,
  suivi du curseur, courbes de pose nommées. *Terminé.*
- **L5 — capteurs et contexte** : activité sans hook, catégorisation de
  process, sessions audio WASAPI, dérivation de l'état. *Terminé.*
- **L5b — locomotion** : déplacement sur l'écran, démarches, terrain
  multi-écran, domicile. *Terminé.* Lot intercalaire hors du plan initial.
- **L6 — comportement et interface** : besoins, utility AI, neuf actions v1,
  humeur, état persistant, puis carton de premier lancement, nommage, bulle de
  besoin et panneau de soin. *Terminé*, en deux phases.

`Desky` est un nom de code technique ; le nom commercial n'est pas arrêté. Tout
ce qui est visible du système en dérive via `APP_NAME` dans
[`pet/__init__.py`](pet/__init__.py).

## Lancer

```bash
.venv/Scripts/python.exe -m pet.main --diag
```

Clic gauche : attraper et déplacer — le pet retombe et se recale sur le sol.
Clic droit : quitter. La fenêtre étant `Qt.Tool`, elle n'est ni dans la barre des
tâches ni dans l'alt-tab, donc c'est la seule sortie jusqu'au menu contextuel du
lot L7.

| Option | Effet |
|---|---|
| `--diag` | régime, fps, CPU, coût du rendu, hit-testing et position, toutes les 2 s |
| `--size N` | hauteur logique en pixels (120–400, persistée) |
| `--verbose` | journal en DEBUG, également sur la console |
| `--purge` | supprime toutes les données locales et quitte |
| `--run-seconds N` | quitte après N secondes, pour scripter les mesures |

## Tests

466 tests, en `unittest` de la bibliothèque standard — aucune dépendance de test
ajoutée.

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -t .
```

Ils ne se contentent pas de vérifier des intervalles demandés : ils mesurent les
**cadences réellement délivrées**, **tuent réellement** un process en pleine
écriture cinq fois de suite, et comparent les **normales analytiques à des
tangentes calculées par différences finies**.

Le seul critère d'acceptation non mécanisable — « 20 robots visuellement
distincts et tous viables » — se rend sur une planche de contact :

```bash
.venv/Scripts/python.exe -m tools.contact_sheet --seeds 20 --out planche.png
.venv/Scripts/python.exe -m tools.face_sheet --out visages.png
.venv/Scripts/python.exe -m tools.explore_designs --out exploration.png
.venv/Scripts/python.exe -m tools.anim_strip --what actions --out mouvement.png
.venv/Scripts/python.exe -m tools.anim_strip --what look --out suivi.png
```

Et pour comprendre pourquoi `watching` ne se déclenche pas, une sonde qui montre
l'arbre de décision seconde par seconde :

```bash
.venv/Scripts/python.exe -m tools.context_probe --seconds 120
```

Et l'étude de mouvement du déplacement, en chronophotographie :

```bash
.venv/Scripts/python.exe -m tools.loco_strip --gait hop --out saut.png
```

Et la journée synthétique du comportement, qui rend son verdict sur les deux
critères d'acceptation du lot L6 :

```bash
.venv/Scripts/python.exe -m tools.day_sim
.venv/Scripts/python.exe -m tools.day_sim --profile bureau --out journee.png
```

Et les trois planches de l'interface — les sigles de la bulle et des yeux, les
icônes du panneau aux tailles où elles seront vues, et les cinq pages :

```bash
.venv/Scripts/python.exe -m tools.bubble_sheet --out bulle.png
.venv/Scripts/python.exe -m tools.icon_sheet --out icones.png
.venv/Scripts/python.exe -m tools.panel_sheet --out panneau.png
```

## Installation

Python **3.12** est requis : le CDC impose 3.11+, et PySide6 ne publie pas encore
de roue pour 3.14.

```bash
py -3.12 -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt
```

---

## Lot L0 — ce qui est établi

Mesuré sur Intel Iris Xe (l'iGPU, c'est-à-dire le pire cas visé), Windows 10
19045, rendu 220×220, MSAA 4×.

| Critère d'acceptation du CDC §16 | Résultat |
|---|---|
| Bords anti-aliasés sans liseré noir | **Tenu.** 0 violation de prémultiplication sur 145 200 sous-pixels ; 388 pixels d'alpha partiel sur le pourtour ; couleur des bords dé-prémultipliée dans [0,469 – 1,000], sans composante sombre parasite |
| Clics traversants hors silhouette, captés dessus | **Tenu.** Bascule de `WS_EX_TRANSPARENT` sur lecture d'alpha, seuil 0,15 |
| La fenêtre ne prend jamais le focus | **Tenu.** `Qt.Tool` + `WS_EX_NOACTIVATE` + `WA_ShowWithoutActivating` ; la fenêtre au premier plan reste inchangée après clic |
| CPU < 4 % d'un cœur à l'état visible au repos | **Tenu à 10 fps** (état idle du CDC §3) : 0,8–4,7 %. **Non tenu à 30 fps** : 3,9–7,0 % |
| Fonctionne sur un GPU intégré Intel | **Tenu.** Le contexte se crée sur l'Iris Xe par défaut, alors que la machine dispose aussi d'une RTX A1000 |
| Démarrage à froid < 3 s | À mesurer au lot L8, sur binaire packagé |

Empreinte observée : **102,8 Mo** de RSS, contre un budget de 150 Mo.

### Coût d'une image, par étage

| Étage | Coût | Devenu |
|---|---|---|
| bind + clear | 0,002 ms | — |
| draw de la sphère toon | 0,026 ms | — |
| resolve MSAA 4× | 0,035 ms | — |
| **read GPU → CPU** | **0,735 ms** | optimisé au lot L1, voir plus bas |
| flip + copie numpy | 0,149 ms | **supprimé** (axe Y inversé dans la projection) |
| calcul de la bbox opaque | 0,233 ms | **amorti** sur 8 images |

Deux enseignements structurants :

1. **Le rendu ne coûte rien** (0,026 ms) et **le MSAA non plus** (0,035 ms). Il
   n'y a donc aucun compromis de qualité visuelle à envisager pour tenir les
   budgets : la géométrie du lot L2, le contour et le visage du lot L3 ont une
   marge considérable.
2. **Le coût est la relecture GPU → CPU**, inhérente à l'architecture offscreen
   imposée par le CDC §4. Elle est de plus **sous-estimée d'un facteur ~2 par un
   banc en boucle serrée** : isolée, elle mesure 0,8 ms, mais 1,8 ms dans
   l'application réelle, où 33 ms d'inactivité séparent les images et laissent
   l'iGPU se sous-cadencer. Un banc synthétique ne suffit donc pas à valider un
   budget sur ce projet, il faut mesurer dans l'app.

---

## Lot L1 — ce qui est établi

| Critère d'acceptation du lot | Résultat |
|---|---|
| 30 fps en interaction, 10 en idle, 0 quand masqué | **Tenu**, sur les cadences délivrées : 30,0–30,5 fps mesurés en interactif, 10,0 en idle, 0 tick en suspendu. Couvert par 9 tests |
| Aucun battement de cadence | **Tenu.** Hystérésis de 1 200 ms : sur 2 s de sollicitations régulières, un seul changement de régime |
| Survit à un kill brutal sans corruption | **Tenu.** 5 kills en pleine écriture, JSON complet à chaque fois. `os.replace()` tient |
| Se recale quand un écran disparaît | **Tenu.** Repli sur l'écran principal, couvert en test pur |
| Se masque sous une application plein écran | **Tenu.** Détecté contre une vraie fenêtre plein écran, avec le shell explicitement écarté |
| La purge est effective | **Tenu.** Emporte aussi les temporaires |
| Le journal ne contient que des catégories | **Tenu**, vérifié par test |

### La relecture GPU → CPU : le PBO est écarté

Le README du lot L0 recommandait une relecture asynchrone à double PBO. **La
mesure l'a invalidé.** Quatre variantes, cadencées à 30 fps :

| Variante | médiane | p90 | max |
|---|---|---|---|
| `read()` + `frombuffer` (état L0) | 1,518 ms | 2,070 ms | 2,848 ms |
| **`read_into` dans un tableau persistant** | **1,084 ms** | **1,486 ms** | **2,037 ms** |
| async 2 PBO + `read()` | 1,513 ms | 2,396 ms | 4,423 ms |
| async 2 PBO + `read_into` | 1,103 ms | 2,653 ms | 3,871 ms |

Le gain ne venait pas de l'asynchronisme mais de la **suppression de
l'allocation de 193 Ko par image**. Le PBO n'apporte rien sur la médiane et
dégrade nettement les queues, pour une image de latence en plus. Retenu : la
variante 2, −29 % sur la médiane et meilleure sur les trois statistiques, sans
latence ni complexité.

### Décisions techniques du lot

- **Un seul espace de coordonnées : le physique.** Curseur (`GetCursorPos`), rect
  de fenêtre (`GetWindowRect`), rects de moniteurs (`GetMonitorInfo`),
  déplacement (`SetWindowPos`) et buffer alpha sont tous en pixels physiques.
  Rien ne transite par l'espace logique de Qt, ce qui supprime par construction
  le risque de double scaling sur un montage à DPI mixtes.
- **Identifiant de moniteur matériel.** La position est mémorisée sous le
  `DeviceID` renvoyé par `EnumDisplayDevices`, et non sous le nom de périphérique
  (`DISPLAY1`, `DISPLAY2`…), qui n'est qu'un rang d'énumération : rebrancher les
  câbles dans l'autre ordre suffirait à faire réapparaître le pet sur le mauvais
  écran.
- **Position stockée en fraction, pas en pixels.** Fraction de la zone de travail
  plus écart au sol : après un passage de 1920 à 1280 de large, une position
  absolue de 1700 px serait hors écran.
- **Le shell est écarté de la détection de plein écran.** `Progman`, `WorkerW` et
  la barre des tâches couvrent tout l'écran en permanence ; les prendre pour des
  applications masquerait le pet en continu, ce qui se lirait comme un logiciel
  qui ne démarre pas.
- **Le plein écran ne masque que sur l'écran concerné.** Une vidéo en plein écran
  sur le second moniteur ne fait pas disparaître le pet resté sur le premier.
- **Chute parabolique avec rebond amorti**, pas d'interpolation linéaire : le
  CDC §10 l'interdit sur tout mouvement visible, et l'exigence vaut dès qu'un
  mouvement existe. Les couches à ressorts du lot L4 remplaceront cette
  intégration ad hoc.
- **Type de timer.** Le tic natif de Windows est de 15,625 ms, donc un
  `CoarseTimer` ne délivre que des cadences de 64/n fps : une demande de 33 ms y
  est arrondie à 3 tics, soit 21 fps au lieu de 30. Le rendu interactif utilise
  donc un `PreciseTimer` ; l'idle et le hit-testing gardent un `CoarseTimer`, qui
  laisse le système regrouper ses réveils — ce qui compte pour l'autonomie, seul
  motif de la contrainte de framerate.
- **Sortie de l'application.** Une fenêtre `Qt.Tool` n'est pas une fenêtre
  primaire pour Qt : sa fermeture ne déclenche pas la sortie. D'où
  `setQuitOnLastWindowClosed(False)` et une sortie pilotée explicitement.

### Deux défauts trouvés par les tests, pas par la lecture

1. **Temporaires orphelins.** Un process tué n'exécute aucun nettoyage : 8 kills
   en pleine écriture laissent 7 fichiers `.tmp`. Sans balayage, le répertoire de
   données accumulerait un résidu à chaque crash, ce que l'exigence de
   désinstallation sans résidu du CDC §16 n'admet pas. `sweep_temp_files()` est
   appelé au démarrage, après le mutex — donc en situation d'exclusivité.
2. **Verrou transitoire après `os.replace()`.** Windows refuse parfois l'ouverture
   du fichier pendant quelques millisecondes, antivirus ou fin de `MoveFileEx`. Le
   test l'a reproduit en `PermissionError`. Sans tentatives, un démarrage tombant
   dans cette fenêtre repartait sur les valeurs par défaut et l'utilisateur y
   perdait la position de son pet. `read_json` réessaie désormais — mais **ne
   réessaie pas** sur un JSON syntaxiquement invalide, l'écriture étant atomique :
   une erreur de syntaxe est une vraie corruption, pas une lecture partielle.

---

## Lot L2 — ce qui est établi

| Critère d'acceptation du lot | Résultat |
|---|---|
| Une même graine produit toujours la même géométrie | **Tenu**, prouvé par test unitaire : maillages comparés **octet par octet** sur plusieurs graines. Le générateur est aussi immunisé contre l'état du `random` global |
| 20 graines → 20 robots distincts et tous viables | **Tenu**, cf. planche de contact. Les 4 types d'oreilles apparaissent, les palettes suivent les poids du §7 |
| Régénération complète sous 200 ms | **Tenu** très largement : 6,3 ms au pire sur 60 graines |
| Migration v1 → v2 sans dérive morphologique | **Tenu.** Un paramètre absent est complété par défaut, **tous les autres restent au bit près**. Un retour en arrière conserve les paramètres inconnus |
| Normales analytiques, sans moyennage de faces | **Tenu.** Écart maximal aux tangentes numériques : **0,0000°**, y compris sur les cas effilés |
| Maillage exploitable par l'inverted hull du lot L3 | **Tenu.** Fermé — chaque arête partagée par exactement 2 triangles, V−E+F = 2 — et sans triangle dégénéré |

### Les paramètres du génome sont des multiplicateurs

Le CDC §7 donne ses plages autour de 1.0 (`head.radius` 0.85–1.35, `body.width`
0.75–1.25) : ce ne sont pas des tailles absolues. La silhouette de référence
qu'ils multiplient vit dans [`geometry/proportions.py`](pet/geometry/proportions.py),
source unique partagée par la validation de viabilité et l'assemblage. Si les
deux calculaient les dimensions séparément, une règle de cohérence pourrait
rejeter des génomes viables ou en accepter d'inviables.

**Les bornes du §7 et ses règles de cohérence sont compatibles** : 67,5 % des
tirages sont viables, soit 1,48 tirage par robot. La règle « tête plus large que
le corps × 1,8 » fait le vrai travail (32 % des rejets) ; celle des oreilles
croisant la dalle mord rarement mais mord (0,3 %). La règle des pupilles ne se
déclenche, elle, sur aucun tirage : c'est une garde contre une édition manuelle
ou un élargissement futur des plages, et le test le dit explicitement.

### Deux décisions ouvertes du §17, tranchées

- **§17.2, type d'oreilles — trait génétique.** Le CDC le liste dans le tableau
  du génome, et le génome est l'identité du robot. La contradiction avec la
  boutique du §13 se résout par un mécanisme de **surcharge** : `build()` accepte
  des `overrides` qui habillent le robot sans muter son génome. Le gène est le
  trait de naissance, l'inventaire est un costume. Un test vérifie que le génome
  d'origine sort intact.
- **§17.3, épaisseur du contour — trait génétique.** L'argument est celui du CDC
  lui-même : « un robot à gros trait a une identité forte ». Coût : un paramètre.

### Deux défauts trouvés par la planche, pas par la lecture

1. **La dalle faciale lisait comme un nœud papillon.** Une plaque plane posée à
   une profondeur fixe devant un crâne qui bombe voit son centre s'enterrer dans
   la tête, et seuls ses bords émergent. Le CDC §9 demandait « un quad légèrement
   bombé » — c'est désormais une **coque** générée sur les exposants du crâne et
   un rayon 2 % supérieur, qui l'épouse comme une visière. D'où la primitive
   `superellipsoid_patch`, portion ouverte de superellipsoïde.
2. **Le cou flottait comme une perle détachée.** Trop mince, et les parties se
   touchaient sans se recouvrir. Le CDC assume des jointures visibles, mais un
   interstice n'est pas une jointure : le cou est élargi et **déborde** dans le
   corps et dans la tête, et la tête est enfoncée dans ce qui la porte.

Un troisième réglage a suivi : la dalle occupait toute la face et l'ensemble
lisait comme un téléviseur. Son emprise angulaire a été resserrée pour que le
plastique l'encadre.

### Choix d'assemblage

- **Nœud de tête à la jointure du cou**, pas au centre du crâne. C'est le pivot
  correct pour le look-at du lot L4 : tourner la tête autour de son centre donne
  un mouvement de bille, pas de nuque.
- **Topologie du rig constante** quelle que soit la morphologie. Le nœud `neck`
  existe même quand sa longueur est nulle — seule la partie disparaît — pour que
  le lot L4 n'ait pas deux chemins d'animation selon le génome.
- **Effilement du corps à jacobien exact.** Le superellipsoïde ne sait pas
  exprimer le rapport épaules/base du §7 ; la déformation est donc appliquée aux
  positions et les normales corrigées par la transposée inverse de son jacobien,
  résolue analytiquement. Vérifié sommet par sommet.
- **Ordre de déclaration du génome figé.** Il fixe l'ordre de consommation du
  PRNG : insérer un paramètre ailleurs qu'à la fin changerait tous les robots
  régénérés depuis leur graine. Un test garde cet ordre explicitement.

---

## Lot L3 — ce qui est établi

Mesuré sur Intel Iris Xe, rendu 220×220, MSAA 4×, cadencé à 30 fps comme dans
l'application.

| Critère d'acceptation du lot | Résultat |
|---|---|
| Contour d'épaisseur uniforme sous toutes les rotations | **Tenu.** Mesuré par différence d'images sur 10 rotations : variation de 4,2 à 12,9 % selon le génome |
| ...et pour tout génome, exposants extrêmes compris | **Tenu.** Cube arrondi `n=0,35` avec le trait le plus épais : 4,01 px moyens, variation 5,2 %, **aucune fente** |
| Paliers de dégradé nets | **Tenu** depuis le lot L0 : rampe de 5 pixels en filtrage `NEAREST` |
| Visage pilotable par uniformes | **Tenu.** 11 expressions, 4 étapes de clignement, 4 directions de regard, 3 transitions — un seul shader, **aucune branche côté CPU** |
| 30 fps stables | **Tenu très largement.** 2,53 ms par image, soit **92,4 % de marge** sur la période de 33,3 ms |
| Prémultiplication préservée avec les 4 passes | **Tenu.** 0 violation, à toutes les rotations |

CPU : **2,53 % d'un cœur à 10 fps** (état idle, budget 4 %), 7,6 % à 30 fps.

### Coût par passe

| Passe | Coût | Note |
|---|---|---|
| corps (toon + relecture) | 2,34 ms | dominé par la relecture GPU→CPU |
| ombre de contact | **−0,05 ms** | gratuite, dans le bruit de mesure |
| contour (inverted hull) | **+0,145 ms** | double les draw calls, ne coûte presque rien |
| visage SDF | **+0,102 ms** | remplace « des centaines de sprites » (CDC §9) |
| **total** | **2,53 ms** | |

Le constat du lot L0 se confirme une troisième fois : **la géométrie est
gratuite, seule la relecture coûte.** Doubler les draw calls pour le contour se
paie 0,145 ms.

### Le sens de culling : ma prédiction du lot L2 était fausse

J'avais écrit qu'avec l'axe Y inversé, l'inverted hull devrait culler `GL_BACK`
là où le CDC §8 écrit `GL_FRONT`. **La mesure dit le contraire** :

| Sens | Pixels sombres parmi les opaques | Lecture |
|---|---|---|
| `GL_FRONT` | 4,6 % | un **trait** |
| `GL_BACK` | 100 % | un **aplat noir** |

C'est donc `GL_FRONT`, exactement comme l'écrit le CDC. La raison est que
l'enroulement des maillages du lot L2 avait justement été choisi pour que les
faces extérieures restent front-facing **après** l'inversion : la règle standard
s'applique donc telle quelle. Un test verrouille les deux sens, pour qu'une
future inversion de projection soit détectée et non re-déduite.

### Le point A du cadrage initial : résolu, et sans objet

Au cadrage du projet, j'avais signalé que l'inverted hull aurait besoin d'un jeu
de **normales soudées**, distinct des normales analytiques du toon, faute de quoi
le contour s'ouvrirait aux exposants bas du superellipsoïde.

Mesuré : **il ne s'ouvre pas.** Et la raison est dans le maillage du lot L2 —
aucun sommet n'y est dupliqué (indices bouclés modulo `sectors`, pôles en
sommets uniques, fermeture prouvée par test). Les normales sont donc **déjà**
partagées : il n'y a rien à souder. Le risque était réel, la conception l'avait
éliminé par avance sans que je le voie.

### L'ombre de contact ne peut pas être dans le plan du sol

Première implémentation : un quad horizontal au sol, comme une ombre physique.
**Mesuré : 102 × 8 pixels** — un filet invisible. La caméra n'a que 9° de
tangage, donc elle voit le sol presque de profil.

Le quad est désormais **aligné sur l'écran**, sous les pieds : 110 × 32 pixels,
et il se comporte comme le §8 le demande — soulevé, il s'élargit (110 → 158 px)
et pâlit (alpha 98 → 28). Le CDC demande « une ellipse floutée rendue sous le
robot », et « ombre de **contact** » dit bien qu'elle marque le contact, non la
projection d'une lumière.

### Le visage

Le CDC §9 est suivi à la lettre : ce n'est pas de la géométrie, mais la coque
bombée du lot L2, à laquelle le lot L3 a ajouté des **coordonnées UV** — l'espace
2D dans lequel le fragment shader dessine les pupilles par SDF, en émissif non
éclairé, avec un halo additif.

Les sept commandes du §9 sont exposées telles quelles : `uBlink`, `uGaze`,
`uLidTop`, `uLidBottom`, `uSquint`, `uPupilScale`, `uGlitch`. Une **expression**
est un jeu nommé de ces valeurs — 11 sont définies — et une transition est leur
mélange. `FaceState.lerp` fournit le mélange ; c'est le lot L4 qui décidera
*quand* et *à quelle vitesse*, et le lot L6 qui choisira l'expression.

Trois choix de rendu, chacun mesuré :

- **Espace isotrope.** La dalle étant plus large que haute, dessiner directement
  en UV déformerait les pupilles. L'aspect est mesuré sur les **bornes réelles**
  de la coque, pas déduit de ses paramètres angulaires.
- **Anti-aliasing par `fwidth`** du gradient de la SDF, et non par un seuil fixe :
  le trait reste net à toute taille de rendu, ce qui compte puisque la taille est
  réglable de 120 à 400 px.
- **Plancher d'ouverture** à 4 % : un œil fermé devient un **trait** et ne
  disparaît pas, ce qu'un clignement complet rendrait autrement inquiétant.

### Trois défauts trouvés par la mesure, pas par la lecture

1. **La dalle sortait en portrait** (aspect 0,74) alors que l'esthétique retenue
   repose sur un écran large. Cause : aux exposants bas, `|sin v|^n1` croît très
   vite près de l'équateur et étire l'axe vertical, si bien que des étendues
   angulaires comparables donnent une coque plus haute que large. Les deux
   étendues sont désormais franchement dissymétriques.
2. **Le VAO du visage n'était pas créé**, et le visage ne s'affichait pas du tout.
   Le vertex shader déclarait `in_normal` sans l'utiliser, le compilateur GLSL
   l'éliminait, et mon test d'attributs refusait alors la liaison. La disposition
   du tampon est maintenant calculée **par programme**, les champs absents
   devenant un saut d'octets.
3. **Les pupilles se recouvraient en un seul pavé cyan.** Je multipliais
   `eye.size` par 2,1 alors que le CDC §7 le donne déjà « en part de dalle » —
   d'où une demi-hauteur de 58 % de la dalle.

### Écarts assumés par rapport à l'arborescence du §5

Le CDC §5 énumère les passes (`toon.py`, `outline.py`, `face.py`) sans dire qui
les enchaîne. Deux modules s'ajoutent donc :

- **`render/scene.py`** — possède les VBO et fixe l'ordre des passes. Le faire
  depuis l'une des passes l'aurait rendue maîtresse des autres. `toon.py` est en
  conséquence devenue une passe pure, sans géométrie ni cadrage.
- **`render/shadow.py`** — l'ombre a sa géométrie, son shader et ses réglages
  propres ; la diluer dans la passe toon aurait mélangé deux choses sans rapport.

### Réglages identifiés pour le lot L9

- **Couplage taille/écart des pupilles.** `uEyeSpacing` suit l'aspect de la
  dalle, `uEyeSize` non : sur une dalle très large (aspect mesuré jusqu'à 2,97)
  les pupilles s'écartent sans grossir et lisent petit. La cause est connue, le
  réglage reste à faire.
- **Plancher de `eye.size` relevé** de 0,16 à 0,21 après rendu : en dessous, la
  pupille lit comme un grain de poussière. Le §7 laisse cette plage vide et
  invite explicitement à l'ajuster au tuning.
- **Étendue de la dalle ramenée** de 0,82 à 0,72 : au haut de la plage de
  `face.plate_ratio`, elle atteignait le bord du crâne au lieu d'y être encadrée.

---

## Lot L4 — ce qui est établi

| Critère d'acceptation du lot | Résultat |
|---|---|
| Suivi du curseur naturel, non mécanique | **Tenu.** Trois ressorts étagés — pupilles, tête, corps — et c'est l'étagement qui fait le naturel, pas la vitesse |
| Aucune interpolation linéaire visible | **Tenu**, et *mesuré* : variation de vitesse de 1,48 à 19,13 selon l'easing, nulle pour une interpolation linéaire. Chaque segment de chaque action est vérifié |
| Le robot reste intéressant plus de 60 s sans interaction | **Tenu** sur 120 s simulées : 6 canaux bougent en continu, aucun figement de plus de 0,5 s, 30+ clignements, 90+ saccades |
| L'idle tourne sans le `brain` | **Tenu.** La couche idle ne prend aucune entrée — ni capteur, ni comportement |
| Bornes du §10.2 : ±55° lacet, ±35° tangage | **Tenu**, et le corps prend le relais au-delà, avec retard mesuré |
| Les pupilles atteignent la cible avant la tête | **Tenu**, vérifié en fraction de course parcourue |

Coût : **0,112 ms par image** pour les trois couches, soit **4 % du budget d'une
image**. 30 fps tenus, rendu total 2,96 ms.

### Le ressort devait être exact, pas approché

La cadence de ce projet passe de 30 à 10 fps selon le régime (CDC §3) : `dt`
triple d'un instant à l'autre. Un intégrateur explicite se met alors à osciller
puis diverge. Les ressorts utilisent donc la **solution analytique** de
l'oscillateur amorti, dans ses trois régimes.

Mesuré : **écart de 1,1 × 10⁻¹⁵** entre un pas de 1/30 s et un pas de 1 ms, sur
la même durée simulée. Le changement de régime de cadence ne modifie donc pas le
mouvement — et un pas de 5 secondes ne fait pas diverger le ressort.

### Trois vitesses, pas une

| Ressort | Pulsation | Amortissement | Rôle |
|---|---|---|---|
| pupilles | 27,0 | 0,80 | arrivent les premières (§10.2) |
| tête | 9,5 | 0,72 | légèrement sous-amortie : dépasse puis revient |
| corps | 3,6 | 1,00 | traîne, prend le relais au-delà des bornes |

Une seule vitesse pour les trois donnerait un mouvement de bloc. C'est
l'étagement qui fait lire le mouvement comme vivant.

### La respiration a demandé un nœud de rig dédié

Le §10.1 demande « une sinusoïde sur l'échelle Y du corps ». Mais l'échelle d'un
nœud **se propage à ses enfants** : la poser sur `body` étirait le cou et la tête
avec la poitrine.

Le maillage du corps est donc porté par `body_flex`, un nœud enfant que rien
d'autre n'utilise. Mesuré : les pieds restent exactement au sol (`y_min = 0` à
toute amplitude), la tête monte avec la poitrine, et **la hauteur de la tête ne
varie pas de 0,000 %**.

### Un défaut de conception exposé par les tests

Mon « intérêt » — l'attention qui décroît quand le curseur s'éloigne —
multipliait l'angle brut **avant** l'écrêtage. Conséquence : la tête ne pouvait
jamais atteindre ses 55°, donc **le relais du corps prescrit par le §10.2 était
du code mort**. La géométrie le dit : la tête sature dès que le curseur est à
2,4 hauteurs de robot, or l'intérêt tombait déjà à zéro à 5 hauteurs.

L'écrêtage et le relais se calculent désormais sur l'angle brut, et l'intérêt ne
s'applique qu'au résultat. La portée d'intérêt est passée à 13 hauteurs, valeur
**contrainte par la géométrie** et non choisie : c'est la distance à laquelle le
relais du corps s'achève.

### Une régression de performance introduite puis corrigée

Pour l'ombre, j'ai ajouté un appel à `current_monitor()` par image. Mesuré :
**1,256 ms** — davantage que tout le rendu, à cause d'`EnumDisplayDevicesW`.

L'identité matérielle d'un écran ne change jamais pour un périphérique donné :
elle est désormais mise en cache, et le cache est invalidé quand l'ensemble des
périphériques change.

| Appel | Avant | Après |
|---|---|---|
| `monitor_from_window` | 1,256 ms | **0,027 ms** |
| `list_monitors` | 3,651 ms | **0,040 ms** |

Bénéfice rétroactif sur le lot L1 : la vérification système à 4 Hz brûlait 1,5 %
d'un cœur en pure énumération d'écrans.

### Un piège de conception trouvé par le banc-titre

`RigPose` relevait comme « pose de repos » l'état **courant** du rig. Créer un
second animateur sur un rig déjà animé y cuisait donc l'animation en cours — ce
qui s'est vu immédiatement sur le banc-titre, où chaque ligne héritait de la
posture finale de la précédente.

La pose de repos est désormais relevée **à la construction** du robot et portée
par `Robot.base_pose`. `Animator.for_robot()` est le constructeur recommandé.

### Ce qui reste ouvert

- **La décision §17.4 est tranchée à moitié.** Les courbes `sleep` et `sit`
  existent et se maintiennent, mais *quand* le pet s'endort appartient au lot
  L6. La mécanique ne préjuge pas du choix.
- **Amplitudes conservatrices.** Les déplacements verticaux de `sit` et
  `celebrate` valent 5 à 12 % de la hauteur du robot ; c'est lisible mais
  modeste, et c'est un réglage du lot L9.
### Deux défauts corrigés après la livraison du lot

1. **Le tangage était inversé** : la tête se baissait quand le curseur montait.
   La convention du canal `head.pitch` n'était pas fixée, et `rotation_x`
   positive envoie la direction du visage vers le bas. Elle est désormais
   explicite — *positif = vers le haut* — inversée **une seule fois**, au point
   de traduction des canaux.

   Le défaut en masquait un second : `sleep` était juste par accident
   (+0,30 = tête baissée), mais **`yawn` bâillait en baissant la tête** au lieu
   de la rejeter en arrière. Les deux courbes sont corrigées.

   Le trou était dans les tests : ils vérifiaient les **bornes** du tangage,
   jamais son **sens**. Ils mesurent maintenant où pointe réellement le visage
   dans le monde, ce qui ne peut pas être satisfait par erreur.

2. **Le test de kill brutal était instable**, et la cause n'était pas le produit.
   Il laissait 0,25 s au sous-process écrivain pour démarrer et écrire. L'échec
   est apparu quand la suite est passée de 106 à 194 tests : le process parent
   porte alors numpy, moderngl et PySide6, et lancer un sous-process depuis un
   parent lourd sous Windows consomme tout le budget. Le test attend désormais
   la **première écriture effective** avant de tuer — il mesure ainsi
   l'atomicité, et non la latence de démarrage de l'interpréteur.

   *Cette première correction était incomplète.* L'attente sortait
   immédiatement dès le deuxième tour, le fichier cible existant déjà depuis le
   tour précédent : le writer suivant ne recevait à nouveau qu'un délai fixe.
   La cible est maintenant effacée avant chaque tour. Vérifié sur six
   exécutions du module et trois de la suite complète.

---

## Lot L5 — ce qui est établi

| Critère d'acceptation du lot | Résultat |
|---|---|
| Aucun hook clavier dans le code | **Tenu**, vérifié par un test qui relit le code source de tous les modules |
| Aucune donnée sensible écrite | **Tenu**, vérifié en écrivant un vrai journal puis en le relisant |
| Matrice de contexte sur 8 scénarios | **Tenue**, et les cinq états du §11 sont tous atteignables |
| `brain` ne connaît pas `render` | **Tenu**, vérifié sur l'AST des imports, et un sous-process confirme que les capteurs s'importent sans charger Qt ni ModernGL |
| Polling à 4 Hz | **Tenu**, à 0,218 ms par cycle — soit 0,09 % d'un cœur |

### La vie privée est tenue structurellement, pas par bonne volonté

Le §3 interdit tout hook clavier, le §11 interdit titres de fenêtre, URL,
captures et frappes. Ces interdictions sont vérifiées par des tests qui
**relisent le code** et **relisent le journal** :

- aucun `SetWindowsHookEx`, `WH_KEYBOARD`, `GetAsyncKeyState`, `RegisterHotKey`…
- aucun `GetWindowText` — le titre est précisément là où vivent les URL ;
- aucun `BitBlt`, `PrintWindow`, `GetDIBits` ;
- le journal reçoit uniquement `SystemContext.redacted()`, et un test échoue si
  on y trouve `.exe`, `http://` ou un nom de process.

Le scan ignore commentaires et chaînes : les modules **documentent** ces
interdictions, et un scan naïf s'accrochait à sa propre documentation. C'est une
garde contre l'ajout accidentel, pas contre une dissimulation volontaire — un
appel construit dynamiquement passerait, et ce n'est pas le risque visé.

**Le seul mécanisme d'observation du clavier de tout le projet** est
`GetLastInputInfo`, qui donne l'instant de la dernière entrée sans jamais voir ce
qui a été tapé.

### Un bug que seule la mesure a révélé

`GetLastInputInfo` renvoyait une inactivité de **−4 294 967 secondes**.

`GetTickCount` retourne un `DWORD` non signé, que ctypes interprétait en signé
faute de `restype` explicite : au-delà de **24,8 jours d'uptime** le compteur
dépasse 2³¹ et repasse en négatif. La machine de dev en était à 42,8 jours.

La soustraction est désormais faite en arithmétique 32 bits masquée, ce qui
traite du même coup le **rebouclage complet à 49,7 jours** — que cette machine
aurait atteint une semaine plus tard.

### Les sessions audio ne peuvent pas être énumérées à 4 Hz

| Appel | Coût | Cadence retenue |
|---|---|---|
| `AudioUtilities.GetAllSessions()` | **28,1 ms** | toutes les 8 s |
| lecture des peak meters en cache | **0,21 ms** | 4 Hz |
| `GetLastInputInfo` | 0,0014 ms | 4 Hz |
| `GetWindowThreadProcessId` | 0,0022 ms | 4 Hz |
| `psutil.Process().name()` | 0,018 ms | mis en cache par PID |

Énumérer à 4 Hz aurait coûté **11 % d'un cœur**. Le capteur énumère donc
rarement et ne lit que les compteurs — 134 fois moins cher. C'est la troisième
fois sur ce projet qu'un appel système apparemment anodin domine le budget : les
deux précédents étaient `EnumDisplayDevicesW` et la relecture GPU.

La détection est également **collante** : un silence de dialogue ne remet pas le
compteur de lecture à zéro, sinon `watching` ne se déclencherait jamais.

### Le critère d'acceptation du §16 phase 4, réécrit

Signalé au cadrage du projet comme le point **D**, et confirmé : le critère
d'origine n'est pas atteignable.

> « `sit_and_watch` se déclenche de manière fiable pendant une vidéo YouTube et
> une vidéo locale, et pas sur de la musique de fond seule »

**WASAPI ne dit pas si un flux est une vidéo.** Côté son, YouTube et Spotify Web
sont indiscernables : même process, même session, même compteur. Aucune
implémentation ne peut satisfaire ce critère par l'audio seul.

Critère de remplacement, dont le comportement exact est fixé par 9 tests :

> `watching` se déclenche quand un média joue depuis au moins **20 s**, le
> curseur est immobile depuis au moins **6 s**, et l'une des conditions suivantes
> est vraie :
> - la source est un **lecteur vidéo connu** (VLC, mpv, MPC, Films & TV…),
>   quelle que soit la taille de sa fenêtre ;
> - la source occupe au moins **60 % du moniteur** — cas du navigateur, parce
>   qu'une vidéo se regarde en grand alors qu'une playlist tourne dans un onglet.
>
> Il ne se déclenche **jamais** sur un lecteur musical connu (Spotify, iTunes,
> foobar2000, AIMP, Deezer, Tidal).
>
> **Faux positif assumé** : une vidéo musicale regardée en plein écran est
> comptée comme une vidéo — ce qui est d'ailleurs défendable.

### Deux interprétations du §11, assumées

- **`watching` prime sur `idle` et `away`.** Ces deux états sont déduits d'une
  *absence* de preuve, alors qu'un média qui joue devant un curseur immobile est
  une preuve *positive* de présence. Un film de deux heures ne doit pas faire
  croire le pet abandonné.
- **Le curseur est échantillonné par le timer de hit-testing** (8–60 Hz selon la
  proximité), et non par un timer dédié à 60 Hz. Les deux ont besoin exactement
  de la même donnée, et un troisième timer coûterait des réveils sans rien
  apporter — ce qui compte pour l'autonomie (§3). Le 60 Hz est donc tenu là où il
  sert, quand le curseur est près du pet.

### Ce qui reste à valider de ton côté

La détection de `watching` est fixée par ses tests, mais la vérifier en vrai
demande une vraie vidéo. Lance le pet avec `--diag`, mets une vidéo en plein
écran dans le navigateur, et regarde la ligne `ctx` passer à `watching` ;
mets ensuite de la musique en petite fenêtre, elle doit rester `typing`.

---

## Correctifs après retour d'usage du lot L5

### Le pet passait sous les autres fenêtres

**Cause non identifiée**, et je le dis plutôt que de le supposer. Trois
hypothèses ont été testées en laboratoire, aucune ne reproduit le défaut : le
pet reste `WS_EX_TOPMOST` avec zéro fenêtre au-dessus après 120 bascules du
click-through, après activation d'une fenêtre rivale, et après un cycle
`hide()`/`show()`.

Le remède porte donc sur le **symptôme** : `assert_topmost` réaffirme le rang à
4 Hz par `SetWindowPos(HWND_TOPMOST)`, sans bouger ni activer la fenêtre. MSDN
est explicite — le rang Z ne se change que par `SetWindowPos`, et le drapeau de
style seul ne le garantit pas. Divers évènements du shell peuvent redescendre
une fenêtre sans toucher son style : bascule de bureau virtuel, sortie de
veille, application passant en plein écran sans bordure.

Coût mesuré : **0,174 ms**, soit 0,07 % d'un cœur à 4 Hz. Idempotent.

### `watching` ne se déclenchait jamais

Deux causes distinctes, toutes deux réelles.

**1. Le capteur de curseur gelait.** Il était alimenté par le timer de
hit-testing, qui **s'arrête** quand le pet se masque — c'est-à-dire précisément
pendant une vidéo en plein écran, le seul cas qui compte.
`cursor_still_seconds` restait donc bloqué sous les 6 secondes requises. La
vérification système à 4 Hz l'alimente désormais aussi, ce qui garantit qu'il
n'arrête jamais d'avancer.

**2. La source du son doit être l'application au premier plan.** Trouvé en
sondant le système réel, et c'est l'inverse du défaut attendu : le son venait de
Chrome, l'avant-plan était l'éditeur à 99 % de couverture, et le test de
couverture — qui porte sur l'avant-plan — aurait déclenché `watching` au bout de
20 secondes. **Travailler avec une vidéo derrière n'est pas regarder une
vidéo**, et sans cette condition les deux situations sont indiscernables.

Une exception nécessaire : une application du Store masque son process derrière
`ApplicationFrameHost`, donc le rapprochement par nom est impossible pour
« Films et TV ». Dans ce cas on retombe sur la liste des lecteurs vidéo connus.

Le critère complet est donc :

> `watching` se déclenche quand un média joue depuis **20 s**, le curseur est
> immobile depuis **6 s**, la source du son **est** l'application au premier plan
> (ou son hôte UWP), la source n'est pas un lecteur musical connu, et soit la
> source est un lecteur vidéo connu, soit sa fenêtre couvre au moins **60 %** du
> moniteur.

### La sonde de contexte

`tools/context_probe.py` affiche l'arbre de décision complet, seconde par
seconde, et nomme la condition qui manque. C'est elle qui a révélé le second
défaut ci-dessus — la lecture du code ne l'aurait pas donné, parce que le
symptôme était un faux positif et non un faux négatif.

---

## Lot L5b — locomotion

Lot intercalaire, hors du plan L0–L9. **Il étend le CDC** : le §6 ne prévoit que
le déplacement à la souris, et la locomotion autonome n'y est qu'implicite, dans
trois des neuf actions v1 du §12 — `idle_wander`, `follow_cursor` et
`sniff_around`. Fait avant le lot L6 parce que celui-ci va élire ces actions et
qu'il faut bien qu'elles fassent quelque chose.

| Critère d'acceptation du lot | Résultat |
|---|---|
| Aucun mouvement linéaire visible | **Tenu.** Dispersion de la vitesse mesurée sur toute la trajectoire, et forme de l'arc vérifiée parabolique |
| Ne sort jamais de la zone de travail | **Tenu** sur les 3 écrans réels, coordonnées négatives comprises |
| Franchissement de moniteur sans saut de hauteur | **Tenu.** Pas maximal mesuré sous 6 px, sur un dénivelé de 200 px |
| Cède à un glisser, sans bras de fer | **Tenu.** Repos de 2,5 s avant de pouvoir repartir |
| Revient près de son domicile | **Tenu** |
| Pas de va-et-vient | **Tenu.** Hystérésis sur la cible |
| Budget CPU à 30 fps | **Tenu** : +2 % d'un cœur |

### Le risque levé d'abord : déplacer une fenêtre par image

| | médiane | p90 | max |
|---|---|---|---|
| image sur place | 2,73 ms | 3,62 | 5,93 |
| image avec déplacement | 3,39 ms | 4,73 | **18,74** |
| dont `SetWindowPos` | 0,552 ms | 1,079 | **16,18** |

**+0,66 ms par image, soit 2 % d'un cœur à 30 fps.** Viable, mais la queue est
vilaine : un pic isolé à 16 ms sur un budget de 33, imputable à la recomposition
DWM d'une fenêtre translucide et topmost. Deux mitigations en place —
`SetWindowPos` n'est appelé que si la position **arrondie** a changé, et
uniquement pendant un trajet.

### Le saut, et pourquoi pas le glissement

Deux démarches sont implémentées, et le choix s'est fait sur la
chronophotographie, pas sur l'intuition :

- **`hop`** — accroupissement d'anticipation, arc parabolique, écrasement à
  l'atterrissage avec dépassement, courte pause. C'est la démarche par défaut.
- **`glide`** — vitesse de croisière plafonnée avec départ et arrivée adoucis.
  Sur la frise, il lit comme **un objet qu'on pousse** : un ruban continu, sans
  rythme. Conservé en option, il ne coûte que douze lignes.

Un robot sans jambes qui glisse ne ressemble pas à un être qui se déplace. Son
arc a un second mérite : il masque le dénivelé au franchissement d'un écran.

### Trois défauts trouvés par la frise, pas par la lecture

1. **Le glissement était une téléportation.** Un ressort de **position** va
   d'autant plus vite que la distance est grande — mesuré : 1440 px en 0,82 s,
   soit 1756 px/s. C'est l'inverse du comportement d'une marche. Il porte
   désormais sur la **vitesse**, plafonnée à une croisière.
2. **Les moniteurs adjacents laissaient un trou infranchissable.** En rentrant
   les bornes écran par écran d'une demi-largeur de pet, il subsistait entre deux
   écrans une bande de la largeur du pet où son centre ne pouvait pas se
   trouver — sur cette machine, de 1810 à 2030. Le saut la franchissait par
   chance, en progressant de 220 px à la fois ; le glissement s'y coinçait
   définitivement. Les écrans qui se touchent forment maintenant **une seule
   bande continue**, et le retrait ne s'applique qu'à ses extrémités : les trois
   écrans donnent une bande unique de 5 540 px.
3. **Le mouvement était trop discret** : arc de 0,20 hauteur à peine visible et
   inclinaison nulle à l'œil. Portée, arc et inclinaison relevés après la
   première frise.

Un garde-fou s'y est ajouté : un trajet qui ne progresse plus pendant 1,5 s est
**abandonné**. Défensif, mais c'est exactement ce qui manquait quand le
glissement se coinçait — un pet bloqué est pire qu'un pet qui renonce.

### Un test qui m'a accusé à tort

La première version du test de linéarité ne gardait que les images où le pet
avance, et concluait que le saut était linéaire. C'est vrai *à l'intérieur d'un
saut* — la vitesse horizontale d'un projectile est constante par définition — et
le filtre jetait justement les accroupissements et les pauses, c'est-à-dire tout
ce qui fait le rythme. La métrique porte désormais sur la trajectoire entière,
et une seconde assertion vérifie que l'arc est **parabolique et non
triangulaire**, sur le rapport de sa moyenne à son maximum : deux tiers pour une
parabole, une moitié pour une rampe.

### Le domicile

**Le dernier glisser de l'utilisateur définit le domicile**, et c'est **lui** qui
est persisté, jamais la position courante. Sans cette règle, la flânerie
écraserait en permanence la position que le lot L1 mémorise par moniteur, et
l'intention de l'utilisateur serait perdue au premier pas. La flânerie tire ses
cibles dans un rayon de 2,6 hauteurs de pet autour du domicile.

Le hasard de la flânerie vient de la **graine du génome**, comme le rythme des
clignements : le tempérament de déplacement fait partie de l'identité du robot,
et reste reproductible en test.

### Échafaudage, à retirer au lot L6

Sans comportement, rien ne choisit de cible. `--wander N` fait flâner le pet
toutes les N secondes, uniquement pour pouvoir juger la mécanique :

```bash
.venv/Scripts/python.exe -m pet.main --diag --wander 6
.venv/Scripts/python.exe -m pet.main --diag --wander 6 --gait glide
```

Le lot L6 remplacera ce déclencheur par une décision réelle, et ces deux
drapeaux disparaîtront.

---

## Lot L6 phase A — comportement

Le §12 en entier : besoins, élection par utilité, neuf actions v1, humeur. Livré
en phase A d'un lot en deux temps ; la phase B — carton de premier lancement,
nommage, bulle, menu de soin — arrive ensuite. L'ordre n'est pas arbitraire :
l'écran de statut *affiche* les besoins et le menu d'interactions les *modifie*,
donc bâtir l'interface d'abord aurait été bâtir sur du vide.

| Critère d'acceptation du lot | Résultat |
|---|---|
| Aucun clignotement entre actions | **Tenu.** Médiane d'épisode 15,2 s, p90 37,5 s, aucun épisode court hors réflexe ou interruption |
| Aucune action inatteignable ni dominante | **Tenu** sur la suite des trois profils : neuf actions jouées, maximum 43 % du temps de présence |
| Le `brain` est testable sans GPU | **Tenu.** Vérifié en sous-processus et par lecture de l'AST |
| L'économie inversée est respectée | **Tenu.** Chaque règle du §12 est un test séparé |
| Aucun état irréversible | **Tenu.** Un mois d'abandon est intégralement rattrapable |
| Le nom survit à un kill brutal | **Tenu**, par les écritures atomiques du lot L1 |
| Budget CPU | **Tenu** : le tick partage le timer des capteurs, aucun réveil ajouté |

### Le vrai risque était l'équilibrage, pas la technique

D'où l'ordre de fabrication : la journée synthétique **avant** les scorers. Elle
sert à régler, pas seulement à valider, et elle a trouvé cinq défauts qu'aucune
relecture n'aurait sortis.

1. **`look_around` était structurellement inatteignable.** Sa disponibilité
   demandait `idle_seconds >= 4`, or l'instrument remettait ce compteur à zéro à
   chaque tick de présence — irréaliste, un humain qui travaille marque des
   pauses en permanence. Défaut de l'instrument, pas du comportement, mais il
   masquait le suivant.
2. **`energy` ne décidait jamais rien.** Elle récupérait plus vite qu'elle ne se
   dépensait : sur une journée de bureau, jamais sous 68, moyenne 89. Le besoin
   existait pour rien et `nap` n'était déclenché que par l'état `away`, jamais
   par la fatigue. Dépense passée devant récupération, l'arc voulu est obtenu :
   pleine le matin, basse le soir.
3. **La flânerie était morte à 0,2 % de la journée.** `sniff_around` scorait
   toujours au-dessus. Le croisement est maintenant posé sur `fun` : sous 69
   points le pet part fouiner les bords, au-dessus il flâne. Chacune a sa niche,
   et la niche veut dire quelque chose.
4. **Le pet broyait du noir chaque matin.** `fun` perdait 9 pt/h en absence, soit
   67 points sur une nuit : l'utilisateur retrouvait un pet affaissé d'ennui tous
   les jours. C'est exactement la culpabilisation que le §12 interdit. Ramené à
   4 pt/h, une nuit coûte 30 points et la matinée les regagne.
5. **`follow_cursor` clignotait 101 fois par journée.** Voir plus bas — c'est le
   défaut le plus instructif du lot.

### La règle qui manquait : la disponibilité est grossière, le score est fin

`follow_cursor` conditionnait sa disponibilité à la distance au curseur. Une
grandeur continue et rapide : elle traverse la borne en pleine action, l'action
devient indisponible, et le plancher de durée est court-circuité — on ne peut pas
retenir une action devenue impossible. Résultat, 101 épisodes de moins d'une
seconde sur une journée, soit un pet qui vacille.

Les seuils continus appartiennent au **score**, où l'hystérésis les lisse ; la
disponibilité ne doit porter que des grilles stables, comme l'état du contexte.
Après correction : 18 épisodes courts, dont 17 sont le réflexe de clic, qui dure
0,62 s par construction.

### Trois mécanismes de durée, pour trois défauts différents

Ils se ressemblent et ne se remplacent pas :

- l'**hystérésis** du §12, +15 % à l'action en cours, empêche deux scores voisins
  d'alterner à chaque tick de 250 ms ;
- le **plancher** `min_seconds` empêche une action de ne durer que trois ticks
  quand un besoin franchit un seuil — ce que l'hystérésis ne couvre pas ;
- le **plafond** `max_seconds` et son repos forcé empêchent une action à score
  élevé et stable de monopoliser le pet. Un seul en porte un : à `fun` nul,
  `bored_slump` bat toutes les ambiances et un pet délaissé resterait affaissé
  pour toujours. Un plafond ailleurs couperait un comportement légitime — une
  nuit de sommeil, un film de deux heures.

S'y ajoute une dérogation, trouvée par un test en échec : un **réflexe traverse
le plancher**. Sans elle, un soin reçu pendant une sieste — plancher de six
secondes — n'était célébré qu'une éternité plus tard, et le pet paraissait sourd.

### Le bonus de nouveauté remplace le hasard

Les quatre actions d'ambiance se disputent une bande étroite autour de 0,3. Une
comparaison de scores quasi constants élit toujours la même : le pet aurait neuf
actions et n'en jouerait que trois. Chacune reçoit donc un bonus qui croît avec
le temps écoulé depuis sa dernière élection.

Un tirage aléatoire aurait fait le même travail, mais il rendrait la journée
synthétique irrejouable et ferait vibrer les scores à chaque tick. Le terme de
nouveauté est déterministe : c'est ce qui rend les deux critères d'acceptation
mesurables.

### Deux métriques que j'avais écrites fausses

Elles condamnaient toutes deux un comportement correct, et c'est le genre
d'erreur qui coûte le plus cher : on règle le produit pour satisfaire une mesure
qui a tort.

- **La domination**, mesurée sur l'horloge murale, accusait `nap` de dominer à
  91 % un profil où la machine tourne seule vingt-deux heures. Un pet laissé seul
  *doit* dormir. Le dénominateur est désormais le **temps de présence** : ce que
  le critère interdit, c'est un pet qui ne fait qu'une chose pendant qu'on le
  regarde.
- **Le clignotement** comptait tout épisode de moins d'une seconde. Dès que les
  réflexes ont pu traverser le plancher, il a accusé `follow_cursor` et
  `idle_wander` — alors qu'être interrompu par un clic est précisément ce qui
  doit arriver. La définition partagée vit maintenant dans `Report.flickers`, et
  écarte les réflexes **et** les épisodes qu'un réflexe termine.

### La convention des besoins, à lire avant tout le reste

Les quatre besoins sont des **niveaux de satisfaction** dans [0, 100], où 100
vaut « comblé ». `hunger` à 100 est donc un pet rassasié, pas un pet affamé.
C'est le §12 qui impose cette lecture en écrivant que « hunger et hygiene sont
les seuls à décroître dans le temps » : ce qui décroît est la satiété.

Toute l'économie tient dans une table de taux en points par heure, une ligne par
état du §11. Les valeurs se lisent comme des durées — `-4,3` pt/h vide la satiété
en vingt-trois heures — et c'est cette lecture qui les rend arbitrables autrement
qu'au doigt mouillé. Le critère d'acceptation « l'économie inversée est
respectée » se vérifie en lisant la table.

### Décisions tranchées

- **§17.4 — il dort vraiment.** `nap` gagne pendant `away`, et le retour de
  l'utilisateur déclenche `happy_bounce`. Les deux courbes existaient depuis le
  lot L4.
- **Décroissance hors ligne plafonnée à huit heures.** Une semaine de fermeture
  ne facture que huit heures d'absence. Revenir de vacances devant un pet à plat
  est exactement le mode d'échec culpabilisant que le §12 interdit. L'absence est
  facturée en état `away`, seule lecture honnête, et qui a le mérite de laisser
  `energy` remonter : le pet est retrouvé reposé.
- **Les délais de soin sont persistés.** Non par méfiance — le §14 est explicite
  sur l'inutilité de l'anti-triche — mais parce qu'un délai qui s'évapore à la
  fermeture est un bug, pas une politique. Ils s'écoulent sur la durée **réelle**
  de l'absence, sans plafond : le plafond protège les besoins, pas les délais.

### Deux défauts de lots antérieurs, trouvés en chemin

Aucun des deux n'appartient au lot L6, et les deux se voient dans le produit.

1. **Une fenêtre simplement maximisée était prise pour du plein écran**, donc le
   pet disparaissait. Sur un moniteur secondaire il n'y a pas de barre des
   tâches, la zone de travail égale le rectangle de l'écran, et le test
   géométrique du lot L5 ne distingue plus rien. Le discriminant a été mesuré, et
   il écarte l'idée évidente :

   | fenêtre | `IsZoomed` | `WS_CAPTION` |
   |---|---|---|
   | application à chrome propre, maximisée | 1 | 0 |
   | Qt plein écran | 0 | 0 |
   | fenêtre classique, maximisée | 1 | 1 |

   La barre de titre ne discrimine rien : une application Electron n'en a pas,
   même simplement maximisée. C'est `IsZoomed` qui sépare les deux cas, et lui
   seul. Limite assumée : un jeu en « maximisé sans bordure » ne masquera pas le
   pet — la moins mauvaise des deux erreurs.

2. **`Terrain.span` était une méthode au milieu de deux propriétés.** Je l'ai lue
   de travers en câblant le comportement, et le pet plantait au premier tick. Le
   plantage n'a été vu qu'en lançant l'application : aucun test ne faisait décider
   le `brain` depuis un vrai terrain, ils passaient tous un tuple. `span` est
   maintenant une propriété comme ses voisines.

### Ce qui reste ouvert

- **`fun` et `energy` saturent au plafond plusieurs heures par jour.** Un besoin
  collé à 100 ne porte aucune information. C'est du réglage de poids, donc du
  lot L9, et la journée synthétique est l'instrument pour le faire.
- **Le pet poursuit le curseur avec insistance** — 40 % du temps de présence.
  Charmant ou agaçant, cela ne se tranche qu'à l'usage.
- **`bored_slump` réutilise la pose assise.** Une courbe dédiée serait mieux ;
  celle du lot L4 rend l'état lisible, et l'écrire relève du polish.
- **Le clic droit quitte toujours.** Le menu de soin est la phase B.

### Échafaudage retiré, comme promis

`--wander` a disparu : c'est le `brain` qui choisit les cibles. `--gait` reste,
comme option de démarche.

---

## Lot L6 phase B — premier lancement et interface

Le §13 en entier, plus la séquence d'arrivée demandée en séance : un carton qui
tombe, un robot qui en sort, un nom à lui donner, et un panneau de soin à quatre
pages au clic droit. **Aucun texte dans l'application**, à deux exceptions près
et deux seulement — la saisie du nom et son affichage.

| Critère d'acceptation du lot | Résultat |
|---|---|
| Un cycle de soin complet fonctionne | **Tenu.** Nourrir, jouer, caresser, nettoyer, avec délais et animation de réponse |
| Aucun texte dans l'interface | **Tenu.** Vérifié sur la source, hors chaînes et commentaires |
| Le nom survit à un kill brutal | **Tenu**, par les écritures atomiques du lot L1 |
| Le nom est définitif | **Tenu.** Un second baptême est refusé |
| La fenêtre du pet ne grandit pas | **Tenu.** Le bord bas du robot ne bouge pas de plus de 6 px, quel que soit le bandeau |
| La boutique est présente et vide | **Tenu.** Bouton et page au lot L6, catalogue au lot L7 |
| Le panneau ne vole pas le focus | **Tenu.** Seule la page de nommage l'active |

### Le bandeau, et pourquoi la fenêtre n'a pas grandi

C'est toi qui as eu raison sur ce point, et mon cadrage initial était trop
pessimiste. Le sol est ancré sur le **bas de la fenêtre** —
`floor_y = bord bas de la zone de travail − hauteur de fenêtre` — donc réserver
de la place au-dessus du robot en le recadrant dans le bas du cadre ne déplace
pas cette équation d'un pixel. Mesuré, bandeau par bandeau :

| bandeau | haut du robot | bas du robot | hauteur |
|---|---|---|---|
| 0 % | 10 | 210 | 200 px |
| 13 % | 37 | 212 | 175 px |
| 26 % | 64 | 213 | 149 px |
| 40 % | 93 | 214 | 121 px |

Le bord bas ne bouge pas ; le robot perd 25 % de taille apparente à 26 %, valeur
retenue sur planche comparative. Les lots L1 et L5b sont intacts, et la surface
de relecture GPU est inchangée — agrandir la fenêtre aurait coûté 36 % de
relecture en plus pour un bandeau vide la plupart du temps.

En revanche `pet_h` désignait bien deux choses, et il a fallu les scinder : la
hauteur de **fenêtre** pour poser le sol, la hauteur de **corps** pour les
unités de démarche et les distances de score.

### Un vocabulaire de sigles, deux techniques

Les sigles de la bulle et des yeux sont des **SDF** dans un shader partagé par
les deux surfaces ; les icônes du panneau sont des **chemins vectoriels** tracés
par QPainter. Deux techniques pour un même langage, à garder cohérentes à la
main — les quatre icônes de besoin reprennent délibérément les formes du shader.

Le partage entre les deux shaders a demandé une inclusion GLSL, que le langage
n'a pas : `RenderContext._source` résout les `#include` par substitution
textuelle avant compilation. Vingt lignes, et la garantie que la bulle et les
yeux ne divergeront pas.

L'ordre des identifiants de sigles est un **contrat** entre `render/glyphs.py`
et `shaders/glyphs.glsl`, au même titre que l'ordre de `PARAMS` dans le génome :
le shader aiguille sur un entier, et décaler la table ferait afficher la goutte
à la place de la gamelle sans qu'aucune erreur ne soit levée. Un test compare
les deux listes.

### Cinq sigles refaits après les avoir regardés

Aucun n'a été jugé sur son code. Tous l'ont été sur planche, aux tailles réelles.

1. **`fun` était une balle** — un anneau barré d'une bande diagonale. Elle se
   lisait comme un **panneau d'interdiction**, soit exactement le contraire du
   message. Une forme qui peut se confondre avec un signe conventionnel connu
   est disqualifiée, quelle que soit son élégance. Remplacée par une étoile.
2. **`robot` avait une antenne** et des yeux évidés : à trente pixels, elle se
   lisait comme le bec d'un pot et eux comme une étiquette. Réduit à un carré
   arrondi et deux yeux — chaque détail ajouté enlevait de la lisibilité.
3. **`quit` était une flèche de rechargement.** L'ouverture de l'anneau faisait
   soixante-quatre degrés ; resserrée à vingt-six, elle redevient un bouton
   d'arrêt. Pour un bouton qui ferme l'application, c'était le pire contresens
   possible.
4. **`shop` était un cadenas.** Un sac à provisions — corps arrondi, anse en
   arc — n'a pas de silhouette propre à cette taille. Remplacé par une étiquette
   de prix, qui n'a pas de sosie dans ce jeu.
5. **`interactions` et `pet` partageaient une main**, donc deux boutons du même
   parcours portaient le même dessin, et la main se lisait comme un bouchon.
   Devenues une grille de quatre et un coeur.

Deux d'entre elles cachaient le même défaut technique : un `arcTo` ajouté à un
chemin **rempli** donne un camembert, pas un anneau. `QPainterPathStroker`
convertit le trait en contour fermé.

### La queue de la bulle pointait vers le ciel

Défaut trouvé en mesurant, pas en lisant : un dard de dix-sept pixels
**au-dessus** du corps de la bulle, largeurs 1, 4, 8, 11, 15 du haut vers le
bas. La cause était une double inversion — la projection orthographique de ce
projet inverse déjà l'axe Y, et je l'avais renversé une seconde fois.

Le même piège a mordu les sigles, et sa résolution est le vrai enseignement :
les deux surfaces qui affichent des pictogrammes n'ont **pas** le même sens de
y. La bulle est bâtie en pixels, qui descendent ; la dalle du visage en UV de
coque, qui montent. Un renversement unique à l'intérieur de `glyphDistance`
servait donc l'une et mettait l'autre en miroir. La convention est désormais
explicite — `+y` vers le haut à l'entrée — et **c'est à l'appelant de s'y
ramener**, en une ligne commentée de chaque côté.

J'ai perdu du temps à raisonner sur ces signes avant de me décider à les
mesurer. Le profil de silhouette ligne par ligne a tranché en une commande ce
que trois relectures n'avaient pas tranché.

### Les sigles des yeux sont dimensionnés sur la dalle, pas sur le génome

Première version : la taille des pupilles. L'arc du point d'interrogation
disparaissait. Deuxième version : la largeur de la dalle. Ils sortaient rognés
des deux côtés — la coque s'enroule sur le crâne, donc ses UV extrêmes sont vus
de biais ou cachés, et la surface utilisable est plus étroite que `uAspect` ne
le suggère.

Version retenue : **position sur les pupilles**, visibles par construction, et
**taille fixe**. La taille fixe a une seconde raison : `eye.size` varie du
simple au double d'un génome à l'autre, et un afficheur doit faire la même
dimension sur tous les robots.

### Le panneau : une seule source de géométrie

Tout est peint dans un `paintEvent`, et les clics sont testés contre la **même**
liste de rectangles qui a servi à peindre — `_layout` est appelée par la
peinture comme par le clic. Une hiérarchie de `QPushButton` stylés aurait
demandé autant de code pour un rendu moins maîtrisé, et surtout la géométrie
aurait existé en deux endroits. Deux calculs séparés finissent toujours par
diverger d'un pixel, et un bouton qui ne répond pas là où il est dessiné est un
défaut invisible en relecture. Un test vérifie que les trois chemins passent
bien par `_layout`.

**Le panneau ne prend pas le focus**, sauf la page de nommage. C'était le
troisième trou identifié au cadrage du projet, et il se résout mieux que prévu :
plutôt que de renoncer à `WS_EX_NOACTIVATE` pour tout le panneau, seule la page
qui a besoin d'un clavier appelle `activateWindow`. Un panneau qui vole le focus
interrompt ce que l'utilisateur était en train de taper, et c'est inacceptable
pour un logiciel de bureau permanent.

Le pet **cesse de flâner** tant que le panneau est ouvert : il rejoint le
glisser et la chute dans la règle de propriété de la position du lot L5b. Un
panneau qui court après un robot en mouvement serait illisible, et rester
tranquille quand on le regarde est de toute façon ce qu'il ferait.

### Le carton : un écart assumé par rapport au cadrage

Le cadrage annonçait un carton **modélisé dans le pipeline toon**, avec des
rabats articulés par le rig, et identifiait ce poste comme le plus incertain en
charge de toute la phase. Il l'était : maillage de caisse, quatre rabats dans un
rig, une seconde animation, et un second contexte ModernGL autonome.

Il est dessiné par QPainter, en polygones. L'argument qui plaidait pour le
pipeline toon était d'éviter une chaîne d'assets pour un seul écran — or du
tracé vectoriel n'est pas un asset : ni fichier, ni import, ni conversion. Et le
langage visuel s'y retrouve quand même, le rendu toon étant fait d'aplats et
d'un contour sombre, ce qu'un polygone tracé par Qt donne directement.

La fenêtre du carton est **petite et se déplace** plutôt que de couvrir l'écran :
un voile plein écran, même transparent, intercepterait les clics du bureau. Elle
descend comme le pet descend quand on le lâche.

Un défaut trouvé sur planche : **fermé, le carton avait les rabats en croix**,
sortant sur les côtés comme des ailes, parce que le signe de la rotation était
inversé. Fermé, un rabat pointe vers l'intérieur et rejoint son voisin au milieu
du couvercle ; au-delà de quatre-vingt-dix degrés le cosinus change de signe et
il repart de lui-même vers l'extérieur, ce qui donne le basculement complet sans
cas particulier.

### La séquence d'arrivée

Le repère du premier lancement est l'**absence de nom**, et non le drapeau
`first_run` du génome : le nom est ce qui manque vraiment tant que le baptême
n'a pas eu lieu, et ce repère survit à un plantage entre le tirage du génome et
la saisie.

1. Le pet est masqué, le carton tombe au milieu de l'écran et rebondit.
2. Au clic, les rabats s'ouvrent et le carton se dissipe. Le robot apparaît à sa
   place — **lâché**, pas posé : la chute du lot L1 le ramène au sol avec son
   écrasement à l'atterrissage.
3. Sa bulle porte un point d'interrogation, et rien d'autre : un robot qui
   réclamerait à manger avant d'avoir un nom mettrait deux demandes en
   concurrence.
4. Au clic sur la bulle, **deux sigles remplacent ses pupilles** — un robot et
   un point d'interrogation, « qui suis-je » — puis le champ de saisie s'ouvre.
5. Le nom validé, la boucle normale démarre.

La page de nommage a **son bouton de validation**, une coche. Dans une interface
sans texte, « appuyez sur Entrée » ne se devine pas ; la touche reste disponible
pour qui la connaît.

### Deux tests que j'avais écrits faux

Le premier est une **récidive** : mon test « aucun texte dans l'interface »
lisait la source brute et trouvait `QPushButton` dans la docstring qui explique
pourquoi le panneau n'en utilise pas. C'est exactement l'erreur que les tests de
vie privée du lot L5 avaient déjà commise sur leurs propres docstrings, et le
correctif était déjà écrit — `_code_only`, qui retire chaînes et commentaires.

Le second exigeait que les rabats montent de façon **monotone**, et accusait
donc l'ouverture complète. Un rabat qui pivote au-delà de la verticale redescend
un peu, et c'est ce qu'il doit faire : la propriété vraie est le basculement,
pas la montée.

### Ce qui reste ouvert

- **La boutique est vide.** Le bouton et la page sont là pour que la mise en
  page soit définitive ; les tokens, leur plafond quotidien et la détection de
  recul d'horloge sont le lot L7.
- **Le panneau ne se ferme pas au clic ailleurs.** Il se ferme par son retour,
  par un second clic droit, ou par Échap. Un clic sur le bureau le laisse
  ouvert : détecter ce cas demanderait soit de voler le focus, soit de surveiller
  la fenêtre de premier plan, et aucune des deux options n'est gratuite.
- **Le carton ne se voit qu'une fois.** Il n'y a pas de moyen de le revoir sans
  purger les données, ce qui rendra son réglage pénible au lot L9.

---

## Correctif de cadence, après le lot L6

Signalé par des utilisateurs : **plus la souris s'éloignait, plus le framerate
tombait.** C'était vrai, et pire que graduel — une falaise.

La seule chose qui maintenait les 30 fps était le curseur **dans la boîte du pet
élargie de 96 px**. Dès qu'il en sortait, plus rien ne sollicitait l'horloge, et
1,2 s plus tard le rendu passait à 10 fps. Sans intermédiaire.

**Défaut de conception, pas d'implémentation.** L'horloge adaptative du §3 date
du lot L1, quand le pet ne bougeait *que* si on le tirait : la proximité du
curseur était alors un bon proxy de « quelque chose se passe ». Depuis les lots
L5b et L6 il se déplace tout seul, et le proxy s'est inversé — ses mouvements les
plus spectaculaires ont lieu précisément quand on ne le survole pas. La preuve
était dans mes propres traces sans que je la lise : pendant la mise au point de
la locomotion, le pet faisait douze sauts et traversait un écran, et le
diagnostic affichait `idle 9.0 fps` du début à la fin.

Le critère est désormais le **mouvement effectif**, et non sa cause : comparer la
position arrondie d'une image à l'autre couvre d'un coup le glisser, la chute, la
flânerie et l'arc du saut, sans énumérer les sources. S'y ajoutent une courbe
d'animation en cours et les fondus de l'interface. La respiration et les
clignements, eux, ne sollicitent rien : le §3 fixe explicitement 10 fps pour le
repos, et c'est là qu'ils vivent.

| | avant | après |
|---|---|---|
| pet en trajet, curseur ailleurs | 9 fps | **30 fps** |
| pet immobile | 9 fps | 9 fps |
| CPU au repos | 0 à 2 % | 0 à 2 % — budget §3 tenu |
| CPU en mouvement | 1 à 2 % | 11 % |

### Une distinction qui n'existait pas

`ActionLayer.busy` dit qu'une action est **chargée**, pas qu'elle **bouge**, et
les deux diffèrent exactement sur les poses soutenues — `sit`, `sleep` — qui
tiennent leur pose finale indéfiniment. Branchée sur `busy`, la cadence gardait
30 fps pour un pet **endormi**. D'où `animating`, ajoutée à côté.

### Une fausse piste, et ce qu'elle a coûté

En mesurant, j'ai vu le régime interactif à 100 % et 11 % de CPU, et j'ai conclu
à une violation du §3. J'ai donc plafonné les deux ambiances de déplacement pour
forcer le pet à s'arrêter — ce qui a **cassé deux critères d'acceptation du lot**
que la phase A avait pourtant mesurés : médiane d'épisode tombée de 15,2 s à
7,0 s, et 132 changements par heure au lieu de 90.

Deux erreurs, et la seconde est la plus instructive.

D'abord, **le §3 ne budgète que le repos** : « CPU au repos, robot visible
< 4 % », et il prescrit par ailleurs « 30 fps en interaction » sans budget
associé. À 3,2 ms l'image, 10 fps coûtent 3,2 % et 30 fps en coûtent 10 —
autrement dit les deux lignes du §3 ne sont conciliables que si le repos est
vraiment le repos. Il l'est. Il n'y avait pas de violation.

Ensuite, la mesure était **biaisée par l'observateur** : je mesurais en
travaillant, donc le contexte était `typing` cent pour cent du temps, c'est-à-dire
exactement le cas où le §3 veut 30 fps. Corréler le régime avec le contexte —
et non avec le seul compteur de CPU — l'a montré en une commande.

Tout est revenu en arrière côté comportement, y compris la machinerie de
« groupe de repos » devenue morte. Reste ouverte une vraie question de produit,
qui n'est pas un défaut : **le pet doit-il flâner pendant qu'on travaille ?**
S'il le fait, l'application tient 30 fps la plupart du temps qu'on passe devant.
Le levier est la vivacité du comportement, pas la cadence, et il n'est pas à moi
de le tourner.

---

## Personnalisation, après le lot L6

Une cinquième icône au menu racine — trois godets de couleur — mène à une page de
pastilles : six couleurs de corps, quatre d'accent. **La couleur est pour
l'instant la seule variable modifiable sans token**, et cette page est glissée
*avant* la boutique : des deux pages qui touchent à l'apparence, la gratuite se
trouve la première.

### Le mécanisme existait déjà

`build(genome, overrides)` attendait ce moment depuis le lot L2, où sa docstring
annonçait : « le génome reste le trait de naissance, l'inventaire est un
costume ». Il n'y avait donc rien à inventer, seulement à brancher — un
dictionnaire `appearance` dans `state.json`, passé tel quel en `overrides`.

Trois conséquences de ce choix, et c'est ce qui le rend bon :

- **le génome n'est jamais muté.** Un test vérifie que `pet.json` est
  bit-à-bit identique après un changement de couleur ;
- **rien de choisi veut dire « la couleur de naissance »**, pas « aucune » : la
  coche se pose en relisant le génome, donc un pet neuf montre déjà sa teinte ;
- **la boutique du lot L7 ajoutera des lignes, pas un mécanisme.** Elle écrira
  dans le même dictionnaire.

Les clés acceptées sont **déclarées** (`CUSTOMISABLE`) et non déduites du
génome : un `overrides` qui prendrait n'importe quelle clé laisserait un fichier
édité à la main changer les proportions du robot, ce qui n'est plus une
personnalisation mais un autre robot.

### Deux détails d'exécution

Le robot est **reconstruit** à chaque choix plutôt que recoloré à chaud. La
couleur traverse la géométrie — teinte des parties, couleur des pupilles,
configuration de la passe toon — et les retoucher une par une reviendrait à
recopier `build`. Elle coûte 7 ms mesurées, une fois par clic. L'animateur est
refait avec, sinon le pet resterait figé dans la pose de repos de l'ancien.

Le panneau s'élargit de quatre à **cinq** boutons pour accueillir l'icône, et
toutes ses pages suivent : un panneau qui change de largeur en changeant de page
est fatigant. Les pastilles, elles, sont plus petites que les boutons — six sur
une ligne, et un grand aplat de couleur écraserait le reste de la page.

La coche de la pastille active est encrée en sombre ou en clair selon la
luminance de la couleur : les palettes vont du blanc cassé au magenta, et une
coche d'une seule teinte disparaîtrait sur la moitié d'entre elles.

---

## Passe d'expérience sur le premier lancement

Quatre corrections d'usage, après retours.

**Le carton part du haut de l'écran.** Il était lâché deux cent quarante pixels
au-dessus de sa cible, donc il apparaissait déjà à moitié descendu : pour entrer
dans le champ, il faut venir de hors-champ. Le départ est désormais calé sur le
bord de l'écran, et borné par la cible pour qu'un moniteur très haut placé ne
donne pas une chute interminable.

**Le robot bondit hors du carton, de côté.** Il en tombait, tout droit. La
nuance compte : le carton part en fondu, et sans élan propre le robot avait
l'air d'avoir été *découvert* là plutôt que d'être sorti tout seul. Le bond ne
coûte qu'une vitesse horizontale ajoutée à la chute du lot L1 — amortie, et
nulle pour toute autre chute, donc le lâcher à la souris est inchangé. Le côté
est choisi sur **la place disponible** et non tiré au hasard : bondir dans le
bord de l'écran pour s'y écraser aussitôt ne serait pas une sortie.

**Une petite scène muette remplace l'apparition sèche**, en quatre temps et
cinq secondes et demie :

| temps | phase | ce qui se passe |
|---|---|---|
| 0,0 s | `emerging` | il bondit hors du carton et retombe au sol |
| 1,4 s | `looking` | il balaie l'écran de gauche à droite, comme pour se repérer |
| 4,3 s | `surprised` | il vous voit droit devant, et sursaute |
| 5,7 s | `asking` | la bulle au point d'interrogation arrive |

Écrite comme une suite d'états plutôt qu'en minuteries enchaînées : chaque phase
sait ce qui la termine, donc l'ensemble se relit comme le scénario qu'il est. Le
**regard appartient à la scène** pendant les trois premières phases — le suivi
du curseur du lot L4 contrarierait à la fois le balayage et le face-à-face — et
lui revient à la quatrième.

**Le clic droit ne donne rien tant que le robot n'a pas de nom**, et la bulle se
retire dès que la saisie est ouverte. Le menu de soin parlerait d'un pet qu'on
n'a pas encore accueilli, et une bulle qui demande encore pendant qu'on répond
est du bruit.

### Deux choses trouvées en écrivant les tests

**Ma première mesure de durée était fausse.** La boucle de rendu prend son `dt`
de l'horloge réelle : une boucle serrée fait donc défiler mille images pour une
seconde de scène, et j'ai d'abord lu une phase d'émergence de 5,65 s là où elle
en dure 1,4. Les tests pilotent désormais la scène avec un `dt` **synthétique**.

**Un refus de nom bloquait l'utilisateur définitivement.** Le baptême ne se
terminait que si le nom venait d'être *accepté* ; un refus — nom déjà posé par
une autre voie — laissait `_onboarding` armé, donc plus jamais de clic droit et
rien pour s'en sortir. La condition porte maintenant sur le fait que le robot
**a** un nom, pas sur le succès du dernier appel.

---

## Les soins deviennent des objets

Le bouton qui soignait « par magie » est remplacé : nourrir, jouer et nettoyer
font **apparaître un objet au sol**, et le soin ne s'applique qu'une fois le
robot et l'objet réunis. Caresser reste direct — c'est le seul soin sans objet à
apporter, et en inventer un aurait été forcé.

### Une seule règle pour trois façons de faire

Le robot va le chercher tout seul, l'utilisateur porte le robot jusqu'à l'objet,
ou il traîne l'objet jusqu'au robot. Les trois sont **le même test de distance
entre deux centres**, donc il n'y a aucun cas particulier à écrire. C'est ce qui
rend le mécanisme petit : tout le reste existait déjà — la locomotion sait aller
à un `x` depuis le lot L5b, et une petite fenêtre translucide déplaçable est ce
que fait le carton depuis la phase B.

Le `brain` gagne une action, `fetch_item`, qui **passe devant le film mais
derrière les réflexes** : poser un objet est un geste délibéré de l'utilisateur
et doit être vu, mais un clic reste prioritaire. Il ne sait rien de l'objet — ni
ce que c'est, ni à quoi il ressemble, juste qu'il y a quelque chose à aller
chercher et où.

### Le soin se fait en deux temps

`start_care` pose le **délai** sans appliquer le gain, `deliver_care` applique le
gain. La séparation est nécessaire : le délai doit courir dès l'apparition de
l'objet — sinon rien n'empêche d'en semer dix — alors que le besoin ne monte
qu'au contact. Et `refund_care` rend le délai si l'objet s'évapore sans avoir été
rejoint : faire payer une tentative ratée serait une punition, que le §12
interdit.

### Un bug qui aurait doublé chaque soin, en silence

L'animation de disparition passe en `gone` dans l'image même où elle se termine.
La fenêtre, qui ne testait que `consumed` et `expiring`, retombait alors dans son
test de proximité et appelait une seconde fois la délivrance — mesuré :
`hunger` montait de 20 à 100 au lieu de 66, sans qu'aucune erreur ne le signale.

L'invariant vit maintenant **sur l'objet** : `consume()` ne rend vrai qu'une
fois. C'est le bon endroit, parce que la propriété porte sur lui et non sur la
séquence d'appels de qui le regarde.

### Les sprites, découverts par préfixe

Onze PNG de 256 × 256 dans `pet/assets/items/`, découverts par `food_*`,
`toy_*`, `clean_*`. Aucune table, aucun manifeste : ajouter une variété de
nourriture au dossier suffit à l'obtenir en jeu. Le tirage **évite de resservir
le précédent**, parce que le hasard pur répète et que deux repas identiques
d'affilée se remarquent bien plus qu'une série variée ne se savoure.

Ceux livrés sont des bouche-trous générés par `tools/make_items.py`, et le
contrat de composition qu'ils respectent vaut pour leurs remplaçants : le **bas
du dessin est la ligne de contact avec le sol**, sans quoi l'objet flotte.

Deux détails d'intégration réutilisent l'existant plutôt que d'ajouter :
l'objet est traversant par défaut et cliquable seulement là où son sprite est
opaque, piloté par le **timer de survol du pet** pour ne pas ajouter de réveil
(§3) ; et il est positionné en pixels physiques comme le pet, parce que la
proximité se mesure entre deux centres et que mélanger les deux espaces de
coordonnées la fausserait sur un montage à DPI mixtes.

### Réglages

Un seul objet à la fois — deux gamelles simultanées demanderaient au pet un
choix dont il n'y a rien à tirer. Apparition entre deux et six largeurs de pet,
du côté où il y a de la place. Portée de contact généreuse, à 0,72 largeur de
pet : rater son objet de trois pixels après l'avoir traîné à travers l'écran
serait une punition. Évaporation au bout de trois minutes.

---

## Le regard suit ce qui compte

Le pet ne regardait que le **curseur**, toujours. Il fixait donc la souris
pendant qu'il marchait vers sa gamelle, et pendant qu'une vidéo jouait à l'autre
bout de l'écran. La cible est désormais résolue par une liste de priorités, en
un seul endroit — deux résolutions finiraient par diverger, comme toute
géométrie tenue à deux exemplaires.

| priorité | il regarde | quand |
|---|---|---|
| 1 | le curseur | on le tient |
| 2 | l'objet | il a décidé d'aller le chercher |
| 3 | **où il veut** | coup d'oeil de curiosité |
| 4 | la fenêtre active | une vidéo joue |
| 5 | le caret, sinon la fenêtre | on écrit |
| 6 | le curseur | le reste du temps |

La bascule entre cibles est gratuite : les trois ressorts décalés du lot L4 —
regard, tête, corps — font glisser le tout sans qu'on ait rien à lisser.

### Le coup d'oeil inventé

C'est la seule cible qui ne vienne de rien d'observable : le pet la **décide**,
et c'est précisément ce qui la rend vivante. Un regard qui ne fait que suivre
des choses existantes reste réactif ; un regard qui part de lui-même vers un
coin de l'écran suggère une intention — comme s'il essayait d'attirer l'attention
ailleurs.

Trois réglages le tiennent du côté de la curiosité plutôt que de la distraction,
et ils sont mesurés : environ **quatre coups d'oeil par minute**, chacun tenu
entre 1,2 et 2,6 s, soit 14 % du temps. Chacun vise un point **assez loin** —
2,2 largeurs de pet au minimum — sans quoi la tête ne tourne pas et le geste ne
se voit pas, et dans la **moitié haute** de l'écran : un regard levé suggère
qu'il a vu quelque chose, un regard baissé ne raconte rien.

Le hasard vient d'une graine dérivée du génome, comme le rythme des clignements
du lot L4 : le tempérament d'attention appartient à l'identité du robot, et
reste reproductible en test.

### Ce que ça lit, et ce que ça ne lit pas

Les points 4 et 5 touchent à d'autres applications, donc ils méritent d'être
explicites. `foreground_window_center` ne prend qu'un **rectangle** — ni titre,
ni classe, ni contenu — et le §11 n'interdit que les titres. Le caret vient de
`GetGUIThreadInfo`, qui interroge l'état déjà publié par le thread actif
**sans installer aucun hook**, exactement comme `GetLastInputInfo` interroge
l'horloge d'inactivité : l'interdiction du §3 tient.

Le caret rend `None` souvent, et c'est attendu : beaucoup d'applications
modernes dessinent le leur sans le publier. Le repli sur le centre de la fenêtre
rend la dégradation invisible.

Le shell est écarté comme ailleurs — fixer la barre des tâches parce qu'on a
cliqué sur le bureau n'aurait aucun sens — et le point visé est placé un peu
au-dessus du centre géométrique de la fenêtre, le contenu utile d'une vidéo ou
d'un texte étant rarement dans sa moitié basse.

---

## Le fouinage traversait tous les écrans

Signalé à l'usage : le pet faisait cinq ou six sauts d'un côté, puis autant pour
revenir, sans fin. Diagnostiqué en corrélant l'action élue avec la cible de
déplacement et la distance à parcourir.

| action | trajets | distance médiane | maximum |
|---|---|---|---|
| `sniff_around` | 8 | **3 532 px** | 4 468 |
| `follow_cursor` | 15 | 683 px | 1 380 |
| `idle_wander` | 7 | 379 px | 810 |

Le coupable saute aux yeux dès qu'on met les trois côte à côte. Le §12 dit
« fouine près du bord de **l'écran** », au singulier ; j'avais implémenté le bord
du **terrain**, c'est-à-dire la bande praticable fusionnée — sur un montage à
trois moniteurs, 5 540 px. Le retour au domicile de la flânerie fournissait le
second aller, et le va-et-vient s'installait.

La cible est désormais le bord de l'écran courant, bornée par le terrain — un
écran peut déborder de la bande praticable à ses extrémités. Mesuré après
correctif : **395 px** de trajet médian pour `sniff_around`, soit un facteur
neuf, et une amplitude totale de 1 766 px sur soixante-dix secondes au lieu de
trois écrans.

Rien n'a bougé côté comportement : seule la **résolution** de l'intention de
déplacement a changé, pas son élection. L'histogramme d'actions du lot L6 est
inchangé, et c'est la bonne façon de corriger ce genre de symptôme — le `brain`
avait raison de vouloir fouiner, c'est la fenêtre qui traduisait mal.

---

## Lot L7 — économie, boutique et réglages

Trois briques, retenues avec l'utilisateur : les tokens, un rayon de chapeaux,
et un écran de réglages portant la réinitialisation.

| Critère d'acceptation du lot | Résultat |
|---|---|
| L'idle infini n'est pas la stratégie optimale | **Tenu** par le plafond quotidien du §14 |
| Un recul d'horloge ne rapporte rien | **Tenu.** La clé du jour doit être strictement postérieure |
| Le quota survit à une fermeture | **Tenu**, persisté avec le solde |
| Un article ne se paie qu'une fois | **Tenu.** Achat et port sont deux gestes séparés |
| Les chapeaux coiffent toutes les morphologies | **Tenu** sur cinq génomes, cotes en parts de tête |
| La réinitialisation ne part pas d'un clic | **Tenu.** Appui maintenu deux secondes |
| Le génome n'est jamais touché | **Tenu**, vérifié par test |

### Le plafond fait tout le travail

Un token par soin, comme convenu. Mais les délais de soin ne suffisent pas à
tenir le rythme : caresser revient toutes les deux minutes, soit trente tokens
par heure, et l'article le plus cher tomberait en deux heures de clics. Le
plafond quotidien du §14 est la vraie régulation — **25 par jour**, donc deux
jours pour la couronne à 50 et une journée pour le nœud à 5.

Le token est versé **à la livraison du soin**, pas au clic du bouton. Depuis que
trois soins sur quatre passent par un objet posé sur le bureau, créditer au
bouton laisserait faire apparaître dix gamelles sans jamais en livrer une.

Sur la triche, le §14 est explicite : « ne pas investir dans du chiffrement ou
de la signature ». La détection de recul d'horloge tient donc en une
comparaison — la clé du jour doit être **strictement postérieure** à celle
enregistrée, donc reculer la date ne rouvre pas le quota. Avancer l'horloge
d'un jour reste payant, et c'est assumé : l'application est gratuite, hors
ligne, sans classement, à récompenses purement cosmétiques.

### Les chapeaux sont de la géométrie

Un chapeau est fait de superellipsoïdes greffés sur le nœud `head` du rig. Il
traverse donc la passe toon, le contour et l'ombre comme le reste du robot, et
il suit la tête sans une ligne de code — **aucun nœud de rig n'est ajouté**. Un
sprite aurait demandé une chaîne d'assets et une orientation à recalculer à
chaque image, pour un résultat qui aurait juré.

Toutes les cotes sont exprimées en **parts des demi-dimensions de la tête**, et
c'est la seule façon de tenir : les crânes varient du simple au double d'un
génome à l'autre, et une cote posée à l'oeil sur un robot trapu déborde sur un
robot élancé. Deux tests le vérifient sur cinq morphologies — aucun chapeau ne
s'enfonce dans le crâne, aucun ne lévite au-dessus.

Sept articles, de 5 à 50 tokens : nœud, bonnet, casquette, chapeau de fête,
haut-de-forme, casque, couronne. Rien de neuf côté stockage — `appearance["hat"]`
est le même dictionnaire que les couleurs, et `inventory` attendait dans
`state.json` depuis le lot L6.

### Le rayon montre le vrai robot

Les vignettes de la boutique sont des **rendus en trois dimensions sur le robot
de l'utilisateur**, avec ses couleurs, et non des icônes dessinées. L'utilisateur
voit exactement ce qu'il achète, et cela évite d'entretenir sept dessins de plus
dans un vocabulaire qui en compte déjà vingt-deux. Huit vignettes coûtent une
soixantaine de millisecondes à l'ouverture du rayon, puis rien : le cache n'est
vidé qu'au changement d'apparence.

Le robot réel est remis en place à la fin du rendu des aperçus. La scène n'a
qu'un maillage à la fois, et la laisser sur le dernier chapeau essayé
remplacerait le pet à l'écran.

**Un seul geste pour acheter et porter.** Toucher un article qu'on ne possède
pas l'achète et le met aussitôt ; toucher un article possédé le porte. Séparer
les deux aurait demandé deux boutons par vignette dans une interface sans texte,
donc deux icônes de plus à distinguer pour rien.

### La règle du sans-texte, précisée

L'arrivée des prix a forcé à trancher : « jamais de texte » visait les **mots**,
c'est-à-dire des libellés qu'il faudrait traduire et qui vieillissent. Un prix
et un solde sont des **chiffres**, universels, et les rendre en pastilles serait
illisible dès dix jetons.

La règle est donc : aucun mot, et du chiffre uniquement là où le chiffre **est**
l'information. Le nom du robot reste la seule chaîne de caractères affichée. Le
test a été réécrit pour vérifier exactement cela — trois méthodes de peinture
ont le droit d'appeler `drawText`, et deux d'entre elles ne formatent que des
nombres.

### Réinitialiser sans pouvoir demander confirmation

Le geste est irréversible et l'interface n'a pas de texte : aucune boîte de
dialogue ne peut demander « êtes-vous sûr ». La durée en tient lieu — le bouton
doit être **maintenu deux secondes**, avec un anneau qui se remplit autour de
l'icône. Sans ambiguïté, et impossible à déclencher par accident.

La purge efface **tout**, tokens et inventaire compris : une réinitialisation
partielle n'en serait pas une. Elle a lieu **après** la fermeture de la fenêtre
et de ses fichiers — sous Windows un journal encore ouvert n'est pas
supprimable, et une purge qui laisse des restes n'en est pas une non plus.

Le lancement au démarrage écrit dans `HKCU\...\Run`, jamais `HKLM` : celui-là
demande l'élévation et inscrit pour tous les comptes de la machine, ce qui serait
disproportionné pour un animal de compagnie. L'échec est silencieux — une
stratégie de groupe peut verrouiller la clé, et planter pour ça serait démesuré.

---

## Un objet consommé pendant qu'on le tient

Signalé à l'usage : en traînant un objet jusqu'au robot, la consommation
démarrait, ne finissait pas, et l'objet restait posé sur le bureau sans plus
jamais pouvoir être absorbé.

La cause tient à l'**ordre des événements**. La proximité déclenche pendant que
le bouton de la souris est encore enfoncé ; le relâchement qui suit appelait
`release`, qui écrasait l'état « consommé » par « en chute ». L'objet retombait,
se posait, et comme il était déjà marqué mangé il n'était plus consommable — il
restait là pour toujours.

Le symptôme ne se voyait qu'avec le **panneau ouvert**, et cette circonstance
était trompeuse : le panneau n'y est pour rien. C'est qu'un pet immobilisé par
le panneau fait de « traîner l'objet jusqu'à lui » la façon naturelle de faire,
alors qu'en temps normal c'est le robot qui vient chercher — et il n'est alors
tenu par personne.

Le correctif est un **invariant** plutôt qu'un cas particulier : une fois
consommé, aucune manipulation ne peut plus atteindre l'objet. `grab_at`,
`drag_to` et `release` s'y refusent, et `consume` lâche la prise d'office. Sept
tests le tiennent, dont un qui vérifie que le cycle normal — attraper, déplacer,
relâcher — n'a pas bougé d'un pixel.

---

## Des titres et des infobulles

La règle « aucun texte dans l'application », tenue depuis le lot L6, est **levée
à la demande de l'utilisateur**. Chaque page porte un titre, chaque bouton une
infobulle. Le gain d'usage est net : une grille de quatre carrés ne dit pas
« interactions » tant qu'on ne l'a pas survolée une première fois.

Le statut est le seul écran sans titre — sa pastille d'humeur, le nom du robot
et ses quatre barres se suffisent, et un titre y répéterait ce que la page
montre déjà. Le menu racine porte le **nom du robot** en guise de titre : c'est
sa page d'accueil, et aucun libellé générique ne dirait mieux où l'on se trouve.

### Ce que la contrainte laisse derrière elle

Deux choses, et la première est un bénéfice inattendu. Les icônes ayant été
dessinées pour **se suffire**, le texte les précise au lieu de les porter : rien
n'a eu à être redessiné, et l'interface reste lisible si l'infobulle n'apparaît
pas.

La seconde est une dette à tenir : l'interface devient **traduisible**. Tous les
libellés vivent donc dans une table unique en tête de `panel.py` — titres,
infobulles, noms d'articles — et un test lit l'AST pour vérifier qu'aucune
méthode de peinture ne contient de chaîne d'affichage écrite en ligne. Sans
cette discipline prise tout de suite, une localisation future demanderait de
relire tout le fichier.

Les infobulles d'apparence sont **construites à la volée** plutôt que tabulées :
une entrée par couleur et par chapeau serait une table à tenir à jour à chaque
ajout d'article, donc une table qui finirait par mentir.

---

## Des emplacements, pas des chapeaux

La boutique gagne une seconde famille d'articles — les moustaches — et c'est
l'occasion de généraliser ce qui était écrit pour une seule. `hats.py` devient
`cosmetics.py` : garder le nom aurait été un mensonge dès la première moustache,
et le renommage ne coûte que six imports.

La généralisation tient en une notion, l'**emplacement**. Chaque article en
occupe un, chaque emplacement se porte indépendamment des autres, et
`SLOTS` est la source unique dont dérivent les pages du rayon, les clés
acceptées dans `state.json` et la validation du costume. Ajouter une famille —
lunettes, écharpe — revient à ajouter une entrée à `SLOTS` et des articles au
catalogue : le panneau construit sa navigation tout seul.

Deux ancrages suffisent pour l'instant, parce qu'ils correspondent aux deux
endroits où l'on pose quelque chose sur une tête :

| ancrage | origine | pour |
|---|---|---|
| `crown` | sommet du crâne | chapeaux |
| `face` | centre de la tête, face avant | moustaches |

Les pièces restent **alignées sur les axes**, sans rotation : `Part` ne porte
qu'un décalage, et lui ajouter une rotation aurait touché l'assembleur et le rig
pour des formes qu'on obtient très bien en empilant des ellipsoïdes.

**Une moustache ne monte jamais sur la dalle du visage.** C'est la seule surface
expressive du robot, et la masquer même en partie lui coûterait plus qu'une
moustache ne lui apporte. Un test le vérifie sur cinq morphologies, en même
temps qu'il vérifie qu'elle est bien en avant du crâne — sans quoi elle s'y
noierait.

### La navigation du rayon

Le rayon a maintenant une racine de catégories et une page par emplacement. Elle
ne se justifierait pas pour une seule catégorie ; elle rend la suivante gratuite,
et c'était tout l'objet de la demande.

Le retour depuis un rayon remonte **aux catégories**, pas au menu : essayer deux
chapeaux demanderait sinon de retraverser tout le panneau à chaque fois.

Les aperçus gardent ce qui est porté sur les **autres** emplacements : on voit le
robot tel qu'il sera, chapeau et moustache ensemble, et non l'article seul sur
une tête nue.

### La profondeur d'une moustache ne se pose pas à l'oeil

Signalé à l'usage : la moustache se confondait avec la géométrie de la tête.
La cote de profondeur était à `0,82·head_c`, choisie au jugé — et c'était
inévitable de se tromper, parce qu'il n'existe pas de bonne valeur unique.

À la hauteur d'une moustache, un demi-rayon sous le centre, la surface d'un
crâne **rond** a déjà reculé à environ `0,89·head_c`, alors qu'un crâne
**cubique** y est encore à `1,0`. Une valeur réglée pour l'un noie la pièce chez
l'autre. Portée à `0,95`, elle ressort franchement sur les crânes ronds et reste
encastrée sur les cubiques : son dos demeure sous la peau dans les deux cas,
donc elle ne flotte jamais non plus.

Un test compare désormais la face avant de chaque pièce à la **peau calculée
pour la morphologie en cours**, sur toute la plage d'exposants — et vérifie dans
le même mouvement qu'elle n'a pas basculé dans l'excès inverse.

La moustache à guidon avait un second défaut, indépendant : ses pointes étaient
placées **au-dessus** de la barre, si bien qu'elles se lisaient comme deux
antennes partant vers le ciel. Redescendues sous la barre et élargies, elles
lisent comme les extrémités épaissies qu'elles doivent être.

### Un test que j'avais généralisé trop vite

Celui qui vérifiait qu'aucun article ne s'enfonce dans le crâne s'est mis à
parcourir tout le catalogue après le renommage — et il a accusé les moustaches,
qui sont sous le sommet du crâne **par construction**. Il est désormais séparé
par ancrage : les articles de tête au-dessus du crâne, les moustaches sous les
yeux et en avant.

---

## Lot L8 — exécutable, icône et installateur

Objectif fixé : de quoi envoyer le produit à un premier testeur. Le nom était
déjà en place — `APP_NAME = "Desky"` depuis le lot L0, tout en dérive.

| Critère | Résultat |
|---|---|
| Exécutable `onedir`, sans console, icône | **Tenu.** 147 Mo installés |
| Données lues à l'exécution embarquées | **Tenu**, et vérifié par le script de production |
| Installateur sans élévation UAC | **Tenu.** 40,8 Mo, installation vérifiée |
| Démarrage automatique décoché par défaut | **Tenu** |
| Chaîne reproductible | **Tenu.** `tools/build.py`, 45 s de bout en bout |
| L'application se lance depuis l'installation | **Non vérifiable ici** — voir plus bas |

### Le piège du gel, corrigé avant qu'il ne morde

Deux dossiers sont lus **à l'exécution** : les shaders GLSL et les sprites
d'objets. PyInstaller suit les imports, pas les `open()`, et leurs chemins se
résolvaient par `Path(__file__).parent` — qui désigne, une fois gelé, un chemin
dans l'archive. L'application se construit alors sans une erreur et refuse
d'afficher son robot **chez le testeur**.

Corrigé par un résolveur explicite, `pet/resources.py`, qui suit `sys._MEIPASS`
quand il existe. Un test lit l'AST de tout le paquet et refuse tout autre usage
de `__file__` pour un chemin de données ; le script de production compte en plus
les fichiers réellement embarqués et échoue s'il en manque. Deux filets, parce
que ce défaut ne se voit qu'en aval de tout ce qu'on sait tester.

### L'icône est rendue par le moteur

Pas dessinée à côté : elle est produite par le pipeline du produit, donc exacte
par construction et automatiquement à jour si le rendu évolue. Un robot de face,
regard droit, sans le bandeau de bulle — il n'y a pas de bulle sur une icône, et
le supprimer rend le robot plus grand dans le carré, ce qui compte beaucoup à
seize pixels.

**Un `.ico` est un lot de tailles, pas une image redimensionnée.** Chacune des
sept est rendue à sa résolution — puis réduite depuis le double, pour que
l'anti-aliasing du contour tienne — parce que laisser Windows réduire un seul
256 donne une bouillie dans la barre des tâches.

### Ce que la machine de développement a appris

Le §15 annonce que « les binaires PyInstaller non signés sont massivement
bloqués ». C'est arrivé **ici**, avant même d'atteindre un testeur, et le
diagnostic est plus fin que prévu :

| cas | résultat |
|---|---|
| exe **signé**, fraîchement copié | tourne |
| exe **non signé**, déjà présent sur le disque | tourne |
| notre exe, **neuf et non signé** | refusé, sans aucune boîte de dialogue |

Ni « non signé » ni « fichier neuf » ne suffisent : c'est leur conjonction, la
signature d'une protection par réputation. `Get-MpPreference` échoue avec
0x800106ba, donc Defender n'est pas aux commandes — une protection tierce gère
ce poste, joint à Azure AD.

**L'installateur, lui, passe.** Il s'exécute, pose 271 fichiers et 144,5 Mo,
crée son désinstalleur. Seuls les binaires qu'il dépose sont ensuite refusés au
lancement sur cette machine.

À distinguer de SmartScreen, que l'on rencontre sur une machine **personnelle** :
là, un avertissement franchissable en deux clics. C'est la différence entre
« pénible » et « impossible », et elle décide à qui on peut envoyer le produit
aujourd'hui.

### Deux contournements, écrits plutôt que redécouverts

La même protection bloque l'**écriture de ressources** dans un PE — icône,
manifeste, informations de version — avec l'erreur 110. PyInstaller s'en sort en
réessayant vingt fois ; Inno Setup abandonne au premier échec. D'où la
compilation de l'installateur dans le dossier temporaire, puis la copie du
résultat.

Et la version ne vit qu'à un endroit, `pet/__init__.py` : elle est passée à Inno
Setup en ligne de commande, jamais recopiée dans le script. Un test le vérifie,
parce que deux numéros de version finissent toujours par diverger et que celui
de l'installateur est le seul que l'utilisateur verra.

### Ce qui reste du §15

La **signature de code**, le **repli GPU** — la boîte d'erreur existe mais n'a
jamais été éprouvée sur une machine sans OpenGL 3.3 — et le **check de version**,
qui sera la seule sortie réseau du projet.

---

## Périmètre

Présent : `pet/main.py`, `pet/app/{win32,window,clock}.py`,
`pet/anim/{rig_pose,layers,locomotion}.py`,
`pet/brain/{sensors,needs,utility,actions,brain,session,trace,replay}.py`,
`pet/ui/{icons,panel,unboxing,item}.py`, `pet/render/{bubble,glyphs}.py`,
`pet/assets/items/*.png`,
`pet/genome/{schema,generator,migration}.py`,
`pet/geometry/{proportions,superellipsoid,rig,builder}.py`,
`pet/render/{context,scene,toon,outline,shadow,face}.py` et ses shaders,
`pet/state/save.py`, `tests/`,
`tools/{contact_sheet,face_sheet,explore_designs,anim_strip,context_probe,
loco_strip,day_sim,bubble_sheet,icon_sheet,panel_sheet,make_items}.py`.

Absent, et volontairement : le comportement (**L6** — le contexte est calculé
mais **rien ne l'utilise encore** : aucune action n'est choisie, les besoins
n'existent pas), l'interface de soin et l'économie (**L7**), le packaging et la
signature (**L8**), le tuning (**L9**).

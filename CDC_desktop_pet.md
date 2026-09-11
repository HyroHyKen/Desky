# Cahier des charges — Desktop Pet robotique procédural

**Plateforme cible :** Windows 10/11 (x64)
**Langage :** Python 3.11+
**Modèle de distribution :** exécutable gratuit téléchargeable depuis un site web, 100 % hors-ligne
**Statut du document :** spécification d'implémentation destinée à un agent de développement

---

## 1. Vision produit

Un compagnon robotique qui vit en surimpression sur le bureau. Il n'est pas dessiné : sa géométrie est **générée par algorithme au lancement**, à partir d'un génome propre à chaque installation. Chaque utilisateur possède donc un robot morphologiquement unique (tête plus grosse, corps plus allongé, oreilles plus écartées, etc.).

Il observe passivement l'activité du poste et y réagit. Un clic ouvre une interface de soin de type Tamagotchi. Les soins génèrent des tokens, dépensables en cosmétiques et en objets d'interaction (balle, lit, gamelle).

**Esthétique de référence :** robotique douce, plastique blanc mat, proportions de nourrisson, visage réduit à deux pupilles lumineuses cyan sur une dalle sombre. Rendu en **toon shading** (équivalent de `MeshToonMaterial` de Three.js) avec contour noir.

> Contrainte d'identité : ne pas reproduire la silhouette d'un produit commercial existant. Le langage visuel est repris, la forme est propre au projet.

---

## 2. Périmètre

### Inclus en v1
- Fenêtre transparente sans bordure, toujours au premier plan, cliquable uniquement sur le robot
- Génération procédurale de la géométrie depuis un génome persistant
- Pipeline de rendu toon avec contour par inverted hull
- Visage animé (clignement, direction du regard, expressions)
- Suivi du curseur par la tête et les pupilles
- Détection du contexte système (activité, fenêtre au premier plan, lecture audio/vidéo)
- Machine comportementale avec besoins (faim, amusement, énergie, propreté)
- Interface de soin
- Économie de tokens et persistance locale
- Installateur signé

### Exclu de la v1
Tout LLM ou SLM, local ou distant. Toute communication réseau autre que la vérification de version. Le multi-plateforme. Le son émis par l'application. Les objets d'interaction (balle, lit) sont spécifiés mais implémentés en v1.1.

---

## 3. Contraintes non négociables

| Contrainte | Valeur cible | Motif |
|---|---|---|
| CPU au repos, robot visible | < 4 % d'un cœur | Une app de bureau permanente qui chauffe est désinstallée |
| RAM résidente | < 150 Mo | Idem |
| Framerate | 30 fps en interaction, 10 fps en idle, 0 quand masqué | Autonomie sur portable |
| Hook clavier global | **interdit** | Faux positifs antivirus, perception de keylogger |
| Contenu des frappes | **jamais lu ni stocké** | Confiance |
| Sortie réseau | aucune hors check de version | Confiance |
| OpenGL minimum | 3.3 core | Compatibilité GPU intégrés |
| Démarrage à froid | < 3 s | Perception de légèreté |

La détection d'activité clavier passe **exclusivement** par `GetLastInputInfo()`, qui renvoie le temps écoulé depuis la dernière interaction utilisateur sans installer aucun hook. Croisé avec le delta de position du curseur, il permet de distinguer « tape », « bouge la souris » et « absent ». C'est suffisant pour tout le gameplay spécifié.

---

## 4. Stack technique imposée

| Rôle | Choix | Alternative rejetée et pourquoi |
|---|---|---|
| Fenêtre et UI | **PySide6** | tkinter : pas d'alpha par pixel sur Windows, seulement du color-key, donc bords crénelés. PyQt6 : licence GPL ou commerciale, incompatible avec une monétisation future |
| Rendu 3D | **ModernGL** en contexte standalone, rendu offscreen dans un FBO | `QOpenGLWidget` + `WA_TranslucentBackground` : instable sur Windows. Panda3D / Ursina : s'approprient la boucle principale, fenêtre transparente pénible |
| Maths | **numpy** | — |
| API Windows | **ctypes** sur `user32`/`kernel32` | pywin32 : dépendance lourde et bruyante au packaging |
| Sessions audio | **pycaw** | — |
| Process | **psutil** | — |
| Packaging | **PyInstaller** en mode `onedir` | `onefile` : décompression à chaque lancement, démarrage lent, davantage flaggé par les antivirus |
| Installateur | **Inno Setup** | — |

---

## 5. Architecture

```
pet/
  main.py                  # bootstrap, single-instance mutex, DPI awareness
  app/
    window.py              # fenêtre translucide, compositing QPainter, hit-testing
    win32.py               # wrappers ctypes (flags, GetLastInputInfo, monitors)
    clock.py               # boucle de rendu, framerate adaptatif
  genome/
    schema.py              # définition et bornes des paramètres, version de schéma
    generator.py           # PRNG déterministe seed -> génome
    migration.py           # migration de schéma sans altérer les pets existants
  geometry/
    superellipsoid.py      # primitive paramétrique
    builder.py             # assemblage du robot depuis un génome
    rig.py                 # hiérarchie de transformations
  render/
    context.py             # contexte ModernGL standalone + FBO RGBA
    toon.py                # passe principale
    outline.py             # passe inverted hull
    face.py                # rendu du visage (SDF en shader)
    shaders/*.glsl
  brain/
    needs.py               # décroissance et saturation des besoins
    utility.py             # scoring et sélection d'action
    actions/               # une action = préconditions + scorer + animation
    sensors.py             # agrégateurs de contexte système
  anim/
    rig_pose.py            # poses, interpolation, ressorts amortis
    layers.py              # superposition idle / look-at / action
  ui/
    care_panel.py          # interface Tamagotchi
    shop.py
  state/
    save.py                # persistance atomique
    economy.py             # accrual et dépense de tokens
```

**Séparation stricte à respecter :** `brain` ne connaît pas `render`. Il produit un état symbolique (`action="sit"`, `mood="curious"`, `look_target=(x,y)`) que `anim` traduit en poses. Cela permet de tester le comportement sans GPU.

---

## 6. Fenêtre et interaction

### Création
Fenêtre `QWidget` avec les flags `FramelessWindowHint | WindowStaysOnTopHint | Tool`. Le flag `Tool` la retire de la barre des tâches et de l'alt-tab. Attribut `WA_TranslucentBackground`.

Styles étendus Win32 à appliquer via `SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ...)` :
- `WS_EX_NOACTIVATE` (0x08000000) — ne vole jamais le focus
- `WS_EX_TOOLWINDOW` (0x80)
- `WS_EX_TRANSPARENT` (0x20) — géré dynamiquement, voir ci-dessous

### Hit-testing par alpha
**Ne pas utiliser `setMask()` par frame** : reconstruire une `QRegion` depuis un bitmap à chaque image est coûteux.

Méthode retenue : la fenêtre est click-through par défaut (`WS_EX_TRANSPARENT` actif). Un timer à 60 Hz appelle `GetCursorPos()`, convertit en coordonnées locales, et lit l'alpha du buffer rendu à ce pixel. Si alpha > 0.15, retirer `WS_EX_TRANSPARENT` ; sinon le remettre. Le robot devient cliquable exactement sur ses pixels opaques, sans coût de masque.

### Compositing
Le FBO est lu en `RGBA8` **prémultiplié**, converti en `QImage(Format_RGBA8888_Premultiplied)` et dessiné par `QPainter.drawImage()`. Le blending GL doit être `glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)` pour produire de l'alpha prémultiplié, faute de quoi les bords présentent un liseré noir.

### Comportements système
- **Multi-écran :** position mémorisée par identifiant de moniteur, repositionnement si l'écran disparaît
- **DPI :** `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`, taille de rendu multipliée par le facteur d'échelle du moniteur courant
- **Plein écran exclusif :** si la fenêtre au premier plan couvre tout le moniteur, masquer le robot et suspendre le rendu
- **Instance unique :** mutex nommé via `CreateMutexW`
- **Déplacement :** glisser le robot le déplace ; il retombe et se recale sur le bord bas de l'écran (notion de « sol »)

---

## 7. Génome et génération procédurale

### Principe
Le génome est un vecteur de paramètres nommés, borné, stocké en JSON **avec ses valeurs explicites et un numéro de version de schéma**. Il n'est pas stocké sous forme de seed seule : si le schéma évolue, le robot d'un utilisateur existant ne doit pas être régénéré différemment.

À la première exécution, un `seed` aléatoire alimente un `random.Random` dédié qui tire chaque paramètre dans ses bornes, puis les valeurs sont figées dans le fichier de sauvegarde.

### Paramètres (valeurs indicatives, à ajuster au tuning)

| Paramètre | Plage | Effet |
|---|---|---|
| `head.radius` | 0.85 – 1.35 | Taille de tête |
| `head.squash_y` | 0.80 – 1.20 | Aplatissement vertical |
| `head.exponent_n1` / `n2` | 0.35 – 1.0 | Sphère (1.0) → cube arrondi (0.35) |
| `body.height` | 0.7 – 1.6 | Élancement |
| `body.width` | 0.75 – 1.25 | Corpulence |
| `body.taper` | 0.7 – 1.15 | Rapport épaules/base |
| `neck.length` | 0.0 – 0.35 | 0 = tête posée sur le corps |
| `ear.type` | enum | `none` \| `antenna` \| `disc` \| `fin` |
| `ear.spread` / `ear.size` | 0.6 – 1.4 | — |
| `face.plate_ratio` | 0.55 – 0.85 | Proportion de la dalle sur la tête |
| `eye.spacing` / `eye.size` / `eye.corner_radius` | — | Identité du regard |
| `palette.body` | choix pondéré | Blanc cassé dominant, teintes pastel rares |
| `palette.accent` | choix pondéré | Cyan dominant, ambre et magenta rares |

**Règle de cohérence :** après tirage, appliquer un passage de validation qui rejette les combinaisons non viables (tête plus large que le corps × 1.8, oreilles intersectant la dalle faciale) et retire dans ce cas. Le charme naît de la variation contrôlée, pas du chaos.

### Primitive : superellipsoïde
Une seule formule couvre sphère, cube arrondi et capsule, ce qui maximise la variété morphologique pour un coût minimal :

```
x = a · sgn(cos v)|cos v|^n1 · sgn(cos u)|cos u|^n2
y = b · sgn(cos v)|cos v|^n1 · sgn(sin u)|sin u|^n2
z = c · sgn(sin v)|sin v|^n1

u ∈ [-π, π], v ∈ [-π/2, π/2]
```

Générer en numpy sur une grille (32 × 24 suffit), calculer les normales analytiquement plutôt que par moyennage de faces, et téléverser en VBO une seule fois. La géométrie est régénérée **uniquement** au changement de génome, jamais par frame.

### Assemblage
Le robot est un **assemblage de parties rigides distinctes** liées par une hiérarchie de transformations, et non un maillage unifié. Les jointures visibles sont assumées : c'est le vocabulaire du hard-surface robotique. Ce choix est aussi ce qui rend l'animation possible.

> Piste écartée pour la v1 : SDF avec union lisse et marching cubes. Plus organique mais empêche l'animation par parties, alourdit le maillage et coûte un re-meshing.

---

## 8. Rendu toon

Caméra **orthographique**. Elle donne une silhouette stable, évite la distorsion de perspective sur un objet proche et rend l'épaisseur du contour constante sans compensation.

### Passe principale
Équivalent fonctionnel de `MeshToonMaterial` : diffus lambertien quantifié par une rampe de dégradé, enrichi d'un spéculaire dur et d'un rim light pour l'aspect plastique brillant.

```glsl
float ndl  = dot(N, L);
float ramp = clamp(ndl * 0.5 + 0.5, 0.0, 1.0);
vec3  base = texture(uGradientMap, vec2(ramp, 0.5)).rgb * uBaseColor;

// spéculaire dur, seuillé mais anti-aliasé
float s    = pow(max(dot(N, H), 0.0), uShininess);
float spec = smoothstep(0.48, 0.52, s);

// rim light
float rim  = smoothstep(uRimStart, uRimEnd, 1.0 - max(dot(N, V), 0.0));

vec3 color = base + spec * uSpecColor + rim * uRimColor;
```

`uGradientMap` : texture 1D de 4 à 6 pixels, filtrage `GL_NEAREST`, wrap `GL_CLAMP_TO_EDGE`. C'est ce filtrage nearest qui produit les paliers nets caractéristiques.

### Passe de contour — inverted hull
Rendre chaque partie une seconde fois avec `glCullFace(GL_FRONT)` et les sommets déplacés le long de leur normale de `uOutlineWidth`, en couleur plate sombre, test de profondeur actif.

Cette méthode est imposée sur une alternative post-process de détection de bords : elle ne requiert ni depth buffer ni normal buffer supplémentaires, et surtout elle se comporte correctement contre un fond **transparent**, là où une détection de contours produirait des artefacts sur tout le pourtour de la silhouette.

### Ombre de contact
Une ellipse floutée en alpha, rendue sous le robot, dont l'opacité et le rayon suivent sa hauteur. Élément peu coûteux et déterminant pour l'ancrage visuel.

---

## 9. Visage

Le visage n'est **pas** de la géométrie. C'est un quad légèrement bombé, enfant de la tête, dont le fragment shader dessine les yeux par SDF (rectangles arrondis, capsules), en émissif non éclairé, avec un léger halo additif.

Uniformes de contrôle, tous animables :

| Uniforme | Rôle |
|---|---|
| `uBlink` | 0 → 1, écrasement vertical de la paupière |
| `uGaze` | vec2, décalage des pupilles |
| `uLidTop` / `uLidBottom` | Occlusion haute/basse → colère, somnolence |
| `uSquint` | Plissement → joie, méfiance |
| `uPupilScale` | Dilatation → surprise, affection |
| `uGlitch` | Bruit de balayage horizontal → réveil, saturation |

Une **expression** est un jeu nommé de ces valeurs. Les transitions sont interpolées, jamais instantanées. Ce shader unique remplace des centaines de sprites et se pilote entièrement depuis le comportement.

---

## 10. Animation

### Rig
`root → body → neck → head → {face, ears}`. Transformations locales composées par une traversée simple. Pas de skinning, pas de squelette pondéré : des parties rigides suffisent et coûtent presque rien.

### Couches, appliquées dans cet ordre
1. **Idle procédural** — respiration (sinusoïde sur l'échelle Y du corps), oscillation lente, clignements à intervalles pseudo-aléatoires, micro-saccades du regard. Cette couche tourne en permanence et porte l'essentiel de l'illusion de vie.
2. **Look-at** — la tête s'oriente vers le curseur par **ressort amorti** (raideur et amortissement paramétrés, pas d'interpolation linéaire), angle borné à ±55° en lacet et ±35° en tangage. Au-delà, le corps pivote avec retard. Les pupilles atteignent la cible avant la tête.
3. **Action** — courbes de pose nommées pour les animations discrètes : `sit`, `stand`, `yawn`, `look_around`, `poke_reaction`, `sleep`, `celebrate`.

**Exigence de qualité :** aucune interpolation linéaire sur un mouvement visible. Tout passe par de l'easing ou des ressorts, avec anticipation avant les mouvements marqués et léger dépassement à l'arrivée. Le charme du produit se joue à ce niveau, pas dans l'architecture.

---

## 11. Capteurs système

Tous les capteurs sont interrogés par polling à 4 Hz et n'exposent au `brain` que des **agrégats**.

| Signal | API | Sortie |
|---|---|---|
| Activité utilisateur | `GetLastInputInfo()` | secondes depuis dernière interaction |
| Mouvement souris | `GetCursorPos()` à 60 Hz | position, vitesse, distance au robot |
| Fenêtre active | `GetForegroundWindow()` + `GetWindowThreadProcessId()` + psutil | nom du process, catégorie |
| Plein écran | rect fenêtre vs rect moniteur | booléen |
| Lecture média | pycaw, sessions WASAPI + peak meter par process | booléen `media_playing` + process source |

**Dérivation du contexte :**
- `typing` = interaction récente sans déplacement du curseur
- `browsing` = interaction récente avec déplacement du curseur
- `idle` = plus de 90 s sans interaction
- `away` = plus de 10 min
- `watching` = `media_playing` vrai depuis plus de 20 s, curseur immobile

Catégorisation du process au premier plan par listes (`dev`, `browser`, `media`, `game`, `office`, `other`), extensible par fichier de config.

**Interdictions explicites :** aucun titre de fenêtre stocké sur disque, aucune URL, aucune capture d'écran, aucune frappe. Le journal de debug ne contient que des catégories.

---

## 12. Comportement — utility AI

Pas d'arbre de comportement, pas de machine à états monolithique. Chaque tick de 250 ms :

1. Mise à jour des besoins (`hunger`, `fun`, `energy`, `hygiene`), chacun dans [0, 100]
2. Chaque action candidate expose `is_available(context)` et `score(needs, context) -> float`
3. L'action de score maximal est élue, avec **hystérésis** (l'action en cours reçoit un bonus de 15 % pour éviter le clignotement entre décisions)
4. L'action élue publie un état symbolique consommé par `anim`

### Règle de conception de l'économie de besoins — impératif

Les besoins **ne décroissent pas linéairement avec le temps**. Ils sont majoritairement alimentés par ce que l'utilisateur fait déjà :

- `fun` monte quand le contexte est `typing` ou `browsing` (il est stimulé par l'activité)
- `energy` remonte pendant `idle` et `away` (il se repose quand tu n'es pas là)
- `hunger` et `hygiene` sont les seuls à décroître dans le temps, lentement, et sont les vecteurs du soin actif

**Aucune mort, aucun état irréversible, aucune notification punitive.** Un besoin bas change son humeur et son animation, jamais plus. Un logiciel de bureau permanent qui culpabilise se fait désinstaller ; c'est le mode d'échec principal de ce genre de produit.

### Actions v1
`idle_wander`, `follow_cursor`, `sit_and_watch` (déclenchée par `watching`), `nap`, `look_around`, `sniff_around` (fouine près du bord de l'écran), `react_to_poke`, `bored_slump`, `happy_bounce`.

---

## 13. Interface de soin

Clic gauche sur le robot → panneau `QWidget` ancré près de lui, sans bordure, arrondi, dans la même palette.

- Quatre jauges de besoins avec libellé d'état textuel plutôt que chiffré
- Actions de soin : nourrir, caresser, jouer, nettoyer. Chacune avec cooldown, effet sur les besoins, et animation de réponse
- Solde de tokens
- Boutique : cosmétiques (palettes, matières, types d'oreilles, styles de regard) et objets (balle, lit, gamelle — v1.1)
- Onglet réglages : position et taille, lancement au démarrage (`HKCU\...\Run`), fréquence d'apparition, bouton de purge des données
- Un écran informatif listant exactement ce qui est mesuré et ce qui ne l'est pas

Clic droit → menu contextuel : masquer 1 h, réglages, quitter.

---

## 14. Économie et persistance

**Accrual :** les tokens sont versés pour la présence effective et le soin, avec un **plafond quotidien** pour que l'idle infini ne soit pas la stratégie optimale. Utiliser une horloge monotone en complément de l'horloge système, et détecter les reculs d'horloge (pas de crédit rétroactif).

**Emplacement :** `%LOCALAPPDATA%\<AppName>\` contenant `pet.json` (génome), `state.json` (besoins, tokens, inventaire), `settings.json`, `debug.log`.

**Écritures atomiques :** écrire dans un fichier temporaire puis `os.replace()`. Sauvegarde toutes les 60 s et à la fermeture propre.

**Sur la triche :** l'application est gratuite, hors-ligne, sans classement, et les récompenses sont purement cosmétiques. Un utilisateur qui édite son JSON ne lèse personne. **Ne pas investir dans du chiffrement ou de la signature de sauvegarde.** Un simple champ de version et une validation de bornes au chargement suffisent.

---

## 15. Distribution

- PyInstaller `onedir`, sans console, icône fournie
- Installateur Inno Setup, portée utilisateur (pas d'élévation UAC), option de lancement au démarrage décochée par défaut
- **Signature de code obligatoire.** Les binaires PyInstaller non signés sont massivement bloqués par SmartScreen et les heuristiques antivirus. Azure Trusted Signing est l'option abordable. Sans signature, le taux d'abandon à l'installation sera rédhibitoire
- Vérification de version : une seule requête GET vers un JSON statique au lancement, échec silencieux, désactivable
- Fallback GPU : si la création du contexte OpenGL 3.3 échoue, afficher un message clair au lieu de crasher. Évaluer un repli ANGLE si des retours remontent des machines virtuelles

**Poids et empreinte attendus :** 90 à 160 Mo installés, 80 à 130 Mo de RAM résidente. Acceptable, non brillant. Si l'empreinte devient bloquante après validation du concept, la réécriture cible serait C#/WPF (~25 Mo de RAM, fenêtre transparente native), avec réutilisation directe du génome, des shaders et de la logique comportementale.

---

## 16. Plan de livraison

Chaque phase se termine sur ses critères d'acceptation avant de passer à la suivante.

### Phase 0 — Spike de faisabilité *(à faire avant tout le reste)*
Fenêtre translucide, sans bordure, always-on-top, affichant une sphère toon rendue par ModernGL en offscreen et composée par `QPainter`.

**Acceptation :** bords anti-aliasés sans liseré noir ; les clics passent au travers hors de la sphère et l'atteignent dessus ; la fenêtre ne prend jamais le focus ; CPU < 4 % à 30 fps ; fonctionne sur un GPU intégré Intel.

*Cette phase valide le risque technique principal. Si elle échoue, tout le reste est à revoir.*

### Phase 1 — Génome et géométrie
Superellipsoïde paramétrique, assemblage hiérarchique, génération depuis un génome, sérialisation.

**Acceptation :** un même seed produit toujours la même géométrie, vérifié par test unitaire ; 20 seeds tirés produisent 20 robots visuellement distincts et tous viables ; la régénération complète prend moins de 200 ms.

### Phase 2 — Rendu
Passe toon, contour inverted hull, ombre de contact, visage SDF.

**Acceptation :** contour d'épaisseur uniforme sous toutes les rotations ; paliers de dégradé nets ; visage pilotable par uniformes ; 30 fps stables.

### Phase 3 — Vie
Rig, couches d'animation, ressorts amortis, look-at curseur, boucle idle.

**Acceptation :** le suivi du curseur paraît naturel et non mécanique ; aucune interpolation linéaire visible ; le robot reste intéressant à regarder plus de 60 s sans aucune interaction.

### Phase 4 — Contexte et comportement
Capteurs, dérivation du contexte, besoins, utility AI, actions v1.

**Acceptation :** `sit_and_watch` se déclenche de manière fiable pendant une vidéo YouTube et une vidéo locale, et pas sur de la musique de fond seule ; aucun clignotement entre actions ; aucun hook clavier dans le code ; le `brain` est testable sans GPU.

### Phase 5 — Interface et économie
Panneau de soin, boutique, persistance, réglages.

**Acceptation :** un cycle complet de soin fonctionne ; les tokens sont plafonnés ; les données survivent à un kill brutal du process ; la purge des données est effective.

### Phase 6 — Packaging
Build, installateur, signature, page de téléchargement.

**Acceptation :** installation propre sur une machine Windows 11 vierge ; aucun avertissement SmartScreen ; désinstallation sans résidu ; démarrage à froid sous 3 s.

---

## 17. Décisions restées ouvertes

1. **Taille de rendu par défaut** — proposition : 220 px de haut, réglable de 120 à 400
2. **Type d'oreilles** — cosmétique déblocable ou trait génétique figé
3. **Contour** — épaisseur fixe ou trait génétique (un robot « à gros trait » a une identité forte)
4. **Somnolence** — s'endort-il vraiment quand tu es absent, ou reste-t-il éveillé pour te faire signe au retour
5. **Nom** — l'utilisateur nomme-t-il son robot au premier lancement (fort attachement, mais une étape d'onboarding en plus)

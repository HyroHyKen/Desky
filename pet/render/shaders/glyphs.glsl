// Vocabulaire de sigles, en SDF. Inclus par `bubble.frag.glsl` et par
// `face.frag.glsl` : la bulle dit ce que le pet veut, et les yeux l'affichent en
// grand quand on clique dessus. Un seul jeu de formes pour les deux, sinon les
// deux surfaces finiraient par ne plus se ressembler.
//
// **L'ordre des identifiants est un contrat** avec `pet/render/glyphs.py`,
// exactement comme l'ordre de `PARAMS` en est un avec le générateur de génome.
// Insérer un sigle au milieu décalerait tout ce que la bulle affiche.
//
// Chaque sigle est dessiné dans le carré [-1, 1]², trait compris, et rend une
// distance signée. Aucune texture, aucun sprite : le §9 prescrit ce shader
// unique « piloté entièrement depuis le comportement », et un pictogramme n'est
// rien d'autre qu'une expression de plus.

#define GLYPH_NONE     0
#define GLYPH_HUNGER   1
#define GLYPH_FUN      2
#define GLYPH_ENERGY   3
#define GLYPH_HYGIENE  4
#define GLYPH_ROBOT    5
#define GLYPH_QUESTION 6

const float GLYPH_FAR = 1e4;

// -- primitives -------------------------------------------------------------

float gCircle(vec2 p, float r) {
    return length(p) - r;
}

float gBox(vec2 p, vec2 b, float r) {
    r = min(r, min(b.x, b.y));
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

float gCapsule(vec2 p, vec2 a, vec2 b, float r) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - r;
}

float gRing(vec2 p, float r, float w) {
    return abs(length(p) - r) - w;
}

// Arc centré sur +y, demi-ouverture `ap`, rayon `ra`, demi-épaisseur `rb`.
// C'est la forme classique : au-delà de l'ouverture, la distance est celle de
// l'extrémité, ce qui donne des bouts francs au lieu d'un anneau tronqué.
float gArc(vec2 p, float ap, float ra, float rb) {
    vec2 sc = vec2(sin(ap), cos(ap));
    p.x = abs(p.x);
    float d = (sc.y * p.x > sc.x * p.y) ? length(p - sc * ra)
                                        : abs(length(p) - ra);
    return d - rb;
}

// Triangle isocèle pointant vers +y, demi-base `b`, hauteur `h`. Trois
// demi-plans : exact, et moins cher qu'une distance à trois segments.
float gTriangleUp(vec2 p, float b, float h) {
    float flanc = h * abs(p.x) + b * p.y - b * h;
    return max(max(flanc / sqrt(h * h + b * b), -p.y - 0.0), -1e4);
}

// Losange, demi-axes `r`. Distance approchée — le facteur d'échelle ramène le
// gradient près de 1 — ce qui suffit pour un masque anti-aliasé par `fwidth`.
float gDiamond(vec2 p, vec2 r) {
    return (abs(p.x) / r.x + abs(p.y) / r.y - 1.0) * min(r.x, r.y);
}

// Quadrant, pour retrancher un quart de plan. Nécessaire dès qu'une forme
// est **asymétrique** : `gArc` replie x sur sa valeur absolue, donc tout ce
// qu'il dessine est symétrique par construction, et un point d'interrogation
// ne l'est pas.
float gQuadrant(vec2 p, vec2 coin, vec2 sens) {
    return max(sens.x * (p.x - coin.x), sens.y * (p.y - coin.y));
}

float gUnion(float a, float b) { return min(a, b); }
float gCut(float a, float b) { return max(a, -b); }
float gClip(float a, float b) { return max(a, b); }

// -- sigles -----------------------------------------------------------------

// Faim : une gamelle **pleine**.
//
// La première version était un simple demi-disque sous une barre, et elle se
// lisait comme une colline ou un coucher de soleil : un récipient vide n'a pas
// de silhouette propre. Trois éléments la sauvent — un bord large, une cuve
// nettement plus étroite que lui, et un petit tas qui dépasse par-dessus. C'est
// le tas qui dit « de la nourriture », et le rétrécissement qui dit « un
// récipient » plutôt qu'un dôme.
float gHunger(vec2 p) {
    float bord = gCapsule(p, vec2(-0.84, 0.12), vec2(0.84, 0.12), 0.13);

    // Cuve : moitié basse d'une ellipse plus large que haute, resserrée vers
    // le fond. `gClip` garde l'intersection, donc on lui passe le demi-plan.
    vec2 cuve_p = vec2(p.x / 1.30, p.y);
    float cuve = gClip(gCircle(cuve_p - vec2(0.0, 0.12), 0.56), p.y - 0.12);

    // Tas de nourriture : moitié haute d'une ellipse plus petite que le bord.
    vec2 tas_p = vec2(p.x / 1.15, p.y);
    float tas = gClip(gCircle(tas_p - vec2(0.0, 0.12), 0.42), 0.12 - p.y);

    return gUnion(gUnion(cuve, bord), tas);
}

// Amusement : une étoile à quatre branches, deux losanges croisés.
//
// La première version était une balle — un anneau barré d'une bande
// diagonale. Sur planche, elle se lisait comme un **panneau d'interdiction**,
// soit exactement le contraire du message. Une forme qui peut se confondre avec
// un signe conventionnel connu est disqualifiée, quelle que soit son élégance.
float gFun(vec2 p) {
    return gUnion(gDiamond(p, vec2(0.28, 0.94)),
                  gDiamond(p, vec2(0.94, 0.28)));
}

// Énergie : une pile. Boîtier arrondi et sa borne, plus lisible qu'un éclair,
// dont les pointes disparaissent au premier anti-aliasing.
float gEnergy(vec2 p) {
    float corps = gBox(p - vec2(0.0, -0.08), vec2(0.42, 0.62), 0.16);
    float borne = gBox(p - vec2(0.0, 0.62), vec2(0.17, 0.14), 0.06);
    float creux = gBox(p - vec2(0.0, -0.30), vec2(0.22, 0.20), 0.07);
    return gCut(gUnion(corps, borne), creux);
}

// Hygiène : une goutte. Disque en bas, triangle en haut, soudés.
float gHygiene(vec2 p) {
    float bas = gCircle(p - vec2(0.0, -0.22), 0.56);
    float haut = gTriangleUp(p - vec2(0.0, -0.22), 0.56, 1.05);
    return gUnion(bas, haut);
}

// Robot : sa propre tête. Sert au baptême du premier lancement, à côté du point
// d'interrogation — « qui suis-je ».
// Robot : sa propre tête, réduite à ce qui la rend reconnaissable — un carré
// arrondi et deux yeux. L'antenne de la première version se lisait comme le
// bec d'un pot, et les yeux évidés comme une étiquette : à trente pixels de
// côté, chaque détail ajouté enlève de la lisibilité au lieu d'en donner.
float gRobot(vec2 p) {
    // Yeux **ronds** et non en fentes verticales : à trente pixels, deux barres
    // évidées dans un rectangle se lisent comme une étiquette ou une fenêtre,
    // alors que deux disques déclenchent immédiatement la lecture « visage ».
    // Les vraies pupilles du pet sont des capsules ; c'est une icône, pas un
    // portrait.
    float tete = gBox(p - vec2(0.0, 0.04), vec2(0.78, 0.62), 0.28);
    float oeil_g = gCircle(p - vec2(-0.30, 0.10), 0.17);
    float oeil_d = gCircle(p - vec2(0.30, 0.10), 0.17);
    // Bouche : une fente courte, qui achève de fixer le sens de lecture.
    float bouche = gCapsule(p, vec2(-0.20, -0.30), vec2(0.20, -0.30), 0.07);
    return gCut(tete, gUnion(gUnion(oeil_g, oeil_d), bouche));
}

// Interrogation : arc, hampe, point. Le seul sigle qui ressemble à un
// caractère, et c'est voulu — il n'y a pas de texte dans l'application, mais un
// point d'interrogation est un pictogramme universel.
float gQuestion(vec2 p) {
    // **Asymétrique, et c'est tout le sujet.** Les deux versions précédentes
    // s'appuyaient sur `gArc`, qui replie x sur sa valeur absolue : elles
    // dessinaient donc un fer à cheval symétrique, lu comme un U ou un oméga.
    //
    // Un point d'interrogation est un anneau dont il **manque le quart
    // inférieur gauche**, prolongé d'une hampe qui redescend au centre. C'est
    // exactement ce que fait ce retranchement de quadrant.
    vec2 centre = vec2(0.0, 0.36);
    float anneau = gRing(p - centre, 0.42, 0.14);
    anneau = gCut(anneau, gQuadrant(p, centre, vec2(1.0, 1.0)));

    // Hampe : du bas de l'anneau vers le centre, légèrement oblique, comme
    // celle d'un caractère dessiné.
    float hampe = gCapsule(p, vec2(0.16, 0.04), vec2(0.0, -0.34), 0.14);
    float point = gCircle(p - vec2(0.0, -0.74), 0.17);
    return gUnion(gUnion(anneau, hampe), point);
}

// Aiguillage. Une chaîne de `if` plutôt qu'un tableau de fonctions, que GLSL
// ne permet pas : le compilateur les élimine toutes sauf une par appel.
//
// **Convention d'entrée : `+y` vers le haut**, comme les sigles sont écrits.
// C'est à l'appelant de s'y ramener, et non à cette fonction de renverser l'axe,
// parce que les deux surfaces qui affichent des sigles n'ont **pas** le même
// sens de y : la bulle est bâtie en pixels, qui descendent, la dalle du visage
// en UV de coque, qui montent. Un renversement unique ici servait l'une et
// mettait l'autre en miroir — la goutte pointait vers le bas et le point
// d'interrogation devenait un crochet.
float glyphDistance(int id, vec2 p) {
    if (id == GLYPH_HUNGER)   return gHunger(p);
    if (id == GLYPH_FUN)      return gFun(p);
    if (id == GLYPH_ENERGY)   return gEnergy(p);
    if (id == GLYPH_HYGIENE)  return gHygiene(p);
    if (id == GLYPH_ROBOT)    return gRobot(p);
    if (id == GLYPH_QUESTION) return gQuestion(p);
    return GLYPH_FAR;
}

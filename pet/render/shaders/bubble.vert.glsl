#version 330 core

// Bulle de besoin, alignée sur l'écran. Le quad est construit ici depuis un
// centre et un rayon en **pixels**, ce qui évite de retéléverser un buffer à
// chaque changement de taille : le VAO ne porte qu'un carré unitaire.

in vec2 in_corner;              // carré unitaire, [-1, 1]²

uniform vec2 uCenterPx;         // centre de la bulle, en pixels de rendu
uniform vec2 uViewportPx;
uniform float uRadiusPx;        // demi-côté de la bulle
uniform float uScale;           // pop d'apparition, 0 → 1

out vec2 vLocal;                // [-1, 1]², repère de la bulle

void main() {
    vLocal = in_corner;

    // La bulle grandit depuis son bord bas, là où la queue touche la tête : un
    // pop centré la ferait sortir du sol de la bulle et paraîtrait flotter.
    vec2 px = uCenterPx + in_corner * uRadiusPx * max(uScale, 0.0001);
    px.y += uRadiusPx * (1.0 - max(uScale, 0.0001));

    // Pixels vers clip, **sans renverser Y**. La projection orthographique de
    // ce projet inverse déjà l'axe (cf. render.toon._ortho), donc un y de pixel
    // qui descend correspond à un y de clip qui descend : les deux vont dans le
    // même sens. Le renverser ici une seconde fois plaçait la bulle à côté du
    // corps au lieu du dessus de la tête.
    vec2 ndc = px / uViewportPx * 2.0 - 1.0;
    gl_Position = vec4(ndc, 0.0, 1.0);
}

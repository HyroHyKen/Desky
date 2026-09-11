#version 330 core

// Bulle de besoin (lot L6 phase B). Une pastille arrondie avec une queue vers
// le bas, et un sigle du vocabulaire partagé à l'intérieur.
//
// Tout est SDF, comme le visage : la bulle n'est pas une image mais une forme
// calculée, donc elle reste nette à n'importe quelle taille de rendu — la taille
// du pet est réglable de 120 à 400 px (§17.1) et un sprite y baverait.

#include "glyphs.glsl"

in vec2 vLocal;                 // [-1, 1]², repère de la bulle

uniform int uGlyph;
uniform float uOpacity;
uniform float uPulse;           // 0 → 1, respiration d'appel
uniform vec3 uFill;
uniform vec3 uInk;
uniform float uRadiusPx;        // pour convertir les épaisseurs en pixels

out vec4 fragColor;

// **Dans ce repère, `+y` descend.** Le quad est construit en pixels et l'axe
// des pixels descend (cf. bubble.vert.glsl), donc `vLocal.y = +1` est le bord
// bas. Les nombres ci-dessous sont écrits dans cette convention, et l'orientation
// a été **mesurée** : la première version pointait sa queue vers le ciel.
const vec2 BODY_CENTER = vec2(0.0, -0.10);
const vec2 BODY_HALF = vec2(0.86, 0.62);
const float BODY_RADIUS = 0.40;

// La queue prend racine dans le corps et sort par le bas : sa base est à
// l'intérieur, sinon la soudure laisse un pli visible au raccord.
const float TAIL_BASE_Y = 0.40;
const float TAIL_HALF = 0.20;
const float TAIL_HEIGHT = 0.58;

void main() {
    vec2 p = vLocal;

    float corps = gBox(p - BODY_CENTER, BODY_HALF, BODY_RADIUS);
    float queue = gTriangleUp(p - vec2(0.0, TAIL_BASE_Y), TAIL_HALF, TAIL_HEIGHT);
    float d = gUnion(corps, queue);

    // Épaisseur du trait en pixels, convertie en unités locales : le contour
    // doit faire la même épaisseur à l'écran quelle que soit la taille du pet,
    // sinon une grande bulle paraît fine et une petite paraît grasse.
    float trait = 2.6 / max(uRadiusPx, 1.0);

    float aa = max(fwidth(d) * 1.1, 1e-4);
    float dedans = 1.0 - smoothstep(-aa, aa, d);
    float bord = 1.0 - smoothstep(-aa, aa, abs(d + trait) - trait);

    // Sigle, à l'intérieur du corps seulement. La respiration d'appel le fait
    // grossir très légèrement : c'est ce qui attire l'oeil sans clignoter.
    // `p.y` descend ici, les sigles sont écrits `+y` vers le haut : on renverse.
    vec2 gp = (p - BODY_CENTER) / (0.44 * (1.0 + 0.06 * uPulse));
    float g = glyphDistance(uGlyph, vec2(gp.x, -gp.y));
    float ga = max(fwidth(g) * 1.1, 1e-4);
    float sigle = 1.0 - smoothstep(-ga, ga, g);

    vec3 color = mix(uFill, uInk, max(bord, sigle));
    float alpha = max(dedans, bord) * uOpacity;

    // Alpha prémultiplié, comme toutes les passes de ce projet : la fenêtre
    // composite en GL_ONE / GL_ONE_MINUS_SRC_ALPHA.
    fragColor = vec4(color * alpha, alpha);
}

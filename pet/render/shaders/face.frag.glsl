#version 330 core

// Visage (CDC §9). Le visage n'est **pas** de la géométrie : c'est une coque
// légèrement bombée dont ce shader dessine les yeux par SDF, en émissif non
// éclairé, avec un léger halo additif.
//
// « Ce shader unique remplace des centaines de sprites et se pilote entièrement
// depuis le comportement. » Tout ce qui suit est donc piloté par uniformes :
// aucune branche conditionnelle, aucun état côté CPU. Une **expression** est un
// jeu nommé de ces valeurs, et les transitions sont des interpolations de ce
// jeu — jamais des bascules.

#include "glyphs.glsl"

in vec2 vUV;                    // espace de la coque, [-1, 1]²

// -- forme du regard, issue du génome ---------------------------------------
uniform float uAspect;          // largeur/hauteur monde de la coque
uniform float uEyeSpacing;      // écart au centre, en unités de hauteur
uniform float uEyeSize;         // demi-hauteur d'un œil
uniform float uEyeAspect;       // largeur/hauteur d'un œil
uniform float uCornerRadius;    // arrondi, en part de la demi-taille
uniform float uEyeCenterY;      // hauteur du regard dans la coque

// -- animation, pilotée par le comportement (CDC §9) ------------------------
uniform float uBlink;           // 0 → 1, écrasement vertical de la paupière
uniform vec2 uGaze;             // décalage des pupilles
uniform float uLidTop;          // occlusion haute → colère
uniform float uLidBottom;       // occlusion basse → somnolence
uniform float uSquint;          // plissement → joie, méfiance
uniform float uPupilScale;      // dilatation → surprise, affection
uniform float uGlitch;          // bruit de balayage horizontal → réveil
uniform float uTime;

// -- afficheur (lot L6 phase B) ---------------------------------------------
// « C'est par ses yeux qu'on affichera ce qu'il souhaite dire à
// l'utilisateur. » Les pupilles se fondent en deux sigles du vocabulaire
// partagé. Un fondu de masques et non une interpolation de distances : morpher
// deux SDF donne une forme intermédiaire qui ne veut rien dire, alors qu'un
// fondu se lit comme un affichage qui change.
uniform int uGlyphLeft;
uniform int uGlyphRight;
uniform float uGlyphMix;        // 0 = pupilles, 1 = sigles

// -- couleurs ---------------------------------------------------------------
uniform vec3 uScreenColor;
uniform vec3 uEyeColor;
uniform float uGlow;

out vec4 fragColor;

float sdRoundBox(vec2 p, vec2 b, float r) {
    r = min(r, min(b.x, b.y));
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

void main() {
    // Espace isotrope : la coque est plus large que haute, donc travailler
    // directement en UV déformerait les yeux. On étire x par l'aspect et on
    // exprime toutes les tailles en unités de hauteur.
    vec2 p = vec2(vUV.x * uAspect, vUV.y - uEyeCenterY);

    // Balayage horizontal. Le décalage dépend de la hauteur, ce qui donne le
    // cisaillement caractéristique d'une image mal synchronisée.
    float scan = sin(p.y * 74.0 - uTime * 26.0) * sin(uTime * 3.7);
    p.x += uGlitch * 0.09 * scan;

    // Le regard déplace les pupilles dans la dalle, sans déplacer la dalle.
    p -= vec2(uGaze.x, uGaze.y) * uEyeSize * 1.35;

    // Hauteur de l'œil : le clignement l'écrase, le plissement la réduit, la
    // dilatation l'augmente. Un plancher évite qu'un œil fermé disparaisse
    // complètement au lieu de devenir un trait.
    float openness = max(0.04, (1.0 - uBlink) * (1.0 - 0.55 * uSquint));
    vec2 half_size = vec2(uEyeSize * uEyeAspect * uPupilScale,
                          uEyeSize * openness * uPupilScale);

    // Arrondi : plancher relevé pour que la pupille lise comme une capsule
    // et non comme un rectangle. Le gène (0,15–0,50) module dans [0,70 ; 1,00]
    // du plus petit demi-côté, 1,00 donnant la capsule parfaite. Réglage de
    // rendu, pas de génome : les valeurs des pets existants ne changent pas.
    float radius = min(1.0, 0.55 + uCornerRadius) * min(half_size.x, half_size.y);
    float d = min(sdRoundBox(p - vec2(uEyeSpacing, 0.0), half_size, radius),
                  sdRoundBox(p + vec2(uEyeSpacing, 0.0), half_size, radius));

    // Paupières : deux demi-plans qui rognent l'œil par le haut et par le bas.
    // C'est ce qui distingue la colère (paupière haute descendue) de la
    // somnolence (paupière basse remontée) d'un simple clignement.
    float lid_top = half_size.y * (1.0 - 2.0 * uLidTop);
    float lid_bottom = -half_size.y * (1.0 - 2.0 * uLidBottom);
    d = max(d, p.y - lid_top);
    d = max(d, lid_bottom - p.y);

    // Anti-aliasing dérivé du gradient de la SDF : reste net quelle que soit la
    // taille de rendu, là où un seuil fixe crénellerait aux petites tailles.
    float aa = max(fwidth(d) * 1.1, 1e-4);
    float mask = 1.0 - smoothstep(-aa, aa, d);

    // Halo additif : la lueur d'une dalle émissive déborde un peu.
    float halo = exp(-max(0.0, d) * 22.0) * uGlow;

    // Afficheur. Les sigles occupent un peu plus que la pupille : dessinés à sa
    // taille exacte, ils seraient illisibles — une pupille est une capsule
    // étroite, un pictogramme a besoin de largeur.
    if (uGlyphMix > 0.001) {
        // Taille et écart fixés sur la **dalle**, et non déduits du génome.
        //
        // Deux raisons. D'abord la lisibilité : une pupille est une capsule
        // étroite, un pictogramme a besoin d'un carré, et à la taille de l'oeil
        // l'arc du point d'interrogation disparaissait. Ensuite l'uniformité :
        // un afficheur doit faire la même taille sur tous les robots, alors que
        // `eye.size` varie du simple au double d'un génome à l'autre — dimensionné
        // dessus, il débordait de la dalle sur les grands yeux.
        //
        // Placés **sur les pupilles** et non sur la largeur de la dalle : la
        // coque s'enroule sur le crâne, donc ses UV extrêmes sont vus de biais
        // ou cachés, et des sigles calés sur `uAspect` sortaient rognés des deux
        // côtés. Les positions des pupilles, elles, sont visibles par
        // construction. Seule la taille est fixe, pour qu'un afficheur ait la
        // même dimension sur tous les robots.
        float taille = 0.44;
        float ecart = uEyeSpacing;
        // `p.y` monte ici : rien à renverser, contrairement à la bulle.
        float gg = glyphDistance(uGlyphLeft, (p + vec2(ecart, 0.0)) / taille);
        float gd = glyphDistance(uGlyphRight, (p - vec2(ecart, 0.0)) / taille);
        float g = min(gg, gd);
        float ga = max(fwidth(g) * 1.1, 1e-4);
        mask = mix(mask, 1.0 - smoothstep(-ga, ga, g), uGlyphMix);
        halo = mix(halo, exp(-max(0.0, g) * 22.0) * uGlow, uGlyphMix);
    }

    vec3 color = uScreenColor + uEyeColor * (mask + halo);

    // Émissif, non éclairé (CDC §9). Alpha 1 : la dalle est opaque, donc la
    // couleur est déjà prémultipliée.
    fragColor = vec4(color, 1.0);
}

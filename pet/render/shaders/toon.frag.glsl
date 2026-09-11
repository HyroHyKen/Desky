#version 330 core

// Passe toon — équivalent fonctionnel de MeshToonMaterial (CDC §8) :
// diffus lambertien quantifié par une rampe, spéculaire dur seuillé, rim light.

in vec3 vNormal;

uniform sampler2D uGradientMap;   // 1D déguisée en 2D, filtrage NEAREST
uniform vec3 uBaseColor;
uniform vec3 uSpecColor;
uniform vec3 uRimColor;
uniform vec3 uLightDir;
uniform float uShininess;
uniform float uRimStart;
uniform float uRimEnd;

out vec4 fragColor;

void main() {
    vec3 N = normalize(vNormal);
    vec3 L = normalize(uLightDir);

    // Caméra orthographique (CDC §8) : la direction de vue est constante sur
    // toute l'image. C'est ce qui rend l'épaisseur du contour uniforme au lot
    // L3 sans compensation, et ça simplifie ici le demi-vecteur.
    vec3 V = vec3(0.0, 0.0, 1.0);
    vec3 H = normalize(L + V);

    float ndl = dot(N, L);
    float ramp = clamp(ndl * 0.5 + 0.5, 0.0, 1.0);
    vec3 base = texture(uGradientMap, vec2(ramp, 0.5)).rgb * uBaseColor;

    // Spéculaire dur : seuillé pour le palier net, mais smoothstep plutôt que
    // step afin de rester anti-aliasé.
    float s = pow(max(dot(N, H), 0.0), uShininess);
    float spec = smoothstep(0.48, 0.52, s);

    float rim = smoothstep(uRimStart, uRimEnd, 1.0 - max(dot(N, V), 0.0));

    vec3 color = base + spec * uSpecColor + rim * uRimColor;

    // Sortie en alpha PRÉMULTIPLIÉ (CDC §6). C'est le point qui décide de la
    // réussite du lot : couplé à glBlendFunc(ONE, ONE_MINUS_SRC_ALPHA) et à un
    // clear à (0,0,0,0), le résolu MSAA moyenne des fragments déjà
    // prémultipliés, ce qui donne un bord correct au lieu du liséré noir que
    // produit un alpha droit composé par QPainter.
    float alpha = 1.0;
    fragColor = vec4(color * alpha, alpha);
}

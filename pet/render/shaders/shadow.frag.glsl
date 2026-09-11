#version 330 core

in vec2 vLocal;

uniform vec3 uShadowColor;
uniform float uOpacity;
uniform float uFalloff;

out vec4 fragColor;

void main() {
    float d = length(vLocal);
    // Chute en puissance plutôt qu'un bord seuillé : une ombre de contact au
    // bord franc lit comme un disque posé, pas comme une ombre.
    float a = uOpacity * pow(max(0.0, 1.0 - d), uFalloff);
    // Prémultiplié (CDC §6) : la couleur est déjà multipliée par l'alpha.
    fragColor = vec4(uShadowColor * a, a);
}

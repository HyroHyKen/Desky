#version 330 core

// Passe de contour par inverted hull (CDC §8) : les sommets sont déplacés le
// long de leur normale, et seules les faces arrière sont rendues. Le décalage
// est exprimé en unités monde, calculées côté CPU depuis une épaisseur en
// pixels : la caméra étant orthographique, l'épaisseur à l'écran est alors
// constante, sans compensation.

in vec3 in_position;
in vec3 in_normal;

uniform mat4 uMVP;
uniform float uScale;
uniform float uOutline;

void main() {
    // L'extrusion s'ajoute après la mise à l'échelle du corps : elle ne doit
    // pas grossir avec la réaction au clic, sinon le trait pulserait.
    vec3 p = in_position * uScale + normalize(in_normal) * uOutline;
    gl_Position = uMVP * vec4(p, 1.0);
}

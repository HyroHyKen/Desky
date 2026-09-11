#version 330 core

uniform vec3 uOutlineColor;

out vec4 fragColor;

void main() {
    // Couleur plate. L'alpha valant 1, la couleur est déjà prémultipliée.
    fragColor = vec4(uOutlineColor, 1.0);
}

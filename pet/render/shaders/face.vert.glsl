#version 330 core

in vec3 in_position;
in vec2 in_uv;

// Pas de normale : le visage est émissif et non éclairé (CDC §9). Un attribut
// déclaré sans être utilisé serait de toute façon éliminé par le compilateur,
// et c'est précisément ce qui empêchait la création du VAO au premier essai.

uniform mat4 uMVP;
uniform float uScale;

out vec2 vUV;

void main() {
    // La coque est bombée en 3D, mais le dessin qui s'y applique est plan :
    // le fragment shader travaille entièrement dans l'espace UV de la coque.
    vUV = in_uv;
    gl_Position = uMVP * vec4(in_position * uScale, 1.0);
}

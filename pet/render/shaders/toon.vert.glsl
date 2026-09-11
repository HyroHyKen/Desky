#version 330 core

in vec3 in_position;
in vec3 in_normal;

uniform mat4 uMVP;
uniform mat3 uNormalMat;
uniform float uScale;

out vec3 vNormal;

void main() {
    vNormal = normalize(uNormalMat * in_normal);
    gl_Position = uMVP * vec4(in_position * uScale, 1.0);
}

#version 330 core

// Ombre de contact (CDC §8) : une ellipse floutée au sol, sous le robot.
// « Élément peu coûteux et déterminant pour l'ancrage visuel. »

in vec2 in_corner;              // quad unitaire, [-1, 1]²

uniform mat4 uMVP;
uniform vec3 uCenter;           // centre de l'ombre, au sol
uniform float uRadius;
uniform float uSquash;          // aplatissement en profondeur

out vec2 vLocal;

void main() {
    vLocal = in_corner;
    // Quad **aligné sur l'écran**, et non couché dans le plan du sol.
    //
    // Mesuré au lot L3 : posée à plat, l'ombre ne faisait que 8 pixels de haut,
    // parce que la caméra n'a que 9° de tangage et voit donc le sol presque de
    // profil. Le CDC §8 demande « une ellipse floutée rendue sous le robot »,
    // pas un plan de sol — et l'appeler « ombre de contact » dit bien qu'elle
    // marque le contact, pas la projection physique d'une lumière.
    //
    // La matrice reçue omet volontairement la rotation du robot : l'ombre reste
    // ainsi face au spectateur quelle que soit l'orientation du pet.
    vec3 p = uCenter + vec3(in_corner.x * uRadius,
                            in_corner.y * uRadius * uSquash,
                            0.0);
    gl_Position = uMVP * vec4(p, 1.0);
}

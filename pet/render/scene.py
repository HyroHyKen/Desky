"""Orchestration des passes de rendu et possession des tampons GPU.

Module hors de la liste du CDC §5, qui énumère les passes (`toon.py`,
`outline.py`, `face.py`) sans dire qui les enchaîne. Quelqu'un doit posséder les
VBO et fixer l'ordre, et le faire depuis l'une des passes l'aurait rendue
maîtresse des autres.

**Ordre des passes**, et chacun de ces choix a une raison :

1. **Ombre**, sans écriture de profondeur. Elle est au sol, exactement au niveau
   des pieds ; lui laisser écrire la profondeur produirait du z-fighting.
2. **Contour**, faces avant écartées, sommets extrudés. Dessiné avant le corps :
   le test de profondeur suffirait dans les deux sens, mais dessiner le trait
   d'abord évite toute égalité de profondeur sur la silhouette.
3. **Corps**, passe toon.
4. **Visage**, en dernier. Émissif et posé sur la tête, il doit gagner sur le
   crâne sans que le halo n'ait à lutter contre lui.

Un seul VBO par partie sert les trois passes de géométrie : elles diffèrent par
le programme, pas par les données. Seule la coque faciale a un tampon distinct,
parce qu'elle porte en plus ses coordonnées UV.
"""

from __future__ import annotations

import moderngl
import numpy as np

from ..geometry.builder import Part, Robot
from .bubble import BubblePass
from .context import RenderContext
from .face import FacePass, FaceState
from .outline import OutlinePass
from .shadow import ShadowPass
from .toon import ToonPass

# Marge autour du robot dans le cadrage, en part de sa plus grande dimension.
# Laisse la place à l'extrusion du contour, au rim light et à l'ombre, qui
# mordent tous sur le bord de la silhouette.
FRAMING_MARGIN = 0.16

# Part de la hauteur de cadre réservée au-dessus du robot, pour la bulle du
# lot L6 phase B.
#
# Réservée sur le **cadrage** et non sur la fenêtre, qui garde sa taille : le sol
# est ancré sur le bas de la fenêtre — `floor_y = bas de zone de travail moins
# hauteur de fenêtre` — donc agrandir la fenêtre aurait déplacé cette équation
# dans les lots L1 et L5b, et coûté 36 % de relecture GPU pour un bandeau vide
# la plupart du temps.
#
# Le robot y perd de la taille apparente. La valeur a été choisie sur planche
# comparative, pas au jugé.
BUBBLE_HEADROOM = 0.26

# Couleur de la dalle sous le visage. Fixe, non génétique : c'est l'ardoise.
SCREEN_COLOR = (0.075, 0.085, 0.105)


def _ortho(half_w: float, half_h: float, near: float, far: float) -> np.ndarray:
    """Projection orthographique centrée, convention M @ v (row-major numpy).

    L'axe Y est **inversé** délibérément. OpenGL a son origine en bas à gauche,
    QImage la veut en haut à gauche ; retourner ici, dans la matrice, rend le
    contenu du FBO directement exploitable et économise le retournement numpy
    par image (0,15 ms mesurées au lot L0, soit 13 % du coût d'une image).

    Conséquence : le sens d'enroulement apparent des triangles est miroir, ce qui
    décide du culling de la passe de contour. Ce sens est **mesuré** au lot L3,
    pas déduit : cf. `Scene.CULL_FACE`.
    """
    m = np.identity(4, dtype="f4")
    m[0, 0] = 1.0 / half_w
    m[1, 1] = -1.0 / half_h
    m[2, 2] = -2.0 / (far - near)
    m[2, 3] = -(far + near) / (far - near)
    return m


def _rotation(yaw: float, pitch: float) -> np.ndarray:
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    ry = np.array([[cy, 0, sy, 0], [0, 1, 0, 0], [-sy, 0, cy, 0], [0, 0, 0, 1]], dtype="f4")
    rx = np.array([[1, 0, 0, 0], [0, cp, -sp, 0], [0, sp, cp, 0], [0, 0, 0, 1]], dtype="f4")
    return ry @ rx


def _translation(v: np.ndarray) -> np.ndarray:
    m = np.identity(4, dtype="f4")
    m[:3, 3] = v
    return m


class _PartBuffers:
    """VBO et IBO d'une partie, avec un VAO par programme qui la consomme."""

    __slots__ = ("part", "vbo", "ibo", "vaos")

    # Contenu du tampon, dans l'ordre. Le nombre de composantes sert à calculer
    # le saut d'octets des attributs qu'un programme n'utilise pas.
    FIELDS = (("in_position", 3), ("in_normal", 3), ("in_uv", 2))

    def __init__(self, ctx: moderngl.Context, part: Part,
                 programs: dict[str, moderngl.Program]) -> None:
        self.part = part
        mesh = part.mesh

        if mesh.uv is not None:
            data = np.hstack([mesh.vertices, mesh.uv]).astype("f4")
            present = ("in_position", "in_normal", "in_uv")
        else:
            data = mesh.vertices
            present = ("in_position", "in_normal")

        self.vbo = ctx.buffer(np.ascontiguousarray(data).tobytes())
        self.ibo = ctx.buffer(mesh.indices.tobytes())
        self.vaos: dict[str, moderngl.VertexArray] = {}

        for name, program in programs.items():
            # La disposition est calculée **par programme**. Un attribut déclaré
            # sans être utilisé est éliminé par le compilateur GLSL — c'est le
            # cas de la normale dans le shader du visage — et le lier alors
            # échoue. Les champs absents deviennent donc un saut d'octets.
            # Un programme qui réclame un attribut absent du tampon est
            # écarté : le lier laisserait cet attribut non initialisé, et le
            # VAO produirait de la géométrie indéfinie au lieu d'échouer.
            if any(f in program and f not in present for f, _ in self.FIELDS):
                continue

            tokens, names = [], []
            for field, count in self.FIELDS:
                if field not in present:
                    continue
                if field in program:
                    tokens.append(f"{count}f")
                    names.append(field)
                else:
                    tokens.append(f"{count}x4")
            if not names:
                continue
            self.vaos[name] = ctx.vertex_array(
                program, [(self.vbo, " ".join(tokens), *names)], self.ibo)

    def release(self) -> None:
        for vao in self.vaos.values():
            vao.release()
        self.vbo.release()
        self.ibo.release()


class Scene:
    """Enchaîne les passes et détient les tampons du robot courant."""

    # Sens de culling de l'inverted hull. **Mesuré** au lot L3 par comparaison
    # des deux valeurs : avec l'axe Y inversé de la projection, l'enroulement
    # apparent décide lequel garde les faces arrière, et se tromper donne un
    # aplat sombre à la place du trait.
    CULL_FACE = "front"

    def __init__(self, rc: RenderContext) -> None:
        self.rc = rc
        self.toon = ToonPass(rc.ctx, rc.program("toon"))
        self.outline = OutlinePass(rc.ctx, rc.program("outline"))
        self.face = FacePass(rc.ctx, rc.program("face"))
        self.shadow = ShadowPass(rc.ctx, rc.program("shadow"))
        self.bubble = BubblePass(rc.ctx, rc.program("bubble"))

        self._programs = {
            "toon": self.toon.program,
            "outline": self.outline.program,
            "face": self.face.program,
        }

        self.robot: Robot | None = None
        self._buffers: list[_PartBuffers] = []
        self._center = np.zeros(3, dtype="f4")
        self._half_extent = 1.0
        self._height = 1.0
        self._half_width = 1.0
        self._floor_y = 0.0
        self._headroom = BUBBLE_HEADROOM
        # Cadrage effectif : le robot garde `_center` et `_half_extent`, la
        # caméra travaille sur les deux valeurs dérivées ci-dessous. Séparer les
        # deux évite de recalculer la boîte englobante à chaque changement de
        # bandeau, et garde une seule définition de « le robot fait telle taille ».
        self._view_half = 1.0
        self._view_center = np.zeros(3, dtype="f4")

        self.face_state = FaceState()
        self.draw_outline = True
        self.draw_shadow = True
        self.draw_face = True

        # Afficheur et bulle. Portés par la scène parce que c'est elle qui
        # connaît le cadrage et l'ordre des passes ; leur **état** vit dans la
        # fenêtre, qui reçoit les clics.
        self.eye_glyphs: tuple[int, int] = (0, 0)
        self.eye_glyph_mix = 0.0
        self.bubble_glyph = 0
        self.bubble_opacity = 0.0
        self.bubble_scale = 1.0
        self.bubble_pulse = 0.0

    # -- robot ---------------------------------------------------------------

    def set_robot(self, robot: Robot) -> None:
        """Téléverse la géométrie. Appelé au changement de génome seulement."""
        self.release_buffers()
        self.robot = robot
        self._buffers = [
            _PartBuffers(self.rc.ctx, part, self._programs) for part in robot.parts
        ]

        lo, hi = robot.bounds()
        self._center = ((lo + hi) / 2.0).astype("f4")
        # Cadrage sur la plus grande dimension : la silhouette garde ainsi la
        # même emprise à l'écran quelle que soit la morphologie tirée, sinon un
        # robot élancé apparaîtrait minuscule à côté d'un trapu.
        self._half_extent = float(np.max(hi - lo)) * 0.5 * (1.0 + FRAMING_MARGIN)
        self._height = float(hi[1] - lo[1])
        self._half_width = float(hi[0] - lo[0]) * 0.5
        self._floor_y = float(lo[1])

        self._reframe()
        self.toon.configure(robot.accent)

        face = next((b for b in self._buffers if b.part.name == "face"), None)
        if face is not None:
            self.face.configure(robot.genome, face.part.mesh.bounds(),
                                SCREEN_COLOR, robot.accent)

    @property
    def headroom(self) -> float:
        return self._headroom

    @headroom.setter
    def headroom(self, value: float) -> None:
        self._headroom = max(0.0, min(0.6, float(value)))
        self._reframe()

    def _reframe(self) -> None:
        """Recalcule le cadrage effectif depuis le bandeau réservé.

        Le robot occupe le bas du cadre : la demi-hauteur de vue est dilatée de
        `1 / (1 - bandeau)`, et le centre de vue remonte d'exactement ce que la
        dilatation a ajouté. Les pieds retombent alors sur le bord bas, ce qui
        est la propriété qui laisse le sol des lots L1 et L5b intact.
        """
        libre = max(0.05, 1.0 - self._headroom)
        self._view_half = self._half_extent / libre
        self._view_center = self._center.copy()
        self._view_center[1] += self._view_half - self._half_extent

    def bubble_anchor_px(self) -> tuple[float, float]:
        """Centre du bandeau de bulle, en pixels de rendu.

        Publié par la scène plutôt que calculé par l'appelant : c'est elle qui
        connaît le cadrage, et deux calculs du même point finiraient par
        diverger.
        """
        w, h = self.rc.size
        haut = self._view_center[1] + self._view_half
        sommet = self._center[1] + self._half_extent
        return w * 0.5, self.project_px((0.0, 0.5 * (haut + sommet), 0.0))[1]

    def release_buffers(self) -> None:
        for buf in self._buffers:
            buf.release()
        self._buffers = []

    def project_px(self, world_point) -> tuple[float, float]:
        """Point du repère du robot -> pixels de la fenêtre, robot au repos.

        Sert au suivi du curseur : la couche look-at a besoin de savoir *où* est
        la tête à l'écran pour mesurer l'écart au curseur. La rotation n'est pas
        appliquée — l'ancre doit rester stable, sinon le pet poursuivrait sa
        propre tête en train de tourner.

        L'origine des pixels est en haut à gauche, comme pour QImage : la
        projection inversant déjà Y, un point haut dans le monde ressort avec un
        y de pixel faible.
        """
        w, h = self.rc.size
        aspect = w / h if h else 1.0
        half = self._view_half
        dx = float(world_point[0]) - float(self._view_center[0])
        dy = float(world_point[1]) - float(self._view_center[1])
        clip_x = dx / (half * aspect)
        clip_y = -dy / half
        return (clip_x * 0.5 + 0.5) * w, (clip_y * 0.5 + 0.5) * h

    # -- rendu ---------------------------------------------------------------

    def draw(self, yaw: float, pitch: float, scale: float = 1.0,
             time_s: float = 0.0, lift: float = 0.0) -> None:
        if self.robot is None:
            return

        w, h = self.rc.size
        aspect = w / h if h else 1.0
        proj = _ortho(self._view_half * aspect, self._view_half, -20.0, 20.0)

        # Le robot est ramené sur l'origine avant rotation : il tourne donc
        # autour de son propre centre et non de ses pieds. La translation de
        # cadrage, elle, porte le centre de **vue**, décalé par le bandeau.
        view = _translation(self._center - self._view_center) @ (
            _rotation(yaw, pitch) @ _translation(-self._center))
        world = self.robot.rig.world_matrices()

        if self.draw_shadow:
            # Matrice **sans rotation** : l'ombre est un quad aligné sur
            # l'écran, la faire tourner avec le pet la basculerait sur la
            # tranche. Seul le recentrage est appliqué.
            flat = proj @ _translation(-self._view_center)
            ground = (float(self._center[0]), self._floor_y, float(self._center[2]))
            self.shadow.draw(flat, ground, self._half_width, self._height, lift)

        if self.draw_outline:
            # Épaisseur convertie sur la demi-hauteur de **vue** : c'est
            # elle qui donne la valeur d'un pixel en unités monde. Prise sur
            # celle du robot, le trait s'épaissirait avec le bandeau.
            width = self.outline.world_width(self._view_half, h,
                                             self.robot.outline_width)
            self.outline.begin(self.CULL_FACE)
            self.outline.program["uOutline"].value = width
            self.outline.program["uScale"].value = scale
            for buf in self._buffers:
                # Les coques ouvertes n'ont pas de face arrière pour masquer
                # leur bord : les extruder dessinerait un liseré autour de
                # l'écran.
                if not buf.part.mesh.closed or "outline" not in buf.vaos:
                    continue
                mvp = proj @ view @ world[buf.part.node] @ buf.part.offset_matrix()
                self.outline.program["uMVP"].write(
                    np.ascontiguousarray(mvp.T).tobytes())
                buf.vaos["outline"].render(moderngl.TRIANGLES)
            self.outline.end()

        self.toon.begin(scale)
        for buf in self._buffers:
            if buf.part.name == "face" and self.draw_face:
                continue                    # rendue par la passe dédiée
            if "toon" not in buf.vaos:
                continue
            model = view @ world[buf.part.node] @ buf.part.offset_matrix()
            self.toon.draw(buf.vaos["toon"], proj @ model, model, buf.part.color)

        if self.draw_face:
            face = next((b for b in self._buffers if b.part.name == "face"), None)
            if face is not None and "face" in face.vaos:
                mvp = proj @ view @ world[face.part.node] @ face.part.offset_matrix()
                self.face.draw(face.vaos["face"], mvp, self.face_state,
                               scale, time_s, self.eye_glyphs,
                               self.eye_glyph_mix)

        # La bulle passe en dernier : elle est au-dessus de tout, et son
        # bandeau est vide par construction du cadrage.
        self.bubble.draw(self.rc.size, self.bubble_anchor_px(),
                         self.bubble_glyph, self.bubble_opacity,
                         self.bubble_scale, self.bubble_pulse)

    def bubble_hit(self, point: tuple[float, float]) -> bool:
        """Le point, en pixels de rendu, tombe-t-il sur la bulle affichée ?"""
        if self.bubble_glyph <= 0 or self.bubble_opacity <= 0.25:
            return False
        return self.bubble.hit(self.rc.size, self.bubble_anchor_px(), point)

    def release(self) -> None:
        self.release_buffers()
        self.toon.release()
        self.bubble.release()
        self.shadow.release()

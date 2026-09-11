"""Contexte ModernGL standalone et FBO RGBA (CDC §4, §6).

Le rendu est offscreen, dans un FBO multi-échantillonné résolu vers un FBO
RGBA8 simple dont on relit les pixels. Ce détour par un contexte standalone
plutôt que par QOpenGLWidget est un choix imposé du CDC : la combinaison
QOpenGLWidget + WA_TranslucentBackground est instable sur Windows.

Le prix payé est une relecture GPU -> CPU par image. À 220 px de côté c'est
~190 Ko, ce qui reste sous le budget ; le buffer relu sert d'ailleurs deux fois,
puisque le hit-testing par alpha (CDC §6) le réutilise au lieu de reconstruire
un masque.
"""

from __future__ import annotations

from pathlib import Path

from .. import resources

import moderngl
import numpy as np

SHADER_DIR = resources.resource_dir("render", "shaders")


class ContextCreationError(RuntimeError):
    """Échec de création du contexte OpenGL 3.3.

    Remontée telle quelle jusqu'au bootstrap, qui doit afficher un message
    clair au lieu de crasher (CDC §15, repli GPU).
    """


class RenderContext:
    """Contexte GL + cible de rendu, redimensionnable."""

    def __init__(self, size: tuple[int, int], samples: int = 4) -> None:
        try:
            self.ctx = moderngl.create_standalone_context(require=330)
        except Exception as exc:                      # noqa: BLE001
            raise ContextCreationError(str(exc)) from exc

        self.info = {
            "version": self.ctx.info["GL_VERSION"],
            "renderer": self.ctx.info["GL_RENDERER"],
            "vendor": self.ctx.info["GL_VENDOR"],
        }

        max_samples = int(self.ctx.info["GL_MAX_SAMPLES"])
        self.samples = min(samples, max_samples)

        self.ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        # Alpha prémultiplié : le shader sort déjà rgb * a.
        self.ctx.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)

        self._msaa = None
        self._resolve = None
        self._pixels: np.ndarray | None = None
        self.size = (0, 0)
        self.resize(size)

    # -- cible de rendu ------------------------------------------------------

    def resize(self, size: tuple[int, int]) -> None:
        """(Re)crée les FBO. Appelé au changement de taille physique seulement."""
        w, h = max(1, int(size[0])), max(1, int(size[1]))
        if (w, h) == self.size:
            return

        for fbo in (self._msaa, self._resolve):
            if fbo is not None:
                fbo.release()

        self._msaa = self.ctx.framebuffer(
            color_attachments=[self.ctx.renderbuffer((w, h), components=4, samples=self.samples)],
            depth_attachment=self.ctx.depth_renderbuffer((w, h), samples=self.samples),
        )
        self._resolve = self.ctx.simple_framebuffer((w, h), components=4)
        # Tampon de relecture persistant : voir read_rgba.
        self._pixels = np.empty((h, w, 4), dtype=np.uint8)
        self.size = (w, h)

    def begin(self) -> None:
        self._msaa.use()
        self.ctx.viewport = (0, 0, *self.size)
        self._msaa.clear(0.0, 0.0, 0.0, 0.0)

    def read_rgba(self) -> np.ndarray:
        """Résout le MSAA et relit le buffer en (h, w, 4) uint8, prémultiplié.

        Le tableau sort déjà en ordre top-down, prêt pour QImage : c'est la
        projection qui inverse l'axe Y (cf. render.toon._ortho), ce qui évite
        une copie par image.

        La relecture se fait **dans un tableau persistant**, réutilisé d'une
        image sur l'autre. Mesure du lot L1, cadencée à 30 fps : 1,08 ms de
        médiane contre 1,52 ms pour un `read()` qui alloue 193 Ko à chaque
        image, avec de meilleures queues aussi (p90 1,49 contre 2,07 ms). Le
        coût dominant de cet étage était donc l'allocation, pas le transfert.

        Une relecture asynchrone à double PBO a été mesurée et **écartée** :
        1,10 ms de médiane pour un p90 à 2,65 ms, soit aucun gain et des
        queues nettement plus lourdes, au prix d'une image de latence.

        Le tableau retourné est le même objet à chaque appel. C'est sans danger
        ici — un seul thread — mais un appelant qui veut conserver une image
        doit la copier.
        """
        self.ctx.copy_framebuffer(self._resolve, self._msaa)
        self._resolve.read_into(self._pixels, components=4)
        return self._pixels

    # -- chargement de programmes -------------------------------------------

    def program(self, name: str) -> moderngl.Program:
        vert = self._source(f"{name}.vert.glsl")
        frag = self._source(f"{name}.frag.glsl")
        return self.ctx.program(vertex_shader=vert, fragment_shader=frag)

    @staticmethod
    def _source(filename: str, depth: int = 0) -> str:
        """Lit un shader en résolvant ses `#include "autre.glsl"`.

        GLSL n'a pas d'inclusion, et le lot L6 en a besoin : le vocabulaire de
        sigles est partagé par la bulle et par le visage, et le dupliquer
        garantirait qu'ils divergent. La substitution est textuelle et se fait
        avant compilation, comme le fait n'importe quel moteur.

        Volontairement minimal : une ligne, un fichier, pas de garde
        d'inclusion. La profondeur est bornée pour qu'un cycle donne une erreur
        franche plutôt qu'un dépassement de pile.
        """
        if depth > 4:
            raise RuntimeError(f"inclusions trop imbriquées dans {filename}")
        lignes = []
        for ligne in (SHADER_DIR / filename).read_text(encoding="utf-8").splitlines():
            nu = ligne.strip()
            if nu.startswith("#include"):
                cible = nu.split('"')[1] if '"' in nu else ""
                lignes.append(RenderContext._source(cible, depth + 1))
            else:
                lignes.append(ligne)
        return "\n".join(lignes) + "\n"

    def release(self) -> None:
        for fbo in (self._msaa, self._resolve):
            if fbo is not None:
                fbo.release()
        self.ctx.release()

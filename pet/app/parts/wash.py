"""Le bain, côté fenêtre : sortir les outils, les suivre, conclure (lot L15).

Les règles sont dans `pet/care/wash.py` et rien ici n'en décide. Ce module est
la couture, comme `games.py` l'est pour les parties : il fournit au rituel ce
qu'il ne peut pas savoir — où est le robot, où est l'outil qu'on tient, quelle
part de sa silhouette est opaque — et exécute ce qu'il en conclut.

**Le robot est gelé pendant le bain**, et c'est la seule liberté qu'on lui
retire. Il vient chercher son kit tout seul, comme n'importe quel objet de soin ;
une fois arrivé, il s'arrête et se laisse faire. Le laisser flâner pendant qu'on
le savonne obligerait à courir après lui l'éponge à la main, ce qui est une
comédie amusante trente secondes et une corvée ensuite.

**Le clic droit est neutralisé pendant ce temps** (voir `PetWindow.washing`).
Le panneau s'ancre au-dessus de la tête et prend la moitié de l'écran : l'ouvrir
au milieu d'un savonnage cacherait précisément ce qu'on est en train de faire.

**Le bain n'expire pas, il s'abandonne.** Les outils n'ont pas la durée de vie
des objets de soin — on ne retire pas l'éponge des mains de quelqu'un — mais un
kit laissé en plan finit par rendre la main au robot, en créditant ce qui a été
fait. Un rituel qui immobiliserait le pet pour toujours serait un bug déguisé en
règle.
"""

from __future__ import annotations

import logging

from ...brain import consumables
from ...care.wash import SPONGE, SPRAY, Wash
from ...care import wash as regles
from ...feedback import bus
from ...ui import sparks
from ...ui.item import SIZE_RATIO, ItemWindow, tool_sprite
from ..ground import floor_y

log = logging.getLogger("desky.window")

# Inactivité au bout de laquelle le bain rend la main, en secondes. Assez long
# pour aller ouvrir la porte, assez court pour qu'un kit oublié ne fige pas le
# robot jusqu'au prochain redémarrage.
WASH_IDLE = 75.0

# Battement entre le dernier jet et la fête. Sans lui, le robot saute de joie
# dans la même image que le jet qui le rince, et les deux se mangent.
WASH_OUTRO = 0.45

# Taille des outils, en part de celle d'un objet de soin. Un peu plus gros :
# on les **manipule**, alors qu'un objet de soin se pose et s'attend.
TOOL_SCALE = 1.15


class WashMixin:
    """Cycle de vie d'un bain : ouvrir, suivre le geste, conclure."""

    # -- état ----------------------------------------------------------------

    @property
    def washing(self) -> bool:
        """Un bain est-il en cours ? Lu par le clic droit et par la locomotion."""
        return self.wash is not None

    # -- ouverture -----------------------------------------------------------

    def _start_wash(self, item: ItemWindow) -> None:
        """Le robot a rejoint son kit : le rituel commence là où le kit était."""
        _, _, pw, ph = self._pet_rect()

        self.wash = Wash(aspect=ph / max(1.0, float(pw)),
                         mask=self._wash_mask(pw, ph),
                         seed=self._picker._rng.randrange(1 << 30))
        self.wash_article = item.consumable
        self._wash_idle = 0.0
        self._wash_outro = 0.0

        self._spawn_tool("sponge", item.x, item.y)

        # Il s'arrête **ici** plutôt qu'au premier coup d'éponge : entre les
        # deux, il ferait un pas de côté et l'éponge ne serait plus en face.
        if self.locomotion is not None:
            self.locomotion.stop()

        bus.emit("bain_commence")
        self.clock.poke()
        log.info("bain commencé (%s)", item.consumable)
        if self.diag:
            print("[diag] bain : éponge", flush=True)

    def _wash_mask(self, pw: int, ph: int) -> tuple[bool, ...] | None:
        """Quelles cases de la grille tombent sur le robot.

        Lu **une fois**, à l'ouverture : la silhouette respire et cligne, et une
        grille qui changerait en cours de bain ferait réapparaître des cases
        déjà faites. Rendre `None` quand aucune image n'est encore disponible
        est volontaire — le modèle accepte alors toute la boîte, ce qui donne un
        bain trop facile plutôt qu'un bain impossible.
        """
        alpha = self._alpha
        if alpha is None or pw <= 0 or ph <= 0:
            return None

        hauteur, largeur = alpha.shape[0], alpha.shape[1]
        cases: list[bool] = []
        for index in range(regles.GRID_COLS * regles.GRID_ROWS):
            col, row = index % regles.GRID_COLS, index // regles.GRID_COLS
            x = min(largeur - 1, int((col + 0.5) / regles.GRID_COLS * largeur))
            y = min(hauteur - 1, int((row + 0.5) / regles.GRID_ROWS * hauteur))
            cases.append(bool(alpha[y, x] > 8))
        return tuple(cases)

    # -- outils --------------------------------------------------------------

    def _spawn_tool(self, name: str, x: float, y: float) -> None:
        """Pose un outil du kit à l'endroit indiqué, en pixels physiques."""
        _, _, pw, ph = self._pet_rect()
        dpr = pw / max(1, self.width())
        cote = max(24, int(round(TOOL_SCALE * SIZE_RATIO * ph / dpr)))

        outil = ItemWindow("clean", tool_sprite(name), cote, tool=True)
        outil.show()
        outil.place(x, y)
        self.wash_tool = outil

    def _swap_tool(self, name: str) -> None:
        """Remplace l'outil courant par un autre, au même endroit."""
        ancien = self.wash_tool
        x, y = (ancien.x, ancien.y) if ancien is not None else (self._x, self._y)
        self._close_tool()
        self._spawn_tool(name, x, y)

    def _close_tool(self) -> None:
        if self.wash_tool is not None:
            self.wash_tool.close()
            self.wash_tool = None

    # -- déroulement ---------------------------------------------------------

    def _step_wash(self, dt: float) -> None:
        """Avance le bain d'une image. Appelé par la boucle de rendu."""
        bain = self.wash
        if bain is None:
            return

        _, _, pw, ph = self._pet_rect()
        dpr = pw / max(1, self.width())
        outil = self.wash_tool

        if outil is not None and not outil.gone:
            sol = floor_y(self.current_monitor().work, int(outil.side * dpr))
            outil.step(dt, sol)

            if outil.held:
                self._wash_idle = 0.0
                tx, ty = outil.center(dpr)
                # Normalisées sur la boîte du robot : c'est le repère du modèle,
                # et le seul qui survive au déplacement du pet pendant le bain.
                u = (tx - self._x) / max(1.0, float(pw))
                v = (ty - self._y) / max(1.0, float(ph))
                if bain.state == SPONGE:
                    bain.scrub(u, v)
                elif bain.state == SPRAY and bain.aim(u, v, dt):
                    self._spray_effect(tx, ty)
            else:
                self._wash_idle += dt

        avant = bain.state
        bain.step(dt)
        if avant == SPONGE and bain.state == SPRAY:
            self._swap_tool("spray")
            bus.emit("bain_rince")
            if self.diag:
                print("[diag] bain : spray", flush=True)

        if bain.done:
            self._wash_outro += dt
            if self._wash_outro >= WASH_OUTRO and not bain.foam:
                self._finish_wash()
        elif self._wash_idle >= WASH_IDLE:
            log.info("bain abandonné : aucun geste depuis %.0f s", WASH_IDLE)
            bain.abandon()

        self.clock.poke()

    def _spray_effect(self, x: float, y: float) -> None:
        """Un jet part : la brume et le petit sursaut du robot."""
        sparks.spray_mist(self._ensure_dust().banc, self._pet_rect(), x, y)
        # Le même encaissement qu'une poussée : être aspergé fait tressaillir.
        self._impact.poke()

    # -- conclusion ----------------------------------------------------------

    def _finish_wash(self) -> None:
        """Ferme le rituel et paie ce qui a été fait."""
        bain, self.wash = self.wash, None
        if bain is None:
            return
        cle, self.wash_article = self.wash_article, ""
        self._close_tool()

        credit = bain.credit()
        complet = credit >= 1.0

        if credit <= 0.0:
            # Rien n'a été fait : le kit est rendu. Le §12 interdit de faire
            # payer un geste qui n'a pas eu lieu.
            self.session.refund_consumable(cle)
            log.info("bain sans un geste : kit rendu")
        else:
            applied = self.session.apply_consumable(cle, factor=credit)
            if applied:
                self._celebrate_care(cle, applied)

        bus.emit("bain_fini", complet=complet)
        self.clock.poke()
        log.info("bain terminé : %d %%", round(credit * 100))
        if self.diag:
            print(f"[diag] bain fini, crédit {credit:.2f}", flush=True)

    def _cancel_wash(self) -> None:
        """Interrompt un bain en cours : fermeture de l'application, remise à zéro.

        **Le kit n'est pas perdu pour autant.** Ce qui a été fait est crédité, et
        un bain jamais commencé est rendu — exactement comme à l'abandon. Fermer
        Desky au milieu d'un savonnage n'est pas une faute à sanctionner.

        La fête est la seule chose qu'on saute : elle passe par l'animateur et
        le panneau, qui n'existent plus forcément à ce moment-là.
        """
        bain, self.wash = self.wash, None
        self._close_tool()
        if bain is None:
            return
        cle, self.wash_article = self.wash_article, ""
        credit = bain.credit()
        if credit <= 0.0:
            self.session.refund_consumable(cle)
        else:
            self.session.apply_consumable(cle, factor=credit)

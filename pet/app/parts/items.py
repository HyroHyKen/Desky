"""Objets de soin posés sur le bureau (CDC §13, lot L7).

Extrait de `window` au lot L10. Un objet de soin vit dans sa **propre fenêtre**
— il doit pouvoir tomber à côté du pet, hors de sa boîte — et sa vie tient en
quatre moments : on le pose, il tombe, le pet va le chercher, il disparaît. Ce
sont les quatre méthodes de ce module.

`ItemsMixin` reste un mixin de `PetWindow` plutôt qu'un objet à part, et c'est
délibéré : ces méthodes lisent la position du pet, son moniteur, son plan, et
écrivent dans son animateur. Les passer à un collaborateur demanderait de lui
tendre la moitié de la fenêtre à chaque appel — on aurait déplacé le couplage
sans le réduire, en ajoutant une indirection.
"""

from __future__ import annotations

import logging

import math

from ...brain import consumables
from ...ui.item import REACH, SIZE_RATIO, ItemWindow
from ..ground import floor_y

# Distance d'apparition d'un objet de soin, en largeurs de pet. Assez loin pour
# que l'aller vaille le coup d'oeil, assez près pour qu'on le retrouve sans
# chercher — un objet lâché à l'autre bout d'un montage à trois écrans serait
# une corvée, pas un jeu.
ITEM_SPAWN_MIN = 2.0
ITEM_SPAWN_MAX = 6.0

# Hauteur de lâcher, en hauteurs d'objet : il tombe et rebondit, comme tout ce
# qui arrive dans ce bureau.
ITEM_DROP_HEIGHT = 1.6


log = logging.getLogger("desky.window")


class ItemsMixin:
    """Pose, chute, ramassage et disparition d'un objet de soin."""

    # -- objets de soin ------------------------------------------------------

    @property
    def item_pending(self) -> bool:
        return self.item is not None and not self.item.gone

    def _spawn_item(self, key: str) -> bool:
        """Pose au sol l'objet correspondant au consommable `key`.

        L'article quitte le stock **ici**, à l'apparition, et non à la
        consommation : sans cela rien n'empêcherait d'en semer dix avec un seul
        exemplaire. S'il n'est jamais rejoint, l'objet s'évapore et l'article est
        rendu — le §12 interdit de punir.
        """
        article = consumables.get(key)
        if article is None or self.item_pending:
            return False
        if not self.session.use_consumable(key):
            return False
        kind = article.kind

        _, _, pw, ph = self._pet_rect()
        dpr = pw / max(1, self.width())
        cote_logique = max(24, int(round(SIZE_RATIO * ph / dpr)))
        cote_physique = cote_logique * dpr

        item = ItemWindow(kind, self._picker.pick(kind), cote_logique,
                          consumable=key)
        mon = self.current_monitor()
        sol = floor_y(mon.work, int(cote_physique))

        # Côté choisi sur la place disponible, distance tirée dans la fourchette.
        wl, _, ww, _ = mon.work
        centre = self._x + pw / 2.0
        ecart = self._picker._rng.uniform(ITEM_SPAWN_MIN, ITEM_SPAWN_MAX) * pw
        cible = centre + (-ecart if centre > wl + ww / 2.0 else ecart)
        cible = max(float(wl), min(float(wl + ww - cote_physique), cible))

        item.show()
        item.place(cible - cote_physique / 2.0,
                   sol - ITEM_DROP_HEIGHT * cote_physique)
        self.item = item
        self._sync_panel_items()
        self.clock.poke()
        log.info("objet posé : %s (%s)", key, kind)
        if self.diag:
            print(f"[diag] objet {key} en x={cible:.0f}", flush=True)
        return True

    def _step_item(self, dt: float) -> None:
        """Avance l'objet, et déclenche le soin quand les deux se rejoignent.

        **Un seul test pour les trois façons de les réunir** : que le robot y
        soit allé, qu'on l'y ait porté, ou qu'on ait traîné l'objet jusqu'à lui,
        c'est la même distance entre les deux centres qui décide.
        """
        item = self.item
        if item is None:
            return
        if item.gone:
            self.item = None
            self._sync_panel_items()
            return

        _, _, pw, ph = self._pet_rect()
        dpr = pw / max(1, self.width())
        sol = floor_y(self.current_monitor().work, int(item.side * dpr))

        if item.state == "expiring":
            if item.expire_step(dt):
                if item.gone:
                    # Jamais rejoint : on rend le délai plutôt que de le faire
                    # payer, et le bouton redevient disponible.
                    self.session.refund_consumable(item.consumable)
                    log.info("objet %s évaporé, article rendu", item.consumable)
            return

        item.step(dt, sol)

        if item.eaten or item.state in ("consumed", "expiring"):
            return

        ix, iy = item.center(dpr)
        px = self._x + pw / 2.0
        py = self._y + ph / 2.0
        if math.hypot(ix - px, iy - py) <= REACH * pw:
            self._consume_item(item)

    def _consume_item(self, item: ItemWindow) -> None:
        if not item.consume():
            return
        applied = self.session.apply_consumable(item.consumable)
        if applied:
            self._celebrate_care(item.consumable, applied)
        if self.locomotion is not None:
            self.locomotion.stop()

    def _sync_panel_items(self) -> None:
        """Tient le panneau au courant : un soin par objet n'est offert que
        si le bureau est libre. Le panneau ne surveille rien de lui-même —
        c'est la fenêtre qui a la boucle de rendu."""
        panel = self.panel
        if panel is None:
            return
        if panel.item_pending != self.item_pending:
            panel.item_pending = self.item_pending
            panel.update()

    def _close_item(self) -> None:
        if self.item is not None:
            self.item.close()
            self.item = None

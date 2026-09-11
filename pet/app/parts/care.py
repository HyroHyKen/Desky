"""Ce que le panneau de soin déclenche sur le pet (CDC §13, §14).

Extrait de `window` au lot L10. Le panneau émet des intentions — soigner,
changer une couleur, acheter un chapeau, renommer, réinitialiser — et ce module
est ce qui leur répond côté robot : appliquer, célébrer, reconstruire la
géométrie, replacer la fenêtre.

C'était le plus gros bloc de `window`, et le moins lié au reste : rien ici ne
touche à la boucle de rendu ni à la physique. Seule la reconstruction du robot
franchit la frontière, et elle le fait en un point unique.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from ...anim.layers import Animator
from ...geometry.builder import build
from ...ui.item import ITEM_KINDS
from ...ui.panel import CarePanel
from ...feedback import bus
from .. import win32

# Jeu entre le haut du pet et le bas du panneau, en pixels logiques.
PANEL_GAP = 8


log = logging.getLogger("desky.window")


class CareMixin:
    """Réponses du pet aux intentions du panneau."""

    # -- panneau de soin (lot L6 phase B) ------------------------------------

    @property
    def panel_open(self) -> bool:
        return (self.panel is not None and self.panel.isVisible()
                and not self.panel.closing)

    def _ensure_panel(self) -> CarePanel:
        if self.panel is None:
            self.panel = CarePanel(self.session, self.genome)
            self.panel.care_requested.connect(self._on_care)
            self.panel.quit_requested.connect(self.quit_requested.emit)
            self.panel.name_submitted.connect(self._on_name)
            self.panel.appearance_chosen.connect(self._on_appearance)
            self.panel.item_chosen.connect(self._on_cosmetic)
            self.panel.reset_requested.connect(self._on_reset)
            self.panel.autostart_toggled.connect(self._on_autostart)
            self.panel.item_preview = self.cosmetic_preview
        return self.panel

    def toggle_panel(self) -> None:
        # Tant que le robot n'a pas de nom, le clic droit ne donne rien : le
        # menu de soin parlerait d'un pet qu'on n'a pas encore accueilli, et il
        # détournerait de la seule chose à faire — le baptiser.
        if self._onboarding:
            return
        if self.panel_open:
            self.panel.close_panel()
            return
        panel = self._ensure_panel()
        panel.item_pending = self.item_pending
        panel.open_page("menu")
        self.place_panel()
        panel.open_panel()
        # Le pet cesse de flâner tant qu'on s'occupe de lui : un panneau qui
        # court après un robot en mouvement serait illisible, et rester tranquille
        # quand on le regarde est de toute façon ce qu'il ferait.
        self.clock.poke()

    def place_panel(self) -> None:
        """Centre le panneau au-dessus de la tête du pet.

        **Seul point du projet qui franchit la frontière des deux espaces de
        coordonnées.** Le pet vit en pixels physiques de bout en bout ; le
        panneau est un widget Qt ordinaire, donc en pixels logiques. La
        conversion se fait ici, une fois, par le rapport mesuré entre les deux.
        """
        panel = self.panel
        if panel is None:
            return
        _, _, pw, ph = self._pet_rect()
        dpr = pw / max(1, self.width())
        # Le haut du pet visible n'est pas le haut de la fenêtre : le bandeau de
        # la bulle est transparent, et le panneau doit se poser sur la tête.
        bandeau = ph * self.scene.headroom if self.scene is not None else 0.0
        haut_logique = (self._y + bandeau) / dpr
        cx = (self._x + pw / 2.0) / dpr
        panel.move(int(cx - panel.width() / 2.0),
                   int(haut_logique - panel.height() - PANEL_GAP))

    def _on_care(self, kind: str) -> None:
        """Un bouton de soin a été pressé.

        Deux chemins, et c'est la seule branche du mécanisme : la caresse agit
        tout de suite, les trois autres **font apparaître un objet** et
        n'agissent qu'une fois le robot et l'objet réunis.
        """
        if kind in ITEM_KINDS:
            self._spawn_item(kind)
            return
        applied = self.session.care(kind)
        if not applied:
            return
        self._celebrate_care(kind, applied)

    def _celebrate_care(self, kind: str, applied: dict) -> None:
        # Token versé ici, c'est-à-dire à la **livraison** du soin et non au
        # clic du bouton (§14). Depuis que trois soins sur quatre passent par un
        # objet posé sur le bureau, créditer au bouton laisserait faire
        # apparaître dix gamelles sans jamais en livrer une.
        gagne = self.session.award_tokens()

        # Le `brain` élira `happy_bounce` au prochain tick ; la courbe est jouée
        # tout de suite, pour que le geste ait une réponse immédiate.
        if self.animator is not None:
            self.animator.play("celebrate")
        besoin = max(applied, key=lambda k: abs(applied[k]))
        # Le fait est annoncé **à la livraison**, au même endroit que le token :
        # c'est là que le soin a réellement eu lieu. L'annoncer au clic ferait
        # partir la gerbe pour une gamelle qui n'a pas encore été rejointe.
        bus.emit("soin_accepte", soin=kind)
        self.show_in_eyes(besoin, besoin, seconds=1.6)
        self.clock.poke()
        if self.panel is not None:
            self.panel.update()
        if self.diag:
            print(f"[diag] token +{gagne} -> {self.session.tokens}", flush=True)
        if self.diag:
            print(f"[diag] soin {kind} -> {applied}", flush=True)

    def _on_appearance(self, param: str, value: str) -> None:
        """Applique un choix de couleur, et le montre tout de suite.

        Le robot est **reconstruit** plutôt que recoloré à chaud. La couleur du
        corps et l'accent traversent la géométrie — teinte des parties, couleur
        des pupilles, configuration de la passe toon — et les retoucher une par
        une reviendrait à recopier `build`. Elle coûte 7 ms mesurées, une fois
        par clic : c'est gratuit à cette échelle.
        """
        if not self.session.set_appearance(param, value):
            return
        self._rebuild_robot()
        log.info("apparence : %s = %s", param, value)

    def _on_cosmetic(self, slot: str, key: str) -> None:
        """Un article a été touché : on l'achète, ou on le porte.

        **Un seul geste pour les deux**, et c'est volontaire : appuyer sur un
        article qu'on ne possède pas l'achète et le met aussitôt, appuyer sur un
        article possédé le porte. Séparer « acheter » de « porter » aurait
        demandé deux boutons par vignette, donc deux pictogrammes de plus à
        distinguer pour rien.
        """
        from ...geometry.cosmetics import NONE

        if key != NONE and not self.session.owns(key):
            if not self.session.buy(key):
                bus.emit("achat_refuse", emplacement=slot, cle=key,
                         raison="fonds")
                return
            bus.emit("article_achete", emplacement=slot, cle=key)
            if self.diag:
                print(f"[diag] achat {key} -> solde {self.session.tokens}",
                      flush=True)
        if not self.session.wear(slot, key):
            return
        self._rebuild_robot()
        if self.panel is not None:
            self.panel.update()
        log.info("%s : %s", slot, key or "aucun")

    def _on_autostart(self) -> None:
        """Bascule le lancement au démarrage (§13)."""
        actif = not win32.autostart_enabled()
        if win32.set_autostart(actif):
            log.info("lancement au démarrage : %s", "oui" if actif else "non")
        if self.panel is not None:
            self.panel.update()

    def _on_reset(self) -> None:
        """Purge tout et quitte. Le §13 demande un bouton, le voici.

        **Tout** : besoins, nom, génome, tokens, inventaire, réglages. Une
        réinitialisation partielle n'en serait pas une, et le §13 parle de purge
        des données. L'application se ferme derrière : recréer un robot dans une
        session qui porte encore l'ancien en mémoire serait une source de bugs
        pour un geste qui arrive une fois dans la vie du produit.
        """
        if self.panel is not None:
            # Sans animation : la session que le panneau peint est sur le point
            # d'être effacée, et le regarder se fermer joliment en lisant des
            # données à demi réinitialisées n'a rien de gracieux.
            self.panel.close_panel(immediat=True)
        log.info("réinitialisation demandée")
        try:
            self.session.flush(force=False)
        except OSError:
            pass
        self._purge_on_exit = True
        self.quit_requested.emit()

    def _rebuild_robot(self) -> None:
        """Reconstruit le robot avec son costume courant, et le réanime.

        Partagé par le changement de couleur et celui de chapeau : les deux
        passent par `overrides`, donc ils ont exactement le même effet.
        """
        if self.scene is None:
            return
        self.robot = build(self.genome, self.session.appearance)
        self.scene.set_robot(self.robot)
        if self.animator is not None:
            self.animator = Animator.for_robot(
                self.robot, seed=int(self.genome.get("seed", 0)))
        self._hat_previews.clear()
        self.clock.poke()

    def cosmetic_preview(self, slot: str, key: str):
        """Aperçu d'un article, rendu **sur le robot de l'utilisateur**.

        Rendu une fois puis gardé : huit vignettes coûtent huit reconstructions
        de maillage, soit une soixantaine de millisecondes à l'ouverture du
        rayon, et rien ensuite. Le cache est vidé dès que l'apparence change,
        sinon les aperçus montreraient l'ancienne couleur.

        Le robot réel est **remis en place** à la fin : la scène n'a qu'un
        maillage à la fois, et le laisser sur le dernier chapeau essayé
        remplacerait le pet à l'écran.
        """
        from PySide6.QtGui import QPixmap

        if self.scene is None or self.robot is None:
            return None
        cache_key = slot + ":" + key
        if cache_key in self._hat_previews:
            return self._hat_previews[cache_key]

        # Les **autres** emplacements gardent ce qui est porté : on montre le
        # robot tel qu'il sera, pas l'article seul sur une tête nue.
        costume = dict(self.session.appearance)
        costume[slot] = key
        try:
            self.scene.set_robot(build(self.genome, costume))
            self.rc.begin()
            self.scene.draw(yaw=0.0, pitch=0.14)
            px = self.rc.read_rgba()
            image = QImage(px.data, px.shape[1], px.shape[0], px.shape[1] * 4,
                           QImage.Format.Format_RGBA8888_Premultiplied).copy()
        finally:
            self.scene.set_robot(self.robot)
        pixmap = QPixmap.fromImage(image)
        self._hat_previews[cache_key] = pixmap
        return pixmap

    def _on_name(self, name: str) -> None:
        accepte = self.session.set_name(name)

        # Le baptême se termine dès que le robot **a** un nom, et non dès que
        # celui-ci vient d'être accepté. La nuance est un garde-fou : un refus
        # — nom déjà posé par une autre voie, par exemple — laissait sinon
        # l'utilisateur sans menu contextuel, définitivement, sans rien pour
        # s'en sortir.
        if not self.session.name:
            return
        self._onboarding = False
        self._intro_phase = ""
        if not accepte:
            return
        if self.panel is not None:
            self.panel.close_panel()
        if self.animator is not None:
            self.animator.play("celebrate")
        self.show_in_eyes("robot", "robot", seconds=2.0)
        log.info("robot baptisé")

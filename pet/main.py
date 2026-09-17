"""Bootstrap : awareness DPI, instance unique, réglages, journal, fenêtre (CDC §5).

Ordre imposé : l'awareness DPI doit être posée **avant** la création de
QApplication, donc avant tout import qui instancierait quoi que ce soit de Qt.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import APP_ID, APP_NAME, VERSION
from .app import win32
from .state import save

log = logging.getLogger("desky.main")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME.lower(), description=f"{APP_NAME} {VERSION}")
    parser.add_argument("--diag", action="store_true",
                        help="affiche régime, fps, CPU et état du hit-testing toutes les 2 s")
    parser.add_argument("--size", type=int, default=None,
                        help=f"hauteur logique du pet en pixels "
                             f"({save.SIZE_MIN}-{save.SIZE_MAX}, persistée)")
    parser.add_argument("--verbose", action="store_true",
                        help="journal en DEBUG, également sur la console")
    parser.add_argument("--purge", action="store_true",
                        help="supprime toutes les données locales et quitte")
    parser.add_argument("--gait", default="hop", choices=("hop", "glide"),
                        help="démarche : sauts ou glissement")
    parser.add_argument("--run-seconds", type=float, default=0.0,
                        help="quitte automatiquement après N secondes "
                             "(exécution des critères d'acceptation en script)")
    args = parser.parse_args(argv)

    log_path = save.setup_logging(verbose=args.verbose)

    if args.purge:
        removed = save.purge_data()
        print(f"Données supprimées dans {save.app_dir()} : "
              f"{', '.join(removed) if removed else 'rien à supprimer'}")
        return 0

    dpi_mode = win32.set_dpi_awareness()

    instance = win32.SingleInstance(APP_ID)
    if instance.already_running:
        print(f"{APP_NAME} est déjà lancé.", file=sys.stderr)
        return 0

    # Après le mutex : on est seul, donc les temporaires trouvés viennent
    # forcément d'un arrêt brutal précédent.
    save.sweep_temp_files()

    settings = save.settings_store()
    settings.load()
    if args.size is not None:
        settings.set(size=max(save.SIZE_MIN, min(save.SIZE_MAX, args.size)))

    genome, first_run = save.load_or_create_genome()
    if first_run:
        log.info("premier lancement : nouveau robot")

    # État vivant du lot L6. Chargé ici, comme les réglages et le génome : le
    # `brain` doit avoir facturé l'absence hors ligne avant le premier tick.
    from .brain.session import Session
    session = Session()
    session.load()
    if session.offline_seconds > 0.0:
        log.info("absence facturée : %.1f h", session.offline_seconds / 3600.0)

    log.info("démarrage %s %s (awareness DPI : %s)", APP_NAME, VERSION, dpi_mode)

    # Imports Qt après l'awareness DPI.
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .app.window import PetWindow
    from .genome.generator import GenomeGenerationError
    from .render.context import ContextCreationError

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)

    # Écran de lancement (lot L19). Ouvert **avant** la fenêtre du robot : ce
    # qui suit construit un contexte OpenGL et assemble un robot, et c'est
    # exactement le temps qu'il est là pour couvrir. Seul son fondu d'entrée
    # s'ajoute au démarrage ; la tenue recouvre un chargement qui avait lieu de
    # toute façon.
    from .ui.splash import Splash

    splash = Splash()
    ecran_demarrage = win32.monitor_from_point(*win32.get_cursor_pos())
    el, et, ew, eh = ecran_demarrage.work
    splash.begin((el + ew / 2.0, et + eh * 0.44),
                 dpr=max(1.0, splash.devicePixelRatioF()))
    splash.pump_entrance(app)
    # Une fenêtre Qt.Tool n'est pas une fenêtre « primaire » pour Qt : sa
    # fermeture ne déclenche donc pas la sortie. C'est structurel pour ce
    # produit, qui n'a ni barre des tâches ni alt-tab — la sortie est pilotée
    # explicitement, et le menu contextuel du lot L7 s'y branchera.
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow(settings, genome, diag=args.diag, session=session)
    window.configure_locomotion(gait=args.gait)
    window.show()
    # Deux fenêtres topmost n'ont pas d'ordre garanti entre elles : sans cette
    # réaffirmation, le robot apparaît parfois **devant** le logo au moment
    # précis où celui-ci est censé le couvrir.
    win32.raise_above(int(splash.winId()), int(window.winId()))

    try:
        window.start()
    except GenomeGenerationError as exc:
        # L'écran de lancement est retiré avant la boîte de dialogue : un logo
        # posé par-dessus un message d'erreur serait la dernière chose que
        # l'utilisateur voit avant de désinstaller.
        splash.close()
        log.error("génome ingénérable : %s", exc)
        QMessageBox.critical(
            None, APP_NAME,
            f"{APP_NAME} n'a pas pu créer de robot.\n\n{exc}",
        )
        return 1
    except ContextCreationError as exc:
        # Repli GPU (CDC §15) : message clair plutôt qu'un crash. L'écran de
        # lancement est libéré d'abord — un logo posé par-dessus le message
        # d'erreur serait la dernière chose à voir avant de désinstaller.
        splash.close()
        log.error("création du contexte OpenGL impossible : %s", exc)
        QMessageBox.critical(
            None, APP_NAME,
            f"{APP_NAME} a besoin d'OpenGL 3.3 et n'a pas pu créer de contexte "
            f"graphique.\n\nDétail : {exc}\n\n"
            "Mettre à jour le pilote de la carte graphique résout généralement "
            "le problème.",
        )
        return 1

    # Le robot est prêt : l'écran peut s'effacer. Il ne part pas pour autant
    # sur-le-champ — `Fondu` lui impose un temps plein minimum, sans quoi le
    # logo clignoterait sur une machine rapide.
    splash.finish()

    def shutdown() -> None:
        window.shutdown()
        window.close()
        # Purge demandée depuis les réglages (§13). Faite **ici**, après la
        # fermeture de la fenêtre et de ses fichiers : sous Windows, un journal
        # encore ouvert n'est pas supprimable, et une purge qui laisse des
        # restes n'en est pas une.
        if getattr(window, "_purge_on_exit", False):
            save.close_logging()
            efface = save.purge_data()
            print("[desky] réinitialisation : %d fichiers effacés"
                  % len(efface))
        app.quit()

    window.quit_requested.connect(shutdown)
    # Filet de sécurité : couvre aussi une fermeture qui ne passerait pas par
    # `shutdown`, par exemple une session Windows qui se termine.
    app.aboutToQuit.connect(window.shutdown)

    if args.diag:
        print(f"[diag] {APP_NAME} {VERSION} | awareness DPI : {dpi_mode}")
        print(f"[diag] données : {save.app_dir()}")
        print(f"[diag] journal : {log_path}")
        print("[diag] clic gauche = attraper et déplacer, "
              "clic droit = panneau de soin")

    # Premier lancement : le robot arrive dans un carton (§13). Le repère est
    # l'absence de **nom**, et non le drapeau `first_run` du génome : le nom est
    # ce qui manque vraiment tant que le baptême n'a pas eu lieu, et ce repère
    # survit à un plantage entre le tirage du génome et la saisie.
    unboxing = None
    if not session.name:
        from .ui.unboxing import HEIGHT as BOX_WINDOW_H
        from .ui.unboxing import Unboxing

        window.begin_onboarding()
        window.hide()

        ecran = window.current_monitor()
        wl, wt, ww, wh = ecran.work
        dpr = max(1.0, window.devicePixelRatioF())
        # Le carton tombe au **milieu** de l'écran, comme demandé, et non au
        # sol : c'est en sortant que le robot descendra se poser.
        centre_x = wl + ww / 2.0
        milieu_y = wt + wh * 0.42

        unboxing = Unboxing()
        unboxing.opened.connect(
            lambda: window.emerge_at(centre_x, milieu_y + 40.0))
        unboxing.start(int(centre_x / dpr),
                       int(milieu_y / dpr - BOX_WINDOW_H * 0.55),
                       screen_top=int(wt / dpr))
        log.info("premier lancement : carton lâché")
        if args.diag:
            print("[diag] premier lancement : clic sur le carton pour ouvrir")

    if args.run_seconds > 0:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(int(args.run_seconds * 1000), shutdown)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

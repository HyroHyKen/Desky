"""Journée synthétique : rejeu du comportement sur 24 h, rapport et courbes.

Deux critères d'acceptation du lot L6 ne se vérifient qu'ici — « aucun
clignotement entre actions » et « aucune action inatteignable ni dominante ».
L'outil sert aussi et surtout à **régler** : il a trouvé, dans l'ordre, un
`look_around` structurellement inatteignable, une `energy` qui ne décidait
jamais rien, une flânerie à 0,2 % de la journée, un pet qui broyait du noir
chaque matin, et 101 épisodes de moins d'une seconde sur `follow_cursor`.

    .venv/Scripts/python.exe -m tools.day_sim
    .venv/Scripts/python.exe -m tools.day_sim --profile bureau --care reasonable
    .venv/Scripts/python.exe -m tools.day_sim --profile bureau --out journee.png
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

# La console Windows n'est pas en UTF-8 par défaut, et ce rapport est truffé
# d'accents. Sans ce réglage il se lit en mojibake, ce qui est un défaut d'outil
# de jugement : on ne relit pas volontiers un tableau illisible.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pet.brain.needs import NEEDS  # noqa: E402  (après le réglage de stdout)
from pet.brain.replay import Report, replay
from pet.brain.trace import PROFILES, Trace, synthetic_day

# Seuils des critères d'acceptation, rassemblés ici pour être discutables.
DOMINANCE_LIMIT = 60.0          # % du temps de présence
FLICKER_FLOOR = 1.0             # s : en dessous, un épisode ne se lit pas
MEDIAN_FLOOR = 8.0              # s : médiane d'épisode acceptable

NEED_COLORS = {
    "hunger": "#C4703A",
    "fun": "#3E8C6E",
    "energy": "#4A78B8",
    "hygiene": "#8A6BAE",
}


def show(label: str, trace: Trace, report: Report) -> bool:
    """Affiche le rapport et retourne True si les critères passent."""
    print("")
    print("=== %s — %.0f h, %d changements de contexte"
          % (label, trace.duration / 3600, len(trace.samples)))

    etats = trace.histogram()
    print("  contexte : " + "  ".join(
        "%s %.1fh" % (k, v / 3600) for k, v in etats.items() if v > 0))

    wall = report.share()
    pres = report.share_present()
    print("  %-15s%9s%10s" % ("action", "journée", "présence"))
    for name, part in sorted(wall.items(), key=lambda kv: -kv[1]):
        print("  %-15s%7.1f %%%8.1f %%" % (name, part, pres.get(name, 0.0)))

    stats = report.episode_stats()
    print("  épisodes : %.0f, médiane %.1f s, p90 %.1f s, mini %.2f s — "
          "%.1f changements/h"
          % (stats["episodes"], stats["median"], stats["p90"], stats["min"],
             report.changes_per_hour))

    courts = collections.Counter(
        n for n, d in report.episodes if d < FLICKER_FLOOR)
    if courts:
        print("  sous la seconde : " + ", ".join(
            "%s x%d" % (n, c) for n, c in courts.most_common()))
    flicker = report.flickers(FLICKER_FLOOR)
    if flicker:
        print("  dont clignotement : " + ", ".join(
            "%s x%d" % (n, c) for n, c in sorted(flicker.items())))

    print("  besoins  : " + "  ".join(
        "%s %.0f/%.0f/%.0f" % (n, report.needs_min[n], report.needs_mean[n],
                               report.needs_max[n]) for n in NEEDS)
        + "   (mini/moyen/maxi)")

    humeurs = sorted(report.mood_seconds.items(), key=lambda kv: -kv[1])
    print("  humeur   : " + "  ".join(
        "%s %.0f%%" % (n, 100.0 * s / report.duration) for n, s in humeurs))
    if report.cares:
        print("  soins    : " + "  ".join(
            "%s x%d" % (k, v) for k, v in sorted(report.cares.items())))

    ok = True
    verdicts = (
        ("aucun épisode sous %.0f s hors réflexe ni interruption"
         % FLICKER_FLOOR, not flicker),
        ("médiane d'épisode au-dessus de %.0f s" % MEDIAN_FLOOR,
         stats["median"] >= MEDIAN_FLOOR),
        ("aucune action au-delà de %.0f %% de la présence" % DOMINANCE_LIMIT,
         not report.dominant(DOMINANCE_LIMIT)),
    )
    for verdict, passed in verdicts:
        print("  [%s] %s" % ("ok   " if passed else "ECHEC", verdict))
        ok = ok and passed
    return ok


def draw(path: Path, trace: Trace, report: Report, width: int = 1280,
         height: int = 420) -> None:
    """Courbes de besoins, et la bande des actions en dessous."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter,
                               QPen)
    QGuiApplication.instance() or QGuiApplication([])

    top, bottom, left, right = 34, 96, 46, 14
    plot = QRect(left, top, width - left - right, height - top - bottom)

    image = QImage(width, height, QImage.Format.Format_RGBA8888_Premultiplied)
    image.fill(QColor("#F4F3EF"))
    painter = QPainter(image)
    font = QFont()
    font.setPixelSize(11)
    painter.setFont(font)

    def x_of(t: float) -> int:
        return plot.left() + int(plot.width() * t / max(1.0, trace.duration))

    def y_of(v: float) -> int:
        return plot.bottom() - int(plot.height() * v / 100.0)

    right_align = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    centre = int(Qt.AlignmentFlag.AlignHCenter)
    gauche = int(Qt.AlignmentFlag.AlignLeft)

    # Grille : une ligne par tranche de 25 points, une par tranche de 3 h.
    for level in (0, 25, 50, 75, 100):
        painter.setPen(QPen(QColor("#DCDAD3"), 1))
        painter.drawLine(plot.left(), y_of(level), plot.right(), y_of(level))
        painter.setPen(QColor("#8B8880"))
        painter.drawText(QRect(0, y_of(level) - 8, left - 6, 16), right_align,
                         str(level))
    for hour in range(0, int(trace.duration / 3600) + 1, 3):
        x = x_of(hour * 3600.0)
        painter.setPen(QPen(QColor("#DCDAD3"), 1))
        painter.drawLine(x, plot.top(), x, plot.bottom())
        painter.setPen(QColor("#8B8880"))
        painter.drawText(QRect(x - 20, plot.bottom() + 3, 40, 14), centre,
                         "%dh" % hour)

    for need in NEEDS:
        painter.setPen(QPen(QColor(NEED_COLORS[need]), 2))
        previous = None
        for t, values, _ in report.curve:
            point = (x_of(t), y_of(values[need]))
            if previous is not None:
                painter.drawLine(previous[0], previous[1], point[0], point[1])
            previous = point

    # Bande des actions : une teinte stable par action, tirée de son rang.
    band = QRect(plot.left(), plot.bottom() + 20, plot.width(), 18)
    names = sorted(set(a for _, _, a in report.curve))
    hues = dict((name, int(360.0 * i / max(1, len(names))))
                for i, name in enumerate(names))
    for index, sample in enumerate(report.curve):
        t, _, action = sample
        end = (report.curve[index + 1][0] if index + 1 < len(report.curve)
               else trace.duration)
        painter.fillRect(x_of(t), band.top(), max(1, x_of(end) - x_of(t)),
                         band.height(), QColor.fromHsv(hues[action], 120, 205))

    painter.setPen(QColor("#2A2A28"))
    painter.drawText(QRect(left, 8, width - left, 18), gauche,
                     "%s — besoins sur %.0f h" % (trace.label,
                                                  trace.duration / 3600))
    painter.drawText(QRect(left, band.bottom() + 4, width - left, 18), gauche,
                     "bande basse : action élue — " + ", ".join(names))
    # Légende : un trait de la couleur du besoin, suivi de son nom.
    x = left + 230
    for need in NEEDS:
        painter.setPen(QPen(QColor(NEED_COLORS[need]), 3))
        painter.drawLine(x, 16, x + 16, 16)
        painter.setPen(QColor("#2A2A28"))
        painter.drawText(QRect(x + 22, 8, 80, 18), gauche, need)
        x += 100

    painter.end()
    ok = image.save(str(path))
    print("")
    print("courbes %s : %s (%dx%d)"
          % ("ecrites" if ok else "ECHEC", path, width, height))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="journée synthétique du brain")
    ap.add_argument("--profile", default="all",
                    choices=("all",) + tuple(PROFILES))
    ap.add_argument("--care", default="all",
                    choices=("all", "none", "reasonable"))
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--out", type=Path, default=None,
                    help="PNG des courbes du dernier profil rejoué")
    args = ap.parse_args(argv)

    profiles = tuple(PROFILES) if args.profile == "all" else (args.profile,)
    cares = ("none", "reasonable") if args.care == "all" else (args.care,)

    seen: dict[str, float] = {}
    ok = True
    last = None
    for profile in profiles:
        for care in cares:
            trace = synthetic_day(profile, args.seed, args.hours)
            _, report = replay(trace, care=care, seed=args.seed)
            ok = show("%s / soin %s" % (profile, care), trace, report) and ok
            for name, seconds in report.seconds_by_action.items():
                seen[name] = seen.get(name, 0.0) + seconds
            last = (trace, report)

    # La joignabilité se juge sur la **suite entière** : un profil sans vidéo ne
    # peut pas jouer `sit_and_watch`, et un profil bien soigné ne peut pas
    # jouer `bored_slump`. Les en accuser serait un faux positif, donc le
    # verdict ne tombe que quand toute la suite a été rejouée.
    morts = tuple(n for n, s in seen.items() if s <= 0.0)
    complet = args.profile == "all" and args.care == "all"
    print("")
    if complet:
        print("[%s] toutes les actions jouées au moins une fois sur la suite%s"
              % ("ok   " if not morts else "ECHEC",
                 "" if not morts else " — mortes : %s" % (morts,)))
        ok = ok and not morts
    elif morts:
        print("(jamais jouées sur ce sous-ensemble : %s — verdict réservé à la "
              "suite complète)" % (morts,))

    if args.out is not None and last is not None:
        draw(args.out, last[0], last[1])

    print("")
    print("TOUS LES CRITERES PASSENT" if ok else "DES CRITERES ECHOUENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

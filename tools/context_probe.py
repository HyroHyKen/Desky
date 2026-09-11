"""Sonde de contexte : montre quelle condition bloque, seconde par seconde.

`watching` combine cinq conditions (CDC §11 et son critère réécrit au lot L5).
Quand il ne se déclenche pas, savoir *laquelle* manque vaut mieux que deviner.
Cette sonde affiche l'arbre de décision complet, sans lancer le pet.

    .venv/Scripts/python.exe -m tools.context_probe
    .venv/Scripts/python.exe -m tools.context_probe --seconds 120

Le nom du process au premier plan et celui de la source audio sont affichés
**ici uniquement** : ce sont des données de diagnostic à l'écran, et le journal
du pet n'en reçoit jamais (CDC §11).
"""

from __future__ import annotations

import argparse
import sys
import time

from pet.brain import sensors
from pet.brain.sensors import (
    AUDIO_ONLY_SOURCES,
    UWP_HOSTS,
    VIDEO_SOURCES,
    WATCH_COVERAGE,
    WATCH_MEDIA_SECONDS,
    WATCH_STILL_SECONDS,
    Sensors,
)

OUI, NON = "oui", "NON"


def verdict(capteurs: Sensors) -> tuple[str, list[str]]:
    """Décision `watching`, et la liste des conditions qui manquent."""
    media = capteurs.media
    source = media.source.lower()
    manque: list[str] = []

    if not media.playing:
        manque.append("aucun son détecté")
    elif media.seconds < WATCH_MEDIA_SECONDS:
        manque.append(f"son depuis {media.seconds:.0f} s "
                      f"(il en faut {WATCH_MEDIA_SECONDS:.0f})")

    still = capteurs.cursor.still_seconds
    if still < WATCH_STILL_SECONDS:
        manque.append(f"curseur immobile depuis {still:.1f} s "
                      f"(il en faut {WATCH_STILL_SECONDS:.0f})")

    coverage = capteurs.foreground.coverage
    foreground = capteurs.foreground.process.lower()
    if source and foreground != source and foreground not in UWP_HOSTS:
        manque.append(f"le son vient de {source} mais l'avant-plan est "
                      f"{foreground or '?'} : travailler avec du son derriere "
                      f"n'est pas regarder")
    if source in AUDIO_ONLY_SOURCES:
        manque.append(f"{source} est un lecteur musical, exclu par principe")
    elif source and source not in VIDEO_SOURCES and coverage < WATCH_COVERAGE:
        manque.append(f"fenêtre couvrant {coverage:.0%} de l'écran "
                      f"(il en faut {WATCH_COVERAGE:.0%})")

    return capteurs.context.state, manque


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="sonde de contexte système")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args(argv)

    capteurs = Sensors()
    print(f"sonde de contexte — {args.seconds:.0f} s, une ligne par "
          f"{args.interval:.1f} s")
    print("mets une vidéo en grand, puis de la musique en petite fenêtre, "
          "et compare.\n")

    debut = time.perf_counter()
    prochain = debut
    while time.perf_counter() - debut < args.seconds:
        now = time.perf_counter()
        capteurs.observe_cursor(now)

        if now >= prochain:
            prochain = now + args.interval
            capteurs.observe_slow(now)
            ctx = capteurs.context
            etat, manque = verdict(capteurs)

            print(f"[{now - debut:5.1f}s] {etat:9s} "
                  f"inactif={ctx.idle_seconds:5.1f}s  "
                  f"curseur immobile={ctx.cursor_still_seconds:5.1f}s  "
                  f"avant-plan={ctx.foreground_category:8s} "
                  f"({capteurs.foreground.process or '?'}) "
                  f"couverture={capteurs.foreground.coverage:5.0%}  "
                  f"plein_écran={OUI if ctx.fullscreen else NON}")
            print(f"          média={OUI if ctx.media_playing else NON} "
                  f"depuis {ctx.media_seconds:5.1f}s "
                  f"source={capteurs.media.source or '?'} "
                  f"({ctx.media_category})")
            if etat == "watching":
                print("          -> WATCHING : toutes les conditions sont réunies")
            elif manque:
                print(f"          -> pas watching : {' | '.join(manque)}")

        time.sleep(0.02)

    print("\nfin de la sonde")
    return 0


if __name__ == "__main__":
    sys.exit(main())

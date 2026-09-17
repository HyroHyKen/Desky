"""Réécrit le bouton de téléchargement du site à chaque publication (lot L16).

    python -m tools.site_release 0.13.0 dist/Desky-0.13.0-setup.exe

Le site est statique et n'appelle aucune API : le lien pointe vers une version
**précise**, donc vérifiable, et la page affiche son numéro et son poids sans
une ligne de JavaScript. Le prix à payer est qu'il faut le réécrire à chaque
release — c'est ce que fait ce script, appelé par le workflow de publication.

**Pourquoi des marqueurs plutôt qu'une expression régulière sur le lien.** Une
expression qui chercherait `href="…setup.exe"` finirait un jour par attraper
celui de la page de vérification, ou par ne plus rien trouver après une
reformulation. Les marqueurs délimitent une zone dont ce script est le seul
propriétaire : à l'intérieur il écrase tout, à l'extérieur il ne touche à rien.
Et `tests/test_site.py` échoue si un marqueur disparaît, donc la faute est
découverte au commit et non au moment de publier.

**Le poids est en mébioctets**, parce que c'est ce que l'explorateur Windows
affichera à côté du fichier téléchargé. Annoncer 41 Mo pour un fichier que
Windows présente comme 39 Mo ferait douter de l'intégrité du téléchargement.
"""

from __future__ import annotations

import pathlib
import sys

DEBUT = "<!-- telechargement:debut"
FIN = "<!-- telechargement:fin -->"

DEPOT = "https://github.com/HyroHyKen/Desky"

# Une entrée par page : le chemin, et les mots de sa langue. Ajouter une langue
# au site revient à ajouter une ligne ici.
PAGES: dict[str, dict[str, str]] = {
    "docs/index.html": {
        "note": ("<!-- telechargement:debut — bloc régénéré à chaque release par\n"
                 "         tools/site_release.py. Ne pas modifier à la main : la publication\n"
                 "         réécrit tout ce qui se trouve entre les deux marqueurs. -->"),
        "titre": "Télécharger pour Windows",
        "meta": "Version %s · %d Mo · Windows 10 et 11",
    },
    "docs/en/index.html": {
        "note": ("<!-- telechargement:debut — block regenerated on every release by\n"
                 "         tools/site_release.py. Do not edit by hand: publishing rewrites\n"
                 "         everything between the two markers. -->"),
        "titre": "Download for Windows",
        "meta": "Version %s · %d MB · Windows 10 and 11",
    },
}


def download_url(version: str, nom: str) -> str:
    """Lien d'un asset de release. `version` sans le « v » initial."""
    return "%s/releases/download/v%s/%s" % (DEPOT, version, nom)


def bloc(version: str, nom: str, mio: int, page: dict[str, str]) -> str:
    """Le fragment HTML complet, marqueurs compris."""
    return (
        '%s\n'
        '    <a class="telecharger" href="%s">\n'
        '      <span class="telecharger-titre">%s</span>\n'
        '      <span class="telecharger-meta">%s</span>\n'
        '    </a>\n'
        '    %s'
        % (page["note"], download_url(version, nom), page["titre"],
           page["meta"] % (version, mio), FIN)
    )


def rewrite(source: str, version: str, nom: str, mio: int,
            page: dict[str, str]) -> str:
    """Remplace la zone délimitée. Lève si un marqueur manque."""
    debut = source.find(DEBUT)
    fin = source.find(FIN)
    if debut < 0 or fin < 0 or fin < debut:
        raise ValueError("marqueurs de téléchargement absents ou inversés")
    return source[:debut] + bloc(version, nom, mio, page) + source[fin + len(FIN):]


def mebioctets(octets: int) -> int:
    return int(round(octets / (1024 * 1024)))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__.strip().splitlines()[2].strip())
        return 2

    version = argv[1].lstrip("v")
    installateur = pathlib.Path(argv[2])
    if not installateur.is_file():
        print("introuvable : %s" % installateur)
        return 1

    mio = mebioctets(installateur.stat().st_size)
    racine = pathlib.Path(__file__).resolve().parent.parent

    for relatif, page in PAGES.items():
        chemin = racine / relatif
        source = chemin.read_text(encoding="utf-8")
        try:
            sortie = rewrite(source, version, installateur.name, mio, page)
        except ValueError as exc:
            print("%s : %s" % (relatif, exc))
            return 1
        if sortie != source:
            chemin.write_text(sortie, encoding="utf-8")
            print("%s : %s, %d Mo" % (relatif, installateur.name, mio))
        else:
            print("%s : déjà à jour" % relatif)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

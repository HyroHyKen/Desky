"""Réécrit ce que le site dit de la version publiée (lot L16).

    python -m tools.site_release 1.0.0 dist/Desky-1.0.0-setup.exe

Le site est statique et n'appelle aucune API : le lien pointe vers une version
**précise**, donc vérifiable, et la page affiche son numéro et son poids sans
une ligne de JavaScript. Le prix à payer est qu'il faut le réécrire à chaque
release — c'est ce que fait ce script, appelé par le workflow de publication.

**Deux zones, et non une.** Le bouton visible, et les données structurées
`SoftwareApplication` du `<head>`. Ces dernières portent elles aussi le numéro
de version, le lien de téléchargement et le poids : les laisser figées
donnerait un site qui annonce la bonne version à l'œil et la mauvaise aux
moteurs et aux assistants, ce qui est pire que de ne rien déclarer du tout.

**Pourquoi des marqueurs plutôt qu'une expression régulière.** Une expression
qui chercherait `href="…setup.exe"` finirait un jour par attraper celui de la
page de vérification, ou par ne plus rien trouver après une reformulation. Les
marqueurs délimitent des zones dont ce script est le seul propriétaire : à
l'intérieur il écrase tout, à l'extérieur il ne touche à rien. Et
`tests/test_site.py` échoue si un marqueur disparaît, donc la faute est
découverte au commit et non au moment de publier.

**Le poids est en mébioctets**, parce que c'est ce que l'explorateur Windows
affichera à côté du fichier téléchargé. Annoncer 41 Mo pour un fichier que
Windows présente comme 39 ferait douter de l'intégrité du téléchargement.
"""

from __future__ import annotations

import json
import pathlib
import sys

DEBUT = "<!-- telechargement:debut"
FIN = "<!-- telechargement:fin -->"

DONNEES_DEBUT = "<!-- donnees:debut"
DONNEES_FIN = "<!-- donnees:fin -->"

DEPOT = "https://github.com/HyroHyKen/Desky"
SITE = "https://hyrohyken.github.io/Desky/"

# Une entrée par page : le chemin, et tout ce qui dépend de sa langue. Ajouter
# une langue au site revient à ajouter une ligne ici.
PAGES: dict[str, dict[str, str]] = {
    "docs/index.html": {
        "note": ("<!-- telechargement:debut — bloc régénéré à chaque release par\n"
                 "         tools/site_release.py. Ne pas modifier à la main : la publication\n"
                 "         réécrit tout ce qui se trouve entre les deux marqueurs. -->"),
        "titre": "Télécharger pour Windows",
        "meta": "Version %s · %d Mo · Windows 10 et 11",
        "note_donnees": ("<!-- donnees:debut — régénéré à chaque release,"
                         " comme le bouton. -->"),
        "url": SITE,
        "langue": "fr",
        "description": ("Desky est un compagnon de bureau gratuit pour Windows."
                        " Un petit robot qui réagit à ce que vous faites, qu'on"
                        " nourrit, qu'on lave et avec qui on joue. Aucune"
                        " connexion réseau, aucune donnée qui quitte la machine."),
    },
    "docs/en/index.html": {
        "note": ("<!-- telechargement:debut — block regenerated on every release by\n"
                 "         tools/site_release.py. Do not edit by hand: publishing rewrites\n"
                 "         everything between the two markers. -->"),
        "titre": "Download for Windows",
        "meta": "Version %s · %d MB · Windows 10 and 11",
        "note_donnees": ("<!-- donnees:debut — regenerated on every release,"
                         " like the button. -->"),
        "url": SITE + "en/",
        "langue": "en",
        "description": ("Desky is a free desktop companion for Windows. A small"
                        " robot that reacts to what you do, that you feed, wash"
                        " and play with. No network connection, no data leaving"
                        " the machine."),
    },
}


def download_url(version: str, nom: str) -> str:
    """Lien d'un asset de release. `version` sans le « v » initial."""
    return "%s/releases/download/v%s/%s" % (DEPOT, version, nom)


def bloc(version: str, nom: str, mio: int, page: dict[str, str]) -> str:
    """Le bouton, marqueurs compris."""
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


def donnees(version: str, nom: str, mio: int, page: dict[str, str]) -> dict:
    """Le graphe `SoftwareApplication` décrivant la version publiée.

    Volontairement factuel et sans superlatif : c'est ce qu'un moteur ou un
    assistant recopiera, et une fiche qui se vante se fait ignorer là où une
    fiche qui déclare son prix, son système et sa licence se fait citer.
    """
    unite = "Mo" if page["langue"] == "fr" else "MB"
    return {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Desky",
        "url": page["url"],
        "inLanguage": page["langue"],
        "description": page["description"],
        "applicationCategory": "EntertainmentApplication",
        "operatingSystem": "Windows 10, Windows 11",
        "softwareVersion": version,
        "downloadUrl": download_url(version, nom),
        "installUrl": page["url"],
        "fileSize": "%d %s" % (mio, unite),
        "softwareRequirements": "Windows 10 ou 11, OpenGL 3.3",
        "isAccessibleForFree": True,
        "license": "https://www.gnu.org/licenses/gpl-3.0.html",
        "image": SITE + "assets/social.png",
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "EUR",
        },
        "author": {
            "@type": "Person",
            "name": "HyroHyKen",
            "url": DEPOT,
        },
        "codeRepository": DEPOT,
    }


def bloc_donnees(version: str, nom: str, mio: int, page: dict[str, str]) -> str:
    charge = json.dumps(donnees(version, nom, mio, page),
                        ensure_ascii=False, indent=2)
    return ('%s\n<script type="application/ld+json">\n%s\n</script>\n%s'
            % (page["note_donnees"], charge, DONNEES_FIN))


def _remplacer(source: str, debut: str, fin: str, contenu: str) -> str:
    i = source.find(debut)
    j = source.find(fin)
    if i < 0 or j < 0 or j < i:
        raise ValueError("marqueurs %r absents ou inversés" % debut)
    return source[:i] + contenu + source[j + len(fin):]


def rewrite(source: str, version: str, nom: str, mio: int,
            page: dict[str, str]) -> str:
    """Remplace les deux zones. Lève si un marqueur manque."""
    source = _remplacer(source, DEBUT, FIN, bloc(version, nom, mio, page))
    return _remplacer(source, DONNEES_DEBUT, DONNEES_FIN,
                      bloc_donnees(version, nom, mio, page))


def mebioctets(octets: int) -> int:
    return int(round(octets / (1024 * 1024)))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python -m tools.site_release <version> <installateur>")
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

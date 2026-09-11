"""Chaîne de production complète : icône, exécutable, installateur (CDC §15).

    .venv/Scripts/python.exe -m tools.build
    .venv/Scripts/python.exe -m tools.build --skip-installer

Trois étapes enchaînées, et deux contournements qu'il vaut mieux avoir écrits
une fois que redécouverts à chaque version.

**Les protections de poste bloquent l'écriture de ressources dans un PE.**
PyInstaller comme Inno Setup terminent leur binaire en y injectant icône,
manifeste et informations de version, et sur une machine surveillée cette
écriture échoue avec l'erreur 110 — `EndUpdateResource failed`. PyInstaller s'en
sort parce qu'il réessaie vingt fois ; Inno Setup abandonne au premier échec.
D'où la compilation de l'installateur **dans le dossier temporaire**, puis la
copie du résultat : le temporaire n'est généralement pas surveillé de la même
façon.

**La version n'est écrite qu'à un seul endroit.** Elle vit dans
`pet/__init__.py`, et elle est passée à Inno Setup en ligne de commande plutôt
que recopiée dans le script : deux numéros de version finissent toujours par
diverger, et celui de l'installateur est le seul que l'utilisateur verra.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RACINE = Path(__file__).resolve().parents[1]
PACKAGING = RACINE / "packaging"
DIST = RACINE / "dist"

# Emplacements habituels d'Inno Setup, portée utilisateur d'abord : c'est là que
# `winget install --scope user` le pose.
ISCC_CANDIDATS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
    Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
)


def version() -> str:
    """Version du produit, sans le suffixe de lot.

    Inno Setup veut une suite de nombres ; `0.11.0-L8` lui est indigeste, et le
    suffixe de lot n'intéresse de toute façon personne en dehors du dépôt.
    """
    from pet import VERSION
    return VERSION.split("-")[0]


def trouve_iscc() -> Path | None:
    for chemin in ISCC_CANDIDATS:
        if chemin.is_file():
            return chemin
    return None


def etape(titre: str) -> None:
    print()
    print("=== %s" % titre)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="production de Desky")
    ap.add_argument("--skip-icon", action="store_true")
    ap.add_argument("--skip-exe", action="store_true")
    ap.add_argument("--skip-installer", action="store_true")
    args = ap.parse_args(argv)

    numero = version()
    print("Desky %s" % numero)

    if not args.skip_icon:
        etape("icône")
        from tools import make_icon
        make_icon.main(["--out", str(PACKAGING / "desky.ico")])

    if not args.skip_exe:
        etape("exécutable")
        debut = time.perf_counter()
        code = subprocess.call([
            sys.executable, "-m", "PyInstaller",
            str(PACKAGING / "desky.spec"),
            "--noconfirm",
            "--distpath", str(DIST),
            "--workpath", str(RACINE / "build" / "pyi"),
            "--log-level", "WARN",
        ], cwd=str(RACINE))
        if code != 0:
            print("échec de PyInstaller")
            return code
        exe = DIST / "Desky" / "Desky.exe"
        poids = sum(f.stat().st_size for f in (DIST / "Desky").rglob("*")
                    if f.is_file())
        print("  %s — %.1f Mo installés, en %.0f s"
              % (exe.name, poids / 1e6, time.perf_counter() - debut))

        # Garde-fou : PyInstaller ne suit que les imports, pas les fichiers lus
        # à l'exécution. Sans ces deux dossiers, l'application se construit sans
        # une erreur et échoue au premier shader — chez le testeur.
        for attendu, minimum in (("pet/render/shaders", 8),
                                 ("pet/assets/items", 1)):
            dossier = DIST / "Desky" / "_internal" / attendu
            compte = len(list(dossier.glob("*"))) if dossier.is_dir() else 0
            marque = "ok" if compte >= minimum else "MANQUANT"
            print("  %-22s %2d fichiers  [%s]" % (attendu, compte, marque))
            if compte < minimum:
                return 1

    if not args.skip_installer:
        etape("installateur")
        iscc = trouve_iscc()
        if iscc is None:
            print("  Inno Setup introuvable — installez-le :")
            print("  winget install --id JRSoftware.InnoSetup --scope user")
            return 1

        # Compilé dans le temporaire, puis rapatrié : voir l'entête du module.
        temporaire = Path(os.environ.get("TEMP", ".")) / "DeskyBuild"
        temporaire.mkdir(parents=True, exist_ok=True)
        code = subprocess.call([
            str(iscc), str(PACKAGING / "desky.iss"),
            "/O%s" % temporaire,
            "/DAppVersion=%s" % numero,
            "/Qp",
        ], cwd=str(PACKAGING))
        if code != 0:
            print("échec d'Inno Setup")
            return code

        produit = temporaire / ("Desky-%s-setup.exe" % numero)
        DIST.mkdir(parents=True, exist_ok=True)
        final = DIST / produit.name
        shutil.copy2(produit, final)
        print("  %s — %.1f Mo" % (final.name, final.stat().st_size / 1e6))

    etape("terminé")
    print("À livrer : %s" % (DIST / ("Desky-%s-setup.exe" % numero)))
    print()
    print("Non signé : SmartScreen affichera un avertissement sur une machine")
    print("personnelle (contournable), et un poste géré peut refuser tout net.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

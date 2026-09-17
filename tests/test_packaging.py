"""Critères d'acceptation du packaging, lot L8 (CDC §15).

Les données lues **à l'exécution** sont le piège de ce lot : PyInstaller suit
les imports, pas les `open()`. Une application qui se construit sans une erreur
et refuse d'afficher son robot chez le premier testeur est exactement le mode
d'échec à empêcher, et il ne se voit pas en relisant le code.

Ces tests ne gèlent rien — ils vérifient que la **résolution** des chemins est
explicite et que le manifeste de gel déclare bien ce qui est lu.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PET = RACINE / "pet"
PACKAGING = RACINE / "packaging"


class ResourceResolutionTest(unittest.TestCase):
    """Les chemins de données doivent survivre au gel."""

    def test_le_resolveur_suit_meipass(self) -> None:
        """C'est la racine que PyInstaller pose, en onedir comme en onefile."""
        source = (PET / "resources.py").read_text(encoding="utf-8")
        self.assertIn("_MEIPASS", source)

    def test_hors_gel_il_retombe_sur_le_paquet(self) -> None:
        from pet import resources

        self.assertFalse(resources.is_frozen())
        self.assertEqual(resources.root(), resources.PACKAGE_ROOT)

    def test_les_deux_dossiers_de_donnees_existent(self) -> None:
        from pet.render.context import SHADER_DIR
        from pet.ui.item import ASSET_DIR

        self.assertTrue(SHADER_DIR.is_dir(), SHADER_DIR)
        self.assertTrue(ASSET_DIR.is_dir(), ASSET_DIR)
        self.assertTrue(list(SHADER_DIR.glob("*.glsl")))
        self.assertTrue(list(ASSET_DIR.glob("*.png")))

    def test_aucun_chemin_de_donnees_ne_part_de_dunder_file(self) -> None:
        """C'est la régression que ce lot a corrigée.

        `Path(__file__).parent` désigne, une fois gelé, un chemin **dans
        l'archive**, qui n'existe pas toujours sur le disque. Le défaut ne se
        voit qu'au premier lancement de la version distribuée — trop tard.

        `resources.py` a le droit de l'utiliser : c'est lui qui répond à la
        question, et il le fait explicitement.
        """
        coupables = []
        for chemin in PET.rglob("*.py"):
            if chemin.name == "resources.py":
                continue
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Name) or noeud.id != "__file__":
                    continue
                coupables.append(chemin.relative_to(RACINE).as_posix())
        self.assertEqual(coupables, [],
                         "ces modules résolvent un chemin par __file__ : %s"
                         % coupables)


class RelativeImportTest(unittest.TestCase):
    """Tout import relatif doit désigner un module qui existe.

    La régression qui a motivé ce test : au lot L10, des méthodes ont changé de
    dossier, et l'une d'elles gardait un `from ..state import save` qui désignait
    désormais `pet.app.state` — inexistant. L'import étant **dans une fonction**,
    rien n'échouait au chargement : la réinitialisation des données aurait levé
    chez l'utilisateur, et seulement là.

    C'est la faiblesse exacte des imports tardifs : Python ne les vérifie qu'à
    l'exécution, et une branche rarement empruntée n'est jamais exécutée en
    test. Une vérification statique les couvre toutes d'un coup, y compris
    celles qu'aucun test n'atteint.
    """

    def test_chaque_import_relatif_designe_un_module_existant(self) -> None:
        fautifs = []
        for chemin in sorted(PET.rglob("*.py")):
            # Paquet qui **contient** le module. Un `__init__.py` en fait partie
            # comme les autres : `pet/app/parts/__init__.py` est contenu par
            # `pet/app/parts`, donc son `from .care` y cherche `care`.
            paquet = chemin.relative_to(RACINE).with_suffix("").parts[:-1]
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.ImportFrom) or not noeud.level:
                    continue
                # Un point désigne le paquet contenant ; chaque point en plus
                # remonte d'un cran.
                remontee = noeud.level - 1
                if remontee > len(paquet) - 1:
                    fautifs.append("%s: remonte au-delà de la racine (%s)"
                                   % (chemin.name, "." * noeud.level))
                    continue
                base = paquet[:len(paquet) - remontee]
                cible = RACINE.joinpath(*base)
                if noeud.module:
                    cible = cible.joinpath(*noeud.module.split("."))
                if not (cible.is_dir() or cible.with_suffix(".py").is_file()):
                    fautifs.append(
                        "%s:%d  %s%s"
                        % (chemin.relative_to(RACINE).as_posix(), noeud.lineno,
                           "." * noeud.level, noeud.module or ""))
        self.assertEqual(fautifs, [],
                         "imports relatifs qui ne mènent nulle part :\n  "
                         + "\n  ".join(fautifs))


class EntryPointTest(unittest.TestCase):
    """Le point d'entrée gelé n'a pas de paquet parent.

    `python -m pet` pose `__package__ = "pet"` ; PyInstaller exécute le même
    fichier comme un script de premier niveau, sans rien poser du tout. Un
    import relatif y lève `ImportError: attempted relative import with no known
    parent package` avant la première ligne utile — et seulement dans la version
    distribuée, ce qui en fait un défaut qu'aucun lancement depuis les sources
    ne peut révéler.

    C'est la régression que ce test empêche : elle a coûté une release.
    """

    def test_le_point_d_entree_n_importe_rien_relativement(self) -> None:
        arbre = ast.parse((PET / "__main__.py").read_text(encoding="utf-8"))
        relatifs = [noeud for noeud in ast.walk(arbre)
                    if isinstance(noeud, ast.ImportFrom) and noeud.level > 0]
        self.assertEqual(
            ["." * n.level + (n.module or "") for n in relatifs], [],
            "pet/__main__.py doit importer en absolu : il est gelé sans paquet parent")

    def test_le_spec_gele_bien_ce_point_d_entree(self) -> None:
        """Si le spec visait un autre script, le test ci-dessus ne garderait
        rien du tout."""
        spec = (PACKAGING / "desky.spec").read_text(encoding="utf-8")
        self.assertIn('"__main__.py"', spec.replace("'", '"'))


class SpecTest(unittest.TestCase):
    """Le manifeste de gel doit déclarer ce que le code lit."""

    def _spec(self) -> str:
        return (PACKAGING / "desky.spec").read_text(encoding="utf-8")

    def test_les_donnees_lues_sont_embarquees(self) -> None:
        spec = self._spec()
        for attendu in ("pet/render/shaders", "pet/assets/items",
                        "pet/assets/brand"):
            self.assertIn(attendu, spec,
                          "%s n'est pas embarqué par le spec" % attendu)

    def test_le_gel_est_sans_console(self) -> None:
        """« PyInstaller onedir, sans console » (§15)."""
        self.assertIn("console=False", self._spec())

    def test_upx_est_ecarte(self) -> None:
        """Il aggrave la détection heuristique, que le §15 cherche à contenir."""
        spec = self._spec()
        self.assertNotIn("upx=True", spec)
        self.assertIn("upx=False", spec)

    def test_l_icone_est_declaree(self) -> None:
        self.assertIn("desky.ico", self._spec())
        self.assertTrue((PACKAGING / "desky.ico").is_file())


class IconTest(unittest.TestCase):
    """Un `.ico` est un lot de tailles, pas une image redimensionnée."""

    def _entries(self):
        import struct

        donnees = (PACKAGING / "desky.ico").read_bytes()
        reserve, genre, nombre = struct.unpack("<HHH", donnees[:6])
        self.assertEqual((reserve, genre), (0, 1), "en-tête ICO invalide")
        return [donnees[6 + 16 * i] or 256 for i in range(nombre)]

    def test_les_petites_tailles_sont_presentes(self) -> None:
        """C'est le 16 px qu'on voit dans la barre des tâches, et c'est lui que
        le système massacre s'il doit réduire un 256 tout seul."""
        tailles = self._entries()
        for attendue in (16, 32, 48, 256):
            self.assertIn(attendue, tailles)

    def test_les_tailles_sont_uniques(self) -> None:
        tailles = self._entries()
        self.assertEqual(len(tailles), len(set(tailles)))

    def test_la_graine_de_la_mascotte_est_figee(self) -> None:
        """C'est le visage du produit : il ne doit pas changer de version en
        version, sinon l'icône de l'utilisateur change sous ses yeux."""
        from tools.make_icon import MASCOT_SEED, YAW

        self.assertIsInstance(MASCOT_SEED, int)
        self.assertEqual(YAW, 0.0, "la mascotte ne regarde pas droit devant")


class InstallerTest(unittest.TestCase):
    """Les trois exigences du §15 sur l'installateur."""

    def _iss(self) -> str:
        return (PACKAGING / "desky.iss").read_text(encoding="utf-8")

    def test_aucune_elevation_uac(self) -> None:
        """« Portée utilisateur, pas d'élévation UAC » (§15)."""
        self.assertIn("PrivilegesRequired=lowest", self._iss())

    def test_le_demarrage_automatique_est_decoche(self) -> None:
        """« Option de lancement au démarrage décochée par défaut » (§15)."""
        iss = self._iss()
        ligne = next(l for l in iss.splitlines()
                     if l.startswith('Name: "autostart"'))
        self.assertIn("unchecked", ligne)

    def test_la_cle_de_demarrage_reste_utilisateur(self) -> None:
        """Jamais HKLM : il demanderait l'élévation et inscrirait pour tous les
        comptes de la machine."""
        iss = self._iss()
        self.assertIn("Root: HKCU", iss)
        self.assertNotIn("Root: HKLM", iss)

    def test_les_donnees_ne_sont_pas_effacees_a_la_desinstallation(self) -> None:
        """Réinstaller doit retrouver son robot. La purge est un geste
        délibéré, dans les réglages, pas un effet de bord."""
        iss = self._iss()
        for interdit in ("{localappdata}\\Desky", "{userappdata}\\Desky"):
            self.assertNotIn(interdit, iss)

    def test_la_version_n_est_pas_recopiee_dans_le_script(self) -> None:
        """Deux numéros de version finissent toujours par diverger."""
        iss = self._iss()
        self.assertIn("#ifndef AppVersion", iss)

        from pet import VERSION
        self.assertNotIn(VERSION.split("-")[0], iss.split("[Setup]")[0]
                         .replace("#ifndef", "").replace('"0.0.0"', ""))


if __name__ == "__main__":
    unittest.main()

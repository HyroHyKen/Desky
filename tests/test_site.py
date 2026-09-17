"""Le site vitrine, et ce que la publication a le droit d'y écrire (lot L16).

Le site a une propriété désagréable : **personne ne le regarde entre deux
releases**, et c'est exactement le moment où il casse. Un marqueur déplacé au
cours d'une retouche de mise en page ne se voit pas — jusqu'à ce que le workflow
de publication échoue, ou pire, réussisse en écrivant le bouton au mauvais
endroit. Ces tests prennent le relais de l'œil qui ne passe plus.

Ils portent donc sur les invariants que la publication suppose, pas sur la
présentation : le texte, les couleurs et la disposition peuvent changer sans que
rien ici bouge.
"""

from __future__ import annotations

import pathlib
import re
import unittest

from tools import site_release

RACINE = pathlib.Path(__file__).resolve().parent.parent
DOCS = RACINE / "docs"


def _lire(relatif: str) -> str:
    return (RACINE / relatif).read_text(encoding="utf-8")


class StructureTest(unittest.TestCase):
    def test_les_pages_existent(self) -> None:
        for relatif in site_release.PAGES:
            self.assertTrue((RACINE / relatif).is_file(), relatif)

    def test_chaque_page_porte_ses_marqueurs_une_seule_fois(self) -> None:
        """Deux zones de téléchargement, et le script n'en réécrirait qu'une :
        la page annoncerait deux versions différentes du même logiciel."""
        for relatif in site_release.PAGES:
            source = _lire(relatif)
            self.assertEqual(source.count(site_release.DEBUT), 1, relatif)
            self.assertEqual(source.count(site_release.FIN), 1, relatif)
            self.assertLess(source.index(site_release.DEBUT),
                            source.index(site_release.FIN), relatif)

    def test_les_ressources_referencees_sont_livrees(self) -> None:
        """Un chemin cassé ne se voit qu'à l'ouverture, et le champ de
        particules disparaîtrait en silence."""
        for relatif in site_release.PAGES:
            page = RACINE / relatif
            source = page.read_text(encoding="utf-8")
            for lien in re.findall(r'(?:src|href)="([^"#:]+)"', source):
                if lien.startswith(("http", "//", "mailto")) or lien.endswith("/"):
                    continue
                cible = (page.parent / lien).resolve()
                self.assertTrue(cible.is_file(), "%s → %s" % (relatif, lien))

    def test_la_planche_des_particules_est_livree(self) -> None:
        """Référencée par le script et non par le HTML, donc invisible au test
        de liens ci-dessus."""
        self.assertTrue((DOCS / "assets" / "deskys.webp").is_file())

    def test_le_script_et_la_planche_s_accordent(self) -> None:
        """La géométrie de l'atlas est recopiée à la main dans le JavaScript
        depuis la sortie du générateur. Une planche régénérée avec d'autres
        réglages et un script oublié découperaient les robots en morceaux."""
        from PySide6.QtGui import QImage

        from tools import site_deskys

        source = (DOCS / "particles.js").read_text(encoding="utf-8")
        lu = {cle: int(re.search(r"var %s = (\d+);" % cle, source).group(1))
              for cle in ("COLS", "CELL_W", "CELL_H", "COUNT")}

        self.assertEqual(lu["COLS"], site_deskys.COLS)
        self.assertEqual(lu["COUNT"], site_deskys.COUNT)

        planche = QImage(str(DOCS / "assets" / "deskys.webp"))
        self.assertFalse(planche.isNull(), "planche illisible")
        lignes = (lu["COUNT"] + lu["COLS"] - 1) // lu["COLS"]
        self.assertEqual(planche.width(), lu["CELL_W"] * lu["COLS"])
        self.assertEqual(planche.height(), lu["CELL_H"] * lignes)

    def test_les_deux_langues_se_pointent_l_une_l_autre(self) -> None:
        self.assertIn('href="en/"', _lire("docs/index.html"))
        self.assertIn('href="../"', _lire("docs/en/index.html"))


class RewriteTest(unittest.TestCase):
    """Ce que la publication écrit, sans toucher au dépôt."""

    def _page(self) -> tuple[str, dict]:
        relatif = "docs/index.html"
        return _lire(relatif), site_release.PAGES[relatif]

    def test_le_lien_pointe_vers_la_version_demandee(self) -> None:
        source, page = self._page()
        sortie = site_release.rewrite(source, "9.9.9", "Desky-9.9.9-setup.exe",
                                      42, page)
        self.assertIn(
            "https://github.com/HyroHyKen/Desky/releases/download/"
            "v9.9.9/Desky-9.9.9-setup.exe", sortie)
        self.assertIn("Version 9.9.9", sortie)
        self.assertIn("42 Mo", sortie)

    def test_la_reecriture_est_idempotente(self) -> None:
        """Republier la même version ne doit produire aucun commit : sinon le
        dépôt gagne un commit vide à chaque relance du workflow."""
        source, page = self._page()
        une = site_release.rewrite(source, "1.2.3", "Desky-1.2.3-setup.exe", 7, page)
        deux = site_release.rewrite(une, "1.2.3", "Desky-1.2.3-setup.exe", 7, page)
        self.assertEqual(une, deux)

    def test_rien_ne_bouge_hors_des_marqueurs(self) -> None:
        """Le seul vrai danger : un script qui déborde et mange le pied de page
        un jour de publication."""
        source, page = self._page()
        sortie = site_release.rewrite(source, "2.0.0", "Desky-2.0.0-setup.exe",
                                      11, page)
        for temoin in ("<title>", "</footer>", "particles.js", "Mentions légales",
                       "gh attestation verify"):
            self.assertIn(temoin, sortie, temoin)
        avant = source[:source.index(site_release.DEBUT)]
        apres = source[source.index(site_release.FIN) + len(site_release.FIN):]
        self.assertTrue(sortie.startswith(avant))
        self.assertTrue(sortie.endswith(apres))

    def test_une_page_sans_marqueur_est_refusee(self) -> None:
        """Échouer bruyamment vaut mieux que publier un bouton mort."""
        _, page = self._page()
        with self.assertRaises(ValueError):
            site_release.rewrite("<html>rien ici</html>", "1.0.0", "x.exe", 1, page)

    def test_le_poids_suit_la_convention_de_l_explorateur(self) -> None:
        """Windows affiche des mébioctets : annoncer 41 Mo pour un fichier qu'il
        présente comme 39 ferait douter du téléchargement."""
        self.assertEqual(site_release.mebioctets(41206961), 39)

    def test_le_v_initial_du_tag_est_tolere(self) -> None:
        source, page = self._page()
        sortie = site_release.rewrite(source, "3.1.4", "Desky-3.1.4-setup.exe",
                                      5, page)
        self.assertIn("/v3.1.4/", sortie)
        self.assertNotIn("/vv3.1.4/", sortie)


class LegalTest(unittest.TestCase):
    """Ce que le pied de page promet, et qui doit rester vrai."""

    def test_la_licence_est_livree(self) -> None:
        texte = (RACINE / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", texte)
        self.assertIn("Version 3", texte)

    def test_le_site_ne_promet_pas_ce_que_le_code_ne_tient_pas(self) -> None:
        """Le pied de page affirme qu'aucune connexion réseau n'a lieu. C'est
        vérifiable, donc on le vérifie : le jour où une vérification de version
        arrivera, c'est ce test qui rappellera de corriger la page avant de
        publier.
        """
        suspects = ("urllib", "http.client", "requests", "socket.socket",
                    "QNetworkAccessManager", "urlopen")
        for source in (RACINE / "pet").rglob("*.py"):
            texte = source.read_text(encoding="utf-8")
            for mot in suspects:
                self.assertNotIn(
                    mot, texte,
                    "%s mentionne %s alors que le site promet l'absence de "
                    "réseau" % (source.relative_to(RACINE), mot))


if __name__ == "__main__":
    unittest.main()

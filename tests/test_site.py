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
        paires = ((site_release.DEBUT, site_release.FIN),
                  (site_release.DONNEES_DEBUT, site_release.DONNEES_FIN))
        for relatif in site_release.PAGES:
            source = _lire(relatif)
            for debut, fin in paires:
                self.assertEqual(source.count(debut), 1, "%s / %s" % (relatif, debut))
                self.assertEqual(source.count(fin), 1, "%s / %s" % (relatif, fin))
                self.assertLess(source.index(debut), source.index(fin), relatif)

    def test_les_donnees_structurees_livrees_sont_du_json_valide(self) -> None:
        """Un JSON-LD malformé est ignoré en silence par les moteurs : la seule
        façon de s'en apercevoir est de le relire."""
        import json
        import re

        for relatif in site_release.PAGES:
            charge = re.search(
                r'<script type="application/ld\+json">(.*?)</script>',
                _lire(relatif), re.S)
            self.assertIsNotNone(charge, relatif)
            donnees = json.loads(charge.group(1))
            self.assertEqual(donnees["@type"], "SoftwareApplication", relatif)
            # Le lien annoncé aux moteurs doit être celui du bouton.
            self.assertIn(donnees["downloadUrl"], _lire(relatif), relatif)

    def test_le_favicon_est_l_icone_de_l_application(self) -> None:
        """À l'octet près, et pas « à peu près » : deux rendus séparés
        finiraient par diverger, et on aurait deux robots différents selon
        qu'on regarde l'onglet ou la barre des tâches."""
        site = (DOCS / "favicon.ico").read_bytes()
        appli = (RACINE / "packaging" / "desky.ico").read_bytes()
        self.assertEqual(site, appli)

    def test_les_fichiers_d_indexation_sont_livres(self) -> None:
        for nom in ("robots.txt", "sitemap.xml", "llms.txt"):
            self.assertTrue((DOCS / nom).is_file(), nom)

    def test_le_sitemap_liste_exactement_les_pages_publiees(self) -> None:
        """Une page oubliée ne se référence pas ; une page fantôme fait perdre
        du crédit au reste du plan."""
        import xml.etree.ElementTree as ET

        arbre = ET.fromstring((DOCS / "sitemap.xml").read_text(encoding="utf-8"))
        espace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        listees = {n.text for n in arbre.iter(espace + "loc")}
        attendues = {page["url"] for page in site_release.PAGES.values()}
        self.assertEqual(listees, attendues)

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

    def test_les_planches_des_particules_sont_livrees(self) -> None:
        """Référencées par le script et non par le HTML, donc invisibles au test
        de liens ci-dessus."""
        from tools import site_deskys

        for fichier, _, _ in site_deskys.PLANCHES.values():
            self.assertTrue((DOCS / "assets" / fichier).is_file(), fichier)

    def _planches_js(self) -> dict[str, dict[str, int]]:
        """Relit la table des planches recopiée à la main dans `particles.js`."""
        source = (DOCS / "particles.js").read_text(encoding="utf-8")
        lu = {}
        for trouve in re.finditer(
                r'fichier:\s*"([^"]+)"\s*,\s*COLS:\s*(\d+)\s*,'
                r'\s*CELL_W:\s*(\d+)\s*,\s*CELL_H:\s*(\d+)\s*,\s*COUNT:\s*(\d+)',
                source):
            lu[trouve.group(1)] = {
                "COLS": int(trouve.group(2)), "CELL_W": int(trouve.group(3)),
                "CELL_H": int(trouve.group(4)), "COUNT": int(trouve.group(5)),
            }
        self.assertTrue(lu, "aucune planche déclarée dans particles.js")
        return lu

    def test_particles_s_accorde_avec_ses_planches(self) -> None:
        """La géométrie de chaque atlas est recopiée à la main dans le
        JavaScript depuis la sortie du générateur. Une planche régénérée avec
        d'autres réglages et un script oublié découperaient les robots en
        morceaux — et depuis le lot L22 il y en a deux à tenir d'accord."""
        from PySide6.QtGui import QImage

        from tools import site_deskys

        lu = self._planches_js()
        attendues = {f: (c, k) for f, c, k in site_deskys.PLANCHES.values()}
        self.assertEqual(set(lu), set(attendues),
                         "particles.js et site_deskys ne listent pas les mêmes "
                         "planches")

        for fichier, cotes in lu.items():
            count, cols = attendues[fichier]
            self.assertEqual(cotes["COLS"], cols, fichier)
            self.assertEqual(cotes["COUNT"], count, fichier)

            planche = QImage(str(DOCS / "assets" / fichier))
            self.assertFalse(planche.isNull(), "%s illisible" % fichier)
            lignes = (count + cols - 1) // cols
            self.assertEqual(planche.width(), cotes["CELL_W"] * cols, fichier)
            self.assertEqual(planche.height(), cotes["CELL_H"] * lignes, fichier)

    def test_le_champ_montre_les_deux_chassis(self) -> None:
        """Une seule planche et la vitrine ne montrerait qu'une moitié du
        produit. La proportion compte aussi : le champ tire uniformément parmi
        toutes les cases, donc c'est le nombre de variantes de chaque planche
        qui décide de la part de chaque famille — elle doit valoir celle du
        tirage du génome, à quelques points près."""
        from pet.genome.schema import CHASSIS, PARAMS_BY_KEY
        from tools import site_deskys

        self.assertEqual(set(site_deskys.PLANCHES), set(CHASSIS))

        tirage = PARAMS_BY_KEY["chassis"]
        poids = dict(zip(tirage.options, tirage.weights))
        total = sum(c for _, c, _ in site_deskys.PLANCHES.values())
        for famille, (_, count, _) in site_deskys.PLANCHES.items():
            part = 100.0 * count / total
            attendu = 100.0 * poids[famille] / sum(poids.values())
            self.assertLess(
                abs(part - attendu), 4.0,
                "le champ montre %.0f %% de %s pour %.0f %% au tirage"
                % (part, famille, attendu))


class ChassisTest(unittest.TestCase):
    """La section des deux châssis, en bas de page (lot L22)."""

    def test_les_dessins_viennent_de_l_application(self) -> None:
        """Le site ne redessine rien : il convertit les planches que le produit
        embarque déjà. Une illustration faite à côté finirait par promettre un
        robot que le moteur ne produit plus."""
        from PySide6.QtGui import QImage

        from pet.genome.schema import CHASSIS
        from tools import site_chassis

        for famille in CHASSIS:
            web = DOCS / "assets" / ("blueprint_%s.webp" % famille)
            appli = RACINE / site_chassis.SOURCE / ("blueprint_%s.png" % famille)
            self.assertTrue(web.is_file(), web.name)
            self.assertTrue(appli.is_file(), appli.name)
            a, b = QImage(str(web)), QImage(str(appli))
            self.assertEqual((a.width(), a.height()), (b.width(), b.height()),
                             "%s n'a pas les cotes du dessin de l'application"
                             % web.name)

    def test_les_deux_pages_portent_la_section(self) -> None:
        for relatif in site_release.PAGES:
            source = _lire(relatif)
            self.assertIn('class="ateliers"', source, relatif)
            for famille in ("capsule", "monobloc"):
                self.assertIn("blueprint_%s.webp" % famille, source,
                              "%s / %s" % (relatif, famille))

    def test_la_fiche_du_site_dit_ce_que_dit_l_application(self) -> None:
        """Les cotes et les masses sont annoncées à trois endroits : le dessin
        industriel, la fiche du premier lancement, et maintenant la page. Un
        plan qui annonce 89 mm à côté d'un site qui en annonce 80 est le genre
        de détail qui défait une immersion en une seconde.

        Le contrôle porte sur les **nombres**, seuls à traverser la traduction :
        « aucune » et « none » disent la même chose, 410 g se dit pareil dans
        les deux langues.
        """
        from pet.ui.chassis_choice import FICHES

        # Ce qui doit se retrouver **tel quel** : une année, une cote, une masse,
        # une référence de calculateur. Le reste de la fiche est de la langue —
        # « aucune » et « none » disent la même chose — et un test qui
        # l'exigerait interdirait de traduire la page.
        chiffre = re.compile(r"^\d+(?: (?:mm|g))?$")
        verifies = 0
        for relatif in site_release.PAGES:
            source = _lire(relatif)
            for famille, lignes in FICHES.items():
                for etiquette, valeur in lignes:
                    if chiffre.match(valeur):
                        attendu = valeur
                    elif valeur.startswith("DK-"):
                        attendu = valeur.split()[0]
                    else:
                        continue
                    verifies += 1
                    # `assertTrue` et non `assertIn` : l'échec d'un `assertIn`
                    # recrache la page entière, et on ne lit plus le message.
                    self.assertTrue(
                        attendu in source,
                        "%s : %s de %s annoncé %s dans l'application, absent "
                        "de la page" % (relatif, etiquette.lower(), famille,
                                        attendu))
        # Sans ce compte, une fiche vidée de ses nombres ferait passer la boucle
        # sans rien vérifier — le genre de test qui rassure et ne tient rien.
        # Cinq par châssis : l'année, les deux cotes, la masse, le calculateur.
        self.assertEqual(verifies,
                         len(site_release.PAGES) * 5 * len(FICHES))

    def _constantes(self, script: str, noms) -> dict[str, int]:
        """Relit les constantes recopiées à la main dans un script."""
        source = (DOCS / script).read_text(encoding="utf-8")
        lu = {}
        for nom in noms:
            trouve = re.search(r"\b%s = (\d+)" % nom, source)
            self.assertIsNotNone(trouve, "%s absent de %s" % (nom, script))
            lu[nom] = int(trouve.group(1))
        return lu

    def test_hero_s_accorde_avec_sa_planche(self) -> None:
        """Même piège, même garde-fou : le robot du héros est découpé dans un
        atlas dont les cotes vivent en double, dans le générateur et dans le
        script. La planche empile les yeux ouverts puis fermés, d'où le
        facteur deux en hauteur."""
        from PySide6.QtGui import QImage

        from tools import site_hero

        lu = self._constantes("hero.js", ("COLS", "ROWS", "CELL_W", "CELL_H"))
        self.assertEqual(lu["COLS"], site_hero.COLS)
        self.assertEqual(lu["ROWS"], site_hero.ROWS)

        planche = QImage(str(DOCS / "assets" / "hero.webp"))
        self.assertFalse(planche.isNull(), "planche illisible")
        self.assertEqual(planche.width(), lu["CELL_W"] * lu["COLS"])
        self.assertEqual(planche.height(), lu["CELL_H"] * lu["ROWS"] * 2)

    def test_le_hero_reprend_la_demarche_du_produit(self) -> None:
        """Les constantes de saut sont recopiées de `pet/anim/locomotion.py`.
        Les régler d'un côté seulement donnerait un robot qui ne marche pas
        comme celui qu'on télécharge — et c'est précisément ce que la page
        promet."""
        from pet.anim import locomotion

        source = (DOCS / "hero.js").read_text(encoding="utf-8")
        for nom in ("HOP_DISTANCE", "HOP_HEIGHT", "HOP_CROUCH", "HOP_SQUASH",
                    "CROUCH_TIME", "AIR_TIME", "LAND_TIME"):
            trouve = re.search(r"\b%s = ([0-9.]+)" % nom, source)
            self.assertIsNotNone(trouve, "%s absent de hero.js" % nom)
            self.assertAlmostEqual(float(trouve.group(1)),
                                   getattr(locomotion, nom), places=4,
                                   msg="%s a divergé de la locomotion" % nom)

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
        un jour de publication.

        Deux zones depuis que les données structurées sont réécrites elles
        aussi, donc trois segments doivent survivre intacts : avant la première,
        entre les deux, et après la seconde.
        """
        source, page = self._page()
        sortie = site_release.rewrite(source, "2.0.0", "Desky-2.0.0-setup.exe",
                                      11, page)
        for temoin in ("<title>", "</footer>", "particles.js", "Mentions légales",
                       "gh attestation verify", "hero.js"):
            self.assertIn(temoin, sortie, temoin)

        def segments(texte: str) -> tuple[str, str, str]:
            a = texte.index(site_release.DONNEES_DEBUT)
            b = texte.index(site_release.DONNEES_FIN) + len(site_release.DONNEES_FIN)
            c = texte.index(site_release.DEBUT)
            d = texte.index(site_release.FIN) + len(site_release.FIN)
            self.assertLess(b, c, "les zones se chevauchent")
            return texte[:a], texte[b:c], texte[d:]

        self.assertEqual(segments(sortie), segments(source))

    def test_les_deux_zones_sont_reecrites_ensemble(self) -> None:
        """Une page qui annoncerait la bonne version à l'œil et la mauvaise aux
        moteurs serait pire que muette : on ne verrait jamais l'erreur."""
        import json
        import re

        source, page = self._page()
        sortie = site_release.rewrite(source, "4.5.6", "Desky-4.5.6-setup.exe",
                                      17, page)
        charge = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                           sortie, re.S)
        self.assertIsNotNone(charge, "données structurées absentes")
        donnees = json.loads(charge.group(1))

        self.assertEqual(donnees["softwareVersion"], "4.5.6")
        self.assertIn("v4.5.6/Desky-4.5.6-setup.exe", donnees["downloadUrl"])
        self.assertEqual(donnees["fileSize"], "17 Mo")
        # Et le bouton visible dit exactement la même chose.
        self.assertIn(donnees["downloadUrl"], sortie)
        self.assertIn("Version 4.5.6 · 17 Mo", sortie)

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

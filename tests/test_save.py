"""Critères d'acceptation de la persistance du lot L1 (CDC §14).

Le test central est `test_survit_a_un_kill_brutal` : il tue réellement un
process en cours d'écriture, en boucle, et vérifie qu'aucune lecture ne tombe
jamais sur un fichier tronqué.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import tempfile
import unittest
from pathlib import Path

from pet.state import save

# Script exécuté par le sous-process du test de kill : écrit sans discontinuer.
WRITER = """
import sys, time
sys.path.insert(0, %(root)r)
from pathlib import Path
from pet.state.save import write_json_atomic
target = Path(%(target)r)
i = 0
while True:
    i += 1
    write_json_atomic(target, {"schema_version": 1, "counter": i,
                               "ballast": "x" * 20000})
"""


class AtomicWriteTest(unittest.TestCase):
    def setUp(self) -> None:
        # ignore_cleanup_errors : après un kill, Windows garde brièvement le
        # `.tmp` du process mort verrouillé, ce qui ferait échouer le nettoyage
        # du répertoire de test. Sans conséquence pour le produit, dont le
        # balayage au démarrage tolère l'OSError.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ecrit_et_relit(self) -> None:
        p = self.dir / "x.json"
        save.write_json_atomic(p, {"a": 1, "b": "é"})
        self.assertEqual(save.read_json(p), {"a": 1, "b": "é"})

    def test_ne_laisse_pas_de_temporaire(self) -> None:
        p = self.dir / "x.json"
        save.write_json_atomic(p, {"a": 1})
        restants = [f.name for f in self.dir.iterdir() if f.name != "x.json"]
        self.assertEqual(restants, [], f"temporaires laissés derrière : {restants}")

    def test_json_corrompu_ne_bloque_pas_le_demarrage(self) -> None:
        p = self.dir / "x.json"
        p.write_text("{ceci n'est pas du json", encoding="utf-8")
        self.assertIsNone(save.read_json(p))

    def test_json_non_objet_est_rejete(self) -> None:
        p = self.dir / "x.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(save.read_json(p))

    def test_survit_a_un_kill_brutal(self) -> None:
        """CDC §14 : les données survivent à un kill brutal du process.

        On tue un écrivain en pleine boucle, plusieurs fois, et on exige qu'à
        chaque fois le fichier visible soit un JSON complet — jamais un tronçon.
        C'est exactement ce que `os.replace()` garantit et qu'une écriture
        directe ne garantit pas.
        """
        root = str(Path(__file__).resolve().parent.parent)
        target = self.dir / "killed.json"
        script = WRITER % {"root": root, "target": str(target)}

        tours = 5
        for tour in range(tours):
            # La cible est effacée avant chaque tour. Sans cela, l'attente de
            # « première écriture » sortait immédiatement dès le deuxième tour,
            # le fichier étant déjà là depuis le précédent : le nouveau writer
            # ne recevait alors qu'un délai fixe de 60 ms, ce qui était
            # exactement le défaut que cette attente devait corriger.
            if target.exists():
                target.unlink()

            proc = subprocess.Popen(
                [sys.executable, "-c", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                # On attend que le writer ait **effectivement** écrit au moins
                # une fois, puis on le laisse tourner un peu avant de le tuer.
                #
                # Un simple délai en horloge ne suffit pas : c'était 0,25 s au
                # lot L1, et l'échec est apparu au lot L4 quand la suite est
                # passée à 194 tests. Le process parent porte alors numpy,
                # moderngl et PySide6, et lancer un sous-process depuis un
                # parent lourd sous Windows consomme tout le budget. Attendre
                # la première écriture mesure l'atomicité, et non la latence de
                # démarrage de l'interpréteur.
                debut = time.perf_counter()
                while not target.exists():
                    if time.perf_counter() - debut > 20.0:
                        self.fail(f"tour {tour} : le writer n'a jamais démarré")
                    if proc.poll() is not None:
                        self.fail(f"tour {tour} : le writer est mort tout seul")
                    time.sleep(0.005)
                # Le délai varie pour ne pas tomber toujours au même endroit du
                # cycle d'écriture.
                proc.wait(timeout=0.06 + tour * 0.04)
            except subprocess.TimeoutExpired:
                pass
            proc.kill()
            proc.wait(timeout=5)

            # On relit par `read_json`, qui réessaie : juste après un
            # `os.replace()`, Windows refuse parfois l'ouverture pendant
            # quelques millisecondes. Ce test l'a effectivement reproduit, en
            # PermissionError, avant que les tentatives soient ajoutées.
            data = save.read_json(target)
            if data is None:
                # Diagnostic explicite : absent et corrompu donnent tous deux
                # `None`, et seul le second serait un défaut d'atomicité.
                if not target.exists():
                    self.fail(f"tour {tour} : le writer n'a rien écrit")
                try:
                    brut = target.read_bytes()
                except OSError as exc:
                    self.fail(f"tour {tour} : fichier toujours inaccessible après "
                              f"les tentatives de read_json ({type(exc).__name__})")
                self.fail(f"tour {tour} : fichier CORROMPU, {len(brut)} octets — "
                          f"l'écriture atomique a échoué")
            self.assertIn("counter", data, f"tour {tour} : contenu incomplet")
            self.assertEqual(len(data["ballast"]), 20000,
                             f"tour {tour} : écriture tronquée")

        # Un process tué ne nettoie rien : des temporaires DOIVENT rester ici.
        # C'est précisément ce que `sweep_temp_files` va effacer au démarrage.
        orphelins = [f for f in self.dir.iterdir() if f.name.endswith(".tmp")]
        self.assertGreater(len(orphelins), 0,
                           "un kill en pleine écriture devrait laisser un temporaire ; "
                           "si ce n'est plus le cas, le test ne tue plus au bon moment")


class SettingsStoreTest(unittest.TestCase):
    """Bornage au chargement (CDC §14 : borner, jamais rejeter)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self._tmp.name

    def tearDown(self) -> None:
        # Sous Windows, un fichier encore ouvert n'est pas supprimable : sans
        # cette fermeture, le handler du journal empêche le nettoyage.
        save.close_logging()
        if self._old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old
        self._tmp.cleanup()

    def test_defauts_si_absent(self) -> None:
        s = save.settings_store()
        s.load()
        self.assertEqual(s.data["size"], 220)
        self.assertEqual(s.data["positions"], {})

    def test_aller_retour(self) -> None:
        s = save.settings_store()
        s.load()
        s.set(size=300, last_monitor="MON-A")
        self.assertTrue(s.save())
        s2 = save.settings_store()
        s2.load()
        self.assertEqual(s2.data["size"], 300)
        self.assertEqual(s2.data["last_monitor"], "MON-A")

    def test_save_sans_modification_n_ecrit_pas(self) -> None:
        s = save.settings_store()
        s.load()
        s.save(force=True)
        self.assertFalse(s.save(), "une sauvegarde sans changement doit être un no-op")

    def test_taille_hors_bornes_est_ramenee(self) -> None:
        s = save.settings_store()
        s.load()
        save.write_json_atomic(s.path, {"schema_version": 1, "size": 99999})
        s2 = save.settings_store()
        s2.load()
        self.assertEqual(s2.data["size"], save.SIZE_MAX)

        save.write_json_atomic(s.path, {"schema_version": 1, "size": -5})
        s3 = save.settings_store()
        s3.load()
        self.assertEqual(s3.data["size"], save.SIZE_MIN)

    def test_taille_non_numerique_retombe_au_defaut(self) -> None:
        s = save.settings_store()
        s.load()
        save.write_json_atomic(s.path, {"schema_version": 1, "size": "grand"})
        s2 = save.settings_store()
        s2.load()
        self.assertEqual(s2.data["size"], 220)

    def test_positions_invalides_sont_ecartees(self) -> None:
        s = save.settings_store()
        s.load()
        save.write_json_atomic(s.path, {
            "schema_version": 1,
            "positions": {
                "bon": {"x_frac": 0.5, "floor_gap": 10},
                "hors_bornes": {"x_frac": 42.0, "floor_gap": -99},
                "pourri": "pas un dict",
                "vide": {},
            },
        })
        s2 = save.settings_store()
        s2.load()
        pos = s2.data["positions"]
        self.assertEqual(pos["bon"], {"x_frac": 0.5, "floor_gap": 10})
        self.assertEqual(pos["hors_bornes"], {"x_frac": 1.0, "floor_gap": 0})
        self.assertNotIn("pourri", pos)
        self.assertIn("vide", pos)          # complété par les défauts, pas rejeté

    def test_purge_est_effective(self) -> None:
        """CDC §13 : le bouton de purge doit réellement tout effacer."""
        s = save.settings_store()
        s.load()
        s.save(force=True)
        save.write_json_atomic(save.app_dir() / "pet.json", {"schema_version": 1})
        save.write_json_atomic(save.app_dir() / "state.json", {"schema_version": 1})

        removed = save.purge_data()
        self.assertIn("settings.json", removed)
        self.assertIn("pet.json", removed)
        self.assertIn("state.json", removed)

        restants = [f.name for f in save.app_dir().iterdir()]
        self.assertEqual(restants, [], f"restant après purge : {restants}")

    def test_balayage_efface_les_temporaires(self) -> None:
        """Les résidus d'un arrêt brutal sont effacés au démarrage suivant."""
        d = save.app_dir()
        (d / ".settings.json.abc123.tmp").write_text("{tronqu", encoding="utf-8")
        (d / ".pet.json.def456.tmp").write_text("{", encoding="utf-8")
        save.write_json_atomic(d / "settings.json", {"schema_version": 1})

        self.assertEqual(save.sweep_temp_files(), 2)
        restants = sorted(f.name for f in d.iterdir())
        self.assertEqual(restants, ["settings.json"],
                         "le balayage ne doit toucher que les .tmp")

    def test_balayage_sans_temporaire_est_un_noop(self) -> None:
        self.assertEqual(save.sweep_temp_files(), 0)

    def test_purge_emporte_aussi_les_temporaires(self) -> None:
        d = save.app_dir()
        (d / ".settings.json.zzz.tmp").write_text("{", encoding="utf-8")
        save.purge_data()
        self.assertEqual([f.name for f in d.iterdir()], [])

    def test_le_journal_ne_contient_que_des_categories(self) -> None:
        """CDC §11 : aucun titre de fenêtre, aucune URL, aucune frappe.

        Vérification structurelle : le journal ne doit pas contenir de chaîne
        ressemblant à une URL. Les capteurs du lot L5 devront réussir ce test.
        """
        log_path = save.setup_logging()
        import logging
        logging.getLogger("desky.test").info("catégorie=browser plein_écran=False")
        for h in logging.getLogger("desky").handlers:
            h.flush()
        contenu = log_path.read_text(encoding="utf-8")
        self.assertIn("catégorie=browser", contenu)
        for interdit in ("http://", "https://", "www."):
            self.assertNotIn(interdit, contenu)


if __name__ == "__main__":
    unittest.main()

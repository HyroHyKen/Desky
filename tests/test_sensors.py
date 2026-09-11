"""Critères d'acceptation des capteurs, lot L5 (CDC §3, §11).

Trois familles de vérifications :

- **Vie privée, structurellement.** Aucun hook n'est installé, aucun titre de
  fenêtre n'est lu, et rien de sensible n'atteint le disque. Ces tests relisent
  le code source et le journal : ce sont les seules preuves qui ne dépendent pas
  de la bonne volonté de l'implémentation.
- **Dérivation du contexte**, sur une matrice de scénarios écrits à la main. Les
  fonctions de dérivation sont pures, donc chaque scénario est un appel.
- **Cloison du §5.** `brain` ne doit importer ni `render` ni `anim`.

Aucun GPU, aucune fenêtre.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from pet.app import win32
from pet.brain import sensors
from pet.brain.sensors import (
    AUDIO_ONLY_SOURCES,
    AWAY_SECONDS,
    CATEGORIES,
    CURSOR_MOVE_EPS,
    DEFAULT_PROCESSES,
    IDLE_SECONDS,
    VIDEO_SOURCES,
    WATCH_COVERAGE,
    WATCH_MEDIA_SECONDS,
    WATCH_STILL_SECONDS,
    CursorSensor,
    SystemContext,
    categorize,
    derive_state,
    is_watching,
    load_categories,
)

PET_ROOT = Path(__file__).resolve().parent.parent / "pet"


def _code_only(source: str) -> str:
    """Source privée de ses commentaires et de ses chaînes.

    Indispensable : les modules **documentent** les interdictions du CDC, donc un
    scan du texte brut s'accroche à sa propre documentation. Les deux premiers
    tests de vie privée échouaient ainsi sur les docstrings qui expliquent que
    `SetWindowsHookEx` est interdit.

    Garde contre un ajout accidentel, pas contre une dissimulation volontaire :
    un appel construit dynamiquement passerait. Ce n'est pas le risque visé.
    """
    import io
    import tokenize

    morceaux = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            morceaux.append(tok.string)
    except tokenize.TokenError:
        return source
    return " ".join(morceaux)


def _sources() -> dict[Path, str]:
    """Code de tous les modules, commentaires et chaînes retirés."""
    return {p: _code_only(p.read_text(encoding="utf-8"))
            for p in PET_ROOT.rglob("*.py")}


def _imported_modules(path: Path) -> set[str]:
    """Modules importés par un fichier, lus dans l'AST.

    Analysé plutôt que cherché par motif : `from ..render import X` ne contient
    pas la chaîne « pet.render », et une docstring qui la mentionne n'est pas un
    import.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # `level` compte les points d'un import relatif.
            modules.add(("." * node.level) + (node.module or ""))
    return modules


class PrivacyTest(unittest.TestCase):
    """Les interdictions du CDC §3 et §11, vérifiées sur le code lui-même."""

    def test_aucun_hook_clavier_ni_souris(self) -> None:
        """CDC §3 : « Hook clavier global : interdit ».

        Le motif est explicite dans le CDC — faux positifs antivirus et
        perception de keylogger. Ce test relit le code parce qu'une revue
        humaine peut laisser passer un ajout, et qu'un hook est précisément le
        genre de raccourci tentant.
        """
        interdits = ("SetWindowsHookEx", "WH_KEYBOARD", "WH_MOUSE",
                     "RegisterHotKey", "GetAsyncKeyState", "GetKeyboardState",
                     "GetKeyState", "keybd_event", "RawInput",
                     "RegisterRawInputDevices")
        for path, code in _sources().items():
            for motif in interdits:
                self.assertNotIn(motif, code,
                                 f"{path.name} contient {motif} — interdit par le §3")

    def test_aucune_lecture_de_titre_de_fenetre(self) -> None:
        """CDC §11 : aucun titre de fenêtre. C'est là que vivent les URL."""
        for path, code in _sources().items():
            for motif in ("GetWindowText", "GetWindowTextW", "GetWindowTextA"):
                self.assertNotIn(motif, code, f"{path.name} lit un titre de fenêtre")

    def test_aucune_capture_d_ecran(self) -> None:
        """CDC §11 : aucune capture d'écran."""
        for path, code in _sources().items():
            for motif in ("BitBlt", "PrintWindow", "GetDIBits", "grabWindow",
                          "CreateCompatibleBitmap"):
                self.assertNotIn(motif, code, f"{path.name} capture l'écran")

    def test_la_forme_expurgee_ne_contient_aucun_nom_de_process(self) -> None:
        context = SystemContext(foreground_process="chrome.exe",
                                foreground_category="browser")
        publie = json.dumps(context.redacted())
        self.assertNotIn("chrome", publie.lower())
        self.assertIn("browser", publie)

    def test_le_journal_ne_recoit_que_des_categories(self) -> None:
        """CDC §11 : « Le journal de debug ne contient que des catégories ».

        Vérifié en écrivant réellement un journal, puis en le relisant.
        """
        from pet.state import save
        import logging

        with tempfile.TemporaryDirectory() as tmp:
            ancien = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = tmp
            try:
                chemin = save.setup_logging()
                context = SystemContext(
                    state="watching", foreground_process="chrome.exe",
                    foreground_category="browser", media_playing=True,
                    media_category="browser", media_seconds=42.0)
                logging.getLogger("desky.test").info("contexte %s",
                                                     context.redacted())
                for handler in logging.getLogger("desky").handlers:
                    handler.flush()
                contenu = chemin.read_text(encoding="utf-8").lower()
            finally:
                save.close_logging()
                if ancien is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = ancien

        self.assertIn("watching", contenu)
        self.assertIn("browser", contenu)
        for interdit in ("chrome", ".exe", "http://", "https://", "www."):
            self.assertNotIn(interdit, contenu,
                             f"le journal contient {interdit!r}")

    def test_le_contexte_persiste_ne_contient_pas_de_process(self) -> None:
        """Même sérialisé en JSON, l'agrégat reste anodin."""
        context = SystemContext(foreground_process="devenv.exe")
        for cle in context.redacted():
            self.assertNotIn("process", cle)


class BoundaryTest(unittest.TestCase):
    """Cloison du CDC §5 : « brain ne connaît pas render »."""

    def test_brain_n_importe_ni_render_ni_anim(self) -> None:
        for path in (PET_ROOT / "brain").rglob("*.py"):
            for module in _imported_modules(path):
                nu = module.lstrip(".")
                self.assertFalse(
                    nu.startswith(("render", "anim", "pet.render", "pet.anim")),
                    f"{path.name} importe {module} — cloison du §5 franchie")

    def test_les_capteurs_s_importent_sans_qt_ni_gpu(self) -> None:
        """Le brain doit être testable sans GPU (CDC §5, critère du lot L4)."""
        import subprocess
        import sys
        code = ("import sys; import pet.brain.sensors; "
                "print('PySide6' in sys.modules, 'moderngl' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True,
                             cwd=str(PET_ROOT.parent))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False False",
                         "importer les capteurs a chargé Qt ou ModernGL")


class IdleTimeTest(unittest.TestCase):
    def test_l_inactivite_est_positive(self) -> None:
        """Le compteur de tics est non signé.

        Livré signé, il donnait une inactivité de −4 294 967 s dès 24,8 jours
        d'uptime — et la machine de dev en était à 42,8.
        """
        for _ in range(20):
            valeur = win32.get_idle_seconds()
            self.assertGreaterEqual(valeur, 0.0)
            self.assertLess(valeur, 86400.0 * 60,
                            "inactivité absurde : arithmétique de tics suspecte")

    def test_le_compteur_de_tics_est_non_signe(self) -> None:
        self.assertGreater(int(win32.kernel32.GetTickCount()), 0)

    def test_l_arithmetique_supporte_le_rebouclage(self) -> None:
        """Le compteur reboucle à 49,7 jours ; la soustraction masquée le gère."""
        masque = win32._TICK_MASK
        # Dernière entrée juste avant le rebouclage, maintenant juste après.
        avant, apres = masque - 500, 500
        delta = (apres - avant) & masque
        self.assertEqual(delta, 1001)


class CategoriesTest(unittest.TestCase):
    def test_categorisation_des_defauts(self) -> None:
        table = load_categories(Path(tempfile.gettempdir()) / "desky-absent")
        attendu = {
            "code.exe": "dev", "windowsterminal.exe": "dev",
            "chrome.exe": "browser", "firefox.exe": "browser",
            "vlc.exe": "media", "spotify.exe": "media",
            "steam.exe": "game", "winword.exe": "office",
            "explorer.exe": "shell", "quelquechose.exe": "other", "": "other",
        }
        for process, categorie in attendu.items():
            self.assertEqual(categorize(process, table), categorie, process)

    def test_la_casse_est_ignoree(self) -> None:
        table = load_categories(Path(tempfile.gettempdir()) / "desky-absent")
        self.assertEqual(categorize("CHROME.EXE", table), "browser")
        self.assertEqual(categorize("Code.Exe", table), "dev")

    def test_toutes_les_categories_du_cdc_existent(self) -> None:
        """CDC §11 : dev, browser, media, game, office, other."""
        for nom in ("dev", "browser", "media", "game", "office", "other"):
            self.assertIn(nom, CATEGORIES)

    def test_aucun_process_dans_deux_categories(self) -> None:
        vus: dict[str, str] = {}
        for categorie, noms in DEFAULT_PROCESSES.items():
            for nom in noms:
                self.assertNotIn(nom, vus,
                                 f"{nom} est dans {vus.get(nom)} et {categorie}")
                vus[nom] = categorie

    def test_le_fichier_de_config_complete_les_defauts(self) -> None:
        """CDC §11 : « extensible par fichier de config ».

        Le fichier **ajoute** et ne remplace pas : déclarer son éditeur exotique
        ne doit pas faire perdre la liste des navigateurs.
        """
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / sensors.PROCESS_CONFIG).write_text(json.dumps({
                "dev": ["mon-editeur.exe"],
                "media": ["lecteur-maison.exe"],
            }), encoding="utf-8")
            table = load_categories(directory)
            self.assertEqual(categorize("mon-editeur.exe", table), "dev")
            self.assertEqual(categorize("lecteur-maison.exe", table), "media")
            self.assertEqual(categorize("chrome.exe", table), "browser")

    def test_une_categorie_inconnue_est_ignoree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / sensors.PROCESS_CONFIG).write_text(
                json.dumps({"licorne": ["x.exe"]}), encoding="utf-8")
            table = load_categories(directory)
            self.assertNotIn("licorne", table)
            self.assertEqual(categorize("x.exe", table), "other")

    def test_un_fichier_corrompu_ne_bloque_pas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / sensors.PROCESS_CONFIG).write_text(
                "{ceci n'est pas du json", encoding="utf-8")
            table = load_categories(directory)
            self.assertEqual(categorize("chrome.exe", table), "browser")


class WatchingTest(unittest.TestCase):
    """Le point que le CDC ne peut pas atteindre tel qu'il est écrit.

    Le §16 phase 4 exige que `sit_and_watch` se déclenche sur une vidéo et pas
    sur de la musique de fond. WASAPI ne dit pas si un flux est une vidéo :
    côté son, YouTube et Spotify Web sont indiscernables. D'où l'heuristique,
    et d'où ces tests, qui en fixent le comportement exact.
    """

    def _watch(self, **kw) -> bool:
        args = dict(media_playing=True, media_seconds=40.0,
                    media_source="vlc.exe", foreground_process="vlc.exe",
                    cursor_still_seconds=10.0, coverage=0.9)
        args.update(kw)
        return is_watching(**args)

    def test_lecteur_video_local(self) -> None:
        for source in ("vlc.exe", "mpv.exe", "mpc-hc64.exe", "video.ui.exe"):
            self.assertTrue(
                self._watch(media_source=source, foreground_process=source,
                            coverage=0.2),
                f"{source} devrait suffire même en petite fenêtre")

    def test_musique_de_fond_jamais(self) -> None:
        """Le cas que le critère du CDC voulait exclure."""
        for source in ("spotify.exe", "itunes.exe", "foobar2000.exe"):
            self.assertFalse(
                self._watch(media_source=source, foreground_process=source,
                            coverage=1.0),
                f"{source} ne doit jamais déclencher watching")

    def test_une_video_derriere_pendant_le_travail_ne_compte_pas(self) -> None:
        """Défaut trouvé en sondant le système réel.

        Le son venait de Chrome, l'avant-plan était l'éditeur à 99 % de
        couverture, et le test de couverture — qui porte sur l'avant-plan —
        déclenchait `watching`. Travailler avec une vidéo derrière n'est pas
        regarder une vidéo.
        """
        self.assertFalse(self._watch(media_source="chrome.exe",
                                     foreground_process="code.exe",
                                     coverage=0.99))
        self.assertFalse(self._watch(media_source="vlc.exe",
                                     foreground_process="code.exe",
                                     coverage=0.99))

    def test_la_source_au_premier_plan_compte(self) -> None:
        self.assertTrue(self._watch(media_source="chrome.exe",
                                    foreground_process="chrome.exe",
                                    coverage=0.92))

    def test_les_applications_du_store_passent_par_leur_hote(self) -> None:
        """Une application UWP masque son process derrière ApplicationFrameHost.

        Le rapprochement par nom devient impossible : on retombe alors sur la
        liste des lecteurs vidéo connus.
        """
        self.assertTrue(self._watch(media_source="video.ui.exe",
                                    foreground_process="applicationframehost.exe",
                                    coverage=0.3))

    def test_sans_source_identifiee_jamais(self) -> None:
        self.assertFalse(self._watch(media_source="", foreground_process=""))

    def test_navigateur_en_grand_oui(self) -> None:
        """Une vidéo se regarde en grand."""
        self.assertTrue(self._watch(media_source="chrome.exe",
                                    foreground_process="chrome.exe",
                                    coverage=0.92))

    def test_navigateur_en_petit_non(self) -> None:
        """Une playlist tourne dans un onglet."""
        self.assertFalse(self._watch(media_source="chrome.exe",
                                     foreground_process="chrome.exe",
                                     coverage=0.35))

    def test_seuil_de_couverture(self) -> None:
        commun = dict(media_source="chrome.exe", foreground_process="chrome.exe")
        self.assertFalse(self._watch(coverage=WATCH_COVERAGE - 0.01, **commun))
        self.assertTrue(self._watch(coverage=WATCH_COVERAGE, **commun))

    def test_il_faut_une_duree_de_son_minimale(self) -> None:
        """CDC §11 : « media_playing vrai depuis plus de 20 s ».

        Le seuil est descendu à 8 s au lot L5 : la condition d'avant-plan filtre
        déjà les sons transitoires que ces 20 s visaient. Le test porte sur la
        constante, pas sur la valeur, pour rester juste après un réglage.
        """
        self.assertFalse(self._watch(media_seconds=WATCH_MEDIA_SECONDS - 0.5))
        self.assertTrue(self._watch(media_seconds=WATCH_MEDIA_SECONDS + 0.5))

    def test_il_faut_un_curseur_immobile(self) -> None:
        """CDC §11 : « curseur immobile »."""
        self.assertFalse(self._watch(cursor_still_seconds=0.0))
        self.assertFalse(self._watch(cursor_still_seconds=WATCH_STILL_SECONDS - 0.5))
        self.assertTrue(self._watch(cursor_still_seconds=WATCH_STILL_SECONDS))

    def test_sans_media_jamais(self) -> None:
        self.assertFalse(self._watch(media_playing=False))

    def test_les_deux_listes_sont_disjointes(self) -> None:
        self.assertEqual(VIDEO_SOURCES & AUDIO_ONLY_SOURCES, frozenset())


class ContextMatrixTest(unittest.TestCase):
    """Matrice de scénarios — critère d'acceptation du lot L5."""

    SCENARIOS = (
        # (libellé, idle_s, vitesse_curseur, watching, état attendu)
        ("frappe au clavier", 0.3, 0.0, False, "typing"),
        ("lecture, sans souris", 30.0, 0.0, False, "typing"),
        ("navigation à la souris", 0.4, 850.0, False, "browsing"),
        ("glissé lent", 1.0, CURSOR_MOVE_EPS + 1.0, False, "browsing"),
        ("pause de 2 minutes", 120.0, 0.0, False, "idle"),
        ("parti déjeuner", 1800.0, 0.0, False, "away"),
        ("film local en cours", 45.0, 0.0, True, "watching"),
        ("film long, deux heures", 4000.0, 0.0, True, "watching"),
    )

    def test_matrice(self) -> None:
        for label, idle, speed, watching, attendu in self.SCENARIOS:
            obtenu = derive_state(idle, speed, watching)
            self.assertEqual(obtenu, attendu,
                             f"{label} : attendu {attendu}, obtenu {obtenu}")

    def test_watching_prime_sur_idle_et_away(self) -> None:
        """Interprétation assumée du §11.

        `idle` et `away` sont déduits d'une **absence** de preuve, alors qu'un
        média qui joue devant un curseur immobile est une preuve **positive** de
        présence. Un film de deux heures ne doit pas faire croire le pet
        abandonné.
        """
        self.assertEqual(derive_state(4000.0, 0.0, True), "watching")
        self.assertEqual(derive_state(4000.0, 0.0, False), "away")

    def test_seuils_du_cdc(self) -> None:
        self.assertEqual(derive_state(IDLE_SECONDS - 0.1, 0.0, False), "typing")
        self.assertEqual(derive_state(IDLE_SECONDS, 0.0, False), "idle")
        self.assertEqual(derive_state(AWAY_SECONDS - 0.1, 0.0, False), "idle")
        self.assertEqual(derive_state(AWAY_SECONDS, 0.0, False), "away")

    def test_tous_les_etats_du_cdc_sont_atteignables(self) -> None:
        atteints = {derive_state(i, v, w)
                    for label, i, v, w, _ in self.SCENARIOS}
        for etat in ("typing", "browsing", "idle", "away", "watching"):
            self.assertIn(etat, atteints, f"{etat} inatteignable")


class CursorSensorTest(unittest.TestCase):
    def test_vitesse(self) -> None:
        capteur = CursorSensor()
        capteur.observe(0.0, (0, 0))
        capteur.observe(1.0, (300, 400))        # 500 px en 1 s
        self.assertAlmostEqual(capteur.speed, 500.0, places=3)

    def test_immobilite_s_accumule(self) -> None:
        capteur = CursorSensor()
        capteur.observe(0.0, (100, 100))
        for i in range(1, 11):
            capteur.observe(i * 0.25, (100, 100))
        self.assertAlmostEqual(capteur.still_seconds, 2.5, places=3)

    def test_un_mouvement_remet_l_immobilite_a_zero(self) -> None:
        capteur = CursorSensor()
        capteur.observe(0.0, (0, 0))
        capteur.observe(2.0, (0, 0))
        self.assertGreater(capteur.still_seconds, 1.0)
        capteur.observe(2.5, (200, 0))
        self.assertEqual(capteur.still_seconds, 0.0)

    def test_un_micro_tremblement_ne_compte_pas(self) -> None:
        """Un déplacement d'un pixel ne doit pas casser l'immobilité."""
        capteur = CursorSensor()
        capteur.observe(0.0, (100, 100))
        for i in range(1, 9):
            capteur.observe(i * 0.25, (100 + (i % 2), 100))
        self.assertGreater(capteur.still_seconds, 1.5)

    def test_pas_de_temps_nul(self) -> None:
        capteur = CursorSensor()
        capteur.observe(1.0, (0, 0))
        capteur.observe(1.0, (50, 0))           # ne doit pas diviser par zéro
        self.assertEqual(capteur.speed, 0.0)


class SensorsIntegrationTest(unittest.TestCase):
    """Les capteurs contre le vrai système. Peu d'assertions, mais réelles."""

    def test_un_cycle_complet_produit_un_contexte_valide(self) -> None:
        import time
        capteurs = sensors.Sensors()
        for i in range(4):
            now = time.perf_counter()
            capteurs.observe_cursor(now)
            capteurs.observe_slow(now, own_hwnd=0)
            time.sleep(0.05)

        context = capteurs.context
        self.assertIn(context.state,
                      {"typing", "browsing", "idle", "away", "watching"})
        self.assertIn(context.foreground_category, CATEGORIES)
        self.assertGreaterEqual(context.idle_seconds, 0.0)
        self.assertGreaterEqual(context.cursor_speed, 0.0)
        self.assertIsInstance(context.fullscreen, bool)
        self.assertIsInstance(context.media_playing, bool)

    def test_le_capteur_media_survit_a_l_absence_de_pycaw(self) -> None:
        """Un poste sans pilote audio ne doit pas empêcher le pet de tourner."""
        capteur = sensors.MediaSensor()
        capteur.available = False
        capteur.observe(1.0)
        self.assertFalse(capteur.playing)

    def test_les_peaks_collants_traversent_un_silence(self) -> None:
        """Un silence de dialogue ne doit pas remettre le compteur à zéro."""
        capteur = sensors.MediaSensor()
        capteur.available = True
        # L'énumération est neutralisée : sans cela le capteur repeuplait ses
        # sessions depuis le **vrai** système audio en cours de test, et un
        # onglet qui jouait de la musique invalidait le scénario.
        capteur._enumerate = lambda: None
        capteur._enumerated_at = 0.0
        capteur._meters = []                    # aucun pic lu

        capteur._last_peak_at = 10.0
        capteur._started_at = 5.0
        capteur.observe(11.0)                   # 1 s après le dernier pic
        self.assertTrue(capteur.playing)
        self.assertAlmostEqual(capteur.seconds, 6.0, places=3)

        capteur.observe(10.0 + sensors.AUDIO_STICKY_SECONDS + 1.0)
        self.assertFalse(capteur.playing, "au-delà de la fenêtre, la lecture cesse")


if __name__ == "__main__":
    unittest.main()

"""Objet QApplication partagé par toute la suite de tests.

Qt n'admet qu'une seule instance d'application par process, et elle doit être
un `QApplication` — un `QCoreApplication` ne permet pas d'instancier un QWidget,
et Qt avorte le process au lieu de lever une exception. Un module de tests qui
créerait le mauvais type ferait donc échouer silencieusement tous les suivants
en exécution groupée, sans même afficher de résumé.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


def ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app  # type: ignore[return-value]

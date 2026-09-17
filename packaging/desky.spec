# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller de Desky (CDC §15).

`onedir` et non `onefile`, comme le §15 l'impose. Ce n'est pas un détail de
confort : un `onefile` se décompresse dans un dossier temporaire à **chaque**
lancement, ce qui ajoute une seconde au démarrage à froid — le §3 en autorise
trois en tout — et fait de l'exécutable une cible bien plus suspecte pour les
heuristiques antivirus, précisément le risque que le §15 cherche à contenir.

Les dossiers de données sont embarqués **explicitement**, et c'est le seul
piège réel de ce fichier : PyInstaller suit les imports, pas les fichiers lus à
l'exécution. Sans ces lignes, l'application se construit sans erreur et échoue
au premier shader, chez le testeur et pas chez nous.

L'arborescence embarquée reproduit celle des sources (`pet/render/shaders`,
`pet/assets/items`, `pet/assets/brand`, `pet/assets/chassis`), ce qui permet
à `pet.resources` de
résoudre les deux cas avec la même logique.
"""

from pathlib import Path

RACINE = Path(SPECPATH).parent

datas = [
    (str(RACINE / "pet" / "render" / "shaders"), "pet/render/shaders"),
    (str(RACINE / "pet" / "assets" / "items"), "pet/assets/items"),
    (str(RACINE / "pet" / "assets" / "brand"), "pet/assets/brand"),
    (str(RACINE / "pet" / "assets" / "chassis"), "pet/assets/chassis"),
]

# Modules Qt inutilisés. PySide6 pèse l'essentiel des 90 à 160 Mo annoncés par
# le §15 ; l'application n'utilise que Core, Gui et Widgets, et écarter le reste
# est le seul levier de poids qui ne coûte rien.
excludes = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSerialPort",
    "PySide6.QtSensors", "PySide6.QtSpatialAudio", "PySide6.QtSvgWidgets",
    "PySide6.QtNfc", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtWebSockets",
    # Écosystème scientifique tiré par numpy, et dont rien n'est utilisé.
    "tkinter", "unittest", "pydoc", "doctest", "pdb",
    "matplotlib", "scipy", "pandas", "PIL",
]

a = Analysis(
    [str(RACINE / "pet" / "__main__.py")],
    pathex=[str(RACINE)],
    binaries=[],
    datas=datas,
    hiddenimports=["pet.main"],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Desky",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX aggrave la détection heuristique (§15)
    console=False,      # « sans console » (§15)
    disable_windowed_traceback=False,
    icon=str(RACINE / "packaging" / "desky.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Desky",
)

"""Point d'entrée du paquet, et **cible du gel PyInstaller** (lot L8).

`python -m pet` et le binaire gelé passent par ici, donc les deux exécutent
exactement le même chemin de démarrage — c'est ce qui évite qu'un défaut
n'apparaisse que dans la version distribuée.

Volontairement vide de toute logique : `main.py` impose un ordre de démarrage
strict, l'awareness DPI devant précéder l'import de Qt, et le dupliquer ici
serait le meilleur moyen de le voir diverger.
"""

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())

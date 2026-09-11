"""Point d'entrée du paquet, et **cible du gel PyInstaller** (lot L8).

`python -m pet` et le binaire gelé passent par ici, donc les deux exécutent
exactement le même chemin de démarrage — c'est ce qui évite qu'un défaut
n'apparaisse que dans la version distribuée.

Volontairement vide de toute logique : `main.py` impose un ordre de démarrage
strict, l'awareness DPI devant précéder l'import de Qt, et le dupliquer ici
serait le meilleur moyen de le voir diverger.

**L'import est absolu, et il doit le rester.** `python -m pet` pose
`__package__ = "pet"`, ce qui rend `from .main import ...` parfaitement légal —
mais PyInstaller, lui, exécute ce fichier comme un script de premier niveau,
sans paquet parent. Un import relatif y échoue au tout premier instant, avant
même que Qt ne soit chargé : « attempted relative import with no known parent
package », dans une boîte de dialogue, chez l'utilisateur et nulle part
ailleurs. La forme absolue fonctionne dans les deux mondes.
"""

import sys

from pet.main import main

if __name__ == "__main__":
    sys.exit(main())

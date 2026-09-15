"""Jeux du robot (lot L12).

Un jeu est une **partie** au sens propre : un état qui avance par pas de temps,
qui finit, et qui rend un score. Rien ici ne connaît Qt ni le rendu — la
fenêtre lit l'état et le peint, le `brain` le consulte pour savoir où aller.

C'est le même partage qu'entre `anim/easing` et `ui/motion`, ou entre
`anim/particles` et `ui/sparks`, et pour la même raison : ce qui calcule se
teste sans écran, et une partie entière peut être jouée en une seconde au pas
de temps synthétique — robot compris.

Le premier jeu est `rally` : ne pas laisser le ballon toucher le sol.
"""

from .balloon import Balloon
from .rally import OVER, PLAYER, PLAYING, ROBOT, SERVING, Rally

__all__ = ["Balloon", "Rally", "PLAYER", "ROBOT",
           "SERVING", "PLAYING", "OVER"]

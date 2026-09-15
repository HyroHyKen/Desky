"""Sous-systèmes de `PetWindow`, sortis du fichier de fenêtre (lot L10).

`window.py` avait atteint dix-huit cents lignes et mélangeait ce qui relève
vraiment d'une fenêtre — géométrie, boucle de rendu, entrées, hit-testing — avec
quatre sujets qui n'en relèvent pas : les objets de soin, la scène d'arrivée,
les réponses au panneau, et le journal de diagnostic.

**Des mixins, et non des collaborateurs.** Ces méthodes lisent et écrivent une
douzaine d'attributs de la fenêtre chacune. Les déplacer dans des objets à part
aurait demandé de leur passer la fenêtre à chaque appel : le couplage aurait
changé de forme sans diminuer, au prix d'une indirection à chaque ligne. Le
mixin déplace le **texte** sans toucher à la sémantique — `self` désigne la même
chose, aucun site d'appel ne bouge, et aucun test n'a eu à être réécrit. C'est
ce qui rend l'extraction vérifiable : la suite passe avant et après, à
l'identique.
"""

from .behaviour import BehaviourMixin
from .care import CareMixin
from .diag import DiagnosticsMixin
from .games import GamesMixin
from .items import ItemsMixin
from .onboarding import OnboardingMixin

__all__ = ["BehaviourMixin", "CareMixin", "DiagnosticsMixin", "GamesMixin",
           "ItemsMixin", "OnboardingMixin"]

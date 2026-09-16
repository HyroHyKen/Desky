"""Les soins qui se **jouent** plutôt qu'ils ne s'appliquent (lot L15).

Un consommable ordinaire agit au contact : le robot rejoint l'objet, la jauge
monte, c'est fini. Le bain ne fonctionne pas comme ça — il demande un geste
tenu, et ce geste a des règles. Ces règles vivent ici, sans Qt et sans GPU,
exactement comme celles de `pet/games` : c'est ce qui permet de rejouer un
nettoyage complet en test à `dt` synthétique, sans écran.

Le dossier existe au pluriel parce que le brossage et le séchage suivront la
même forme ; `wash` n'a rien de particulier qui mérite d'être au niveau du
dessus.
"""

from .wash import DONE, SPONGE, SPRAY, Foam, Wash

__all__ = ["DONE", "SPONGE", "SPRAY", "Foam", "Wash"]

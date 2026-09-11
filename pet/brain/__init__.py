"""Couche comportementale.

Cloison stricte du CDC §5 : **`brain` ne connaît pas `render`.** Il produit un
état symbolique — catégories, booléens, secondes — que `anim` traduit en poses.
C'est ce qui permet de tester le comportement sans GPU, et un test vérifie que
ce paquet n'importe rien de `pet.render` ni de `pet.anim`.
"""

"""Le robot comme joueur : où il se place, et quand il frappe (lot L12).

Pur, comme le reste du paquet. Il ne reçoit que des nombres — l'état de la
partie, le rectangle du pet — et rend une intention : une abscisse où aller, un
oui ou non pour frapper. La fenêtre exécute, elle ne décide pas.

**Il vise l'atterrissage, pas le ballon.** Courir sous un ballon en le suivant
des yeux est la façon la plus sûre d'arriver en retard : il dérive, et poursuivre
sa position courante fait toujours suivre une trajectoire plus longue que la
sienne. `Balloon.predict_landing` rejoue la physique jusqu'au sol et dit où il
va tomber ; le robot y va directement et attend.

**Il ne bouge pas pendant le tour du joueur.** C'est l'alternance stricte, vue
de son côté : aller se placer sous un ballon qui ne lui revient pas donnerait
l'impression qu'il triche, ou pire, qu'il attend une erreur.

**Il n'est pas parfait, et c'est voulu.** Il vise à un cheveu près, mais sa
vitesse de marche est celle du produit — il n'a pas de mode « jeu » où il se
téléporte. Quand le ballon devient lourd et tombe vite, il finit par ne plus
arriver à temps. C'est ce qui donne une fin à une partie que le joueur jouerait
parfaitement, et c'est une fin honnête : on voit le robot courir et manquer.
"""

from __future__ import annotations

from .balloon import Balloon
from .rally import ROBOT, Rally

# Portée **horizontale**, en hauteurs de pet, du centre du pet au centre du
# ballon. Généreuse : rater son ballon de trois pixels après avoir traversé
# l'écran serait une punition, et le §12 les interdit — c'est déjà le
# raisonnement de `REACH` pour les objets de soin.
REACH_X = 0.85

# Portées **verticales**, mesurées depuis le haut de la tête.
#
# Elles étaient confondues avec la portée horizontale, à 0,95 hauteur de pet
# au-dessus du crâne : le robot frappait donc un ballon flottant à deux fois sa
# propre hauteur, sans lever le bras ni sauter. Un robot qui touche ce qu'il ne
# peut visiblement pas atteindre annule l'enjeu du placement — autant le faire
# frapper depuis n'importe où.
#
# Vers le haut, on garde de quoi ne pas rater d'un cheveu un ballon qui
# affleure. Vers le bas, la hauteur du corps : il joue aussi du torse, et un
# ballon au niveau des pieds est encore à lui.
REACH_UP = 0.28
REACH_DOWN = 1.00

# Il se place légèrement **en avant** du point d'arrivée, du côté d'où vient le
# ballon : frapper un ballon qui tombe pile sur la tête l'envoie tout droit en
# l'air et le renvoie au même endroit, ce qui fait un échange sans déplacement
# et donne une partie statique.
LEAD = 0.22

# En dessous de cette hauteur au-dessus du sol, il frappe dès qu'il peut plutôt
# que d'attendre le contact parfait. Un ballon rattrapé à dix pixels du sol est
# plus spectaculaire qu'un ballon manqué proprement.
PANIC_HEIGHT = 0.55


def aim(rally: Rally, pet_h: float) -> float | None:
    """Abscisse où le robot doit se tenir, ou `None` s'il n'a rien à faire.

    `None` veut dire « reste où tu es » — pendant le tour du joueur, pendant le
    service, et après la fin de la partie.
    """
    if not rally.robot_turn:
        return None

    ballon = rally.balloon
    cible, _ = ballon.predict_landing()

    # Se décaler du côté d'où le ballon arrive. S'il tombe à la verticale, le
    # signe est arbitraire et le décalage sans conséquence.
    sens = -1.0 if ballon.vx >= 0.0 else 1.0
    cible += sens * LEAD * pet_h
    return max(ballon.left, min(ballon.right, cible))


def should_hit(rally: Rally, pet_x: float, pet_top: float,
               pet_h: float) -> bool:
    """Le robot peut-il frapper maintenant ?

    Le contact est mesuré entre le **haut** du pet et le ballon, pas entre les
    deux centres : c'est avec la tête qu'il joue, et un ballon qui passe à
    hauteur de pieds ne doit pas compter comme une frappe.
    """
    if not rally.robot_turn:
        return False
    ballon = rally.balloon
    if not ballon.can_hit:
        return False

    if abs(ballon.x - pet_x) > REACH_X * pet_h:
        return False

    # Positif quand le ballon est **au-dessus** de la tête.
    au_dessus = pet_top - ballon.y
    if au_dessus > REACH_UP * pet_h:
        return False                    # trop haut : il ne l'atteint pas

    # Au ras du sol, on ne fait plus la fine bouche sur la hauteur basse : un
    # ballon rattrapé à dix pixels du sol est plus spectaculaire qu'un ballon
    # manqué proprement. La borne haute, elle, tient toujours.
    if ballon.floor - ballon.y <= PANIC_HEIGHT * pet_h:
        return True
    return au_dessus >= -REACH_DOWN * pet_h


def play(rally: Rally, pet_x: float, pet_top: float, pet_h: float) -> bool:
    """Joue le tour du robot s'il le peut. Rend `True` s'il a frappé."""
    if not should_hit(rally, pet_x, pet_top, pet_h):
        return False
    return rally.hit(ROBOT, pet_x)


def unreachable(rally: Rally, pet_x: float, pet_h: float,
                speed: float) -> bool:
    """Le robot arrivera-t-il trop tard ?

    Sert au diagnostic et aux tests d'équilibrage : c'est ce prédicat qui dit à
    partir de combien d'échanges le ballon devient plus rapide que lui, donc où
    une partie jouée parfaitement finit par s'arrêter.
    """
    if not rally.robot_turn or speed <= 0.0:
        return False
    cible, delai = rally.balloon.predict_landing()
    return abs(cible - pet_x) / speed > delai

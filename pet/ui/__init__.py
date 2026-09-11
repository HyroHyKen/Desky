"""Interface de soin (CDC §13, lot L6 phase B).

L'interface a été **sans aucun texte** jusqu'au lot L7, où la règle a été levée
à la demande de l'utilisateur : des titres de page et des infobulles rendent les
pictogrammes explicites, et le gain d'usage est réel — une grille de quatre
carrés ne dit pas « interactions » tant qu'on ne l'a pas survolée.

La contrainte laisse une trace utile : les icônes ont été dessinées pour se
suffire, donc le texte les **précise** au lieu de les porter. Et elle laisse une
conséquence à tenir — l'interface est désormais traduisible. Tous les libellés
vivent donc dans une table unique en tête de `panel.py`, et un test vérifie
qu'aucune chaîne d'affichage n'est écrite en ligne dans une méthode de peinture.
Le seul écran sans titre est le statut : sa pastille d'humeur, le nom du robot
et ses quatre barres se suffisent.
"""

# Réveil du robot Instagram

Ce dossier pilote, depuis GitHub uniquement, le robot de publication Instagram de KingDream
Digital (dépôt privé `boriscorsiez/kingdream-digital`). Chaque jour :

| Heure (Paris) | Ce qui se passe |
|---|---|
| 11 h 28 | le robot est lancé : il prépare le post et le met en ligne à 12:00:00 |
| 12 h 04 | contrôle : si le post n'est pas en ligne, publication immédiate |
| 12 h 08 | dernier contrôle : un passage bloqué est annulé et le post republié |

Le post est en ligne au plus tard vers 12 h 10. Les minutes GitHub de ce dépôt public sont
gratuites.

**Le seul réglage** : le secret `ROBOT_GITHUB_TOKEN` de ce dépôt (*Settings* → *Secrets and
variables* → *Actions*). C'est un jeton GitHub à grain fin limité à `boriscorsiez/kingdream-digital`,
avec les droits *Actions : Read and write* et *Contents : Read-only*.

Tests : `python -m unittest robot/test_reveil.py`

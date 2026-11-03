# -*- coding: utf-8 -*-
"""
Reveil du robot Instagram de KingDream Digital : 100 % GitHub, sans aucun autre service.

Le robot de publication vit dans le depot prive boriscorsiez/kingdream-digital (workflow
instagram.yml). Sur ce depot, GitHub lance ses horaires programmes avec des heures de retard :
ce reveil, dans le depot public des images (minutes GitHub gratuites), demarre tot le matin,
attend l'heure, puis pilote le robot :

    11 h 28   lance le robot en mode « Midi pile » : il prepare le post et le met en ligne a 12:00:00
    12 h 04   controle : si le post n'est pas en ligne, publication immediate
    12 h 08   dernier controle : si un passage est bloque, il est annule et le post est republie
              -> le post est en ligne au plus tard vers 12 h 10

Un passage lance trop tot attend au plus ATTENTE_MAX, puis s'arrete : le passage suivant
(horaire suivant du workflow) prend le relais. Un passage lance apres midi fait directement le
controle et le rattrapage. Le fichier publication.json du post (ecrit par le robot) empeche
toute double publication.

Secret necessaire dans ce depot : ROBOT_GITHUB_TOKEN, un jeton GitHub limite au depot du robot,
droits « Actions : lecture et ecriture » et « Contents : lecture ».

    python robot/reveil.py            (dans le workflow .github/workflows/reveil-instagram.yml)
"""

import base64
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
DEPOT = os.environ.get("DEPOT_ROBOT", "boriscorsiez/kingdream-digital")
WORKFLOW = "instagram.yml"
BRANCHE = "master"
API = "https://api.github.com"

LANCEMENT = dt.time(11, 28)
MIDI = dt.time(12, 0)
CONTROLE = dt.time(12, 4)
DERNIER = dt.time(12, 8)
FIN = dt.time(21, 0)
ATTENTE_MAX = dt.timedelta(hours=5, minutes=45)   # un passage GitHub dure 6 h au plus (+ 11 min de travail)
ACTIFS = {"queued", "in_progress", "waiting", "requested", "pending"}

MIDI_PILE = {"post": "", "essai": "false", "midi": "true", "attendre": "false"}


def immediat(nom):
    return {"post": nom, "essai": "false", "midi": "false", "attendre": "false"}


class ErreurGithub(Exception):
    pass


class Github:
    """Appels minimaux a l'API GitHub du depot du robot."""

    def __init__(self, jeton):
        self.jeton = jeton

    def requete(self, methode, chemin, corps=None):
        donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
        req = urllib.request.Request(API + chemin, data=donnees, method=methode, headers={
            "Authorization": f"Bearer {self.jeton}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "kingdream-reveil-instagram",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as rep:
                texte = rep.read().decode("utf-8")
                return rep.status, (json.loads(texte) if texte else None)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, None
            raise ErreurGithub(f"{methode} {chemin} : HTTP {e.code} {e.reason}") from None

    def contenu(self, chemin):
        statut, corps = self.requete("GET", f"/repos/{DEPOT}/contents/{chemin}?ref={BRANCHE}")
        return corps if statut == 200 else None

    def passages(self):
        _, corps = self.requete("GET", f"/repos/{DEPOT}/actions/workflows/{WORKFLOW}/runs?per_page=10")
        return (corps or {}).get("workflow_runs", [])

    def lancer(self, inputs):
        self.requete("POST", f"/repos/{DEPOT}/actions/workflows/{WORKFLOW}/dispatches",
                     {"ref": BRANCHE, "inputs": inputs})

    def annuler(self, identifiant):
        self.requete("POST", f"/repos/{DEPOT}/actions/runs/{identifiant}/cancel")


def post_du_jour(gh, jour):
    """Dossier du post prevu ce jour (statut « pret »), ou None. Les posts recents ont les plus grands numeros."""
    entrees = gh.contenu("Instagram/posts") or []
    dossiers = sorted((e["name"] for e in entrees if e.get("type") == "dir"), reverse=True)
    for nom in dossiers:
        fichier = gh.contenu(f"Instagram/posts/{nom}/post.json")
        if not fichier:
            continue
        post = json.loads(base64.b64decode(fichier["content"]).decode("utf-8"))
        prevue = post.get("date_prevue", "")
        if prevue == jour.isoformat() and post.get("statut") == "pret":
            return nom
        if prevue and prevue < jour.isoformat():
            return None   # les suivants sont plus anciens
    return None


def publie(gh, nom):
    return gh.contenu(f"Instagram/posts/{nom}/publication.json") is not None


def passages_actifs(gh):
    return [r for r in gh.passages() if r.get("status") in ACTIFS]


def journal(texte):
    print(f"[{dt.datetime.now(PARIS):%H:%M:%S}] {texte}", flush=True)


def _debut(passage):
    texte = passage.get("run_started_at") or passage.get("created_at") or ""
    try:
        return dt.datetime.fromisoformat(texte.replace("Z", "+00:00"))
    except ValueError:
        return None


def reveil(gh, horloge=lambda: dt.datetime.now(PARIS), dormir=time.sleep):
    """Pilote le robot pour la journee. Retourne un court bilan (texte)."""
    depart = horloge()
    jour = depart.date()
    limite = depart + ATTENTE_MAX

    def a(heure):
        return dt.datetime.combine(jour, heure, tzinfo=PARIS)

    def attendre_jusqua(heure):
        reste = (a(heure) - horloge()).total_seconds()
        if reste > 0:
            journal(f"Attente jusqu'a {heure:%H:%M}.")
            dormir(reste)

    def verifier_pendant(minutes):
        for _ in range(minutes * 2):
            dormir(30)
            if publie(gh, nom):
                return True
        return False

    if depart.time() >= FIN:
        return "Apres 21 h : plus de publication aujourd'hui."
    nom = post_du_jour(gh, jour)
    if not nom:
        return "Aucun post prevu aujourd'hui."
    if publie(gh, nom):
        return f"{nom} est deja publie."

    # 1. 11 h 28 : lancer le robot, qui met le post en ligne a 12:00:00
    if depart.time() < MIDI:
        if a(LANCEMENT) > limite:
            dormir(max(0.0, (limite - horloge()).total_seconds()))
            return "Lance trop tot : le passage suivant prend le relais."
        attendre_jusqua(LANCEMENT)
        if publie(gh, nom):
            return f"{nom} est deja publie."
        if passages_actifs(gh):
            journal("Un passage du robot est deja en cours : rien a lancer.")
        else:
            gh.lancer(MIDI_PILE)
            journal("Robot lance : mise en ligne a 12:00:00.")
        if a(CONTROLE) > limite:
            return "Robot lance ; le controle de 12 h 04 revient au passage suivant (relais)."
        attendre_jusqua(CONTROLE)

    # 2. 12 h 04 : le post est-il en ligne ?
    if publie(gh, nom):
        return f"{nom} publie a midi."
    actifs = passages_actifs(gh)
    if actifs and horloge() < a(DERNIER):
        if a(DERNIER) > limite:
            return "Controle de 12 h 08 laisse au passage suivant (relais)."
        journal("Pas encore publie, un passage est en cours : dernier controle a 12 h 08.")
        attendre_jusqua(DERNIER)
        if publie(gh, nom):
            return f"{nom} publie."
        actifs = passages_actifs(gh)

    # 3. Rattrapage
    if actifs:
        # Seul le passage de midi, lance avant 12 h et toujours en cours a 12 h 08, est bloque :
        # on l'annule. Un passage de rattrapage lance apres midi est en train de publier : on l'attend.
        bloques = [r for r in actifs if r.get("status") == "in_progress"
                   and (_debut(r) or a(MIDI)) < a(MIDI)]
        if not bloques:
            journal("Un passage de rattrapage est en cours : on attend qu'il publie.")
            if verifier_pendant(10):
                return f"{nom} publie (rattrapage)."
            return f"::warning::{nom} : le passage en cours n'a pas encore publie (voir le depot du robot)."
        for r in bloques:
            journal(f"Passage n° {r.get('run_number')} bloque depuis midi : annule.")
            gh.annuler(r["id"])
        dormir(15)
    gh.lancer(immediat(nom))
    journal(f"Publication immediate de {nom} lancee.")
    if verifier_pendant(10):
        return f"{nom} publie (rattrapage)."
    return f"::warning::{nom} lance en publication immediate, pas encore confirme (voir le depot du robot)."


def main():
    jeton = os.environ.get("ROBOT_GITHUB_TOKEN")
    if not jeton:
        # En sommeil tant que le secret n'existe pas : aucune erreur, aucun e-mail.
        print("Reveil en sommeil : pas de secret ROBOT_GITHUB_TOKEN dans ce depot (voir robot/README.md).")
        return 0
    try:
        journal(reveil(Github(jeton)))
    except ErreurGithub as e:
        print(f"::error::{e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Tests du reveil, sans reseau : fausse horloge et faux GitHub.   python -m unittest robot/test_reveil.py"""

import base64
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reveil  # noqa: E402

P = reveil.PARIS
JOUR = dt.date(2026, 11, 4)


def heure(h, m=0):
    return dt.datetime.combine(JOUR, dt.time(h, m), tzinfo=P)


class Horloge:
    def __init__(self, debut):
        self.t = debut

    def __call__(self):
        return self.t

    def dormir(self, secondes):
        self.t += dt.timedelta(seconds=max(0, secondes))


class FauxGithub:
    """Le robot met le post en ligne a 12:00 (midi pile) ou 2 min apres une publication immediate."""

    def __init__(self, horloge, posts=None, bloque=False, publie_a=None, passages=None):
        self.h = horloge
        self.posts = posts if posts is not None else {"018_faux_email": "2026-11-04", "017_audit_page_par_page": "2026-11-03"}
        self.bloque = bloque
        self.publie_a = publie_a
        self.lances, self.annules = [], []
        self.runs = passages or []

    def contenu(self, chemin):
        if chemin == "Instagram/posts":
            return [{"name": n, "type": "dir"} for n in self.posts]
        nom, fichier = chemin.split("/")[2:4]
        if fichier == "post.json":
            corps = json.dumps({"date_prevue": self.posts[nom], "statut": "pret"}).encode()
            return {"content": base64.b64encode(corps).decode()}
        if fichier == "publication.json":
            return {} if (self.publie_a and self.h() >= self.publie_a) else None
        return None

    def passages(self):
        return [r for r in self.runs if r["status"] in reveil.ACTIFS or r.get("garde")]

    def lancer(self, inputs):
        self.lances.append((self.h(), dict(inputs)))
        debut = self.h().astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        if inputs["midi"] == "true":
            self.runs.append({"id": 1, "run_number": 101, "status": "in_progress", "run_started_at": debut})
            if not self.bloque:
                self.publie_a = heure(12, 0)
        else:
            self.runs.append({"id": 2, "run_number": 102, "status": "in_progress", "run_started_at": debut})
            self.publie_a = self.h() + dt.timedelta(minutes=2)

    def annuler(self, identifiant):
        self.annules.append(identifiant)
        for r in self.runs:
            if r["id"] == identifiant:
                r["status"] = "completed"


def lancer(debut, **options):
    h = Horloge(debut)
    gh = FauxGithub(h, **options)
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        bilan = reveil.reveil(gh, horloge=h, dormir=h.dormir)
    return gh, h, bilan


class Reveil(unittest.TestCase):
    def test_journee_normale(self):
        gh, h, bilan = lancer(heure(9, 0))
        self.assertEqual([(t.time(), i["midi"]) for t, i in gh.lances], [(dt.time(11, 28), "true")])
        self.assertIn("publie a midi", bilan)
        self.assertEqual(gh.annules, [])
        self.assertLessEqual(h.t, heure(12, 5))

    def test_lance_trop_tot_passe_le_relais(self):
        gh, h, bilan = lancer(heure(3, 0))
        self.assertEqual(gh.lances, [])
        self.assertIn("relais", bilan)
        self.assertEqual(h.t, heure(3, 0) + reveil.ATTENTE_MAX)

    def test_lance_a_6h_lance_puis_passe_le_controle(self):
        gh, h, bilan = lancer(heure(6, 10))
        self.assertEqual([t.time() for t, _ in gh.lances], [dt.time(11, 28)])
        self.assertIn("relais", bilan)
        self.assertLess(h.t, heure(12, 0))

    def test_relais_apres_le_lancement_ne_relance_pas(self):
        """Le passage suivant demarre a 11 h 29 : le robot tourne deja, il ne fait que controler."""
        actif = {"id": 1, "run_number": 101, "status": "in_progress", "run_started_at": "2026-11-04T10:28:00Z"}
        gh, h, bilan = lancer(heure(11, 29), publie_a=heure(12, 0), passages=[actif])
        self.assertEqual(gh.lances, [])
        self.assertIn("publie a midi", bilan)

    def test_robot_bloque_annule_a_12h08_et_republie(self):
        gh, h, bilan = lancer(heure(10, 0), bloque=True)
        self.assertEqual(gh.annules, [1])
        self.assertEqual([i["post"] for _, i in gh.lances], ["", "018_faux_email"])
        self.assertGreaterEqual(gh.lances[1][0], heure(12, 8))
        self.assertLess(gh.lances[1][0], heure(12, 9))
        self.assertIn("rattrapage", bilan)
        self.assertLessEqual(gh.publie_a, heure(12, 11))

    def test_robot_jamais_lance_rattrape_a_12h04(self):
        gh, h, bilan = lancer(heure(12, 4))
        self.assertEqual([i["post"] for _, i in gh.lances], ["018_faux_email"])
        self.assertIn("rattrapage", bilan)

    def test_rattrapage_en_cours_l_apres_midi_n_est_pas_annule(self):
        actif = {"id": 7, "run_number": 107, "status": "in_progress", "run_started_at": "2026-11-04T11:35:00Z"}
        gh, h, bilan = lancer(heure(12, 40), publie_a=heure(12, 42), passages=[actif])
        self.assertEqual(gh.annules, [])
        self.assertEqual(gh.lances, [])
        self.assertIn("rattrapage", bilan)

    def test_deja_publie(self):
        gh, h, bilan = lancer(heure(11, 0), publie_a=heure(0, 0))
        self.assertEqual(gh.lances, [])
        self.assertIn("deja publie", bilan)

    def test_pas_de_post(self):
        gh, h, bilan = lancer(heure(9, 0), posts={"017_audit_page_par_page": "2026-11-03"})
        self.assertEqual(gh.lances, [])
        self.assertIn("Aucun post", bilan)

    def test_jamais_plus_de_6_heures(self):
        for depart in range(0, 12):
            for minute in (0, 17, 43):
                gh, h, _ = lancer(heure(depart, minute), bloque=True)
                self.assertLessEqual(h.t - heure(depart, minute), dt.timedelta(hours=6), (depart, minute))


if __name__ == "__main__":
    unittest.main()

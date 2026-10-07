import tempfile, unittest
from pathlib import Path
from arena.ledger import Ledger
from arena.bot import Arena


class LedgerTests(unittest.TestCase):
    def test_a_viewer_starts_with_the_start_xp_and_cannot_spend_more_than_they_have(self):
        with tempfile.TemporaryDirectory() as d:
            l = Ledger(Path(d) / "x.sqlite")
            l.seen("ann", "Ann", 50)
            self.assertEqual(l.xp("ann"), 50)
            self.assertFalse(l.spend("ann", 100))
            l.add("ann", 60)
            self.assertTrue(l.spend("ann", 100))
            self.assertEqual(l.xp("ann"), 10)

    def test_no_study_event_is_kept_without_an_irb_approval(self):
        with tempfile.TemporaryDirectory() as d:
            l = Ledger(Path(d) / "x.sqlite")
            l.seen("ann", "Ann", 50)
            l.event("predict", "ann", side=0)
            self.assertEqual(l.db.execute("select count(*) from events").fetchone()[0], 0)
            s = Ledger(Path(d) / "y.sqlite", study="IRB-0000")
            s.seen("ann", "Ann", 50)
            s.event("predict", "ann", side=0)
            pid, data = s.db.execute("select pid, data from events").fetchone()
            self.assertNotIn("ann", pid + data, "a study event carried the login")

    def test_a_share_code_decodes_to_the_tree_it_was_made_from(self):
        import base64, json
        tree = {"reaction_ticks": 10, "rules": [{"do": "guard"}]}
        code = base64.b64encode(json.dumps(tree).encode()).decode()
        self.assertEqual(json.loads(Arena.decode(code)), tree)
        self.assertIsNone(Arena.decode("not a code"))


if __name__ == "__main__":
    unittest.main()

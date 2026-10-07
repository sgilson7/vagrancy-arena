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


class TreesCommandTests(unittest.TestCase):
    def arena(self, d):
        a = Arena(ledger_path=Path(d) / "x.sqlite", chat=False)
        a.sent, a.said, a.clock = [], [], 1000.0
        async def send(msg): a.sent.append(msg)
        async def say(text): a.said.append(text)
        a.send, a.chat.say, a.now = send, say, lambda: a.clock
        return a

    def test_a_viewer_turns_the_trees_off_and_nobody_can_turn_them_back_until_the_hold_ends(self):
        import asyncio
        from arena.bot import CONFIG
        with tempfile.TemporaryDirectory() as d:
            a = self.arena(d)
            asyncio.run(a.on_chat("viewer", "Viewer", "!trees off", False))
            self.assertEqual(a.trees, "off")
            self.assertIn({"type": "trees", "show": False}, a.sent)
            a.clock += CONFIG["trees_hold_seconds"] - 1
            asyncio.run(a.on_chat("sam", "Sam", "!trees on", True))
            asyncio.run(a.on_chat("sam", "Sam", "!trees sometimes", True))
            self.assertEqual(a.trees, "off", "a moderator changed the trees during a hold")
            a.clock += 2
            self.assertEqual(a.trees, "on", "the hold did not end on time")
            asyncio.run(a.on_chat("viewer", "Viewer", "!trees off", False))
            self.assertEqual(a.trees, "off", "a new hold could not start after the last one ended")

    def test_only_the_broadcaster_or_a_moderator_can_set_the_trees_to_sometimes(self):
        import asyncio
        with tempfile.TemporaryDirectory() as d:
            a = self.arena(d)
            asyncio.run(a.on_chat("viewer", "Viewer", "!trees sometimes", False))
            self.assertEqual(a.trees, "on")
            asyncio.run(a.on_chat("sam", "Sam", "!trees sometimes", True))
            self.assertEqual(a.trees, "sometimes")


class SpeedCommandTests(unittest.TestCase):
    def test_a_speed_change_locks_out_the_next_one_for_a_minute(self):
        import asyncio
        from arena.bot import CONFIG
        with tempfile.TemporaryDirectory() as d:
            a = TreesCommandTests.arena(None, d)
            asyncio.run(a.on_chat("viewer", "Viewer", "!speed quarter", False))
            self.assertEqual(a.speed, 0.25)
            self.assertIn({"type": "speed", "value": 0.25}, a.sent)
            a.clock += CONFIG["speed_lock_seconds"] - 1
            asyncio.run(a.on_chat("sam", "Sam", "!speed double", True))
            self.assertEqual(a.speed, 0.25, "the speed changed during the lockout")
            a.clock += 2
            asyncio.run(a.on_chat("other", "Other", "!speed double", False))
            self.assertEqual(a.speed, 2, "the lockout did not end on time")


class SubmitCostTests(unittest.TestCase):
    def test_a_tree_costs_the_submit_cost_and_a_refused_tree_gives_it_back(self):
        import asyncio, base64, json
        from arena.bot import CONFIG
        with tempfile.TemporaryDirectory() as d:
            a = TreesCommandTests.arena(None, d)
            code = base64.b64encode(json.dumps({"reaction_ticks": 10, "rules": [{"do": "guard"}]}).encode()).decode()
            verdict = {"ok": True}
            async def check(tree): return verdict
            a.check_tree = check
            asyncio.run(a.on_chat("ann", "Ann", f"!submit {code}", False))
            self.assertEqual(a.queue, [], "a viewer without the submit cost queued a tree")
            a.ledger.add("ann", CONFIG["submit_cost"])
            verdict = {"ok": False, "key": "btlab.editor.refuse.number"}
            before = a.ledger.xp("ann")
            asyncio.run(a.on_chat("ann", "Ann", f"!submit {code}", False))
            self.assertEqual((a.queue, a.ledger.xp("ann")), ([], before), "a refused tree kept the experience")
            verdict = {"ok": True}
            asyncio.run(a.on_chat("ann", "Ann", f"!submit {code}", False))
            self.assertEqual((len(a.queue), a.ledger.xp("ann")), (1, before - CONFIG["submit_cost"]))


class PageReturnTests(unittest.TestCase):
    def test_a_page_that_comes_back_mid_fight_is_sent_the_fight_under_way(self):
        import asyncio, json
        with tempfile.TemporaryDirectory() as d:
            a = TreesCommandTests.arena(None, d)
            fight = {"type": "exhibition", "left": {"id": "drover"}, "right": {"id": "cooper"}}
            a.current, a.result = fight, None

            class Page:
                def __init__(self): self.msgs = [json.dumps({"type": "hello", "roster": ["drover"]})]
                def __aiter__(self): return self
                async def __anext__(self):
                    if not self.msgs: raise StopAsyncIteration
                    return self.msgs.pop(0)
            asyncio.run(a.page_handler(Page()))
            self.assertIn(fight, a.sent, "the page that came back was not sent the fight under way")


if __name__ == "__main__":
    unittest.main()

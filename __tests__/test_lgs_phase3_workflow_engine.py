"""LGS Phase 3 tests — workflow engine.

Drives the engine end-to-end with a stateful fake `_sb` (in-memory stand-in
for the workflow_runs / workflow_definitions / businesses tables) so we can
assert: enqueue dedup, internal step execution, the confirmation gate, the
connector seam no-op, and a full multi-step run reaching 'done'. No live DB.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import workflow_engine as we


class ConditionsMatchTests(unittest.TestCase):
    def test_empty_conditions_match(self):
        self.assertTrue(we._conditions_match({}, {"amount": 5}))

    def test_equality_match(self):
        self.assertTrue(we._conditions_match({"plan": "pro"}, {"plan": "pro", "x": 1}))

    def test_mismatch(self):
        self.assertFalse(we._conditions_match({"plan": "pro"}, {"plan": "free"}))


class FakeSB:
    """Stateful fake for workflow_engine._sb. Holds a steps list + a biz row;
    records every PATCH to workflow_runs so tests assert the final state."""

    def __init__(self, steps):
        self.steps = steps
        self.run_patches = []          # list of patch bodies applied to the run
        self.posts = []                # (path, body) for POST calls
        self.enqueue_code = 201        # override to 409 to test dedup

    async def __call__(self, client, method, path, body=None, prefer=None):
        if method == "GET" and path.startswith("/workflow_definitions"):
            return 200, [{"steps": self.steps}]
        if method == "GET" and path.startswith("/businesses"):
            return 200, [{"id": "biz-1", "name": "Test Biz", "voice_profile": {}}]
        if method == "GET" and path.startswith("/custom_modules"):
            return 200, [{"agent_config": {}}]  # non-restricted
        if method == "GET" and path.startswith("/connectors"):
            return 200, []  # no connector → connector steps skip
        if method == "PATCH" and path.startswith("/workflow_runs"):
            self.run_patches.append(body)
            return 200, [body]
        if method == "POST" and path.startswith("/workflow_runs"):
            return self.enqueue_code, ([body] if self.enqueue_code < 400 else None)
        if method == "POST":
            self.posts.append((path, body))
            return 201, [body]
        return 200, []

    def final_status(self):
        for p in reversed(self.run_patches):
            if "status" in p:
                return p["status"]
        return None


class EnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_ok(self):
        fake = FakeSB(steps=[{"action": "log"}])
        with patch.object(we, "_sb", fake):
            res = await we.enqueue_run(None, {"id": "wf-1", "slug": "w", "steps": [{"action": "log"}]},
                                       "biz-1", "idem-1")
        self.assertEqual(res["status"], "enqueued")

    async def test_enqueue_dedup_409(self):
        fake = FakeSB(steps=[{"action": "log"}]); fake.enqueue_code = 409
        with patch.object(we, "_sb", fake):
            res = await we.enqueue_run(None, {"id": "wf-1", "slug": "w", "steps": []},
                                       "biz-1", "idem-dup")
        self.assertEqual(res["status"], "skipped_duplicate")


class ExecuteStepTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_log_step(self):
        fake = FakeSB(steps=[])
        with patch.object(we, "_sb", fake):
            res = await we.execute_step(None, {"step_cursor": 0, "business_id": "b"}, {},
                                        {"action": "log", "params": {"message": "hi"}}, {})
        self.assertTrue(res["ok"])

    async def test_update_context_mutates_ctx(self):
        ctx = {}
        res = await we.execute_step(None, {"step_cursor": 0}, {},
                                    {"action": "update_context", "params": {"k": "v"}}, ctx)
        self.assertTrue(res["ok"])
        self.assertEqual(ctx.get("k"), "v")

    async def test_confirmation_gate_pauses(self):
        # requires_confirmation + cursor not in _confirmed_steps → pause
        res = await we.execute_step(None, {"step_cursor": 1}, {},
                                    {"action": "log", "requires_confirmation": True}, {})
        self.assertTrue(res.get("pause"))

    async def test_confirmation_gate_passes_when_confirmed(self):
        res = await we.execute_step(None, {"step_cursor": 1}, {},
                                    {"action": "log", "requires_confirmation": True},
                                    {"_confirmed_steps": [1]})
        self.assertTrue(res.get("ok"))
        self.assertFalse(res.get("pause", False))

    async def test_connector_seam_no_connector_skips(self):
        fake = FakeSB(steps=[])
        with patch.object(we, "_sb", fake):
            res = await we.execute_step(None, {"step_cursor": 0, "business_id": "b"}, {},
                                        {"action": "connector.enroll", "params": {"provider": "learnworlds"}}, {})
        self.assertTrue(res["ok"])
        self.assertEqual(res.get("skipped"), "no_connector")  # generic seam, no instance code

    async def test_unknown_action_fails(self):
        fake = FakeSB(steps=[])
        with patch.object(we, "_sb", fake):
            res = await we.execute_step(None, {"step_cursor": 0, "business_id": "b"}, {},
                                        {"action": "definitely_not_a_real_action"}, {})
        self.assertFalse(res["ok"])


class AdvanceRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_step_run_reaches_done(self):
        steps = [
            {"action": "log", "params": {"message": "start"}},
            {"action": "update_context", "params": {"flag": True}},
        ]
        fake = FakeSB(steps=steps)
        run = {"id": "run-1", "workflow_id": "wf-1", "business_id": "biz-1",
               "step_cursor": 0, "context": {}, "log": []}
        with patch.object(we, "_sb", fake):
            res = await we.advance_run(None, run)
        self.assertEqual(res["status"], "done")
        self.assertEqual(fake.final_status(), "done")

    async def test_confirmation_step_halts_run(self):
        steps = [
            {"action": "log"},
            {"action": "log", "requires_confirmation": True},  # gate here
            {"action": "log"},
        ]
        fake = FakeSB(steps=steps)
        run = {"id": "run-2", "workflow_id": "wf-1", "business_id": "biz-1",
               "step_cursor": 0, "context": {}, "log": []}
        with patch.object(we, "_sb", fake):
            res = await we.advance_run(None, run)
        self.assertEqual(res["status"], "awaiting_confirmation")
        self.assertEqual(res["step"], 1)
        self.assertEqual(fake.final_status(), "awaiting_confirmation")

    async def test_failing_step_marks_failed(self):
        steps = [{"action": "log"}, {"action": "no_such_action"}]
        fake = FakeSB(steps=steps)
        run = {"id": "run-3", "workflow_id": "wf-1", "business_id": "biz-1",
               "step_cursor": 0, "context": {}, "log": []}
        with patch.object(we, "_sb", fake):
            res = await we.advance_run(None, run)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(fake.final_status(), "failed")


if __name__ == "__main__":
    unittest.main()

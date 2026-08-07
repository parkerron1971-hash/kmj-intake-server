"""Session agent — PHI gate.

Kevin's ruling 2026-08-07: a therapist's session content must not be
handed to a model provider. Every draft on this agent builds its prompt
from the client's NAME plus the session type and title, which for a
therapist reads "this named person is in mental-health treatment".

The frontend hides the buttons (FE#398), but the endpoints take a bare
business_id and chief_of_staff's AGENT_ENDPOINT_MAP wires all three to
Chief actions — so the UI is not the gate. This is.

These tests exist because the gate is easy to delete by accident: it is
three inline conditionals in front of three model calls, and nothing
about removing one of them looks wrong in a diff. What SHOULD break is
this file.

Run via:
  pytest -q __tests__/test_session_agent_phi_gate.py
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import session_agent


COACH = {"id": "biz-coach", "name": "Clearway Coaching", "type": "coach",
         "voice_profile": {}, "settings": {"practitioner_name": "Dana"}}
THERAPIST = {"id": "biz-thera", "name": "Quiet Harbour", "type": "therapist",
             "voice_profile": {}, "settings": {"practitioner_name": "Dr Reyes"}}

SESSION = {
    "id": "sess-1",
    "contact_id": "contact-1",
    "title": "Intake",
    "session_type": "therapy_session",
    "scheduled_for": "2026-08-01T15:00:00+00:00",
    "notes": None,
}


class IsClinicalTests(unittest.TestCase):
    def test_therapist_is_clinical(self):
        self.assertTrue(session_agent._is_clinical({"type": "therapist"}))

    def test_other_verticals_are_not(self):
        for t in ("coach", "consultant", "lawyer", "ministry",
                  "personal_services", "contractor"):
            self.assertFalse(session_agent._is_clinical({"type": t}), t)

    def test_tolerates_case_padding_and_absence(self):
        self.assertTrue(session_agent._is_clinical({"type": "  Therapist "}))
        self.assertFalse(session_agent._is_clinical({"type": None}))
        self.assertFalse(session_agent._is_clinical({}))


class _Harness:
    """Stands in for Supabase. Records writes so the test can assert the
    workflow still ran, not merely that the model call did not."""

    def __init__(self):
        self.posts: list[tuple[str, dict]] = []
        self.patches: list[tuple[str, dict]] = []

    async def sb(self, client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts"):
            return [{"id": "contact-1", "name": "Jordan Vale",
                     "email": "j@example.com", "health_score": 50}]
        if method == "GET":
            return []
        if method == "POST":
            self.posts.append((path, body or {}))
            return [{"id": "row-1"}]
        if method == "PATCH":
            self.patches.append((path, body or {}))
            return [{"id": "row-1"}]
        return None

    def queued_draft(self):
        for path, body in self.posts:
            if path == "/agent_queue":
                return body
        return None


class NoShowPhiGateTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, business):
        h = _Harness()
        claude = AsyncMock(return_value="MODEL WROTE THIS")
        with patch.object(session_agent, "_sb", new=AsyncMock(side_effect=h.sb)), \
             patch.object(session_agent, "_call_claude", new=claude):
            await session_agent._noshow_one_session(None, business, SESSION)
        return h, claude

    async def test_therapist_never_reaches_the_model(self):
        h, claude = await self._run(THERAPIST)
        claude.assert_not_awaited()
        draft = h.queued_draft()
        self.assertIsNotNone(draft, "the draft must still be queued")
        self.assertNotIn("MODEL WROTE THIS", draft["body"])
        # Honest attribution — no model ran, so none is recorded.
        self.assertIsNone(draft["ai_model"])

    async def test_therapist_keeps_the_whole_workflow(self):
        # The point of gating rather than blocking: a therapist still
        # gets the draft, the health decay and the event.
        h, _ = await self._run(THERAPIST)
        self.assertIsNotNone(h.queued_draft())
        self.assertTrue(any(p.startswith("/contacts") for p, _ in h.patches),
                        "health score should still decay")
        self.assertTrue(any(p == "/events" for p, _ in h.posts),
                        "no-show event should still be written")

    async def test_coach_still_gets_the_model(self):
        # The gate must be narrow. If this fails the feature was removed
        # for everybody rather than withheld from one vertical.
        h, claude = await self._run(COACH)
        claude.assert_awaited()
        draft = h.queued_draft()
        self.assertEqual(draft["body"], "MODEL WROTE THIS")
        self.assertEqual(draft["ai_model"], session_agent.DRAFT_MODEL)


if __name__ == "__main__":
    unittest.main()

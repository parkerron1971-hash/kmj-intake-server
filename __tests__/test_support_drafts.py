"""The Support desk agent drafts, never sends, and never leaks builder words.

Drafts live on the operator-only triage row and reach a practitioner only
through the reply endpoint when a person sends them. A draft must answer
the latest thing the practitioner said, and must pass the same wording
guard every system message to a practitioner passes.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import support_drafts as sd
import support_router as sr


def item(**kw):
    base = {"id": "t1", "lane": "triage", "answered": False, "awaiting_you": False,
            "created_at": "2026-10-01T10:00:00+00:00", "last_message_at": None,
            "business_id": "b1", "subject": "Invoice won't send", "message": "It errors.",
            "category": "bug", "rank": 5, "thread": [], "repeats": 1, "fix_state": "new"}
    base.update(kw)
    return base


# --- which tickets need a draft --------------------------------------

def test_never_answered_needs_an_answer():
    assert sd.needs_answer(item())


def test_answered_and_not_waiting_needs_nothing():
    assert not sd.needs_answer(item(answered=True))


def test_practitioner_spoke_last_needs_an_answer_to_that():
    it = item(answered=True, awaiting_you=True, last_message_at="2026-10-02T09:00:00+00:00")
    assert sd.needs_answer(it)
    assert sd.answers_for(it) == "2026-10-02T09:00:00+00:00"


def test_closed_needs_nothing():
    assert not sd.needs_answer(item(lane="closed"))


def test_a_newer_message_makes_the_draft_stale():
    it = item(answered=True, awaiting_you=True, last_message_at="2026-10-02T09:00:00+00:00")
    old = {"draft_reply": "x", "draft_for_at": "2026-10-01T10:00:00+00:00"}
    new = {"draft_reply": "x", "draft_for_at": "2026-10-02T09:00:00+00:00"}
    assert not sd.draft_is_current(old, it)
    assert sd.draft_is_current(new, it)


# --- parsing and the wording guard -----------------------------------

def test_parse_accepts_real_line_breaks_inside_the_reply():
    raw = '{"reply": "Hi there.' + chr(10) + chr(10) + '- The Solutionist team", "summary": "s"}'
    d = sd._parse(raw)
    assert d and d["reply"].startswith("Hi there.")


def test_parse_tolerates_a_fence_and_drops_unknown_labels():
    d = sd._parse('```json\n{"reply": "Hi there", "summary": "s", "category": "weird", "severity": "high"}\n```')
    assert d == {"reply": "Hi there", "summary": "s", "category": None, "severity": "high"}
    assert sd._parse("no json here") is None
    assert sd._parse('{"reply": ""}') is None


class _Resp:
    def __init__(self, text, status=200):
        self.status_code, self._text, self.text = status, text, text

    def json(self):
        return {"content": [{"type": "text", "text": self._text}]}


def _model_says(monkeypatch, text, status=200):
    import llm_call
    seen = {}

    async def apost(client, payload, **kw):
        seen.update(payload=payload, kw=kw)
        return _Resp(text, status)

    monkeypatch.setattr(llm_call, "apost", apost)
    return seen


def test_a_draft_with_builder_words_never_survives(monkeypatch):
    _model_says(monkeypatch, '{"reply": "We fixed it in GitHub PR #12 with Claude.", '
                             '"summary": "s", "category": "bug", "severity": "high"}')
    assert asyncio.run(sd.draft_one(None, item(), {})) is None


def test_a_clean_draft_is_returned_and_never_billed_to_the_practitioner(monkeypatch):
    seen = _model_says(monkeypatch, '{"reply": "Thanks for telling us. We are looking into it.\n— The Solutionist team", '
                                    '"summary": "invoice send error", "category": "bug", "severity": "high"}')
    d = asyncio.run(sd.draft_one(None, item(), {"name": "Acme"}))
    assert d["reply"].startswith("Thanks for telling us") and d["severity"] == "high"
    assert seen["kw"]["units"] == 0 and seen["kw"]["business_id"] == "b1"
    assert "Invoice won't send" in seen["payload"]["messages"][0]["content"]


def test_a_model_error_is_no_draft(monkeypatch):
    _model_says(monkeypatch, "overloaded", status=529)
    assert asyncio.run(sd.draft_one(None, item(), {})) is None


# --- the pass --------------------------------------------------------

class _Client:
    def __init__(self):
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.posts.append(json)


def test_tick_drafts_only_what_waits_and_caps_the_pass(monkeypatch):
    waiting = [item(id=f"t{i}", rank=i) for i in range(8)]
    answered = item(id="done", answered=True, rank=99)
    own = item(id="own", rank=98, business_id="kmj")
    has_draft = item(id="drafted", rank=50)
    queue = {"lanes": {"triage": waiting + [answered, has_draft, own]}}
    client = _Client()
    written = []

    async def load(c):
        return queue

    async def triage_for(c, ids):
        return {"drafted": {"draft_reply": "x", "draft_for_at": "2026-10-01T10:00:00+00:00"}}

    async def draft_one(c, it, biz):
        return {"reply": "Hi", "summary": "s", "category": "bug", "severity": "normal", "model": "m"}

    async def upsert(c, ticket, patch):
        written.append((ticket["id"], patch))

    async def business(c, bid):
        return {"owner_id": "kevin"} if bid == "kmj" else {"owner_id": "someone"}

    import platform_watchdog

    async def owner(c, h):
        return "kevin"

    monkeypatch.setattr(platform_watchdog, "_owner_user_id", owner)

    monkeypatch.setattr(sr, "_load_queue", load)
    monkeypatch.setattr(sr, "_triage_for", triage_for)
    monkeypatch.setattr(sr, "_upsert_triage", upsert)
    monkeypatch.setattr(sd, "draft_one", draft_one)
    monkeypatch.setattr(sd, "_business", business)
    monkeypatch.setattr(sd, "_service_headers", lambda: {})
    monkeypatch.setattr(sd.httpx, "AsyncClient", lambda **kw: client)
    import spend_guard
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)

    out = asyncio.run(sd.drafts_tick())
    ids = [t for t, _ in written]
    assert out["ok"] and len(ids) == sd.MAX_PER_TICK
    assert "done" not in ids and "drafted" not in ids
    assert "own" not in ids, "no reply drafted to the platform owner himself"
    assert ids == ["t7", "t6", "t5", "t4", "t3"], "highest rank first"
    assert written[0][1]["draft_for_at"] == "2026-10-01T10:00:00+00:00"
    run = client.posts[-1]
    assert run["agent"] == "support_desk" and run["details"]["drafted"] == 5
    assert run["details"]["skipped_owner_own"] == 1


def test_tick_stops_when_over_budget(monkeypatch):
    import spend_guard
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: True)
    assert asyncio.run(sd.drafts_tick()) == {"skipped": True, "reason": "over_budget"}


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("SUPPORT_DRAFTS", "off")
    assert asyncio.run(sd.drafts_tick()) == {"skipped": True}


# --- what the queue shows the operator --------------------------------

def test_queue_shows_a_current_draft():
    t = {"created_at": "2026-10-01T10:00:00+00:00", "last_message_author": None}
    tr = {"draft_reply": "Hi", "draft_for_at": "2026-10-01T10:00:00+00:00", "draft_summary": "s"}
    assert sr._current_draft(t, tr)["reply"] == "Hi"


def test_queue_hides_a_draft_once_answered():
    t = {"created_at": "2026-10-01T10:00:00+00:00", "replied_at": "2026-10-01T11:00:00+00:00",
         "last_message_author": "operator"}
    tr = {"draft_reply": "Hi", "draft_for_at": "2026-10-01T10:00:00+00:00"}
    assert sr._current_draft(t, tr) is None


def test_queue_hides_a_stale_draft():
    t = {"created_at": "2026-10-01T10:00:00+00:00", "replied_at": "2026-10-01T11:00:00+00:00",
         "last_message_author": "practitioner", "last_message_at": "2026-10-02T09:00:00+00:00"}
    tr = {"draft_reply": "Hi", "draft_for_at": "2026-10-01T10:00:00+00:00"}
    assert sr._current_draft(t, tr) is None

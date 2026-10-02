"""
test_proposal_life.py — a proposal expires, reminds, and reaches the phone.

What must hold:
  1. A FILED PROPOSAL CARRIES AN EXPIRY when the table can hold one,
     files without it when it cannot, and pushes to the owner with the
     two buttons — nothing executes from the push.
  2. EXPIRY IS HONEST. Only drafts still in draft are flipped; the row
     says why; the practitioner is told in the rail and the inbox, never
     by push. If the CHECK refuses `expired`, dismissed-with-reason.
  3. ONE REMINDER PER DRAFT, one per business per twelve hours, waking
     hours only. Expiry runs at any hour.
  4. THE BRIEF COUNTS what needs a hand; a lead alert hands over the
     drafted reply instead of the contact when one is waiting.
  5. THE AGENT IS TOLD to draft a new lead's first reply.
House rules: sync tests + asyncio.run.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import action_proposals as ap
import proposal_life as pl
import push_notifications as push
import sb_clients

NOON = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)
NIGHT = datetime(2026, 9, 8, 4, 0, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_probe(monkeypatch):
    monkeypatch.setitem(pl._probe, "ok", None)
    monkeypatch.setitem(pl._probe, "at", 0.0)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    yield


# ─── 1. filing ───────────────────────────────────────────────────────

def test_filing_extras_follow_the_table(monkeypatch):
    assert pl.filing_extras(NOON) == {}, "no Supabase URL: never probed, never set"
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: None)
    assert pl.columns_supported() is False and pl.filing_extras(NOON) == {}
    monkeypatch.setitem(pl._probe, "ok", None)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])
    assert pl.columns_supported() is True
    assert pl.filing_extras(NOON) == {"expires_at": "2026-09-10T16:00:00Z"}


def test_file_carries_the_expiry_and_pushes_with_buttons(monkeypatch):
    posts, pushed = [], []
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": posts.append((p, b)) or [{"id": "q-1", **b}])
    monkeypatch.setattr(pl, "filing_extras", lambda now=None, hours=None: {"expires_at": "2026-09-10T16:00:00Z"})
    monkeypatch.setattr(pl, "announce_filed", lambda bid, qid, sentence: pushed.append((bid, qid, sentence)) or 1)
    qid = ap.file("biz-1", {"type": "send_sms", "contact_id": "c-1", "message": "See you Thursday"},
                  actor="chief:agent", surface="agent")
    assert qid == "q-1" and posts[0][1]["expires_at"] == "2026-09-10T16:00:00Z"
    assert pushed and pushed[0][:2] == ("biz-1", "q-1") and "Thursday" in pushed[0][2]


def test_announce_reaches_the_owner_with_two_buttons_and_never_runs_anything(monkeypatch):
    sent = []
    monkeypatch.setattr(push, "push_enabled", lambda: True)
    monkeypatch.setattr(push, "send_to_user", lambda uid, **kw: sent.append((uid, kw)) or 1)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"owner_id": "own-1"}])
    assert pl.announce_filed("biz-1", "q-9", "Text Ada: see you Thursday") == 1
    uid, kw = sent[0]
    assert uid == "own-1" and kw["nav"] == "operate:queue" and kw["tag"] == "proposal-q-9"
    assert [a["action"] for a in kw["actions"]] == ["approve", "later"]
    assert kw["data"] == {"approve_id": "q-9", "business_id": "biz-1"}
    monkeypatch.setattr(push, "push_enabled", lambda: False)
    assert pl.announce_filed("biz-1", "q-9", "x") == 0


def test_the_push_payload_carries_buttons_and_data():
    p = push._payload("t", "b", "operate:queue", "tag", pl.ACTIONS, {"approve_id": "q", "nested": {"no": 1}})
    assert p["actions"] == pl.ACTIONS and p["data"] == {"approve_id": "q"}
    assert "actions" not in push._payload("t", "b", "home") and "data" not in push._payload("t", "b", "home")


# ─── 2 + 3. the tick ─────────────────────────────────────────────────

@pytest.fixture
def queue(monkeypatch):
    state = {"rows": [], "patches": [], "posts": [], "pushed": [], "recent": False, "refuse_expired": False}

    def _get(path):
        if path.startswith("/agent_queue"):
            return list(state["rows"])
        if path.startswith("/businesses"):
            return [{"id": "biz-1", "owner_id": "own-1", "name": "Bloom"},
                    {"id": "biz-2", "owner_id": "own-2", "name": "Cut"}]
        if path.startswith("/chief_notifications"):
            return [{"id": "n"}] if state["recent"] else []
        return []

    def _patch(path, body):
        state["patches"].append((path, body))
        if body.get("status") == "expired" and state["refuse_expired"]:
            return None
        return [{"id": "x"}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _patch)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: state["posts"].append((p, b)) or [{}])
    monkeypatch.setattr(push, "send_to_user", lambda uid, **kw: state["pushed"].append((uid, kw)) or 1)
    monkeypatch.setattr(pl, "columns_supported", lambda: True)
    return state


def test_expiry_flips_only_drafts_and_tells_the_practitioner_without_a_push(queue):
    queue["rows"] = [{"id": "q-1", "business_id": "biz-1", "subject": "Text Ada", "contact_id": "c-1"}]
    assert pl.expire_due(NOON) == ["q-1"]
    path, body = queue["patches"][0]
    assert "id=eq.q-1" in path and "status=eq.draft" in path and body["status"] == "expired"
    kinds = [(p, b.get("action_type") or b.get("type")) for p, b in queue["posts"]]
    assert ("/chief_activity", "proposal_expired") in kinds and ("/chief_notifications", "reminder") in kinds
    assert not queue["pushed"], "an expiry is news, not an interruption"
    assert "Text Ada" in queue["posts"][0][1]["label"]


def test_expiry_falls_back_to_dismissed_when_the_check_is_not_widened(queue):
    queue["rows"] = [{"id": "q-1", "business_id": "biz-1", "subject": "Text Ada"}]
    queue["refuse_expired"] = True
    assert pl.expire_due(NOON) == ["q-1"]
    assert queue["patches"][-1][1]["status"] == "dismissed"
    assert "Expired unapproved" in queue["patches"][-1][1]["ai_reasoning"]


def test_reminders_are_one_per_business_and_mark_every_draft(queue):
    queue["rows"] = [{"id": "q-1", "business_id": "biz-1", "subject": "Text Ada"},
                     {"id": "q-2", "business_id": "biz-1", "subject": "Send invoice 12"},
                     {"id": "q-3", "business_id": "biz-2", "subject": "Text Bo"}]
    assert sorted(pl.remind_due(NOON)) == ["biz-1", "biz-2"]
    notes = [b for p, b in queue["posts"] if p == "/chief_notifications"]
    assert len(notes) == 2 and notes[0]["title"] == "2 things need your hand"
    assert notes[0]["action_payload"]["dedup_key"] == "needs_hand:biz-1" and "Text Ada" in notes[0]["body"]
    assert notes[1]["title"] == "One thing needs your hand"
    pushes = {uid: kw for uid, kw in queue["pushed"]}
    assert pushes["own-1"].get("actions") is None, "two items: open the queue, no approve button"
    assert pushes["own-2"]["actions"] == pl.ACTIONS and pushes["own-2"]["data"]["approve_id"] == "q-3"
    marks = [(p, b) for p, b in queue["patches"] if "reminded_at" in b]
    assert any("q-1,q-2" in p for p, _ in marks) and any("q-3" in p for p, _ in marks)


def test_a_business_reminded_recently_is_not_reminded_again_but_its_drafts_are_marked(queue):
    queue["rows"] = [{"id": "q-1", "business_id": "biz-1", "subject": "Text Ada"}]
    queue["recent"] = True
    assert pl.remind_due(NOON) == []
    assert not queue["pushed"] and not queue["posts"]
    assert queue["patches"] and "reminded_at" in queue["patches"][0][1]


def test_the_tick_expires_at_night_and_reminds_only_by_day(monkeypatch, queue):
    calls = []
    monkeypatch.setattr(pl, "expire_due", lambda now=None: calls.append("expire") or [])
    monkeypatch.setattr(pl, "remind_due", lambda now=None: calls.append("remind") or [])
    _run(pl.proposals_tick(NIGHT))
    assert calls == ["expire"]
    _run(pl.proposals_tick(NOON))
    assert calls == ["expire", "expire", "remind"]
    monkeypatch.setattr(pl, "columns_supported", lambda: False)
    assert _run(pl.proposals_tick(NOON)) == {"skipped": "migration"}
    monkeypatch.setenv("PROPOSAL_LIFE", "off")
    assert _run(pl.proposals_tick(NOON)) == {"skipped": "off"}


# ─── 4. the brief and the lead alerts ────────────────────────────────

def test_the_morning_brief_counts_what_needs_a_hand(monkeypatch):
    import notification_engine as ne
    seen = []

    async def _sb(client, method, path, body=None):
        seen.append(path)
        if "channel=eq.action" in path:
            return [{"id": "q-1", "subject": "Text Ada"}]
        return []
    monkeypatch.setattr(ne, "_sb", _sb)
    data = _run(ne._gather_morning_data(None, "biz-1"))
    assert data["needs_your_hand"] == [{"id": "q-1", "subject": "Text Ada"}]
    assert "NEEDS_YOUR_HAND (1)" in ne._format_data_for_prompt(data)
    assert any("channel=eq.action" in p and "status=eq.draft" in p for p in seen)


def test_a_hot_lead_alert_hands_over_the_drafted_reply(monkeypatch):
    import notification_engine as ne
    alerts = []

    async def _sb(client, method, path, body=None):
        if path.startswith("/businesses"):
            return [{"id": "biz-1", "settings": {}}]
        if path.startswith("/events"):
            return [{"contact_id": "c-1", "event_type": "contact_form_submitted",
                     "contacts": {"name": "Ada", "lead_score": 90}}]
        return []
    monkeypatch.setattr(ne, "_sb", _sb)

    async def _alert(client, biz_id, title, body, **kw):
        alerts.append((title, body, kw))
        return {"id": "n-1"}
    monkeypatch.setattr(ne, "create_urgent_alert", _alert)
    monkeypatch.setattr(pl, "waiting_for_contact", lambda bid, cid: {"id": "q-1", "subject": "Text Ada"})
    _run(ne._check_urgent(None, "biz-1"))
    title, body, kw = alerts[0]
    assert "drafted the reply" in body and kw["suggested_action"] == "Open the reply"
    assert kw["action_payload"]["sub"] == "queue"
    alerts.clear()
    monkeypatch.setattr(pl, "waiting_for_contact", lambda bid, cid: None)
    _run(ne._check_urgent(None, "biz-1"))
    title, body, kw = alerts[0]
    assert "drafted" not in body and kw["action_payload"]["sub"] == "contacts"


def test_waiting_for_contact_is_a_read_that_never_raises(monkeypatch):
    def _boom(path):
        raise RuntimeError("down")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    assert pl.waiting_for_contact("biz-1", "c-1") is None
    assert pl.waiting_for_contact("biz-1", None) is None


# ─── 5. the agent's words ────────────────────────────────────────────

def test_the_agent_is_told_to_draft_a_new_leads_first_reply():
    import chief_agent
    assert "propose_send_sms" in chief_agent._SYSTEM and "NEW LEAD" in chief_agent._SYSTEM
    assert "acting on your own" in chief_agent._SYSTEM, "the older tests' anchor stays"

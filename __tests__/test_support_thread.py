"""The conversation on a ticket, and the wall around it.

A practitioner reports something and then hears nothing: that is the
failure this file guards. So the ticket now tells its own story — someone
is looking, a fix is being worked on, it has shipped — and the person can
write back into the same thread.

Every one of those messages is tenant-readable. That is the point of them,
and it is the whole risk: support_triage holds what the operator thinks and
support_ticket_messages holds what the practitioner is told, and the tests
here exist to keep the first out of the second. The sentence that closes a
ticket now comes from a session that has spent an hour inside a repo, and
a session that has spent an hour inside a repo talks like one.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import support_queue as sq
import support_router as sr
import support_thread as st
from auth_supabase import AuthedUser

TICKET = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TASK = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
BIZ = "cccccccc-cccc-cccc-cccc-cccccccccccc"
OWNER = "dddddddd-dddd-dddd-dddd-dddddddddddd"
STRANGER = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATION = os.path.join(ROOT, "supabase", "APPLY-2026-09-02-support-thread.sql")


def _ticket(**kw):
    return {"id": TICKET, "business_id": BIZ, "business_name": "Test Salon",
            "category": "bug", "subject": "Cancel does nothing",
            "message": "nothing happens", "status": "open", "stage": "received",
            "created_at": "2026-09-01T00:00:00Z", **kw}


# ─── the stage a practitioner sees ───────────────────────────────────

def test_every_fix_state_maps_to_a_stage():
    """A fix_state with no stage would leave a ticket showing whatever it
    showed last while the work moved on underneath — the exact silence
    this is meant to end."""
    assert set(st.STAGE_OF_FIX_STATE) == set(sq.FIX_STATES)
    assert set(st.STAGE_OF_FIX_STATE.values()) <= set(st.STAGES)


def test_every_stage_has_words_for_it():
    assert set(st.STAGE_LABEL) == set(st.STAGES)


def test_an_unknown_fix_state_degrades_to_a_working_badge():
    assert st.stage_of("something_new_in_2027") == "received"
    assert st.stage_of(None) == "received"


def test_the_migration_does_not_constrain_stage():
    """Deliberately no CHECK — the archetype constraint went out of step
    with the app's own list and Postgres then rejected writes the app had
    already reported as successful. Stages will gain values."""
    sql = open(MIGRATION, encoding="utf-8").read().lower()
    assert "add column if not exists stage text" in sql
    assert not re.search(r"stage\s+text[^;]*check", sql)


def test_the_authors_the_code_writes_are_the_authors_the_check_allows():
    sql = open(MIGRATION, encoding="utf-8").read()
    m = re.search(r"author\s+text not null check \(author in \(([^)]*)\)", sql, re.I)
    assert m
    allowed = set(re.findall(r"'([a-z]+)'", m.group(1)))
    assert allowed == {"practitioner", "support", "system"}


# ─── the guard ───────────────────────────────────────────────────────

@pytest.mark.parametrize("sentence", [
    "Fixed in PR #785, merged to main.",
    "Opened a GitHub issue and Claude picked it up.",
    "The repo had a stale branch; rebuilt and deployed.",
    "Added a migration on the supabase side.",
    "See https://github.com/x/y/pull/1 for the change.",
    "Patched the endpoint that was throwing a stack trace.",
])
def test_workshop_language_never_reaches_a_practitioner(sentence):
    ok, hits = st.practitioner_safe(sentence)
    assert not ok and hits
    assert st.clean_for_practitioner(sentence, "STANDARD") == "STANDARD"


@pytest.mark.parametrize("sentence", [
    "The cancel button on a booking works now — it cancels straight away.",
    "Your invoices will show the right total from now on.",
    "That page loads again; it was timing out on large contact lists.",
])
def test_a_sentence_about_their_business_goes_through_as_written(sentence):
    ok, hits = st.practitioner_safe(sentence)
    assert ok and not hits
    assert st.clean_for_practitioner(sentence, "STANDARD") == sentence


def test_every_system_message_passes_its_own_guard():
    """The one that catches a careless future edit: the sentences the
    ticket says about itself are checked by the same wall as the ones a
    session writes."""
    for kind, body in st.SYSTEM_MESSAGE.items():
        ok, hits = st.practitioner_safe(body)
        assert ok, f"{kind} would be blocked by its own guard: {hits}"


def test_an_empty_or_enormous_sentence_falls_back():
    assert st.clean_for_practitioner("", "STANDARD") == "STANDARD"
    assert st.clean_for_practitioner("   ", "STANDARD") == "STANDARD"
    assert st.clean_for_practitioner("x" * 401, "STANDARD") == "STANDARD"


def test_the_email_list_names_only_real_messages():
    assert set(st.EMAIL_ON) <= set(st.SYSTEM_MESSAGE)


# ─── appending, and the wall at the last moment ──────────────────────

@pytest.fixture
def sb(monkeypatch):
    """Records every write instead of making it."""
    state = {"inserts": [], "patches": [], "triage": {}}

    async def fake_insert(c, path, body, upsert=False):
        state["inserts"].append((path, body))
        return [{**body, "id": "msg-1", "created_at": "2026-09-02T10:00:00Z"}]

    async def fake_patch(c, path, params, body):
        state["patches"].append((path, body))

    async def fake_get(c, path, params):
        if path == "support_triage":
            return [state["triage"]] if state["triage"] else []
        if path == "businesses":
            return [{"owner_id": OWNER}]
        if path == "support_tickets":
            return [state.get("ticket") or _ticket()]
        return []

    monkeypatch.setattr(sr, "_sb_insert", fake_insert)
    monkeypatch.setattr(sr, "_sb_patch", fake_patch)
    monkeypatch.setattr(sr, "_sb_get", fake_get)
    return state


@pytest.mark.anyio
async def test_a_message_writes_the_badge_in_the_same_breath(sb):
    ticket = _ticket()
    await sr._append_message(None, ticket, "system",
                             st.SYSTEM_MESSAGE["working"], kind="working")
    table, row = sb["inserts"][0]
    assert table == "support_ticket_messages"
    assert row["author"] == "system" and row["kind"] == "working"
    assert row["business_id"] == BIZ

    _t, patch = sb["patches"][0]
    assert patch["stage"] == "working"
    assert patch["last_message_author"] == "system"
    # The badge and the thread are one event — the ticket in hand carries
    # the new stage too, so the next decision reads the truth.
    assert ticket["stage"] == "working"


@pytest.mark.anyio
async def test_an_internal_system_message_is_refused_at_the_write(sb):
    """The wall stands at the last possible moment, not only at the API
    edge — a future caller passing workshop language straight in gets a
    500, not a practitioner reading about a pull request."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await sr._append_message(None, _ticket(), "system",
                                 "Merged the PR on the frontend repo.", kind="fixed")
    assert not sb["inserts"]


@pytest.mark.anyio
async def test_a_practitioners_own_words_are_never_second_guessed(sb):
    """The guard is on what the SYSTEM says, not on what a person says. A
    practitioner writing 'the deploy broke my site' must not be silently
    swallowed."""
    await sr._append_message(None, _ticket(), "practitioner",
                             "since the deploy my github link is broken")
    assert sb["inserts"]


@pytest.mark.anyio
async def test_the_same_news_is_not_announced_twice(sb):
    await sr._note_transition(None, _ticket(stage="working"), "working")
    assert not sb["inserts"]
    await sr._note_transition(None, _ticket(stage="looking"), "working")
    assert len(sb["inserts"]) == 1


@pytest.mark.anyio
async def test_a_transition_that_cannot_be_written_never_breaks_the_move(sb, monkeypatch):
    """The board's correctness must not depend on the telling."""
    async def boom(*a, **kw):
        raise RuntimeError("supabase is having a day")

    monkeypatch.setattr(sr, "_append_message", boom)
    await sr._note_transition(None, _ticket(), "working")   # must not raise


# ─── the walk-back now speaks ────────────────────────────────────────

@pytest.mark.anyio
@pytest.mark.parametrize("dev_status,expect_kind", [
    ("working", "working"),
    ("done", "fixed"),
    ("failed", "stalled"),
])
async def test_the_ticket_tells_its_own_story_as_the_work_moves(
        monkeypatch, dev_status, expect_kind):
    """What the walk-back ASKS to say. Whether it is actually said twice is
    _note_transition's rule, and it has its own test above — keeping the
    say-once check in one place is why this one asserts the ask."""
    triage = {TICKET: {"ticket_id": TICKET, "fix_state": "queued",
                       "dev_task_id": TASK, "severity": "high"}}
    ticket = _ticket(stage="working")
    said = []

    async def fake_patch(c, path, params, body):
        if path == "support_triage":
            triage[TICKET].update(body)

    async def fake_note(c, tkt, kind):
        if kind:
            said.append(kind)

    monkeypatch.setattr(sr, "_sb_patch", fake_patch)
    monkeypatch.setattr(sr, "_note_transition", fake_note)

    await sr._reconcile(None, triage, {TASK: {"id": TASK, "status": dev_status}},
                        {TICKET: ticket})
    assert said == ([expect_kind] if expect_kind else [])


# ─── the sentence the fix writes ─────────────────────────────────────

@pytest.mark.anyio
async def test_the_session_sentence_reaches_them_when_it_is_fit_to_send(sb, monkeypatch):
    sb["triage"] = {"ticket_id": TICKET, "fix_state": "fixing",
                    "dev_task_id": TASK, "note": None}
    sb["ticket"] = _ticket(stage="working")
    sent = {}

    async def fake_email(c, ticket, text):
        sent["body"] = text
        return True, None

    monkeypatch.setattr(sr, "_email_practitioner", fake_email)

    told = await sr.note_fix_shipped(
        TASK, "The cancel button on a booking works now.")
    assert told
    msg = [b for p, b in sb["inserts"] if p == "support_ticket_messages"][0]
    assert msg["body"] == "The cancel button on a booking works now."
    assert msg["kind"] == "fixed"
    assert sent["body"] == msg["body"]          # and it was actually sent


@pytest.mark.anyio
async def test_a_workshop_sentence_is_replaced_and_kept_where_only_you_see_it(
        sb, monkeypatch):
    sb["triage"] = {"ticket_id": TICKET, "fix_state": "fixing",
                    "dev_task_id": TASK, "note": None}
    sb["ticket"] = _ticket(stage="working")

    async def fake_email(c, ticket, text):
        return True, None

    monkeypatch.setattr(sr, "_email_practitioner", fake_email)

    assert await sr.note_fix_shipped(TASK, "Fixed in PR #785 on the frontend repo.")

    msg = [b for p, b in sb["inserts"] if p == "support_ticket_messages"][0]
    assert msg["body"] == st.SYSTEM_MESSAGE["fixed"]
    assert "PR #785" not in msg["body"]
    # Not lost — it is on the operator-only note.
    notes = [b.get("note") for p, b in sb["patches"] if p == "support_triage"]
    notes += [b.get("note") for p, b in sb["inserts"] if p == "support_triage"]
    assert any(n and "PR #785" in n for n in notes)


@pytest.mark.anyio
async def test_an_ordinary_dev_task_is_not_a_ticket(sb):
    sb["triage"] = {}
    assert await sr.note_fix_shipped(TASK, "anything") is False
    assert not sb["inserts"]


# ─── their end of it ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_a_stranger_cannot_read_or_write_someone_elses_ticket(sb):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        await sr.add_ticket_message(
            TICKET, sr.TicketMessageBody(text="hello"),
            user=AuthedUser(id=STRANGER, email="x@y.com", role="authenticated"))
    # 404, not 403: whether a ticket id exists is not a stranger's business.
    assert e.value.status_code == 404


@pytest.mark.anyio
async def test_their_reply_reopens_a_closed_ticket_and_nudges_you(sb, monkeypatch):
    sb["triage"] = {"ticket_id": TICKET, "fix_state": "answered"}
    sb["ticket"] = _ticket(status="resolved", stage="answered")
    nudged = {}

    async def fake_nudge(subject, body):
        nudged["subject"] = subject

    monkeypatch.setattr(sr, "_email_operator", fake_nudge)

    out = await sr.add_ticket_message(
        TICKET, sr.TicketMessageBody(text="still not working for me"),
        user=AuthedUser(id=OWNER, email="owner@biz.com", role="authenticated"))
    assert out["ok"]

    # It is back in the queue…
    triage_writes = [b for p, b in sb["patches"] if p == "support_triage"]
    triage_writes += [b for p, b in sb["inserts"] if p == "support_triage"]
    assert any(w.get("fix_state") == "triaged" for w in triage_writes)
    # …their own view stops saying resolved…
    assert any(b.get("status") == "in_progress"
               for p, b in sb["patches"] if p == "support_tickets")
    # …and somebody knows a person is waiting.
    assert "replied" in nudged["subject"]


# ─── and it climbs the queue ─────────────────────────────────────────

def test_a_ticket_they_replied_to_outranks_one_nobody_has_touched():
    waiting, why = sq.rank({"created_at": "2026-09-01T00:00:00Z",
                            "last_message_author": "practitioner"},
                           {"severity": "normal",
                            "first_response_at": "2026-09-01T01:00:00Z"})
    quiet, _ = sq.rank({"created_at": "2026-09-01T00:00:00Z",
                        "last_message_author": "support"},
                       {"severity": "normal",
                        "first_response_at": "2026-09-01T01:00:00Z"})
    assert waiting > quiet
    assert "they replied, waiting on you" in why


@pytest.fixture
def anyio_backend():
    return "asyncio"

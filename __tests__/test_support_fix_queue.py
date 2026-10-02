"""The fix queue: the order it puts things in, and the doors it closes.

Two things are guarded here.

First, the ORDER. A queue nobody trusts is a queue nobody uses, and the
way trust dies is a blocker sitting under a feature idea because the
feature idea is newer. So: severity dominates, age eventually beats a tie,
repeats outrank one-offs, and an explicitly-set severity is never quietly
replaced by the keyword guess (the upsert that seeded a triage row on every
write would have done exactly that — see _upsert_triage).

Second, the DOORS. /platform/support/* is the owner's; /dev-bridge/tickets
is a paired device's; and a device token may open a local session but may
never fire a cloud build, because that spends the platform owner's budget.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import support_queue as sq
import support_router as sr

TICKET = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TASK = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
BIZ = "cccccccc-cccc-cccc-cccc-cccccccccccc"

MIGRATION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "supabase", "APPLY-2026-09-02-support-fix-queue.sql")


# ─── the vocabulary matches the database ─────────────────────────────
# The archetype CHECK taught this repo the lesson the hard way: an app
# that accepts a value Postgres rejects writes nothing and says nothing.

def _check_values(column: str) -> set:
    sql = open(MIGRATION, encoding="utf-8").read()
    m = re.search(rf"{column}\s+text[^;]*?check\s*\({column} in \(([^)]*)\)",
                  sql, re.S | re.I)
    assert m, f"no CHECK found for {column} in the migration"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def test_severities_match_the_migration():
    assert _check_values("severity") == set(sq.SEVERITIES)


def test_fix_states_match_the_migration():
    assert _check_values("fix_state") == set(sq.FIX_STATES)


def test_every_fix_state_has_a_lane():
    assert set(sq.LANES) == set(sq.FIX_STATES)


# ─── severity, guessed ───────────────────────────────────────────────

@pytest.mark.parametrize("category,subject,message,expected", [
    ("question", "Help", "I cannot log in since this morning", "blocker"),
    ("bug", "Everything is gone", "lost all my contacts", "blocker"),
    ("billing", "Invoice question", "how do I read this", "high"),
    ("bug", "Cancel button", "I click cancel and it does not work", "high"),
    ("bug", "Odd wording", "the label reads a bit strangely", "normal"),
    ("feature", "Would love tags", "tags on contacts", "low"),
    ("general", "Small thing", "there is a typo on the invoice", "low"),
    ("question", "How do I add a client", "cannot find the button", "normal"),
])
def test_guess_severity(category, subject, message, expected):
    got, why = sq.guess_severity(category, subject, message)
    assert got == expected, f"{subject!r} -> {got} ({why})"
    assert why


def test_severity_guess_is_stable():
    a = sq.guess_severity("bug", "It broke", "error on save")
    b = sq.guess_severity("bug", "It broke", "error on save")
    assert a == b


# ─── the order ───────────────────────────────────────────────────────

def _t(created="2026-09-01T00:00:00Z", **kw):
    return {"id": TICKET, "created_at": created, **kw}


def test_a_blocker_outranks_a_month_old_feature_idea():
    fresh_blocker, _ = sq.rank(_t(), {"severity": "blocker"})
    old_idea, _ = sq.rank(_t("2026-07-01T00:00:00Z"), {"severity": "low"})
    assert fresh_blocker > old_idea


def test_age_breaks_the_tie_between_equals():
    now = sq.parse_ts("2026-09-02T00:00:00Z")
    old, _ = sq.rank(_t("2026-08-01T00:00:00Z"), {"severity": "normal"}, now=now)
    new, _ = sq.rank(_t("2026-09-01T00:00:00Z"), {"severity": "normal"}, now=now)
    assert old > new


def test_age_never_lifts_a_normal_over_a_fresh_high():
    """The cap earns its keep: nothing rots forever, but a stale nuisance
    must not displace a real problem reported this morning."""
    now = sq.parse_ts("2027-09-02T00:00:00Z")     # a YEAR old
    ancient, _ = sq.rank(_t("2026-09-01T00:00:00Z"), {"severity": "normal"}, now=now)
    fresh, _ = sq.rank(_t("2027-09-02T00:00:00Z"), {"severity": "high"}, now=now)
    assert fresh > ancient


def test_repeats_outrank_a_single_report():
    many, why = sq.rank(_t(), {"severity": "normal"}, repeats=4)
    one, _ = sq.rank(_t(), {"severity": "normal"}, repeats=1)
    assert many > one
    assert any("4 reports" in w for w in why)


def test_an_unanswered_ticket_carries_weight():
    silent, why = sq.rank(_t(), {"severity": "normal"})
    answered, _ = sq.rank(_t(), {"severity": "normal",
                                 "first_response_at": "2026-09-01T01:00:00Z"})
    assert silent > answered
    assert "never answered" in why


def test_rank_always_explains_itself():
    _, why = sq.rank(_t("2026-08-01T00:00:00Z"), {"severity": "high"}, repeats=2)
    assert why[0] == "high"
    assert len(why) >= 2


# ─── clustering ──────────────────────────────────────────────────────

def test_word_order_does_not_split_one_problem():
    a = sq.problem_key("bug", "booking cancel broken", "", {"screen": "booking"})
    b = sq.problem_key("bug", "cancel broken on booking", "", {"screen": "booking"})
    assert a == b


def test_different_screens_are_different_problems():
    a = sq.problem_key("bug", "save fails", "", {"screen": "invoices"})
    b = sq.problem_key("bug", "save fails", "", {"screen": "contacts"})
    assert a != b


def test_problem_key_survives_an_empty_subject():
    assert sq.problem_key("bug", "", "", None)


# ─── seeding: turning it on does not dump history into the triage lane ─

def test_a_resolved_ticket_seeds_closed_not_new():
    row = sr._seed_triage({"id": TICKET, "category": "bug", "subject": "x",
                           "message": "error", "status": "resolved",
                           "replied_at": "2026-08-01T00:00:00Z"})
    assert row["fix_state"] == "answered"
    assert sq.lane_of(row["fix_state"]) == "closed"
    assert row["first_response_at"] == "2026-08-01T00:00:00Z"


def test_an_in_progress_ticket_seeds_ready():
    row = sr._seed_triage({"id": TICKET, "category": "bug", "subject": "x",
                           "message": "error", "status": "in_progress"})
    assert row["fix_state"] == "triaged"
    assert row["triaged_by"] == "auto"


# ─── the write that used to overwrite a human decision ───────────────

@pytest.mark.anyio
async def test_upsert_keeps_a_hand_set_severity(monkeypatch):
    existing = {"ticket_id": TICKET, "severity": "blocker", "fix_state": "triaged",
                "triaged_by": "kmjcreativesolution@gmail.com"}
    patched = {}

    async def fake_get(c, path, params):
        return [existing]

    async def fake_patch(c, path, params, body):
        patched.update(body)

    async def fake_insert(c, path, body, upsert=False):
        raise AssertionError("must patch the existing row, never re-seed it")

    monkeypatch.setattr(sr, "_sb_get", fake_get)
    monkeypatch.setattr(sr, "_sb_patch", fake_patch)
    monkeypatch.setattr(sr, "_sb_insert", fake_insert)

    out = await sr._upsert_triage(
        None, {"id": TICKET, "category": "bug", "subject": "x", "message": "typo"},
        {"first_response_at": "2026-09-02T00:00:00Z"})
    assert out["severity"] == "blocker"
    assert "severity" not in patched


# ─── reading triage by the ids on screen, not by a limit ─────────────

@pytest.mark.anyio
async def test_triage_is_read_by_ticket_id_in_bounded_chunks(monkeypatch):
    """A 'limit N' read of the triage table would eventually miss the row
    for a ticket in view — and the seeding insert would then overwrite a
    hand-set severity with the keyword guess. So the read is scoped to the
    ids on screen, chunked so the URL stays bounded too."""
    ids = [f"{i:08d}-0000-0000-0000-000000000000" for i in range(120)]
    asked = []

    async def fake_get(c, path, params):
        assert path == "support_triage"
        assert params["ticket_id"].startswith("in.(")
        inner = params["ticket_id"][4:-1].split(",")
        assert len(inner) <= sr._ID_CHUNK
        asked.extend(inner)
        return [{"ticket_id": inner[0], "severity": "blocker"}]

    monkeypatch.setattr(sr, "_sb_get", fake_get)
    out = await sr._triage_for(None, ids)
    assert asked == ids                      # every one of them, none twice
    assert len(out) == 3                     # 120 ids over chunks of 50


# ─── the brief a fixing session opens with ───────────────────────────

def test_the_brief_carries_their_own_words_and_the_ticket_id():
    brief = sr._fix_brief({
        "id": TICKET, "business_id": BIZ, "business_name": "Vertical Test Salon",
        "category": "bug", "subject": "Cancel does nothing",
        "created_at": "2026-09-01T00:00:00Z",
        "message": "I press cancel on a booking and the page just sits there.",
        "context": {"screen": "booking", "app_version": "1.4.2"},
    })
    assert "I press cancel on a booking and the page just sits there." in brief
    assert TICKET in brief
    assert "screen: booking" in brief
    # What goes back to the practitioner must not be builder language.
    assert "no builder, GitHub or Claude Code language" in brief


# ─── the doors ───────────────────────────────────────────────────────

def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(sr.router)
    return app


@pytest.mark.parametrize("method,path", [
    ("get", "/platform/support/queue"),
    ("post", "/platform/support/tickets/%s/triage" % TICKET),
    ("post", "/platform/support/tickets/%s/dispatch" % TICKET),
    ("post", "/platform/support/tickets/%s/reply" % TICKET),
])
def test_platform_surface_is_shut_without_a_jwt(method, path):
    r = TestClient(_app()).request(method, path, json={"text": "hi"})
    assert r.status_code in (401, 403), r.text


@pytest.mark.parametrize("method,path", [
    ("get", "/dev-bridge/tickets"),
    ("post", "/dev-bridge/tickets/%s/dispatch" % TICKET),
])
def test_device_surface_is_shut_without_a_device_token(method, path):
    r = TestClient(_app()).request(method, path, json={})
    assert r.status_code == 401, r.text


@pytest.mark.anyio
async def test_a_device_can_only_open_local_work(monkeypatch):
    """A device token opens a session on Kevin's own machine. It must not
    be able to file a cloud build — that spends the platform owner's API
    budget, and the owner gate on the builder bridge is the only thing
    standing between a stolen device token and that budget. Asserted by
    calling it, not by reading it: the lane must be local even if a caller
    asks for something else."""
    import dev_bridge
    seen = {}

    async def fake_device(c, authorization):
        return {"id": "dev-1", "name": "Solution Space"}

    async def fake_ticket(c, tid):
        return {"id": tid, "subject": "x", "message": "y", "status": "open"}

    async def fake_dispatch(c, ticket, **kw):
        seen.update(kw)
        return {"ok": True}

    monkeypatch.setattr(dev_bridge, "_require_device", fake_device)
    monkeypatch.setattr(sr, "_get_ticket", fake_ticket)
    monkeypatch.setattr(sr, "_dispatch", fake_dispatch)

    out = await sr.bridge_dispatch_ticket(
        TICKET, sr.BridgeDispatchBody(repo="backend"), authorization="Bearer t")
    assert out["ok"]
    assert seen["lane"] == "local"
    # There is no lane to ask for in the first place.
    assert "lane" not in sr.BridgeDispatchBody.model_fields


# ─── dispatch, end to end with the database stubbed ──────────────────

@pytest.mark.anyio
async def test_dispatch_files_a_local_task_and_moves_the_ticket(monkeypatch):
    ticket = {"id": TICKET, "business_id": BIZ, "business_name": "Test Salon",
              "category": "bug", "subject": "Cancel does nothing",
              "message": "nothing happens", "status": "open",
              "created_at": "2026-09-01T00:00:00Z", "context": {"screen": "booking"}}
    inserted, patched = [], []

    async def fake_get(c, path, params):
        if path == "support_tickets":
            return [ticket]
        return []

    async def fake_insert(c, path, body, upsert=False):
        inserted.append((path, body))
        return [{**(body if isinstance(body, dict) else body[0]), "id": TASK}]

    async def fake_patch(c, path, params, body):
        patched.append((path, body))

    monkeypatch.setattr(sr, "_sb_get", fake_get)
    monkeypatch.setattr(sr, "_sb_insert", fake_insert)
    monkeypatch.setattr(sr, "_sb_patch", fake_patch)

    out = await sr._dispatch(None, ticket, lane="local", repo="frontend",
                             project_path="", title="", extra="", by="test")
    assert out["ok"] is True

    tables = [p for p, _ in inserted]
    assert "dev_tasks" in tables and "support_triage" in tables
    task = dict(inserted[tables.index("dev_tasks")][1])
    assert task["lane"] == "local"
    assert task["status"] == "queued"
    assert task["report_key"]                      # the session can report back
    assert "nothing happens" in task["details"]

    triage = dict(inserted[tables.index("support_triage")][1])
    assert triage["fix_state"] == "queued"
    assert triage["dev_task_id"] == TASK

    # And their own view of it stops saying "open".
    assert ("support_tickets", {"status": "in_progress"}) in patched


# ─── the walk-back ───────────────────────────────────────────────────

@pytest.mark.anyio
@pytest.mark.parametrize("dev_status,expected", [
    ("working", "fixing"),
    ("done", "shipped"),
    ("failed", "triaged"),
    ("cancelled", "triaged"),
])
async def test_a_finished_task_moves_its_ticket(monkeypatch, dev_status, expected):
    triage = {TICKET: {"ticket_id": TICKET, "fix_state": "queued",
                       "dev_task_id": TASK, "severity": "high"}}
    tasks = {TASK: {"id": TASK, "status": dev_status}}

    async def fake_patch(c, path, params, body):
        triage[TICKET].update(body)

    monkeypatch.setattr(sr, "_sb_patch", fake_patch)
    moved = await sr._reconcile(None, triage, tasks)
    assert moved == 1
    assert triage[TICKET]["fix_state"] == expected
    if expected == "shipped":
        assert triage[TICKET]["shipped_at"]
        # 'shipped' is deliberately NOT 'closed': the practitioner has not
        # been told yet, and the confirm lane is what remembers that.
        assert sq.lane_of("shipped") == "confirm"


@pytest.mark.anyio
async def test_reconcile_leaves_settled_tickets_alone(monkeypatch):
    triage = {TICKET: {"ticket_id": TICKET, "fix_state": "answered",
                       "dev_task_id": TASK}}

    async def fake_patch(c, path, params, body):
        raise AssertionError("a closed ticket must not be reopened by a sweep")

    monkeypatch.setattr(sr, "_sb_patch", fake_patch)
    assert await sr._reconcile(None, triage, {TASK: {"id": TASK, "status": "done"}}) == 0


@pytest.fixture
def anyio_backend():
    return "asyncio"

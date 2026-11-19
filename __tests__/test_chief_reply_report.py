"""
test_chief_reply_report.py — "Report" on a Chief reply (2026-11-19).

Google Play's AI-generated content policy: people must be able to flag
offensive AI output without leaving the app. POST /agents/chief/reply-report
files the report as a support ticket Mission Control already reads. These
pin:

  * who: anyone who may talk to Chief in the business (the owner, a seat of
    any role, an active collaborator); a stranger gets 404 and nothing is
    written; an access check that can't run is a refusal, not a yes;
  * what: one support_tickets row, marked context.kind=chief_reply_report,
    with the reply, the message before it and the note, inside the table's
    limits (subject 200, message 5000), and user_id set explicitly (its
    default is auth.uid(), null for the service role);
  * ranking: "Offensive or harmful" is triaged high on arrival, and a
    triage write that fails never loses the report;
  * a sample church's report lands on the home church, and both write
    guards let it through;
  * a failed write is a plain 503, never a crash or a fake "sent".
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import chief_reply_report as R
import rate_limit
import sample_church
import sample_church_guard
import sb_clients
from auth_supabase import require_user

BIZ = "11111111-1111-1111-1111-111111111111"
HOME = "22222222-2222-2222-2222-222222222222"
SAMPLE = "33333333-3333-3333-3333-333333333333"
OWNER = "00000000-0000-0000-0000-0000000000a1"
SEATS = {role: f"00000000-0000-0000-0000-0000000000b{i}"
         for i, role in enumerate(("admin", "manager", "member", "viewer"))}
ACCOUNTANT = "00000000-0000-0000-0000-0000000000c1"
STRANGER = "00000000-0000-0000-0000-0000000000d1"


class FakeDB:
    """sb_get_as_service / sb_post_as_service by table name, filtered by
    the id, user and status in the path. `none_on` answers None for a
    table, which is what sb_get_as_service really does when a read fails
    (it never raises); `raise_on` raises, for a client that does."""

    def __init__(self, tables, fail_insert=(), raise_on=(), none_on=()):
        self.tables = tables
        self.inserts = []
        self.fail_insert = set(fail_insert)
        self.raise_on = set(raise_on)
        self.none_on = set(none_on)

    def get(self, path):
        table, _, query = path.partition("?")
        table = table.strip("/")
        if table in self.raise_on:
            raise RuntimeError(f"{table} unreadable")
        if table in self.none_on:
            return None
        rows = [dict(r) for r in self.tables.get(table, [])]
        for key, values in parse_qs(query).items():
            if values and values[0].startswith("eq."):
                want = values[0][3:]
                rows = [r for r in rows if str(r.get(key)) == want]
        return rows

    def post(self, path, body, prefer="return=representation", **_):
        table = path.split("?", 1)[0].strip("/")
        if table in self.fail_insert:
            return None
        self.inserts.append((table, dict(body)))
        return [{"id": f"{table}-row-{len(self.inserts)}", **body}]

    def rows(self, table):
        return [b for t, b in self.inserts if t == table]


@pytest.fixture
def api(monkeypatch):
    rate_limit._buckets.clear()
    who = {"user": OWNER}

    def install(fail_insert=(), raise_on=(), none_on=(), **tables):
        tables.setdefault("businesses", [
            {"id": BIZ, "owner_id": OWNER, "name": "Grace Church"},
            {"id": HOME, "owner_id": OWNER, "name": "Home Church"},
            {"id": SAMPLE, "owner_id": OWNER, "name": "Grace Street Fellowship"},
        ])
        tables.setdefault("business_users", [
            {"business_id": BIZ, "user_id": uid, "role": role, "status": "active"}
            for role, uid in SEATS.items()])
        tables.setdefault("business_collaborators", [
            {"id": "col-1", "business_id": BIZ, "user_id": ACCOUNTANT,
             "role": "accountant", "status": "active"}])
        db = FakeDB(tables, fail_insert=fail_insert, raise_on=raise_on, none_on=none_on)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
        monkeypatch.setattr(sample_church, "is_sample", lambda bid: str(bid) == SAMPLE)
        monkeypatch.setattr(sample_church, "home_of",
                            lambda bid: HOME if str(bid) == SAMPLE else None)
        app = FastAPI()
        app.include_router(R.router)
        app.dependency_overrides[require_user] = (
            lambda: SimpleNamespace(id=who["user"], email=None, role="authenticated"))
        client = TestClient(app)

        def post(user=OWNER, **body):
            who["user"] = user
            payload = {"business_id": BIZ, "reason": "offensive",
                       "reply": "Here is what I found.",
                       "asked": "What's on this week?",
                       "note": "This was rude.", "surface": "chief"}
            payload.update(body)
            payload = {k: v for k, v in payload.items() if v is not None}
            return client.post("/agents/chief/reply-report", json=payload)
        post.db = db
        return post
    return install


# ─── who may report ──────────────────────────────────────────────────

def test_the_owner_files_a_ticket_mission_control_reads(api):
    post = api()
    r = post()
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "message": "Thanks — we'll look at it."}
    [t] = post.db.rows("support_tickets")
    assert t["business_id"] == BIZ
    assert t["business_name"] == "Grace Church"
    assert t["user_id"] == OWNER
    assert t["category"] == "general"
    assert t["subject"] == "Chief reply reported: Offensive or harmful"
    assert "Here is what I found." in t["message"]
    assert "What's on this week?" in t["message"]
    assert "This was rude." in t["message"]
    assert t["context"]["kind"] == "chief_reply_report"
    assert t["context"]["reason"] == "offensive"
    assert t["context"]["reporter_role"] == "owner"
    # Nothing a ticket could carry that the table forbids a tenant row.
    assert "status" not in t and "admin_reply" not in t


@pytest.mark.parametrize("role", sorted(SEATS))
def test_any_seat_that_talks_to_chief_can_report(api, role):
    post = api()
    r = post(SEATS[role])
    assert r.status_code == 200, r.text
    [t] = post.db.rows("support_tickets")
    assert t["user_id"] == SEATS[role]
    assert t["context"]["reporter_role"] == role


def test_an_active_collaborator_can_report(api):
    post = api()
    r = post(ACCOUNTANT)
    assert r.status_code == 200, r.text
    assert post.db.rows("support_tickets")[0]["context"]["reporter_role"] == "collaborator"


def test_a_stranger_gets_404_and_nothing_is_written(api):
    post = api()
    r = post(STRANGER)
    assert r.status_code == 404
    assert post.db.inserts == []


def test_an_inactive_seat_is_a_stranger(api):
    post = api(business_users=[{"business_id": BIZ, "user_id": SEATS["member"],
                                "role": "member", "status": "removed"}])
    assert post(SEATS["member"]).status_code == 404
    assert post.db.inserts == []


def test_an_access_check_that_cannot_run_refuses(api):
    post = api(raise_on=("businesses",))
    r = post()
    assert r.status_code == 503
    assert post.db.inserts == []


# sb_get_as_service answers None, not an exception, when a read fails. A real
# team member must hear "try again" (503), never "business not found" (404).
@pytest.mark.parametrize("table,user", [
    ("businesses", OWNER),
    ("businesses", SEATS["member"]),
    ("business_users", SEATS["member"]),
    ("business_collaborators", ACCOUNTANT),
], ids=["owner-business-read", "member-business-read", "member-seat-read",
        "collaborator-read"])
def test_a_read_that_answers_none_is_a_503_not_a_404(api, table, user):
    post = api(none_on=(table,))
    r = post(user)
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "access check unavailable"
    assert post.db.inserts == []


def test_an_owner_is_known_before_the_seat_read(api):
    """The owner is answered from the businesses row; a seat read that
    would fail is never needed for them."""
    post = api(none_on=("business_users", "business_collaborators"))
    assert post(OWNER).status_code == 200


def test_a_stranger_after_every_read_answered_is_still_404(api):
    post = api(business_collaborators=[])
    assert post(STRANGER).status_code == 404


def test_a_malformed_business_id_names_no_business(api):
    post = api()
    assert post(business_id="abc#&user_id=eq.x").status_code == 404
    assert post.db.inserts == []


# ─── what a report holds ─────────────────────────────────────────────

def test_an_unknown_reason_is_refused(api):
    post = api()
    assert post(reason="spam").status_code == 400
    assert post.db.inserts == []


def test_an_empty_reply_is_refused(api):
    post = api()
    assert post(reply="   ").status_code == 400
    assert post.db.inserts == []


def test_wrong_or_made_up_is_a_bug_ticket(api):
    post = api()
    assert post(reason="wrong").status_code == 200
    [t] = post.db.rows("support_tickets")
    assert t["category"] == "bug"
    assert t["subject"] == "Chief reply reported: Wrong or made up"


def test_the_note_and_the_question_are_optional(api):
    post = api()
    r = post(reason="other", note=None, asked=None, surface=None)
    assert r.status_code == 200, r.text
    [t] = post.db.rows("support_tickets")
    assert "Their note" not in t["message"] and "They asked" not in t["message"]
    assert t["message"].endswith("Chief replied:\nHere is what I found.")


def test_long_text_fits_the_tables_limits(api):
    post = api()
    r = post(reply="x" * 20000, asked="y" * 5000, note="z" * 5000,
             surface="s" * 500, conversation_id="c" * 500)
    assert r.status_code == 200, r.text
    [t] = post.db.rows("support_tickets")
    assert 1 <= len(t["subject"]) <= 200
    assert 1 <= len(t["message"]) <= 5000
    assert t["message"].count("x") <= R.REPLY_MAX
    assert t["context"]["reply_chars"] == 20000
    assert len(t["context"]["surface"]) <= R.SURFACE_MAX
    assert len(t["context"]["conversation_id"]) <= R.CONVERSATION_MAX


# ─── how it ranks ────────────────────────────────────────────────────

def test_offensive_is_triaged_high_on_arrival(api):
    post = api()
    post()
    [tri] = post.db.rows("support_triage")
    [t] = post.db.rows("support_tickets")
    assert tri["severity"] == "high"
    assert tri["fix_state"] == "new"
    assert tri["triaged_by"] == "auto"
    assert tri["ticket_id"].startswith("support_tickets-row-")
    assert tri["problem_key"] is None
    assert t  # the ticket is there too


def test_two_different_reports_with_one_reason_never_share_a_key(api):
    """The subject is the same for every report with one reason, so a key
    built from it would make unrelated replies one 'repeated problem' and
    rank them up (support_router counts repeats by key). Each stands alone,
    in this route's triage row and in the queue's own seeding."""
    import support_queue as sq
    import support_router
    post = api()
    post(reply="Your Tuesday class is full.")
    post(reply="Here is the invoice for Dana.", asked="Bill Dana")
    tickets = post.db.rows("support_tickets")
    keys = [t["problem_key"] for t in post.db.rows("support_triage")]
    assert len(tickets) == 2 and tickets[0]["subject"] == tickets[1]["subject"]
    assert keys == [None, None]
    # The queue's fallback, when this route's triage write didn't land.
    seeded = [support_router._seed_triage({**t, "id": f"t{i}"}) for i, t in enumerate(tickets)]
    assert [s["problem_key"] for s in seeded] == [None, None]
    assert all(sq.stands_alone(t["context"]) for t in tickets)
    # An ordinary ticket is keyed exactly as before.
    plain = support_router._seed_triage({"id": "p", "category": "bug",
                                         "subject": "Booking cancel button broken",
                                         "message": "x", "context": {"screen": "booking"}})
    assert plain["problem_key"] == sq.problem_key("bug", "Booking cancel button broken",
                                                  "x", {"screen": "booking"})


def test_other_reasons_are_triaged_normal(api):
    post = api()
    post(reason="wrong")
    assert post.db.rows("support_triage")[0]["severity"] == "normal"


def test_a_triage_write_that_fails_never_loses_the_report(api):
    post = api(fail_insert=("support_triage",))
    r = post()
    assert r.status_code == 200, r.text
    assert len(post.db.rows("support_tickets")) == 1


# ─── failure is said plainly ─────────────────────────────────────────

def test_a_failed_write_is_a_plain_503_not_a_fake_sent(api):
    post = api(fail_insert=("support_tickets",))
    r = post()
    assert r.status_code == 503
    assert r.json()["detail"] == R.NOT_SENT


def test_a_tap_loop_is_rate_limited(api, monkeypatch):
    monkeypatch.setitem(rate_limit._LIMITS, "chief_reply_report", (2, 3600))
    post = api()
    assert post().status_code == 200
    assert post().status_code == 200
    r = post()
    assert r.status_code == 429
    assert r.headers.get("Retry-After") == "3600"
    assert len(post.db.rows("support_tickets")) == 2


# ─── a sample church ─────────────────────────────────────────────────

def test_a_sample_churchs_report_lands_on_the_home_church(api):
    post = api()
    r = post(business_id=SAMPLE)
    assert r.status_code == 200, r.text
    [t] = post.db.rows("support_tickets")
    assert t["business_id"] == HOME
    assert t["business_name"] == "Home Church"
    assert t["context"]["sample_church"] == SAMPLE


def test_the_sample_write_guard_lets_a_report_through():
    assert sample_church_guard.allowed("POST", "/agents/chief/reply-report")


# ─── wiring ──────────────────────────────────────────────────────────

def test_the_router_is_registered_before_the_public_site_catch_all():
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "kmj_intake_automation.py").read_text(encoding="utf-8")
    mine = src.index("app.include_router(chief_reply_report_router)")
    last = src.index("app.include_router(public_site_router)")
    assert mine < last


def test_the_rate_limit_bucket_exists():
    assert "chief_reply_report" in rate_limit._LIMITS

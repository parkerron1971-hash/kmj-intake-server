"""
test_care_handoff.py — a Prayer & care request handed to an office login gets
a heads-up and a due time (Kevin, 2026-11-18: "build the heads-up and due
time for logins").

Pinned here:
  * a hand-off to a login is due a day out and untold; taken back or given
    back, the timing clears; handed to yourself, nobody is told;
  * before the migration (no timing columns read) a hand-off writes no
    timing at all, so it works exactly as before;
  * the login's first step ("I'm on it", prayed, done, or a note) stamps
    assigned_acted_at; the pastor's own doesn't;
  * the sweep tells the login once, two minutes after the hand-off, outside
    quiet hours unless the request needs a pastor; never reads `submission`;
    lets its claim go when nothing went;
  * late: reminded when due, whoever handed it hears a day late, the office
    is asked three days late; each rung claimed once;
  * CARE_HEADS_UP=off reads nothing (My week's line: test_church_my_week).

People, churches and requests here are made up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import care_handoff as H
import church_history
import private_care as P
import sb_clients
from fastapi import HTTPException

BIZ = "11111111-1111-1111-1111-111111111111"
OWNER = "44444444-4444-4444-4444-444444444444"
PASTOR = "55555555-5555-5555-5555-555555555555"
CARE = "66666666-6666-6666-6666-666666666666"
LEFT = "99999999-9999-9999-9999-999999999999"
REQ = "22222222-2222-2222-2222-000000000001"
NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
TEAM = [
    {"user_id": PASTOR, "pastor": True, "name": "Lydia Chen"},
    {"user_id": CARE, "pastor": False, "name": "Jessica Reed"},
]


def _iso(dt):
    return dt.isoformat()


class Desk:
    """ministry_care_requests and notes, as the service sees them."""

    def __init__(self, timed=True, **row):
        self.row = {"id": REQ, "status": "new", "prayed_at": None, "status_changed_at": None,
                    "assigned_to": None, "contact_id": None, "prayer_team": False, "needs_pastor": False,
                    "leader_contact_id": None, "leader_prayed_at": None}
        if timed:
            self.row.update(assigned_due_at=None, assigned_told_at=None, assigned_acted_at=None,
                            assigned_late_level=0)
        self.row.update(row)
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        if path.startswith("/businesses"):
            return [{"id": BIZ, "owner_id": OWNER}]
        if path.startswith("/ministry_care_requests"):
            return [dict(self.row)]
        return []

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        if "assigned_acted_at=is.null" in path and self.row.get("assigned_acted_at"):
            return []
        self.row.update(body)
        return [dict(self.row)]

    def post(self, path, body, **kw):
        self.calls.append(("POST", path, body))
        return [dict(body, id="n1", created_at="now")]


@pytest.fixture
def desk(monkeypatch):
    def install(**kw):
        d = Desk(**kw)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
        monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
        return d
    monkeypatch.setattr(P, "_team", lambda biz: [dict(t) for t in TEAM])
    return install


def _patches(d):
    return [b for m, _, b in d.calls if m == "PATCH"]


# ─── The hand-off ─────────────────────────────────────────────────────

def test_a_hand_off_to_a_login_is_due_in_a_day_and_untold(desk):
    d = desk()
    out = P.update_request(BIZ, REQ, assigned_to=CARE, caller=P.CareCaller(OWNER, True))["request"]
    body = _patches(d)[0]
    assert body["assigned_to"] == CARE and body["assigned_told_at"] is None
    assert body["assigned_acted_at"] is None and body["assigned_late_level"] == 0
    handed = datetime.fromisoformat(body["assigned_at"])
    due = datetime.fromisoformat(body["assigned_due_at"])
    assert due - handed == timedelta(days=1)
    # The desk gets the timing back to draw it.
    assert out["assigned_due_at"] == body["assigned_due_at"] and out["assigned_told_at"] is None


def test_taken_back_or_given_back_the_timing_clears(desk):
    for caller in (P.CareCaller(OWNER, True), P.CareCaller(CARE, False)):
        d = desk(assigned_to=CARE, assigned_due_at="2026-11-19T15:00:00+00:00",
                 assigned_told_at="2026-11-18T15:02:00+00:00", assigned_late_level=1)
        P.update_request(BIZ, REQ, assigned_to=None, caller=caller)
        body = _patches(d)[0]
        assert body["assigned_to"] is None
        assert body["assigned_due_at"] is None and body["assigned_told_at"] is None
        assert body["assigned_late_level"] == 0


def test_handed_to_yourself_nobody_is_told(desk):
    """A keeper (sees every request, not the owner) taking one."""
    d = desk()
    P.update_request(BIZ, REQ, assigned_to=CARE, caller=P.CareCaller(CARE, True))
    body = _patches(d)[0]
    assert body["assigned_told_at"] == body["assigned_at"]


def test_before_the_migration_a_hand_off_writes_no_timing(desk):
    d = desk(timed=False)
    P.update_request(BIZ, REQ, assigned_to=CARE, caller=P.CareCaller(OWNER, True))
    body = _patches(d)[0]
    assert body["assigned_to"] == CARE
    assert not any(k.startswith("assigned_") and k not in ("assigned_to", "assigned_at", "assigned_by")
                   for k in body)


# ─── The first step ───────────────────────────────────────────────────

@pytest.mark.parametrize("kw", [{"status": "reviewed"}, {"status": "closed"}, {"prayed": True}])
def test_the_logins_first_step_stamps_acted(desk, kw):
    d = desk(assigned_to=CARE, assigned_due_at="2026-11-19T15:00:00+00:00", status="reviewed")
    out = P.update_request(BIZ, REQ, caller=P.CareCaller(CARE, False), **kw)["request"]
    body = _patches(d)[0]
    # "I'm on it" on a request already reviewed still counts.
    assert body["assigned_acted_at"] and out["assigned_acted_at"] == body["assigned_acted_at"]


def test_the_pastors_own_step_is_not_the_logins(desk):
    d = desk(assigned_to=CARE, assigned_due_at="2026-11-19T15:00:00+00:00")
    P.update_request(BIZ, REQ, status="reviewed", caller=P.CareCaller(OWNER, True))
    assert "assigned_acted_at" not in _patches(d)[0]


def test_opening_it_again_is_not_a_first_step(desk):
    d = desk(assigned_to=CARE, assigned_due_at="2026-11-19T15:00:00+00:00", prayed_at="2026-11-18T16:00:00Z")
    P.update_request(BIZ, REQ, prayed=False, caller=P.CareCaller(CARE, False))
    assert "assigned_acted_at" not in _patches(d)[0]


def test_a_note_from_the_login_is_a_first_step(desk):
    d = desk(assigned_to=CARE, assigned_due_at="2026-11-19T15:00:00+00:00")
    out = P.add_note(BIZ, REQ, "Called her Tuesday", CARE, P.CareCaller(CARE, False))
    acted = [(p, b) for m, p, b in d.calls if m == "PATCH"]
    assert len(acted) == 1 and "assigned_acted_at=is.null" in acted[0][0]
    assert f"assigned_to=eq.{CARE}" in acted[0][0]
    assert out["assigned_acted_at"]


def test_a_note_from_the_pastor_is_not_the_logins_step(desk):
    d = desk(assigned_to=CARE, assigned_due_at="2026-11-19T15:00:00+00:00")
    out = P.add_note(BIZ, REQ, "Checked in", OWNER, P.CareCaller(OWNER, True))
    assert not _patches(d) and "assigned_acted_at" not in out


def test_a_second_note_changes_nothing(desk):
    d = desk(assigned_to=CARE, assigned_due_at="2026-11-19T15:00:00+00:00",
             assigned_acted_at="2026-11-18T16:00:00+00:00")
    P.add_note(BIZ, REQ, "Again", CARE, P.CareCaller(CARE, False))
    assert not _patches(d)


# ─── The sweep ────────────────────────────────────────────────────────

class Ch:
    def __init__(self, seats=(PASTOR, CARE)):
        self.b = BIZ
        self.owner = OWNER
        self.business = {"id": BIZ, "name": "Grace Chapel", "owner_id": OWNER, "settings": {}}
        self.seats = {s: {"user_id": s} for s in seats}


class Sweep:
    def __init__(self, untold=(), late=(), quiet=False, delivers=True, seats=(PASTOR, CARE)):
        self.untold, self.late = [dict(r) for r in untold], [dict(r) for r in late]
        self.quiet, self.delivers, self.seats = quiet, delivers, seats
        self.reads, self.claims, self.told, self.alerts, self.history = [], [], [], [], []

    def rows(self, path):
        self.reads.append(path)
        if path.startswith("/businesses"):
            return [{"id": BIZ, "name": "Grace Chapel", "owner_id": OWNER, "settings": {}}]
        return self.untold if "assigned_told_at=is.null" in path else self.late

    def patch(self, path, body):
        self.claims.append((path, body))
        return [{"id": REQ}]

    def tell(self, ch, uid, words, ref):
        self.told.append((uid, words, ref))
        return self.delivers

    def alert(self, biz, title, body, key):
        self.alerts.append((title, body, key))
        return self.delivers


@pytest.fixture
def sweep(monkeypatch):
    def install(**kw):
        s = Sweep(**kw)
        import church_over
        import member_push
        import sample_church
        monkeypatch.setattr(H, "_rows", s.rows)
        monkeypatch.setattr(sb_clients, "sb_patch_as_service", s.patch)
        monkeypatch.setattr(H, "tell", s.tell)
        monkeypatch.setattr(H, "office_alert", s.alert)
        monkeypatch.setattr(H, "_called", lambda ch, uid: {OWNER: "Andre", PASTOR: "Lydia", CARE: "Jessica"}.get(uid, H.OFFICE))
        monkeypatch.setattr(church_over, "Church", lambda biz: Ch(s.seats))
        monkeypatch.setattr(member_push, "quiet_hour", lambda biz, now=None: s.quiet)
        monkeypatch.setattr(sample_church, "exclude", lambda col="business_id": "")
        monkeypatch.setattr(sample_church, "drop_samples", lambda rows, key="business_id": list(rows))
        monkeypatch.setattr(church_history, "note", lambda *a, **k: s.history.append(a) or True)
        return s
    monkeypatch.delenv("CARE_HEADS_UP", raising=False)
    return install


def _handed(**kw):
    r = {"id": REQ, "business_id": BIZ, "assigned_to": CARE, "assigned_by": OWNER,
         "assigned_at": _iso(NOW - timedelta(minutes=5)), "assigned_due_at": _iso(NOW + timedelta(days=1) - timedelta(minutes=5)),
         "assigned_told_at": None, "assigned_late_level": 0, "needs_pastor": False}
    r.update(kw)
    return r


def test_the_login_hears_once_and_never_the_request(sweep):
    s = sweep(untold=[_handed()])
    stats = H.sweep_tick(NOW)
    assert stats["told"] == 1
    uid, words, ref = s.told[0]
    assert uid == CARE and ref.startswith(f"care-told-{REQ}-")
    assert "Andre handed" in words["body"] and "tomorrow" in words["body"]
    # The claim lands only while it's untold and still with the same login.
    path, body = s.claims[0]
    assert "assigned_told_at=is.null" in path and f"assigned_to=eq.{CARE}" in path
    assert "assigned_acted_at=is.null" in path and body["assigned_told_at"]
    # Nothing the sweep reads carries the request.
    req_reads = [p for p in s.reads if p.startswith("/ministry_care_requests")]
    assert req_reads and all("submission" not in p for p in req_reads)
    text = " ".join(words.values())
    assert "Ada" not in text and "family" not in text
    assert s.history and s.history[0][1] == "church:care_told"


def test_the_heads_up_waits_two_minutes_for_an_undo(sweep):
    s = sweep(untold=[_handed()])
    H.sweep_tick(NOW)
    untold_read = next(p for p in s.reads if "assigned_told_at=is.null" in p)
    settled = (NOW - timedelta(seconds=H.SETTLE_SECONDS)).isoformat()
    from urllib.parse import quote
    assert f"assigned_at=lt.{quote(settled, safe='')}" in untold_read


def test_quiet_hours_hold_the_heads_up_unless_it_needs_a_pastor(sweep):
    s = sweep(untold=[_handed()], quiet=True)
    assert H.sweep_tick(NOW)["held"] == 1 and not s.told and not s.claims
    s = sweep(untold=[_handed(needs_pastor=True, assigned_to=PASTOR)], quiet=True)
    assert H.sweep_tick(NOW)["told"] == 1
    assert s.told[0][1]["title"] == "A request that needs a pastor is yours"


def test_nothing_went_so_the_claim_is_let_go(sweep):
    s = sweep(untold=[_handed()], delivers=False)
    stats = H.sweep_tick(NOW)
    assert stats["unsent"] == 1 and stats["told"] == 0
    assert len(s.claims) == 2
    release_path, release = s.claims[1]
    assert release == {"assigned_told_at": None} and "assigned_told_at=eq." in release_path


def test_a_login_that_left_the_office_tells_the_office(sweep):
    s = sweep(untold=[_handed(assigned_to=LEFT)])
    stats = H.sweep_tick(NOW)
    assert stats["gone"] == 1 and not s.told
    assert s.alerts[0][2] == f"care-gone-{REQ}"


def test_late_steps_climb_once_each(sweep):
    due = NOW - timedelta(hours=1)
    assert H.late_step(_handed(assigned_due_at=_iso(due)), NOW) == (1, "nudged")
    assert H.late_step(_handed(assigned_due_at=_iso(due - timedelta(days=1)), assigned_late_level=1), NOW) == (2, "handed_by_told")
    assert H.late_step(_handed(assigned_due_at=_iso(due - timedelta(days=3)), assigned_late_level=2), NOW) == (3, "office_asked")
    assert H.late_step(_handed(assigned_due_at=_iso(due - timedelta(days=1)), assigned_late_level=2), NOW) is None
    assert H.late_step(_handed(assigned_due_at=_iso(NOW + timedelta(hours=1))), NOW) is None


def test_when_due_the_login_is_reminded(sweep):
    told = _iso(NOW - timedelta(days=1))
    s = sweep(late=[_handed(assigned_due_at=_iso(NOW - timedelta(minutes=30)), assigned_told_at=told)])
    assert H.sweep_tick(NOW)["nudged"] == 1
    assert s.told[0][0] == CARE and "due now" in s.told[0][1]["body"]
    path, body = s.claims[0]
    assert body == {"assigned_late_level": 1} and "assigned_late_level=eq.0" in path


def test_a_day_late_whoever_handed_it_hears(sweep):
    s = sweep(late=[_handed(assigned_by=PASTOR, assigned_due_at=_iso(NOW - timedelta(days=1, minutes=5)),
                            assigned_told_at="x", assigned_late_level=1)])
    assert H.sweep_tick(NOW)["handed_by_told"] == 1
    uid, words, _ = s.told[0]
    assert uid == PASTOR and "you handed Jessica" in words["body"] and "a day" in words["body"]
    assert not s.alerts


def test_three_days_late_the_office_is_asked(sweep):
    s = sweep(late=[_handed(assigned_due_at=_iso(NOW - timedelta(days=3, minutes=5)), assigned_told_at="x",
                            assigned_late_level=2)])
    assert H.sweep_tick(NOW)["office_asked"] == 1
    assert s.told[0][0] == OWNER and s.alerts[0][0] == "Hand a care request to someone else?"
    assert "Jessica" in s.alerts[0][1]


def test_late_steps_wait_out_quiet_hours(sweep):
    s = sweep(late=[_handed(assigned_due_at=_iso(NOW - timedelta(minutes=30)), assigned_told_at="x")], quiet=True)
    assert H.sweep_tick(NOW)["held"] == 1 and not s.claims


def test_a_rung_that_couldnt_go_is_let_go(sweep):
    s = sweep(late=[_handed(assigned_due_at=_iso(NOW - timedelta(minutes=30)), assigned_told_at="x")], delivers=False)
    assert H.sweep_tick(NOW)["unsent"] == 1
    assert s.claims[1][1] == {"assigned_late_level": 0} and "assigned_late_level=eq.1" in s.claims[1][0]


def test_the_switch_off_reads_nothing(sweep, monkeypatch):
    s = sweep(untold=[_handed()])
    monkeypatch.setenv("CARE_HEADS_UP", "off")
    assert not any(H.sweep_tick(NOW).values()) and not s.reads


def test_before_the_migration_the_sweep_does_nothing(sweep, monkeypatch):
    s = sweep()
    monkeypatch.setattr(H, "_rows", lambda path: None)
    assert not any(H.sweep_tick(NOW).values()) and not s.claims


# ─── Words ────────────────────────────────────────────────

def test_times_read_in_the_churchs_own_words():
    biz = {"id": BIZ}
    assert H.at_words(_iso(NOW + timedelta(hours=1)), biz, NOW).startswith(("today", "tomorrow"))
    assert H.at_words(None, biz, NOW) == "soon"

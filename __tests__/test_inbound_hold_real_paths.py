"""Needs a look over the REAL hand-off code, not mocks (the account-2 review of
#2098: mocking on_connect_card and close_for_contact hid must-fix 1 and
should-fix 5).

- church_follow_up.on_connect_card / start run for real over the in-memory
  PostgREST, so Real, undo, Real again opens (and reopens) a real follow-up.
- Not a guest closes follow-ups through church_follow_up's own code: #2097's
  close_for_contact when it is there (it also cancels the queued texts, which
  is what broke undo), and church_follow_up.close before it lands. Both are
  run, and undo must put back exactly what was taken.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import church_follow_up as cfu
import inbound_hold as H
from __tests__.test_inbound_hold import A, GUEST, OWNER, SOFIA, contact, db, site  # noqa: F401  (fixtures)

# The real hand-off, taken before any fixture records it.
REAL_ON_CONNECT_CARD = cfu.on_connect_card
LATER = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
EARLIER = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def real_hand_off(site, monkeypatch):
    """The site fixture records on_connect_card; here the real one runs (and
    the Welcome Path stays off, so only the follow-up is in play)."""
    real = REAL_ON_CONNECT_CARD
    import new_here
    monkeypatch.setattr(new_here, "path_on", lambda biz: False)
    monkeypatch.setattr(cfu, "on_connect_card", real)
    return site


def follow_ups(db, cid):
    return [r for r in db.rows("church_follow_ups") if r.get("contact_id") == cid]


def test_real_undo_real_opens_a_real_follow_up_each_time(db, real_hand_off):
    real_hand_off.send(SOFIA)
    cid = contact(db, SOFIA["email"])["id"]
    assert follow_ups(db, cid) == []                     # held: nothing opened
    out = H.decide(A, cid, H.REAL, by_user=OWNER)
    (fu,) = follow_ups(db, cid)
    assert out["follow_ups_opened"] == 1 and fu["status"] == "open" and fu["source_event"]
    H.undo(A, out["decision_id"], by_user=OWNER)
    assert follow_ups(db, cid)[0]["status"] == "closed"
    again = H.decide(A, cid, H.REAL, by_user=OWNER)       # should-fix 5: used to open nothing
    assert again["follow_ups_opened"] == 1
    assert [f["status"] for f in follow_ups(db, cid)] == ["open"]   # the same one, reopened


def _the_2097_helpers(db):
    """#2097's close_for_contact and leave_path, as merged there (6cf9026a):
    close each open follow-up, then cancel the person's queued texts. Used
    only while #2097 isn't on this branch; the real ones win once it is."""
    def leave_path(biz, cid):
        n = 0
        for r in db.rows("chief_scheduled_actions"):
            if (r.get("business_id") == biz and r.get("status") == "queued"
                    and (r.get("action") or {}).get("contact_id") == cid):
                r.update(status="cancelled", last_error="They're marked inactive; not sent.")
                n += 1
        return n

    def close_for_contact(biz, cid, *, by_user="", by_name="", why=""):
        closed = []
        for r in db.rows("church_follow_ups"):
            if r.get("business_id") == biz and r.get("contact_id") == cid and r.get("status") in ("open", "handed_back"):
                cfu._patch(biz, r["id"], {"status": "closed", "done_at": "now"})
                closed.append(r["id"])
        leave_path(biz, cid)
        return closed
    return close_for_contact


@pytest.mark.parametrize("helper", ["2097", "close"])
@pytest.mark.parametrize("verdict", [H.NOT_A_GUEST, H.SCAM])
def test_undo_puts_back_exactly_what_was_taken(db, real_hand_off, monkeypatch, helper, verdict):
    if helper == "2097":
        if not hasattr(cfu, "close_for_contact"):
            monkeypatch.setattr(cfu, "close_for_contact", _the_2097_helpers(db), raising=False)
    else:
        monkeypatch.delattr(cfu, "close_for_contact", raising=False)
    real_hand_off.send(GUEST)                            # a guest who ran as usual
    cid = contact(db, GUEST["email"])["id"]
    (fu,) = follow_ups(db, cid)
    db.rows("chief_scheduled_actions").extend([
        {"id": "t-ahead", "business_id": A, "status": "queued", "run_at": LATER,
         "action": {"type": "new_here_text", "contact_id": cid}},
        {"id": "t-past", "business_id": A, "status": "queued", "run_at": EARLIER,
         "action": {"type": "new_here_text", "contact_id": cid}},
        {"id": "t-other", "business_id": A, "status": "cancelled", "run_at": LATER,      # not this tap's
         "action": {"type": "new_here_text", "contact_id": cid}},
    ])
    out = H.decide(A, cid, verdict, by_user=OWNER)
    assert out["follow_ups_closed"] == 1 and out["texts_cancelled"] == 2       # must-fix 1: was 0 after #2097
    texts = {r["id"]: r["status"] for r in db.rows("chief_scheduled_actions")}
    assert texts == {"t-ahead": "cancelled", "t-past": "cancelled", "t-other": "cancelled"}
    assert follow_ups(db, cid)[0]["status"] == "closed" and contact(db, GUEST["email"])["status"] == "inactive"

    H.undo(A, out["decision_id"], by_user=OWNER)
    texts = {r["id"]: r["status"] for r in db.rows("chief_scheduled_actions")}
    # The text still ahead goes again; the one whose time passed stays off (it
    # would arrive late); the one this tap never took stays as it was.
    assert texts == {"t-ahead": "queued", "t-past": "cancelled", "t-other": "cancelled"}
    assert follow_ups(db, cid)[0]["status"] == "open" and follow_ups(db, cid)[0]["id"] == fu["id"]
    assert contact(db, GUEST["email"])["status"] == "lead"


def test_a_person_that_does_not_save_puts_the_rest_back(db, real_hand_off, monkeypatch):
    monkeypatch.delattr(cfu, "close_for_contact", raising=False)
    real_hand_off.send(GUEST)
    cid = contact(db, GUEST["email"])["id"]
    db.rows("chief_scheduled_actions").append({"id": "t-1", "business_id": A, "status": "queued", "run_at": LATER,
                                               "action": {"type": "new_here_text", "contact_id": cid}})
    real_patch = db.patch

    def refuse_contacts(path, body, **kw):
        if path.startswith("/contacts?"):
            return []
        return real_patch(path, body, **kw)
    monkeypatch.setattr(H.sb_clients, "sb_patch_as_service", refuse_contacts)
    with pytest.raises(Exception):
        H.decide(A, cid, H.NOT_A_GUEST, by_user=OWNER)
    monkeypatch.setattr(H.sb_clients, "sb_patch_as_service", real_patch)
    assert follow_ups(db, cid)[0]["status"] == "open"
    assert db.rows("chief_scheduled_actions")[0]["status"] == "queued"
    assert db.rows("inbound_decisions") == []


def test_undo_is_once_and_only_the_latest(db, real_hand_off, monkeypatch):
    monkeypatch.delattr(cfu, "close_for_contact", raising=False)
    real_hand_off.send(SOFIA)
    cid = contact(db, SOFIA["email"])["id"]
    first = H.decide(A, cid, H.REAL, by_user=OWNER)
    second = H.decide(A, cid, H.NOT_A_GUEST, by_user=OWNER)
    with pytest.raises(Exception) as e:
        H.undo(A, first["decision_id"], by_user=OWNER)
    assert getattr(e.value, "status_code", None) == 409 and "later tap" in e.value.detail
    H.undo(A, second["decision_id"], by_user=OWNER)
    with pytest.raises(Exception) as e:
        H.undo(A, second["decision_id"], by_user=OWNER)
    assert e.value.status_code == 409
    # Two at once: the second finds the row already claimed.
    real_patch = db.patch
    claims = []

    def racing(path, body, **kw):
        if path.startswith("/inbound_decisions?") and "undone_at=is.null" in path:
            claims.append(path)
            if len(claims) == 1:
                return []            # the other screen claimed it a moment ago
        return real_patch(path, body, **kw)
    monkeypatch.setattr(H.sb_clients, "sb_patch_as_service", racing)
    with pytest.raises(Exception) as e:
        H.undo(A, first["decision_id"], by_user=OWNER)
    assert e.value.status_code == 409


def test_scam_never_remembers_a_shared_domain(db, real_hand_off, monkeypatch):
    monkeypatch.delattr(cfu, "close_for_contact", raising=False)
    real_hand_off.send(dict(SOFIA, email="scammer@nc.rr.com", submission_id="rr-1"))
    cid = contact(db, "scammer@nc.rr.com")["id"]
    H.decide(A, cid, H.SCAM, by_user=OWNER)
    assert "domain" not in {s["kind"] for s in db.rows("inbound_senders")}
    # Another rr.com member at the same church is not held for it.
    real_hand_off.send(dict(name="Ruth Allen", email="ruth.allen@nc.rr.com", phone="(704) 555-0199",
                            form="connect_card", message="", submission_id="rr-2",
                            fields={"visits": "This is my first time", "notes": "My granddaughter invited me"}))
    assert "inbound_hold" not in contact(db, "ruth.allen@nc.rr.com")["metadata"]


def test_a_throwaway_domain_is_remembered(db, real_hand_off, monkeypatch):
    monkeypatch.delattr(cfu, "close_for_contact", raising=False)
    real_hand_off.send(dict(SOFIA, email="x1@mailinator.com", submission_id="m-1"))
    H.decide(A, contact(db, "x1@mailinator.com")["id"], H.SCAM, by_user=OWNER)
    assert "domain" in {s["kind"] for s in db.rows("inbound_senders")}


def test_the_send_gate_reads_every_way_a_send_names_someone(db, real_hand_off):
    real_hand_off.send(SOFIA)
    for action in ({"name": "Sara Moreno"}, {"to_name": "Sara Moreno"}, {"recipient": "Sara Moreno"},
                   {"recipient": SOFIA["email"]}, {"contact_name": "Dana Rivers", "to": SOFIA["email"]}):
        assert H.flagged_recipient(A, action) == "Sara Moreno's card is waiting for a look", action
    assert H.flagged_recipient(A, {"name": "Nobody Here"}) is None


def test_real_person_waits_for_a_go_ahead_on_a_tainted_turn(db, real_hand_off, monkeypatch):
    import business_users_router as bur
    import chief_duties
    import chief_holds
    import chief_inbound
    import chief_of_staff as cos
    chief_holds.clear()
    monkeypatch.setattr(chief_duties, "_turn_user", lambda: OWNER)
    monkeypatch.setattr(bur, "role_of", lambda biz, u: "owner")
    real_hand_off.send(SOFIA)
    cid = contact(db, SOFIA["email"])["id"]
    run = lambda: asyncio.run(chief_inbound.HANDLERS["mark_real_person"](None, {"id": A}, {"contact_id": cid}))
    tok = cos._UNTRUSTED_TAINT.set(1)
    try:
        out = run()
        assert out["failed"] and out["needs_confirmation"] and "HELD" in out["result"]
        assert contact(db, SOFIA["email"])["metadata"].get("inbound_hold")          # nothing ran
        go = cos._TURN_GO_AHEAD.set(True)
        try:
            out = run()
        finally:
            cos._TURN_GO_AHEAD.reset(go)
        assert not out.get("failed") and "inbound_hold" not in contact(db, SOFIA["email"])["metadata"]
    finally:
        cos._UNTRUSTED_TAINT.reset(tok)
    # Not a guest only stops things: it never waits.
    real_hand_off.send(dict(SOFIA, email="b@x-test.org", name="Bea Cole", submission_id="s-z"))
    tok = cos._UNTRUSTED_TAINT.set(1)
    try:
        out = asyncio.run(chief_inbound.HANDLERS["mark_not_a_guest"](None, {"id": A}, {"name": "Bea Cole"}))
    finally:
        cos._UNTRUSTED_TAINT.reset(tok)
    assert not out.get("failed")

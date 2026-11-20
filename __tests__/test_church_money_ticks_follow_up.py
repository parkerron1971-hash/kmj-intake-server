"""Giving as its own tick: the follow-up before the switch goes on
(church_money_ticks, church_money_holders, the bank doors, the sends, payroll,
and the old gift thank-you events). 2026-11-20.

Pins:
  1. one spelling of an id: an unhyphenated, upper-case or braced business,
     login or seat id finds the same row in every hook, and an id that isn't a
     uuid is refused, never read as "no id" (no seat filter, no business)
  2. lowering and taking away run with the switch off; giving stays behind it
  3. tables_ready keeps a yes ten minutes at most and flips to no the moment a
     read or write says the table isn't there; with the tables gone no hook
     ever blocks a revoke or a level change; a probe that can't tell does
  4. the bank's own rows and balances take the bank tick (the Zelle senders,
     a gift added from a bank row, the trust balances, the trust report)
  5. sending the books or a statement out takes Work, never a See tick
  6. every payroll and contractor door reaches require_pay_records
  7. the old gift thank-you events: the SQL picks exactly the code's gifts

The fixture is test_church_money_ticks's (its MoneyDB and its people).
People and churches here are made up."""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys
import uuid

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_money_gate as gate  # noqa: E402
import church_money_holders as mh  # noqa: E402
import church_money_ticks as cmt  # noqa: E402
import church_sheet as cs  # noqa: E402
import sb_clients  # noqa: E402
from test_church_money_ticks import (  # noqa: E402,F401  (db and _fresh are fixtures)
    ADMIN, BIZ, MANAGER, MEMBER, OWNER, SHOP, VIEWER, _ask, _biz, _change, _fresh, _give, _held, _seat, _status, _u,
    db)

MISSING = {"status": 404, "code": "PGRST205", "message": "Could not find the table in the schema cache"}


def _spellings(u):
    bare = u.replace("-", "")
    return {
        "upper case": u.upper(),
        "no hyphens": bare,
        "braces": "{" + u + "}",
        "braces, upper case, no hyphens": "{" + bare.upper() + "}",
        "a hyphen after every four": "-".join(bare[i:i + 4] for i in range(0, 32, 4)),
    }


SPELLINGS = list(_spellings(BIZ))


def _spell(u, how):
    return _spellings(u)[how]


class Writes:
    """Every write to the two money tables, kept, then passed on."""

    def __init__(self, db, monkeypatch):
        self.paths = []
        for name in ("sb_patch_as_service", "sb_delete_as_service"):
            real = getattr(sb_clients, name)

            def keep(path, *a, _real=real, **k):
                if path.startswith(f"/{mh.HOLDERS}") or path.startswith(f"/{mh.ASKS}"):
                    self.paths.append(path)
                return _real(path, *a, **k)
            monkeypatch.setattr(sb_clients, name, keep)


def _drop_tables(db, monkeypatch, err=MISSING):
    """The rollback ran: every read and write of the two tables is refused
    the way PostgREST refuses a table that isn't there."""
    real_get, real_patch, real_delete = db.get, db.patch, db.delete

    def mine(path):
        return path.startswith(f"/{mh.HOLDERS}") or path.startswith(f"/{mh.ASKS}")

    def get(path, **kw):
        if mine(path):
            db.reads.append(path)
            db.err = err
            return None
        return real_get(path, **kw)

    def patch(path, body, **kw):
        if mine(path):
            db.err = err
            return None
        return real_patch(path, body, **kw)

    def delete(path, **kw):
        return False if mine(path) else real_delete(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)


# ─── 1. One spelling of an id ─────────────────────────────────────────

@pytest.mark.parametrize("how", SPELLINGS)
def test_every_spelling_of_the_same_id_lowers_the_same_row(db, how):
    _give(db, MANAGER, "lead", who=True, bank=True)
    assert cmt.seat_lowered_to_viewer(_spell(BIZ, how), _spell(MANAGER, how))
    held = _held(db, MANAGER)
    assert (held["level"], held["who_gave"], held["bank"]) == ("see", True, True)
    assert mh.money_holder(_spell(BIZ, how), _spell(MANAGER, how))["level"] == "see"     # the gate's read too
    _give(db, ADMIN, "see", bank=True)                            # an Admin's bank row
    assert cmt.role_lowered(_spell(BIZ, how), _spell(ADMIN, how), "admin", "manager")
    assert _held(db, ADMIN) is None                               # cleared, whatever the spelling
    _give(db, MEMBER, "work")
    assert cmt.role_lowered(_spell(BIZ, how), _spell(MEMBER, how), "member", "viewer")
    assert _held(db, MEMBER)["level"] == "see"


@pytest.mark.parametrize("how", SPELLINGS)
def test_every_spelling_of_a_seat_id_keeps_the_seat_filter(db, how):
    """Revoking a person's OLD row, its id spelled another way, must not
    take the tick on their live seat: before 2026-11-20 an unhyphenated
    seat id dropped the seat filter and deleted every tick they held."""
    import business_users_router as bur
    old = {**_seat(MANAGER, "manager", "Caleb Stone", status="revoked"), "id": str(uuid.uuid4())}
    db.t["business_users"].append(old)
    _give(db, MANAGER, "work", who=True)
    assert cmt.seat_gone(_spell(BIZ, how), _spell(MANAGER, how), _spell(old["id"], how))
    assert _held(db, MANAGER)["level"] == "work"
    out = bur.hand_back_login(_spell(BIZ, how), MANAGER, seat_id=_spell(old["id"], how))
    assert out["failed"] == 0 and _held(db, MANAGER)["level"] == "work"
    live = db._active(BIZ, MANAGER)
    live["status"] = "revoked"
    assert bur.hand_back_login(_spell(BIZ, how), MANAGER, seat_id=_spell(live["id"], how))["failed"] == 0
    assert _held(db, MANAGER) is None                             # an unhyphenated business id used to keep it


@pytest.mark.parametrize("how", SPELLINGS)
def test_a_spelled_business_id_withdraws_the_asks_of_a_login_that_left(db, how):
    aid = _ask(db, ADMIN, MEMBER, "see", False)
    seat = db._active(BIZ, MEMBER)
    seat["status"] = "revoked"
    assert cmt.seat_gone(_spell(BIZ, how), _spell(MEMBER, how), _spell(seat["id"], how))
    assert next(a for a in db.t[mh.ASKS] if a["id"] == aid)["status"] == "withdrawn"


@pytest.mark.parametrize("biz, user, seat", [
    ("nope", MANAGER, None), (BIZ, "nope", None), (f"{BIZ}#", MANAGER, None), (BIZ, f"{MANAGER}&user_id=neq.x", None),
    (None, MANAGER, None), (BIZ, None, None), ("", "", None), (BIZ, MANAGER, "not-a-seat"), (BIZ, MANAGER, ""),
    (BIZ, MANAGER, "*"), (BIZ, MANAGER, f"{uuid.uuid4()}&seat_id=neq.x"), ("urn:uuid:" + BIZ, MANAGER, None),
])
def test_an_id_that_is_not_a_uuid_is_refused_and_nothing_is_written(db, monkeypatch, biz, user, seat):
    _give(db, MANAGER, "lead", who=True, bank=True)
    writes = Writes(db, monkeypatch)
    assert cmt.seat_gone(biz, user, seat) is False
    if seat is None:
        assert cmt.seat_lowered_to_viewer(biz, user) is False
        assert cmt.role_lowered(biz, user, "admin", "viewer") is False
    assert writes.paths == []
    assert _held(db, MANAGER)["level"] == "lead"                  # never read as "every seat" or "no id"


def test_a_revoke_with_a_seat_id_that_is_not_one_is_counted_as_failed(db):
    import business_users_router as bur
    _give(db, MANAGER, "work")
    db._active(BIZ, MANAGER)["status"] = "revoked"
    assert bur.hand_back_login(BIZ, MANAGER, seat_id="nope")["failed"] == 1
    assert _held(db, MANAGER)["level"] == "work"


def test_the_callers_hand_the_hooks_ids_the_hooks_can_read():
    """revoke hands over the business id and the seat id as the request
    spelled them (the hooks normalise them); the sheet and Logins & areas
    hand over ids they already normalised with uuid.UUID."""
    bur = pathlib.Path(ROOT, "business_users_router.py").read_text(encoding="utf-8")
    assert 'hand_back_login(biz, target[0].get("user_id"), seat_id=member_id)' in bur
    assert "church_money_ticks.seat_gone(biz, user_id, seat_id)" in bur
    sheet = pathlib.Path(ROOT, "church_sheet.py").read_text(encoding="utf-8")
    assert 'target = _uuid(body.get("user_id"), "login")' in sheet and "return str(uuid.UUID(str(v or \"\")))" in sheet
    assert "cmt.role_lowered(ch.b, target, trole, level)" in sheet
    areas = pathlib.Path(ROOT, "church_areas.py").read_text(encoding="utf-8")
    assert 'uid = str(uuid.UUID(str(body.get("user_id") or "")))' in areas
    assert "church_money_ticks.seat_lowered_to_viewer(biz, uid)" in areas
    ticks = pathlib.Path(ROOT, "church_money_ticks.py").read_text(encoding="utf-8")
    hooks = ticks[ticks.index("def _hook_ids("):ticks.index("# ─── Who holds the bank")]
    assert ".lower()" not in hooks and "str(business_id)" not in hooks and "str(user_id)" not in hooks


# ─── 2. Lowering runs with the switch off ─────────────────────────────

@pytest.mark.parametrize("mode", ["off", "owner"])
def test_lowering_and_taking_away_run_whatever_the_switch_says(db, monkeypatch, mode):
    import business_users_router as bur
    import member_asks
    _give(db, MANAGER, "lead", who=True, bank=True)
    _give(db, ADMIN, "see", bank=True)
    _give(db, MEMBER, "work", who=True)
    aid = _ask(db, ADMIN, VIEWER, "see", False)
    monkeypatch.setenv("CHURCH_MONEY_TICKS", mode)
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: False)     # `owner`: another church's
    assert not cmt.open_for(BIZ)
    _change(db, OWNER, MANAGER, {"level": "viewer"})              # a Viewer's tick drops to See
    held = _held(db, MANAGER)
    assert (held["level"], held["who_gave"], held["bank"]) == ("see", True, True)
    _change(db, OWNER, ADMIN, {"level": "manager", "areas": ["office"]})       # a demoted Admin's row is cleared
    assert _held(db, ADMIN) is None
    seat = db._active(BIZ, MEMBER)
    seat["status"] = "revoked"                                    # a login taken off the team
    assert bur.hand_back_login(BIZ, MEMBER, seat_id=seat["id"])["failed"] == 0
    assert _held(db, MEMBER) is None
    db._active(BIZ, VIEWER)["status"] = "revoked"
    bur.hand_back_login(BIZ, VIEWER)
    assert next(a for a in db.t[mh.ASKS] if a["id"] == aid)["status"] == "withdrawn"
    # Giving stays behind the switch.
    with pytest.raises(HTTPException) as e:
        _change(db, OWNER, MANAGER, {"money": {"level": "see"}})
    assert e.value.status_code == 400 and e.value.detail == cmt.NOT_ON
    assert cmt.holder(BIZ, MANAGER) is None                       # and no door reads a tick


def test_the_hooks_no_longer_ask_the_switch():
    src = pathlib.Path(ROOT, "church_money_ticks.py").read_text(encoding="utf-8")
    for fn in ("seat_gone", "seat_lowered_to_viewer", "role_lowered"):
        body = src[src.index(f"def {fn}("):]
        body = body[:body.index("\ndef ", 10)]
        assert "mode()" not in body and "open_for(" not in body, fn
    assert "def _hooks_on(" not in src


# ─── 3. tables_ready is not yes for good ──────────────────────────────

@pytest.fixture
def clock(monkeypatch):
    import time
    now = [10_000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now


def _probes(db):
    return [r for r in db.reads if r == f"/{mh.HOLDERS}?select=business_id&limit=1"]


def test_a_yes_is_kept_ten_minutes_at_most(db, clock):
    db.reads.clear()
    assert cmt.tables_ready() and len(_probes(db)) == 1
    clock[0] += mh.KEEP_YES_S - 1
    assert cmt.tables_ready() and len(_probes(db)) == 1            # kept
    clock[0] += 2
    assert cmt.tables_ready() and len(_probes(db)) == 2            # asked again


@pytest.mark.parametrize("err", [MISSING, {"status": 404, "code": "", "message": ""},
                                 {"status": 400, "code": "42P01", "message": "relation does not exist"}])
def test_a_read_that_says_the_table_is_gone_flips_it_to_no_at_once(db, monkeypatch, clock, err):
    assert cmt.tables_ready()                                     # a yes, kept
    _drop_tables(db, monkeypatch, err)
    assert mh.money_holder(BIZ, MANAGER) is None                  # the gate's read sees it first
    assert mh._READY["yes"] is False and not cmt.tables_ready()
    reads = len(_probes(db))
    clock[0] += mh.KEEP_NO_S - 1
    assert not cmt.tables_ready() and len(_probes(db)) == reads   # a no is kept five minutes


def test_a_write_that_says_the_table_is_gone_flips_it_too(db, monkeypatch, clock):
    _give(db, MANAGER, "work")
    assert cmt.tables_ready()
    _drop_tables(db, monkeypatch)
    assert cmt.seat_lowered_to_viewer(BIZ, MANAGER)               # nothing to clean: never blocks
    assert not cmt.tables_ready()


def test_with_the_tables_gone_no_hook_blocks_a_revoke_or_a_level_change(db, monkeypatch, clock):
    import business_users_router as bur
    _change(db, OWNER, ADMIN, {"money": {"bank": True}})
    assert cmt.tables_ready()                                     # a yes kept from before the rollback
    _drop_tables(db, monkeypatch)
    _change(db, OWNER, MANAGER, {"level": "viewer"})              # no 503
    assert db._active(BIZ, MANAGER)["role"] == "viewer"
    _change(db, OWNER, ADMIN, {"level": "manager", "areas": ["office"]})
    assert db._active(BIZ, ADMIN)["role"] == "manager"
    db._active(BIZ, MEMBER)["status"] = "revoked"
    assert bur.hand_back_login(BIZ, MEMBER)["failed"] == 0
    for fn, args in ((cmt.seat_gone, (BIZ, VIEWER)), (cmt.seat_lowered_to_viewer, (BIZ, VIEWER)),
                     (cmt.role_lowered, (BIZ, VIEWER, "admin", "viewer"))):
        assert fn(*args) is True, fn.__name__


def test_a_probe_that_cannot_tell_stops_a_lowering_and_is_not_kept(db, monkeypatch, clock):
    import business_users_router as bur
    _give(db, MANAGER, "lead")
    real = db.get

    def down(path, **kw):
        if path.startswith(f"/{mh.HOLDERS}"):
            db.err = None                                         # a timeout: no answer at all
            return None
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", down)
    assert cmt._tables() is None and not cmt.tables_ready()
    assert _status(cs.change, _biz(db), OWNER, MANAGER, {"level": "viewer"}) == 503
    assert db._active(BIZ, MANAGER)["role"] == "manager" and _held(db, MANAGER)["level"] == "lead"
    db._active(BIZ, MANAGER)["status"] = "revoked"
    assert bur.hand_back_login(BIZ, MANAGER)["failed"] == 1
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)    # it answers again: nothing was kept
    assert bur.hand_back_login(BIZ, MANAGER)["failed"] == 0 and _held(db, MANAGER) is None


# ─── 4. The bank's own rows take the bank tick ────────────────────────

@pytest.fixture
def giving_on(monkeypatch):
    import giving_services as gs
    import giving_ways
    monkeypatch.setattr(giving_ways, "switched_on", lambda biz: True)
    monkeypatch.setattr(gs, "_count", lambda biz, cid: {"id": cid, "status": "open", "collects_online": True,
                                                        "service_date": "2026-11-15", "starts_at": "2026-11-15T15:00:00Z"})
    monkeypatch.setattr(gs, "bank_suggestions", lambda biz, count: [{"bank_ref": "tx1", "sender": "Jane Giver"}])
    return gs


def test_the_zelle_senders_take_the_bank_tick(db, giving_on, monkeypatch):
    gs = giving_on
    count = str(uuid.uuid4())
    _give(db, MANAGER, "see", who=True)                           # who gave, not the bank
    with pytest.raises(HTTPException) as e:
        gs.count_bank_suggestions(BIZ, count, _u(MANAGER))
    assert e.value.status_code == 403 and e.value.detail == gate.BANK_403
    _give(db, MANAGER, "see", who=True, bank=True)
    assert gs.count_bank_suggestions(BIZ, count, _u(MANAGER))["suggestions"]
    _give(db, MEMBER, "see", bank=True)                           # the bank without who gave: the giving gate first
    assert _status(gs.count_bank_suggestions, BIZ, count, _u(MEMBER)) == 403
    for uid in (OWNER, ADMIN):
        assert gs.count_bank_suggestions(BIZ, count, _u(uid))["suggestions"], uid
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "off")               # off: the people it always had
    for uid in (OWNER, ADMIN):
        assert gs.count_bank_suggestions(BIZ, count, _u(uid))["suggestions"], uid
    with pytest.raises(HTTPException) as e:
        gs.count_bank_suggestions(BIZ, count, _u(MANAGER))
    assert e.value.detail == gate.GIVING_403                      # refused by the giving gate, as before


def test_a_gift_added_from_a_bank_row_takes_the_bank_tick(db, giving_on, monkeypatch):
    import giving_router
    gs = giving_on
    count = str(uuid.uuid4())
    recorded = []
    monkeypatch.setattr(gs, "_saved_before", lambda biz, rid: False)
    monkeypatch.setattr(gs, "_bank_row_for", lambda biz, ref, cents: {"date": "2026-11-14"})
    monkeypatch.setattr(giving_router, "record_manual_gift",
                        lambda biz, row, user, **kw: recorded.append(row) or {"id": "g1"})
    rows = {"rows": [{"request_id": str(uuid.uuid4()), "amount_cents": 5000, "fund": "general", "method": "zelle",
                      "bank_ref": "tx1"}]}
    _give(db, MANAGER, "work", who=True)
    with pytest.raises(HTTPException) as e:
        gs.record_gifts(BIZ, count, rows, _u(MANAGER))
    assert e.value.status_code == 403 and e.value.detail == gate.BANK_403 and recorded == []
    plain = {"rows": [{"request_id": str(uuid.uuid4()), "amount_cents": 2000, "fund": "general", "method": "cash"}]}
    assert gs.record_gifts(BIZ, count, plain, _u(MANAGER))["saved"] == 1           # no bank row: not asked
    _give(db, MANAGER, "work", who=True, bank=True)
    assert gs.record_gifts(BIZ, count, rows, _u(MANAGER))["saved"] == 1
    assert recorded[-1]["received_on"] == "2026-11-14"


def test_the_trust_balances_take_the_bank_tick(db, monkeypatch):
    import billing_limits
    import gl_reports
    import gl_router
    import reports_router as rr
    monkeypatch.setattr(billing_limits, "require_feature", lambda biz, feature: None)
    monkeypatch.setattr(gl_reports, "effective_lines", lambda biz: [])
    monkeypatch.setattr(gl_reports, "gl_active", lambda biz: False)
    _give(db, MANAGER, "see", who=True)
    for door in (lambda u: gl_router.trust_status(BIZ, u), lambda u: rr.trust_reconciliation(BIZ, None, u),
                 lambda u: rr.export(BIZ, "trust_reconciliation", from_=None, to=None, user=u)):
        with pytest.raises(HTTPException) as e:
            door(_u(MANAGER))
        assert e.value.status_code == 403 and e.value.detail == gate.BANK_403
    _give(db, MANAGER, "see", bank=True)
    assert gl_router.trust_status(BIZ, _u(MANAGER)) == {"ok": True, "has_trust_accounts": False}
    assert rr.trust_reconciliation(BIZ, None, _u(MANAGER))["report"] == "trust_reconciliation"
    for uid in (OWNER, ADMIN):
        assert gl_router.trust_status(BIZ, _u(uid))["ok"], uid
    assert gl_router.trust_status(SHOP, _u(OWNER))["ok"]          # a shop isn't asked


def test_every_bank_door_found_in_the_sweep_asks_the_bank_part():
    gs = pathlib.Path(ROOT, "giving_services.py").read_text(encoding="utf-8")
    body = gs[gs.index("def count_bank_suggestions("):]
    assert "_bank_part(business_id, user, biz)" in body[:body.index("\ndef ", 10)]
    rec = gs[gs.index("def record_gifts("):]
    rec = rec[:rec.index("\n@router.", 10)]
    assert rec.index("_bank_part(business_id, user, biz)") < rec.index("_bank_row_for(")
    assert 'require_money(business_id, user, "see", "bank"' in gs
    gl = pathlib.Path(ROOT, "gl_router.py").read_text(encoding="utf-8")
    trust = gl[gl.index("def trust_status("):]
    trust = trust[:trust.index("\n@router.", 10)]
    assert trust.index('require_money(biz, user, "see", "bank"') < trust.index("/plaid_accounts?")
    rr = pathlib.Path(ROOT, "reports_router.py").read_text(encoding="utf-8")
    body = rr[rr.index('@router.get("/trust-reconciliation")'):]
    assert "_bank_part(biz, user, _owner_or_reader(biz, user))" in body[:body.index("\n@router.", 10)]
    assert 'if report == "trust_reconciliation":\n        _bank_part(biz, user, biz_row)' in rr
    # The doors that already read the bank behind the bank part, unchanged.
    for name, needle in (("bank_statements.py", "plaid_router._require_reader"),
                         ("giving_deposits.py", "plaid_router._require_reader(business_id, user)")):
        assert needle in pathlib.Path(ROOT, name).read_text(encoding="utf-8"), name


# ─── 5. Sending money records out takes Work ──────────────────────────

class Stop(Exception):
    pass


def test_sending_the_books_or_a_statement_out_takes_work(db, monkeypatch):
    import billing_limits
    import gl_reports_t2
    import reports_router as rr

    def stop(*a, **k):
        raise Stop()
    monkeypatch.setattr(billing_limits, "require_feature", stop)               # past the gates: stop there
    monkeypatch.setattr(gl_reports_t2, "customer_statement", stop)
    contact = str(uuid.uuid4())

    def send_books(uid):
        return asyncio.run(rr.accountant_send(BIZ, None, _u(uid)))

    def send_statement(uid):
        return asyncio.run(rr.customer_statement_send(BIZ, contact, _u(uid)))

    _give(db, MANAGER, "see", who=True)
    for send in (send_books, send_statement):
        with pytest.raises(HTTPException) as e:
            send(MANAGER)
        assert e.value.status_code == 403 and e.value.detail == gate.SEES_ONLY_403, send.__name__
    _give(db, MANAGER, "work", who=True)
    for send in (send_books, send_statement):
        with pytest.raises(Stop):
            send(MANAGER)
    for uid in (OWNER, ADMIN):
        for send in (send_books, send_statement):
            with pytest.raises(Stop):
                send(uid)
    with pytest.raises(Stop):
        asyncio.run(rr.accountant_send(SHOP, None, _u(OWNER)))    # a shop: as before
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "off")
    with pytest.raises(HTTPException) as e:
        send_books(MANAGER)
    assert e.value.detail == gate.GIVING_403                      # off: the church wall, as before


def test_both_sends_ask_work_before_anything_goes():
    rr = pathlib.Path(ROOT, "reports_router.py").read_text(encoding="utf-8")
    for route, sent in (('@router.post("/accountant/send")', "send_via_resend("),
                        ('@router.post("/customer-statement/send")', "send_via_resend(")):
        body = rr[rr.index(route):]
        body = body[:body.index("\n@router.", 10)]
        assert body.index('require_ministry_finance(biz, user, biz_row, need="work")') < body.index(sent), route
    mail = pathlib.Path(ROOT, "giving_statement_mail.py").read_text(encoding="utf-8")
    body = mail[mail.index('@router.post("/giving/{business_id}/statements/{year}/mail")'):]
    assert 'require_finance(_uuid(business_id), user, need="work")' in body


# ─── 6. Payroll and contractors: every door reaches the pay-records wall ─

def test_every_payroll_and_contractor_door_reaches_require_pay_records():
    for name, gates in (("payroll_router.py", ("_access(", "_owner(", "_employee(", "_run(", "_scoped_run(",
                                                "_stub_run(", "_quarter(", "_year_data(")),
                        ("contractors_router.py", ("_access(", "_owner(", "_contractor("))):
        src = pathlib.Path(ROOT, name).read_text(encoding="utf-8")
        access = src[src.index("def _access("):]
        assert "church_money_gate.require_pay_records(biz, user, row)" in access[:access.index("\ndef ", 10)], name
        routes = list(re.finditer(r'^@router\.(get|post|put|patch|delete)\("([^"]*)"', src, re.M))
        assert routes, name
        for i, m in enumerate(routes):
            body = src[m.start():routes[i + 1].start() if i + 1 < len(routes) else len(src)]
            assert any(g in body for g in gates), f"{name} {m.group(1).upper()} {m.group(2)}"
    rr = pathlib.Path(ROOT, "reports_router.py").read_text(encoding="utf-8")
    for route in ("/1099-summary", "/1099-drafts"):
        body = rr[rr.index(f'@router.get("{route}")'):]
        assert "_pay_records_wall(" in body[:body.index("\n@router.", 10)], route
    assert 'if report == "summary_1099":\n        _pay_records_wall(biz, user, biz_row)' in rr


# ─── 7. The old gift thank-you events ─────────────────────────────────

def test_the_sql_picks_exactly_the_codes_gifts_and_waits_for_kevin():
    agent = pathlib.Path(ROOT, "payment_agent.py").read_text(encoding="utf-8")
    assert 'for_gift = trigger.startswith(("giving", "donation"))' in agent
    assert '"data": {"amount": amount, "trigger_event": ev.get("event_type")}' in agent
    assert '"event_type": "giving_thankyou_created" if for_gift else "payment_thankyou_created"' in agent
    apply = pathlib.Path(ROOT, "supabase", "APPLY-2026-11-20-gift-thankyou-events.sql").read_text(encoding="utf-8")
    test = ("(starts_with(data->>'trigger_event', 'giving') or starts_with(data->>'trigger_event', 'donation'))")
    statement = apply[apply.index("\nbegin;"):apply.index("\ncommit;")]
    assert "set local lock_timeout = '5s';" in statement
    assert "update public.events" in statement and "delete" not in statement.lower()
    assert "where event_type = 'payment_thankyou_created'" in statement and test in statement
    assert "set event_type = 'giving_thankyou_created'" in statement
    head = apply[:apply.index("\nbegin;")]
    assert "-- Check before" in head and head.count(test) >= 1 and "count(*)" in head
    assert "-- Check after" in apply[apply.index("\ncommit;"):]
    back = pathlib.Path(ROOT, "supabase", "ROLLBACK-2026-11-20-gift-thankyou-events.sql").read_text(encoding="utf-8")
    assert "data->>'retyped_from' = 'payment_thankyou_created'" in back and "delete from" not in back.lower()
    ledger = pathlib.Path(ROOT, "docs", "MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(line for line in ledger.splitlines() if line.startswith("| `supabase/APPLY-2026-11-20-gift-thankyou-events.sql`"))
    assert row.rstrip().endswith("| **NOT APPLIED** (Kevin applies it by hand, before the switch goes on). |")
    ci = pathlib.Path(ROOT, ".github", "workflows", "ci.yml").read_text(encoding="utf-8")
    assert "node __tests__/gift_thankyou_events_db.mjs" in ci


# ─── The sheet's guarded rows say who may hold giving ─────────────────

class _GuardCh:
    b = "11111111-1111-4111-8111-111111111111"

    def role(self, target):
        return "member"

    def login_name(self, target):
        return "Dana Hill"


def _guard_rows(monkeypatch, on, held):
    import church_keys
    monkeypatch.setattr(church_keys, "mode", lambda: "off")
    monkeypatch.setattr(cmt, "open_for", lambda biz: on)
    monkeypatch.setattr(cmt, "holder", lambda biz, uid: held)
    return {r["key"]: r for r in cs._guarded(_GuardCh(), "22222222-2222-4222-8222-222222222222", None)}


def test_the_guarded_rows_name_the_giving_tick_while_it_is_on(monkeypatch):
    rows = _guard_rows(monkeypatch, True, {"level": "see", "who_gave": True, "bank": False})
    assert rows["who_gave"]["holds"] is True and rows["bank"]["holds"] is False
    for key in ("who_gave", "bank"):
        assert "whoever the owner gives it to under Giving on their sheet" in rows[key]["how"]


def test_the_guarded_rows_are_unchanged_while_the_tick_is_off(monkeypatch):
    rows = _guard_rows(monkeypatch, False, {"level": "lead", "who_gave": True, "bank": True})
    assert rows["who_gave"]["holds"] is False and rows["bank"]["holds"] is False
    assert rows["who_gave"]["how"].endswith("the owner, an Admin login and the church's accountant.")


def test_a_failed_tick_read_leaves_the_guarded_rows_as_the_seat_gives(monkeypatch):
    def boom(biz, uid):
        raise RuntimeError("read failed")
    rows = _guard_rows(monkeypatch, True, None)
    assert rows["who_gave"]["holds"] is False
    import church_keys  # noqa: F401
    monkeypatch.setattr(cmt, "holder", boom)
    rows = {r["key"]: r for r in cs._guarded(_GuardCh(), "22222222-2222-4222-8222-222222222222", None)}
    assert rows["bank"]["holds"] is False

"""Giving as its own tick, the server piece (church_money_ticks.py, and the
tick's standings in church_money_gate). Kevin, 2026-11-18: "yes build with
C": only the owner gives giving access, with the password; an Admin or
whoever sets up jobs and sheets asks, and nothing opens until the owner says
yes.

Pins:
  * the switch: off reads nothing and decides nothing; owner is the platform
    owner's church; before the tables exist every read is "no tick"
  * the gate with the switch on, person by part by need: any tick reads the
    books, bills, rentals and help; Work changes them; the gift records take
    "who gave"; the bank takes "bank and payouts"; reopening a count takes
    Lead; setup stays the owner's; a Viewer never works; a tick on a seat
    that is gone opens nothing; nobody who passed before is refused
  * the sheet: the owner's raise asks for the password and a lowering
    doesn't; an Admin's or a holder's raise becomes a request, asks for no
    password and opens nothing; an Admin may lower, a holder may not; a
    Viewer only Sees; one request at a time
  * the requests: who reads them, who answers (the owner, the password on a
    yes), a request that ran out, a second answer, another church's owner,
    taking one back, the hourly sweep and its one reminder
  * a login that leaves keeps nothing; a login made a Viewer keeps only See
  * Chief: a login that only Sees giving reads money and changes none
  * the Stripe doors, the refund, the thank-you event and marking alerts read

People and churches here are made up."""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_duties as cd  # noqa: E402
import church_job_defs as cj  # noqa: E402
import church_money_gate as gate  # noqa: E402
import church_money_holders as mh  # noqa: E402
import church_money_ticks as cmt  # noqa: E402
import church_over as co  # noqa: E402
import church_sheet as cs  # noqa: E402
import sb_clients  # noqa: E402
from test_church_duties import DutyDB  # noqa: E402

BIZ = "a0000000-0000-4000-8000-0000000000a0"      # Hope Chapel
OTHER = "b0000000-0000-4000-8000-0000000000b0"    # Grace Fellowship, another church
SHOP = "d0000000-0000-4000-8000-0000000000d0"     # Corner Barbers
OWNER = "10000000-0000-4000-8000-000000000001"    # Pastor Daniel Brooks
OTHER_OWNER = "10000000-0000-4000-8000-000000000002"
ADMIN = "c1000000-0000-4000-8000-000000000001"    # Alma Price, an Admin
HOLDER = "c2000000-0000-4000-8000-000000000002"   # Nora Whitfield, sets up jobs and sheets
MANAGER = "c3000000-0000-4000-8000-000000000003"  # Caleb Stone, a Manager
MEMBER = "c4000000-0000-4000-8000-000000000004"   # Gwen Abara, a Member
VIEWER = "c5000000-0000-4000-8000-000000000005"   # Ruth Okafor, a Viewer
GONE = "c6000000-0000-4000-8000-000000000006"     # Sam Ortiz, taken off the team
STRANGER = "c9000000-0000-4000-8000-000000000009"
NOW = dt.datetime.now(dt.timezone.utc)


def _z(at):
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seat(uid, role, name, status="active", lane=None, areas=None, biz=BIZ):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_OID, uid + biz + status)), "business_id": biz, "user_id": uid,
            "role": role, "invited_email": f"{name.split()[0].lower()}@hopechapel.example", "lane": lane,
            "areas": areas, "contact_id": None, "name": name, "status": status, "joined_at": "2026-01-01T00:00:00Z"}


class MoneyDB(DutyDB):
    """The duties' fake, plus the three server-only money functions as the
    migration writes them (supabase/APPLY-2026-11-18-church-money-holders.sql)."""

    def __init__(self, **tables):
        super().__init__(**tables)
        self.err = None
        self.reads = []

    def get(self, path, **kw):
        self.reads.append(path)
        return super().get(path, **kw)

    def _owner(self, biz):
        return next((b["owner_id"] for b in self.t["businesses"] if b["id"] == biz), None)

    def _active(self, biz, uid):
        return next((s for s in self.t["business_users"]
                     if s["business_id"] == biz and s["user_id"] == uid and s["status"] == "active"), None)

    def _refuse(self, code):
        self.err = {"status": 400, "code": code, "message": "church_money"}
        return None

    def post(self, path, body, prefer=None, **kw):
        self.err = None
        if path == "/rpc/church_money_grant":
            return self.grant(**{k[2:]: v for k, v in body.items()})
        if path == "/rpc/church_money_ask":
            return self.ask(**{k[2:]: v for k, v in body.items()})
        if path == "/rpc/church_money_answer":
            return self.answer(**{k[2:]: v for k, v in body.items()})
        return super().post(path, body, prefer, **kw)

    def grant(self, business, user, level, who_gave, bank, by, ask=None):
        owner = self._owner(business)
        if not owner or owner != by:
            return self._refuse("42501")
        if user == owner:
            return self._refuse("22023")
        rows = self.t.setdefault(mh.HOLDERS, [])
        if level is None:
            self.t[mh.HOLDERS] = [r for r in rows if not (r["business_id"] == business and r["user_id"] == user)]
            return {"ok": True, "holder": None}
        seat = self._active(business, user)
        if level not in mh.LEVELS or not seat or (seat["role"] == "viewer" and level != "see"):
            return self._refuse("22023")
        self.t[mh.HOLDERS] = [r for r in rows if not (r["business_id"] == business and r["user_id"] == user)]
        row = {"business_id": business, "user_id": user, "seat_id": seat["id"], "level": level,
               "who_gave": bool(who_gave), "bank": bool(bank), "granted_by": by, "granted_at": _z(NOW), "ask_id": ask}
        self.t[mh.HOLDERS].append(row)
        return {"ok": True, "holder": dict(row)}

    def ask(self, business, user, by, level, who_gave, bank):
        owner = self._owner(business)
        seat = self._active(business, user)
        if not owner or by == user or user == owner or level not in mh.LEVELS or not seat \
                or (seat["role"] == "viewer" and level != "see"):
            return self._refuse("22023")
        asks = self.t.setdefault(mh.ASKS, [])
        for a in asks:
            if a["business_id"] == business and a["user_id"] == user and a["status"] == "asked":
                if a["expires_at"] <= _z(dt.datetime.now(dt.timezone.utc)):
                    a["status"] = "expired"
                else:
                    return self._refuse("23505")
        row = {"id": str(uuid.uuid4()), "business_id": business, "user_id": user, "asked_by": by,
               "wants": {"level": level, "who_gave": bool(who_gave), "bank": bool(bank)}, "status": "asked",
               "asked_at": _z(NOW), "expires_at": _z(NOW + dt.timedelta(days=7)), "reminded_at": None,
               "answered_by": None, "answered_at": None}
        asks.append(row)
        return {"ok": True, "ask": dict(row)}

    def answer(self, ask, yes, by):
        a = next((r for r in self.t.get(mh.ASKS, []) if r["id"] == ask), None)
        if not a:
            return self._refuse("P0002")
        if self._owner(a["business_id"]) != by:
            return self._refuse("42501")
        if a["status"] != "asked" or a["asked_by"] == a["user_id"]:
            return self._refuse("22023")
        if a["expires_at"] <= _z(dt.datetime.now(dt.timezone.utc)):
            a["status"] = "expired"
            return {"ok": False, "status": "expired", "holder": None}
        out = None
        if yes:
            out = self.grant(a["business_id"], a["user_id"], a["wants"]["level"], a["wants"]["who_gave"],
                             a["wants"]["bank"], by, a["id"])
            if out is None:
                return None
        a.update(status="approved" if yes else "declined", answered_by=by, answered_at=_z(NOW))
        return {"ok": True, "status": a["status"], "holder": (out or {}).get("holder")}


@pytest.fixture
def db(monkeypatch):
    fake = MoneyDB(
        businesses=[{"id": BIZ, "name": "Hope Chapel", "type": "church", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Daniel Brooks"}},
                    {"id": OTHER, "name": "Grace Fellowship", "type": "church", "owner_id": OTHER_OWNER,
                     "settings": {}},
                    {"id": SHOP, "name": "Corner Barbers", "type": "barber", "owner_id": OWNER, "settings": {}}],
        business_users=[
            _seat(ADMIN, "admin", "Alma Price", lane="treasurer"),
            _seat(HOLDER, "manager", "Nora Whitfield", lane="office_leadership", areas=["messages_safety", "office"]),
            _seat(MANAGER, "manager", "Caleb Stone", lane="people_care", areas=["people_care"]),
            _seat(MEMBER, "member", "Gwen Abara", areas=["office"]),
            _seat(VIEWER, "viewer", "Ruth Okafor", areas=["office"]),
            _seat(GONE, "manager", "Sam Ortiz", status="revoked"),
        ],
        business_collaborators=[], contacts=[], church_role_defs=[], church_leader_roles=[],
        church_role_settings=[], church_area_places=[], church_duty_holders=[], church_duty_changes=[],
        church_jobs=[], church_sheet_changes=[], strategy_tracks=[], chief_notifications=[], events=[],
        church_keepers=[], church_area_keys=[],
        **{mh.HOLDERS: [], mh.ASKS: []},
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    monkeypatch.setattr(sb_clients, "last_error", lambda: fake.err)
    for k in ("CHURCH_DUTIES", "CHURCH_AREAS", "CHURCH_KEYS", "CHIEF_AREAS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "on")
    import member_asks
    import messaging_router
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    monkeypatch.setattr(co, "_OWNER_EMAIL", {})
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "")
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: "pastor@hopechapel.example")
    fake.told = []
    monkeypatch.setattr(cj, "tell_owner", lambda business, title, body, tag: fake.told.append((title, body, tag)))
    cs.change(_biz(fake), OWNER, HOLDER, {"duties": {"add": [cj.GRANT]}})
    return fake


@pytest.fixture(autouse=True)
def _fresh():
    import chief_areas
    import chief_office
    caches = (cd._CACHE, cd._FAILED, ca._MY_CACHE, chief_office._CACHE)
    for c in caches:
        c.clear()
    chief_areas.forget()
    cmt._READY.update(yes=False, until=0.0)
    yield
    cmt._READY.update(yes=False, until=0.0)
    for c in caches:
        c.clear()
    chief_areas.forget()


def _biz(db, biz=BIZ):
    return next(b for b in db.t["businesses"] if b["id"] == biz)


def _u(uid, email="someone@hopechapel.example"):
    return SimpleNamespace(id=uid, email=email)


def _session(uid):
    return SimpleNamespace(user=_u(uid))


def _give(db, uid, level="see", who=False, bank=False):
    assert db.grant(BIZ, uid, level, who, bank, OWNER)["ok"]


def _held(db, uid, biz=BIZ):
    return next((r for r in db.t[mh.HOLDERS] if r["user_id"] == uid and r["business_id"] == biz), None)


def _may(uid, need, part, biz=BIZ):
    try:
        gate.require_money(biz, _u(uid), need, part)
        return True
    except HTTPException:
        return False


def _status(fn, *a, **kw):
    with pytest.raises(HTTPException) as e:
        fn(*a, **kw)
    return e.value.status_code


# ─── The switch ───────────────────────────────────────────────────────

def test_switched_off_nothing_is_read_and_nothing_is_decided(db, monkeypatch):
    _give(db, MANAGER, "lead", who=True, bank=True)
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "off")
    db.reads.clear()
    assert cmt.mode() == "off" and not cmt.open_for(BIZ)
    assert cmt.holder(BIZ, MANAGER) is None and db.reads == []
    assert not gate.tick_admits(BIZ, _u(MANAGER), "work", "payouts") and db.reads == []
    for part, need in gate.RULES:
        assert not _may(MANAGER, need, part), (part, need)       # a Manager is what a Manager always was
    ch = co.Church(_biz(db))
    assert cmt.block(_biz(db), ch, cs.standing(ch, OWNER, MANAGER), MANAGER) is None
    assert cs.compose(_biz(db), OWNER, MANAGER)["money"] is None
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, MANAGER, {"money": {"level": "see"}})
    assert e.value.status_code == 400 and e.value.detail == cmt.NOT_ON
    assert _status(cmt.list_asks, BIZ, session=_session(OWNER)) == 404
    assert cmt.sweep() == {"expired": 0, "reminded": 0}
    assert cmt.seat_gone(BIZ, MANAGER) and cmt.seat_lowered_to_viewer(BIZ, MANAGER)
    assert _held(db, MANAGER)["level"] == "lead"                 # off touches nothing


def test_owner_mode_is_the_platform_owners_church_alone(db, monkeypatch):
    import member_asks
    _give(db, MANAGER, "work")
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: str(biz) == OTHER)
    assert not cmt.open_for(BIZ) and cmt.holder(BIZ, MANAGER) is None and not _may(MANAGER, "see", "books")
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: str(biz) == BIZ)
    assert cmt.open_for(BIZ) and _may(MANAGER, "see", "books")

    def boom(biz):
        raise RuntimeError("down")
    monkeypatch.setattr(member_asks, "platform_church", boom)
    assert not cmt.open_for(BIZ)                                  # couldn't tell: closed
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "sideways")
    assert cmt.mode() == "off"


def test_before_the_tables_exist_everyone_reads_no_tick(db, monkeypatch):
    real = db.get

    def missing(path, **kw):
        if path.startswith(f"/{mh.HOLDERS}") or path.startswith(f"/{mh.ASKS}"):
            return None                                           # PostgREST's error for a table that isn't there
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", missing)
    assert cmt.holder(BIZ, MANAGER) is None and not _may(MANAGER, "see", "books")
    sheet = cs.compose(_biz(db), OWNER, MANAGER)["money"]
    assert sheet["level"] is None and sheet["pending"] is None and sheet["can"] == "grant"
    assert _may(OWNER, "work", "giving") and _may(ADMIN, "work", "giving")


# ─── The gate, with the switch on ─────────────────────────────────────

SEE = {("books", "see"), ("bills", "see"), ("store", "see"), ("checks", "see"), ("help", "see"),
       ("rentals", "see"), ("my_week", "see")}
WORK = SEE | {("books", "work"), ("bills", "work"), ("store", "work"), ("checks", "work"), ("help", "work"),
              ("rentals", "work"), ("my_week", "work")}
WHO = {("giving", "see")}
WHO_WORK = {("giving", "see"), ("giving", "work")}
BANK = {("bank", "see")}
BANK_WORK = {("bank", "see"), ("bank", "work")}
LEAD = {("count_reopen", "work")}


@pytest.mark.parametrize("who, tick, opens", [
    (MANAGER, None, set()),
    (MANAGER, ("see", False, False), SEE),
    (MANAGER, ("see", True, False), SEE | WHO),
    (MANAGER, ("see", False, True), SEE | BANK),
    (MANAGER, ("work", False, False), WORK),
    (MEMBER, ("work", True, False), WORK | WHO_WORK),
    (MANAGER, ("work", False, True), WORK | BANK_WORK),
    (MANAGER, ("lead", True, True), WORK | WHO_WORK | BANK_WORK | LEAD),
    (MANAGER, ("lead", False, False), WORK | LEAD),
    (VIEWER, ("see", True, True), SEE | WHO | BANK),
])
def test_what_each_tick_opens_part_by_part(db, who, tick, opens):
    if tick:
        _give(db, who, *tick)
    got = {(part, need) for (part, need) in gate.RULES_ON if _may(who, need, part)}
    assert got == opens
    assert not _may(who, "see", "setup") and not _may(who, "work", "setup")       # the owner's alone, always


def test_a_viewer_never_works_whatever_its_row_says(db):
    seat = db._active(BIZ, VIEWER)
    db.t[mh.HOLDERS].append({"business_id": BIZ, "user_id": VIEWER, "seat_id": seat["id"], "level": "lead",
                             "who_gave": True, "bank": True, "granted_by": OWNER, "granted_at": _z(NOW),
                             "ask_id": None})
    got = {(part, need) for (part, need) in gate.RULES_ON if _may(VIEWER, need, part)}
    assert got == SEE | WHO | BANK
    assert not gate.tick_admits(BIZ, _u(VIEWER), "work", "payouts")


def test_a_tick_counts_only_on_the_seat_it_was_given_to(db):
    _give(db, MANAGER, "lead", who=True, bank=True)
    assert _may(MANAGER, "work", "giving")
    seat = db._active(BIZ, MANAGER)
    seat["status"] = "revoked"                                   # taken off the team
    assert not any(_may(MANAGER, need, part) for (part, need) in gate.RULES_ON)
    db.t["business_users"].append({**_seat(MANAGER, "manager", "Caleb Stone"), "id": str(uuid.uuid4())})
    assert not any(_may(MANAGER, need, part) for (part, need) in gate.RULES_ON)   # invited again: a new seat
    assert not any(_may(STRANGER, need, part) for (part, need) in gate.RULES_ON)


def test_nobody_who_passed_before_is_refused_and_the_tick_is_tried_last(db, monkeypatch):
    for uid in (OWNER, ADMIN):
        monkeypatch.setenv("CHURCH_MONEY_TICKS", "off")
        before = {k: _may(uid, k[1], k[0]) for k in gate.RULES}
        monkeypatch.setenv("CHURCH_MONEY_TICKS", "on")
        assert {k: _may(uid, k[1], k[0]) for k in gate.RULES} == before
        db.reads.clear()
        for part, need in gate.RULES:
            if part != "help":                                    # the amounts side of help is the tick's alone
                _may(uid, need, part)
        assert not [r for r in db.reads if r.startswith(f"/{mh.HOLDERS}")]         # never read for them
    assert _may(OWNER, "see", "books", SHOP)                     # a shop is not asked, as before
    for (part, need), rule in gate.RULES_ON.items():
        old = gate.RULES[(part, need)]
        ticks = [s for s in rule.who if s in gate.TICKS]
        assert list(rule.who[len(rule.who) - len(ticks):]) == ticks                # the tick's standings come last
        assert [s for s in rule.who if s not in gate.TICKS] == [s for s in old.who if s != gate.MONEY_AREA]
    assert not any(gate.MONEY_AREA in r.who for r in gate.RULES_ON.values())       # the legacy row is gone


def test_a_tick_at_another_church_opens_nothing_here(db):
    db.t["business_users"].append(_seat(MANAGER, "manager", "Caleb Stone", biz=OTHER))
    assert db.grant(OTHER, MANAGER, "lead", True, True, OTHER_OWNER)["ok"]
    assert _may(MANAGER, "work", "giving", OTHER)
    assert not any(_may(MANAGER, need, part) for (part, need) in gate.RULES_ON)


def test_the_stripe_doors_follow_the_bank_tick(db):
    with pytest.raises(ValueError):
        gate.tick_admits(BIZ, _u(MANAGER), "see", "books")
    assert not gate.tick_admits(BIZ, _u(MANAGER), "see", "payouts")
    _give(db, MANAGER, "see", bank=True)
    assert gate.tick_admits(BIZ, _u(MANAGER), "see", "payouts")
    assert not gate.tick_admits(BIZ, _u(MANAGER), "see", "charges")               # a charge names its giver
    assert not gate.tick_admits(BIZ, _u(MANAGER), "work", "payouts")              # See refunds nothing
    _give(db, MANAGER, "work", who=True, bank=True)
    assert all(gate.tick_admits(BIZ, _u(MANAGER), need, door) for (door, need) in gate.TICK_DOORS)
    assert not gate.tick_admits(BIZ, _u(ADMIN), "see", "payouts")                 # an Admin as such: the door's own rule
    assert not gate.tick_admits("not-a-uuid", _u(MANAGER), "see", "payouts")


def test_the_stripe_reads_and_the_refund_ask_the_right_door():
    proxy = pathlib.Path(ROOT, "stripe_data_proxy.py").read_text(encoding="utf-8")
    assert proxy.count('_require_owner_with_acct(biz, user, "payouts")') == 2
    for fn in ("list_payouts", "list_refunds"):
        body = proxy[proxy.index(f"async def {fn}("):]
        assert '_require_owner_with_acct(biz, user, "payouts")' in body[:body.index("\n@router", 10)]
    assert 'tick_admits(business_id, user, "see", door)' in proxy
    pay = pathlib.Path(ROOT, "stripe_payments_router.py").read_text(encoding="utf-8")
    assert 'tick_admits(business_id, user, "work", "payouts")' in pay
    assert '"event_type": "payment_refund_issued"' in pay
    # The password is skipped only for a login the gate has just named as the holder.
    assert 'by_holder = church_money_gate.tick_admits(body.business_id, user, "work", "payouts")' in pay
    refund = pay[pay.index("async def refund_charge("):]
    assert refund.index("if not by_holder:") < refund.index("scope=ledger_unlock.SCOPE_DANGER")         < refund.index("create_refund(")


# ─── The sheet ────────────────────────────────────────────────────────

def _change(db, by, target, body):
    asked = []
    out = cs.change(_biz(db), by, target, body, widening=lambda: asked.append(1))
    return out, bool(asked)


def test_the_owners_raise_asks_for_the_password_and_a_lowering_doesnt(db):
    out, pw = _change(db, OWNER, MANAGER, {"money": {"level": "work", "who_gave": True, "bank": False}})
    assert pw and out["changed"] and "giving: Work, with who gave (was off)" in out["summary"]
    assert _held(db, MANAGER)["level"] == "work" and _held(db, MANAGER)["who_gave"] is True
    out, pw = _change(db, OWNER, MANAGER, {"money": {"level": "work", "who_gave": True, "bank": True}})
    assert pw and _held(db, MANAGER)["bank"] is True              # one more tick is more
    out, pw = _change(db, OWNER, MANAGER, {"money": {"level": "see", "who_gave": False, "bank": False}})
    assert not pw and _held(db, MANAGER)["level"] == "see"
    out, pw = _change(db, OWNER, MANAGER, {"money": {"level": "see", "who_gave": False, "bank": False}})
    assert not pw and not out["changed"]                          # the same again is nothing
    out, pw = _change(db, OWNER, MANAGER, {"money": {"level": None}})
    assert not pw and _held(db, MANAGER) is None and "giving: off (was See)" in out["summary"]
    rec = db.t["church_sheet_changes"][-1]
    assert rec["detail"]["money"] == {"kind": "grant", "wants": None,
                                      "was": {"level": "see", "who_gave": False, "bank": False}}
    sheet = cs.compose(_biz(db), OWNER, MANAGER)["money"]
    assert sheet["can"] == "grant" and sheet["level"] is None and [x["key"] for x in sheet["levels"]] == list(mh.LEVELS)


def test_an_admins_or_a_holders_raise_is_a_request_that_opens_nothing(db):
    for by, target in ((ADMIN, MANAGER), (HOLDER, MEMBER)):
        out, pw = _change(db, by, target, {"money": {"level": "work", "who_gave": True, "bank": False}})
        assert not pw and out["money_asked"] and out["owner_told"]
        assert "asked the owner for giving: Work, with who gave" in out["summary"]
        assert _held(db, target) is None and not _may(target, "see", "books")
        ask = next(a for a in db.t[mh.ASKS] if a["user_id"] == target)
        assert ask["status"] == "asked" and ask["asked_by"] == by
        sheet = cs.compose(_biz(db), by, target)["money"]
        assert sheet["can"] == "ask" and sheet["level"] is None
        assert sheet["pending"]["wants"] == {"level": "work", "who_gave": True, "bank": False}
        assert sheet["pending"]["asked_by"] == by and sheet["pending"]["asked_by_name"]
    assert any("asks to open giving" in t[0] for t in db.told)
    # One request at a time, whoever sends the second.
    with pytest.raises(HTTPException) as e:
        _change(db, HOLDER, MANAGER, {"money": {"level": "see"}})
    assert e.value.status_code == 409 and "already a request waiting" in e.value.detail
    assert len([a for a in db.t[mh.ASKS] if a["user_id"] == MANAGER]) == 1


def test_two_requests_racing_leave_one(db, monkeypatch):
    monkeypatch.setattr(mh, "open_ask", lambda *a, **k: None)     # both read "none waiting"
    _change(db, ADMIN, MANAGER, {"money": {"level": "see"}})
    with pytest.raises(HTTPException) as e:
        _change(db, HOLDER, MANAGER, {"money": {"level": "see"}})
    assert e.value.status_code == 409 and len([a for a in db.t[mh.ASKS] if a["user_id"] == MANAGER]) == 1


def test_an_admin_may_lower_and_a_holder_may_not(db):
    _give(db, MANAGER, "lead", who=True, bank=True)
    out, pw = _change(db, ADMIN, MANAGER, {"money": {"level": "see", "who_gave": True, "bank": False}})
    assert not pw and _held(db, MANAGER) == {**_held(db, MANAGER), "level": "see", "who_gave": True, "bank": False}
    assert not out.get("money_asked")
    assert _status(cs.change, _biz(db), HOLDER, MANAGER, {"money": {"level": None}}) == 403
    out, pw = _change(db, ADMIN, MANAGER, {"money": {"level": None}})
    assert not pw and _held(db, MANAGER) is None
    # Some up and some down from an Admin is a request for the whole of it: nothing moves.
    _give(db, MEMBER, "work", who=True)
    out, pw = _change(db, ADMIN, MEMBER, {"money": {"level": "see", "who_gave": True, "bank": True}})
    assert out["money_asked"] and _held(db, MEMBER)["level"] == "work" and _held(db, MEMBER)["bank"] is False


def test_nobody_touches_their_own_and_a_viewer_only_sees(db):
    assert _status(cs.change, _biz(db), HOLDER, HOLDER, {"money": {"level": "see"}}) == 403
    assert _status(cs.change, _biz(db), ADMIN, ADMIN, {"money": {"level": "see"}}) == 403
    assert _status(cs.change, _biz(db), MANAGER, MEMBER, {"money": {"level": "see"}}) == 403    # not an editor
    with pytest.raises(HTTPException) as e:
        _change(db, OWNER, VIEWER, {"money": {"level": "work"}})
    assert e.value.status_code == 400 and e.value.detail == cmt.VIEWER_SEES
    with pytest.raises(HTTPException) as e:                        # moved down to Viewer in the same save
        _change(db, OWNER, MANAGER, {"level": "viewer", "money": {"level": "lead"}})
    assert e.value.status_code == 400 and db._active(BIZ, MANAGER)["role"] == "manager"      # nothing was written
    out, pw = _change(db, OWNER, VIEWER, {"money": {"level": "see", "who_gave": True}})
    assert pw and _held(db, VIEWER)["level"] == "see"
    levels = {x["key"]: x["allowed"] for x in cs.compose(_biz(db), OWNER, VIEWER)["money"]["levels"]}
    assert levels == {"see": True, "work": False, "lead": False}
    for bad in ({"level": "all"}, {"level": "see", "bank": "yes"}, "see", []):
        assert _status(cs.change, _biz(db), OWNER, MANAGER, {"money": bad}) == 400


def test_an_admin_has_giving_already_and_only_the_owner_adds_the_bank(db):
    sheet = cs.compose(_biz(db), OWNER, ADMIN)["money"]
    assert (sheet["level"], sheet["who_gave"], sheet["bank"], sheet["can"]) == ("lead", True, False, "grant")
    out, pw = _change(db, OWNER, ADMIN, {"money": {"level": "lead", "who_gave": True, "bank": True}})
    # ONLY what was ticked is stored: the bank. Never an implied Lead or who gave.
    assert pw and _held(db, ADMIN) == {**_held(db, ADMIN), "level": "see", "who_gave": False, "bank": True}
    assert all(gate.tick_admits(BIZ, _u(ADMIN), need, door) for (door, need) in gate.TICK_DOORS)   # by its Admin seat
    sheet = cs.compose(_biz(db), OWNER, ADMIN)["money"]
    assert (sheet["level"], sheet["who_gave"], sheet["bank"]) == ("lead", True, True)
    out, pw = _change(db, OWNER, ADMIN, {"money": {"level": "lead", "bank": False}})
    assert not pw and _held(db, ADMIN) is None                    # nothing an Admin doesn't have: no row kept
    own = cs.compose(_biz(db), OWNER, OWNER)["money"]
    assert own["can"] is None and own["why"] == cmt.OWNER_HAS_IT


def test_a_raise_that_fails_last_says_what_saved(db, monkeypatch):
    monkeypatch.setattr(db, "grant", lambda **kw: None)
    with pytest.raises(HTTPException) as e:
        _change(db, OWNER, MANAGER, {"areas": ["people_care", "office"], "money": {"level": "work"}})
    assert e.value.status_code == 503 and "Everything else on the sheet saved." in e.value.detail
    assert db._active(BIZ, MANAGER)["areas"] == ["people_care", "office"] and _held(db, MANAGER) is None
    assert db.t["church_sheet_changes"][-1]["detail"]["money"] is None             # the record says only what saved


# ─── The requests ─────────────────────────────────────────────────────

def _ask(db, by=ADMIN, target=MANAGER, level="work", who=True, bank=False):
    return db.ask(BIZ, target, by, level, who, bank)["ask"]["id"]


def _unlock(monkeypatch, ok=True):
    import ledger_unlock
    seen = []

    def gate_(request, uid, scope, business_id=None):
        seen.append((uid, scope, business_id))
        if not ok:
            raise HTTPException(403, {"code": "ledger_locked"})
    monkeypatch.setattr(ledger_unlock, "require_unlock", gate_)
    return seen


def test_who_reads_the_requests(db):
    a1, a2 = _ask(db, ADMIN, MANAGER), _ask(db, HOLDER, MEMBER, "see", False)
    got = cmt.list_asks(BIZ, session=_session(OWNER))
    assert got["can_answer"] and [a["id"] for a in got["asks"]] == [a1, a2]
    assert got["asks"][0]["name"] and got["asks"][0]["wants_words"] == "Work, with who gave"
    mine = cmt.list_asks(BIZ, session=_session(HOLDER))
    assert not mine["can_answer"] and [a["id"] for a in mine["asks"]] == [a2]
    assert cmt.list_asks(BIZ, session=_session(MANAGER))["asks"] == []            # asked about, not told here
    assert _status(cmt.list_asks, BIZ, session=_session(STRANGER)) == 403
    assert _status(cmt.list_asks, "nope", session=_session(OWNER)) == 400
    assert _status(cmt.list_asks, SHOP, session=_session(OWNER)) == 404


def test_the_owner_says_yes_with_the_password_and_it_opens_exactly_what_was_asked(db, monkeypatch):
    aid = _ask(db)
    seen = _unlock(monkeypatch)
    for uid in (ADMIN, HOLDER, MANAGER, STRANGER, OTHER_OWNER):
        assert _status(cmt.answer_ask, aid, {"yes": True}, None, session=_session(uid)) == 403
    assert seen == [] and _held(db, MANAGER) is None
    assert _status(cmt.answer_ask, aid, {"yes": "true"}, None, session=_session(OWNER)) == 400
    out = cmt.answer_ask(aid, {"yes": True}, None, session=_session(OWNER))
    import ledger_unlock
    assert seen == [(OWNER, ledger_unlock.SCOPE_ACCESS, BIZ)] and out["status"] == "approved"
    held = _held(db, MANAGER)
    assert (held["level"], held["who_gave"], held["bank"], held["ask_id"]) == ("work", True, False, aid)
    assert "said yes to giving for" in db.t["church_sheet_changes"][-1]["summary"]
    assert _status(cmt.answer_ask, aid, {"yes": False}, None, session=_session(OWNER)) == 409    # answered once


def test_without_the_password_a_yes_opens_nothing_and_a_no_needs_none(db, monkeypatch):
    aid = _ask(db)
    seen = _unlock(monkeypatch, ok=False)
    assert _status(cmt.answer_ask, aid, {"yes": True}, None, session=_session(OWNER)) == 403
    assert _held(db, MANAGER) is None and next(a for a in db.t[mh.ASKS] if a["id"] == aid)["status"] == "asked"
    out = cmt.answer_ask(aid, {"yes": False}, None, session=_session(OWNER))
    assert out["status"] == "declined" and _held(db, MANAGER) is None and len(seen) == 1


def test_a_request_that_ran_out_is_never_granted(db, monkeypatch):
    aid = _ask(db)
    next(a for a in db.t[mh.ASKS] if a["id"] == aid)["expires_at"] = _z(NOW - dt.timedelta(minutes=1))
    _unlock(monkeypatch)
    with pytest.raises(HTTPException) as e:
        cmt.answer_ask(aid, {"yes": True}, None, session=_session(OWNER))
    assert e.value.status_code == 409 and e.value.detail == cmt.EXPIRED and _held(db, MANAGER) is None
    assert cmt.list_asks(BIZ, session=_session(OWNER))["asks"] == []
    assert cs.compose(_biz(db), OWNER, MANAGER)["money"]["pending"] is None
    _change(db, ADMIN, MANAGER, {"money": {"level": "see"}})      # and a new one can be sent
    assert _status(cmt.answer_ask, str(uuid.uuid4()), {"yes": True}, None, session=_session(OWNER)) == 404
    assert _status(cmt.answer_ask, "nope", {"yes": True}, None, session=_session(OWNER)) == 400


def test_another_churchs_owner_answers_nothing_here(db, monkeypatch):
    aid = _ask(db)
    _unlock(monkeypatch)
    assert _status(cmt.answer_ask, aid, {"yes": True}, None, session=_session(OTHER_OWNER)) == 403
    assert _status(cmt.withdraw_ask, aid, session=_session(OTHER_OWNER)) == 403
    assert db.answer(aid, True, OTHER_OWNER) is None and _held(db, MANAGER) is None


def test_whoever_asked_or_the_owner_takes_a_request_back(db):
    aid = _ask(db, HOLDER, MEMBER, "see", False)
    assert _status(cmt.withdraw_ask, aid, session=_session(ADMIN)) == 403
    assert _status(cmt.withdraw_ask, aid, session=_session(MEMBER)) == 403
    assert cmt.withdraw_ask(aid, session=_session(HOLDER))["status"] == "withdrawn"
    assert _status(cmt.withdraw_ask, aid, session=_session(OWNER)) == 409
    aid = _ask(db, HOLDER, MEMBER, "see", False)
    assert cmt.withdraw_ask(aid, session=_session(OWNER))["status"] == "withdrawn"


def test_the_sweep_marks_what_ran_out_and_reminds_each_owner_once(db):
    old, due, fresh = _ask(db, ADMIN, MANAGER), _ask(db, ADMIN, MEMBER, "see", False), _ask(db, HOLDER, VIEWER, "see", False)
    row = {a["id"]: a for a in db.t[mh.ASKS]}
    row[old]["expires_at"] = _z(NOW - dt.timedelta(hours=1))
    row[due]["asked_at"] = _z(NOW - dt.timedelta(hours=49))
    db.told.clear()
    assert cmt.sweep() == {"expired": 1, "reminded": 1}
    assert row[old]["status"] == "expired" and row[due]["reminded_at"] and row[fresh]["reminded_at"] is None
    assert len(db.told) == 1 and "Still waiting" in db.told[0][0] and "Nothing is open" in db.told[0][1]
    assert cmt.sweep() == {"expired": 0, "reminded": 0} and len(db.told) == 1     # once


# ─── A login that leaves, or is lowered ───────────────────────────────

def test_a_login_taken_off_the_team_keeps_no_tick_and_no_request(db):
    import business_users_router
    _give(db, MANAGER, "work", who=True)
    aid = _ask(db, ADMIN, MEMBER, "see", False)
    for uid in (MANAGER, MEMBER):
        db._active(BIZ, uid)["status"] = "revoked"
    assert business_users_router.hand_back_login(BIZ, MANAGER)["failed"] == 0
    assert _held(db, MANAGER) is None
    business_users_router.hand_back_login(BIZ, MEMBER)
    assert next(a for a in db.t[mh.ASKS] if a["id"] == aid)["status"] == "withdrawn"
    assert cmt.seat_gone("nope", MANAGER) and cmt.seat_gone(BIZ, None)


def test_a_login_made_a_viewer_keeps_only_see_and_work_never_comes_back(db, monkeypatch):
    _give(db, MANAGER, "lead", who=True, bank=True)
    _change(db, OWNER, MANAGER, {"level": "viewer"})
    held = _held(db, MANAGER)
    assert (held["level"], held["who_gave"], held["bank"]) == ("see", True, True)
    _change(db, OWNER, MANAGER, {"level": "member"})
    assert _held(db, MANAGER)["level"] == "see" and not _may(MANAGER, "work", "books")
    # A lowering that can't be saved stops the level too.
    _give(db, MEMBER, "work")
    real = db.patch

    def failing(path, body, **kw):
        return None if path.startswith(f"/{mh.HOLDERS}") else real(path, body, **kw)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", failing)
    assert _status(cs.change, _biz(db), OWNER, MEMBER, {"level": "viewer"}) == 503
    assert db._active(BIZ, MEMBER)["role"] == "member"


# ─── Chief ────────────────────────────────────────────────────────────

def test_chief_reads_money_for_a_login_that_sees_and_changes_none(db):
    import chief_areas
    assert chief_areas.refusal("bills", {}, chief_areas.scope_for(BIZ, MANAGER, OWNER))          # no tick: refused
    _give(db, MANAGER, "see")
    chief_areas.forget()
    scope = chief_areas.scope_for(BIZ, MANAGER, OWNER)
    assert scope["money"] == {"level": "see", "can_work": False, "who_gave": False, "bank": False}
    assert "giving_money" not in scope["areas"]                   # Chief's own context stays trimmed of money
    assert chief_areas.refusal("giving_counts", {}, scope) is None                # its handler asks the gate
    assert "doesn't change it" in chief_areas.refusal("record_service_gifts", {}, scope)
    money = {v for v, n in chief_areas.VERBS.items() if n == chief_areas.MONEY}
    assert chief_areas.TICK_VERBS <= money and chief_areas.MONEY_READS - {"show_view"} <= money
    _give(db, MANAGER, "lead", who=True, bank=True)
    chief_areas.forget()
    scope = chief_areas.scope_for(BIZ, MANAGER, OWNER)
    assert "giving_money" not in scope["areas"] and chief_areas.refusal("record_service_gifts", {}, scope) is None
    # A Chief verb is never wider than its door: everything outside the short list stays the owner's and
    # the Admins', whatever the tick (approving a proposal is the owner's alone over HTTP; bills read the bank).
    for verb in sorted(money - chief_areas.TICK_VERBS):
        assert "owner's or an admin's" in chief_areas.refusal(verb, {}, scope), verb
    for verb in ("approve_bookkeeping_proposal", "review_books", "bills", "add_bill", "send_report", "show_revenue"):
        assert verb in money - chief_areas.TICK_VERBS
    counts = pathlib.Path(ROOT, "chief_giving_counts.py").read_text(encoding="utf-8")
    assert counts.count('_chief({"id": biz_id}, atype, "work")') == 2 and "gs._gate(str(biz[\"id\"]), user, need)" in counts
    for verb in ("grant_money", "ask_money", "answer_money_ask"):
        assert verb not in chief_areas.VERBS                      # Chief never gives, asks or answers


def test_chiefs_sheet_verb_says_the_giving_block(db):
    import chief_church_sheet
    src = pathlib.Path(ROOT, "chief_church_sheet.py").read_text(encoding="utf-8")
    assert 'm = s.get("money")' in src and "You never give it, ask for it or answer a request." in src
    assert chief_church_sheet is not None


# ─── The thank-you event, and marking alerts read ─────────────────────

def test_a_thank_you_for_a_gift_is_a_giving_event():
    src = pathlib.Path(ROOT, "payment_agent.py").read_text(encoding="utf-8")
    assert '"event_type": "giving_thankyou_created" if for_gift else "payment_thankyou_created"' in src
    assert 'for_gift = trigger.startswith(("giving", "donation"))' in src
    import re
    giving_class = re.compile(r"^giving")                         # the events policy's giving class
    assert giving_class.match("giving_thankyou_created") and not giving_class.match("payment_thankyou_created")


def _alert(db, kind=None, biz=BIZ):
    row = {"id": str(uuid.uuid4()), "business_id": biz, "status": "unread", "read_at": None,
           "data": {"kind": kind} if kind else {}, "data->>kind": kind}
    db.t["chief_notifications"].append(row)
    return row


def test_a_login_marks_read_only_the_alerts_it_may_see(db, monkeypatch):
    import business_access
    import business_users_router as bur

    def access(biz, user, min_role="viewer"):
        role = "owner" if db._owner(biz) == str(user.id) else (db._active(biz, str(user.id)) or {}).get("role")
        if bur._ROLE_RANK.get(role or "", 0) < bur._ROLE_RANK[min_role]:
            raise HTTPException(403, "not authorized")
    monkeypatch.setattr(business_access, "assert_access", access)
    plain, paid, gift, other = _alert(db), _alert(db, "invoice_paid"), _alert(db, "gift_received"), _alert(db, None, OTHER)

    def read(uid, ids=None):
        body = {"business_id": BIZ}
        if ids is not None:
            body["ids"] = ids
        return cmt.read_alerts(body, session=_session(uid))["read"]

    def reset():
        for r in (plain, paid, gift, other):
            r["status"] = "unread"

    assert read(MANAGER) == 1 and (plain["status"], paid["status"], gift["status"]) == ("read", "unread", "unread")
    reset()
    _give(db, MANAGER, "see")                                     # Sees giving: the paid alert, not the gift
    assert read(MANAGER) == 2 and (paid["status"], gift["status"]) == ("read", "unread")
    reset()
    _give(db, MANAGER, "see", who=True)
    assert read(MANAGER) == 3 and gift["status"] == "read" and other["status"] == "unread"
    reset()
    assert read(OWNER, [gift["id"]]) == 1 and (plain["status"], gift["status"]) == ("unread", "read")
    assert read(OWNER, []) == 0
    assert _status(cmt.read_alerts, {"business_id": BIZ}, session=_session(VIEWER)) == 403
    assert _status(cmt.read_alerts, {"business_id": BIZ, "ids": ["nope"]}, session=_session(OWNER)) == 400
    assert _status(cmt.read_alerts, {"business_id": "nope"}, session=_session(OWNER)) == 400


# ─── Wiring ───────────────────────────────────────────────────────────

def test_it_is_registered_switched_and_asks_the_money_gate_only():
    app = pathlib.Path(ROOT, "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "app.include_router(church_money_ticks_router)" in app and 'id="church_money_asks"' in app
    env = pathlib.Path(ROOT, ".env.example").read_text(encoding="utf-8")
    assert "CHURCH_MONEY_TICKS=off" in env
    src = pathlib.Path(ROOT, "church_money_ticks.py").read_text(encoding="utf-8")
    assert "sb_get_as_anon" not in src and "_as_user" not in src and "SUPABASE_ANON" not in src
    for route in ("list_asks", "answer_ask", "withdraw_ask", "read_alerts"):
        body = src[src.index(f"def {route}("):]
        assert "sb_clients.authed_request" in body[:400], route


# ─── After the independent review of 2026-11-18 ───────────────────────
# Each of these was a reproduction in the reviewer's probes.

def test_who_gave_is_not_shown_to_a_login_that_only_sees(db, monkeypatch):
    import reports_router as rr
    givers = {"by_customer": [{"customer": "Jane Giver", "amount": 500.0}], "total": 500.0}
    _give(db, MEMBER, "see")
    assert rr._owner_or_reader(BIZ, _u(MEMBER))["id"] == BIZ      # the books open
    hidden = rr._givers_hidden(BIZ, _u(MEMBER), givers)
    assert hidden["by_customer"] == [] and hidden["givers_locked"] and hidden["total"] == 500.0   # totals kept
    for wall in (rr._giving_wall, rr._names_wall):
        with pytest.raises(HTTPException) as e:
            wall(BIZ, _u(MEMBER))
        assert e.value.status_code == 403 and e.value.detail == gate.GIVERS_403
    _give(db, MEMBER, "see", who=True)
    assert rr._givers_hidden(BIZ, _u(MEMBER), givers)["by_customer"] and rr._giving_wall(BIZ, _u(MEMBER)) is None
    for uid in (OWNER, ADMIN):
        assert rr._givers_hidden(BIZ, _u(uid), givers)["by_customer"] and gate.sees_givers(BIZ, _u(uid))
    assert gate.sees_givers(SHOP, _u(STRANGER))                   # a shop is not asked
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "off")
    db.reads.clear()
    assert gate.sees_givers(BIZ, _u(MANAGER)) and db.reads == []  # off: as before, nothing read
    src = pathlib.Path(ROOT, "reports_router.py").read_text(encoding="utf-8")
    for route in ("general-ledger", "journal", "audit-trail-report"):
        body = src[src.index(f'@router.get("/{route}")'):]
        assert "_names_wall(biz, user)" in body[:body.index("\n@router.", 10)], route
    export = src[src.index('@router.get("/export")'):]
    export = export[:export.index("\n@router.", 10)]
    assert 'if report in ("general_ledger", "audit_trail"):\n        _names_wall(biz, user)' in export
    assert "_givers_hidden(biz, user, data)" in export and "_bank_wall(biz, user, biz_row)" in export
    for route in ("statement-customers", "customer-statement", "donors", "givers", "giver-history"):
        body = src[src.index(f'@router.get("/{route}")'):]
        assert "_giving_wall(biz, user)" in body[:body.index("\n@router.", 10)], route


def test_the_bank_tick_alone_does_not_open_gifts_matched_to_deposits(db, monkeypatch):
    import giving_deposits as gd
    monkeypatch.setattr(gd, "switched_on", lambda biz: True)
    _give(db, MANAGER, "see", bank=True)
    with pytest.raises(HTTPException) as e:
        gd._gate(BIZ, _u(MANAGER), write=False)
    assert e.value.status_code == 403 and e.value.detail == gate.GIVERS_403
    _give(db, MANAGER, "see", who=True, bank=True)
    assert gd._gate(BIZ, _u(MANAGER), write=False)["id"] == BIZ
    assert _status(gd._gate, BIZ, _u(MANAGER), write=True) == 403           # See doesn't match or unmatch


def test_the_banks_report_takes_the_bank_tick(db):
    import reports_router as rr
    _give(db, MANAGER, "see", who=True)
    row = rr._owner_or_reader(BIZ, _u(MANAGER))
    assert _status(rr._bank_wall, BIZ, _u(MANAGER), row) == 403
    _give(db, MANAGER, "see", bank=True)
    assert rr._bank_wall(BIZ, _u(MANAGER), row) is None
    src = pathlib.Path(ROOT, "reports_router.py").read_text(encoding="utf-8")
    body = src[src.index('@router.get("/bank-reconciliation")'):]
    assert "_bank_wall(biz, user, biz_row)" in body[:body.index("\n@router.", 10)]


def test_a_login_that_only_sees_changes_no_money(db):
    import church_help
    import giving_records
    _give(db, MEMBER, "see")
    ca._MY_CACHE.clear()
    view = church_help.view_of(BIZ, MEMBER, "member")
    me = {"biz": _biz(db), "role": "member", "uid": MEMBER, "view": view}
    assert view == "money" and church_help.pays(me) is False     # reads the amounts, pays nothing
    _give(db, MEMBER, "work")
    assert church_help.pays({**me, "money_work": gate.may_money(BIZ, _u(MEMBER), "work", "help")}) is True
    me.pop("money_work", None)
    assert church_help.pays(me) is True
    # The doors with a seat ladder behind the church wall: a Manager seat would write, a See tick must not.
    _give(db, MANAGER, "see")
    row = _biz(db)
    giving_records.require_ministry_finance(BIZ, _u(MANAGER), row)                # reading: yes
    with pytest.raises(HTTPException) as e:
        giving_records.require_ministry_finance(BIZ, _u(MANAGER), row, need="work")
    assert e.value.status_code == 403 and e.value.detail == gate.SEES_ONLY_403
    for mod in ("gl_router", "payroll_router", "contractors_router", "accounting_periods_router"):
        import importlib
        r = importlib.import_module(mod)
        assert r._access(BIZ, _u(MANAGER), "viewer")["id"] == BIZ, mod
        assert _status(r._access, BIZ, _u(MANAGER), "manager") == 403, mod
    _give(db, MANAGER, "work")
    for mod in ("gl_router", "payroll_router", "contractors_router", "accounting_periods_router"):
        assert importlib.import_module(mod)._access(BIZ, _u(MANAGER), "manager")["id"] == BIZ, mod
    giving_records.require_ministry_finance(BIZ, _u(MANAGER), row, need="work")
    for uid in (OWNER, ADMIN):                                   # as ever
        giving_records.require_ministry_finance(BIZ, _u(uid), row, need="work")
    # The bank's wall holds a tick to the bank's own Work.
    _give(db, MANAGER, "work", bank=False)
    assert _status(giving_records.require_ministry_finance, BIZ, _u(MANAGER), row, part="bank", need="work") == 403


def test_no_money_door_that_changes_something_asks_only_to_see():
    """The scan: every door with a seat ladder behind the church wall asks
    it at "work" when it is about to change something, and the two doors the
    review named ask "work" themselves."""
    for mod in ("gl_router", "payroll_router", "contractors_router", "accounting_periods_router"):
        src = pathlib.Path(ROOT, f"{mod}.py").read_text(encoding="utf-8")
        body = src[src.index("def _access("):]
        body = body[:body.index("\ndef ", 10)]
        assert 'require_ministry_finance(biz, user, row, need="see" if min_role == "viewer" else "work")' in body, mod
        assert "require_ministry_finance(biz, user, row)\n" not in src, mod
    reports = pathlib.Path(ROOT, "reports_router.py").read_text(encoding="utf-8")
    put = reports[reports.index('@router.put("/budgets")'):]
    assert 'require_ministry_finance(biz, user, row, need="work")' in put[:put.index("\n@router.", 10)]
    # Every other non-GET route in reports_router is the owner's alone or sends as the owner.
    import re
    for m in re.finditer(r'@router\.(post|put|delete|patch)\("([^"]+)"\)', reports):
        body = reports[m.start():reports.index("\n@router.", m.start() + 10)]
        assert "_owner(" in body or 'need="work"' in body or "_owner_or_accountant(" in body \
            or "require_role(" in body, m.group(2)
    help_src = pathlib.Path(ROOT, "church_help.py").read_text(encoding="utf-8")
    pays = help_src[help_src.index("def pays("):]
    assert '"work", "help"' in pays[:pays.index("\ndef ", 10)]
    gate_src = pathlib.Path(ROOT, "church_money_gate.py").read_text(encoding="utf-8")
    assert "if need == \"work\" and p.by in TICKS:" in gate_src


def test_an_admin_moved_down_keeps_nothing_from_her_admin_row(db):
    _change(db, OWNER, ADMIN, {"money": {"bank": True}})
    assert _held(db, ADMIN)["bank"] is True
    out, pw = _change(db, OWNER, ADMIN, {"level": "manager", "areas": ["office"]})
    assert not pw and _held(db, ADMIN) is None                   # cleared before the level was written
    assert not any(_may(ADMIN, need, part) for (part, need) in gate.RULES_ON)
    assert not any(gate.tick_admits(BIZ, _u(ADMIN), need, door) for (door, need) in gate.TICK_DOORS)
    # A Member who Sees, made an Admin with the bank, then moved down again: nothing rides along.
    _give(db, MEMBER, "see")
    _change(db, OWNER, MEMBER, {"level": "admin", "money": {"bank": True}})
    assert (_held(db, MEMBER)["level"], _held(db, MEMBER)["who_gave"], _held(db, MEMBER)["bank"]) == ("see", False, True)
    _change(db, OWNER, MEMBER, {"level": "member", "areas": ["office"]})
    assert _held(db, MEMBER) is None and not _may(MEMBER, "see", "books")
    # Moved down and given giving in the SAME save: judged against nothing, so it takes the password.
    _change(db, OWNER, MANAGER, {"level": "admin", "money": {"bank": True}})
    out, pw = _change(db, OWNER, MANAGER, {"level": "manager", "areas": ["office"],
                                           "money": {"level": "see", "who_gave": False, "bank": True}})
    assert pw and (_held(db, MANAGER)["level"], _held(db, MANAGER)["bank"]) == ("see", True)


def test_a_cap_that_cannot_be_saved_stops_the_level(db, monkeypatch):
    _change(db, OWNER, ADMIN, {"money": {"bank": True}})
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda path: False)
    assert _status(cs.change, _biz(db), OWNER, ADMIN, {"level": "manager", "areas": ["office"]}) == 503
    assert db._active(BIZ, ADMIN)["role"] == "admin" and _held(db, ADMIN)["bank"] is True


def test_switched_on_before_the_tables_exist_is_exactly_off(db, monkeypatch):
    import business_users_router
    real = db.get

    def missing(path, **kw):
        if path.startswith(f"/{mh.HOLDERS}") or path.startswith(f"/{mh.ASKS}"):
            return None
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", missing)
    writes = []
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda path: writes.append(path) or False)
    assert not cmt.tables_ready()
    _change(db, OWNER, MANAGER, {"level": "viewer"})              # no 503: nothing to lower
    assert db._active(BIZ, MANAGER)["role"] == "viewer"
    assert business_users_router.hand_back_login(BIZ, MEMBER)["failed"] == 0
    assert cmt.sweep() == {"expired": 0, "reminded": 0}
    assert not [w for w in writes if mh.HOLDERS in w or mh.ASKS in w]
    for mode in ("on", "owner"):
        monkeypatch.setenv("CHURCH_MONEY_TICKS", mode)
        assert not any(_may(HOLDER, need, part) for (part, need) in gate.RULES)   # a Manager, as with it off
        assert all(_may(OWNER, k[1], k[0]) == (k[0] != "help") for k in gate.RULES)


def test_two_lowerings_racing_end_at_the_lower(db):
    _give(db, MANAGER, "lead", who=True, bank=True)
    ch = co.Church(_biz(db))
    plan = cmt.plan(_biz(db), ch, cs.standing(ch, ADMIN, MANAGER), ADMIN, MANAGER,
                    {"money": {"level": "work", "who_gave": True, "bank": True}}, "manager")
    assert plan["kind"] == "lower"
    _change(db, OWNER, MANAGER, {"money": {"level": "see", "who_gave": False, "bank": False}})    # the owner, meanwhile
    cmt.apply(plan, _biz(db), ADMIN, "Alma Price", MANAGER)
    held = _held(db, MANAGER)
    assert (held["level"], held["who_gave"], held["bank"]) == ("see", False, False)             # never back up
    src = pathlib.Path(ROOT, "church_money_ticks.py").read_text(encoding="utf-8")
    lower = src[src.index("def _lower("):src.index("# ─── A login that leaves")]
    body = lower.split('"""')[2]
    assert "{k: False for k in" in body and "level=in.(" in body and ": True" not in body   # only ever down


def test_revoking_an_old_row_leaves_the_live_seats_tick(db):
    import business_users_router
    old = {**_seat(MANAGER, "manager", "Caleb Stone", status="revoked"), "id": str(uuid.uuid4())}
    db.t["business_users"].append(old)
    _give(db, MANAGER, "work", who=True)
    aid = _ask(db, MANAGER, MEMBER, "see", False) if False else None
    assert business_users_router.hand_back_login(BIZ, MANAGER, seat_id=old["id"])["failed"] == 0
    assert _held(db, MANAGER)["level"] == "work" and _may(MANAGER, "work", "books")
    live = db._active(BIZ, MANAGER)
    live["status"] = "revoked"
    business_users_router.hand_back_login(BIZ, MANAGER, seat_id=live["id"])
    assert _held(db, MANAGER) is None and aid is None
    src = pathlib.Path(ROOT, "business_users_router.py").read_text(encoding="utf-8")
    assert "hand_back_login(biz, target[0].get(\"user_id\"), seat_id=member_id)" in src


def test_a_request_does_not_outlive_whoever_sent_it(db):
    import business_users_router
    aid = _ask(db, HOLDER, MEMBER, "see", False)
    seat = db._active(BIZ, HOLDER)
    seat["status"] = "revoked"
    business_users_router.hand_back_login(BIZ, HOLDER, seat_id=seat["id"])
    assert next(a for a in db.t[mh.ASKS] if a["id"] == aid)["status"] == "withdrawn"


def test_a_key_that_is_not_sent_is_unchanged(db):
    _give(db, MANAGER, "see", who=True, bank=True)
    out, pw = _change(db, OWNER, MANAGER, {"money": {"level": "work"}})
    held = _held(db, MANAGER)
    assert pw and (held["level"], held["who_gave"], held["bank"]) == ("work", True, True)
    out, pw = _change(db, OWNER, MANAGER, {"money": {"bank": False}})
    held = _held(db, MANAGER)
    assert not pw and (held["level"], held["who_gave"], held["bank"]) == ("work", True, False)
    assert _status(cs.change, _biz(db), OWNER, MEMBER, {"money": {"who_gave": True}}) == 400    # no level, none held


def test_a_refund_is_checked_keyed_and_never_zero(monkeypatch):
    import asyncio
    import stripe_payments_router as pay
    monkeypatch.setattr(pay, "_require_owner", lambda business_id, user: {"id": BIZ, "owner_id": OWNER})
    for amount in (0, -500):
        with pytest.raises(HTTPException) as e:
            asyncio.run(pay.refund_charge("ch_1", pay.RefundBody(business_id=BIZ, amount_cents=amount), None,
                                          _u(OWNER)))
        assert e.value.status_code == 400 and "above zero" in e.value.detail
    src = pathlib.Path(ROOT, "stripe_payments_router.py").read_text(encoding="utf-8")
    refund = src[src.index("async def refund_charge("):]
    assert refund.index("amount_cents <= 0") < refund.index("require_unlock(") < refund.index("create_refund(")
    assert "idempotency_key=key" in refund and "REFUND MADE BUT NOT RECORDED" in refund
    assert '"recorded": recorded' in refund and "tell_owner(" in refund
    helper = pathlib.Path(ROOT, "stripe_checkout_helpers.py").read_text(encoding="utf-8")
    assert '"Idempotency-Key": idempotency_key' in helper


def test_the_owner_reads_the_requests_through_chief_and_chief_answers_none(db):
    import chief_areas
    import chief_church_sheet as ccs
    assert "list_money_asks" in ccs.HANDLERS and "list_money_asks" in chief_areas.VERBS
    assert ccs._money_asks(_biz(db), OWNER, {})["label"] == "No requests waiting"
    _ask(db, ADMIN, MANAGER)
    got = ccs._money_asks(_biz(db), OWNER, {})
    assert "1 request for giving access is waiting" in got["result"] and "Work, with who gave" in got["result"]
    assert "You never answer one." in got["result"]
    assert "1 request" in ccs._money_asks(_biz(db), ADMIN, {})["result"]          # her own
    assert ccs._money_asks(_biz(db), HOLDER, {})["label"] == "No requests waiting"
    assert _status(ccs._money_asks, _biz(db), STRANGER, {}) == 403
    for name in ("action_registry.py", "chief_prompt.py", "chief_tool_loop.py"):
        assert "list_money_asks" in pathlib.Path(ROOT, name).read_text(encoding="utf-8"), name


def test_whoever_asked_hears_the_answer(db, monkeypatch):
    import threading
    import push_notifications
    sent = []
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: sent.append((uid, kw["title"])))

    class Now:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(threading, "Thread", Now)
    _unlock(monkeypatch)
    cmt.answer_ask(_ask(db, HOLDER, MEMBER, "see", False), {"yes": False}, None, session=_session(OWNER))
    cmt.answer_ask(_ask(db, ADMIN, MANAGER), {"yes": True}, None, session=_session(OWNER))
    assert [u for u, _ in sent] == [HOLDER, ADMIN]
    assert "said no" in sent[0][1] and "said yes" in sent[1][1]


def test_a_reminder_that_could_not_be_sent_is_tried_again(db, monkeypatch):
    aid = _ask(db, ADMIN, MEMBER, "see", False)
    row = next(a for a in db.t[mh.ASKS] if a["id"] == aid)
    row["asked_at"] = _z(NOW - dt.timedelta(hours=50))

    def boom(*a, **k):
        raise RuntimeError("push is down")
    monkeypatch.setattr(cj, "tell_owner", boom)
    assert cmt.sweep()["reminded"] == 0 and row["reminded_at"] is None
    monkeypatch.setattr(cj, "tell_owner", lambda *a, **k: None)
    assert cmt.sweep()["reminded"] == 1 and row["reminded_at"]


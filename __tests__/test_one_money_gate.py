"""One money gate (church_money_gate.require_money / may_money).

Kevin, 2026-11-18, "One sheet per person", step three: giving becomes its own
tick. First every door that asks "may this login see or work the church's
money?" asks it in one place, and NOBODY'S ANSWER CHANGES.

Pins:
  * the rule table: every part, both needs, who each row admits
  * no behaviour change: each old gate, copied here as it stood on main
    before this change (f859d05a), answers the same as the door that
    replaced it, for every kind of person on every kind of business: the
    same yes or no, the same status code, the same words, the same value
    handed back
  * the legacy area row (a login whose guessed areas include Giving & money)
    still opens check requests and the treasurer's side of help requests,
    and nothing else
  * a source scan: a money module decides money access through the gate,
    never by reading a role, the accountant or the owner itself; every
    other role line in those modules is on a list with its reason

People and businesses here are made up."""
from __future__ import annotations

import ast
import io
import os
import pathlib
import re
import sys
import tokenize
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import church_money_gate as gate  # noqa: E402
import sb_clients  # noqa: E402

CHURCH = "b1000000-0000-4000-8000-0000000000b1"
NONPROFIT = "b2000000-0000-4000-8000-0000000000b2"     # nonprofit-like, not a church
SHOP = "b3000000-0000-4000-8000-0000000000b3"
MISSING = "b9000000-0000-4000-8000-0000000000b9"       # no such business
BUSINESSES = (CHURCH, NONPROFIT, SHOP, MISSING)

OWNER = "a1000000-0000-4000-8000-0000000000a1"
ADMIN = "a2000000-0000-4000-8000-0000000000a2"
ACCOUNTANT = "a3000000-0000-4000-8000-0000000000a3"    # an accountant collaborator, no seat
TREASURER_LANE = "a4000000-0000-4000-8000-0000000000a4"  # a Manager seat whose lane says treasurer
GUESSED = "a5000000-0000-4000-8000-0000000000a5"       # a Manager whose guessed areas include Giving & money
MANAGER = "a6000000-0000-4000-8000-0000000000a6"
MEMBER = "a7000000-0000-4000-8000-0000000000a7"
VIEWER = "a8000000-0000-4000-8000-0000000000a8"
STRANGER = "a9000000-0000-4000-8000-0000000000a9"
BOTH = "aa000000-0000-4000-8000-0000000000aa"          # a Manager seat who is also the accountant
GONE = "ab000000-0000-4000-8000-0000000000ab"          # an Admin seat that was removed
PEOPLE = {"owner": OWNER, "admin": ADMIN, "accountant": ACCOUNTANT, "treasurer_lane": TREASURER_LANE,
          "guessed": GUESSED, "manager": MANAGER, "member": MEMBER, "viewer": VIEWER, "stranger": STRANGER,
          "both": BOTH, "gone": GONE}
SEATS = {ADMIN: ("admin", None), TREASURER_LANE: ("manager", "treasurer"), GUESSED: ("manager", None),
         MANAGER: ("manager", None), MEMBER: ("member", None), VIEWER: ("viewer", None), BOTH: ("manager", None)}
TYPES = {CHURCH: "church", NONPROFIT: "nonprofit", SHOP: "barber"}


class FakeDB:
    """The three reads a money gate makes: the business row, the person's
    active seat, and whether they are the accountant."""

    def __init__(self) -> None:
        self.reads: List[str] = []

    def get(self, path: str, *a: Any, **kw: Any) -> List[Dict[str, Any]]:
        self.reads.append(path)
        table, _, query = path.lstrip("/").partition("?")
        q = {k: unquote(v) for k, v in parse_qsl(query)}
        biz = (q.get("id") or q.get("business_id") or "").replace("eq.", "")
        uid = (q.get("user_id") or "").replace("eq.", "")
        if table == "businesses":
            if biz not in TYPES:
                return []
            return [{"id": biz, "name": "Made-up", "type": TYPES[biz], "owner_id": OWNER, "settings": {},
                     "stripe_account_id": None}]
        if biz not in TYPES:
            return []
        if table == "business_users":
            if uid in SEATS:
                return [{"role": SEATS[uid][0], "lane": SEATS[uid][1], "areas": None, "user_id": uid}]
            return []
        if table == "business_collaborators":
            return [{"id": "c1"}] if uid in (ACCOUNTANT, BOTH) else []
        raise AssertionError(f"unexpected read: {path}")


def _view(business_id: str, user_id: str, role: Optional[str]) -> Optional[Dict[str, Any]]:
    """church_areas.my_areas, made up: the guessed Manager works the office
    and Giving & money; every other office login the office alone."""
    if not role or TYPES.get(str(business_id)) != "church":
        return None
    if role in ("owner", "admin"):
        return {"areas": None, "by": "all"}
    if str(user_id) == GUESSED:
        return {"areas": ["office", "giving_money"], "by": "guess"}
    return {"areas": ["office"], "by": "picked"}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    import church_areas
    import church_keys
    monkeypatch.setattr(church_areas, "mode", lambda: "on")
    monkeypatch.setattr(church_areas, "my_areas", _view)
    monkeypatch.setattr(church_keys, "wall", lambda *a, **k: None)
    monkeypatch.setattr(church_keys, "is_open", lambda *a, **k: True)
    return fake


def _user(uid: str) -> SimpleNamespace:
    return SimpleNamespace(id=uid, email="someone@example.test")


def _answer(fn, *a: Any, **kw: Any) -> Tuple[Any, ...]:
    """What a gate said: ("ok", what it handed back) or ("no", status, words)."""
    try:
        got = fn(*a, **kw)
    except HTTPException as e:
        return ("no", e.status_code, e.detail)
    if isinstance(got, dict):
        got = {k: got.get(k) for k in ("id", "type", "owner_id") if k in got}
    return ("ok", got)


def _role(biz: str, uid: str) -> Optional[str]:
    from business_users_router import role_of
    return role_of(biz, uid)


EVERYONE = [(who, biz) for who in PEOPLE for biz in BUSINESSES]


# ─── The gates as they stood on main before this change (f859d05a) ─────

def old_require_finance(business_id, user):
    from business_users_router import role_of
    from business_collaborators_router import is_active_accountant
    role = role_of(business_id, str(user.id))
    if role in ("owner", "admin") or is_active_accountant(business_id, str(user.id)):
        return role or "accountant"
    raise HTTPException(403, "Giving records require owner, admin, or accountant access.")


def old_require_ministry_finance(business_id, user, business=None):
    import vertical_family
    rows = [business] if business else sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,type&limit=1")
    if not rows:
        raise HTTPException(404, "Business not found")
    if vertical_family.is_nonprofit_like(rows[0].get("type")):
        old_require_finance(business_id, user)


def _old_business(business_id):
    from urllib.parse import quote
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(business_id), safe='')}&select=id,name,type,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _old_church_admin(business_id, user_id):
    from business_users_router import role_of
    return role_of(str(business_id), user_id) == "admin"


def old_standing(business_id, user, business=None):
    import church_follow_up
    row = business if isinstance(business, dict) and "owner_id" in business else _old_business(business_id)
    uid = str(user.id)
    if str(row.get("owner_id")) == uid:
        return "owner"
    if "type" not in row:
        row = _old_business(business_id)
    if church_follow_up.is_church(row) and _old_church_admin(business_id, uid):
        return "admin"
    return None


def old_require_money_writer(business_id, user, *, detail="not authorized"):
    import church_follow_up
    row = _old_business(business_id)
    uid = str(user.id)
    if str(row.get("owner_id")) == uid:
        return row
    if church_follow_up.is_church(row) and _old_church_admin(business_id, uid):
        return row
    raise HTTPException(403, detail)


def old_treasurer(biz_id, uid, role):
    if role in ("owner", "admin", "accountant"):
        return True
    import church_areas
    if church_areas.mode() != "on":
        return False
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    return isinstance(areas, list) and "giving_money" in areas


def old_reports_finance(biz_id, uid, role):
    if role in ("owner", "admin"):
        return True
    try:
        import business_collaborators_router as bcr
        return bool(bcr.is_active_accountant(biz_id, uid))
    except Exception:
        return False


def old_roll_may_give(biz_id, user, role):
    try:
        ok = role in ("owner", "admin")
        if not ok:
            from business_collaborators_router import is_active_accountant
            ok = bool(is_active_accountant(biz_id, str(user.id)))
        if not ok:
            return False
        import church_keys
        return church_keys.is_open(biz_id, user, "giving_money")
    except HTTPException:
        return False
    except Exception:
        return False


def old_bills_reader(biz, user):
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id,type&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    from business_collaborators_router import is_active_accountant
    if is_active_accountant(biz, str(user.id)):
        return row
    import church_follow_up
    from business_users_router import require_role
    require_role(biz, str(user.id), "admin" if church_follow_up.is_church(row) else "viewer")
    return row


def old_owner_door(business_id, user, detail="not authorized"):
    """plaid_router, giving_router, stripe_connect_router and bills_router
    each wrote these lines for themselves."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, detail)
    return rows[0]


def old_reopen(business_id, user):
    if old_require_finance(business_id, user) not in ("owner", "admin"):
        raise HTTPException(403, "Only the owner or an admin can reopen a closed count.")


def old_help_view(biz_id, uid, role):
    if role in ("owner", "admin"):
        return "care"
    import church_areas
    if church_areas.mode() != "on":
        return "care"
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    if areas is None or "people_care" in areas:
        return "care"
    if "giving_money" in areas:
        return "money"
    return None


# ─── The table ────────────────────────────────────────────────────────

def test_every_part_has_its_rows_and_each_admits_exactly_who_it_did():
    assert gate.NEEDS == ("see", "work")
    for part in gate.PARTS:
        for need in gate.NEEDS:
            if (part, need) == ("count_reopen", "see"):
                assert (part, need) not in gate.RULES          # reopening is a change; there is nothing to see
                continue
            assert (part, need) in gate.RULES, (part, need)
    assert {p for p, _ in gate.RULES} == set(gate.PARTS)
    who = {k: (r.who, r.split, r.elsewhere) for k, r in gate.RULES.items()}
    finance = (("owner", "admin", "accountant"), None, None)
    wall = (("owner", "admin", "accountant"), "nonprofit", gate.PASS)
    writer = (("owner", "admin"), "church", ("owner",))
    top = (("owner", "admin"), None, None)
    treasurer = (("owner", "admin", "accountant", "money_area"), None, None)
    assert who == {
        ("giving", "see"): finance, ("giving", "work"): finance,
        ("books", "see"): wall, ("books", "work"): writer,
        ("bank", "see"): wall, ("bank", "work"): writer,
        ("bills", "see"): (("owner", "accountant", "admin"), "church", ("owner", "accountant", "seat")),
        ("bills", "work"): writer,
        ("store", "see"): writer, ("store", "work"): writer,
        ("checks", "see"): treasurer, ("checks", "work"): treasurer,
        ("help", "see"): (("money_area",), None, None), ("help", "work"): (("money_area",), None, None),
        ("rentals", "see"): top, ("rentals", "work"): top,
        ("my_week", "see"): top, ("my_week", "work"): top,
        ("count_reopen", "work"): top,
        ("setup", "see"): (("owner",), None, None), ("setup", "work"): (("owner",), None, None),
    }
    # The legacy area row opens the treasurer's desk and nothing else.
    assert {p for (p, _), r in gate.RULES.items() if gate.MONEY_AREA in r.who + (r.elsewhere or ())} == {"checks", "help"}
    assert all(r.status == 403 for r in gate.RULES.values())


def test_a_part_or_need_nobody_wrote_a_rule_for_is_an_error_not_a_yes(db):
    for need, part in (("see", "payroll"), ("lead", "giving"), ("see", "count_reopen")):
        with pytest.raises(ValueError):
            gate.require_money(CHURCH, _user(OWNER), need, part)
        with pytest.raises(ValueError):
            gate.may_money(CHURCH, _user(OWNER), need, part)


# ─── No behaviour change ──────────────────────────────────────────────

@pytest.mark.parametrize("who, biz", EVERYONE)
def test_giving_answers_as_require_finance_did(db, who, biz):
    import giving_records
    u = _user(PEOPLE[who])
    old = _answer(old_require_finance, biz, u)
    assert _answer(giving_records.require_finance, biz, u) == old
    for need in gate.NEEDS:
        new = _answer(lambda: gate.require_money(biz, u, need, "giving").role or "accountant")
        assert new == old, (who, biz, need)
        assert gate.may_money(biz, u, need, "giving") is (old[0] == "ok")


@pytest.mark.parametrize("who, biz", EVERYONE)
def test_the_books_and_the_bank_read_as_require_ministry_finance_did(db, who, biz):
    import giving_records
    u = _user(PEOPLE[who])
    row = {"id": biz, "type": TYPES[biz], "owner_id": OWNER, "name": "Made-up"} if biz in TYPES else None
    for business in (None, row):
        old = _answer(old_require_ministry_finance, biz, u, business)
        assert _answer(giving_records.require_ministry_finance, biz, u, business) == old, (who, biz)
        assert _answer(giving_records.require_ministry_finance, biz, u, business, "bank") == old, (who, biz)
        for part in ("books", "bank"):
            new = _answer(lambda: gate.require_money(biz, u, "see", part, business=business) and None)
            assert new == old, (who, biz, part)


@pytest.mark.parametrize("who, biz", EVERYONE)
def test_changing_the_books_the_bank_the_bills_and_the_store_answers_as_require_money_writer_did(db, who, biz):
    u = _user(PEOPLE[who])
    old = _answer(old_require_money_writer, biz, u)
    assert _answer(gate.require_money_writer, biz, u) == old
    for part in ("books", "bank", "bills", "store"):
        assert _answer(gate.require_money_writer, biz, u, part=part) == old, (who, biz, part)
        assert _answer(lambda: gate.require_money(biz, u, "work", part).business) == old
    words = "not authorized for this business"
    assert (_answer(gate.require_money_writer, biz, u, part="store", detail=words)
            == _answer(old_require_money_writer, biz, u, detail=words))
    # standing() and can_write(), with and without the caller's own row.
    full = {"id": biz, "type": TYPES.get(biz), "owner_id": OWNER}
    for business in (None, full, {"id": biz, "owner_id": OWNER}, {"id": biz}):
        if biz not in TYPES and business is full:
            continue
        assert _answer(gate.standing, biz, u, business) == _answer(old_standing, biz, u, business), (who, biz, business)
    assert gate.can_write(biz, u) is (old[0] == "ok")


def test_the_money_writer_reads_the_business_once_and_the_seat_only_when_it_must(db):
    gate.require_money_writer(CHURCH, _user(OWNER))
    assert [p.split("?")[0] for p in db.reads] == ["/businesses"]
    db.reads.clear()
    gate.require_money_writer(CHURCH, _user(ADMIN))
    assert [p.split("?")[0] for p in db.reads] == ["/businesses", "/businesses", "/business_users"]   # role_of reads both
    db.reads.clear()
    with pytest.raises(HTTPException):
        gate.require_money_writer(SHOP, _user(ADMIN))
    assert [p.split("?")[0] for p in db.reads] == ["/businesses"]       # outside a church the seat is never read


@pytest.mark.parametrize("who, biz", EVERYONE)
def test_the_bills_list_answers_as_its_reader_did(db, who, biz):
    import bills_router
    u = _user(PEOPLE[who])
    assert _answer(bills_router._reader, biz, u) == _answer(old_bills_reader, biz, u), (who, biz)
    assert _answer(bills_router._writer, biz, u) == _answer(old_require_money_writer, biz, u), (who, biz)
    assert _answer(bills_router._owner, biz, u) == _answer(old_owner_door, biz, u), (who, biz)


@pytest.mark.parametrize("who, biz", EVERYONE)
def test_the_owner_only_doors_stay_the_owners_with_the_same_words(db, who, biz, monkeypatch):
    import giving_router
    import housing_allowance
    import plaid_router
    import stripe_connect_router
    u = _user(PEOPLE[who])
    old = _answer(old_owner_door, biz, u)
    for door in (plaid_router._require_owner, giving_router._require_owner, stripe_connect_router._require_owner):
        assert _answer(door, biz, u) == old, (who, biz, door.__module__)
    assert _answer(gate.require_owner, biz, u) == old
    assert _answer(lambda: gate.require_money(biz, u, "see", "setup").business) == old
    # The housing allowance: its own switch, its own read, its own words.
    monkeypatch.setattr(housing_allowance, "switched_on", lambda b: True)
    got = _answer(housing_allowance.require_owner, biz, u.id)
    if biz not in TYPES:
        assert got == ("no", 404, "business not found")
    elif who == "owner":
        assert got == ("ok", None)
    else:
        assert got == ("no", 403, "The housing allowance is the owner's alone.")
    assert _answer(housing_allowance.require_owner, CHURCH, None) == ("no", 403, "The housing allowance is the owner's alone.")


@pytest.mark.parametrize("who, biz", EVERYONE)
def test_can_change_on_funds_and_statements_is_the_owner_alone(db, who, biz):
    import funds
    uid = PEOPLE[who]
    row = {"id": biz, "type": TYPES.get(biz), "owner_id": OWNER, "name": "Made-up"}
    assert funds.is_owner(row, uid) is (who == "owner")
    assert funds.is_owner(row, None) is False and funds.is_owner({"id": biz}, uid) is False
    assert gate.may_money(biz, _user(uid), "work", "setup", business=row) is (who == "owner")
    assert db.reads == []                                    # the row it was given is the row it used


@pytest.mark.parametrize("who, biz", EVERYONE)
def test_reopening_a_count_is_the_owners_or_an_admins_as_before(db, who, biz):
    u = _user(PEOPLE[who])
    old = _answer(old_reopen, biz, u)

    def new():
        import giving_records
        giving_records.require_finance(biz, u)               # giving_services._gate, which still runs first
        gate.require_money(biz, u, "work", "count_reopen")

    assert _answer(new) == old, (who, biz)


@pytest.mark.parametrize("who", list(PEOPLE))
def test_the_treasurers_desk_answers_as_treasurer_did_the_legacy_area_row_included(db, who, monkeypatch):
    import church_areas
    import church_checks
    uid = PEOPLE[who]
    role = _role(CHURCH, uid) or ("accountant" if who == "accountant" else None)
    if role is None:
        return                                               # no login here: church_checks._role is a 404 before this
    old = _answer(old_treasurer, CHURCH, uid, role)
    assert _answer(church_checks.treasurer, CHURCH, uid, role) == old, who
    assert old == ("ok", who in ("owner", "admin", "accountant", "guessed"))
    for need in gate.NEEDS:
        assert gate.may_money(CHURCH, _user(uid), need, "checks", role=role, accountant=role == "accountant") is old[1]
    # Who sees what switched off: nobody passes by an area.
    monkeypatch.setattr(church_areas, "mode", lambda: "owner")
    assert _answer(church_checks.treasurer, CHURCH, uid, role) == _answer(old_treasurer, CHURCH, uid, role)
    assert church_checks.treasurer(CHURCH, uid, role) is (who in ("owner", "admin", "accountant"))
    # A view that couldn't be read is a 503, never a yes.
    monkeypatch.setattr(church_areas, "mode", lambda: "on")
    monkeypatch.setattr(church_areas, "my_areas", lambda *a: None)
    assert _answer(church_checks.treasurer, CHURCH, uid, role) == _answer(old_treasurer, CHURCH, uid, role)
    if who not in ("owner", "admin", "accountant"):
        assert _answer(church_checks.treasurer, CHURCH, uid, role) == (
            "no", 503, "Your areas couldn't be read just now. Try again.")


def test_a_manager_who_is_also_the_accountant_is_not_the_treasurer_by_that_as_before(db):
    """church_checks resolves the role itself; a seat is a seat, and the
    accountant is asked about only when there is no seat."""
    import church_checks
    assert church_checks.treasurer(CHURCH, BOTH, "manager") is False is old_treasurer(CHURCH, BOTH, "manager")
    assert not any("business_collaborators" in p for p in db.reads)


@pytest.mark.parametrize("who", list(PEOPLE))
def test_help_requests_show_the_amounts_side_to_the_same_logins(db, who, monkeypatch):
    import church_areas
    import church_help
    uid = PEOPLE[who]
    role = _role(CHURCH, uid)
    if role is None:
        return
    assert _answer(church_help.view_of, CHURCH, uid, role) == _answer(old_help_view, CHURCH, uid, role), who
    assert church_help.view_of(CHURCH, uid, role) == ("care" if who in ("owner", "admin") else
                                                      "money" if who == "guessed" else None)
    monkeypatch.setattr(church_areas, "my_areas", lambda *a: {"areas": ["people_care", "giving_money"]})
    assert church_help.view_of(CHURCH, uid, role) == old_help_view(CHURCH, uid, role) == "care"
    monkeypatch.setattr(church_areas, "my_areas", lambda *a: None)
    assert _answer(church_help.view_of, CHURCH, uid, role) == _answer(old_help_view, CHURCH, uid, role)


@pytest.mark.parametrize("who, biz", EVERYONE)
def test_reports_the_roll_my_week_and_rentals_show_money_to_the_same_logins(db, who, biz, monkeypatch):
    import church_keys
    import church_reports
    import church_roll
    import church_spaces
    uid = PEOPLE[who]
    u = _user(uid)
    for role in (_role(biz, uid), "owner", "admin", "manager", "member", "viewer", None):
        assert church_reports._finance(biz, uid, role) is old_reports_finance(biz, uid, role), (who, biz, role)
        assert church_roll._may_give(biz, u, role) is old_roll_may_give(biz, u, role), (who, biz, role)
        top = role in ("owner", "admin")
        assert gate.may_money(biz, u, "see", "my_week", role=role) is top
        me = {"biz": {"id": biz}, "role": role, "uid": uid, "rooms": False}
        assert church_spaces._money(me) is top
        assert church_spaces._can(me)["rentals"] is top and church_spaces._can(me)["rental_list"] is top
    # Behind the Giving keeper, as before: a locked wall is a no for everyone.
    monkeypatch.setattr(church_keys, "is_open", lambda *a, **k: False)
    assert church_roll._may_give(biz, u, _role(biz, uid)) is False


def test_a_failed_read_is_a_no_for_the_screens_that_said_so_and_never_a_yes(db, monkeypatch):
    import business_collaborators_router as bcr
    import church_reports
    import church_roll

    def boom(*a, **k):
        raise RuntimeError("the database is away")

    monkeypatch.setattr(bcr, "is_active_accountant", boom)
    assert church_reports._finance(CHURCH, ACCOUNTANT, "manager") is False
    assert church_roll._may_give(CHURCH, _user(ACCOUNTANT), "manager") is False
    assert church_reports._finance(CHURCH, OWNER, "owner") is True        # the owner needs no such read
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    assert gate.can_write(CHURCH, _user(OWNER)) is False
    with pytest.raises(RuntimeError):
        gate.require_money(CHURCH, _user(OWNER), "work", "books")


def test_my_week_keeps_giving_off_the_list_for_everyone_but_the_owner_and_admins():
    src = (pathlib.Path(ROOT) / "church_my_week.py").read_text(encoding="utf-8")
    assert 'church_money_gate.may_money(biz, SimpleNamespace(id=user_id), "see", "my_week", role=role)' in src
    assert "FINANCE_ROLES" not in src


# ─── The source scan ──────────────────────────────────────────────────

# Every module that holds a door onto a church's money.
MONEY_MODULES = (
    "giving_records", "giving_router", "giving_services", "giving_sheets", "giving_week", "giving_ways",
    "giving_deposits", "giving_statements", "giving_statement_mail", "giving_reports", "church_pledges",
    "church_recurring_gifts", "chief_giving_actions", "chief_giving_counts", "church_checks", "church_money_levels",
    "church_help", "church_reports", "church_roll", "church_my_week", "church_spaces", "bills_router", "plaid_router",
    "bank_statements", "bank_money", "bank_picks", "funds", "housing_allowance", "expense_categories", "store_router",
    "stripe_connect_router", "gl_router", "reports_router", "chief_reconcile", "chief_file_bank",
)

# What a hand-written money decision looks like.
DECIDES = (
    r"\brole_of\(", r"\brequire_role\(", r"is_active_accountant\(",
    r"owner_id[\"']\)\)?\s*[!=]=", r"[!=]=\s*str\([\w\[\]\"'.]*owner_id", r"[!=]=\s*owner\b",
    r"in \(\"owner\", \"admin\"", r"(giving_money[\"']|MONEY_AREA|FINANCE_ONLY) in ",
    r"\b(FINANCE|FINANCE_ROLES|TREASURERS)\b",
)

# (module, function) → why that line is not a money decision, or why it stays.
ALLOWED: Dict[Tuple[str, str], str] = {
    ("church_pledges", "open_to"): "the feature switch: the platform owner's email, not a church's money",
    ("church_help", "open_to"): "the feature switch",
    ("church_reports", "open_to"): "the feature switch",
    ("church_roll", "open_to"): "the feature switch",
    ("church_spaces", "open_to"): "the feature switch",
    ("church_checks", "_role"): "resolves WHO this is (a seat, else the accountant) and hands it to the gate",
    ("church_checks", "_seat_names"): "a name for the page: 'The owner'",
    ("church_checks", "serves"): "whether an email is the owner's, for who may not approve their own request",
    ("church_help", "_seat_names"): "a name for the page",
    ("church_help", "treasurers"): "WHO TO TELL that a help request is ready to pay, not who may open it; it reads "
                                   "the same legacy area guess and moves to the tick with it",
    ("church_roll", "_areas_ok"): "People & care and the Office, not money",
    ("church_my_week", "people"): "leaves the owner out of a list of office logins",
    ("church_my_week", "_role"): "resolves the role it hands on",
    ("church_spaces", "shown"): "a name for the page",
    ("plaid_router", "_require_reader"): "the every-business read ladder (owner, accountant, any seat); in a church "
                                         "the gate's wall is asked first, on the line above it",
    ("gl_router", "_access"): "the every-business seat ladder; in a church the gate's wall is asked first",
    ("reports_router", "_owner_or_reader"): "the every-business read ladder; the gate's wall is asked first",
    ("reports_router", "_owner_or_accountant"): "the accountant's export, every business: not moved in this change",
    ("reports_router", "_owner"): "owner-only report writes, every business: not moved in this change",
    ("reports_router", "accountant_send"): "the seat ladder for sending the accountant's package, every business",
    ("reports_router", "put_budgets"): "the seat ladder for budgets, every business",
    ("reports_router", "customer_statement_send"): "the seat ladder for a customer's statement, every business",
    ("store_router", "get_inventory"): "stock, not money",
    ("store_router", "adjust_inventory"): "stock, not money",
    ("store_router", "set_inventory_threshold"): "stock, not money",
    ("store_router", "set_reorder_plan"): "stock, not money",
}


def _decisions(module: str) -> List[Tuple[str, int, str]]:
    """(function, line number, the line) for every line of code in a module
    that looks like a hand-written access decision. Comments and docstrings
    don't count."""
    src = (pathlib.Path(ROOT) / f"{module}.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    doc: set = set()
    for n in ast.walk(tree):
        body = getattr(n, "body", None)
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and body
                and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            doc.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    code: set = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                        tokenize.ENDMARKER):
            continue
        code.update(ln for ln in range(tok.start[0], tok.end[0] + 1) if ln not in doc)
    funcs = [(n.lineno, n.end_lineno or n.lineno, n.name) for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    lines = src.splitlines()
    out = []
    for ln in sorted(code):
        text = re.split(r"\s{2,}#", lines[ln - 1])[0]
        if any(re.search(p, text) for p in DECIDES):
            inside = [f for f in funcs if f[0] <= ln <= f[1]]
            fn = min(inside, key=lambda f: f[1] - f[0])[2] if inside else "<module>"
            out.append((fn, ln, text.strip()))
    return out


def test_no_money_module_decides_money_access_for_itself():
    found: Dict[Tuple[str, str], List[str]] = {}
    for module in MONEY_MODULES:
        for fn, ln, text in _decisions(module):
            found.setdefault((module, fn), []).append(f"{module}.py:{ln}  {text}")
    stray = {k: v for k, v in found.items() if k not in ALLOWED}
    assert not stray, ("a money module decides access without church_money_gate. Ask the gate "
                       "(require_money / may_money), or add the function to ALLOWED with the reason it is not a "
                       "money decision:\n" + "\n".join(line for v in stray.values() for line in v))
    stale = sorted(k for k in ALLOWED if k not in found)
    assert not stale, f"ALLOWED names a function with nothing left to allow: {stale}"


def test_the_scan_would_catch_each_old_copy():
    """The scan is only worth having if the lines this change removed would
    have tripped it."""
    for line in ('    if role in ("owner", "admin") or is_active_accountant(business_id, str(user.id)):',
                 '    role = role_of(business_id, str(user.id))',
                 '    if str(rows[0].get("owner_id")) != str(user.id):',
                 '    require_role(biz, str(user.id), "admin" if church_follow_up.is_church(row) else "viewer")',
                 '    finance = role in FINANCE_ROLES',
                 '    money = me["role"] in FINANCE',
                 '    if role in TREASURERS:',
                 '    return isinstance(areas, list) and MONEY_AREA in areas',
                 '    if not user_id or str(user_id) != owner:',
                 '    return bool(user_id) and str(biz_row.get("owner_id")) == str(user_id)'):
        assert any(re.search(p, line) for p in DECIDES), line


def test_the_gates_that_kept_their_names_only_ask_the_one_gate():
    import inspect
    import giving_records
    for fn in (giving_records.require_finance, giving_records.require_ministry_finance, gate.require_money_writer,
               gate.require_owner):
        body = inspect.getsource(fn)
        assert "require_money(" in body, fn.__name__
        code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith(("#", '"""')))
        assert "role_of(" not in code and "is_active_accountant(" not in code and "HTTPException(" not in code

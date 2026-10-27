"""Rooms & spaces, with Rentals (church_spaces.py). Kevin 2026-10-27, on the
Church Menu Gaps check ("Office, filled in", the 9:10 AM beat: a family calls
for the fellowship hall for a funeral meal on Saturday): "lets start building
this". Planning Center's Calendar is the bar.

Pins:
  * two booked bookings of one room never overlap: the second is refused and
    the answer names what it clashes with; back to back is fine; a request
    over a booked time is refused too, and so is approving the second of two
    overlapping requests; when two presses race, the table's constraint
    refuses one and the answer still names the clash
  * a weekly repeat is one row a week through its end date, at the same
    clock time across a clock change, all or none
  * the owner, admins and office logins use it; a login whose areas leave
    out the office, a stranger and a business that isn't a church don't;
    another church's spaces and bookings are invisible
  * a member-level office login asks (a request); an approver books
  * a rental's bill is made once, through the invoices, and linked; its
    money is the owner's and admins'
  * the status is false while the switch is off or the tables aren't made,
    and nothing answers 500
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas  # noqa: E402
import church_spaces as cs  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SALON = "33333333-3333-4333-8333-333333333333"
NAMES = ("owner", "admin", "manager", "secretary", "viewer", "singer", "stranger", "other_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
NY = "America/New_York"
T0 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
HALL = "aaaaaaaa-0000-4000-8000-000000000001"
VAN = "aaaaaaaa-0000-4000-8000-000000000002"
THEIRS = "aaaaaaaa-0000-4000-8000-000000000003"
DANA = "cccccccc-0000-4000-8000-000000000001"


def _ny(y, mo, d, h, mi=0) -> str:
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(NY)).isoformat()


def _overlap(a, b) -> bool:
    return a["start_at"] < b["end_at"] and b["start_at"] < a["end_at"]


class SpacesDB(FakeDB):
    """The two tables' defaults, the exclusion constraint, `like`, and the
    invoices' primary key, on the shared fake."""

    def _match(self, row, filters):
        rest = []
        for f in filters:
            if f[0] != "or" and f[1] == "like":
                if not re.match("^" + re.escape(f[2]).replace("%", ".*") + "$", str(row.get(f[0]) or "")):
                    return False
            else:
                rest.append(f)
        return super()._match(row, rest)

    def _clash(self, rows):
        booked = [r for r in self.t.get("church_space_bookings", []) if r.get("status") == "booked"]
        for i, r in enumerate(rows):
            if r.get("status") != "booked":
                continue
            others = [b for b in booked if b["id"] != r["id"]] + [x for x in rows[:i] if x.get("status") == "booked"]
            if any(b["space_id"] == r["space_id"] and _overlap(b, r) for b in others):
                return True
        return False

    def get(self, path, **kw):
        if self.missing and path.lstrip("/").split("?")[0] in ("church_spaces", "church_space_bookings"):
            return None   # the relation doesn't exist yet
        return super().get(path, **kw)

    def post(self, path, body, prefer=None, **kw):
        table = path.lstrip("/").split("?")[0]
        rows = body if isinstance(body, list) else [body]
        if table == "church_space_bookings":
            rows = [{"status": "requested", "kind": "use", "notes": "", "fee_cents": 0, "deposit_cents": 0,
                     "invoice_id": None, "contact_id": None, "series_id": None, "repeat_until": None,
                     "renter_name": None, "renter_email": None, "renter_phone": None, **r} for r in rows]
            if self._clash(rows):
                return None   # 409 from the exclusion constraint
        if table == "invoices" and any(r.get("id") and any(i["id"] == r["id"] for i in self.t.get("invoices", []))
                                       for r in rows):
            return None       # 409 from the primary key
        return super().post(path, rows, prefer=prefer, **kw)

    def patch(self, path, body, **kw):
        table, filters, _ = self._parse(path)
        if table == "church_space_bookings" and body.get("status") == "booked":
            hit = [{**r, **body} for r in self.t.get(table, []) if self._match(r, filters)]
            if self._clash(hit):
                return None
        return super().patch(path, body, **kw)


@pytest.fixture
def db(monkeypatch):
    seats = (("admin", "admin"), ("manager", "manager"), ("secretary", "member"), ("viewer", "viewer"),
             ("singer", "member"))
    fake = SpacesDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"], "settings": {}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"], "settings": {}},
                    {"id": SALON, "name": "Shear Joy", "type": "salon", "owner_id": ID["owner"], "settings": {}}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active",
                         "invited_email": f"{n}@lovecity.org"} for n, r in seats],
        contacts=[{"id": DANA, "business_id": BIZ, "name": "Dana Johnson", "email": "dana@example.com"}],
        church_spaces=[{"id": HALL, "business_id": BIZ, "name": "Fellowship hall", "kind": "room", "capacity": 120,
                        "notes": "", "active": True, "sort_order": 0},
                       {"id": VAN, "business_id": BIZ, "name": "The van", "kind": "vehicle", "capacity": 15,
                        "notes": "", "active": True, "sort_order": 1},
                       {"id": THEIRS, "business_id": OTHER, "name": "Grace sanctuary", "kind": "room", "capacity": 300,
                        "notes": "", "active": True, "sort_order": 0}],
        church_space_bookings=[], invoices=[],
    )
    fake.missing = False
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_SPACES", "on")
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setattr(cs, "_now", lambda: T0)
    # Who sees what: the singer works worship only; everyone else, the whole church.
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {
        "areas": ["worship_media"] if uid == ID["singer"] else None, "by": "picked"})
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(cs.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def _book(name, biz=BIZ, **kw):
    body = {"business_id": biz, "space_id": HALL, "title": "Johnson family meal", "tz": NY,
            "start_at": _ny(2026, 10, 31, 17), "end_at": _ny(2026, 10, 31, 20), **kw}
    return client(name).post("/church/spaces/bookings", json=body)


def _rows(db, **match):
    return [r for r in db.t["church_space_bookings"] if all(r.get(k) == v for k, v in match.items())]


# ─── The switch, the tables ──────────────────────────────────────────

def test_status_is_false_when_the_switch_is_off(db, monkeypatch):
    monkeypatch.setenv("CHURCH_SPACES", "off")
    for name in ("owner", "admin", "stranger"):
        assert client(name).get(f"/church/spaces/status?business_id={BIZ}").json()["enabled"] is False
    assert client("owner").get(f"/church/spaces?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_SPACES", "owner")   # the platform owner alone until a Thursday
    assert client("owner").get(f"/church/spaces/status?business_id={BIZ}").json()["enabled"] is True
    assert client("admin").get(f"/church/spaces/status?business_id={BIZ}").json()["enabled"] is False
    assert _book("admin").status_code == 404


def test_status_is_false_until_the_tables_are_made_and_nothing_answers_500(db):
    db.missing = True
    assert client("owner").get(f"/church/spaces/status?business_id={BIZ}").json() == {
        "enabled": False, "book": False, "approve": False, "rentals": False}
    c = client("owner")
    for got in (c.get(f"/church/spaces?business_id={BIZ}"),
                c.get(f"/church/spaces/bookings?business_id={BIZ}&start=2026-10-25T00:00:00Z&end=2026-11-01T00:00:00Z"),
                c.get(f"/church/spaces/rentals?business_id={BIZ}"),
                _book("owner")):
        assert got.status_code == 503, got.text


def test_status_says_what_each_login_may_do(db):
    def status(name):
        return client(name).get(f"/church/spaces/status?business_id={BIZ}").json()
    assert status("owner") == {"enabled": True, "book": True, "approve": True, "rentals": True}
    assert status("admin") == {"enabled": True, "book": True, "approve": True, "rentals": True}
    assert status("manager") == {"enabled": True, "book": True, "approve": True, "rentals": False}
    assert status("secretary") == {"enabled": True, "book": True, "approve": False, "rentals": False}
    assert status("viewer") == {"enabled": True, "book": False, "approve": False, "rentals": False}
    assert status("singer")["enabled"] is False, "their areas leave out the office"
    assert client("owner").get(f"/church/spaces/status?business_id={SALON}").json()["enabled"] is False


# ─── Who ─────────────────────────────────────────────────────────────

def test_a_login_that_doesnt_work_the_office_is_refused(db):
    assert client("singer").get(f"/church/spaces?business_id={BIZ}").status_code == 403
    assert _book("singer").status_code == 403
    assert client("stranger").get(f"/church/spaces?business_id={BIZ}").status_code == 404
    assert client("stranger").get(f"/church/spaces/status?business_id={BIZ}").status_code == 404
    assert _book("stranger").status_code == 404
    assert _book("viewer").status_code == 403, "a viewer only looks"
    assert client("owner").get(f"/church/spaces?business_id={SALON}").status_code == 404, "churches only"
    assert db.t["church_space_bookings"] == []


def test_another_churchs_spaces_are_invisible(db):
    mine = client("owner").get(f"/church/spaces?business_id={BIZ}").json()["spaces"]
    assert [s["name"] for s in mine] == ["Fellowship hall", "The van"]
    assert _book("owner", space_id=THEIRS).status_code == 404, "their room isn't ours to book"
    theirs = _book("other_owner", biz=OTHER, space_id=THEIRS, title="Grace prayer night").json()["bookings"][0]
    assert client("owner").patch(f"/church/spaces/{THEIRS}", json={"business_id": BIZ, "name": "Ours now"}).status_code == 404
    assert client("owner").post(f"/church/spaces/bookings/{theirs['id']}/decide",
                                json={"business_id": BIZ, "status": "cancelled"}).status_code == 404
    week = client("owner").get(f"/church/spaces/bookings?business_id={BIZ}"
                               "&start=2026-10-25T00:00:00Z&end=2026-11-01T04:00:00Z").json()
    assert week["bookings"] == [] and week["requests"] == []
    assert client("other_owner").get(f"/church/spaces?business_id={BIZ}").status_code == 404
    assert db.t["church_spaces"][2]["name"] == "Grace sanctuary"


# ─── Clashes ─────────────────────────────────────────────────────────

def test_a_clash_is_refused_and_says_what_it_clashes_with(db):
    first = _book("admin")
    assert first.status_code == 200 and first.json()["status"] == "booked"
    late = _book("manager", title="Choir rehearsal", start_at=_ny(2026, 10, 31, 19), end_at=_ny(2026, 10, 31, 21))
    assert late.status_code == 409
    d = late.json()["detail"]
    assert d["code"] == "clash"
    assert d["message"] == "Fellowship hall is already booked then: Johnson family meal, Sat Oct 31, 5:00 PM–8:00 PM."
    assert d["clashes"][0]["id"] == first.json()["bookings"][0]["id"]
    ask = _book("secretary", title="Youth night", start_at=_ny(2026, 10, 31, 18), end_at=_ny(2026, 10, 31, 19))
    assert ask.status_code == 409, "a request over a booked time is refused too"
    assert _book("admin", title="Clean up", start_at=_ny(2026, 10, 31, 20), end_at=_ny(2026, 10, 31, 21)).status_code == 200
    assert _book("admin", space_id=VAN, title="Van to the cemetery").status_code == 200, "another space"
    # The page asks before it saves.
    check = client("secretary").post("/church/spaces/check", json={
        "business_id": BIZ, "space_id": HALL, "tz": NY, "start_at": _ny(2026, 10, 31, 16), "end_at": _ny(2026, 10, 31, 18)})
    assert check.status_code == 200 and check.json()["clashes"][0]["title"] == "Johnson family meal"
    assert check.json()["message"].startswith("Fellowship hall is already booked then")
    assert len(_rows(db, space_id=HALL, status="booked")) == 2


def test_two_presses_at_once_one_is_refused_by_the_table_and_still_named(db, monkeypatch):
    real = cs.clashes
    calls = []

    def racing(*a, **kw):
        calls.append(1)
        return [] if len(calls) == 2 else real(*a, **kw)   # the second press checked before the first saved
    assert _book("admin").status_code == 200
    monkeypatch.setattr(cs, "clashes", racing)
    got = _book("manager", title="Choir rehearsal")
    assert got.status_code == 409 and "Johnson family meal" in got.json()["detail"]["message"]
    assert len(_rows(db, status="booked")) == 1


def test_a_request_waits_for_an_approver_and_the_second_of_two_overlapping_is_refused(db):
    a = _book("secretary", title="Youth night")
    assert a.status_code == 200 and a.json()["status"] == "requested", "a member-level login asks"
    b = _book("secretary", title="Ladies' tea", start_at=_ny(2026, 10, 31, 18), end_at=_ny(2026, 10, 31, 19))
    assert b.status_code == 200, "requests may overlap each other"
    week = client("viewer").get(f"/church/spaces/bookings?business_id={BIZ}"
                                "&start=2026-10-25T00:00:00Z&end=2026-11-01T04:00:00Z").json()
    assert [r["title"] for r in week["requests"]] == ["Youth night", "Ladies' tea"]
    assert week["requests"][0]["by_name"] == "secretary@lovecity.org"
    aid, bid = a.json()["bookings"][0]["id"], b.json()["bookings"][0]["id"]
    decide = lambda who, bid_, st: client(who).post(f"/church/spaces/bookings/{bid_}/decide",
                                                    json={"business_id": BIZ, "status": st, "tz": NY})
    assert decide("secretary", aid, "booked").status_code == 403, "a request isn't its own approval"
    assert decide("admin", aid, "booked").json()["bookings"][0]["status"] == "booked"
    second = decide("admin", bid, "booked")
    assert second.status_code == 409 and "Youth night" in second.json()["detail"]["message"]
    assert decide("admin", bid, "declined").json()["bookings"][0]["status"] == "declined"
    assert decide("admin", bid, "declined").status_code == 409, "settled once"
    # The person who asked can cancel their own; no one else below an admin can.
    c = _book("secretary", title="Bake sale", start_at=_ny(2026, 11, 1, 13), end_at=_ny(2026, 11, 1, 15))
    cid = c.json()["bookings"][0]["id"]
    assert decide("viewer", cid, "cancelled").status_code == 403
    assert decide("secretary", cid, "cancelled").json()["bookings"][0]["status"] == "cancelled"


# ─── Weekly repeats ──────────────────────────────────────────────────

def test_weekly_repeats_expand_with_no_clashes_at_the_same_clock_time(db):
    got = _book("admin", title="Men's breakfast", start_at=_ny(2026, 10, 25, 9), end_at=_ny(2026, 10, 25, 11),
                repeat_until="2026-11-15")
    assert got.status_code == 200, got.text
    rows = got.json()["bookings"]
    assert len(rows) == 4 and len({r["series_id"] for r in rows}) == 1 and rows[0]["series_id"]
    starts = [datetime.fromisoformat(r["start_at"]) for r in rows]
    assert [s.astimezone(ZoneInfo(NY)).hour for s in starts] == [9, 9, 9, 9], "9 AM across the clock change"
    assert [s.astimezone(timezone.utc).hour for s in starts] == [13, 14, 14, 14]
    assert all(r["repeat_until"] == "2026-11-15" and r["status"] == "booked" for r in rows)
    # A repeat that meets one booked week is refused whole, naming it.
    clash = _book("admin", title="Prayer breakfast", start_at=_ny(2026, 10, 25, 10), end_at=_ny(2026, 10, 25, 12),
                  space_id=VAN, repeat_until="2026-11-29")
    assert clash.status_code == 200, "another space"
    again = _book("admin", title="Bible study", start_at=_ny(2026, 11, 8, 10), end_at=_ny(2026, 11, 8, 12),
                  repeat_until="2026-11-29")
    assert again.status_code == 409
    d = again.json()["detail"]
    assert d["message"] == ("Fellowship hall is already booked then: Men's breakfast, Sun Nov 8, 9:00 AM–11:00 AM. "
                            "And 1 more time in this repeat.")
    assert len(_rows(db, space_id=HALL)) == 4, "all or none"
    # Cancel this one and the later ones.
    third = rows[2]["id"]
    left = client("admin").post(f"/church/spaces/bookings/{third}/decide",
                                json={"business_id": BIZ, "status": "cancelled", "series": True}).json()["bookings"]
    assert len(left) == 2 and len(_rows(db, space_id=HALL, status="booked")) == 2
    assert _book("admin", repeat_until="2028-01-01").status_code == 400, "a year at most"


def test_expand_weekly_and_the_clock_words():
    tz = ZoneInfo(NY)
    s = datetime(2026, 10, 25, 9, tzinfo=tz)
    assert cs.expand_weekly(s, s + timedelta(hours=2), None, tz) == [(s, s + timedelta(hours=2))]
    weeks = cs.expand_weekly(s, s + timedelta(hours=2), date(2026, 11, 14), tz)
    assert len(weeks) == 3, "the 15th's week starts after the end date"
    assert cs.overlaps(s, s + timedelta(hours=1), s + timedelta(minutes=59), s + timedelta(hours=2))
    assert not cs.overlaps(s, s + timedelta(hours=1), s + timedelta(hours=1), s + timedelta(hours=2))
    assert cs.when_text(s, s + timedelta(hours=2), tz) == "Sun Oct 25, 9:00 AM–11:00 AM"
    assert cs.when_text(s, s + timedelta(days=1), tz) == "Sun Oct 25, 9:00 AM – Mon Oct 26, 9:00 AM"
    with pytest.raises(HTTPException):
        cs.expand_weekly(s, s + timedelta(hours=1), date(2028, 1, 1), tz)


# ─── Rentals ─────────────────────────────────────────────────────────

def _rental(name="admin", **kw):
    return _book(name, title="Carter wedding reception", kind="rental", renter_name="Ana Carter",
                 renter_email="ana.carter@example.com", renter_phone="555-0199", fee=250, deposit=100, **kw)


def test_a_rental_bill_is_made_once_and_linked(db):
    got = _rental()
    assert got.status_code == 200, got.text
    r = got.json()["bookings"][0]
    assert r["fee_cents"] == 25000 and r["deposit_cents"] == 10000 and r["bill"] is None
    bill = lambda who="admin": client(who).post(f"/church/spaces/bookings/{r['id']}/bill",
                                                json={"business_id": BIZ, "tz": NY})
    first = bill()
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True
    [inv] = db.t["invoices"]
    assert inv["business_id"] == BIZ and inv["status"] == "draft" and inv["total"] == 350.0
    assert inv["invoice_number"] == "INV-2026-001" and inv.get("is_gift") in (None, False)
    assert [i["description"] for i in inv["items"]] == [
        "Fellowship hall rental: Carter wedding reception (Sat Oct 31, 5:00 PM–8:00 PM)", "Deposit"]
    [renter] = [c for c in db.t["contacts"] if c.get("email") == "ana.carter@example.com"]
    assert renter["name"] == "Ana Carter" and renter["source"] == "room_rental" and inv["contact_id"] == renter["id"]
    row = _rows(db, id=r["id"])[0]
    assert row["invoice_id"] == inv["id"] and row["contact_id"] == renter["id"]
    assert first.json()["bookings"][0]["bill"]["status"] == "draft"
    again = bill()
    assert again.json()["created"] is False and again.json()["invoice_id"] == inv["id"]
    # A press after a link that failed: the same bill, linked, never a second.
    row["invoice_id"] = None
    assert bill().json()["invoice_id"] == inv["id"] and len(db.t["invoices"]) == 1
    assert _rows(db, id=r["id"])[0]["invoice_id"] == inv["id"]
    # Paid shows on the Rentals page.
    inv.update(status="paid", paid_at="2026-10-26T15:00:00+00:00")
    rentals = client("admin").get(f"/church/spaces/rentals?business_id={BIZ}").json()["rentals"]
    assert rentals[0]["bill"]["status"] == "paid" and rentals[0]["bill"]["number"] == "INV-2026-001"
    # The amounts on a billed rental stay put.
    edit = client("admin").patch(f"/church/spaces/bookings/{r['id']}", json={"business_id": BIZ, "fee": 300})
    assert edit.status_code == 409


def test_the_bill_number_follows_the_years_highest_and_a_cancel_names_the_bill_left(db):
    db.t["invoices"] += [{"id": f"i{n}", "business_id": BIZ, "invoice_number": f"INV-2026-{n:03d}", "status": "paid"}
                         for n in (7, 999, 1000)] + [{"id": "x", "business_id": BIZ, "invoice_number": "INV-2026-draft"},
                                                     {"id": "o", "business_id": OTHER, "invoice_number": "INV-2026-5000"}]
    r = _rental().json()["bookings"][0]
    client("admin").post(f"/church/spaces/bookings/{r['id']}/bill", json={"business_id": BIZ, "tz": NY})
    made = [i for i in db.t["invoices"] if i.get("contact_id")][0]
    assert made["invoice_number"] == "INV-2026-1001", "read as numbers, this church's only"
    gone = client("admin").post(f"/church/spaces/bookings/{r['id']}/decide",
                                json={"business_id": BIZ, "status": "cancelled"}).json()
    assert gone["bookings"][0]["status"] == "cancelled"
    assert [b["id"] for b in gone["bills_left"]] == [made["id"]] and gone["bills_left"][0]["status"] == "draft"
    use = _book("admin", start_at=_ny(2026, 11, 2, 9), end_at=_ny(2026, 11, 2, 10)).json()["bookings"][0]
    assert client("admin").post(f"/church/spaces/bookings/{use['id']}/decide",
                                json={"business_id": BIZ, "status": "cancelled"}).json()["bills_left"] == []


def test_a_bill_needs_a_booked_rental_with_an_amount_and_somewhere_to_go(db):
    use = _book("admin").json()["bookings"][0]
    assert client("admin").post(f"/church/spaces/bookings/{use['id']}/bill", json={"business_id": BIZ}).status_code == 400
    bare = _book("admin", kind="rental", title="Room for a meeting", start_at=_ny(2026, 11, 2, 9),
                 end_at=_ny(2026, 11, 2, 10), fee=50).json()["bookings"][0]
    got = client("admin").post(f"/church/spaces/bookings/{bare['id']}/bill", json={"business_id": BIZ, "tz": NY})
    assert got.status_code == 400 and "email" in got.json()["detail"]
    assert db.t["invoices"] == []
    # Picking one of the church's people is somewhere to go.
    client("admin").patch(f"/church/spaces/bookings/{bare['id']}", json={"business_id": BIZ, "contact_id": DANA})
    assert client("admin").post(f"/church/spaces/bookings/{bare['id']}/bill",
                                json={"business_id": BIZ, "tz": NY}).json()["created"] is True
    assert db.t["invoices"][0]["contact_id"] == DANA and db.t["invoices"][0]["total"] == 50.0


def test_a_rentals_money_stays_with_the_owner_and_admins(db):
    r = _rental().json()["bookings"][0]
    assert _rental("secretary", start_at=_ny(2026, 11, 7, 17), end_at=_ny(2026, 11, 7, 20)).status_code == 403, \
        "only an admin sets a fee"
    week = client("secretary").get(f"/church/spaces/bookings?business_id={BIZ}"
                                   "&start=2026-10-25T00:00:00Z&end=2026-11-01T04:00:00Z").json()["bookings"]
    seen = week[0]
    assert seen["kind"] == "rental" and seen["renter_name"] == "Ana Carter"
    assert not {"fee_cents", "deposit_cents", "invoice_id", "bill"} & set(seen)
    for who in ("secretary", "manager"):
        assert client(who).get(f"/church/spaces/rentals?business_id={BIZ}").status_code == 403
        assert client(who).post(f"/church/spaces/bookings/{r['id']}/bill", json={"business_id": BIZ}).status_code == 403
    assert db.t["invoices"] == []
    # A rental the office takes without its amounts: an admin sets them later.
    ask = _book("secretary", kind="rental", title="Garcia birthday", renter_name="Luis Garcia",
                start_at=_ny(2026, 11, 7, 12), end_at=_ny(2026, 11, 7, 15))
    assert ask.status_code == 200 and ask.json()["status"] == "requested"


# ─── Spaces ──────────────────────────────────────────────────────────

def test_approvers_keep_the_list_of_spaces(db):
    add = lambda who, **kw: client(who).post("/church/spaces", json={"business_id": BIZ, **kw})
    assert add("secretary", name="Projector", kind="equipment").status_code == 403
    made = add("manager", name="Projector", kind="equipment", capacity="")
    assert made.status_code == 200 and made.json()["space"]["sort_order"] == 2
    assert add("admin", name="Boat", kind="boat").status_code == 400
    assert add("admin", name="  ").status_code == 400
    pid = made.json()["space"]["id"]
    order = client("admin").post("/church/spaces/order", json={"business_id": BIZ, "ids": [pid, HALL, VAN]})
    assert [s["name"] for s in order.json()["spaces"]] == ["Projector", "Fellowship hall", "The van"]
    assert client("admin").post("/church/spaces/order", json={"business_id": BIZ, "ids": [THEIRS]}).status_code == 400
    off = client("admin").patch(f"/church/spaces/{VAN}", json={"business_id": BIZ, "active": False})
    assert off.json()["space"]["active"] is False
    assert _book("admin", space_id=VAN).status_code == 400, "a retired space takes no new bookings"

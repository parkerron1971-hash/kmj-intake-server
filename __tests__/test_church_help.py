"""Help requests, benevolence (church_help.py). Kevin 2026-10-27, on the Church
Office Prototypes ("Help requests" tab): "lets go with your list". A single
mom asks for help with a light bill; the office needs a fund, a limit, a yes
and a record.

Pins:
  * confidential by area: the owner, admins and People & care logins read who
    and the story; a private request's name is the owner's and admins'; a
    youth's ask is theirs alone; a Giving login sees amounts, never a name or
    a story; anyone else is refused
  * the limit: up to it, staff approve; above it a keeper of Giving & money
    says yes (a keeper here, or the asker with an open key, by tap or code),
    the owner bound too; with no keeper the limit alone governs; raising the
    limit needs the same yes
  * another church's requests, asks and people are unreachable
  * help given goes into the books as an expense of the fund (no name, no
    story), adds up into the month's fund and the year's families; giving
    more than approved is approving more; closed books refuse; a record can
    be taken back with its expense
  * the status is false while the switch is off or the tables aren't made,
    and nothing answers 500
  * a member's "Ask for help" from the app shows up, and becomes one request
    when the office acts; its Prayer & care row moves along
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
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
import church_help as ch  # noqa: E402
import church_keys as ck  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SALON = "33333333-3333-4333-8333-333333333333"
NAMES = ("owner", "admin", "carer", "viewer", "treasurer", "singer", "stranger", "other_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
T0 = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
DANA = "cccccccc-0000-4000-8000-000000000001"
MARCUS = "cccccccc-0000-4000-8000-000000000002"
THEIR_PERSON = "cccccccc-0000-4000-8000-000000000003"
ASK = "dddddddd-0000-4000-8000-000000000001"
PRAYER = "dddddddd-0000-4000-8000-000000000002"
CLOSED_ASK = "dddddddd-0000-4000-8000-000000000003"
YOUTH_ASK = "dddddddd-0000-4000-8000-000000000004"
THEIR_ASK = "dddddddd-0000-4000-8000-000000000005"
VISIT = "dddddddd-0000-4000-8000-000000000006"
STORY = "Our light bill is past due and the kids are home."


class HelpDB(FakeDB):
    """The three tables' defaults, the ask's one-row rule, the fund's upsert
    and PostgREST's JSON filter (submission->>kind), on the shared fake."""

    REQ_DEFAULTS = {"contact_id": None, "name": None, "anonymous": False, "pastors_only": False, "wants_call": False,
                    "amount_cents": None, "approved_cents": None, "notes": "", "status": "new", "source": "phone",
                    "care_request_id": None, "created_by": None, "decided_by": None, "decided_at": None}

    def _match(self, row, filters):
        if any(f[0] != "or" and "->>" in f[0] for f in filters):
            row = dict(row)
            for f in filters:
                if f[0] != "or" and "->>" in f[0]:
                    base, key = f[0].split("->>", 1)
                    v = (row.get(base) or {}).get(key) if isinstance(row.get(base), dict) else None
                    row[f[0]] = v
        return super()._match(row, filters)

    def _gone(self, path):
        return self.missing and path.lstrip("/").split("?")[0].startswith("church_help_")

    def get(self, path, **kw):
        return None if self._gone(path) else super().get(path, **kw)

    def post(self, path, body, prefer=None, **kw):
        if self._gone(path):
            return None
        table = path.lstrip("/").split("?")[0]
        rows = body if isinstance(body, list) else [body]
        if table == "church_help_requests":
            rows = [{**self.REQ_DEFAULTS, **r} for r in rows]
            have = self.t.setdefault(table, [])
            fresh = [r for r in rows if not (r.get("care_request_id") and any(
                h.get("care_request_id") == r["care_request_id"] for h in have))]
            if len(fresh) < len(rows) and "on_conflict=care_request_id" not in path:
                return None   # 409 from the unique ask
            rows = fresh
            if not rows:
                return []     # ignore-duplicates: nothing new
        if table == "church_help_settings":
            have = self.t.setdefault(table, [])
            old = next((r for r in have if r["business_id"] == rows[0]["business_id"]), None)
            if old:
                old.update(rows[0])
                return [dict(old)]
        if table == "church_help_given":
            rows = [{"note": "", "payee": None, "expense_id": None, **r} for r in rows]
        if table == "church_area_keys":
            rows = [{"status": "asked", "asked_at": ck._iso(ck._now()), "code_tries": 0, "reason": "",
                     "answered_by": None, "opens_until": None, "how": None, **r} for r in rows]
        return super().post(path, rows, prefer=prefer, **kw)

    def patch(self, path, body, **kw):
        return None if self._gone(path) else super().patch(path, body, **kw)


@pytest.fixture
def db(monkeypatch):
    seats = (("admin", "admin"), ("carer", "member"), ("viewer", "viewer"), ("treasurer", "manager"),
             ("singer", "member"))
    care = lambda cid, biz, sub, status="new", contact=DANA: {  # noqa: E731
        "id": cid, "business_id": biz, "status": status, "contact_id": contact, "submission": sub,
        "created_at": "2026-10-26T14:00:00+00:00"}
    fake = HelpDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"],
                     "settings": {"giving": {"funds": ["Tithes & offerings", "Benevolence fund", "Building"]}}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"], "settings": {}},
                    {"id": SALON, "name": "Shear Joy", "type": "salon", "owner_id": ID["owner"], "settings": {}}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active",
                         "invited_email": f"{n}@lovecity.org"} for n, r in seats],
        contacts=[{"id": DANA, "business_id": BIZ, "name": "Dana Johnson"},
                  {"id": MARCUS, "business_id": BIZ, "name": "Marcus Reed"},
                  {"id": THEIR_PERSON, "business_id": OTHER, "name": "Grace Member"}],
        ministry_care_requests=[
            care(ASK, BIZ, {"kind": "help", "need": "A bill", "request": STORY, "name": "Dana Johnson",
                            "confidential": "yes", "source": "Member app, Ask the church", "wants_call": "yes"}),
            care(PRAYER, BIZ, {"prayer_request": "Pray for my mother", "confidential": "no"}),
            care(CLOSED_ASK, BIZ, {"kind": "help", "need": "Food", "request": "Handled in care"}, status="closed"),
            care(YOUTH_ASK, BIZ, {"kind": "help", "need": "A ride", "request": "Ride to school", "youth": "yes",
                                  "source": "Member app, Youth"}, contact=MARCUS),
            care(VISIT, BIZ, {"kind": "visit", "visit": "A home visit", "request": "Please visit"}),
            care(THEIR_ASK, OTHER, {"kind": "help", "need": "Food", "request": "Theirs"}, contact=THEIR_PERSON),
        ],
        church_help_settings=[], church_help_requests=[], church_help_given=[], business_expenses=[],
        church_keepers=[], church_area_keys=[], accounting_periods=[],
    )
    fake.missing = False
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_HELP", "on")
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setenv("CHURCH_KEYS", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setattr(ch, "_now", lambda: T0)
    monkeypatch.setattr(ck, "_now", lambda: T0)
    monkeypatch.setattr(ch, "_tz", lambda biz: ZoneInfo("America/New_York"))
    fake.told = []
    monkeypatch.setattr(ck, "_tell", lambda biz, to, title, body, seats, tag: fake.told.append((sorted(to), title, body)))
    # Who sees what: the carer and the viewer work People & care, the
    # treasurer Giving & money only, the singer worship only.
    areas = {ID["carer"]: ["people_care"], ID["viewer"]: ["people_care"], ID["treasurer"]: ["giving_money"],
             ID["singer"]: ["worship_media"]}
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {"areas": areas.get(uid), "by": "picked"})
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(ch.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def _page(name, biz=BIZ):
    got = client(name).get(f"/church/help?business_id={biz}")
    assert got.status_code == 200, got.text
    return got.json()


def _add(who, biz=BIZ, **kw):
    body = {"business_id": biz, "need": "bill", "amount": "180", "notes": STORY, "contact_id": DANA, **kw}
    return client(who).post("/church/help/requests", json=body)


def _decide(name, ref, status="approved", amount=None, biz=BIZ):
    body = {"business_id": biz, "status": status, **({"amount": amount} if amount is not None else {})}
    return client(name).post(f"/church/help/requests/{ref}/decide", json=body)


def _give(name, ref, biz=BIZ, **kw):
    body = {"business_id": biz, "how": "check", "amount": "150", "given_on": "2026-10-27",
            "payee": "Cleveland Electric", **kw}
    return client(name).post(f"/church/help/requests/{ref}/given", json=body)


def _keeper(db, name, area="giving_money"):
    db.t["church_keepers"].append({"business_id": BIZ, "area": area, "user_id": ID[name], "added_by": ID["admin"],
                                   "added_at": "2026-10-01T00:00:00+00:00",
                                   "starts_at": "2026-10-01T00:00:00+00:00", "ends_at": None})


def _req(db, ref):
    return next(r for r in db.t["church_help_requests"] if r["id"] == ref)


def _by(page, ref):
    return next(r for r in page["requests"] if r["id"] == ref)


# ─── The switch, the tables ──────────────────────────────────────────

def test_status_is_false_when_the_switch_is_off_or_the_tables_arent_made(db, monkeypatch):
    def status(name):
        return client(name).get(f"/church/help/status?business_id={BIZ}").json()["enabled"]
    monkeypatch.setenv("CHURCH_HELP", "off")
    assert status("owner") is False and status("admin") is False
    assert client("owner").get(f"/church/help?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_HELP", "owner")   # the platform owner alone until a Thursday
    assert status("owner") is True and status("admin") is False
    assert _add("admin").status_code == 404
    monkeypatch.setenv("CHURCH_HELP", "on")
    db.missing = True
    assert client("owner").get(f"/church/help/status?business_id={BIZ}").json() == {
        "enabled": False, "view": None, "approve": False, "settings": False}
    c = client("owner")
    for got in (c.get(f"/church/help?business_id={BIZ}"), _add("owner"), _decide("owner", f"care-{ASK}"),
                c.put("/church/help/settings", json={"business_id": BIZ, "gift_limit": "200"})):
        assert got.status_code == 503, got.text
    assert db.t["church_help_requests"] == [] and db.t["business_expenses"] == []


def test_status_says_what_each_login_may_do(db):
    def status(name, biz=BIZ):
        return client(name).get(f"/church/help/status?business_id={biz}").json()
    assert status("owner") == {"enabled": True, "view": "care", "approve": True, "settings": True}
    assert status("admin") == {"enabled": True, "view": "care", "approve": True, "settings": True}
    assert status("carer") == {"enabled": True, "view": "care", "approve": True, "settings": False}
    assert status("viewer") == {"enabled": True, "view": "care", "approve": False, "settings": False}
    assert status("treasurer") == {"enabled": True, "view": "money", "approve": False, "settings": False}
    assert status("singer")["enabled"] is False, "their areas leave out care and giving"
    assert status("owner", SALON)["enabled"] is False, "churches only"
    assert client("stranger").get(f"/church/help/status?business_id={BIZ}").status_code == 404


# ─── Who sees what ───────────────────────────────────────────────────

def test_help_requests_are_confidential_by_area(db):
    bill = _add("carer").json()["request"]
    private = _add("carer", need="food", amount="60", notes="Lost my job", contact_id=MARCUS, anonymous=True).json()["request"]
    assert _decide("carer", bill["id"], amount="150").status_code == 200
    assert _give("carer", bill["id"], note="Paid the July balance for Dana").status_code == 200

    carer = _page("carer")
    mine = _by(carer, bill["id"])
    assert mine["who"] == "Dana Johnson" and mine["notes"] == STORY and mine["private"] is False
    assert mine["given"][0]["note"] == "Paid the July balance for Dana"
    hidden = _by(carer, private["id"])
    assert hidden["who"] is None and hidden["contact_id"] is None and hidden["private"] is True
    assert hidden["notes"] == "Lost my job", "the care team reads the need; only who is kept back"
    assert all(r["id"] != f"care-{YOUTH_ASK}" for r in carer["requests"]), "a youth's ask is the pastors' alone"
    # A carer can't un-hide who asked.
    assert client("carer").patch(f"/church/help/requests/{private['id']}",
                                 json={"business_id": BIZ, "anonymous": False}).status_code == 403

    owner = _page("owner")
    assert _by(owner, private["id"])["who"] == "Marcus Reed"
    assert _by(owner, f"care-{YOUTH_ASK}")["who"] == "Marcus Reed"
    assert _by(owner, f"care-{YOUTH_ASK}")["pastors_only"] is True

    money = _page("treasurer")
    for r in money["requests"]:
        assert r["who"] is None and r["notes"] is None and r["contact_id"] is None, r
        assert all(g["note"] is None for g in r["given"])
    seen = _by(money, bill["id"])
    assert seen["approved_cents"] == 15000 and seen["given_cents"] == 15000 and seen["need"] == "bill"
    assert money["fund"]["given_month_cents"] == 15000
    assert money["me"] == {"view": "money", "approve": False, "settings": False}
    assert _decide("treasurer", private["id"]).status_code == 403, "amounts only: no yes without the story"
    assert _add("viewer").status_code == 403, "a viewer only reads"

    assert client("singer").get(f"/church/help?business_id={BIZ}").status_code == 403
    assert client("stranger").get(f"/church/help?business_id={BIZ}").status_code == 404
    # The books never carry a name or a story.
    exp = db.t["business_expenses"][0]
    said = " ".join(str(v) for v in exp.values())
    assert "Dana" not in said and "light bill" not in said.lower() and "July" not in said


# ─── The limit and the keepers ───────────────────────────────────────

def test_with_no_keeper_the_limit_alone_governs(db):
    ref = _add("carer").json()["request"]["id"]
    page = _page("carer")
    assert page["keeper"]["on"] is False and page["fund"]["gift_limit_cents"] == 15000
    assert _by(page, ref)["over_limit"] is True
    for name in ("carer", "owner", "admin"):
        got = _decide(name, ref)
        assert got.status_code == 403 and got.json()["detail"]["code"] == "over_limit", name
        assert "no keeper for Giving & money" in got.json()["detail"]["message"]
    asked = client("carer").post(f"/church/help/requests/{ref}/keeper", json={"business_id": BIZ})
    assert asked.status_code == 409 and asked.json()["detail"]["code"] == "over_limit"
    assert _decide("carer", ref, amount="150").json()["request"]["approved_cents"] == 15000, "up to the limit"
    assert _req(db, ref)["status"] == "approved"
    # Giving more than approved is approving more: refused above the limit.
    assert _give("carer", ref, amount="180", how="cash").json()["detail"]["code"] == "over_limit"
    assert db.t["church_help_given"] == [] and db.t["business_expenses"] == []


def test_above_the_limit_a_keeper_says_yes_the_owner_bound_too(db):
    _keeper(db, "treasurer")
    ref = _add("carer").json()["request"]["id"]
    assert _page("carer")["keeper"] == {"on": True, "mine": False, "open_until": None, "asked": None, "keepers": 1}
    for name in ("carer", "owner"):
        got = _decide(name, ref)
        assert got.status_code == 403 and got.json()["detail"]["code"] == "needs_keeper", name
    # The church keys' own ask: every keeper hears it, never who or the story.
    asked = client("carer").post(f"/church/help/requests/{ref}/keeper", json={"business_id": BIZ})
    assert asked.status_code == 200 and asked.json()["told"] == 1
    keepers, title, body = db.told[-1]
    assert keepers == [ID["treasurer"]] and "Giving & money" in title
    assert "$180" in body and "a bill" in body and "Dana" not in body and "light" not in body
    assert _page("carer")["keeper"]["asked"]["id"] == asked.json()["key"]["id"]
    assert _decide("carer", ref).status_code == 403, "an ask opens nothing until a keeper says yes"
    # The keeper's yes (in Areas) opens Giving & money to the asker for an hour.
    ck.answer(BIZ, PEOPLE["treasurer"], asked.json()["key"]["id"], True)
    assert _page("carer")["keeper"]["open_until"]
    got = _decide("carer", ref)
    assert got.status_code == 200 and got.json()["request"]["approved_cents"] == 18000
    assert _give("carer", ref, amount="180").status_code == 200
    assert _req(db, ref)["status"] == "helped"


def test_a_keeper_approves_here_and_a_code_opens_it_too(db):
    _keeper(db, "treasurer")
    _keeper(db, "admin")
    ref = _add("carer", amount="300").json()["request"]["id"]
    assert _page("admin")["keeper"]["mine"] is True
    assert _decide("admin", ref).status_code == 200, "a keeper who works care says yes here"
    other = _add("carer", amount="250", need="other").json()["request"]["id"]
    asked = client("carer").post(f"/church/help/requests/{other}/keeper", json={"business_id": BIZ}).json()
    code = re.search(r"code: (\d{6})", db.told[-1][2]).group(1)
    wrong = client("carer").post("/church/help/key-code", json={"business_id": BIZ, "key_id": asked["key"]["id"],
                                                                "code": "000000" if code != "000000" else "111111"})
    assert wrong.status_code == 400
    assert client("carer").post("/church/help/key-code", json={"business_id": BIZ, "key_id": asked["key"]["id"],
                                                               "code": code}).status_code == 200
    assert _decide("carer", other).status_code == 200
    # Raising the limit needs the same yes; lowering it doesn't.
    c = client("owner")
    raised = c.put("/church/help/settings", json={"business_id": BIZ, "gift_limit": "300"})
    assert raised.status_code == 403 and raised.json()["detail"]["code"] == "needs_keeper"
    assert c.put("/church/help/settings", json={"business_id": BIZ, "gift_limit": "100"}).json()["fund"]["gift_limit_cents"] == 10000
    assert client("admin").put("/church/help/settings",
                               json={"business_id": BIZ, "gift_limit": "300"}).json()["fund"]["gift_limit_cents"] == 30000
    assert client("carer").put("/church/help/settings", json={"business_id": BIZ, "gift_limit": "1"}).status_code == 403


# ─── Another church ──────────────────────────────────────────────────

def test_another_church_is_unreachable(db):
    theirs = _add("other_owner", biz=OTHER, contact_id=THEIR_PERSON, amount="40").json()["request"]
    assert _decide("owner", theirs["id"]).status_code == 404
    assert _give("owner", theirs["id"]).status_code == 404
    assert client("owner").patch(f"/church/help/requests/{theirs['id']}", json={"business_id": BIZ, "notes": "x"}).status_code == 404
    assert _decide("owner", f"care-{THEIR_ASK}").status_code == 404, "their member's ask isn't ours to adopt"
    assert _add("owner", contact_id=THEIR_PERSON).status_code == 400
    assert client("other_owner").get(f"/church/help?business_id={BIZ}").status_code == 404
    mine = _page("owner")
    assert all(r["id"] not in (theirs["id"], f"care-{THEIR_ASK}") for r in mine["requests"])
    assert _req(db, theirs["id"])["status"] == "new"
    given = _give("other_owner", theirs["id"], biz=OTHER, amount="40")
    assert given.status_code == 200
    assert client("owner").delete(f"/church/help/given/{db.t['church_help_given'][0]['id']}?business_id={BIZ}").status_code == 404
    assert _page("owner")["fund"]["given_month_cents"] == 0


# ─── Help given, the books, the fund ─────────────────────────────────

def test_help_given_goes_in_the_books_and_the_fund_adds_up(db):
    c = client("admin")
    saved = c.put("/church/help/settings", json={"business_id": BIZ, "fund": "Benevolence fund", "monthly_budget": "800"})
    assert saved.json()["fund"]["monthly_budget_cents"] == 80000
    bill = _add("carer").json()["request"]["id"]
    assert _decide("carer", bill, amount="150").status_code == 200
    got = _give("carer", bill)
    assert got.status_code == 200 and got.json()["in_books"] is True
    exp = db.t["business_expenses"][0]
    assert exp["amount"] == 150.0 and exp["category"] == "operating" and exp["subcategory"] == "Benevolence fund"
    assert exp["vendor"] == "Cleveland Electric" and exp["date"] == "2026-10-27" and exp["payment_method"] == "check"
    assert exp["description"] == "Help given from the Benevolence fund: a bill (a check)"
    assert db.t["church_help_given"][0]["expense_id"] == exp["id"]

    # Groceries last month for Dana again (one family), a ride for a walk-in.
    food = _add("carer", need="food", amount="", notes="Pantry").json()["request"]["id"]
    assert _give("carer", food, how="groceries", amount="60", given_on="2026-09-30", payee="").status_code == 200
    ride = _add("carer", need="ride", amount="", contact_id=None, name="Walk-in", source="walk_in").json()["request"]["id"]
    assert _give("carer", ride, how="ride", amount="", payee="").json()["in_books"] is False
    assert len(db.t["business_expenses"]) == 2, "a ride with no money isn't an expense"
    # Promised: approved, not given yet.
    promise = _add("carer", need="other", amount="100", contact_id=MARCUS).json()["request"]["id"]
    assert _decide("carer", promise).status_code == 200

    fund = _page("carer")["fund"]
    assert fund["fund"] == "Benevolence fund" and "Benevolence fund" in fund["funds"]
    assert fund["given_month_cents"] == 15000
    assert fund["promised_cents"] == 10000
    assert fund["left_cents"] == 80000 - 15000 - 10000
    assert fund["given_year_cents"] == 21000
    assert fund["families_year"] == 2, "Dana twice is one family; the walk-in is another"
    assert fund["waiting"] == 1, "the member's ask from the app"

    # Money is money with no amount → refused; cash needs an amount.
    assert _give("carer", promise, how="cash", amount="").status_code == 400
    # Giving more than approved, within the limit, approves it.
    assert _give("carer", promise, how="gift_card", amount="120", payee="Kroger").status_code == 200
    assert _req(db, promise)["approved_cents"] == 12000 and _req(db, promise)["status"] == "helped"

    # Closed books refuse, and nothing is saved.
    db.t["accounting_periods"].append({"id": "p1", "business_id": BIZ, "status": "closed", "period_type": "month",
                                       "period_start": "2026-09-01", "period_end": "2026-09-30"})
    late = _give("carer", food, how="groceries", amount="20", given_on="2026-09-15")
    assert late.status_code == 409 and late.json()["detail"]["code"] == "books_closed"
    assert len(db.t["church_help_given"]) == 4
    assert _give("carer", bill, given_on="2026-12-25").status_code == 400, "not before it's given"

    # Taking a record back takes its expense with it: the owner and admins.
    rec = next(g for g in db.t["church_help_given"] if g["request_id"] == bill)
    assert client("carer").delete(f"/church/help/given/{rec['id']}?business_id={BIZ}").status_code == 403
    back = c.delete(f"/church/help/given/{rec['id']}?business_id={BIZ}")
    assert back.status_code == 200 and back.json()["request"]["status"] == "approved"
    assert all(e["id"] != rec["expense_id"] for e in db.t["business_expenses"])


def test_decline_and_its_rules(db):
    ref = _add("carer", amount="40").json()["request"]["id"]
    assert _decide("viewer", ref, "declined").status_code == 403
    assert _decide("carer", ref, "declined").json()["request"]["status"] == "declined"
    assert _give("carer", ref, amount="40").status_code == 409
    assert _decide("carer", ref).status_code == 409
    given = _add("carer", amount="40").json()["request"]["id"]
    _give("carer", given, amount="40")
    assert _decide("carer", given, "declined").status_code == 409, "help was given already"


# ─── The member app's asks ───────────────────────────────────────────

def test_asks_from_the_member_app_show_up_and_become_one_request(db):
    page = _page("carer")
    app = [r for r in page["requests"] if r["source"] == "app"]
    assert [r["id"] for r in app] == [f"care-{ASK}"], "a help ask only: not prayer, a visit, a closed one or a youth's"
    ask = app[0]
    assert ask["need"] == "bill" and ask["notes"] == STORY and ask["who"] == "Dana Johnson"
    assert ask["status"] == "new" and ask["wants_call"] is True and ask["from_app"] is True
    assert ask["amount_cents"] is None, "the app's ask carries no amount: the office sets it"
    assert db.t["church_help_requests"] == [], "reading writes nothing"

    # Acting on it makes its own row, once, however many press at once.
    c = client("carer")
    assert c.patch(f"/church/help/requests/care-{ASK}", json={"business_id": BIZ, "amount": "120"}).status_code == 200
    assert _decide("carer", f"care-{ASK}").status_code == 200
    rows = [r for r in db.t["church_help_requests"] if r["care_request_id"] == ASK]
    assert len(rows) == 1 and rows[0]["source"] == "app" and rows[0]["approved_cents"] == 12000
    care = next(r for r in db.t["ministry_care_requests"] if r["id"] == ASK)
    assert care["status"] == "reviewed", "Prayer & care follows: approved is reviewed"
    page = _page("carer")
    assert [r["id"] for r in page["requests"] if r["source"] == "app"] == [rows[0]["id"]]
    assert _give("carer", rows[0]["id"], how="check", amount="120").status_code == 200
    assert care["status"] == "closed", "helped closes it in Prayer & care"
    # A youth's ask: the owner and admins act on it; anyone else finds nothing.
    assert _decide("carer", f"care-{YOUTH_ASK}").status_code == 404
    assert _decide("admin", f"care-{YOUTH_ASK}", amount="0").status_code == 200
    assert next(r for r in db.t["church_help_requests"] if r["care_request_id"] == YOUTH_ASK)["pastors_only"] is True
    assert _decide("owner", f"care-{VISIT}").status_code == 404, "a visit isn't a help request"
    assert _decide("owner", f"care-{PRAYER}").status_code == 404


def test_part_of_what_was_approved_leaves_the_rest_promised(db):
    _keeper(db, "admin")
    c = client("admin")
    c.put("/church/help/settings", json={"business_id": BIZ, "monthly_budget": "1000"})
    rent = _decide("admin", f"care-{ASK}", amount="300")
    assert rent.status_code == 200
    ref = rent.json()["request"]["id"]
    care = next(r for r in db.t["ministry_care_requests"] if r["id"] == ASK)
    part = _give("carer", ref, amount="100", how="cash")
    assert part.status_code == 200 and part.json()["request"]["status"] == "approved"
    assert _req(db, ref)["status"] == "approved", "$200 is still owed"
    assert care["status"] == "reviewed", "Prayer & care stays open until it's all given"
    fund = _page("carer")["fund"]
    assert fund["given_month_cents"] == 10000 and fund["promised_cents"] == 20000
    assert fund["left_cents"] == 100000 - 10000 - 20000
    rest = _give("carer", ref, amount="200")
    assert rest.json()["request"]["status"] == "helped" and care["status"] == "closed"
    # Taking part back leaves it approved, with that part promised again.
    rec = next(g for g in db.t["church_help_given"] if g["amount_cents"] == 20000)
    back = c.delete(f"/church/help/given/{rec['id']}?business_id={BIZ}").json()
    assert back["request"]["status"] == "approved" and back["books"] is True
    assert _page("carer")["fund"]["promised_cents"] == 20000


def test_nothing_is_written_for_an_ask_someone_cant_act_on(db):
    assert _decide("carer", f"care-{YOUTH_ASK}").status_code == 404
    assert _give("carer", f"care-{YOUTH_ASK}", how="ride", amount="").status_code == 404
    closed = _decide("owner", f"care-{CLOSED_ASK}")
    assert closed.status_code == 409, "it was closed in Prayer & care"
    assert db.t["church_help_requests"] == [], "no row for an ask nobody could act on here"


def test_a_take_back_whose_expense_wont_delete_says_so(db, monkeypatch):
    ref = _add("carer", amount="40").json()["request"]["id"]
    _give("carer", ref, amount="40", how="cash")
    rec = db.t["church_help_given"][0]
    real = db.delete
    monkeypatch.setattr(sb_clients, "sb_delete_as_service",
                        lambda path, **kw: False if path.startswith("/business_expenses") else real(path, **kw))
    got = client("admin").delete(f"/church/help/given/{rec['id']}?business_id={BIZ}").json()
    assert got["books"] is False and "still in the books" in got["message"]
    assert db.t["church_help_given"] == [], "the record is gone, and the answer says the expense isn't"

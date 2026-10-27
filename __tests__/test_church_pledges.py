"""The Giving door's office pages (church_pledges.py, church_recurring_gifts.py).
Kevin, 2026-10-27, "lets start building this": the office had no list of
recurring gifts, and pledges and campaigns didn't exist.

Pins:
  * only the owner, admins and the accountant see any of it; a member or
    another church's owner is refused, and status says false for them
  * another church's campaigns, pledges and recurring gifts never show
  * a campaign's progress counts only its fund's paid gifts inside its
    dates (the church's own days), net of refunds, per giver and in all
  * a pledge to a campaign that isn't this church's is refused
  * status is false when the switch is off, and pledges false (never a
    500) while the tables aren't there; the recurring list needs no table
  * the recurring list never carries card data
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_pledges as cp  # noqa: E402
import church_recurring_gifts as crg  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SHOP = "33333333-3333-4333-8333-333333333333"
OWNER_EMAIL = "kevin@solutionist.test"


def _user(n: int, email: str) -> AuthedUser:
    return AuthedUser(id=f"00000000-0000-4000-8000-{n:012d}", email=email, role="authenticated")


OWNER = _user(1, OWNER_EMAIL)            # owns BIZ, and is the platform owner
ADMIN = _user(2, "admin@lovecity.org")
CPA = _user(3, "cpa@books.test")
MEMBER = _user(4, "usher@lovecity.org")
STRANGER = _user(5, "pastor@other.org")  # owns OTHER
ANN, BEN, CAL, ZED = (f"c0000000-0000-4000-8000-{i:012d}" for i in (1, 2, 3, 9))
SETTINGS = {"giving": {"enabled": True, "funds": ["General", "Building", "Missions"]},
            "timezone": "America/New_York"}


class GivingDB(FakeDB):
    """The shared fake, plus what these reads use: quoted in-lists, an
    order, the embedded giver, and a table that isn't there yet (None)."""

    missing: set = set()

    def get(self, path, **kw):
        table = path.lstrip("/").split("?")[0]
        if table in self.missing:
            return None
        rows = super().get(path.replace("%22", ""), **kw)
        qs = path.split("?", 1)[1] if "?" in path else ""
        order = next((p.split("=", 1)[1] for p in qs.split("&") if p.startswith("order=")), "")
        if order:
            col, _, way = order.partition(".")
            rows.sort(key=lambda r: str(r.get(col) or ""), reverse=way.startswith("desc"))
        if "contacts(" in path:
            people = {c["id"]: c for c in self.t.get("contacts", [])}
            for r in rows:
                c = people.get(r.get("contact_id"))
                r["contacts"] = {"name": c["name"], "email": c.get("email")} if c else None
        return rows

    def post(self, path, body, prefer=None, **kw):
        table = path.lstrip("/").split("?")[0]
        if table in self.missing:
            return None
        if table == "church_pledges":
            body = {"recorded_at": datetime.now(timezone.utc).isoformat(), **body}
        return super().post(path, body, prefer=prefer, **kw)


@pytest.fixture
def db(monkeypatch):
    fake = GivingDB(
        businesses=[
            {"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER.id,
             "settings": SETTINGS, "stripe_account_id": "acct_lovecity"},
            {"id": OTHER, "name": "Other Church", "type": "ministry", "owner_id": STRANGER.id,
             "settings": SETTINGS, "stripe_account_id": "acct_other"},
            {"id": SHOP, "name": "Corner Barber", "type": "barber", "owner_id": OWNER.id, "settings": {}},
        ],
        business_users=[{"business_id": BIZ, "user_id": ADMIN.id, "role": "admin", "status": "active"},
                        {"business_id": BIZ, "user_id": MEMBER.id, "role": "member", "status": "active"}],
        business_collaborators=[{"business_id": BIZ, "user_id": CPA.id, "role": "accountant", "status": "active",
                                 "id": "collab-1"}],
        contacts=[{"id": ANN, "business_id": BIZ, "name": "Ann Avery", "email": "ann@example.com"},
                  {"id": BEN, "business_id": BIZ, "name": "Ben Brooks", "email": "ben@example.com"},
                  {"id": CAL, "business_id": BIZ, "name": "Cal Cole", "email": "cal@example.com"},
                  {"id": ZED, "business_id": OTHER, "name": "Zed Other", "email": "zed@other.org"}],
        church_campaigns=[], church_pledges=[], church_keepers=[], church_area_keys=[], invoices=[],
    )
    fake.missing = set()
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("CHURCH_PLEDGES", "on")
    monkeypatch.setenv("CHURCH_KEYS", "on")
    # The campaigns here run Nov-Dec 2026; read them from mid-January.
    monkeypatch.setattr(cp, "_now", lambda: datetime(2027, 1, 15, 17, 0, tzinfo=timezone.utc))
    crg._cache.clear()
    return fake


def _refused(fn, *args, **kw) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        fn(*args, **kw)
    return e.value


def _campaign(user=OWNER, biz=BIZ, **over):
    body = {"business_id": biz, "name": "Building fund", "goal_cents": 5_000_000, "fund": "Building",
            "starts_on": "2026-11-01", "ends_on": "2026-12-31", **over}
    return cp.create_campaign(body, user)["campaign"]


def _gift(db, contact, cents, fund, paid_at, refund=None, biz=BIZ):
    db.t["invoices"].append({
        "id": str(uuid.uuid4()), "business_id": biz, "invoice_number": f"GIVE-{uuid.uuid4()}", "is_gift": True,
        "status": "paid", "gift_fund": fund, "total": cents / 100, "paid_at": paid_at, "contact_id": contact,
        "refund_amount_cents": refund, "category": None, "notes": "", "updated_at": paid_at,
        "payment_method": "stripe"})


# ─── Who ──────────────────────────────────────────────────────────────

def test_owner_admin_and_accountant_see_it_and_status_says_so(db):
    for who in (OWNER, ADMIN, CPA):
        assert cp.status(BIZ, who) == {"enabled": True, "recurring": True, "pledges": True}, who.email
        assert cp.list_campaigns(BIZ, who)["funds"] == ["General", "Building", "Missions"]


def test_non_finance_logins_are_refused(db):
    c = _campaign()
    for who in (MEMBER, STRANGER):
        assert cp.status(BIZ, who) == {"enabled": False, "recurring": False, "pledges": False}, who.email
        assert _refused(cp.recurring, BIZ, user=who).status_code == 403
        assert _refused(cp.list_campaigns, BIZ, who).status_code == 403
        assert _refused(cp.list_pledges, BIZ, user=who).status_code == 403
        assert _refused(_campaign, who).status_code == 403
        assert _refused(cp.record_pledge, {"business_id": BIZ, "campaign_id": c["id"], "contact_id": ANN,
                                           "total_cents": 1000}, who).status_code == 403
    assert db.t["church_pledges"] == []


def test_the_switch_off_hides_everything_and_owner_means_the_platform_owner(db, monkeypatch):
    monkeypatch.setenv("CHURCH_PLEDGES", "off")
    assert cp.status(BIZ, OWNER)["enabled"] is False
    assert _refused(cp.list_campaigns, BIZ, OWNER).status_code == 404
    monkeypatch.setenv("CHURCH_PLEDGES", "owner")
    assert cp.status(BIZ, OWNER)["enabled"] is True
    assert cp.status(BIZ, ADMIN)["enabled"] is False, "owner mode is the platform owner only"
    assert _refused(cp.recurring, BIZ, user=ADMIN).status_code == 404
    monkeypatch.delenv("CHURCH_PLEDGES")
    assert cp.mode() == "owner", "owner until a Thursday"


def test_status_says_pledges_false_while_the_tables_are_missing_and_nothing_500s(db, monkeypatch):
    db.missing = {"church_campaigns", "church_pledges"}
    assert cp.status(BIZ, OWNER) == {"enabled": True, "recurring": True, "pledges": False}
    for fn, args in ((cp.list_campaigns, (BIZ, OWNER)), (cp.list_pledges, (BIZ, None, OWNER)),
                     (cp.create_campaign, ({"business_id": BIZ}, OWNER))):
        assert _refused(fn, *args).status_code == 409
    # The recurring list needs no table.
    monkeypatch.setattr(crg, "_stripe_get", lambda path, account, params: {"data": [], "has_more": False})
    assert cp.recurring(BIZ, user=OWNER)["gifts"] == []


def test_only_churches(db):
    assert cp.status(SHOP, OWNER)["enabled"] is False
    assert _refused(cp.list_campaigns, SHOP, OWNER).status_code == 404
    assert cp.status("not-a-uuid", OWNER)["enabled"] is False


# ─── Campaigns ────────────────────────────────────────────────────────

def test_a_campaign_takes_one_of_the_church_funds_and_dates_that_run_forward(db):
    c = _campaign(fund="building fund")
    assert c["fund"] == "Building" and c["created_by"] == OWNER.id
    assert _refused(_campaign, fund="Roof").status_code == 400
    assert _refused(_campaign, fund="").status_code == 400
    assert _refused(_campaign, starts_on="2026-12-01", ends_on="2026-11-01").status_code == 400
    assert _refused(_campaign, goal_cents=0).status_code == 400
    assert _refused(_campaign, goal_cents=12.5).status_code == 400
    assert _refused(_campaign, name="  ").status_code == 400
    edited = cp.edit_campaign(c["id"], {"business_id": BIZ, "goal_cents": 6_000_000}, ADMIN)["campaign"]
    assert edited["goal_cents"] == 6_000_000
    assert _refused(cp.edit_campaign, c["id"], {"business_id": BIZ, "ends_on": "2026-10-01"}, ADMIN).status_code == 400


def test_another_churchs_campaigns_and_pledges_are_invisible(db):
    mine = _campaign()
    theirs = _campaign(STRANGER, OTHER, name="Their roof")
    cp.record_pledge({"business_id": OTHER, "campaign_id": theirs["id"], "contact_id": ZED, "total_cents": 9_999}, STRANGER)
    assert [c["name"] for c in cp.list_campaigns(BIZ, OWNER)["campaigns"]] == ["Building fund"]
    assert cp.list_pledges(BIZ, user=OWNER)["pledges"] == []
    # Their campaign can't be pledged to, edited or read from here.
    assert _refused(cp.record_pledge, {"business_id": BIZ, "campaign_id": theirs["id"], "contact_id": ANN,
                                       "total_cents": 1000}, OWNER).status_code == 404
    assert _refused(cp.edit_campaign, theirs["id"], {"business_id": BIZ, "name": "Mine now"}, OWNER).status_code == 404
    assert _refused(cp.list_pledges, BIZ, theirs["id"], OWNER).status_code == 404
    # Nor can their giver be named on our pledge card.
    assert _refused(cp.record_pledge, {"business_id": BIZ, "campaign_id": mine["id"], "contact_id": ZED,
                                       "total_cents": 1000}, OWNER).status_code == 400
    # Nor their pledge removed through our church.
    their_pledge = db.t["church_pledges"][0]["id"]
    assert _refused(cp.remove_pledge, their_pledge, BIZ, OWNER).status_code == 404
    assert len(db.t["church_pledges"]) == 1


# ─── Pledges ──────────────────────────────────────────────────────────

def test_a_pledge_to_a_missing_campaign_is_refused(db):
    for cid in (str(uuid.uuid4()), "nope"):
        e = _refused(cp.record_pledge, {"business_id": BIZ, "campaign_id": cid, "contact_id": ANN, "total_cents": 1000}, OWNER)
        assert e.status_code in (400, 404), cid
    assert db.t["church_pledges"] == []


def test_a_pledge_is_a_total_or_per_period_times_periods(db):
    c = _campaign()
    a = cp.record_pledge({"business_id": BIZ, "campaign_id": c["id"], "contact_id": ANN,
                          "per_period_cents": 2_500, "period": "weekly", "periods": 52, "note": "card 14"}, CPA)
    row = next(p for p in db.t["church_pledges"] if p["id"] == a["id"])
    assert (row["total_cents"], row["per_period_cents"], row["period"], row["periods"]) == (130_000, 2_500, "weekly", 52)
    assert row["recorded_by"] == CPA.id and row["note"] == "card 14"
    cp.record_pledge({"business_id": BIZ, "campaign_id": c["id"], "contact_id": BEN, "total_cents": 100_000}, OWNER)
    assert _refused(cp.record_pledge, {"business_id": BIZ, "campaign_id": c["id"], "contact_id": CAL,
                                       "per_period_cents": 100, "period": "daily", "periods": 3}, OWNER).status_code == 400
    assert _refused(cp.record_pledge, {"business_id": BIZ, "campaign_id": c["id"], "contact_id": CAL,
                                       "per_period_cents": 100, "period": "monthly", "periods": 0}, OWNER).status_code == 400
    # One per giver per campaign.
    assert _refused(cp.record_pledge, {"business_id": BIZ, "campaign_id": c["id"], "contact_id": ANN,
                                       "total_cents": 5}, OWNER).status_code == 409
    # A retried save lands once.
    rid = str(uuid.uuid4())
    first = cp.record_pledge({"business_id": BIZ, "campaign_id": c["id"], "contact_id": CAL, "total_cents": 700, "request_id": rid}, OWNER)
    again = cp.record_pledge({"business_id": BIZ, "campaign_id": c["id"], "contact_id": CAL, "total_cents": 700, "request_id": rid}, OWNER)
    assert again == {"ok": True, "id": first["id"], "already": True}
    assert len(db.t["church_pledges"]) == 3
    assert cp.remove_pledge(first["id"], BIZ, ADMIN) == {"ok": True}
    assert len(db.t["church_pledges"]) == 2


# ─── Progress ─────────────────────────────────────────────────────────

def test_progress_counts_only_the_funds_gifts_inside_the_dates_net_of_refunds(db):
    c = _campaign(goal_cents=1_000_000)
    cp.record_pledge({"business_id": BIZ, "campaign_id": c["id"], "contact_id": ANN, "total_cents": 50_000}, OWNER)
    cp.record_pledge({"business_id": BIZ, "campaign_id": c["id"], "contact_id": BEN, "total_cents": 10_000}, OWNER)
    _gift(db, ANN, 20_000, "Building", "2026-11-08T15:00:00Z")                 # counts
    _gift(db, ANN, 5_000, "Building Fund", "2026-12-31T23:00:00Z")             # counts: same fund, last day (Eastern)
    _gift(db, ANN, 9_000, "Building", "2026-11-01T03:00:00Z")                  # Oct 31 in Eastern: before the start
    _gift(db, ANN, 9_000, "Building", "2027-01-01T06:00:00Z")                  # after the end
    _gift(db, ANN, 9_000, "General", "2026-11-15T15:00:00Z")                   # another fund
    _gift(db, BEN, 15_000, "building", "2026-12-01T15:00:00Z", refund=5_000)   # counts 100.00
    _gift(db, BEN, 4_000, "Building", "2026-12-02T15:00:00Z", refund=4_000)    # refunded whole
    _gift(db, None, 3_000, "Building", "2026-12-03T15:00:00Z")                 # an unattributed gift counts for the campaign
    _gift(db, ZED, 70_000, "Building", "2026-12-04T15:00:00Z", biz=OTHER)      # another church
    camp = cp.list_campaigns(BIZ, OWNER)["campaigns"][0]
    assert camp["given_cents"] == 20_000 + 5_000 + 10_000 + 3_000
    assert camp["pledged_cents"] == 60_000 and camp["pledges"] == 2 and camp["givers"] == 2
    assert camp["pledged_given_cents"] == 25_000 + 10_000
    assert camp["goal_percent"] == 4
    assert "rows" not in camp, "totals only on the campaigns list"
    rows = {p["giver"]: p for p in cp.list_pledges(BIZ, c["id"], OWNER)["pledges"]}
    assert (rows["Ann Avery"]["given_cents"], rows["Ann Avery"]["left_cents"], rows["Ann Avery"]["percent"]) == (25_000, 25_000, 50)
    assert (rows["Ben Brooks"]["given_cents"], rows["Ben Brooks"]["left_cents"], rows["Ben Brooks"]["percent"]) == (10_000, 0, 100)


def test_progress_by_hand_matches_the_route():
    tz = cp._tz({"settings": SETTINGS})
    camp = {"fund": "Missions", "starts_on": "2026-01-01", "ends_on": "2026-01-31", "goal_cents": 100}
    gifts = [{"gift_fund": "Missions Fund", "paid_at": "2026-01-15T12:00:00Z", "total": 0.6, "contact_id": "a"},
             {"gift_fund": "Missions", "paid_at": "2026-01-16T12:00:00Z", "total": 1.0, "refund_amount_cents": 100, "contact_id": "a"},
             {"gift_fund": None, "paid_at": "2026-01-17T12:00:00Z", "total": 5.0, "contact_id": "a"}]
    out = cp.progress(camp, [{"contact_id": "a", "total_cents": 50}], gifts, tz)
    assert out["given_cents"] == 60 and out["goal_percent"] == 60
    assert out["rows"][0]["percent"] == 100 and out["rows"][0]["left_cents"] == 0
    assert cp.fund_key(None) == cp.fund_key("General Fund") == "general"


def test_gifts_are_read_only_for_the_days_the_campaigns_have_run():
    today = date(2027, 1, 15)
    camps = [{"starts_on": "2020-01-01", "ends_on": "2020-03-31"},   # long over
             {"starts_on": "2026-11-01", "ends_on": "2027-06-30"},   # running: up to today
             {"starts_on": "2026-12-01", "ends_on": "2027-01-10"},   # overlaps the running one
             {"starts_on": "2027-03-01", "ends_on": "2027-04-30"}]   # not started: no gifts yet
    assert cp.windows(camps, today) == [(date(2019, 12, 31), date(2020, 4, 2)), (date(2026, 10, 31), date(2027, 1, 17))]
    assert cp.windows([camps[3]], today) == []


def test_a_campaign_that_has_not_started_reads_no_gifts(db, monkeypatch):
    _campaign(starts_on="2027-03-01", ends_on="2027-04-30")
    import giving_records
    monkeypatch.setattr(giving_records, "read_gifts", lambda *a, **k: pytest.fail("read gifts for a campaign that hasn't started"))
    camp = cp.list_campaigns(BIZ, OWNER)["campaigns"][0]
    assert (camp["phase"], camp["given_cents"]) == ("upcoming", 0)


# ─── The keys ─────────────────────────────────────────────────────────

def test_who_gave_what_sits_behind_the_giving_keeper_while_totals_stay_open(db, monkeypatch):
    _campaign()
    db.t["church_keepers"].append({"business_id": BIZ, "area": "giving_money", "user_id": CPA.id,
                                   "starts_at": "2026-01-01T00:00:00+00:00", "ends_at": None})
    monkeypatch.setattr(crg, "_stripe_get", lambda path, account, params: {"data": [], "has_more": False})
    for fn, args in ((cp.recurring, (BIZ,)), (cp.list_pledges, (BIZ,))):
        e = _refused(fn, *args, user=OWNER)
        assert e.status_code == 403 and e.detail["code"] == "area_locked"
    assert cp.list_campaigns(BIZ, OWNER)["campaigns"][0]["name"] == "Building fund"
    assert cp.recurring(BIZ, user=CPA)["gifts"] == [], "the keeper is in"


def test_the_routes_are_mounted_under_church_giving():
    paths = {r.path for r in cp.router.routes}
    assert {"/church/giving/status", "/church/giving/recurring", "/church/giving/campaigns",
            "/church/giving/campaigns/{campaign_id}", "/church/giving/pledges",
            "/church/giving/pledges/{pledge_id}"} <= paths
    src = open(os.path.join(ROOT, "kmj_intake_automation.py"), encoding="utf-8").read()
    assert src.index("church_pledges_router") < src.rindex("app.include_router(public_site_router)")

# __tests__/test_churchsavvy_billing.py
#
# What a church on ChurchSavvy alone has paid for (churchsavvy_billing.py).
# Pins:
#   * off (the default) holds nobody: every route opens as before, and
#     nothing about the plan is even read
#   * on, a church on ChurchSavvy alone opens only its plan's parts: the
#     screens (every worship route) for cs_screens, Planning for
#     cs_planning, both for cs_both, by subscription or by comp; the rest
#     answers 402 churchsavvy_plan, and the status reads every plan uses
#     still answer (the app needs them to show Choose your plan)
#   * a Solutionist church is never held; owner mode holds only the
#     platform owner
#   * checkout: a ChurchSavvy plan is its own price or nothing (never the
#     default Professional price), only for a church on ChurchSavvy alone,
#     only once the switch opens it, never a second subscription, no
#     promotion-code box, and back to ChurchSavvy's Plan and billing
#   * changing plan moves the one subscription item to the new price
#   * the serving sweep leaves out a church whose plan hasn't got Planning
#   * the catalog's amounts are the ones the page shows ($20 / $15 / $29)

import asyncio
import pathlib
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import churchsavvy_billing as csb  # noqa: E402
import feature_gates  # noqa: E402
import sb_clients  # noqa: E402
import stripe_billing as sb  # noqa: E402
import sunday_order  # noqa: E402
import sunday_planning  # noqa: E402
import sunday_serving_alerts as ssa  # noqa: E402
import worship_router as wr  # noqa: E402
import worship_team as wt  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_worship_team import BIZ, FakeDb, OWNER_EMAIL  # noqa: E402

PEOPLE = {
    "owner": AuthedUser(id="u-owner", email="pastor@lovecity.org", role="authenticated"),
    "kevin": AuthedUser(id="u-kevin", email=OWNER_EMAIL, role="authenticated"),
    "stranger": AuthedUser(id="u-stranger", email="who@else.org", role="authenticated"),
}
SEATS = {("u-owner", BIZ): "owner", ("u-kevin", BIZ): "admin"}
PRICES = {"CS_SCREENS": "price_cs_screens", "CS_PLANNING": "price_cs_planning", "CS_BOTH": "price_cs_both"}


@pytest.fixture
def api(monkeypatch):
    db = FakeDb()
    db.t["businesses"][0].update({"type": "ministry", "settings": {"churchsavvy_only": True}})
    reads = []

    def get(path, **kw):
        reads.append(path)
        return db.get(path, **kw)

    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    monkeypatch.delenv("CHURCHSAVVY_BILLING", raising=False)
    for k, v in PRICES.items():
        monkeypatch.setenv(f"STRIPE_PRICE_ID_{k}", v)
    monkeypatch.setattr(wt, "role_of", lambda biz, uid: SEATS.get((uid, biz)))
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    for r in (wt.router, wr.router, sunday_planning.router, sunday_order.router, csb.router):
        app.include_router(r)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    return db, as_, reads


def church(db):
    return db.t["businesses"][0]


def songs(as_, who="owner"):
    return as_(who).get(f"/worship/songs?business_id={BIZ}")


def teams(as_, who="owner"):
    return as_(who).get(f"/planning/teams?business_id={BIZ}")


def held_part(r):
    assert r.status_code == 402, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "churchsavvy_plan"
    return detail["part"]


def test_off_holds_nobody_and_reads_nothing(api):
    db, as_, reads = api
    assert songs(as_).status_code == 200
    assert teams(as_).status_code == 200
    assert csb.mode() == "off"
    # The plan is never read while the switch is off: no extra businesses read per request.
    reads.clear()
    csb.require_part(BIZ, "screens", PEOPLE["owner"])
    assert reads == []
    s = as_("owner").get(f"/churchsavvy-billing/status?business_id={BIZ}").json()
    assert s["standalone"] is True and s["held"] is False and s["checkout_open"] is False
    assert [p["cents"] for p in s["plans"]] == [2000, 1500, 2900]


def test_on_opens_only_the_plans_parts(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "on")
    # No plan yet: both parts held, the reads every plan shares still answer.
    assert held_part(songs(as_)) == "screens"
    assert held_part(teams(as_)) == "planning"
    assert as_("owner").get(f"/worship/status?business_id={BIZ}").status_code == 200
    assert as_("owner").get(f"/planning/status?business_id={BIZ}").status_code == 200
    s = as_("owner").get(f"/churchsavvy-billing/status?business_id={BIZ}").json()
    assert s["held"] is True and s["parts"] == [] and s["plan"] is None and s["checkout_open"] is True
    # Planning by subscription.
    church(db).update({"subscription_status": "active", "subscription_plan": "price_cs_planning"})
    assert teams(as_).status_code == 200
    assert held_part(songs(as_)) == "screens"
    # The booth's who's-on reads on any plan.
    church(db).update({"subscription_status": "active", "subscription_plan": "price_cs_screens"})
    assert songs(as_).status_code == 200
    assert held_part(teams(as_)) == "planning"
    assert as_("owner").get(f"/planning/today?business_id={BIZ}").status_code != 402
    # A lapsed subscription opens nothing again.
    church(db).update({"subscription_status": "canceled"})
    assert held_part(songs(as_)) == "screens"
    # Both, by the owner's comp (Mission Control), with no subscription at all.
    church(db).update({"comp_tier": "cs_both"})
    assert songs(as_).status_code == 200 and teams(as_).status_code == 200
    s = as_("owner").get(f"/churchsavvy-billing/status?business_id={BIZ}").json()
    assert s["plan"] == "cs_both" and s["comped"] is True and s["parts"] == ["planning", "screens"]
    # Writes are held the same way as reads.
    church(db).update({"comp_tier": "cs_screens"})
    r = as_("owner").post("/planning/teams", json={"business_id": BIZ, "name": "Greeters"})
    assert held_part(r) == "planning"
    # A stranger is still a stranger, never told about the plan.
    assert songs(as_, "stranger").status_code == 404


def test_a_solutionist_church_is_never_held(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "on")
    church(db)["settings"] = {}
    assert songs(as_).status_code == 200 and teams(as_).status_code == 200
    s = as_("owner").get(f"/churchsavvy-billing/status?business_id={BIZ}").json()
    assert s["standalone"] is False and s["held"] is False and s["parts"] == ["planning", "screens"]


def test_owner_mode_holds_only_the_platform_owner(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "owner")
    assert songs(as_, "owner").status_code == 200
    assert held_part(songs(as_, "kevin")) == "screens"
    assert csb.checkout_open(PEOPLE["kevin"]) and not csb.checkout_open(PEOPLE["owner"])
    # What the status tells each of them matches.
    status = lambda who: as_(who).get(f"/churchsavvy-billing/status?business_id={BIZ}").json()
    assert status("owner")["held"] is False and status("owner")["checkout_open"] is False
    assert status("kevin")["held"] is True and status("kevin")["checkout_open"] is True


# ─── checkout, the portal, changing plan ─────────────────────────────


@pytest.fixture
def stripe(api, monkeypatch):
    db, _, _ = api
    posted, fetched = [], {}

    async def stripe_post(path, data):
        posted.append((path, data))
        if path.startswith("/subscriptions/"):
            return {"id": path.rsplit("/", 1)[1], "status": "active", "cancel_at_period_end": False,
                    "items": {"data": [{"id": "si_1", "price": {"id": data["items"][0]["price"]}}]}}
        return {"id": "cs_test_x", "url": "https://checkout.stripe.test/x"}

    async def stripe_get(path, params):
        return fetched[path]

    async def load(bid):
        return dict(church(db), stripe_customer_id="cus_1")

    async def patch(bid, body, **_):
        church(db).update(body)

    monkeypatch.setattr(sb, "_stripe_post", stripe_post)
    monkeypatch.setattr(sb, "_stripe_get", stripe_get)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_patch_business", patch)
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "on")
    return posted, fetched


def checkout(plan, user="owner"):
    return asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id=BIZ, plan=plan), user=PEOPLE[user]))


def refused(fn):
    with pytest.raises(HTTPException) as e:
        fn()
    return e.value.status_code, str(e.value.detail)


def test_checkout_for_a_churchsavvy_plan(api, stripe, monkeypatch):
    db, _, _ = api
    posted, _ = stripe
    out = checkout("cs_planning")
    assert out["url"].startswith("https://checkout.stripe.test/")
    path, data = posted[-1]
    assert path == "/checkout/sessions"
    assert data["line_items"] == [{"price": "price_cs_planning", "quantity": 1}]
    assert data["allow_promotion_codes"] is False
    assert data["success_url"].endswith("/churchsavvy/setup/billing?paid=1")
    assert data["cancel_url"].endswith("/churchsavvy/setup/billing")
    # Its own address once it has one.
    monkeypatch.setenv("CHURCHSAVVY_APP_URL", "https://app.churchsavvy.test/")
    checkout("cs_both")
    assert posted[-1][1]["success_url"] == "https://app.churchsavvy.test/setup/billing?paid=1"


def test_checkout_refusals(api, stripe, monkeypatch):
    db, _, _ = api
    posted, _ = stripe
    # Its own price or nothing: never the default (Professional) price.
    monkeypatch.delenv("STRIPE_PRICE_ID_CS_SCREENS")
    monkeypatch.setenv("STRIPE_PRICE_ID_DEFAULT", "price_pro_default")
    assert refused(lambda: checkout("cs_screens"))[0] == 409
    # Closed while the switch is off; owner mode opens it to the owner alone.
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "off")
    assert refused(lambda: checkout("cs_planning")) == (409, "ChurchSavvy's plans aren't open yet.")
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "owner")
    church(db)["owner_id"] = "u-kevin"
    checkout("cs_planning", "kevin")
    church(db)["owner_id"] = "u-owner"
    assert refused(lambda: checkout("cs_planning"))[0] == 409
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "on")
    # A Solutionist church has it already.
    church(db)["settings"] = {}
    assert "through Solutionist" in refused(lambda: checkout("cs_planning"))[1]
    church(db)["settings"] = {"churchsavvy_only": True}
    # Never a second subscription.
    church(db).update({"stripe_subscription_id": "sub_1", "subscription_status": "active"})
    assert "already has a plan" in refused(lambda: checkout("cs_both"))[1]
    # Only the owner buys.
    church(db).update({"stripe_subscription_id": None, "subscription_status": None})
    assert refused(lambda: checkout("cs_both", "kevin"))[0] == 403
    # A raw ChurchSavvy price id is held to the same rules.
    church(db)["settings"] = {}
    with pytest.raises(HTTPException):
        asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id=BIZ, price_id="price_cs_both"), user=PEOPLE["owner"]))
    assert all(p != "/checkout/sessions" or d["line_items"][0]["price"] != "price_cs_both" for p, d in posted[1:])


def test_the_portal_comes_back_to_churchsavvy(api, stripe, monkeypatch):
    db, _, _ = api
    posted, _ = stripe
    import ledger_unlock
    monkeypatch.setattr(ledger_unlock, "require_unlock", lambda *a, **k: None)
    asyncio.run(sb.create_portal(sb.PortalBody(business_id=BIZ), request=None, user=PEOPLE["owner"]))
    assert posted[-1][1]["return_url"].endswith("/churchsavvy/setup/billing")
    church(db)["settings"] = {}
    asyncio.run(sb.create_portal(sb.PortalBody(business_id=BIZ), request=None, user=PEOPLE["owner"]))
    assert posted[-1][1]["return_url"] == sb._portal_return_url()


def test_changing_plan_moves_the_one_item(api, stripe):
    db, as_, _ = api
    posted, fetched = stripe
    church(db).update({"stripe_subscription_id": "sub_1", "subscription_status": "active",
                       "subscription_plan": "price_cs_planning"})
    fetched["/subscriptions/sub_1"] = {"items": {"data": [{"id": "si_1", "price": {"id": "price_cs_planning"}}]}}
    r = as_("owner").post("/churchsavvy-billing/change", json={"business_id": BIZ, "plan": "cs_both"})
    assert r.status_code == 200 and r.json() == {"plan": "cs_both", "plan_name": "ChurchSavvy and Planning", "changed": True}
    path, data = posted[-1]
    assert path == "/subscriptions/sub_1" and data["items"] == [{"id": "si_1", "price": "price_cs_both"}]
    assert data["proration_behavior"] == "create_prorations"
    assert church(db)["subscription_plan"] == "price_cs_both" and church(db)["tier"] == "cs_both"
    # The same plan again changes nothing.
    fetched["/subscriptions/sub_1"] = {"items": {"data": [{"id": "si_1", "price": {"id": "price_cs_both"}}]}}
    n = len(posted)
    assert as_("owner").post("/churchsavvy-billing/change", json={"business_id": BIZ, "plan": "cs_both"}).json()["changed"] is False
    assert len(posted) == n
    # Never another kind of subscription, never a made-up plan, never someone else's church.
    fetched["/subscriptions/sub_1"] = {"items": {"data": [{"id": "si_1", "price": {"id": "price_other"}}]}}
    assert as_("owner").post("/churchsavvy-billing/change", json={"business_id": BIZ, "plan": "cs_screens"}).status_code == 409
    assert as_("owner").post("/churchsavvy-billing/change", json={"business_id": BIZ, "plan": "professional"}).status_code == 400
    assert as_("kevin").post("/churchsavvy-billing/change", json={"business_id": BIZ, "plan": "cs_screens"}).status_code == 403
    # Without a plan to change, choose one first.
    church(db).update({"stripe_subscription_id": None})
    assert as_("owner").post("/churchsavvy-billing/change", json={"business_id": BIZ, "plan": "cs_screens"}).status_code == 409


def test_receipts_are_the_owners(api, stripe):
    db, as_, _ = api
    _, fetched = stripe
    fetched["/invoices"] = {"data": [
        {"status": "paid", "created": 1792800000, "amount_paid": 2900, "amount_due": 2900,
         "hosted_invoice_url": "https://invoice.stripe.test/1",
         "lines": {"data": [{"price": {"id": "price_cs_both"}}]}},
        {"status": "open", "created": 1790200000, "amount_paid": 0, "amount_due": 1500,
         "hosted_invoice_url": "https://invoice.stripe.test/2",
         "lines": {"data": [{"price": {"id": "price_cs_planning"}}]}},
        {"status": "draft", "created": 1790100000, "amount_due": 2000, "lines": {"data": []}},
    ]}
    j = as_("owner").get(f"/churchsavvy-billing/receipts?business_id={BIZ}").json()["receipts"]
    assert [(r["for"], r["cents"], r["status"]) for r in j] == [("Both, one month", 2900, "paid"),
                                                              ("Planning, one month", 1500, "due")]
    assert j[0]["url"] == "https://invoice.stripe.test/1" and j[0]["date"].startswith("2026-")
    assert as_("kevin").get(f"/churchsavvy-billing/receipts?business_id={BIZ}").status_code == 403


# ─── the sweep, the catalog ──────────────────────────────────────────


def test_the_sweep_skips_a_church_without_planning(monkeypatch):
    rows = [{"id": "a", "settings": {"churchsavvy_only": True}},
            {"id": "b", "settings": {"churchsavvy_only": True}, "comp_tier": "cs_planning"},
            {"id": "c", "settings": {}}]
    asked = []

    def get(path, **_):
        asked.append(path)
        return [dict(r) for r in rows]

    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.delenv("CHURCHSAVVY_BILLING", raising=False)
    assert sorted(b["id"] for b in ssa._churches()) == ["a", "b", "c"]
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "on")
    assert sorted(b["id"] for b in ssa._churches()) == ["b", "c"]
    assert all("comp_tier" in p and "subscription_plan" in p for p in asked)
    # Owner mode rehearses in the app only.
    monkeypatch.setenv("CHURCHSAVVY_BILLING", "owner")
    assert sorted(b["id"] for b in ssa._churches()) == ["a", "b", "c"]


def test_the_catalog_charges_what_the_page_shows():
    catalog = {env: (amount, interval) for env, _lk, _n, amount, interval in sb.BOOTSTRAP_CATALOG}
    for plan in feature_gates.CHURCHSAVVY_PLANS:
        env = f"STRIPE_PRICE_ID_{plan.upper()}"
        assert catalog[env] == (csb.PRICES[plan], "month")
        assert feature_gates.PRICE_ENV_TO_PLAN[plan.upper()] == plan
    assert (csb.PRICES["cs_screens"], csb.PRICES["cs_planning"], csb.PRICES["cs_both"]) == (2000, 1500, 2900)
    # A ChurchSavvy plan carries none of Solutionist's features.
    assert all(feature_gates.plan_features(p) == frozenset() for p in feature_gates.CHURCHSAVVY_PLANS)

"""
test_member_portal_gifts.py — a giver changes, pauses or stops their own
recurring gift from /my/gifts.

The gift is a subscription on the church's OWN Stripe account; nothing
here stores it. So the tests pin who may touch one (the signed-in
member's email, gifts to THIS church only, re-checked on every action),
that the owner's preview never writes, and the exact Stripe calls.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import member_portal_church as mpc
import member_portal_gifts as G

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
ACCT = "acct_love"
EMAIL = "ruth@example.com"


def _sub(sid, *, biz=BIZ, fund="General", cents=5000, interval="month", count=1,
         status="active", fee=0, paused=False, kind="gift"):
    items = [{"id": f"si_{sid}_0", "quantity": 1, "current_period_end": 1792000000,
              "price": {"unit_amount": cents, "currency": "usd", "product": f"prod_{sid}",
                        "recurring": {"interval": interval, "interval_count": count}}}]
    if fee:
        items.append({"id": f"si_{sid}_1", "quantity": 1,
                      "price": {"unit_amount": fee, "currency": "usd", "product": f"prod_fee_{sid}",
                                "recurring": {"interval": interval, "interval_count": count}}})
    return {"id": sid, "customer": "cus_1", "status": status,
            "pause_collection": {"behavior": "void"} if paused else None,
            "metadata": {"source_type": kind, "business_id": biz, "fund": fund},
            "items": {"data": items}}


class FakeStripe:
    def __init__(self, subs, customers=None, fail=()):
        self.subs = subs
        self.customers = customers if customers is not None else [{"id": "cus_1", "email": EMAIL}]
        self.fail = set(fail)
        self.calls = []

    async def __call__(self, method, path, account, *, data=None, params=None):
        self.calls.append((method, path, account, dict(data or {}), dict(params or {})))
        key = (method, path.split("/")[1])
        if key in self.fail or path in self.fail:
            return 500, {}
        if method == "GET" and path == "/customers":
            return 200, {"data": self.customers}
        if method == "GET" and path == "/subscriptions":
            return 200, {"data": self.subs}
        if path == "/billing_portal/configurations":
            return 200, {"id": "bpc_1"}
        if path == "/billing_portal/sessions":
            return 200, {"url": "https://billing.stripe.com/p/session_x"}
        return 200, {"id": path.split("/")[-1]}


@pytest.fixture
def stripe(monkeypatch):
    def install(subs, **kw):
        f = FakeStripe(subs, **kw)
        monkeypatch.setattr(G, "_stripe", f)
        return f
    return install


def _biz(**over):
    b = {"id": BIZ, "name": "Love City Church", "stripe_account_id": ACCT, "type": "church",
         "settings": {"giving": {"enabled": True}}}
    b.update(over)
    return b


def run(x):
    return asyncio.run(x)


# ─── finding the member's gifts ──────────────────────────────────────

def test_only_this_churchs_live_gifts_for_this_email(stripe):
    f = stripe([_sub("sub_mine001"), _sub("sub_other001", biz=OTHER), _sub("sub_order001", kind="order"),
                _sub("sub_gone001", status="canceled"), _sub("sub_week001", interval="week", count=2, cents=2500)])
    out = run(G.recurring_gifts(_biz(), "Ruth@Example.com "))
    assert [g["id"] for g in out] == ["sub_mine001", "sub_week001"]
    assert out[1]["every"] == "every 2 weeks" and out[1]["gift_cents"] == 2500
    assert all(c[2] == ACCT for c in f.calls)                     # the church's own account
    assert f.calls[0][4] == {"email": EMAIL, "limit": 10}


def test_a_customer_whose_email_only_resembles_is_ignored(stripe):
    stripe([_sub("sub_mine001")], customers=[{"id": "cus_1", "email": "RUTH@example.com.evil"}])
    assert run(G.recurring_gifts(_biz(), EMAIL)) == []


def test_no_email_or_no_stripe_is_none_found_not_an_error(stripe):
    f = stripe([_sub("sub_mine001")])
    assert run(G.recurring_gifts(_biz(), "")) == []
    assert run(G.recurring_gifts(_biz(stripe_account_id=None), EMAIL)) == []
    assert f.calls == []


def test_stripe_failing_is_none(stripe):
    stripe([_sub("sub_mine001")], fail={("GET", "subscriptions")})
    assert run(G.recurring_gifts(_biz(), EMAIL)) is None


# ─── the actions ─────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    church = {"business": _biz(), "site": {"slug": "love-city-church"}}
    me = {"id": "c1", "name": "Ruth", "email": EMAIL}
    state = {"unavailable": False, "me": me, "allowed": True}

    async def signed_in(request):
        return church, (None if state["unavailable"] else state["me"]), state["unavailable"]

    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda c, m: state["allowed"])
    monkeypatch.setattr(mpc, "load_me", lambda b, cid: me)
    monkeypatch.setattr("financial_policy.require_stripe_write", lambda acct: None)
    patched = []
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: patched.append((p, b)) or [b])
    app = FastAPI()
    app.include_router(G.router)
    c = TestClient(app, base_url="https://lovecityc.com", follow_redirects=False)
    return c, state, patched


def _post(c, **form):
    return c.post("/my/gifts", data=form)


def test_pause_and_resume(client, stripe):
    c, _, _ = client
    f = stripe([_sub("sub_mine001")])
    r = _post(c, sub="sub_mine001", action="pause")
    assert r.status_code == 303 and r.headers["location"] == "/my/gifts?done=pause"
    assert f.calls[-1][:4] == ("POST", "/subscriptions/sub_mine001", ACCT, {"pause_collection[behavior]": "void"})
    _post(c, sub="sub_mine001", action="resume")
    assert f.calls[-1][3] == {"pause_collection": ""}


def test_stop_needs_the_box_ticked(client, stripe):
    c, _, _ = client
    f = stripe([_sub("sub_mine001")])
    assert _post(c, sub="sub_mine001", action="stop").headers["location"] == "/my/gifts?err=confirm"
    assert not any(m == "DELETE" for m, *_ in f.calls)
    assert _post(c, sub="sub_mine001", action="stop", confirm="yes").headers["location"] == "/my/gifts?done=stop"
    assert f.calls[-1][:2] == ("DELETE", "/subscriptions/sub_mine001")


def test_new_amount_keeps_the_product_and_rhythm_and_refigures_the_fee(client, stripe):
    c, _, _ = client
    f = stripe([_sub("sub_mine001", interval="week", count=2, fee=176)])
    r = _post(c, sub="sub_mine001", action="amount", amount="75")
    assert r.headers["location"] == "/my/gifts?done=amount"
    data = f.calls[-1][3]
    assert data["proration_behavior"] == "none"
    assert data["items[0][id]"] == "si_sub_mine001_0" and data["items[0][price_data][product]"] == "prod_sub_mine001"
    assert data["items[0][price_data][unit_amount]"] == 7500
    assert data["items[0][price_data][recurring][interval]"] == "week"
    assert data["items[0][price_data][recurring][interval_count]"] == 2
    from giving_router import covered_fee_cents
    assert data["items[1][price_data][unit_amount]"] == covered_fee_cents(7500)


@pytest.mark.parametrize("amount", ["0.5", "30000", "abc"])
def test_an_amount_out_of_range_changes_nothing(client, stripe, amount):
    c, _, _ = client
    f = stripe([_sub("sub_mine001")])
    assert _post(c, sub="sub_mine001", action="amount", amount=amount).headers["location"] == "/my/gifts?err=amount"
    assert not any(m == "POST" for m, *_ in f.calls)


def test_card_goes_to_stripes_own_page_and_the_config_is_made_once(client, stripe):
    c, _, patched = client
    f = stripe([_sub("sub_mine001")])
    r = _post(c, sub="sub_mine001", action="card")
    assert r.headers["location"] == "https://billing.stripe.com/p/session_x"
    cfg = next(x for x in f.calls if x[1] == "/billing_portal/configurations")[3]
    assert cfg["features[payment_method_update][enabled]"] == "true"
    assert "features[subscription_cancel][enabled]" not in cfg
    sess = next(x for x in f.calls if x[1] == "/billing_portal/sessions")[3]
    assert sess == {"customer": "cus_1", "configuration": "bpc_1", "return_url": "https://lovecityc.com/my/gifts"}
    saved = patched[0][1]["settings"]["giving"]["portal_config"]
    assert saved == {"id": "bpc_1", "account": ACCT}


def test_someone_elses_gift_or_another_churchs_is_refused(client, stripe):
    c, _, _ = client
    f = stripe([_sub("sub_mine001"), _sub("sub_other001", biz=OTHER)])
    for sid in ("sub_other001", "sub_nothere"):
        assert _post(c, sub=sid, action="stop", confirm="yes").headers["location"] == "/my/gifts?err=gone"
    assert not any(m == "DELETE" for m, *_ in f.calls)


def test_the_owners_preview_never_writes(client, stripe):
    c, state, _ = client
    f = stripe([_sub("sub_mine001")])
    state["unavailable"] = "preview"
    assert _post(c, sub="sub_mine001", action="pause").headers["location"] == "/my/gifts?err=preview"
    assert f.calls == []


def test_signed_out_goes_back_and_nothing_happens(client, stripe):
    c, state, _ = client
    f = stripe([_sub("sub_mine001")])
    state["me"] = None
    assert _post(c, sub="sub_mine001", action="pause").headers["location"] == "/my/gifts"
    assert f.calls == []


def test_bad_input_is_refused_before_stripe(client, stripe):
    c, state, _ = client
    f = stripe([_sub("sub_mine001")])
    assert _post(c, sub="sub_mine001", action="refund").headers["location"] == "/my/gifts?err=error"
    assert _post(c, sub="../customers", action="pause").headers["location"] == "/my/gifts?err=error"
    state["allowed"] = False
    assert _post(c, sub="sub_mine001", action="pause").headers["location"] == "/my/gifts?err=slow"
    assert f.calls == []


# ─── the page ────────────────────────────────────────────────────────

def _req(q=""):
    from starlette.requests import Request
    return Request({"type": "http", "query_string": q.encode(), "headers": [], "path": "/my/gifts"})


def test_page_lists_each_gift_with_its_actions():
    gifts = [G._shape(_sub("sub_mine001", cents=5000, fee=176, interval="week", count=2)),
             G._shape(_sub("sub_mine002", paused=True))]
    html = G.render_gifts(_biz(), {"slug": "x"}, _req("done=pause"), {"id": "c1", "email": EMAIL},
                          gifts, "/give")
    assert "$51.76" in html and "every 2 weeks" in html and "processing fee" in html
    assert "Resume my gift" in html and "Pause my gift" in html
    assert 'value="sub_mine001"' in html and "Stop this gift" in html
    assert "Your gift is paused" in html


def test_page_with_no_gift_says_which_email_it_looked_under():
    html = G.render_gifts(_biz(), {"slug": "x"}, _req(), {"id": "c1", "email": EMAIL}, [], "/give")
    assert EMAIL in html and "Set up a gift" in html


def test_page_when_stripe_is_down_says_nothing_changed():
    html = G.render_gifts(_biz(), {"slug": "x"}, _req(), {"id": "c1", "email": EMAIL}, None, "/give")
    assert "Nothing has changed" in html


def test_the_post_route_is_mounted_before_the_catch_all():
    import os
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    import kmj_intake_automation
    routes = [(getattr(r, "path", ""), getattr(r, "methods", set())) for r in kmj_intake_automation.app.routes]
    paths = [p for p, _ in routes]
    i = next(i for i, (p, m) in enumerate(routes) if p == "/my/gifts" and "POST" in (m or set()))
    assert i < paths.index("/{path:path}")

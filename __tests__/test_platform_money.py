"""Mission Control → Money: the owner's bills, when they're due, what they're
on pace for, the income, and the tax / reserve / pay split.

No network: the database (sb_clients), Twilio, Railway and DigitalOcean are
all faked. The promises under test are the ones Kevin reads money by: an
unreadable vendor shows its entered amount and says so (never a 500); a
due date never lands on a day the month doesn't have; income is priced at
what each subscription really pays (founding vs regular), with comped
businesses and the owner's own left out; the split always adds up.
"""
from __future__ import annotations

import logging
import pathlib
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import church_founding
import pricing_config
import platform_money as pm
import sb_clients
from auth_supabase import require_user
from lead_admin import PLATFORM_OWNER_EMAIL

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)   # Nov 14, 7 AM Eastern

CONTRACT_KEYS = {"ok", "month", "as_of", "income", "costs", "totals", "left_over_cents",
                 "split", "due_next", "alerts", "plan_model"}
COST_KEYS = {"key", "vendor", "what", "kind", "source", "live_error", "so_far_cents", "on_pace_cents",
             "last_month_cents", "billing_day", "next_due", "note", "watch"}


# ─── Fakes ──────────────────────────────────────────────────────────────

class FakeDB:
    """The service-role helpers platform_money calls, over in-memory rows."""

    def __init__(self, bills=None, config=None, missing=False):
        self.bills = [dict(b, active=True) for b in (pm.DEFAULT_BILLS if bills is None else bills)]
        self.config = config if config is not None else dict(pm.DEFAULT_CONFIG)
        self.missing = missing
        self.usage = {"this": [], "last": []}
        self.businesses = []
        self.usage_fails = False
        self.writes = []
        self.error = None

    def _fail(self, status=404, code="PGRST205"):
        self.error = {"status": status, "code": code, "message": ""}
        return None

    def get(self, path, *, redact=False):
        self.error = None
        if self.missing and path.startswith(("/platform_money_bills", "/platform_money_config")):
            return self._fail()
        if path.startswith("/platform_money_bills"):
            return sorted(self.bills, key=lambda b: (b.get("sort", 100), b["vendor"]))
        if path.startswith("/platform_money_config"):
            return [dict(self.config)]
        raise AssertionError(f"unexpected GET {path}")

    def get_all(self, path, *, key="id", strict=False, redact=False):
        if path.startswith("/api_usage"):
            assert "select=id,model,endpoint,cost_cents" in path
            if self.usage_fails:
                raise sb_clients.PartialRead("the first page failed")
            return self.usage["this"] if "gte.2026-11-01" in path else self.usage["last"]
        if path.startswith("/businesses"):
            return self.businesses
        raise AssertionError(f"unexpected paged GET {path}")

    def post(self, path, body, prefer="return=representation", *, redact=False):
        self.error = None
        if self.missing:
            return self._fail()
        self.writes.append(("POST", path, body, prefer))
        if path.startswith("/platform_money_bills"):
            if any(b["key"] == body["key"] for b in self.bills):
                return self._fail(409, "23505")
            self.bills.append(dict(body))
            return [dict(body)]
        if path.startswith("/platform_money_config"):
            self.config = {k: body[k] for k in pm.DEFAULT_CONFIG}
            return [dict(body)]
        raise AssertionError(f"unexpected POST {path}")

    def patch(self, path, body):
        self.error = None
        if self.missing:
            return self._fail()
        self.writes.append(("PATCH", path, body, None))
        key = path.split("key=eq.", 1)[1]
        hit = [b for b in self.bills if b["key"] == key]
        for b in hit:
            b.update(body)
        return [dict(b) for b in hit]

    def last_error(self):
        return self.error


def fake_http(responses):
    """_http_json stand-in: the first URL fragment that matches answers."""
    calls = []

    def _http(method, url, **kw):
        calls.append((method, url, kw))
        for fragment, answer in responses.items():
            if fragment in url:
                if isinstance(answer, BaseException):
                    raise answer
                return answer
        raise AssertionError(f"unexpected {method} {url}")
    return _http, calls


TWILIO = {"ThisMonth.json": {"usage_records": [{"category": "totalprice", "price": "18.40", "price_unit": "usd"}]},
          "LastMonth.json": {"usage_records": [{"category": "totalprice", "price": "30.1234", "price_unit": "usd"}]}}
RAILWAY = {"backboard.railway.com": {"data": {"me": {"workspaces": [
    {"customer": {"currentUsage": 9.5,
                  "billingPeriod": {"start": "2026-10-27T00:00:00.000Z", "end": "2026-11-27T00:00:00.000Z"}}}]}}}}
DIGITALOCEAN = {"api.digitalocean.com": {"month_to_date_usage": "2.75", "account_balance": "0.00"}}

SECRETS = {"RAILWAY_API_TOKEN": "rw-secret-token-123", "DIGITALOCEAN_TOKEN": "do-secret-token-456",
           "TWILIO_ACCOUNT_SID": "ACsecretsid0000", "TWILIO_AUTH_TOKEN": "tw-secret-token-789"}


@pytest.fixture
def env(monkeypatch):
    """A clean slate: no vendor tokens, no Stripe price ids, a fixed clock,
    empty caches. Returns the FakeDB the module now reads."""
    import os
    for name in list(os.environ):
        if name.startswith(("STRIPE_PRICE_ID", "TWILIO_")) or name in (
                "RAILWAY_API_TOKEN", "DIGITALOCEAN_TOKEN", "STRIPE_PRICE_IDS_KEPT", "FOUNDING_CHURCH_SPOTS"):
            monkeypatch.delenv(name, raising=False)
    db = FakeDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", db.get_all)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setattr(sb_clients, "last_error", db.last_error)
    monkeypatch.setattr(pm, "_now", lambda: NOW)
    monkeypatch.setattr(church_founding, "_owner_is_platform", lambda owner_id: owner_id == "kevin")
    pm.forget()
    yield db
    pm.forget()


def _client(email=PLATFORM_OWNER_EMAIL):
    app = FastAPI()
    app.include_router(pm.router)
    if email is not None:
        app.dependency_overrides[require_user] = lambda: SimpleNamespace(id="u-1", email=email, role="authenticated")
    return TestClient(app)


def _costs(body):
    return {c["key"]: c for c in body["costs"]}


# ─── The owner gate ─────────────────────────────────────────────────────

def test_every_route_is_owner_only(env):
    routes = [("get", "/platform/money/summary", None), ("get", "/platform/money/bills", None),
              ("post", "/platform/money/bills", {"vendor": "X"}),
              ("patch", "/platform/money/bills/supabase", {"amount_cents": 1}),
              ("delete", "/platform/money/bills/supabase", None),
              ("get", "/platform/money/config", None),
              ("put", "/platform/money/config", {"tax_pct": 30, "reserve_pct": 10, "pay_pct": 60,
                                                 "reserve_goal_months": 3})]
    anonymous, tenant = _client(None), _client("tenant@example.com")
    for method, url, body in routes:
        kw = {"json": body} if body is not None else {}
        assert getattr(anonymous, method)(url, **kw).status_code in (401, 403), url
        assert getattr(tenant, method)(url, **kw).status_code == 403, url
    assert env.writes == []


# ─── The summary ────────────────────────────────────────────────────────

def test_summary_shape_with_every_reader_live(env, monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    http, calls = fake_http({**TWILIO, **RAILWAY, **DIGITALOCEAN})
    monkeypatch.setattr(pm, "_http_json", http)
    env.usage["this"] = [
        {"id": 1, "model": "claude-sonnet-5-5", "endpoint": "/chief", "cost_cents": 3000.4},
        {"id": 2, "model": "claude-haiku-5-5", "endpoint": "/chief", "cost_cents": 1555.2},
        {"id": 3, "model": "gpt-4o-mini-transcribe", "endpoint": "/ai/whisper", "cost_cents": 40},
        {"id": 4, "model": "inworld-tts-2-flash", "endpoint": "/ai/tts", "cost_cents": 12},
        {"id": 5, "model": "", "endpoint": "/ai/tts-el", "cost_cents": 6},
        {"id": 6, "model": "layer2_cache", "endpoint": "/ai/proxy", "cost_cents": 0},
        {"id": 7, "model": "twilio", "endpoint": "sms", "cost_cents": 999},
    ]
    env.usage["last"] = [{"id": 8, "model": "claude-sonnet-5", "endpoint": "/chief", "cost_cents": 6800}]

    r = _client().get("/platform/money/summary")
    assert r.status_code == 200
    body = r.json()
    assert CONTRACT_KEYS <= set(body)
    assert body["ok"] is True and body["month"] == "2026-11"
    assert body["as_of"].startswith("2026-11-14T12:00:00")
    assert body["setup_needed"] is False
    for c in body["costs"]:
        assert COST_KEYS <= set(c), c["key"]
    paces = [c["on_pace_cents"] for c in body["costs"]]
    assert paces == sorted(paces, reverse=True)

    costs = _costs(body)
    # 13.5 days into a 30-day month.
    anth = costs["anthropic"]
    assert (anth["source"], anth["live_error"], anth["so_far_cents"]) == ("live", False, 4556)
    assert anth["on_pace_cents"] == round(4556 * 30 / 13.5)
    assert anth["last_month_cents"] == 6800
    assert costs["openai"]["so_far_cents"] == 40
    assert costs["inworld"]["so_far_cents"] == 12
    assert costs["elevenlabs"]["so_far_cents"] == 6        # by its endpoint; texts never count as AI
    tw = costs["twilio"]
    assert (tw["source"], tw["so_far_cents"], tw["last_month_cents"]) == ("live", 1840, 3012)
    # Railway is paced over its own billing period (Oct 27 → Nov 27).
    rw = costs["railway"]
    assert rw["source"] == "live" and rw["so_far_cents"] == 950
    assert rw["on_pace_cents"] == round(950 * 31 / 18.5)
    assert costs["digitalocean"]["so_far_cents"] == 275
    # Flat bills: their amount, nothing so far.
    sb = costs["supabase"]
    assert (sb["source"], sb["so_far_cents"], sb["on_pace_cents"], sb["next_due"]) == ("entered", None, 3500, "2026-11-22")
    # Usage bills with no reader: their entered amount, no error.
    assert (costs["livekit"]["source"], costs["livekit"]["live_error"]) == ("entered", False)

    totals = body["totals"]
    assert totals["flat_cents"] == 27500
    assert totals["on_pace_cents"] == sum(paces) == totals["flat_cents"] + totals["usage_cents"]
    assert totals["so_far_usage_cents"] == 4556 + 40 + 12 + 6 + 1840 + 950 + 275

    # Nothing pays yet: everything is a shortfall, nothing to split.
    assert body["income"]["mrr_cents"] == 0
    assert body["left_over_cents"] == -totals["on_pace_cents"]
    split = body["split"]
    assert (split["tax_cents"], split["reserve_cents"], split["pay_cents"]) == (0, 0, 0)
    assert split["reserve_goal_cents"] == 3 * totals["on_pace_cents"]
    assert (split["tax_pct"], split["reserve_pct"], split["pay_pct"], split["reserve_goal_months"]) == (30, 10, 60, 3)

    # Due next: bills with a day, the next 35 days, by date.
    due = body["due_next"]
    assert [d["key"] for d in due] == ["supabase", "resend", "railway", "digitalocean", "claude", "vercel"]
    assert [d["date"] for d in due] == ["2026-11-22", "2026-11-23", "2026-11-27", "2026-12-01",
                                        "2026-12-04", "2026-12-07"]
    assert due[2]["amount_cents"] == rw["on_pace_cents"] and due[2]["source"] == "live"

    pmodel = body["plan_model"]
    assert pmodel["founding_price_cents"] == pricing_config.church_founding_price_cents()["church_growing"]
    assert pmodel["regular_price_cents"] == pricing_config.church_price_cents()["church_growing"]
    assert (pmodel["per_church_cost_cents"], pmodel["card_fee_pct"], pmodel["card_fee_fixed_cents"]) == (1500, 2.9, 30)
    assert pmodel["founding_spots"] == church_founding.spots()
    assert pmodel["base_steps"][1:] == [[50, 80000], [100, 150000]]

    # No token, and not the Twilio account id, is in the answer.
    for secret in SECRETS.values():
        assert secret not in r.text


def test_unset_tokens_show_the_entered_amount_without_an_error(env, monkeypatch):
    monkeypatch.setattr(pm, "_http_json", fake_http({})[0])   # any call would fail the test
    body = _client().get("/platform/money/summary").json()
    costs = _costs(body)
    for key in ("railway", "digitalocean", "twilio"):
        c = costs[key]
        assert (c["source"], c["live_error"], c["so_far_cents"]) == ("entered", False, None), key
        assert c["on_pace_cents"] == next(b["amount_cents"] for b in pm.DEFAULT_BILLS if b["key"] == key)
    assert costs["anthropic"]["source"] == "live"   # the ledger needs no token


def test_every_reader_failing_still_answers(env, monkeypatch, caplog):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    boom = pm.ReadFailed("status 500")
    monkeypatch.setattr(pm, "_http_json", fake_http({"twilio": boom, "railway": RuntimeError(SECRETS["RAILWAY_API_TOKEN"]),
                                                      "digitalocean": boom})[0])
    env.usage_fails = True
    monkeypatch.setattr(pm, "read_income", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    with caplog.at_level(logging.WARNING, logger="platform_money"):
        r = _client().get("/platform/money/summary")
    assert r.status_code == 200
    body = r.json()
    costs = _costs(body)
    for key in ("railway", "digitalocean", "twilio", "anthropic", "openai", "inworld", "elevenlabs"):
        c = costs[key]
        assert (c["source"], c["live_error"], c["so_far_cents"]) == ("entered", True, None), key
    assert costs["anthropic"]["on_pace_cents"] == 7000
    assert body["income"]["live_error"] is True and body["income"]["mrr_cents"] == 0
    assert any(a["key"] == "income" for a in body["alerts"])
    # The logs name the reader and the kind of failure, never a token or the sid.
    for secret in SECRETS.values():
        assert secret not in caplog.text
    assert "railway live read failed: RuntimeError" in caplog.text


def test_live_reads_are_cached_and_refresh_reads_again(env, monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "x")
    http, calls = fake_http(DIGITALOCEAN)
    monkeypatch.setattr(pm, "_http_json", http)
    client = _client()
    client.get("/platform/money/summary")
    client.get("/platform/money/summary")
    assert len(calls) == 1
    client.get("/platform/money/summary?refresh=true")
    assert len(calls) == 2


def test_edits_show_at_once(env):
    client = _client()
    assert client.patch("/platform/money/bills/supabase", json={"amount_cents": 4500}).status_code == 200
    body = client.get("/platform/money/summary").json()
    assert _costs(body)["supabase"]["on_pace_cents"] == 4500
    assert client.delete("/platform/money/bills/vercel").status_code == 200
    body = client.get("/platform/money/summary").json()
    assert "vercel" not in _costs(body)
    assert "vercel" not in [d["key"] for d in body["due_next"]]


# ─── On pace ────────────────────────────────────────────────────────────

def test_on_pace_math():
    start, end = datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert pm.on_pace(1000, start, end, datetime(2026, 11, 11, tzinfo=timezone.utc)) == 3000
    # Never projected from under a day: an hour in is treated as one day.
    assert pm.on_pace(100, start, end, datetime(2026, 11, 1, 1, tzinfo=timezone.utc)) == 3000
    # The period over: what was spent is the pace.
    assert pm.on_pace(4321, start, end, datetime(2026, 12, 3, tzinfo=timezone.utc)) == 4321
    assert pm.on_pace(0, start, end, datetime(2026, 11, 20, tzinfo=timezone.utc)) == 0


def test_month_bounds_roll_over_the_year():
    assert pm.month_bounds(datetime(2026, 12, 9, tzinfo=timezone.utc)) == (
        datetime(2026, 12, 1, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert pm.last_month_bounds(datetime(2027, 1, 5, tzinfo=timezone.utc)) == (
        datetime(2026, 12, 1, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc))


# ─── Due dates ──────────────────────────────────────────────────────────

def test_next_due_clamps_to_the_months_last_day():
    assert pm.next_due(31, date(2026, 11, 14)) == date(2026, 11, 30)      # Nov has 30 days
    assert pm.next_due(30, date(2027, 2, 3)) == date(2027, 2, 28)
    assert pm.next_due(29, date(2028, 2, 3)) == date(2028, 2, 29)         # a leap year


def test_next_due_rolls_a_past_day_to_next_month():
    assert pm.next_due(4, date(2026, 11, 14)) == date(2026, 12, 4)
    assert pm.next_due(14, date(2026, 11, 14)) == date(2026, 11, 14)      # due today is still due
    assert pm.next_due(5, date(2026, 12, 20)) == date(2027, 1, 5)         # across the year
    assert pm.next_due(31, date(2026, 12, 31)) == date(2026, 12, 31)
    assert pm.next_due(31, date(2027, 1, 31)) == date(2027, 1, 31)
    assert pm.next_due(30, date(2027, 1, 31)) == date(2027, 2, 28)        # rolled AND clamped


def test_next_due_without_a_day():
    assert pm.next_due(None, date(2026, 11, 14)) is None
    assert pm.next_due(0, date(2026, 11, 14)) is None
    assert pm.next_due(32, date(2026, 11, 14)) is None


# ─── Income ─────────────────────────────────────────────────────────────

@pytest.fixture
def prices(monkeypatch):
    ids = {"STRIPE_PRICE_ID_CHURCH_GROWING": "price_grow", "STRIPE_PRICE_ID_CHURCH_GROWING_FOUNDING": "price_grow_f",
           "STRIPE_PRICE_ID_CHURCH_GROWING_ANNUAL": "price_grow_y", "STRIPE_PRICE_ID_CHURCH_SMALL": "price_small",
           "STRIPE_PRICE_ID_SOLO": "price_solo"}
    for name, value in ids.items():
        monkeypatch.setenv(name, value)
    return ids


def _biz(i, plan, status="active", owner="someone", comp=None):
    return {"id": f"b{i}", "owner_id": f"{owner}-{i}" if owner == "someone" else owner,
            "subscription_status": status, "subscription_plan": plan, "comp_tier": comp}


def test_income_prices_each_subscription_at_what_it_pays(env, prices):
    grow, grow_f = pricing_config.church_price_cents()["church_growing"], \
        pricing_config.church_founding_price_cents()["church_growing"]
    small = pricing_config.church_price_cents()["church_small"]
    solo = pricing_config.audience_price_cents()["solo"]
    rows = [
        _biz(1, "price_grow"),                           # regular
        _biz(2, "price_grow_f"),                         # founding
        _biz(3, "price_grow_f", status="past_due"),      # still paying (Stripe is retrying)
        _biz(4, "price_grow_y"),                         # annual: a twelfth of ten months
        _biz(5, "price_small"),
        _biz(6, "price_solo"),
        _biz(7, "price_grow", status="trialing"),        # a trial pays nothing yet
        _biz(8, "price_grow", status="canceled"),
        _biz(9, "price_unknown"),                        # no plan reads from it
        _biz(10, "price_grow", owner="kevin"),           # the owner's own church
        _biz(11, "price_grow", comp="church_growing"),   # comped: counted, never priced
        _biz(12, None, status=None, comp="practice"),
        _biz(13, "price_grow", comp="  "),               # a blank comp is no comp
    ]
    out = pm.income_from_rows(rows, church_founding._owner_is_platform)
    assert out["comped"] == 2
    assert out["paying"] == 7
    assert out["founding"] == 2
    annual = round(grow * 10 / 12)
    assert out["mrr_cents"] == grow + 2 * grow_f + annual + small + solo + grow
    by = {p["plan"]: p for p in out["by_plan"]}
    assert by["church_growing"] == {"plan": "church_growing", "name": "Growing Church", "count": 5,
                                    "cents": 2 * grow + 2 * grow_f + annual}
    assert by["solo"]["count"] == 1 and by["solo"]["cents"] == solo
    assert [p["cents"] for p in out["by_plan"]] == sorted((p["cents"] for p in out["by_plan"]), reverse=True)
    assert out["unchecked"] == 0


def test_income_an_owner_that_cant_be_checked_is_left_out(env, prices):
    out = pm.income_from_rows([_biz(1, "price_grow"), _biz(2, "price_grow")],
                              lambda owner_id: None if owner_id == "someone-2" else False)
    assert out["paying"] == 1 and out["unchecked"] == 1
    alerts = pm.alerts_for([], out)
    assert [a["key"] for a in alerts] == ["income"] and alerts[0]["level"] == "info"


def test_summary_income_and_split(env, prices, monkeypatch):
    grow_f = pricing_config.church_founding_price_cents()["church_growing"]
    env.bills = [dict(b, active=True) for b in pm.DEFAULT_BILLS if b["kind"] == "flat"]   # 27,500 a month
    env.businesses = [_biz(i, "price_grow_f") for i in range(3)] + [_biz(9, "price_grow", owner="kevin"),
                                                                    _biz(10, None, status=None, comp="church_large")]
    body = _client().get("/platform/money/summary").json()
    inc = body["income"]
    assert (inc["paying"], inc["founding"], inc["comped"], inc["mrr_cents"]) == (3, 3, 1, 3 * grow_f)
    assert inc["by_plan"] == [{"plan": "church_growing", "name": "Growing Church", "count": 3, "cents": 3 * grow_f}]
    left = 3 * grow_f - 27500
    assert body["left_over_cents"] == left
    split = body["split"]
    assert split["tax_cents"] == left * 30 // 100
    assert split["reserve_cents"] == left * 10 // 100
    assert split["tax_cents"] + split["reserve_cents"] + split["pay_cents"] == left
    assert split["reserve_goal_cents"] == 3 * 27500
    # No business name, id or owner travels.
    assert "b0" not in str(inc) and "someone" not in str(body)


# ─── The split and the plan model ───────────────────────────────────────

def test_split_rounding_always_adds_up():
    cfg = {"tax_pct": 33.3, "reserve_pct": 16.7, "pay_pct": 50, "reserve_goal_months": 2}
    s = pm.split_for(10001, cfg, 400)
    assert s["tax_cents"] + s["reserve_cents"] + s["pay_cents"] == 10001
    assert s["reserve_goal_cents"] == 800
    s = pm.split_for(-5, cfg, 400)
    assert (s["tax_cents"], s["reserve_cents"], s["pay_cents"]) == (0, 0, 0)
    assert pm.split_for(0, cfg, 400)["pay_cents"] == 0


def test_plan_model_base_steps_start_at_the_real_costs():
    assert pm.plan_model(46100)["base_steps"] == [[25, 50000], [50, 80000], [100, 150000]]
    assert pm.plan_model(61234)["base_steps"] == [[25, 65000], [50, 80000], [100, 150000]]
    assert pm.plan_model(90001)["base_steps"] == [[25, 95000], [50, 95000], [100, 150000]]


# ─── Alerts ─────────────────────────────────────────────────────────────

def _cost(key, pace, last, source="live", watch=False, note=None):
    return {"key": key, "vendor": key.title(), "on_pace_cents": pace, "last_month_cents": last,
            "source": source, "watch": watch, "note": note}


def test_alerts_running_high_and_watched_bills():
    alerts = pm.alerts_for([
        _cost("anthropic", 12000, 6800),                  # 1.76x and over $10: high
        _cost("openai", 900, 100),                        # 9x, but under $10: quiet
        _cost("twilio", 4000, 3000),                      # 1.33x: quiet
        _cost("railway", 5000, None),                     # no last month to compare
        _cost("entered", 50000, 100, source="entered"),   # not a live number
        _cost("livekit", 0, None, source="entered", watch=True, note="Free plan stops at 5,000"),
        _cost("resend", 2000, None, source="entered", watch=True, note=None),
    ], {"unchecked": 0})
    by = {a["key"]: a for a in alerts}
    assert set(by) == {"anthropic", "livekit", "resend"}
    assert by["anthropic"]["title"] == "Anthropic is running high" and by["anthropic"]["level"] == "warn"
    assert "$120" in by["anthropic"]["body"] and "$68" in by["anthropic"]["body"]
    assert by["livekit"]["body"] == "Free plan stops at 5,000"
    assert by["resend"]["body"]
    for a in alerts:
        assert set(a) == {"key", "title", "body", "level"} and a["level"] in ("warn", "info")


def test_a_watched_bill_running_high_is_one_alert():
    alerts = pm.alerts_for([_cost("resend", 3500, 2000, watch=True, note="May go up to $35")], {"unchecked": 0})
    assert len(alerts) == 1 and "running high" in alerts[0]["title"] and "May go up to $35" in alerts[0]["body"]


# ─── The bills ──────────────────────────────────────────────────────────

def test_bills_list_and_create(env):
    client = _client()
    body = client.get("/platform/money/bills").json()
    assert [b["key"] for b in body["bills"]][:3] == ["claude", "supabase", "vercel"]
    assert body["setup_needed"] is False
    r = client.post("/platform/money/bills", json={"vendor": "Google Workspace", "what": "Mail",
                                                   "amount_cents": 1400, "billing_day": 9})
    assert r.status_code == 200
    assert r.json()["bill"]["key"] == "google-workspace" and r.json()["bill"]["active"] is True
    assert client.post("/platform/money/bills", json={"key": "supabase", "vendor": "Again"}).status_code == 409
    assert client.post("/platform/money/bills", json={"vendor": "X", "live": "stripe"}).status_code == 422
    assert client.post("/platform/money/bills", json={"vendor": "X", "key": "Bad Key!"}).status_code == 422
    assert client.post("/platform/money/bills", json={"vendor": "X", "amount_cents": -1}).status_code == 422


def test_bill_patch_validation(env):
    client = _client()
    bad = [{"amount_cents": -1}, {"billing_day": 0}, {"billing_day": 32}, {"kind": "weekly"},
           {"vendor": None}, {"vendor": "   "}, {"amount_cents": None}, {"active": None},
           {"live": "railway"}, {"owner": "x"}, {}]
    for body in bad:
        assert client.patch("/platform/money/bills/supabase", json=body).status_code == 422, body
    assert env.writes == []
    r = client.patch("/platform/money/bills/supabase",
                     json={"amount_cents": 3600, "billing_day": None, "note": "  ", "watch": True})
    assert r.status_code == 200
    bill = r.json()["bill"]
    assert (bill["amount_cents"], bill["billing_day"], bill["note"], bill["watch"]) == (3600, None, None, True)
    assert "updated_at" in env.writes[-1][2]
    assert client.patch("/platform/money/bills/nope", json={"amount_cents": 1}).status_code == 404
    assert client.patch("/platform/money/bills/Bad%20Key", json={"amount_cents": 1}).status_code == 404


def test_delete_is_soft_and_patch_brings_it_back(env):
    client = _client()
    r = client.delete("/platform/money/bills/r2")
    assert r.status_code == 200 and r.json()["bill"]["active"] is False
    assert env.writes[-1][0] == "PATCH" and env.writes[-1][2]["active"] is False
    assert any(b["key"] == "r2" for b in client.get("/platform/money/bills").json()["bills"])
    assert client.patch("/platform/money/bills/r2", json={"active": True}).json()["bill"]["active"] is True
    assert client.delete("/platform/money/bills/nope").status_code == 404


# ─── The split's settings ───────────────────────────────────────────────

def test_config_must_add_up_to_100(env):
    client = _client()
    assert client.get("/platform/money/config").json()["config"] == {
        "tax_pct": 30, "reserve_pct": 10, "pay_pct": 60, "reserve_goal_months": 3}
    bad = [{"tax_pct": 30, "reserve_pct": 10, "pay_pct": 50, "reserve_goal_months": 3},
           {"tax_pct": 101, "reserve_pct": 0, "pay_pct": -1, "reserve_goal_months": 3},
           {"tax_pct": 30, "reserve_pct": 10, "pay_pct": 60, "reserve_goal_months": 25},
           {"tax_pct": 30, "reserve_pct": 10, "pay_pct": 60, "reserve_goal_months": -1},
           {"tax_pct": 30, "reserve_pct": 10, "pay_pct": 60}]
    for body in bad:
        assert client.put("/platform/money/config", json=body).status_code == 422, body
    assert env.writes == []
    r = client.put("/platform/money/config", json={"tax_pct": 25, "reserve_pct": 15.5, "pay_pct": 59.5,
                                                   "reserve_goal_months": 6})
    assert r.status_code == 200
    assert r.json()["config"] == {"tax_pct": 25, "reserve_pct": 15.5, "pay_pct": 59.5, "reserve_goal_months": 6}
    method, path, body, prefer = env.writes[-1]
    assert body["id"] == 1 and "merge-duplicates" in prefer
    assert _client().get("/platform/money/summary").json()["split"]["reserve_goal_months"] == 6


# ─── Before the migration ───────────────────────────────────────────────

def test_before_the_migration_reads_the_seed_and_saving_says_so(env):
    env.missing = True
    client = _client()
    body = client.get("/platform/money/summary").json()
    assert body["setup_needed"] is True
    assert body["totals"]["flat_cents"] == 27500
    assert len(body["costs"]) == len(pm.DEFAULT_BILLS)
    assert client.get("/platform/money/config").json()["config"]["pay_pct"] == 60
    r = client.patch("/platform/money/bills/supabase", json={"amount_cents": 1})
    assert r.status_code == 503 and pm.MIGRATION in r.json()["detail"]
    assert client.put("/platform/money/config", json={"tax_pct": 30, "reserve_pct": 10, "pay_pct": 60,
                                                      "reserve_goal_months": 3}).status_code == 503


def test_a_table_that_is_there_but_unreadable_is_a_503_not_the_seed(env, monkeypatch):
    def down(path, *, redact=False):
        env.error = None    # a transport failure: no PostgREST answer at all
        return None
    monkeypatch.setattr(sb_clients, "sb_get_as_service", down)
    assert _client().get("/platform/money/summary").status_code == 503


# ─── The readers' parsing ───────────────────────────────────────────────

def test_a_closed_month_is_read_once(env, monkeypatch):
    seen = []
    real = env.get_all

    def counting(path, **kw):
        seen.append("last" if "gte.2026-10-01" in path else "this")
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", counting)
    env.usage["last"] = [{"id": 1, "model": "gpt-5.4", "endpoint": "/x", "cost_cents": 250}]
    first = pm.read_api_usage(NOW)
    second = pm.read_api_usage(NOW)
    assert seen == ["this", "last", "this"]
    assert first["api_usage:openai"]["last_month_cents"] == second["api_usage:openai"]["last_month_cents"] == 250
    assert first["api_usage:anthropic"]["last_month_cents"] == 0


def test_twilio_reader_uses_the_auth_token_or_the_api_key(env, monkeypatch):
    http, calls = fake_http(TWILIO)
    monkeypatch.setattr(pm, "_http_json", http)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK1")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "sec")
    out = pm.read_twilio(NOW)
    assert out["twilio"]["so_far_cents"] == 1840
    assert calls[0][2]["auth"] == ("SK1", "sec") and calls[0][2]["params"] == {"Category": "totalprice"}
    assert "/Accounts/AC1/Usage/Records/ThisMonth.json" in calls[0][1]
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    pm.read_twilio(NOW)
    assert calls[-1][2]["auth"] == ("AC1", "tok")


def test_twilio_empty_month_is_zero_and_a_strange_answer_fails():
    assert pm._twilio_total({"usage_records": []}) == 0
    with pytest.raises(pm.ReadFailed):
        pm._twilio_total({"message": "Authenticate"})


def test_railway_errors_fail_the_read(env, monkeypatch):
    monkeypatch.setenv("RAILWAY_API_TOKEN", "t")
    monkeypatch.setattr(pm, "_http_json", fake_http({"railway": {"errors": [{"message": "Not Authorized"}]}})[0])
    with pytest.raises(pm.ReadFailed):
        pm.read_railway(NOW)
    monkeypatch.setattr(pm, "_http_json", fake_http({"railway": {"data": {"me": {"workspaces": [{"customer": None}]}}}})[0])
    with pytest.raises(pm.ReadFailed):
        pm.read_railway(NOW)


def test_railway_sends_the_token_as_a_bearer(env, monkeypatch):
    monkeypatch.setenv("RAILWAY_API_TOKEN", "tok-1")
    http, calls = fake_http(RAILWAY)
    monkeypatch.setattr(pm, "_http_json", http)
    pm.read_railway(NOW)
    method, url, kw = calls[0]
    assert method == "POST" and url == pm.RAILWAY_URL
    assert kw["headers"]["Authorization"] == "Bearer tok-1"
    assert "currentUsage" in kw["json_body"]["query"]

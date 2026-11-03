"""Every text is counted and costed against the business that sent it
(2026-11-03, Kevin: "make the fixes").

Each outbound text cost the platform money at Twilio and none of it was
recorded: no api_usage row, nothing in the Costs view, and no way to say how
many texts a church sent this month (its plan's text allowance is counted in
texts). Now:

  1. twilio_sms.send_sms writes one api_usage row per text Twilio accepts
     (endpoint "sms"), against the business whose line sent it, priced at
     segments x pricing_config.sms_segment_cost_cents(). A send that raises
     writes nothing. The TwiML auto-reply writes one too.
  2. A text is not AI: the spend guard, the credit meter, the Chief message
     count and the other AI readers leave SMS rows out, in the query (so a
     day of texts never crowds AI rows out of PostgREST's 1,000-row window)
     and in memory. A 2,000-text announcement must not trip the breaker.
  3. sms_usage.texts_this_month counts a business's texts since the 1st,
     by the database, and says None (never 0) when it can't read.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import api_usage_logger
import billing_context
import billing_limits
import pricing_config
import sb_clients
import sms_usage
import spend_guard
import turn_context
import twilio_sms
import usage_metering

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHURCH = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


# ─── fakes ────────────────────────────────────────────────────────────

class _Messages:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("Twilio said no")
        return SimpleNamespace(sid=f"SM{len(self.calls)}")


@pytest.fixture
def rows(monkeypatch):
    """Every api_usage row the logger is asked to write."""
    out = []
    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync", lambda **kw: out.append(kw))

    async def _async(**kw):
        out.append(kw)
    monkeypatch.setattr(api_usage_logger, "log_api_usage", _async)
    return out


@pytest.fixture
def twilio(monkeypatch):
    fake = _Messages()
    monkeypatch.setattr(twilio_sms, "_twilio_client", lambda: SimpleNamespace(messages=fake))
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MG_test")
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550000000")
    monkeypatch.delenv("COST_SMS_SEGMENT_CENTS", raising=False)
    monkeypatch.delenv("SMS_SEGMENT_CENTS", raising=False)
    return fake


# ─── 1. one row per text, against its business ────────────────────────

def test_a_send_records_one_row_for_its_business(twilio, rows):
    sid = twilio_sms.send_sms("+15551112222", "See you Sunday — 10 AM.",
                              business_id=CHURCH, kind="message")
    assert sid == "SM1"
    assert len(rows) == 1
    r = rows[0]
    assert r["endpoint"] == "sms" and r["model"] == "twilio-sms" and r["provider"] == "twilio"
    assert r["business_id"] == CHURCH
    assert r["task_type"] == "sms_message"
    assert r["response_id"] == "SM1"
    assert r["input_tokens"] == 1 and r["output_tokens"] == 0     # one segment
    assert r["cost_cents_override"] == 1.25                     # the default dial
    assert r["units"] == 0                                      # never Chief credits


def test_the_cost_is_segments_times_the_dial(twilio, rows, monkeypatch):
    long_text = "x" * 200                          # GSM-7, 2 segments
    twilio_sms.send_sms("+15551112222", long_text, business_id=CHURCH)
    assert rows[-1]["input_tokens"] == 2 and rows[-1]["cost_cents_override"] == 2.5
    monkeypatch.setenv("COST_SMS_SEGMENT_CENTS", "2")
    twilio_sms.send_sms("+15551112222", long_text, business_id=CHURCH)
    assert rows[-1]["cost_cents_override"] == 4.0


def test_segments_are_counted_on_the_text_as_sent(twilio, rows):
    """An em dash would make the text UCS-2 (70 a segment); gsm_safe swaps
    it before it leaves, so 150 characters stay one segment."""
    body = "—" + "x" * 149
    assert twilio_sms.segments(body) == 3
    twilio_sms.send_sms("+15551112222", body, business_id=CHURCH)
    assert rows[-1]["input_tokens"] == 1


def test_a_failed_send_records_nothing(monkeypatch, rows):
    fake = _Messages(fail=True)
    monkeypatch.setattr(twilio_sms, "_twilio_client", lambda: SimpleNamespace(messages=fake))
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MG_test")
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550000000")
    with pytest.raises(RuntimeError):
        twilio_sms.send_sms("+15551112222", "hi", business_id=CHURCH)
    assert fake.calls and rows == []


def test_a_send_from_the_churchs_own_account_records_too(monkeypatch, rows):
    fake = _Messages()
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550000000")
    monkeypatch.setattr(twilio_sms, "own_account_route",
                        lambda n: {"account_sid": "AC_sub", "service_sid": "MG_sub"})
    monkeypatch.setattr(twilio_sms, "_account_client", lambda acct: SimpleNamespace(messages=fake))
    twilio_sms.send_sms("+15551112222", "hi", from_number="+12165550100", business_id=CHURCH)
    assert len(rows) == 1 and rows[0]["business_id"] == CHURCH and rows[0]["response_id"] == "SM1"


def test_a_lost_cost_row_never_fails_the_text(twilio, monkeypatch):
    def boom(**kw):
        raise RuntimeError("database down")
    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync", boom)
    assert twilio_sms.send_sms("+15551112222", "hi", business_id=CHURCH) == "SM1"


def test_the_row_names_its_own_business_never_the_requests(monkeypatch):
    """Through the real logger: a platform text (no business) sent inside a
    request billed to a church stays the platform's, and a text sent inside
    a Chief turn is not stamped as one of the turn's model calls."""
    posted = []
    monkeypatch.setattr(api_usage_logger, "SUPABASE_URL", "https://db.test")
    monkeypatch.setattr(api_usage_logger, "SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setattr(api_usage_logger.httpx, "post", lambda url, **kw: posted.append(kw["json"]))
    import schema_probe
    monkeypatch.setattr(schema_probe, "has_columns", lambda table, cols: True)
    tokens = turn_context.set_turn("turn-123")
    try:
        with billing_context.bill_to(OTHER):
            sms_usage.record_send(None, "Your code is 123456", sid="SM9", kind="trial_check")
            sms_usage.record_send(CHURCH, "hi", sid="SM10", kind="message")
            assert billing_context.current() == OTHER       # the request's tenant comes back
    finally:
        turn_context.reset(tokens)
    assert "business_id" not in posted[0]                 # not OTHER
    assert posted[1]["business_id"] == CHURCH
    for body in posted:
        assert "turn_id" not in body and "lane" not in body
        assert body["provider"] == "twilio" and body["units"] == 0
    assert posted[0]["response_id"] == "SM9"


def test_the_twiml_auto_reply_records_a_row(monkeypatch, rows):
    """Twilio sends (and bills) the webhook's TwiML reply like any text."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import sms_routing

    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "twilio")

    async def route(**kw):
        return {"action": "daily_join", "business_id": CHURCH, "reply": "You're in — see you tomorrow."}
    monkeypatch.setattr(sms_routing, "route_inbound", route)
    app = FastAPI()
    app.include_router(twilio_sms.router)
    res = TestClient(app).post("/webhooks/twilio/sms",
                               data={"From": "+15551112222", "Body": "DAILY", "To": "+15550000000"})
    assert res.status_code == 200 and "<Message>" in res.text
    assert len(rows) == 1
    assert rows[0]["business_id"] == CHURCH and rows[0]["task_type"] == "sms_reply"
    assert rows[0]["input_tokens"] == 1 and rows[0]["cost_cents_override"] == 1.25


# ─── every caller names its business ──────────────────────────────────

def _is_send(node) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "send_sms"
            and isinstance(node.value, ast.Name) and node.value.id == "twilio_sms")


def test_every_production_send_names_who_pays():
    """Every call of twilio_sms.send_sms outside its own module, directly or
    handed to run_in_threadpool / to_thread, says whose text it is
    (business_id=, None for the platform's own) and what kind."""
    found = []
    for path in ROOT.glob("*.py"):
        src = path.read_text(encoding="utf-8", errors="ignore")
        if path.name == "twilio_sms.py" or "twilio_sms.send_sms" not in src:
            continue
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and (_is_send(node.func) or any(_is_send(a) for a in node.args)):
                found.append(path.name)
                named = {k.arg for k in node.keywords}
                assert {"business_id", "kind"} <= named, f"{path.name}:{node.lineno} names no payer"
    assert {"sms_service.py", "sms_routing.py", "kids_checkin.py", "member_portal.py",
            "no_card_trial.py"} <= set(found)


def test_kids_and_member_codes_are_billed_to_the_church(monkeypatch):
    import kids_checkin
    import member_portal
    import sms_service
    sent = []
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)

    async def not_opted(client, phone, business_id=None):
        return False

    async def sender(client, business_id):
        return "+15550009999"
    monkeypatch.setattr(sms_service, "is_opted_out", not_opted)
    monkeypatch.setattr(sms_service, "sender_for", sender)
    monkeypatch.setattr(twilio_sms, "send_sms", lambda to, body, **kw: sent.append(kw) or "SM1")
    biz = {"id": CHURCH, "name": "Love City"}
    assert asyncio.run(kids_checkin.text_code(biz, "+15551112222", "4821", ["Ava"])) == "sent"
    asyncio.run(member_portal._send_code_text(biz, "+15551112222", "123456"))
    assert [(s["business_id"], s["kind"]) for s in sent] == [(CHURCH, "pickup_code"), (CHURCH, "signin_code")]


# ─── 2. a text is not AI ──────────────────────────────────────────────

def _sms(biz, dollars):
    return {"business_id": biz, "cost_cents": dollars * 100.0, "endpoint": "sms", "units": 0}


def _ai(biz, dollars, endpoint="/chief/backend"):
    return {"business_id": biz, "cost_cents": dollars * 100.0, "endpoint": endpoint}


@pytest.fixture
def guard(monkeypatch):
    spend_guard._cache_at = 0.0
    spend_guard._cache_total_cents = 0.0
    spend_guard._cache_by_business = {}
    spend_guard._alerted.clear()
    monkeypatch.setattr(spend_guard, "_push_owner", lambda *a, **k: None)
    monkeypatch.delenv("SPEND_GUARD", raising=False)
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "50")
    monkeypatch.setenv("DAILY_SPEND_CAP_PER_BUSINESS_USD", "25")
    token = billing_context._CURRENT.set(None)
    yield
    billing_context._CURRENT.reset(token)
    spend_guard._cache_at = 0.0
    spend_guard._alerted.clear()


def test_a_2000_text_announcement_never_trips_the_spend_guard(monkeypatch, guard):
    """2,000 one-segment texts are $25: the per-church ceiling, half the
    platform's. The query leaves them out, and so does the sum."""
    paths = []
    usage = [_sms(CHURCH, 0.0125)] * 2000 + [_sms(OTHER, 30)] + [_ai(CHURCH, 2)]

    def read(path):
        paths.append(path)
        return usage                     # as if the database ignored the filter
    monkeypatch.setattr(spend_guard.sb_clients, "sb_get_as_service", read)
    assert spend_guard.over_budget(CHURCH) is False
    assert spend_guard.over_budget(OTHER) is False
    assert spend_guard.today_spend_cents(business_id=CHURCH) == pytest.approx(200.0)
    assert spend_guard.today_spend_cents() == pytest.approx(200.0)
    assert "endpoint=neq.sms" in paths[0] and "endpoint" in paths[0].split("select=")[1]


def test_ai_spend_still_trips_it(monkeypatch, guard):
    monkeypatch.setattr(spend_guard.sb_clients, "sb_get_as_service",
                        lambda path: [_sms(CHURCH, 5), _ai(CHURCH, 26)])
    assert spend_guard.over_budget(CHURCH) is True


def test_texts_never_draw_chief_credits(monkeypatch):
    paths = []

    def read(path):
        paths.append(path)
        return [{"endpoint": "sms", "units": 0}] * 500 + [{"endpoint": "sms"}] * 5 + \
               [{"endpoint": "/chief/backend", "units": None}]
    monkeypatch.setattr(usage_metering.sb_clients, "sb_get_as_service", read)
    assert usage_metering.weighted_usage_since(CHURCH, "2026-11-01T00:00:00Z") == pricing_config.chat_price()
    assert "endpoint=neq.sms" in paths[0]
    assert usage_metering.weight_for("sms") == 0
    assert usage_metering.weight_for_row({"endpoint": "sms"}) == 0


def test_the_low_credit_nudge_reads_past_texts(monkeypatch):
    seen = []
    monkeypatch.setattr(usage_metering.sb_clients, "sb_get_as_service",
                        lambda path: seen.append(path) or [])
    usage_metering.check_low_credit(CHURCH, {
        "allotment": 100, "grandfathered": False, "weighted_used": 95,
        "credits_balance": 0, "credits_burned_month": 0, "month": "2026-11"})
    last = [p for p in seen if "order=created_at.desc" in p]
    assert last and "endpoint=neq.sms" in last[0]


def test_texts_are_not_chief_messages(monkeypatch):
    paths = []
    monkeypatch.setattr(billing_limits.sb_clients, "sb_get_as_service",
                        lambda path: paths.append(path) or ([{"id": 1, "endpoint": "sms"}] * 3
                                                            + [{"id": 2, "endpoint": "/chief/backend"}]))
    assert billing_limits.chief_messages_this_month(CHURCH) == 1
    assert "endpoint=neq.sms" in paths[0]


@pytest.mark.parametrize("module", ["spend_guard.py", "usage_metering.py", "billing_limits.py",
                                    "launch_access.py", "ops_desk.py", "chief_quality.py"])
def test_every_ai_reader_of_api_usage_leaves_texts_out(module):
    """Readers that mean AI spend or AI use. The Costs view and margin's
    COGS keep texts: they are what the platform pays."""
    src = (ROOT / module).read_text(encoding="utf-8")
    assert "sms_usage.NOT_SMS" in src or '"endpoint": "neq.sms"' in src


# ─── 3. the monthly count ─────────────────────────────────────────────

def test_texts_this_month_counts_by_the_database(monkeypatch):
    seen = []
    monkeypatch.setattr(sb_clients, "sb_count_as_service", lambda path: seen.append(path) or 1234)
    now = datetime(2026, 11, 17, 15, 30, tzinfo=timezone.utc)
    assert sms_usage.texts_this_month(CHURCH, now=now) == 1234
    path = seen[0]
    assert path.startswith("/api_usage?")
    assert f"business_id=eq.{CHURCH}" in path and "endpoint=eq.sms" in path
    assert "created_at=gte.2026-11-01T00:00:00Z" in path


def test_texts_this_month_is_none_when_the_read_fails(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_count_as_service", lambda path: None)
    assert sms_usage.texts_this_month(CHURCH) is None

    def boom(path):
        raise RuntimeError("no service key")
    monkeypatch.setattr(sb_clients, "sb_count_as_service", boom)
    assert sms_usage.texts_this_month(CHURCH) is None
    assert sms_usage.texts_this_month("") is None


def test_segments_this_month_sums_every_row(monkeypatch):
    def read_all(path, *, key="id", strict=False, redact=False):
        assert "endpoint=eq.sms" in path and key == "id" and strict
        return [{"id": i, "input_tokens": 2} for i in range(1500)]
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", read_all)
    assert sms_usage.segments_this_month(CHURCH) == 3000

    def partial(path, **kw):
        raise sb_clients.PartialRead("a later page failed")
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", partial)
    assert sms_usage.segments_this_month(CHURCH) is None


def test_cost_since_is_none_on_a_short_read(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service",
                        lambda path, **kw: [{"id": 1, "input_tokens": 1, "cost_cents": 1.25},
                                            {"id": 2, "input_tokens": 3, "cost_cents": 3.75}])
    assert sms_usage.cost_since(30) == {"texts": 2, "segments": 4, "cost_cents": 5.0}

    def partial(path, **kw):
        raise sb_clients.PartialRead("a later page failed")
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", partial)
    assert sms_usage.cost_since(30) is None


# ─── sb_count_as_service: a count, or None ────────────────────────────

def _count_with(monkeypatch, handler):
    monkeypatch.setenv("SUPABASE_URL", "https://db.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setattr(sb_clients, "_pool", lambda: httpx.MockTransport(handler))
    return sb_clients.sb_count_as_service("/api_usage?endpoint=eq.sms&select=id")


def test_the_count_is_read_from_content_range(monkeypatch):
    seen = {}

    def handler(req):
        seen.update(method=req.method, prefer=req.headers.get("prefer"), auth=req.headers.get("authorization"))
        return httpx.Response(206, headers={"content-range": "0-0/42"})
    assert _count_with(monkeypatch, handler) == 42
    assert seen == {"method": "HEAD", "prefer": "count=exact", "auth": "Bearer service"}
    assert _count_with(monkeypatch, lambda req: httpx.Response(200, headers={"content-range": "*/0"})) == 0


def test_a_failed_count_is_none_not_zero(monkeypatch):
    assert _count_with(monkeypatch, lambda req: httpx.Response(500)) is None
    assert _count_with(monkeypatch, lambda req: httpx.Response(200)) is None

    def down(req):
        raise httpx.ConnectError("down")
    assert _count_with(monkeypatch, down) is None
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    assert sb_clients.sb_count_as_service("/api_usage?select=id") is None


# ─── the dial ─────────────────────────────────────────────────────────

def test_the_segment_cost_dial(monkeypatch):
    monkeypatch.delenv("COST_SMS_SEGMENT_CENTS", raising=False)
    monkeypatch.delenv("SMS_SEGMENT_CENTS", raising=False)
    assert pricing_config.sms_segment_cost_cents() == 1.25
    monkeypatch.setenv("SMS_SEGMENT_CENTS", "0.9")
    assert pricing_config.sms_segment_cost_cents() == 0.9
    monkeypatch.setenv("COST_SMS_SEGMENT_CENTS", "1.5")        # the namespaced name wins
    assert pricing_config.sms_segment_cost_cents() == 1.5
    for bad in ("abc", "-1", "inf"):
        monkeypatch.setenv("COST_SMS_SEGMENT_CENTS", bad)
        monkeypatch.delenv("SMS_SEGMENT_CENTS", raising=False)
        assert pricing_config.sms_segment_cost_cents() == 1.25
    assert pricing_config.snapshot()["costs"]["sms_segment_cents"] == 1.25

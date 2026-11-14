"""The sample church, BE-3: nothing in a sample is ever SENT, SPENT, PUBLISHED
or LEARNED FROM (sample_church.py, sample_church_guard.py, 2026-11-15).

Pinned here, one path at a time:
  · the provider seams refuse a sample, a fictional number and a reserved
    email domain (texts, mail, church mail, push, member push, AI);
  · no_card_trial holds a sample's site back and words it as a sample;
  · the member app, public giving, sign-ups, stations and screens refuse it;
  · Feed 2, semantic memory, the MCP caller and OAuth/pairing never see it;
  · platform counts leave it out; the sweep helpers (prime, drop_samples,
    exclude) work in one read;
  · the write guard (409 for any write that names a sample);
  · the last-visit stamp and the daily cleanup.
The end-to-end "nothing is ever sent" test and the job classification pin
live in test_sample_church_no_sends.py.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import sample_church as sc  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

ROOT = _here.parent
SAMPLE = "5a3b1e00-0000-4000-8000-00000000a001"
HOME = "5a3b1e00-0000-4000-8000-00000000b002"
REAL = "5a3b1e00-0000-4000-8000-00000000c003"
OWNER = "5a3b1e00-0000-4000-8000-00000000d004"


@pytest.fixture(autouse=True)
def _recipient_guard_on(monkeypatch):
    """conftest turns the made-up-recipient guard off for the rest of the
    suite; here it is the thing under test."""
    monkeypatch.setenv("MADE_UP_RECIPIENT_GUARD", "on")


class _DB(FakeSB):
    def __init__(self):
        super().__init__()
        self.reads = []

    def get(self, path):
        self.reads.append(path)
        return super().get(path)


@pytest.fixture
def db(monkeypatch):
    fb = _DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, redact=False: fb.get(p))
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="return=representation": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: (fb.patch(p, b), [b])[1])
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.setattr(sc, "_columns_ready", lambda: True)
    sc._reset_for_tests()
    fb.rows("businesses").extend([
        {"id": SAMPLE, "owner_id": OWNER, "name": sc.NAME, "type": "church", "is_sample": True,
         "sample_of": HOME, "is_active": False,
         "settings": {sc.SETTINGS_KEY: {"status": "ready", "created_at": "2026-11-01T00:00:00+00:00"}}},
        {"id": HOME, "owner_id": OWNER, "name": "Home", "type": "church", "is_sample": False,
         "sample_of": None, "is_active": True, "settings": {}},
        {"id": REAL, "owner_id": "someone", "name": "Real", "type": "church", "is_sample": False,
         "sample_of": None, "is_active": True, "settings": {}},
    ])
    return fb


# ─── Made-up recipients ───────────────────────────────────────────────

@pytest.mark.parametrize("number,fiction", [
    ("+13125550101", True), ("(312) 555-0199", True), ("312-555-0150", True),
    ("+13125550200", False), ("+13125550099", False), ("+13125551234", False),
    ("", False), (None, False), ("+447700900123", False),
])
def test_fictional_numbers_are_the_555_01xx_range(number, fiction):
    assert sc.fictional_phone(number) is fiction


@pytest.mark.parametrize("addr,reserved", [
    ("a@example.com", True), ("a@mail.example.org", True), ("A@EXAMPLE.NET", True),
    ("Pastor <p@grace.example>", True), ("x@church.test", True), ("x@y.invalid", True),
    ("x@localhost", True),
    ("a@gmail.com", False), ("a@example.church", False), ("a@notexample.com", False),
    ("a@testing.org", False), ("", False), (None, False), ("not-an-email", False),
])
def test_reserved_email_domains(addr, reserved):
    assert sc.reserved_email(addr) is reserved


def test_send_refusal_names_why(db):
    assert sc.send_refusal(REAL, phone="+13125550101") == "a made-up number"
    assert sc.send_refusal(REAL, email=["ok@gmail.com", "x@example.com"]) == "a made-up email address"
    assert sc.send_refusal(SAMPLE, email="ok@gmail.com") == "a sample church sends nothing"
    assert sc.send_refusal(REAL, phone="+13125551234", email="ok@gmail.com") is None
    assert sc.send_refusal(None, phone="+13125551234") is None


# ─── Texts ────────────────────────────────────────────────────────────

class _Twilio:
    def __init__(self):
        self.sent = []
        self.messages = self

    def create(self, **kw):
        self.sent.append(kw)

        class M:
            sid = "SM1"
        return M()


@pytest.fixture
def twilio(monkeypatch, db):
    import twilio_sms
    import sms_usage
    fake = _Twilio()
    monkeypatch.setattr(twilio_sms, "_twilio_client", lambda: fake)
    monkeypatch.setattr(twilio_sms, "platform_number", lambda: "+15550001111")
    monkeypatch.setattr(twilio_sms, "own_account_route", lambda n: None)
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MG1")
    costs = []
    monkeypatch.setattr(sms_usage, "record_send", lambda *a, **k: costs.append(a))
    return fake, costs


def test_send_sms_refuses_a_sample_church(twilio):
    import twilio_sms
    fake, costs = twilio
    with pytest.raises(sc.SendRefused):
        twilio_sms.send_sms("+13125551234", "hi", business_id=SAMPLE)
    assert fake.sent == [] and costs == []


def test_send_sms_refuses_a_fictional_number_for_everyone(twilio):
    import twilio_sms
    fake, _ = twilio
    for bid in (REAL, None):
        with pytest.raises(sc.SendRefused):
            twilio_sms.send_sms("+13125550142", "hi", business_id=bid)
    assert fake.sent == []


def test_send_sms_still_sends_a_real_text(twilio):
    import twilio_sms
    fake, costs = twilio
    assert twilio_sms.send_sms("+13125551234", "hi", business_id=REAL) == "SM1"
    assert len(fake.sent) == 1 and len(costs) == 1


# ─── Email ────────────────────────────────────────────────────────────

@pytest.fixture
def resend(monkeypatch, db):
    import email_sender
    posted = []

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"id": "em_1"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def post(self, url, **kw):
            posted.append((url, kw))
            return _Resp()

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _Client)

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(email_sender, "is_suppressed", _none)
    monkeypatch.setattr(email_sender, "_business_row_for_send", _none)

    async def _same(fe, fn, bid, rt):
        return fe, fn
    monkeypatch.setattr(email_sender, "_apply_business_identity", _same)
    return posted


def _send(**over):
    import email_sender
    kw = dict(to_email="pat@gmail.com", to_name=None, from_email="noreply@mysolutionist.app",
              from_name=None, subject="Hi", body="Hello", reply_to=None, business_id=REAL)
    kw.update(over)
    return asyncio.run(email_sender.send_via_resend(**kw))


def test_send_via_resend_refuses_a_sample(resend):
    with pytest.raises(sc.SendRefused):
        _send(business_id=SAMPLE)
    assert resend == []


@pytest.mark.parametrize("addr", ["a@example.com", "b@grace.test", "c@x.invalid"])
def test_send_via_resend_refuses_reserved_domains_for_everyone(resend, addr):
    for bid in (REAL, None):
        with pytest.raises(sc.SendRefused):
            _send(to_email=addr, business_id=bid)
    assert resend == []


def test_send_via_resend_still_sends_real_mail(resend):
    assert _send()["id"] == "em_1"
    assert len(resend) == 1


def test_church_mail_never_posts_to_a_reserved_address(monkeypatch):
    import church_mail
    called = []

    class _C:
        async def request(self, *a, **k):
            called.append(a)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    out = asyncio.run(church_mail._resend(_C(), "POST", "/emails", json={"to": ["Pat <p@example.org>"]}))
    assert out is None and called == []


def test_church_mail_copies_refuse_a_sample_church(db):
    import church_mail
    church = church_mail.Church({"id": SAMPLE, "name": sc.NAME, "settings": {}})
    why = asyncio.run(church_mail._send_refusal(church.id, "pat@gmail.com"))
    assert why == "a sample church sends nothing"
    assert asyncio.run(church_mail._send_refusal(REAL, "pat@gmail.com")) is None


def test_the_public_contact_form_refuses_a_sample(db, monkeypatch):
    import public_site
    import rate_limit
    monkeypatch.setattr(public_site, "_check_contact_rate", lambda ip: True)
    monkeypatch.setattr(rate_limit, "trusted_client_ip", lambda r: "1.1.1.1")
    resp = asyncio.run(public_site.contact_submit_endpoint(
        SAMPLE, {"name": "Pat", "email": "pat@gmail.com", "message": "hello"}, request=None))
    assert resp.status_code == 409


# ─── Push ─────────────────────────────────────────────────────────────

def test_push_refuses_a_sample(db, monkeypatch):
    import push_notifications as pn
    import member_push
    sent = []
    monkeypatch.setattr(pn, "push_enabled", lambda: True)
    monkeypatch.setattr(pn, "_send_one", lambda r, p: sent.append(r) or True)
    monkeypatch.setattr(member_push, "ready", lambda: True)
    db.rows("push_subscriptions").append({"business_id": SAMPLE, "user_id": OWNER, "endpoint": "e",
                                          "subscription": {}})
    assert pn.send_to_business(SAMPLE, title="t", body="b") == 0
    assert pn.send_to_user(OWNER, title="t", body="b", business_id=SAMPLE) == 0
    biz = dict(db.rows("businesses")[0], settings={"member_portal": {"notifications": {"news": True}}})
    assert member_push.send(biz, "news", title="t", body="b") == 0
    assert sent == []


# ─── AI spend ─────────────────────────────────────────────────────────

def test_can_interact_is_false_for_a_sample(db, monkeypatch):
    import usage_metering
    import feature_gates
    monkeypatch.setattr(feature_gates, "enforcement_on", lambda: False)
    assert usage_metering.can_interact(SAMPLE) is False
    assert usage_metering.can_interact(REAL) is True


@pytest.fixture
def anthropic_wire(monkeypatch):
    import httpx
    import llm_call
    calls = []

    def _post(url, **kw):
        calls.append(url)
        return httpx.Response(200, json={"content": [], "usage": {}}, request=httpx.Request("POST", url))
    monkeypatch.setattr(llm_call.httpx, "post", _post)
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    return calls


def test_llm_call_refuses_a_sample_before_the_call(db, anthropic_wire):
    import billing_context
    import llm_call
    r = llm_call.post({"model": "m", "messages": []}, business_id=SAMPLE)
    assert r.status_code == 403 and anthropic_wire == []
    with billing_context.bill_to(SAMPLE):
        assert llm_call.post({"model": "m", "messages": []}).status_code == 403
        with pytest.raises(llm_call.SampleSpendRefused):
            llm_call.sdk_client()
        assert isinstance(llm_call.astream(None, {"model": "m"}), llm_call._RefusedStream)
    assert anthropic_wire == []
    assert llm_call.post({"model": "m", "messages": []}, business_id=REAL).status_code == 200
    assert len(anthropic_wire) == 1


def test_llm_call_lets_the_sample_chief_lane_through(db, anthropic_wire):
    import llm_call
    with sc.allow_sample_chief():
        assert sc.sample_chief_allowed() is True
        assert llm_call.post({"model": "m", "messages": []}, business_id=SAMPLE).status_code == 200
    assert sc.sample_chief_allowed() is False
    assert len(anthropic_wire) == 1


def test_apost_refuses_a_sample(db):
    import llm_call

    class _C:
        def post(self, *a, **k):
            raise AssertionError("no call for a sample")
    r = asyncio.run(llm_call.apost(_C(), {"model": "m"}, business_id=SAMPLE))
    assert r.status_code == 403


def test_prewarm_warms_nothing_for_a_sample(db):
    import chief_of_staff as cos
    out = asyncio.run(cos.chief_prewarm_endpoint(cos.PrewarmRequest(business_id=SAMPLE), user_session=None))
    assert out == {"ok": True, "warmed": 0, "reason": "sample church"}


def test_ai_proxy_refuses_a_sample():
    src = (ROOT / "ai_proxy.py").read_text(encoding="utf-8")
    i = src.index("async def ai_proxy(")
    body = src[i:i + 6000]
    assert body.index('refuse_async(str(_cap_biz), "ai")') < body.index("billing_context.set_current")


# ─── The public web ───────────────────────────────────────────────────

def test_no_card_gates_hold_a_sample_back_in_its_own_words(db, monkeypatch):
    import no_card_trial as nct
    import usage_metering
    monkeypatch.setattr(usage_metering, "_biz_row", lambda bid: next(
        (dict(r) for r in db.rows("businesses") if r["id"] == bid), None))
    r = nct.blocks(SAMPLE)
    assert r is not None and r["is_sample"] is True
    assert nct.blocks(REAL) is None
    assert nct.card_message("texts", r) == sc.MESSAGE
    with pytest.raises(nct.CardRequired) as e:
        nct.check(SAMPLE, "texts")
    assert e.value.message == sc.MESSAGE

    async def _rows(client, method, path):
        return [dict(x) for x in db.get(path)]
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_as_service", _rows)
    nct._hidden_cache.clear()
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-secret-test-secret-test-secret")
    assert asyncio.run(nct.site_hidden(None, SAMPLE)) is True
    assert asyncio.run(nct.site_hidden(None, REAL)) is False
    tok = nct.preview_token(SAMPLE)
    assert asyncio.run(nct.preview_blocked(None, SAMPLE, None)) is True
    assert asyncio.run(nct.preview_blocked(None, SAMPLE, tok)) is False


def test_member_app_opens_a_sample_only_in_the_owners_preview(db, monkeypatch):
    import member_portal as mp
    import member_portal_preview as pv
    import public_site

    class _URL:
        path = "/my"

    class _Req:
        url = _URL()
        query_params = {}
        cookies = {}

    monkeypatch.setattr(public_site, "public_host", lambda r: "grace.mysolutionist.app")
    monkeypatch.setattr(public_site, "_is_api_host", lambda h: False)
    monkeypatch.setattr(public_site, "extract_slug_from_host", lambda r: "grace")
    biz = dict(db.rows("businesses")[0])
    db.rows("business_sites").append({"slug": "grace", "business_id": SAMPLE, "site_config": {},
                                      "business": biz})
    assert mp._church_for_request(_Req()) is None
    monkeypatch.setattr(pv, "read_session", lambda v, b, epoch=0, now=None: {"preview": True})
    assert mp._church_for_request(_Req())["business"]["id"] == SAMPLE


def test_public_signups_stations_and_screens_refuse_a_sample(db, monkeypatch):
    import kids_station
    import worship_show_router as wsr
    import church_event_signups as ces
    db.rows("checkin_stations").append({"id": "st1", "business_id": SAMPLE, "token_hash": kids_station.token_hash("t" * 40),
                                        "revoked_at": None, "last_seen_at": "2099-01-01T00:00:00+00:00", "mode": "staff"})
    with pytest.raises(HTTPException) as e:
        kids_station.station_from_token("t" * 40)
    assert e.value.status_code == 401
    monkeypatch.setattr(wsr, "mode", lambda: "on")
    db.rows("worship_screens").append({"business_id": SAMPLE, "token": "s" * 40, "archived_at": None})
    with pytest.raises(HTTPException) as e:
        wsr.screen_from_token("s" * 40)
    assert e.value.status_code == 404
    db.rows("business_sites").append({"slug": "grace", "business_id": SAMPLE, "site_config": {}})
    monkeypatch.setattr(ces, "_rows", lambda p: db.get(p))
    monkeypatch.setattr(ces, "_business", lambda bid: next(r for r in db.rows("businesses") if r["id"] == bid))
    with pytest.raises(HTTPException) as e:
        ces._public_church("grace")
    assert e.value.status_code == 404
    for f, needle in (("giving_router.py", "online giving isn't available here"),
                      ("events_rsvp_router.py", 'raise HTTPException(404, "not found")')):
        src = (ROOT / f).read_text(encoding="utf-8")
        assert "sample_church.is_sample_async" in src and needle in src


# ─── Integrations and learning ────────────────────────────────────────

def test_oauth_tickets_and_pairings_refuse_a_sample(db):
    import oauth_connect_ticket as oct
    with pytest.raises(HTTPException) as e:
        oct.mint(SAMPLE, OWNER)
    assert e.value.status_code == 409 and e.value.detail["error"] == "sample_church"
    assert oct.mint(REAL, OWNER)
    assert "sample_church.skip(business[0])" in (ROOT / "connected_ai.py").read_text(encoding="utf-8")


def test_mcp_never_resolves_to_a_sample(db, monkeypatch):
    import mcp_server
    monkeypatch.setenv("SUPABASE_URL", "https://db.example")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")

    class _R:
        status_code = 200

        def __init__(self, data):
            self._d = data

        def json(self):
            return self._d

    class _C:
        async def get(self, url, headers=None, params=None):
            if "owner_id" in params:
                return _R([dict(db.rows("businesses")[0]), dict(db.rows("businesses")[1])])
            return _R([r for r in db.rows("businesses") if f"eq.{r['id']}" == params["id"]])

    class _Caller:
        business_id = None
        user_id = OWNER
    got = asyncio.run(mcp_server._resolve_business(_C(), _Caller()))
    assert got["id"] == HOME
    _Caller.business_id = SAMPLE
    assert asyncio.run(mcp_server._resolve_business(_C(), _Caller())) is None


def test_feed2_never_learns_from_a_sample(db):
    import vertical_distill as vd
    assert vd.contributes({"id": SAMPLE, "type": "church", "is_sample": True, "settings": {}}) is False
    assert vd.contributes({"id": SAMPLE, "type": "church", "settings": {"feed2": {"contribute": True}}}) is False
    assert vd.contributes({"id": REAL, "type": "church", "settings": {}}) is True


def test_semantic_memory_never_embeds_a_samples(db, monkeypatch):
    import chief_memory_semantic as cms
    monkeypatch.setattr(cms, "embed", lambda t: (_ for _ in ()).throw(AssertionError("no embedding")))
    assert cms.match(SAMPLE, "anything") == []


def test_platform_counts_leave_samples_out(db, monkeypatch):
    import margin
    import church_founding
    import church_billing
    import sb_clients
    assert [b["id"] for b in margin._businesses()] == [HOME, REAL]
    asked = []
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", lambda p, **k: asked.append(p) or [])
    church_founding.taken()
    church_billing._founding_taken()
    assert len(asked) == 2 and all("is_sample=not.is.true" in p for p in asked)
    assert "is_sample=not.is.true" in (ROOT / "platform_money.py").read_text(encoding="utf-8")


# ─── The sweep helpers ────────────────────────────────────────────────

def test_drop_samples_reads_once_then_remembers(db):
    rows = [{"business_id": SAMPLE, "n": 1}, {"business_id": REAL, "n": 2},
            {"business_id": "not-a-business", "n": 3}, {"business_id": SAMPLE, "n": 4}]
    before = len(db.reads)
    assert [r["n"] for r in sc.drop_samples(rows)] == [2, 3]
    assert len(db.reads) - before == 1
    assert [r["n"] for r in sc.drop_samples(rows)] == [2, 3]
    assert len(db.reads) - before == 1                       # all remembered, both ways
    assert sc.drop_samples([SAMPLE, REAL]) == [REAL]
    assert sc.drop_sample_map({SAMPLE: 1, REAL: 2}) == {REAL: 2}
    own = [{"id": SAMPLE, "is_sample": True}, {"id": REAL, "is_sample": False}]
    assert sc.drop_samples(own, "id") == [own[1]]


def test_exclude_keeps_samples_out_of_a_sweeps_query(db):
    flt = sc.exclude()
    assert flt == f"&business_id=not.in.({SAMPLE})"
    db.rows("church_follow_ups").extend([{"business_id": SAMPLE}, {"business_id": REAL}])
    assert [r["business_id"] for r in db.get("/church_follow_ups?select=*" + flt)] == [REAL]
    sc._reset_for_tests()
    db.t["businesses"] = [r for r in db.rows("businesses") if not r.get("is_sample")]
    assert sc.exclude() == ""


# ─── READ_POSTS and the write guard ───────────────────────────────────

def test_read_posts_are_named_and_reach_the_app(db):
    assert len(sc.READ_POSTS) >= 10 and len(set(sc.READ_POSTS)) == len(sc.READ_POSTS)
    assert all(p.startswith("/") for p in sc.READ_POSTS)
    src = (ROOT / "sample_church.py").read_text(encoding="utf-8")
    assert '"read_posts": list(READ_POSTS)' in src
    for spends in ("/sms/draft", "/church-mail/draft", "/campaigns/plan", "/bank-statements/read",
                   "/receipts/scan", "/kids/this-week"):
        assert spends not in sc.READ_POSTS


def _guard_app():
    from starlette.applications import Starlette
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from sample_church_guard import SampleChurchGuard

    async def echo(request):
        raw = await request.body()
        return JSONResponse({"ok": True, "body": raw.decode("utf-8")})

    app = Starlette(routes=[Route("/{rest:path}", echo, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])])
    app.add_middleware(SampleChurchGuard)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    return app


def test_the_guard_refuses_every_write_that_names_a_sample(db):
    from starlette.testclient import TestClient
    c = TestClient(_guard_app())
    for method, url, kw in (
            ("POST", f"/contacts/{SAMPLE}", {}),
            ("DELETE", f"/x/{SAMPLE.upper()}/y", {}),
            ("PATCH", f"/things?business_id={SAMPLE}", {}),
            ("POST", "/things", {"json": {"business_id": SAMPLE, "x": 1}}),
            ("PUT", "/things", {"json": [{"businessId": SAMPLE}]}),
            ("POST", "/sms/draft", {"json": {"biz": SAMPLE}}),
    ):
        r = c.request(method, url, headers={"origin": "https://app.example"}, **kw)
        assert r.status_code == 409, (method, url)
        assert r.json() == {"detail": sc.detail("write")}
        assert r.headers.get("access-control-allow-origin") == "*"


def test_the_guard_lets_reads_real_churches_and_the_named_posts_through(db):
    from starlette.testclient import TestClient
    c = TestClient(_guard_app())
    assert c.get(f"/contacts/{SAMPLE}").status_code == 200
    r = c.post("/things", json={"business_id": REAL, "note": "kept"})
    assert r.status_code == 200 and json.loads(r.json()["body"]) == {"business_id": REAL, "note": "kept"}
    assert c.post(f"/program-outcomes/{SAMPLE}/preview", json={"business_id": SAMPLE}).status_code == 200
    assert c.post("/email/preview", json={"business_id": SAMPLE}).status_code == 200
    assert c.post("/agents/chief/chat", json={"business_id": SAMPLE}).status_code == 200
    assert c.post("/sample-church/ask", json={"business_id": SAMPLE}).status_code == 200
    # A big body streams through unread (its path and query are still read).
    big = {"business_id": SAMPLE, "pad": "x" * (300 * 1024)}
    r = c.post("/things", json=big)
    assert r.status_code == 200 and len(r.json()["body"]) > 300 * 1024
    assert c.post(f"/things/{SAMPLE}", content=b"raw", headers={"content-type": "text/plain"}).status_code == 409


def test_the_guard_marks_token_previews_noindex(db):
    from starlette.testclient import TestClient
    c = TestClient(_guard_app())
    assert c.get("/public/site/grace?pv=123.abc").headers.get("x-robots-tag") == "noindex"
    assert c.get(f"/sites/{SAMPLE}/preview?pv=1").headers.get("x-robots-tag") == "noindex"
    assert "x-robots-tag" not in c.get("/public/site/grace").headers


def test_the_guard_costs_one_read_then_none(db):
    from sample_church_guard import first_sample, _known_sample
    other = "5a3b1e00-0000-4000-8000-00000000e005"
    before = len(db.reads)
    assert first_sample([REAL, other]) is None
    assert len(db.reads) - before == 1
    assert _known_sample([REAL, other]) is None
    assert _known_sample([SAMPLE]) is False or _known_sample([SAMPLE]) == SAMPLE
    assert first_sample([REAL, SAMPLE]) == SAMPLE


def test_the_guard_sits_inside_cors_in_the_app():
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert src.index("app.add_middleware(SampleChurchGuard)") < src.index("app.add_middleware(\n    CORSMiddleware")


# ─── The last visit and the daily cleanup ─────────────────────────────

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def _s(**m):
    base = {"id": SAMPLE, "is_sample": True, "sample_of": HOME, "created_at": "2026-11-01T00:00:00+00:00",
            "settings": {sc.SETTINGS_KEY: {"status": "ready", **m}}}
    return base


@pytest.mark.parametrize("sample,home,why", [
    (_s(), {"id": HOME}, None),
    ({**_s(), "sample_of": None}, None, "home_gone"),
    (_s(), {"id": HOME, "subscription_status": "active"}, "home_pays"),
    (_s(), {"id": HOME, "stripe_subscription_id": "sub_1"}, "home_pays"),
    (_s(), {"id": HOME, "subscription_status": "canceled"}, None),
    (_s(status="ending", ended_at=(NOW - timedelta(hours=1)).isoformat()), {"id": HOME}, "ending"),
    (_s(status="ending", ended_at=(NOW - timedelta(minutes=2)).isoformat()), {"id": HOME}, None),
    (_s(last_seen_at=(NOW - timedelta(days=61)).isoformat()), {"id": HOME}, "idle"),
    (_s(last_seen_at=(NOW - timedelta(days=59)).isoformat()), {"id": HOME}, None),
    ({**_s(), "settings": {sc.SETTINGS_KEY: {"status": "pending",
                                             "created_at": (NOW - timedelta(days=70)).isoformat()}}},
     {"id": HOME}, "idle"),
    ({**_s(), "is_sample": False}, None, None),
])
def test_cleanup_reason(sample, home, why):
    assert sc.cleanup_reason(sample, home, NOW) == why


def test_cleanup_tick_deletes_through_the_one_delete_and_logs_counts(db, monkeypatch):
    deleted = []

    async def _delete(s):
        deleted.append(s["id"])
        return True
    monkeypatch.setattr(sc, "delete", _delete)
    gone = "5a3b1e00-0000-4000-8000-00000000f006"
    db.rows("businesses").append({"id": gone, "is_sample": True, "sample_of": "missing-home",
                                  "settings": {}, "created_at": NOW.isoformat()})
    db.rows("businesses")[1]["subscription_status"] = "active"
    out = asyncio.run(sc.cleanup_tick(NOW))
    assert sorted(deleted) == sorted([SAMPLE, gone])
    assert out == {"home_pays": 1, "home_gone": 1}
    assert REAL not in deleted and HOME not in deleted


def test_cleanup_deletes_nothing_when_the_read_fails(db, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, redact=False: None)
    monkeypatch.setattr(sc, "delete", lambda s: (_ for _ in ()).throw(AssertionError("deleted")))
    assert asyncio.run(sc.cleanup_tick(NOW)) == {}


def test_cleanup_kill_switch(db, monkeypatch):
    monkeypatch.setenv("SAMPLE_CHURCH_CLEANUP", "off")
    monkeypatch.setattr(sc, "delete", lambda s: (_ for _ in ()).throw(AssertionError("deleted")))
    assert asyncio.run(sc.cleanup_tick(NOW)) == {}


def test_cleanup_is_scheduled_daily():
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("sample_church_cleanup", _sample_church.cleanup_tick)' in src
    i = src.index('g("sample_church_cleanup"')
    assert '"cron", hour=' in src[i:i + 200]


def test_touch_stamps_a_ready_sample_at_most_twice_a_day(db):
    row = dict(db.rows("businesses")[0])
    assert sc.touch(row, NOW) is True
    assert row["settings"][sc.SETTINGS_KEY]["last_seen_at"] == NOW.isoformat()
    assert db.rows("businesses")[0]["settings"][sc.SETTINGS_KEY]["status"] == "ready"
    assert sc.touch(row, NOW + timedelta(hours=1)) is False
    assert sc.touch(row, NOW + timedelta(hours=13)) is True
    pending = {**row, "settings": {sc.SETTINGS_KEY: {"status": "pending"}}}
    assert sc.touch(pending, NOW) is False             # the seed's to write, never ours
    assert sc.touch({"id": REAL, "is_sample": False, "settings": {}}, NOW) is False
    assert sc.last_seen(row) == NOW + timedelta(hours=13)


def test_billing_access_block_stamps_the_visit():
    src = (ROOT / "sample_church.py").read_text(encoding="utf-8")
    i = src.index("def access_block(")
    assert "touch(sample)" in src[i:i + 900]


# The app's guard (solutionist-studio #1561) matches each entry as a PATH:
# exact, `{param}` segments, or a trailing `/*`. No methods, no query
# strings, no regexes; the server's guard matches the same way.
_READ_POST_SHAPE = __import__("re").compile(
    r"^(?:/(?:[A-Za-z0-9._~-]+|\{[A-Za-z_][A-Za-z0-9_]*\}))+(?:/\*)?$")


def test_every_read_post_is_a_plain_path_the_app_can_match():
    for p in sc.READ_POSTS:
        assert _READ_POST_SHAPE.match(p), p
        assert "?" not in p and " " not in p and not p.endswith("/")


def test_the_server_matches_read_posts_like_the_app():
    from sample_church_guard import allowed, _template_re
    assert _template_re("/groups/{id}/preview").match("/groups/abc/preview")
    assert not _template_re("/groups/{id}/preview").match("/groups/a/b/preview")
    assert _template_re("/search/*").match("/search/x/y") and _template_re("/search/*").match("/search")
    assert not _template_re("/email/preview").match("/email/preview/more")
    assert allowed("POST", f"/program-outcomes/{SAMPLE}/preview")
    assert allowed("POST", "/storage/v1/object/list/bucket")
    assert not allowed("DELETE", f"/program-outcomes/{SAMPLE}/preview")    # POSTs only
    assert not allowed("POST", "/email/send")

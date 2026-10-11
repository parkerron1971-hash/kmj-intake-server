"""Texting under each business's own name, step 4: its own number (2026-10-11).

Once a business's registration is approved, its number lives in its own
Twilio sub-account, on its own messaging service. Pinned here:
  1. The number it already has with us MOVES (its clients keep it), off our
     shared pool and onto its own service; without one, one is bought in its
     area code. Neither ever happens twice.
  2. Sends from a number in a sub-account go through that account and its
     service; our shared number's sends are untouched (no lookup at all).
  3. Webhooks for a business's own number are checked with that
     sub-account's token; ours with ours; an unknown account is refused.
  4. Releasing a number happens in the account that holds it.
  5. The registration: approval gives the number, records it, tells the
     owner once; a failure waits for the next sweep.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))      # the fake Twilio, shared with step 3

import texting_isv as ti  # noqa: E402
import texting_registration as tr  # noqa: E402
import twilio_sms  # noqa: E402
from test_texting_isv import PARENT, SUB, FakeTwilio  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
PN = "PN" + "7" * 32
MG = "MG" + "8" * 32


def run(x):
    return asyncio.run(x)


class NumbersTwilio(FakeTwilio):
    """The fake Twilio, plus phone numbers: in our account, in the
    sub-account, available to buy, and in services."""

    def __init__(self):
        super().__init__()
        self.ours = {PN: "+12165550100"}           # the business's number with us today
        self.theirs = {}                            # numbers in the sub-account
        self.in_service = []

    def __call__(self, method, url, *, auth=None, data=None, params=None, headers=None):
        path = re.sub(r"^https://[^/]+", "", url)
        m = re.fullmatch(rf"/2010-04-01/Accounts/{SUB}/IncomingPhoneNumbers/(PN\w+)\.json", path)
        if method == "GET" and m and m.group(1) not in self.theirs:
            self.calls.append((method, path, auth[0], [], {}))
            return httpx.Response(404, json={"code": 20404, "message": "The requested resource was not found"})
        if method == "POST" and re.fullmatch(r"/v1/Services/MG\w+/PhoneNumbers", path) \
                and dict(data or {}).get("PhoneNumberSid") in self.in_service:
            self.calls.append((method, path, auth[0], list(dict(data).items()), {}))
            return httpx.Response(409, json={"code": 21710, "message": "Phone Number is already in the Messaging Service"})
        return super().__call__(method, url, auth=auth, data=data, params=params, headers=headers)

    def answer(self, method, path, f, params):
        m = re.fullmatch(rf"/2010-04-01/Accounts/{PARENT}/IncomingPhoneNumbers/(PN\w+)\.json", path)
        if m and method == "POST":
            assert f == {"AccountSid": SUB}
            self.theirs[m.group(1)] = self.ours.pop(m.group(1))
            return {"sid": m.group(1), "account_sid": SUB}
        m = re.fullmatch(rf"/2010-04-01/Accounts/{SUB}/IncomingPhoneNumbers/(PN\w+)\.json", path)
        if m:
            return {"sid": m.group(1), "phone_number": self.theirs[m.group(1)], "account_sid": SUB}
        if path == f"/2010-04-01/Accounts/{SUB}/IncomingPhoneNumbers.json":
            if method == "GET":
                return {"incoming_phone_numbers": [{"sid": s, "phone_number": n} for s, n in self.theirs.items()]}
            sid = self.sid("PN")
            self.theirs[sid] = f["PhoneNumber"]
            return {"sid": sid, "phone_number": f["PhoneNumber"]}
        if path == f"/2010-04-01/Accounts/{SUB}/AvailablePhoneNumbers/US/Local.json":
            return {"available_phone_numbers": [{"phone_number": f"+1{params.get('AreaCode', '313')}5550199"}]}
        m = re.fullmatch(r"/v1/Services/(MG\w+)/PhoneNumbers", path)
        if m:
            self.in_service.append(f["PhoneNumberSid"])
            return {"sid": f["PhoneNumberSid"]}
        return super().answer(method, path, f, params)


@pytest.fixture
def tw(monkeypatch):
    fake = NumbersTwilio()
    monkeypatch.setattr(ti, "_http", fake)
    monkeypatch.setattr(ti, "_SUB_TOKENS", {})
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", PARENT)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "parenttoken")
    return fake


T = {"account_sid": SUB, "service_sid": MG}


# ── 1. the number moves in, or is bought there ────────────────────────

def test_the_number_it_has_moves_into_its_own_account(tw):
    t, saves = dict(T), []
    got = ti.ensure_number(t, platform_sid=PN, area_code="231", save=saves.append)
    assert got == {"sid": PN, "phone_number": "+12165550100", "moved": True}
    assert PN in tw.theirs and PN not in tw.ours and tw.in_service == [PN]
    [(m, path, user, form, _h)] = tw.posts(rf"Accounts/{PARENT}/IncomingPhoneNumbers")
    assert user == PARENT and dict(form) == {"AccountSid": SUB}          # moved by us, into theirs
    assert [c for c in tw.posts(r"PhoneNumbers$") if c[2] == SUB]          # attached as the business
    assert not tw.posts(r"Accounts/AC\w+/IncomingPhoneNumbers\.json$")      # nothing bought
    n = len(tw.calls)
    ti.ensure_number(t, platform_sid=PN, area_code="231", save=saves.append)
    assert [c for c in tw.calls[n:] if c[0] == "POST"] == []               # never twice


def test_a_move_cut_short_is_finished_not_repeated(tw):
    t = dict(T)
    tw.theirs[PN] = tw.ours.pop(PN)                                        # moved, then a crash
    got = ti.ensure_number(t, platform_sid=PN, area_code=None, save=lambda x: None)
    assert got["phone_number"] == "+12165550100" and not tw.posts(rf"Accounts/{PARENT}/IncomingPhoneNumbers")


def test_without_a_number_one_is_bought_in_its_area_code_once(tw):
    t = dict(T)
    got = ti.ensure_number(t, platform_sid=None, area_code="231", save=lambda x: None)
    assert got["phone_number"] == "+12315550199" and got["moved"] is False
    [(m, path, user, form, _h)] = tw.posts(rf"Accounts/{SUB}/IncomingPhoneNumbers\.json$")
    f = dict(form)
    assert user == SUB and f["SmsUrl"].endswith("/webhooks/twilio/sms") and f["StatusCallback"].endswith(
        "/webhooks/twilio/status")
    lost = dict(T)                                                         # a run that lost the id
    assert ti.ensure_number(lost, platform_sid=None, area_code="231", save=lambda x: None)["sid"] == got["sid"]
    assert len(tw.posts(rf"Accounts/{SUB}/IncomingPhoneNumbers\.json$")) == 1


# ── 2. sending from it ────────────────────────────────────────────────

class _Msgs:
    def __init__(self, who, log):
        self.who, self.log = who, log

    def create(self, **kw):
        self.log.append((self.who, kw))
        return SimpleNamespace(sid=f"SM_{self.who}")


@pytest.fixture
def sends(monkeypatch):
    log, lookups = [], []
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550001111")
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MG_platform")
    monkeypatch.setattr(twilio_sms, "_twilio_client", lambda: SimpleNamespace(messages=_Msgs("platform", log)))
    monkeypatch.setattr(twilio_sms, "_account_client", lambda acct: SimpleNamespace(messages=_Msgs(acct, log)))
    monkeypatch.setattr(twilio_sms, "_ROUTES", {})

    def get(path):
        lookups.append(path)
        return [{"account_sid": SUB, "messaging_service_sid": MG}] if "%2B12165550100" in path else []

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    return log, lookups


def test_a_text_from_its_own_number_goes_through_its_own_account(sends):
    log, lookups = sends
    assert twilio_sms.send_sms("+15559998888", "hi", from_number="+12165550100") == f"SM_{SUB}"
    assert log == [(SUB, {"to": "+15559998888", "body": "hi", "messaging_service_sid": MG, "from_": "+12165550100"})]
    twilio_sms.send_sms("+15559998888", "again", from_number="+12165550100")
    assert len(lookups) == 1                                               # cached
    twilio_sms.send_sms("+15559998888", "shared")                          # our number: no lookup at all
    twilio_sms.send_sms("+15559998888", "theirs", from_number="+13135550123")   # a number on our account
    assert [w for w, _ in log[1:]] == [SUB, "platform", "platform"]
    assert log[2][1]["messaging_service_sid"] == "MG_platform" and len(lookups) == 2


def test_an_unreadable_lookup_falls_back_to_today(monkeypatch, sends):
    log, _ = sends

    def boom(path):
        raise RuntimeError("SUPABASE down")

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    twilio_sms.send_sms("+15559998888", "hi", from_number="+12165550100")
    assert log[0][0] == "platform"                                         # never blocks a send
    assert "+12165550100" not in twilio_sms._ROUTES                       # and isn't remembered


# ── 3. webhooks for it ────────────────────────────────────────────────

def _signed(token, url, params):
    from twilio.request_validator import RequestValidator
    return RequestValidator(token).compute_signature(url, params)


def test_each_account_is_checked_with_its_own_token(monkeypatch):
    import sb_clients
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", PARENT)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "parenttoken")
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: [{"id": 1}] if f"account_sid=eq.{SUB}" in path else [])
    monkeypatch.setattr(ti, "sub_token", lambda acct: "subtoken")
    assert twilio_sms.webhook_token(None) == "parenttoken" and twilio_sms.webhook_token(PARENT) == "parenttoken"
    assert twilio_sms.webhook_token(SUB) == "subtoken"
    assert twilio_sms.webhook_token("AC" + "3" * 32) is None                # not one of ours
    assert twilio_sms.webhook_token("AC1);drop") is None

    app = FastAPI()
    app.include_router(twilio_sms.router)
    client = TestClient(app)
    import sms_routing
    routed = []

    async def route_inbound(**kw):
        routed.append(kw)
        return {}

    monkeypatch.setattr(sms_routing, "route_inbound", route_inbound)
    url = "http://testserver/webhooks/twilio/sms"
    for acct, token, expect in ((SUB, "subtoken", 200), (SUB, "parenttoken", 403), (PARENT, "parenttoken", 200),
                                ("AC" + "3" * 32, "parenttoken", 403)):
        params = {"AccountSid": acct, "From": "+15559998888", "To": "+12165550100", "Body": "hi", "MessageSid": "SM1"}
        r = client.post("/webhooks/twilio/sms", data=params, headers={"X-Twilio-Signature": _signed(token, url, params)})
        assert r.status_code == expect, (acct, token)
    assert len(routed) == 2


# ── 4. releasing it ───────────────────────────────────────────────────

def test_releasing_happens_where_the_number_is(monkeypatch):
    seen = []

    def client_for(name):
        return SimpleNamespace(incoming_phone_numbers=lambda sid: SimpleNamespace(
            delete=lambda: seen.append((name, sid))))

    monkeypatch.setattr(twilio_sms, "_account_client", lambda acct: client_for(acct))
    monkeypatch.setattr(twilio_sms, "_twilio_admin_client", lambda: client_for("ours"))
    twilio_sms.release_number(PN, SUB)
    twilio_sms.release_number(PN)
    assert seen == [(SUB, PN), ("ours", PN)]
    twilio_sms.detach_from_service(PN, SUB)                                # nothing to detach from our pool
    src = pathlib.Path(twilio_sms.__file__).resolve().parent
    for f in ("sms_numbers_router.py", "account_lifecycle.py"):
        text = src.joinpath(f).read_text(encoding="utf-8")
        assert "release_number, sid, *extra)" in text and "provider_sid,account_sid" in text, f


# ── 5. the registration gives it ──────────────────────────────────────

BUSINESS = {"id": BIZ, "name": "KMJ Creative Solutions", "owner_id": "u1", "settings": {}}
ROW = {"status": "approved", "answers": {"rep_phone": "+12315550100"},
       "twilio": {"account_sid": SUB, "service_sid": MG, "brand_sid": "BN1"}}


@pytest.fixture
def give(monkeypatch):
    state = {"saved": [], "told": [], "patches": [], "posts": [], "detached": [], "line": None}
    monkeypatch.setattr(tr, "_saver", lambda bid: state["saved"].append)
    monkeypatch.setattr(tr, "_platform_line", lambda bid: state["line"])

    async def tell(biz, status, reasons=None, number=None):
        state["told"].append((status, number))
        return {}

    monkeypatch.setattr(tr, "_tell_owner", tell)
    monkeypatch.setattr(tr.sb_clients, "sb_patch_as_service", lambda p, b: state["patches"].append((p, b)) or [b])
    monkeypatch.setattr(tr.sb_clients, "sb_post_as_service", lambda p, b, *a: state["posts"].append((p, b)) or [b])
    monkeypatch.setattr(twilio_sms, "detach_from_service", lambda pn, acct=None: state["detached"].append(pn))
    return state


def test_approval_moves_its_number_records_it_and_tells_the_owner_once(give, monkeypatch):
    give["line"] = {"id": "n1", "phone_number": "+12165550100", "provider_sid": PN}
    calls = []

    def ensure(t, **kw):
        calls.append(kw)
        t.update(number_sid=PN, number="+12165550100", number_moved=True)
        return {"sid": PN, "phone_number": "+12165550100", "moved": True}

    monkeypatch.setattr(tr.texting_isv, "ensure_number", ensure)
    assert run(tr._give_number(BUSINESS, ROW)) is True
    assert give["detached"] == [PN] and calls == [{"platform_sid": PN, "area_code": "231",
                                                    "save": calls[0]["save"]}]
    [(path, fields)] = give["patches"]
    assert path == "/sms_numbers?id=eq.n1" and fields["account_sid"] == SUB and fields["messaging_service_sid"] == MG
    assert give["saved"][-1]["number_ready"] is True and give["told"] == [("number_ready", "+12165550100")]
    assert run(tr._give_number(BUSINESS, {**ROW, "twilio": give["saved"][-1]})) is True
    assert len(give["told"]) == 1                                          # once


def test_without_a_number_one_is_recorded_new(give, monkeypatch):
    monkeypatch.setattr(tr.texting_isv, "ensure_number",
                        lambda t, **kw: {"sid": "PN9", "phone_number": "+12315550199", "moved": False})
    assert run(tr._give_number(BUSINESS, ROW)) is True
    [(path, row)] = give["posts"]
    assert path == "/sms_numbers" and row["status"] == "active" and row["account_sid"] == SUB
    assert row["phone_number"] == "+12315550199" and row["area_code"] == "231" and give["detached"] == []


def test_a_number_that_cant_be_set_up_waits_for_the_next_sweep(give, monkeypatch):
    def down(t, **kw):
        raise ti.TwilioDown("no local numbers available right now")

    monkeypatch.setattr(tr.texting_isv, "ensure_number", down)
    assert run(tr._give_number(BUSINESS, ROW)) is False and give["told"] == [] and give["posts"] == []


def test_the_owner_hears_the_number_in_plain_words(monkeypatch):
    posts = []
    monkeypatch.setattr(tr.sb_clients, "sb_post_as_service", lambda p, r, *a: posts.append(r) or [r])
    import push_notifications
    monkeypatch.setattr(push_notifications, "send_to_business", lambda bid, **kw: 0)
    import email_domain_monitor

    async def no_email(uid):
        return None

    monkeypatch.setattr(email_domain_monitor, "_owner_email", no_email)
    run(tr._tell_owner(BUSINESS, "number_ready", number="+12165550100"))
    assert posts[0]["title"] == "Your texts now go out under KMJ Creative Solutions"
    assert posts[0]["body"].startswith("(216) 555-0100 is now KMJ Creative Solutions's own registered number.")


def test_approval_and_a_waiting_number_are_both_moved_along(monkeypatch):
    given = []

    async def give_number(biz, row):
        given.append(row["status"])
        return True

    async def check(biz, row):
        return "approved"

    rows = iter([{"status": "campaign_pending", "twilio": {"brand_sid": "BN1"}},
                 {"status": "approved", "twilio": {"brand_sid": "BN1"}}])
    monkeypatch.setattr(tr, "registration", lambda bid: next(rows))
    monkeypatch.setattr(tr, "_business", lambda bid: BUSINESS)
    monkeypatch.setattr(tr, "_check", check)
    monkeypatch.setattr(tr, "_give_number", give_number)
    assert run(tr.advance(BIZ)) == "approved" and given == ["approved"]
    monkeypatch.setattr(tr, "registration", lambda bid: {"status": "approved", "twilio": {"number_ready": True}})
    assert run(tr.advance(BIZ)) == "approved" and given == ["approved"]           # ready: left alone
    src = pathlib.Path(tr.__file__).read_text(encoding="utf-8")
    assert "and(status.eq.approved,twilio->>number_ready.is.null)" in src           # the sweep finds them

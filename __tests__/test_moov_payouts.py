"""Moov payouts in test mode (moov_payouts.py, moov_client.py).

Kevin, 2026-11-27: a church pays its 1099 people through Moov, from the
church's own bank; off by default, each church opts in.

Pins:
  * off unless MOOV_PAYOUTS opens it AND the church opts in; live mode refused
  * who: the owner sets up (opt-in, Moov's form, caps); the owner or an Admin
    sends, with the pay step-up for this church; an accountant sees; a Member
    and a Manager neither send nor confirm the step-up
  * the whole path against a fake Moov: church onboarded, payee onboarded,
    quote with fees, next-day send, completed -> the bill is paid with
    paid_via 'moov', 1099 eligible, contractor linked, and the 1099 summary
    counts it once
  * once: the same request id never pays twice; a bill can't be sent twice
  * never from us: a source that isn't the church's own payment method, or the
    partner account, is refused before Moov is asked to move money
  * caps per payment and per day; the owner can't raise them past the platform
  * failures and returns put the bill back (cancelled if made here)
  * the webhook: dropped with no secret, refused with a bad signature, and a
    good one only makes us read Moov (the body's status is never copied)
  * no key in a log line

Every name, id and figure here is made up.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import pathlib
import sys
import time
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from payroll_free_fake import PayrollFake  # noqa: E402

import church_money_gate as gate  # noqa: E402
import ledger_unlock  # noqa: E402
import moov_client  # noqa: E402
import moov_payouts as mp  # noqa: E402
import sb_clients  # noqa: E402


def uid() -> str:
    return str(uuid.uuid4())


CHURCH, SHOP = uid(), uid()
OWNER, ADMIN, ACCOUNTANT, MANAGER, MEMBER = (uid() for _ in range(5))
ROLE = {OWNER: "owner", ADMIN: "admin", ACCOUNTANT: "accountant", MANAGER: "manager", MEMBER: "member"}
PARTNER = "moov-partner-0001"
SECRET_PRIVATE = "sk-private-made-up-9f8e7d"
WEBHOOK_SECRET = "whsec-made-up"

UNIQUE = {"moov_payouts": ("idempotency_key",), "moov_webhook_events": ("event_id",)}


class DB(PayrollFake):
    def post(self, path, body, prefer="return=representation", **kw):
        table = self._table(path)
        for col in UNIQUE.get(table, ()):
            if any(str(r.get(col)) == str(body.get(col)) for r in self.rows(table)):
                return None
        if table == "moov_payouts" and body.get("bill_id"):
            if any(r.get("bill_id") == body["bill_id"] and r.get("status") in mp.LIVE
                   for r in self.rows(table)):
                return None
        if table == "moov_webhook_events":
            row = dict(body)
            self.rows(table).append(row)
            return [row]
        return super().post(path, body, prefer, **kw)


class FakeMoov:
    """Just enough of Moov's API: invites, accounts, payment methods, transfer
    options, transfers (with the idempotency key), and a transfer read."""

    def __init__(self) -> None:
        self.invites: Dict[str, Dict[str, Any]] = {}
        self.methods: Dict[str, List[Dict[str, Any]]] = {}
        self.transfers: Dict[str, Dict[str, Any]] = {}
        self.by_key: Dict[str, str] = {}
        self.calls: List[tuple] = []
        self.refuse_transfer = 0
        self.headers: List[Dict[str, str]] = []

    def redeem(self, code: str, account_id: str, methods: List[Dict[str, Any]]) -> None:
        self.invites[code]["redeemedAccountID"] = account_id
        self.methods[account_id] = methods

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        self.calls.append((method, path))
        self.headers.append(dict(req.headers))
        body = json.loads(req.content) if req.content else {}
        if method == "POST" and path == "/onboarding-invites":
            code = f"inv{len(self.invites) + 1}"
            self.invites[code] = {"code": code, "link": f"https://moov.test/onboard/{code}", "body": body}
            return httpx.Response(200, json=self.invites[code])
        if method == "GET" and path.startswith("/onboarding-invites/"):
            return httpx.Response(200, json=self.invites[path.rsplit("/", 1)[1]])
        parts = path.strip("/").split("/")
        if method == "GET" and len(parts) == 2 and parts[0] == "accounts":
            return httpx.Response(200, json={"accountID": parts[1], "capabilities": [
                {"capability": c, "status": "enabled"} for c in ("transfers", "send-funds.ach", "wallet.balance")]})
        if method == "GET" and len(parts) == 3 and parts[2] == "payment-methods":
            return httpx.Response(200, json=self.methods.get(parts[1], []))
        if method == "POST" and parts[-1] == "transfer-options":
            assert parts[1] == PARTNER
            return httpx.Response(200, json={
                "sourceOptions": self.methods.get(body["source"]["accountID"], []),
                "destinationOptions": self.methods.get(body["destination"]["accountID"], [])})
        if method == "POST" and parts[-1] == "transfers":
            key = req.headers["x-idempotency-key"]
            if key in self.by_key:
                return httpx.Response(409, json=self.transfers[self.by_key[key]])
            if self.refuse_transfer:
                return httpx.Response(self.refuse_transfer, json={"error": "nope"})
            tid = f"tr{len(self.transfers) + 1}"
            self.transfers[tid] = {"transferID": tid, "status": "pending", "body": body}
            self.by_key[key] = tid
            return httpx.Response(200, json=self.transfers[tid])
        if method == "GET" and len(parts) == 4 and parts[2] == "transfers":
            return httpx.Response(200, json=self.transfers[parts[3]])
        return httpx.Response(404, json={})


CHURCH_METHODS = [{"paymentMethodID": "pm-church-debit", "paymentMethodType": "ach-debit-fund"}]
PAYEE_METHODS = [{"paymentMethodID": "pm-payee-std", "paymentMethodType": "ach-credit-standard"},
                 {"paymentMethodID": "pm-payee-sd", "paymentMethodType": "ach-credit-same-day"}]


@pytest.fixture
def env(monkeypatch):
    db = DB()
    db.t["businesses"] = [{"id": CHURCH, "name": "Grace Hill Church", "type": "church", "owner_id": OWNER},
                          {"id": SHOP, "name": "Fade Shop", "type": "barber", "owner_id": OWNER}]
    db.t["contractors"] = [{"id": uid(), "business_id": CHURCH, "name": "Sam Rivers", "email": "sam@example.test",
                            "is_1099_eligible": True, "default_category": "operating"}]
    for name, fn in (("sb_get_as_service", db.get), ("sb_post_as_service", db.post),
                     ("sb_patch_as_service", db.patch)):
        monkeypatch.setattr(sb_clients, name, fn)
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", lambda path, **k: db.get(path))
    # The money gate, answered from its own rule table by each person's standing.
    def require_money(biz, user, need, part, **k):
        rule = gate._rule(need, part)
        if ROLE.get(str(user.id)) not in rule.who:
            raise HTTPException(rule.status, rule.detail)
        return gate.Pass(by=ROLE[str(user.id)], role=None, business=None)
    def may_money(biz, user, need, part, **k):
        try:
            require_money(biz, user, need, part)
            return True
        except HTTPException:
            return False
    monkeypatch.setattr(gate, "require_money", require_money)
    monkeypatch.setattr(gate, "may_money", may_money)
    import audit_log, billing_limits, period_lock, financial_policy
    audits: List[Dict[str, Any]] = []
    monkeypatch.setattr(audit_log, "record", lambda biz, **k: audits.append({"biz": biz, **k}) or True)
    monkeypatch.setattr(billing_limits, "require_feature", lambda *a: None)
    monkeypatch.setattr(financial_policy, "require_operational_write", lambda *a: None)
    monkeypatch.setattr(period_lock, "locked_period", lambda *a: None)
    monkeypatch.setattr(ledger_unlock, "_secret", lambda: b"moov-test-step-up-key")
    moov = FakeMoov()
    monkeypatch.setattr(moov_client, "_transport", httpx.MockTransport(moov.handler))
    for k, v in {"MOOV_PAYOUTS": "on", "MOOV_PUBLIC_KEY": "pk-made-up", "MOOV_PRIVATE_KEY": SECRET_PRIVATE,
                 "MOOV_PARTNER_ACCOUNT_ID": PARTNER, "MOOV_FEE_PLAN_CODES": "plan-1",
                 "MOOV_WEBHOOK_SECRET": WEBHOOK_SECRET}.items():
        monkeypatch.setenv(k, v)
    for k in ("MOOV_MODE", "MOOV_MAX_PAYMENT_USD", "MOOV_MAX_DAILY_USD", "MOOV_AMOUNT_SHAPE",
              "WEBHOOK_ALLOW_UNSIGNED"):
        monkeypatch.delenv(k, raising=False)
    return SimpleNamespace(db=db, moov=moov, audits=audits, contractor=db.t["contractors"][0]["id"])


def u(who: str) -> SimpleNamespace:
    return SimpleNamespace(id=who, email=f"{ROLE[who]}@example.test")


def unlocked(who: str, scope: str = ledger_unlock.SCOPE_PAY, biz: str = CHURCH) -> Request:
    token = ledger_unlock.mint(who, scope=scope, business_id=biz)["token"]
    return Request({"type": "http", "headers": [(b"x-ledger-unlock", token.encode())]})


def ready(e) -> None:
    """The church and its payee onboarded at the fake Moov."""
    mp.church_opt_in(mp.OptInBody(business_id=CHURCH, on=True), u(OWNER))
    link = mp.church_onboarding(mp.BizBody(business_id=CHURCH), u(OWNER))["link"]
    e.moov.redeem(link.rsplit("/", 1)[1], "moov-church-1", CHURCH_METHODS)
    church = mp.church_refresh(mp.BizBody(business_id=CHURCH), u(OWNER))["church"]
    assert church["status"] == "active" and church["bank_ready"]
    import asyncio
    out = asyncio.run(mp.payee_invite(e.contractor, mp.BizBody(business_id=CHURCH), u(ADMIN)))
    e.moov.redeem(out["link"].rsplit("/", 1)[1], "moov-payee-1", PAYEE_METHODS)
    payee = mp.payee_refresh(e.contractor, mp.BizBody(business_id=CHURCH), u(ADMIN))["payee"]
    assert payee["status"] == "active" and payee["bank_ready"]


def send(e, who=ADMIN, amount=150.0, key="key-0001", **kw):
    body = mp.PayBody(business_id=CHURCH, contractor_id=e.contractor, amount=amount, idempotency_key=key, **kw)
    return mp.pay(body, unlocked(who), u(who))


def bills(e) -> List[Dict[str, Any]]:
    return e.db.t.get("bills", [])


# ─── Off by default ───────────────────────────────────────────────────

def test_off_unless_the_switch_opens_it_and_the_church_opts_in(env, monkeypatch):
    monkeypatch.delenv("MOOV_PAYOUTS")
    assert mp.status(CHURCH, u(OWNER)) == {"ok": True, "switched_on": False}
    with pytest.raises(HTTPException) as e:
        send(env)
    assert e.value.status_code == 404
    monkeypatch.setenv("MOOV_PAYOUTS", "on")
    st = mp.status(CHURCH, u(OWNER))
    assert st["switched_on"] and st["mode"] == "test" and st["church"]["opted_in"] is False
    with pytest.raises(HTTPException) as e:
        send(env)
    assert e.value.status_code == 409 and e.value.detail == mp.NOT_OPTED_IN
    assert mp.status(SHOP, u(OWNER)) == {"ok": True, "switched_on": False}      # churches only


def test_owner_switch_is_the_platform_owners_churches_only(env, monkeypatch):
    monkeypatch.setenv("MOOV_PAYOUTS", "owner")
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: False)
    assert mp.status(CHURCH, u(OWNER))["switched_on"] is False
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: True)
    assert mp.status(CHURCH, u(OWNER))["switched_on"] is True


def test_live_mode_is_refused_in_this_build(env, monkeypatch):
    assert moov_client.LIVE_ALLOWED is False
    monkeypatch.setenv("MOOV_MODE", "live")
    assert not moov_client.configured() and moov_client.why_not() == moov_client.LIVE_REFUSED
    with pytest.raises(HTTPException) as e:
        moov_client.get_account("anything")
    assert e.value.status_code == 503
    assert env.moov.calls == []


# ─── Who ──────────────────────────────────────────────────────────────

def test_only_the_owner_sets_up_and_only_the_owner_or_an_admin_sends(env):
    for who in (ADMIN, ACCOUNTANT, MANAGER, MEMBER):
        with pytest.raises(HTTPException) as e:
            mp.church_opt_in(mp.OptInBody(business_id=CHURCH, on=True), u(who))
        assert e.value.status_code == 403
    ready(env)
    for who in (ACCOUNTANT, MANAGER, MEMBER):
        with pytest.raises(HTTPException) as e:
            send(env, who=who)
        assert e.value.status_code == 403
    assert mp.list_payouts(CHURCH, u(ACCOUNTANT))["payouts"] == []                  # the accountant sees
    with pytest.raises(HTTPException):
        mp.list_payouts(CHURCH, u(MEMBER))
    assert send(env, who=OWNER, key="key-owner-1")["ok"]
    assert send(env, who=ADMIN, key="key-admin-1")["ok"]


def test_sending_needs_the_pay_step_up_for_this_church(env):
    ready(env)
    body = mp.PayBody(business_id=CHURCH, contractor_id=env.contractor, amount=10, idempotency_key="key-step")
    for req in (Request({"type": "http", "headers": []}),
                unlocked(ADMIN, scope=ledger_unlock.SCOPE_DANGER),
                unlocked(ADMIN, biz=SHOP),
                unlocked(OWNER)):                                   # someone else's proof
        with pytest.raises(HTTPException) as e:
            mp.pay(body, req, u(ADMIN))
        assert e.value.status_code == 403 and e.value.detail["code"] == "ledger_locked"
        assert e.value.detail["scope"] == "pay"
    assert env.moov.transfers == {}


def test_an_admin_may_confirm_the_pay_step_up_and_a_manager_may_not(env, monkeypatch):
    seats = {ADMIN: "admin", MANAGER: "manager"}
    def get(path, **k):
        if path.startswith("/business_users"):
            who = next(w for w in seats if w in path)
            return [{"role": seats[who]}]
        return env.db.get(path)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    assert ledger_unlock._require_actor(CHURCH, ADMIN, ledger_unlock.SCOPE_PAY)
    with pytest.raises(HTTPException):
        ledger_unlock._require_actor(CHURCH, MANAGER, ledger_unlock.SCOPE_PAY)
    with pytest.raises(HTTPException):
        ledger_unlock._require_actor(CHURCH, ADMIN, ledger_unlock.SCOPE_DANGER)   # danger stays the owner's
    assert ledger_unlock.SCOPE_PAY in ledger_unlock.BOUND_SCOPES


# ─── The whole path ───────────────────────────────────────────────────

def test_next_day_send_then_completed_records_one_paid_1099_bill(env):
    ready(env)
    q = mp.quote_payout(mp.QuoteBody(business_id=CHURCH, contractor_id=env.contractor, amount=150), u(ADMIN))
    fees = {s["speed"]: (s["fee"], s["available"]) for s in q["speeds"]}
    assert fees == {"next_day": (0.25, True), "same_day": (0.40, True), "instant": (1.43, False)}
    out = send(env, amount=150)
    p = out["payout"]
    assert p["status"] == "pending" and p["speed"] == "next_day" and p["fee_estimate"] == 0.25
    sent = env.moov.transfers["tr1"]["body"]
    assert sent["source"] == {"paymentMethodID": "pm-church-debit"}
    assert sent["destination"] == {"paymentMethodID": "pm-payee-std"}
    assert sent["amount"] == {"currency": "USD", "valueDecimal": "150.00"}
    [bill] = bills(env)
    assert bill["status"] == "scheduled" and bill["contractor_id"] == env.contractor and bill["is_1099_eligible"]

    env.moov.transfers["tr1"]["status"] = "completed"
    p = mp.refresh(p["id"], mp.BizBody(business_id=CHURCH), u(ADMIN))["payout"]
    assert p["status"] == "completed" and p["status_words"] == "Paid"
    [bill] = bills(env)
    assert (bill["status"], bill["paid_via"], bill["paid_amount"]) == ("paid", "moov", 150.0)
    mp.refresh(p["id"], mp.BizBody(business_id=CHURCH), u(ADMIN))            # again: nothing changes
    assert len(bills(env)) == 1

    import reports_router
    year = int(bill["paid_at"][:4])
    summary = reports_router._summary_1099(CHURCH, year)
    assert [(r["contractor_id"], r["total_paid"], r["payments"]) for r in summary["rows"]] == [
        (env.contractor, 150.0, 1)]
    verbs = [a["verb"] for a in env.audits]
    assert "moov_payout_sent" in verbs and "moov_payout_completed" in verbs


def test_paying_a_bill_marks_that_bill_and_makes_no_other(env):
    ready(env)
    env.db.t["bills"] = [{"id": uid(), "business_id": CHURCH, "vendor_name": "Sam Rivers", "amount": 80,
                          "status": "pending", "category": "operating", "is_1099_eligible": False}]
    bid = env.db.t["bills"][0]["id"]
    with pytest.raises(HTTPException) as e:
        send(env, amount=79, bill_id=bid)
    assert e.value.status_code == 409                                  # the amount must match
    p = send(env, amount=80, bill_id=bid)["payout"]
    assert p["bill_id"] == bid and len(bills(env)) == 1
    with pytest.raises(HTTPException) as e:
        send(env, amount=80, bill_id=bid, key="key-0002")               # never twice
    assert e.value.status_code == 409
    env.moov.transfers["tr1"]["status"] = "completed"
    mp.refresh(p["id"], mp.BizBody(business_id=CHURCH), u(ADMIN))
    [bill] = bills(env)
    assert bill["status"] == "paid" and bill["paid_via"] == "moov" and bill["is_1099_eligible"] is True
    assert bill["contractor_id"] == env.contractor


def test_the_same_request_twice_pays_once(env):
    ready(env)
    a = send(env, key="key-same")
    b = send(env, key="key-same")
    assert a["payout"]["id"] == b["payout"]["id"]
    assert len(env.moov.transfers) == 1 and len(bills(env)) == 1
    assert len(env.db.t["moov_payouts"]) == 1


def test_an_unread_answer_is_retried_with_the_same_key_and_still_pays_once(env):
    ready(env)
    env.moov.refuse_transfer = 503
    out = send(env, key="key-retry")
    assert out["note"] == mp.SENT_UNSURE and out["payout"]["status"] == "created"
    env.moov.refuse_transfer = 0
    again = send(env, key="key-retry")
    assert again["payout"]["status"] == "pending" and len(env.moov.transfers) == 1
    assert len(bills(env)) == 1


def test_instant_shows_its_fee_and_is_refused_when_moov_offers_no_instant_route(env):
    ready(env)
    with pytest.raises(HTTPException) as e:
        send(env, speed="instant")
    assert e.value.status_code == 409 and "Instant" in e.value.detail
    assert moov_client.fee_for("instant", 10) == 0.50 and moov_client.fee_for("instant", 2000) == 5.00
    assert env.moov.transfers == {}


# ─── Never from us ────────────────────────────────────────────────────

def test_a_source_that_isnt_the_churchs_own_is_refused_before_money_moves(env):
    ready(env)
    for source, pm in ((PARTNER, "pm-church-debit"), ("moov-church-1", "pm-someone-elses"), ("", "x")):
        with pytest.raises(HTTPException) as e:
            moov_client.create_transfer(source_account_id=source, source_payment_method_id=pm,
                                        destination_payment_method_id="pm-payee-std", amount_cents=100,
                                        idempotency_key="k" * 10, description="x", metadata={}, foreign_id="f")
        assert e.value.status_code == 403
    assert env.moov.transfers == {}


def test_the_partner_account_cannot_be_claimed_as_a_church(env):
    mp.church_opt_in(mp.OptInBody(business_id=CHURCH, on=True), u(OWNER))
    link = mp.church_onboarding(mp.BizBody(business_id=CHURCH), u(OWNER))["link"]
    env.moov.redeem(link.rsplit("/", 1)[1], PARTNER, CHURCH_METHODS)
    with pytest.raises(HTTPException) as e:
        mp.church_refresh(mp.BizBody(business_id=CHURCH), u(OWNER))
    assert e.value.status_code == 409


# ─── Caps ─────────────────────────────────────────────────────────────

def test_caps_per_payment_and_per_day(env, monkeypatch):
    ready(env)
    with pytest.raises(HTTPException) as e:
        send(env, amount=1000.01)
    assert e.value.status_code == 409 and "one payment" in e.value.detail
    mp.church_caps(mp.CapsBody(business_id=CHURCH, per_payment_cap=600, daily_cap=1000), u(OWNER))
    send(env, amount=600, key="key-cap-a")
    with pytest.raises(HTTPException) as e:
        send(env, amount=500, key="key-cap-b")
    assert e.value.status_code == 409 and "a day" in e.value.detail
    with pytest.raises(HTTPException) as e:
        mp.church_caps(mp.CapsBody(business_id=CHURCH, per_payment_cap=6000, daily_cap=9000), u(OWNER))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        mp.church_caps(mp.CapsBody(business_id=CHURCH, per_payment_cap=100, daily_cap=200), u(ADMIN))
    assert e.value.status_code == 403
    assert len(env.moov.transfers) == 1


# ─── Failures and returns ─────────────────────────────────────────────

def test_a_failed_transfer_cancels_the_bill_it_made(env):
    ready(env)
    p = send(env)["payout"]
    env.moov.transfers["tr1"].update(status="failed", failureReason="source-payment-error")
    p = mp.refresh(p["id"], mp.BizBody(business_id=CHURCH), u(ADMIN))["payout"]
    assert p["status"] == "failed" and p["failure_reason"] == "source-payment-error"
    assert bills(env)[0]["status"] == "cancelled"


def test_a_return_after_completion_reopens_the_bill_it_paid(env):
    ready(env)
    env.db.t["bills"] = [{"id": uid(), "business_id": CHURCH, "vendor_name": "Sam Rivers", "amount": 150,
                          "status": "overdue", "category": "operating"}]
    p = send(env, bill_id=env.db.t["bills"][0]["id"])["payout"]
    env.moov.transfers["tr1"]["status"] = "completed"
    mp.refresh(p["id"], mp.BizBody(business_id=CHURCH), u(ADMIN))
    assert bills(env)[0]["status"] == "paid"
    env.moov.transfers["tr1"].update(status="reversed", destination={"achDetails": {"return": {"code": "R03"}}})
    p = mp.refresh(p["id"], mp.BizBody(business_id=CHURCH), u(ADMIN))["payout"]
    assert p["status"] == "reversed" and p["return_code"] == "R03"
    b = bills(env)[0]
    assert (b["status"], b["paid_via"], b["paid_at"]) == ("overdue", None, None)


def test_a_return_in_a_closed_month_is_left_for_a_person(env, monkeypatch):
    ready(env)
    p = send(env)["payout"]
    env.moov.transfers["tr1"]["status"] = "completed"
    mp.refresh(p["id"], mp.BizBody(business_id=CHURCH), u(ADMIN))
    import period_lock
    monkeypatch.setattr(period_lock, "locked_period", lambda *a: {"id": "p1"})
    env.moov.transfers["tr1"]["status"] = "reversed"
    p = mp.refresh(p["id"], mp.BizBody(business_id=CHURCH), u(ADMIN))["payout"]
    assert p["needs_review"] and bills(env)[0]["status"] == "paid"


def test_moov_refusing_the_transfer_puts_the_bill_back(env):
    ready(env)
    env.moov.refuse_transfer = 422
    out = send(env)
    assert out["ok"] is False and out["note"] == mp.REFUSED
    assert out["payout"]["status"] == "failed" and bills(env)[0]["status"] == "cancelled"


# ─── The webhook ──────────────────────────────────────────────────────

def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mp.router)
    return TestClient(app)


def _signed(ts: str = None, nonce: str = "n-1", wid: str = "wh-1", secret: str = WEBHOOK_SECRET) -> Dict[str, str]:
    ts = ts or str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}|{nonce}|{wid}".encode(), hashlib.sha512).hexdigest()
    return {"X-Timestamp": ts, "X-Nonce": nonce, "X-Webhook-ID": wid, "X-Signature": sig}


def test_webhook_fails_closed_and_reads_moov_rather_than_the_body(env, monkeypatch):
    ready(env)
    p = send(env)["payout"]
    event = {"eventID": "ev-1", "type": "transfer.updated", "data": {"transferID": "tr1", "status": "completed"}}
    c = _client()
    monkeypatch.delenv("MOOV_WEBHOOK_SECRET")
    assert c.post("/moov/webhook", json=event).json() == {"ok": False}            # no secret: dropped
    monkeypatch.setenv("MOOV_WEBHOOK_SECRET", WEBHOOK_SECRET)
    assert c.post("/moov/webhook", json=event, headers=_signed(secret="wrong")).status_code == 400
    assert c.post("/moov/webhook", json=event,
                  headers=_signed(ts=str(int(time.time()) - 3600))).status_code == 400   # stale
    r = c.post("/moov/webhook", json=event, headers=_signed())
    assert r.status_code == 200
    # The body said completed; Moov says pending, so pending it stays.
    assert env.db.t["moov_payouts"][0]["status"] == "pending" and bills(env)[0]["status"] == "scheduled"
    assert c.post("/moov/webhook", json=event, headers=_signed()).json().get("duplicate") is True
    env.moov.transfers["tr1"]["status"] = "completed"
    event2 = {**event, "eventID": "ev-2"}
    assert c.post("/moov/webhook", json=event2, headers=_signed()).status_code == 200
    assert env.db.t["moov_payouts"][0]["status"] == "completed" and bills(env)[0]["status"] == "paid"
    assert p["id"] == env.db.t["moov_payouts"][0]["id"]


def test_signature_check_is_moovs_shape():
    ts, now = "1700000000", 1700000100.0
    good = _signed(ts=ts)
    lower = {k.lower(): v for k, v in good.items()}
    assert moov_client.signature_ok(lower, secret=WEBHOOK_SECRET, now=now)
    assert not moov_client.signature_ok({**lower, "x-nonce": "other"}, secret=WEBHOOK_SECRET, now=now)
    assert not moov_client.signature_ok(lower, secret="", now=now)
    assert not moov_client.signature_ok({**lower, "x-signature": ""}, secret=WEBHOOK_SECRET, now=now)


# ─── No secrets in logs ───────────────────────────────────────────────

def test_no_key_or_body_reaches_a_log_line(env, caplog):
    env.moov.refuse_transfer = 0
    caplog.set_level(logging.DEBUG)
    with pytest.raises(moov_client.MoovError):
        moov_client.request("GET", "/accounts/a3f0c1d2-1111-2222-3333-444455556666/nothing-here")
    text = "\n".join(r.getMessage() for r in caplog.records)
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name == "moov_client")
    assert SECRET_PRIVATE not in text
    assert "a3f0c1d2-1111" not in ours and ":id" in ours
    assert all("authorization" in h and SECRET_PRIVATE not in h["authorization"] for h in env.moov.headers)
    assert all(h.get("x-moov-version") == moov_client.DEFAULT_VERSION for h in env.moov.headers)

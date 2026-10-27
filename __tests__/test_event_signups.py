"""Paid sign-ups for church events, with a waitlist (church_event_signups.py).
The Church Menu Gaps check ("The other doors", the Sunday card): RSVP had
capacity and serving roles but no payment and no waitlist. Kevin, 2026-10-27:
"ok continue". Planning Center Registrations and Subsplash are the bar.

Pins:
  * free RSVP is exactly as before for an event without a setup (and while
    the tables don't exist); an event that takes sign-ups refuses the free
    "I'm coming" but still takes a server
  * the amount always comes from the server's prices; a client-sent amount
    is never read
  * the webhook refuses a bad signature, the wrong connected account,
    another church's metadata and the wrong amount; a repeated delivery is
    processed once
  * a seat hold runs out and gives its place back; the waitlist moves first
    come, first served, and a newcomer never jumps it; an offer's link pays
  * another church's event, sign-ups and setup are unreachable
  * the switch: off means no prices; owner means only a church the
    platform owner owns
  * the public sign-up is rate-limited before anything is read
  * a refund frees the place; the CSV can't carry a formula
The SQL itself (locks, order, hashes, grants) is pinned on PGlite in
__tests__/church_event_signups_db.mjs; here the fake follows its rules.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas  # noqa: E402
import church_event_signups as ces  # noqa: E402
import events_rsvp_router as er  # noqa: E402
import member_portal_church as mpc  # noqa: E402
import rate_limit  # noqa: E402
import sb_clients  # noqa: E402
import stripe_checkout_helpers as sch  # noqa: E402
import stripe_connect_router as scr  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
NAMES = ("owner", "admin", "manager", "viewer", "stranger", "other_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
MOD, MOD2 = "dddddddd-0000-4000-8000-000000000001", "dddddddd-0000-4000-8000-000000000002"
VBS = "eeeeeeee-0000-4000-8000-000000000001"
PICNIC = "eeeeeeee-0000-4000-8000-000000000002"
GRACE_EV = "eeeeeeee-0000-4000-8000-000000000003"
SETUP = "ffffffff-0000-4000-8000-000000000001"
ADULT, CHILD, FAMILY = ("aaaaaaaa-0000-4000-8000-00000000000%d" % i for i in (1, 2, 3))
T0 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat()


class SignupsDB(FakeDB):
    """The sign-up tables, the upsert, and the two database functions on the
    shared fake, by the migration's own rules."""

    TABLES = ("church_event_signup_setups", "church_event_ticket_types", "church_event_registrations")

    def __init__(self, **tables):
        super().__init__(**tables)
        self.missing = False
        self.now = T0
        self.seq = 0
        self.reads = 0

    def get(self, path, **kw):
        self.reads += 1
        if self.missing and path.lstrip("/").split("?")[0] in self.TABLES:
            return None
        return super().get(path, **kw)

    def patch(self, path, body, **kw):
        if self.missing and path.lstrip("/").split("?")[0] in self.TABLES:
            return None
        return super().patch(path, body, **kw)

    def post(self, path, body, prefer=None, **kw):
        table = path.lstrip("/").split("?")[0]
        if self.missing and (table in self.TABLES or table.startswith("rpc/church_event")):
            return None
        if table == "rpc/church_event_take":
            return self._take(body)
        if table == "rpc/church_event_settle":
            s = self._setup(body["p_business"], body["p_entry"])
            return {"offers": self._move(s) if s else []}
        if table == "church_event_signup_setups" and "on_conflict" in path:
            old = self._setup(body["business_id"], body["entry_id"])
            if old:
                old.update(body)
                return [dict(old)]
            body = {"id": str(uuid.uuid4()), **body}
        if table == "church_event_ticket_types":
            body = {"active": True, **body}
        return super().post(path, body, prefer=prefer, **kw)

    # ── church_event_take / church_event_settle, as the SQL does them ──
    def _setup(self, biz, entry):
        return next((s for s in self.t.get("church_event_signup_setups", [])
                     if s["business_id"] == biz and s["entry_id"] == entry), None)

    def _regs(self, biz, entry):
        return [r for r in self.t.setdefault("church_event_registrations", [])
                if r["business_id"] == biz and r["entry_id"] == entry]

    def _taken(self, biz, entry):
        return sum(r["seats"] for r in self._regs(biz, entry)
                   if r["status"] in ("paid", "confirmed")
                   or (r["status"] in ("held", "offered") and r["hold_expires_at"] > iso(self.now)))

    def _insert(self, biz, entry, row, status, hold=None):
        self.seq += 1
        r = {"id": str(uuid.uuid4()), "business_id": biz, "entry_id": entry, "status": status,
             "hold_expires_at": hold, "created_at": iso(self.now) + f".{self.seq:06d}", "refunded_cents": 0,
             "claim_hash": None, "checkout_url": None, "stripe_session_id": None, "stripe_payment_intent": None,
             "paid_at": None, "offered_at": None, **{k: row.get(k) for k in (
                 "event_title", "contact_id", "name", "email", "phone", "texts_ok", "tickets", "seats",
                 "amount_cents", "answers", "source", "request_key")}}
        self.t.setdefault("church_event_registrations", []).append(r)
        return r

    def _move(self, s):
        biz, entry = s["business_id"], s["entry_id"]
        for r in self._regs(biz, entry):
            if r["status"] in ("held", "offered") and r["hold_expires_at"] <= iso(self.now):
                r["status"] = "expired"
        out = []
        if not s.get("open", True):
            return out
        while True:
            waiting = sorted((r for r in self._regs(biz, entry) if r["status"] == "waiting"),
                             key=lambda r: r["created_at"])
            if not waiting:
                break
            w = waiting[0]
            if s.get("capacity") is not None and self._taken(biz, entry) + w["seats"] > s["capacity"]:
                break
            token = None
            if w["amount_cents"] == 0:
                w.update(status="confirmed", hold_expires_at=None)
            else:
                token = uuid.uuid4().hex + uuid.uuid4().hex
                w.update(status="offered", hold_expires_at=iso(self.now + timedelta(hours=s.get("offer_hours") or 24)),
                         claim_hash=hashlib.sha256(token.encode()).hexdigest())
            out.append({"id": w["id"], "status": w["status"], "token": token, "name": w["name"], "email": w["email"],
                        "phone": w["phone"], "texts_ok": w["texts_ok"], "amount_cents": w["amount_cents"],
                        "seats": w["seats"], "tickets": w["tickets"], "hold_expires_at": w["hold_expires_at"]})
        return out

    def _take(self, a):
        biz, entry, row = a["p_business"], a["p_entry"], a["p_row"]
        s = self._setup(biz, entry)
        if not s:
            return {"state": "closed", "why": "none"}
        if row.get("request_key"):
            old = next((r for r in self.t.get("church_event_registrations", [])
                        if r["business_id"] == biz and r.get("request_key") == row["request_key"]), None)
            if old:
                return {"state": "already", "id": old["id"], "status": old["status"],
                        "checkout_url": old.get("checkout_url"), "hold_expires_at": old.get("hold_expires_at"),
                        "offers": []}
        offers = self._move(s)
        if not s.get("open", True) or (s.get("deadline") and s["deadline"] <= iso(self.now)):
            return {"state": "closed", "why": "deadline" if s.get("open", True) else "closed", "offers": offers}
        queued = sum(1 for r in self._regs(biz, entry) if r["status"] == "waiting")
        cap = s.get("capacity")
        if queued == 0 and (cap is None or self._taken(biz, entry) + row["seats"] <= cap):
            free = row["amount_cents"] == 0
            r = self._insert(biz, entry, row, "confirmed" if free else "held",
                             None if free else iso(self.now + timedelta(minutes=a["p_hold_minutes"])))
            return {"state": r["status"], "id": r["id"], "hold_expires_at": r["hold_expires_at"], "offers": offers}
        if not (a["p_waitlist"] and s.get("waitlist", True)):
            return {"state": "full", "waitlist": s.get("waitlist", True), "offers": offers}
        r = self._insert(biz, entry, row, "waiting")
        return {"state": "waiting", "id": r["id"], "position": queued + 1, "offers": offers}


def _setup_row(**kw):
    return {"id": SETUP, "business_id": BIZ, "entry_id": VBS, "open": True, "capacity": 3, "deadline": None,
            "questions": [{"id": "qshirt", "label": "T-shirt size", "kind": "choice", "options": ["S", "M", "L"],
                           "required": True},
                          {"id": "qallergy", "label": "Allergies", "kind": "text", "required": False}],
            "waitlist": True, "offer_hours": 24, "bring": "A sack lunch and sunscreen", "updated_at": iso(T0), **kw}


@pytest.fixture
def db(monkeypatch):
    on = {"events_public": {"enabled": True}}
    fake = SignupsDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"],
                     "settings": on, "stripe_account_id": "acct_love"},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"],
                     "settings": on, "stripe_account_id": "acct_grace"}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": n, "status": "active",
                         "invited_email": f"{n}@lovecity.org"} for n in ("admin", "manager", "viewer")],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "site_config": {}},
                        {"business_id": OTHER, "slug": "grace-chapel", "site_config": {}}],
        custom_modules=[{"id": MOD, "business_id": BIZ, "name": "Services & Events", "archetype": "event_roster",
                         "is_active": True, "archetype_params": {}},
                        {"id": MOD2, "business_id": OTHER, "name": "Events", "archetype": "event_roster",
                         "is_active": True, "archetype_params": {}}],
        module_entries=[
            {"id": VBS, "module_id": MOD, "business_id": BIZ, "status": "active", "updated_at": "r1",
             "data": {"title": "Vacation Bible School", "date": "2026-11-14", "location": "Fellowship hall",
                      "signups": []}},
            {"id": PICNIC, "module_id": MOD, "business_id": BIZ, "status": "active", "updated_at": "r1",
             "data": {"title": "Church picnic", "date": "2026-11-21", "capacity": 50, "signups": []}},
            {"id": GRACE_EV, "module_id": MOD2, "business_id": OTHER, "status": "active", "updated_at": "r1",
             "data": {"title": "Grace retreat", "date": "2026-11-20", "signups": []}}],
        contacts=[], stripe_webhook_events=[], sms_consents=[],
        church_event_signup_setups=[_setup_row()],
        church_event_ticket_types=[
            {"id": ADULT, "business_id": BIZ, "setup_id": SETUP, "label": "Adult", "price_cents": 2500, "seats": 1,
             "max_per_signup": None, "active": True, "sort_order": 0},
            {"id": CHILD, "business_id": BIZ, "setup_id": SETUP, "label": "Child", "price_cents": 1000, "seats": 1,
             "max_per_signup": None, "active": True, "sort_order": 1},
            {"id": FAMILY, "business_id": BIZ, "setup_id": SETUP, "label": "Family", "price_cents": 6000, "seats": 4,
             "max_per_signup": 1, "active": True, "sort_order": 2}],
        church_event_registrations=[],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_PAID_SIGNUPS", "on")
    monkeypatch.setenv("CHURCH_AREAS", "off")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setattr(ces, "_now", lambda: fake.now)
    monkeypatch.setattr(ces, "_church_tz", lambda biz: "America/New_York")
    emails = {n: e.email for n, e in PEOPLE.items()}
    monkeypatch.setattr(ces, "_owner_email", lambda oid: next((emails[n] for n, i in ID.items() if i == oid), None))
    ces._owner_seen.clear()
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    monkeypatch.setattr(church_areas, "my_areas", lambda *a: {"areas": None})
    fake.sent, fake.texts, fake.sessions = [], [], []
    monkeypatch.setattr(ces, "_send_email", lambda biz, to, name, subject, body, key: fake.sent.append(
        {"to": to, "subject": subject, "body": body, "key": key}))
    monkeypatch.setattr(ces, "_send_text", lambda biz, to, msg: fake.texts.append((to, msg)))
    monkeypatch.setattr(ces, "_run", lambda coro: None)

    async def checkout(*, stripe_account_id, **kw):
        form = sch._event_signup_checkout_form(**kw)     # the real form, priced lines and all
        sid = f"cs_test_{uuid.uuid4().hex[:24]}"
        fake.sessions.append({"account": stripe_account_id, "form": form, "id": sid, **kw})
        return {"id": sid, "url": f"https://checkout.stripe.com/c/pay/{sid}"}
    monkeypatch.setattr(sch, "create_event_signup_checkout", checkout)
    import event_spine
    monkeypatch.setattr(event_spine, "emit", lambda *a, **k: None)
    return fake


def office(name="owner") -> TestClient:
    app = FastAPI()
    app.include_router(ces.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def public() -> TestClient:
    app = FastAPI()
    app.include_router(ces.router)
    app.include_router(er.router)
    app.include_router(scr.router)
    return TestClient(app)


def signup(slug="love-city-church", entry=VBS, **kw):
    body = {"entry_id": entry, "name": "Ann Carter", "email": "ann@example.org",
            "tickets": {ADULT: 1, CHILD: 1}, "answers": {"qshirt": "m"}, **kw}
    return public().post(f"/public/events/{slug}/signup", json=body)


def regs(db, **match):
    return [r for r in db.t["church_event_registrations"] if all(r.get(k) == v for k, v in match.items())]


def webhook(db, monkeypatch, session, *, account="acct_love", evt=None, good=True, kind="checkout.session.completed"):
    monkeypatch.setattr(scr, "verify_webhook_signature", lambda payload, sig: good)
    event = {"id": evt or f"evt_{uuid.uuid4().hex[:16]}", "type": kind, "account": account,
             "livemode": False, "data": {"object": session}}
    return public().post("/payments/stripe/webhook", content=json.dumps(event),
                         headers={"stripe-signature": "t=1,v1=x"})


def paid_session(db, reg, **kw):
    return {"id": reg["stripe_session_id"], "object": "checkout.session", "payment_status": "paid",
            "amount_total": reg["amount_cents"], "currency": "usd", "payment_intent": "pi_123",
            "metadata": {"source_type": "event_signup", "source_id": reg["id"], "business_id": reg["business_id"],
                         "entry_id": reg["entry_id"]}, **kw}


# ─── Free RSVP is unchanged ──────────────────────────────────────────

def test_free_rsvp_is_exactly_as_before_for_an_event_without_a_setup(db):
    got = public().post("/public/events/love-city-church/rsvp",
                        json={"entry_id": PICNIC, "name": "Bo Diaz", "email": "bo@example.org"})
    assert got.status_code == 200 and got.json() == {"ok": True, "already": False, "attending": 1}
    picnic = next(e for e in db.t["module_entries"] if e["id"] == PICNIC)
    assert [s["name"] for s in picnic["data"]["signups"]] == ["Bo Diaz"]
    assert not db.t["church_event_registrations"] and not db.sessions
    # The member app's "I'm coming" too.
    me = {"id": "cccccccc-0000-4000-8000-000000000001", "name": "Cy Moss", "email": "cy@example.org"}
    assert mpc.member_rsvp(BIZ, me, PICNIC, "coming") == (True, "coming")


def test_free_rsvp_is_unchanged_while_the_tables_dont_exist(db):
    db.missing = True
    for entry in (PICNIC, VBS):
        got = public().post("/public/events/love-city-church/rsvp",
                            json={"entry_id": entry, "name": "Bo Diaz", "email": f"bo{entry[-1]}@example.org"})
        assert got.status_code == 200, got.text
    assert office().get(f"/church/events/signups/status?business_id={BIZ}").json()["enabled"] is False
    for got in (office().get(f"/church/events/signups?business_id={BIZ}&entry_id={VBS}"),
                office().get(f"/church/events/signups/summary?business_id={BIZ}"),
                signup()):
        assert got.status_code == 503, got.text


def test_an_event_that_takes_sign_ups_refuses_the_free_rsvp_but_takes_a_server(db):
    got = public().post("/public/events/love-city-church/rsvp",
                        json={"entry_id": VBS, "name": "Bo Diaz", "email": "bo@example.org"})
    assert got.status_code == 409 and "sign-up" in got.json()["detail"]
    me = {"id": "cccccccc-0000-4000-8000-000000000001", "name": "Cy Moss", "email": "cy@example.org"}
    assert mpc.member_rsvp(BIZ, me, VBS, "coming") == (False, "signup")
    entry = next(e for e in db.t["module_entries"] if e["id"] == VBS)
    entry["data"]["_roles"] = [{"id": "kids", "label": "Kids helper", "needed": 4}]
    assert mpc.member_rsvp(BIZ, me, VBS, "serve", "kids") == (True, "serving")


# ─── The amount comes from the server ────────────────────────────────

def test_the_amount_always_comes_from_the_servers_prices(db):
    got = signup(tickets={ADULT: 2, CHILD: 1}, amount_cents=1, total=1, price_cents=1)
    assert got.status_code == 200, got.text
    assert got.json()["url"].startswith("https://checkout.stripe.com/")
    [r] = regs(db)
    assert r["amount_cents"] == 2 * 2500 + 1000 and r["seats"] == 3 and r["status"] == "held"
    assert r["answers"] == {"qshirt": "M"}
    [s] = db.sessions
    assert s["account"] == "acct_love"
    f = s["form"]
    assert (f["line_items[0][price_data][unit_amount]"], f["line_items[0][quantity]"]) == (2500, 2)
    assert (f["line_items[1][price_data][unit_amount]"], f["line_items[1][quantity]"]) == (1000, 1)
    assert f["metadata[source_type]"] == "event_signup" and f["metadata[source_id]"] == r["id"]
    assert f["metadata[business_id]"] == BIZ and f["payment_intent_data[metadata][source_id]"] == r["id"]
    assert f["payment_method_types[0]"] == "card"
    # Stripe's page closes before the place's hold runs out.
    assert f["expires_at"] < datetime.fromisoformat(r["hold_expires_at"]).timestamp()
    assert r["stripe_session_id"] == s["id"]


@pytest.mark.parametrize("tickets,said", [
    ({"not-a-ticket": 1}, "isn't one this event offers"),
    ({ADULT: -1}, "Choose from 1"),
    ({FAMILY: 2}, "Choose from 1 to 1 Family"),
    ({}, "at least one ticket"),
    ({ADULT: 21}, "Choose from 1 to 20"),
])
def test_tickets_the_event_doesnt_offer_are_refused(db, tickets, said):
    got = signup(tickets=tickets)
    assert got.status_code == 400 and said in got.json()["detail"]
    assert not db.t["church_event_registrations"] and not db.sessions


def test_a_required_question_is_asked_by_name(db):
    got = signup(answers={"qshirt": "XXL"})
    assert got.status_code == 400 and got.json()["detail"] == "Please answer: T-shirt size"


def test_a_free_ticket_signs_up_without_stripe(db):
    for t in db.t["church_event_ticket_types"]:
        t["price_cents"] = 0
    got = signup()
    assert got.status_code == 200 and got.json()["confirmed"] is True
    assert got.json()["bring"] == "A sack lunch and sunscreen"
    assert regs(db)[0]["status"] == "confirmed" and not db.sessions


def test_the_same_press_twice_is_one_sign_up(db):
    a = signup(request_id="0b8a5b1c-1111-4111-8111-000000000001")
    b = signup(request_id="0b8a5b1c-1111-4111-8111-000000000001")
    assert a.json()["url"] == b.json()["url"]
    assert len(regs(db)) == 1 and len(db.sessions) == 1


# ─── The webhook ─────────────────────────────────────────────────────

def test_the_webhook_marks_paid_only_from_the_churchs_own_account(db, monkeypatch):
    signup()
    [r] = regs(db)
    sess = paid_session(db, r)
    # A bad signature: refused, nothing read or changed.
    got = webhook(db, monkeypatch, sess, good=False)
    assert got.status_code == 400 and r["status"] == "held"
    # Paid on another church's account (Grace Chapel holds its own keys).
    got = webhook(db, monkeypatch, sess, account="acct_grace")
    assert got.status_code == 500 and r["status"] == "held"
    assert db.t["stripe_webhook_events"][-1]["processed_ok"] is False
    assert "different payment account" in db.t["stripe_webhook_events"][-1]["processed_error"]
    # Metadata naming another church, on that church's own account.
    other = {**sess, "metadata": {**sess["metadata"], "business_id": OTHER}}
    assert webhook(db, monkeypatch, other, account="acct_grace").status_code == 500 and r["status"] == "held"
    # Less than the server's price.
    assert webhook(db, monkeypatch, {**sess, "amount_total": 100}).status_code == 500 and r["status"] == "held"
    # Not paid yet (Stripe's page closed without payment): nothing.
    assert webhook(db, monkeypatch, {**sess, "payment_status": "unpaid"}).status_code == 200 and r["status"] == "held"
    assert not db.sent
    # The real thing.
    got = webhook(db, monkeypatch, sess)
    assert got.status_code == 200 and r["status"] == "paid" and r["stripe_payment_intent"] == "pi_123"
    assert r["stripe_account_id"] == "acct_love"
    [mail] = db.sent
    assert mail["to"] == "ann@example.org" and "1 Adult, 1 Child" in mail["body"] and "$35 paid" in mail["body"]
    assert "sack lunch" in mail["body"]


def test_a_repeated_delivery_is_processed_once(db, monkeypatch):
    signup()
    [r] = regs(db)
    sess = paid_session(db, r)
    first = webhook(db, monkeypatch, sess, evt="evt_same")
    again = webhook(db, monkeypatch, sess, evt="evt_same")
    assert first.status_code == 200 and again.json().get("deduplicated") is True
    # Stripe's other success event for the same payment changes nothing either.
    other = webhook(db, monkeypatch, sess, evt="evt_async", kind="checkout.session.async_payment_succeeded")
    assert other.status_code == 200
    assert r["status"] == "paid" and len(db.sent) == 1
    assert ces.record_checkout(sess, "acct_love") is None


def test_a_payment_that_lands_after_the_hold_ran_out_is_still_paid(db, monkeypatch):
    signup()
    [r] = regs(db)
    db.now = T0 + timedelta(hours=1)
    ces.sweep_tick()
    assert r["status"] == "expired"
    # Its places went to someone else meanwhile: the payment is still kept
    # (the money moved), the office is told, and the event shows over.
    signup(name="Bea", email="bea@example.org", tickets={ADULT: 3})
    assert webhook(db, monkeypatch, paid_session(db, r)).status_code == 200 and r["status"] == "paid"
    [note] = [n for n in db.t.get("chief_notifications", []) if n["data"]["kind"] == "event_signup_late"]
    assert "Ann Carter paid after their place had gone back" in note["body"]
    d = office().get(f"/church/events/signups?business_id={BIZ}&entry_id={VBS}").json()
    assert d["totals"]["over"] == 2


def test_a_full_refund_frees_the_place_and_moves_the_waitlist(db, monkeypatch):
    db.t["church_event_signup_setups"][0]["capacity"] = 2
    signup()
    [r] = regs(db)
    webhook(db, monkeypatch, paid_session(db, r))
    assert signup(name="Dee", email="dee@example.org", tickets={ADULT: 1}).status_code == 409
    signup(name="Dee", email="dee@example.org", tickets={ADULT: 1}, waitlist=True)
    charge = {"id": "ch_1", "object": "charge", "amount_refunded": 3500, "refunded": True, "payment_intent": "pi_123",
              "metadata": {"source_type": "event_signup", "source_id": r["id"], "business_id": BIZ}}
    # Another account's refund touches nothing.
    webhook(db, monkeypatch, charge, account="acct_grace", kind="charge.refunded")
    assert r["status"] == "paid" and r["refunded_cents"] == 0
    # A refund that can't be written is a failed event, so Stripe sends it again.
    real = db.patch
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **kw: None if "church_event_registrations" in path else real(path, body, **kw))
    assert webhook(db, monkeypatch, charge, kind="charge.refunded").status_code == 500 and r["status"] == "paid"
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    assert webhook(db, monkeypatch, charge, kind="charge.refunded").status_code == 200
    assert r["status"] == "refunded" and r["refunded_cents"] == 3500
    [dee] = regs(db, name="Dee")
    assert dee["status"] == "offered"


# ─── Holds, capacity and the waitlist ────────────────────────────────

def test_a_seat_hold_runs_out_and_gives_its_place_back(db):
    signup(tickets={ADULT: 3})
    [r] = regs(db)
    assert r["hold_expires_at"] == iso(T0 + timedelta(minutes=ces.HOLD_MINUTES))
    late = signup(name="Bea", email="bea@example.org", tickets={ADULT: 1})
    assert late.status_code == 409 and late.json()["code"] == "full" and late.json()["waitlist"] is True
    db.now = T0 + timedelta(minutes=ces.HOLD_MINUTES + 1)
    assert ces.tally(regs(db), db.now)["taken"] == 0
    got = signup(name="Bea", email="bea@example.org", tickets={ADULT: 1})
    assert got.status_code == 200 and r["status"] == "expired"


def test_capacity_and_the_waitlist_go_in_order(db):
    assert signup(tickets={ADULT: 2}).status_code == 200                        # 2 of 3 held
    one = signup(name="Cal", email="cal@example.org", tickets={ADULT: 2}, waitlist=True)
    two = signup(name="Dee", email="dee@example.org", tickets={ADULT: 1}, waitlist=True)
    assert (one.json()["position"], two.json()["position"]) == (1, 2)
    assert "24 hours" in one.json()["next"] and "won't be charged" in one.json()["next"]
    # One place is free, but Cal (2) is at the front: a newcomer can't jump the line.
    jump = signup(name="Eve", email="eve@example.org", tickets={ADULT: 1})
    assert jump.status_code == 409 and jump.json()["code"] == "full"
    assert [m["subject"] for m in db.sent] == ["You're on the waitlist for Vacation Bible School"] * 2
    # Ann's hold runs out: Cal is offered first, then Dee fits behind him.
    db.now = T0 + timedelta(minutes=ces.HOLD_MINUTES + 1)
    assert ces.sweep_tick() == 2
    cal, dee = regs(db, name="Cal")[0], regs(db, name="Dee")[0]
    assert cal["status"] == "offered" and dee["status"] == "offered"
    offers = [m for m in db.sent if m["subject"].startswith("A place opened up")]
    assert [m["to"] for m in offers] == ["cal@example.org", "dee@example.org"]
    token = offers[0]["body"].split("?claim=")[1].split('"')[0]
    assert hashlib.sha256(token.encode()).hexdigest() == cal["claim_hash"] and token not in json.dumps(cal)
    # The offer's link: what it's for, then pay for it.
    seen = public().get(f"/public/events/love-city-church/claim/{token}").json()
    assert seen["status"] == "offered" and seen["amount_cents"] == 5000 and seen["first"] == "Cal"
    assert "email" not in seen and "name" not in seen
    paid = public().post("/public/events/love-city-church/claim", json={"token": token})
    assert paid.status_code == 200 and paid.json()["url"] and db.sessions[-1]["registration_id"] == cal["id"]
    # An offer that ran out goes to the next person, and its link says so.
    db.now = T0 + timedelta(days=2)
    ces.sweep_tick()
    assert cal["status"] == "expired"
    assert public().post("/public/events/love-city-church/claim", json={"token": token}).status_code == 410


def test_a_closed_or_past_deadline_event_takes_no_one(db):
    db.t["church_event_signup_setups"][0]["deadline"] = iso(T0 - timedelta(hours=1))
    got = signup()
    assert got.status_code == 409 and got.json()["detail"] == "Sign-ups for this event have closed."
    db.t["church_event_signup_setups"][0].update(deadline=None, open=False)
    got = signup()
    assert got.status_code == 409 and not regs(db)
    # Closed is still a sign-up event: the free RSVP stays shut, and the page says closed.
    got = public().post("/public/events/love-city-church/rsvp",
                        json={"entry_id": VBS, "name": "Bo Diaz", "email": "bo@example.org"})
    assert got.status_code == 409
    occ = ces.annotate(BIZ, [{"entry_id": VBS, "date": "2026-11-14"}])
    assert occ[0]["signup"]["closed"] == "closed"


def test_back_from_stripe_gives_the_hold_back(db):
    rid = "0b8a5b1c-1111-4111-8111-000000000009"
    signup(tickets={ADULT: 3}, request_id=rid)
    assert public().post("/public/events/love-city-church/release",
                         json={"entry_id": VBS, "request_id": "someone-elses-id"}).json()["released"] is False
    assert public().post("/public/events/love-city-church/release",
                         json={"entry_id": VBS, "request_id": rid}).json()["released"] is True
    assert regs(db)[0]["status"] == "cancelled"
    assert signup(name="Bea", email="bea@example.org", tickets={ADULT: 3}).status_code == 200


# ─── Another church is out of reach ──────────────────────────────────

def test_another_churchs_event_is_unreachable(db):
    # On Love City's page, Grace's event: not found (and nothing written).
    assert signup(entry=GRACE_EV).status_code == 404
    # Grace's owner opening Love City's sign-ups, or Love City's opening Grace's event.
    assert office("other_owner").get(f"/church/events/signups?business_id={BIZ}&entry_id={VBS}").status_code == 404
    assert office("owner").get(f"/church/events/signups?business_id={BIZ}&entry_id={GRACE_EV}").status_code == 404
    assert office("stranger").get(f"/church/events/signups/summary?business_id={BIZ}").status_code == 404
    got = office("owner").put("/church/events/signups/setup", json={
        "business_id": BIZ, "entry_id": GRACE_EV, "types": [{"label": "Adult", "price_cents": 100}]})
    assert got.status_code == 404
    # A Love City sign-up can't be cancelled from Grace's office.
    signup()
    [r] = regs(db)
    got = office("other_owner").post(f"/church/events/signups/{r['id']}/cancel", json={"business_id": OTHER})
    assert got.status_code == 404 and r["status"] == "held"
    assert not any(x["entry_id"] == GRACE_EV for x in db.t["church_event_registrations"])


def test_only_the_office_sees_sign_ups_and_only_owner_and_admins_change_them(db):
    signup()
    assert office("manager").get(f"/church/events/signups?business_id={BIZ}&entry_id={VBS}").status_code == 200
    assert office("viewer").get(f"/church/events/signups?business_id={BIZ}&entry_id={VBS}").status_code == 403
    body = {"business_id": BIZ, "entry_id": VBS, "types": [{"label": "Adult", "price_cents": 2500}]}
    assert office("manager").put("/church/events/signups/setup", json=body).status_code == 403
    assert office("admin").put("/church/events/signups/setup", json=body).status_code == 200
    assert office("manager").get(f"/church/events/signups/export?business_id={BIZ}&entry_id={VBS}").status_code == 403


# ─── The switch ──────────────────────────────────────────────────────

def test_the_switch_off_means_no_prices(db, monkeypatch):
    monkeypatch.setenv("CHURCH_PAID_SIGNUPS", "off")
    assert office().get(f"/church/events/signups/status?business_id={BIZ}").json()["enabled"] is False
    got = office().put("/church/events/signups/setup", json={
        "business_id": BIZ, "entry_id": PICNIC, "types": [{"label": "Adult", "price_cents": 1500}]})
    assert got.status_code == 404 and not ces.setups_for(BIZ, [PICNIC])
    got = signup()
    assert got.status_code == 409 and "aren't open online" in got.json()["detail"]
    assert not db.sessions and not regs(db)
    # The page says so, rather than turning the event free.
    occ = ces.annotate(BIZ, [{"entry_id": VBS, "date": "2026-11-14"}])
    assert occ[0]["signup"]["closed"] == "paused"
    assert "open online right now" in ces.public_card({**occ[0], "title": "VBS", "date_label": "", "location": ""}, er._esc)


def test_owner_mode_is_only_a_church_the_platform_owner_owns(db, monkeypatch):
    monkeypatch.setenv("CHURCH_PAID_SIGNUPS", "owner")
    body = {"business_id": OTHER, "entry_id": GRACE_EV, "types": [{"label": "Adult", "price_cents": 1500}]}
    assert office("other_owner").put("/church/events/signups/setup", json=body).status_code == 404
    assert office("other_owner").get(f"/church/events/signups/status?business_id={OTHER}").json()["enabled"] is False
    assert office("owner").get(f"/church/events/signups/status?business_id={BIZ}").json() == {
        "enabled": True, "can_price": True, "connected": True}
    # An address that can't be read is "no".
    ces._owner_seen.clear()
    monkeypatch.setattr(ces, "_owner_email", lambda oid: None)
    assert office("owner").get(f"/church/events/signups/status?business_id={BIZ}").json()["enabled"] is False


def test_a_price_needs_stripe_connected(db):
    db.t["businesses"][0]["stripe_account_id"] = None
    got = office().put("/church/events/signups/setup", json={
        "business_id": BIZ, "entry_id": PICNIC, "types": [{"label": "Adult", "price_cents": 1500}]})
    assert got.status_code == 409 and "Connect Stripe" in got.json()["detail"]
    got = office().put("/church/events/signups/setup", json={
        "business_id": BIZ, "entry_id": PICNIC, "types": [{"label": "Everyone", "price_cents": 0}]})
    assert got.status_code == 200 and got.json()["view"]["priced"] is False


# ─── The office ──────────────────────────────────────────────────────

def test_the_office_sets_up_an_event_and_reads_its_sign_ups(db):
    got = office().put("/church/events/signups/setup", json={
        "business_id": BIZ, "entry_id": PICNIC, "capacity": 40, "deadline": "2026-11-20T04:59:00Z",
        "offer_hours": 12, "bring": "A chair",
        "questions": [{"label": "Bringing a dish?", "kind": "yes_no"}, {"label": "", "kind": "text"}],
        "types": [{"label": "Adult", "price_cents": 1500}, {"label": "Kids under 5", "price_cents": 0}]})
    assert got.status_code == 200, got.text
    d = got.json()
    assert [t["label"] for t in d["types"]] == ["Adult", "Kids under 5"]
    assert d["setup"]["capacity"] == 40 and d["setup"]["offer_hours"] == 12
    assert [q["label"] for q in d["setup"]["questions"]] == ["Bringing a dish?"]
    assert d["view"]["price_from"] == 0 and d["view"]["priced"] is True
    # A ticket taken off the list is retired, never deleted.
    adult = next(t for t in d["types"] if t["label"] == "Adult")
    got = office().put("/church/events/signups/setup", json={
        "business_id": BIZ, "entry_id": PICNIC, "types": [{"id": adult["id"], "label": "Adult", "price_cents": 2000}]})
    types = {t["label"]: t for t in got.json()["types"]}
    assert types["Adult"]["price_cents"] == 2000 and types["Kids under 5"]["active"] is False
    for bad in ({"offer_hours": 100}, {"capacity": 0}, {"types": []},
                {"types": [{"label": "A", "price_cents": -5}]}, {"types": [{"label": "A", "price_cents": 1}] * 2},
                {"questions": [{"label": "Size", "kind": "choice", "options": ["One"]}]}):
        body = {"business_id": BIZ, "entry_id": PICNIC, "types": [{"label": "Adult", "price_cents": 1}], **bad}
        assert office().put("/church/events/signups/setup", json=body).status_code == 400, bad


def test_the_office_view_leads_with_what_needs_doing(db, monkeypatch):
    signup()
    signup(name="Bea", email="bea@example.org", tickets={ADULT: 1})
    [ann] = regs(db, name="Ann Carter")
    webhook(db, monkeypatch, paid_session(db, ann))
    signup(name="Cal", email="cal@example.org", tickets={ADULT: 1}, waitlist=True)
    d = office("manager").get(f"/church/events/signups?business_id={BIZ}&entry_id={VBS}").json()
    by = {r["name"]: r for r in d["registrations"]}
    assert by["Ann Carter"]["status"] == "paid" and by["Ann Carter"]["stripe_link"].endswith("/payments/pi_123")
    assert by["Bea"]["status"] == "held" and by["Cal"]["status"] == "waiting" and by["Cal"]["position"] == 1
    assert by["Ann Carter"]["answers"] == {"qshirt": "M"}
    t = d["totals"]
    assert (t["paid"], t["paid_seats"], t["paid_cents"], t["held"], t["waiting"], t["taken"]) == (1, 2, 3500, 1, 1, 3)
    s = office("manager").get(f"/church/events/signups/summary?business_id={BIZ}").json()["entries"][VBS]
    assert s["paid"] == 1 and s["waiting"] == 1 and s["places_left"] == 0
    # Cancel: a paid one is refunded in Stripe instead; a waiting one comes off.
    c = office("owner")
    assert c.post(f"/church/events/signups/{ann['id']}/cancel", json={"business_id": BIZ}).status_code == 409
    got = c.post(f"/church/events/signups/{by['Cal']['id']}/cancel", json={"business_id": BIZ})
    assert got.status_code == 200 and regs(db, name="Cal")[0]["status"] == "cancelled"


def test_the_csv_carries_the_answers_and_no_formula(db):
    signup(name="=HYPERLINK(\"http://x\")", answers={"qshirt": "S", "qallergy": "+peanuts"})
    got = office().get(f"/church/events/signups/export?business_id={BIZ}&entry_id={VBS}")
    assert got.status_code == 200 and got.headers["content-type"].startswith("text/csv")
    assert "vacation-bible-school-sign-ups.csv" in got.headers["content-disposition"]
    lines = got.text.lstrip("﻿").splitlines()
    assert lines[0].endswith("T-shirt size,Allergies")
    assert lines[1].startswith("\"'=HYPERLINK") and lines[1].endswith(",S,'+peanuts")


# ─── The public page and the member app ──────────────────────────────

def test_the_public_page_shows_the_price_places_and_deadline_in_one_line(db):
    db.t["church_event_signup_setups"][0]["deadline"] = "2026-11-10T04:59:00+00:00"
    occ = ces.annotate(BIZ, [{"entry_id": VBS, "title": "Vacation Bible School", "date": "2026-11-14",
                              "date_label": "Saturday, November 14", "location": "Fellowship hall"}])
    html = er.render_events_page(db.t["businesses"][0], occ, "https://x/events", "love-city-church",
                                 api_origin="https://api")
    assert "Adult $25 · Child $10 · Family $60" in html and "3 places left" in html
    assert "Sign up by Mon, Nov 9" in html and "Continue to payment" in html
    assert "T-shirt size" in html and 'data-q="qshirt"' in html and "required" in html
    assert "/public/events/' + SLUG + path" in html


def test_the_member_app_offers_the_sign_up_where_im_coming_was(db):
    me = {"id": "cccccccc-0000-4000-8000-000000000001", "name": "Cy Moss", "email": "cy@example.org"}
    occ = mpc.upcoming_for(BIZ, me)
    vbs = next(o for o in occ if o["entry_id"] == VBS)
    card = mpc.occasion_card(vbs, "/my/events")
    assert "I'm coming" not in card and 'action="/my/events/signup"' in card and 'name="qty_' in card
    picnic = next(o for o in occ if o["entry_id"] == PICNIC)
    assert "I'm coming" in mpc.occasion_card(picnic, "/my/events")
    # Once they're on the waitlist, the card says exactly what happens next.
    db.t["church_event_signup_setups"][0]["capacity"] = 1
    signup(name="Ann", email="ann@example.org", tickets={ADULT: 1})
    signup(name="Cy Moss", email="cy@example.org", tickets={ADULT: 1}, waitlist=True)
    regs(db, name="Cy Moss")[0]["contact_id"] = me["id"]
    vbs = next(o for o in mpc.upcoming_for(BIZ, me) if o["entry_id"] == VBS)
    card = mpc.occasion_card(vbs, "/my/events")
    assert "number 1 on the waitlist" in card and "24 hours" in card


def test_the_public_sign_up_is_rate_limited_before_anything_is_read(db, monkeypatch):
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: False)
    db.reads = 0
    got = signup()
    assert got.status_code == 429 and db.reads == 0 and not regs(db)

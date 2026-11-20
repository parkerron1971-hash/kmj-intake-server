"""The church's Payments page, the new Overview (payments_overview.py).

Kevin, 2026-11-19: "also upgrade the payments section as well. this needs to
be top tier." Built to the mock he chose on 2026-11-20.

Pins:
  * the shapes the app is built from (the overview, the feed, the download)
  * the period edges: a week starts on Monday, on the church's clock; the
    stretch before never runs past the shorter month
  * the switch: off is a 404, owner is the platform owner's church only, a
    business that isn't a church is a 404
  * every door: the owner, an Admin, the accountant, a See tick without who
    gave or the bank, a tick with the bank but not who gave, a Viewer seat, a
    login of another church, a stranger, the Giving keeper
  * Stripe is read only for a login with the bank part, at most so many
    pages, kept 60 seconds; a part that fails is null with partial: true,
    never a 500, and isn't kept
  * where each gift is: on the way in the next payout, with Stripe, in the
    bank, refunded, didn't go through
  * money going out: each card behind its own page's door

Every church, person and figure here is made up."""
from __future__ import annotations

import asyncio
import csv
import io
import os
import pathlib
import sys
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import church_money_holders as mh  # noqa: E402
import payments_overview as po  # noqa: E402
import sb_clients  # noqa: E402

BIZ = "a1000000-0000-4000-8000-0000000000a1"        # Cedar Hill Church
OTHER = "b1000000-0000-4000-8000-0000000000b1"      # Riverbend Chapel, another church
SHOP = "d1000000-0000-4000-8000-0000000000d1"       # Corner Barbers
UNCONN = "e1000000-0000-4000-8000-0000000000e1"     # Lakeside Fellowship, no Stripe yet
OWNER = "11000000-0000-4000-8000-000000000001"      # Pastor Ruth Alder
OTHER_OWNER = "11000000-0000-4000-8000-000000000002"
ADMIN = "c1100000-0000-4000-8000-000000000001"      # an Admin seat
MANAGER = "c2100000-0000-4000-8000-000000000002"    # a Manager seat (ticks)
VIEWER = "c3100000-0000-4000-8000-000000000003"     # a Viewer seat
ACCOUNTANT = "c4100000-0000-4000-8000-000000000004"  # the outside accountant
OTHER_ADMIN = "c5100000-0000-4000-8000-000000000005"  # an Admin at Riverbend
STRANGER = "c9100000-0000-4000-8000-000000000009"
C1 = "f1000000-0000-4000-8000-000000000001"          # Ada Lovett
C2 = "f1000000-0000-4000-8000-000000000002"          # Ben Carver
ACCT = "acct_cedar1"
PLATFORM = "pastor@cedarhill.example"
NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc)      # Thursday, 3 PM in New York


def ts(y, m, d, h=0, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp())


def iso(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── A small PostgREST stand-in ───────────────────────────────────────

def _split(s):
    return [x.strip().strip('"') for x in s.split(",")] if s else []


def _cmp(row, col, op, val):
    v = row.get(col)
    if op == "not":
        inner_op, _, inner = val.partition(".")
        return not _cmp(row, col, inner_op, inner)
    if op == "is":
        return v is None if val == "null" else str(v).lower() == val
    if op == "in":
        return str(v) in set(_split(val.strip("()")))
    if op == "eq":
        return str(v).lower() == val.lower() if isinstance(v, bool) else str(v) == val
    if op == "neq":
        return str(v) != val
    if v is None:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        val = float(val)
    return {"gt": v > val, "lt": v < val, "gte": v >= val, "lte": v <= val}[op]


class FakeDB:
    def __init__(self, **tables):
        self.t = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.reads = []
        self.down = set()
        self.writes = []

    def get(self, path, **_):
        self.reads.append(path)
        table, _, qs = path.lstrip("/").partition("?")
        if table in self.down:
            return None
        filters, limit = [], None
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            v = unquote(v)
            if k in ("select", "order"):
                continue
            if k == "limit":
                limit = int(v)
                continue
            op, _, val = v.partition(".")
            filters.append((k, op, val))
        rows = [dict(r) for r in self.t.get(table, []) if all(_cmp(r, *f) for f in filters)]
        rows.sort(key=lambda r: str(r.get("id", "")))
        return rows[:limit] if limit else rows

    def write(self, *a, **k):
        self.writes.append(a)
        return []


def _seat(uid, role, biz=BIZ):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_OID, uid + biz)), "business_id": biz, "user_id": uid, "role": role,
            "status": "active", "invited_email": f"{uid[:4]}@cedarhill.example"}


def _gift(n, cents, day, fund="General", number=None, contact=None, refund=None, method="stripe", notes="",
          biz=BIZ):
    return {"id": f"0000000{n}-1111-4111-8111-111111111111", "business_id": biz, "is_gift": True, "status": "paid",
            "payment_method": method, "invoice_number": number or f"GIVE-pi_{n}", "gift_fund": fund,
            "total": cents / 100, "refund_amount_cents": refund, "paid_at": day, "contact_id": contact,
            "notes": notes}


ORDER_ID = "0000000a-2222-4222-8222-222222222222"
REG_ID = "0000000b-3333-4333-8333-333333333333"


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        businesses=[
            {"id": BIZ, "name": "Cedar Hill Church", "type": "church", "owner_id": OWNER, "stripe_account_id": ACCT,
             "settings": {"availability": {"timezone": "America/New_York"}}},
            {"id": OTHER, "name": "Riverbend Chapel", "type": "church", "owner_id": OTHER_OWNER,
             "stripe_account_id": "acct_river1", "settings": {"availability": {"timezone": "America/Chicago"}}},
            {"id": SHOP, "name": "Corner Barbers", "type": "barber", "owner_id": OWNER, "stripe_account_id": "acct_x",
             "settings": {}},
            {"id": UNCONN, "name": "Lakeside Fellowship", "type": "church", "owner_id": OWNER,
             "stripe_account_id": None, "settings": {"availability": {"timezone": "America/New_York"}}},
        ],
        business_users=[_seat(ADMIN, "admin"), _seat(MANAGER, "manager"), _seat(VIEWER, "viewer"),
                        _seat(OTHER_ADMIN, "admin", OTHER)],
        business_collaborators=[{"id": "col1", "business_id": BIZ, "user_id": ACCOUNTANT, "status": "active",
                                 "role": "accountant"}],
        contacts=[{"id": C1, "business_id": BIZ, "name": "Ada Lovett"},
                  {"id": C2, "business_id": BIZ, "name": "Ben  Carver"}],
        invoices=[
            _gift(1, 10000, iso(2026, 11, 18, 15), contact=C1),
            _gift(2, 25000, iso(2026, 11, 10, 15), fund="Building", contact=C2),
            _gift(3, 6000, iso(2026, 11, 5, 15), number="GIVE-in_3", contact=C1,
                  notes="Online gift · General Fund · monthly · ada@example.com"),
            _gift(4, 4000, iso(2026, 11, 12, 15), refund=4000),                        # refunded in full
            _gift(5, 8000, iso(2026, 11, 15, 15), method="cash", number="GIVE-manual-5"),  # not online
            _gift(6, 30000, iso(2026, 10, 10, 15), number="GIVE-pi_old"),              # October
            _gift(7, 99900, iso(2026, 11, 18, 15), biz=OTHER),                          # another church's
        ],
        orders=[{"id": ORDER_ID, "business_id": BIZ, "status": "paid", "total_cents": 3000, "refund_amount_cents": None,
                 "paid_at": iso(2026, 11, 16, 15), "contact_id": None, "customer_name": "Cy Noel",
                 "stripe_payment_intent_id": "pi_5"}],
        church_event_registrations=[{"id": REG_ID, "business_id": BIZ, "status": "paid", "amount_cents": 7500,
                                     "refunded_cents": 0, "paid_at": iso(2026, 11, 17, 14), "contact_id": None,
                                     "name": "Dee Hart", "event_title": "Youth retreat",
                                     "stripe_payment_intent": "pi_6", "stripe_session_id": "cs_6"}],
        plaid_accounts=[{"account_id": "pa1", "business_id": BIZ, "included_in_bookkeeping": True, "deleted_at": None}],
        plaid_transactions=[
            {"transaction_id": "t1", "id": "t1", "business_id": BIZ, "amount": -90.0, "date": "2026-11-13",
             "reconciliation_status": "auto_matched", "reconciled_to_payout_id": "po_paid1", "pending": False},
            {"transaction_id": "t2", "id": "t2", "business_id": BIZ, "amount": -240.0, "date": "2026-11-16",
             "reconciliation_status": "unmatched", "reconciled_to_payout_id": None, "pending": False},
        ],
        bills=[
            {"id": "b1", "business_id": BIZ, "vendor_name": "City Electric", "amount": 284.5, "paid_amount": None,
             "due_date": "2026-11-20", "status": "pending", "is_1099_eligible": False},
            {"id": "b2", "business_id": BIZ, "vendor_name": "Shield Insurance", "amount": 1000.0, "paid_amount": None,
             "due_date": "2026-11-21", "status": "overdue", "is_1099_eligible": False},
            {"id": "b3", "business_id": BIZ, "vendor_name": "Copier lease", "amount": 90.0, "paid_amount": 90.0,
             "due_date": "2026-11-19", "status": "paid", "paid_at": "2026-11-18", "is_1099_eligible": False},
            {"id": "b4", "business_id": BIZ, "vendor_name": "Lawn care", "amount": 120.0, "paid_amount": None,
             "due_date": "2026-11-25", "status": "pending", "is_1099_eligible": False},
            {"id": "b5", "business_id": BIZ, "vendor_name": "Sound tech", "amount": 3000.0, "paid_amount": 3000.0,
             "due_date": "2026-05-01", "status": "paid", "paid_at": "2026-05-02", "is_1099_eligible": True},
            {"id": "b6", "business_id": BIZ, "vendor_name": "Organist", "amount": 1600.0, "paid_amount": 1600.0,
             "due_date": "2026-09-01", "status": "paid", "paid_at": "2026-09-02", "is_1099_eligible": True},
        ],
        contractors=[{"id": "k1", "business_id": BIZ, "w9_received_at": "2026-02-01", "stripe_account_id": None},
                     {"id": "k2", "business_id": BIZ, "w9_received_at": None, "stripe_account_id": "acct_k2"}],
        pay_runs=[{"id": "r1", "business_id": BIZ, "status": "draft", "pay_date": "2026-11-30",
                   "totals": {"employees": 4, "gross": 6371.33, "net": 5000.0}}],
        employees=[{"id": f"e{i}", "business_id": BIZ, "status": "active", "pay_frequency": "monthly"}
                   for i in range(4)],
        church_keepers=[], church_area_keys=[],
        **{mh.HOLDERS: []},
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    for name in ("sb_post_as_service", "sb_patch_as_service", "sb_delete_as_service"):
        monkeypatch.setattr(sb_clients, name, fake.write)
    for k in ("CHURCH_MONEY_TICKS", "CHURCH_AREAS", "CHURCH_KEYS", "STRIPE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PAYMENTS_OVERVIEW", "on")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_cedar")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", PLATFORM)
    monkeypatch.setattr(po, "_now", lambda: NOW)
    import member_asks
    import messaging_router
    import payroll_deposits
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: PLATFORM if uid == OWNER else "")
    monkeypatch.setattr(payroll_deposits, "marked", lambda biz: ({}, False))
    import church_money_ticks
    import rate_limit
    church_money_ticks._READY.update(yes=False, until=0.0)
    po._CACHE.clear()
    rate_limit._buckets.clear()
    yield fake
    po._CACHE.clear()
    rate_limit._buckets.clear()


# ─── A Stripe stand-in ────────────────────────────────────────────────

def _charge(cid, created, cents, *, pi=None, md=None, wallet=None, last4="4242", kind="card", fee=0, net=None,
            available=None, refunded=0, status="succeeded", disputed=False, invoice=None, desc="", name=None):
    pmd = {"type": kind}
    if kind == "card":
        pmd["card"] = {"last4": last4, "wallet": {"type": wallet} if wallet else None}
    return {"id": cid, "created": created, "amount": cents, "amount_refunded": refunded, "refunded": refunded >= cents,
            "disputed": disputed, "status": status, "payment_intent": pi, "invoice": invoice, "description": desc,
            "metadata": md or {}, "billing_details": {"name": name}, "payment_method_details": pmd,
            "balance_transaction": None if available is None else
            {"id": f"txn_{cid}", "fee": fee, "net": cents - fee if net is None else net, "available_on": available}}


def _payout(pid, cents, created, arrival, status):
    return {"id": pid, "amount": cents, "created": created, "arrival_date": arrival, "status": status,
            "automatic": True, "destination": {"id": "ba_1", "last4": "4410"}}


CHARGES = [
    _charge("ch_1", ts(2026, 11, 18, 15), 10000, pi="pi_1", md={"source_type": "gift", "fund": "General",
            "covered_fee_cents": "320", "giver_name": "A. Lovett"}, wallet="apple_pay", fee=320,
            available=ts(2026, 11, 19)),
    _charge("ch_6", ts(2026, 11, 17, 14), 7500, pi="pi_6", md={"source_type": "event_signup"}, last4="1881", fee=248,
            available=ts(2026, 11, 19)),
    _charge("ch_5", ts(2026, 11, 16, 15), 3000, pi="pi_5", md={"source_type": "order", "source_id": ORDER_ID},
            kind="link", fee=117, available=ts(2026, 11, 18)),
    _charge("ch_fail", ts(2026, 11, 15, 15), 5000, status="failed", name="Card Tester"),
    _charge("ch_4", ts(2026, 11, 12, 15), 4000, pi="pi_4", md={"source_type": "gift", "fund": "General"}, fee=146,
            available=ts(2026, 11, 14), refunded=4000),
    _charge("ch_2", ts(2026, 11, 10, 15), 25000, pi="pi_2", md={"source_type": "gift", "fund": "Building"}, fee=755,
            available=ts(2026, 11, 12)),
    _charge("ch_3", ts(2026, 11, 5, 15), 6000, invoice="in_3", desc="Subscription update", wallet="google_pay",
            fee=204, available=ts(2026, 11, 7)),
]
PAYOUTS = [
    _payout("po_next", 10500, ts(2026, 11, 19, 0, 30), ts(2026, 11, 20), "in_transit"),
    _payout("po_paid2", 24000, ts(2026, 11, 14, 0, 30), ts(2026, 11, 16), "paid"),
    _payout("po_paid1", 9000, ts(2026, 11, 12, 0, 30), ts(2026, 11, 13), "paid"),
]


class FakeStripe:
    def __init__(self):
        self.calls = []
        self.down = set()
        self.charges = [dict(c) for c in CHARGES]
        self.payouts = [dict(p) for p in PAYOUTS]
        self.page = 100
        self.disputes = [
            {"id": "dp_1", "amount": 12000, "status": "needs_response", "livemode": False,
             "charge": {"id": "ch_old", "created": ts(2026, 10, 30, 16)},
             "evidence_details": {"due_by": ts(2026, 11, 28, 23, 59) + 59}},
            {"id": "dp_won", "amount": 5000, "status": "won", "livemode": False, "charge": {"created": 1},
             "evidence_details": {"due_by": 1}},
        ]

    def _page(self, rows, params):
        after = params.get("starting_after")
        if after:
            ids = [r["id"] for r in rows]
            rows = rows[ids.index(after) + 1:] if after in ids else []
        return {"data": rows[:self.page], "has_more": len(rows) > self.page}

    async def get(self, client, path, acct, params):
        params = dict(params)
        self.calls.append((acct, path, params))
        if path in self.down or "*" in self.down:
            raise po.StripeDown("down")
        if path == "/balance":
            return {"pending": [{"amount": 5000, "currency": "usd"}], "available": [{"amount": 0, "currency": "usd"}]}
        if path == "/account":
            return {"settings": {"payouts": {"schedule": {"interval": "daily", "delay_days": 2}}}}
        if path == "/disputes":
            return self._page(self.disputes, params)
        if path == "/payouts":
            rows = [p for p in self.payouts if p["created"] >= int(params.get("created[gte]") or 0)]
            return self._page(rows, params)
        if path == "/charges":
            lo, hi = int(params.get("created[gte]") or 0), int(params.get("created[lte]") or 10 ** 12)
            return self._page([c for c in self.charges if lo <= c["created"] <= hi], params)
        if path == "/balance_transactions":
            if params.get("payout") != "po_next":
                return {"data": [], "has_more": False}
            rows = [{"id": "txn_po", "type": "payout", "amount": -10500, "net": -10500, "created": ts(2026, 11, 19)}]
            for c in self.charges:
                if c["id"] in ("ch_1", "ch_6", "ch_5"):
                    rows.append({"id": f"txn_{c['id']}", "type": "payment" if c["id"] == "ch_5" else "charge",
                                 "amount": c["amount"], "net": c["balance_transaction"]["net"],
                                 "created": c["created"], "source": c})
            return {"data": rows, "has_more": False}
        raise AssertionError(path)


@pytest.fixture
def stripe(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(po, "_get", fake.get)
    return fake


def _u(uid):
    return SimpleNamespace(id=uid, email=f"{uid[:4]}@cedarhill.example")


def run(coro):
    return asyncio.run(coro)


def overview(uid, biz=BIZ, period="month"):
    return run(po.payments_overview(biz, period, user=_u(uid)))


def feed(uid, biz=BIZ, period="month", filter=None, q=None, after=None):
    return run(po.payments_feed(biz, period, filter, q, after, user=_u(uid)))


def status_of(fn, *a, **kw):
    with pytest.raises(HTTPException) as e:
        fn(*a, **kw)
    return e.value.status_code


def tick(db, uid, level="see", who=False, bank=False, monkeypatch=None):
    seat = next(s for s in db.t["business_users"] if s["user_id"] == uid and s["business_id"] == BIZ)
    db.t[mh.HOLDERS].append({"business_id": BIZ, "user_id": uid, "seat_id": seat["id"], "level": level,
                             "who_gave": who, "bank": bank, "granted_by": OWNER, "granted_at": iso(2026, 11, 18),
                             "ask_id": None})


# ─── The shape ────────────────────────────────────────────────────────

def test_the_owner_sees_the_whole_page(db, stripe):
    out = overview(OWNER)
    assert set(out) >= {"checked_at", "period", "connected", "path", "next_payout", "needs_you", "by_fund", "methods",
                        "covered_fee", "going_out", "stripe", "can", "partial"}
    assert out["connected"] is True and out["partial"] is False
    assert out["checked_at"] and out["checked_at"].endswith("Z")
    assert out["period"] == {"key": "month", "label": "November", "start": "2026-11-01", "end": "2026-11-19",
                             "week_starts": "monday"}
    path = out["path"]
    # Online gifts and payments, refunds off: 100 + 250 + 60 + the store's 30 + the retreat's 75. Not the cash
    # gift, not the refunded one, not October's, not another church's.
    assert path["given"] == {"cents": 51500, "count": 5, "vs_prior_pct": 72}
    assert path["fees"] == {"cents": 1790, "covered_by_givers_cents": 320, "church_paid_cents": 1470}
    assert path["on_the_way"] == {"cents": 15500, "count": 3, "lands_on": "2026-11-20"}
    assert path["in_bank"] == {"cents": 33000, "payouts": 2, "all_matched": False}
    nxt = out["next_payout"]
    assert nxt["id"] == "po_next" and nxt["cents"] == 10500 and nxt["lands_on"] == "2026-11-20"
    assert nxt["bank_last4"] == "4410" and nxt["count"] == 3 and nxt["more"] == 0
    assert nxt["items"] == [
        {"when": "2026-11-18", "who": "Ada Lovett", "for": "General", "cents": 10000, "net_cents": 9680},
        {"when": "2026-11-17", "who": "Dee Hart", "for": "Youth retreat", "cents": 7500, "net_cents": 7252},
        {"when": "2026-11-16", "who": "Cy Noel", "for": "Store", "cents": 3000, "net_cents": 2883},
    ]
    assert [n["kind"] for n in out["needs_you"]] == ["dispute", "unmatched_payout"]
    dispute, unmatched = out["needs_you"]
    assert dispute == {"kind": "dispute", "id": "dp_1", "cents": 12000, "given_on": "2026-10-30",
                       "due_by": "2026-11-28T23:59:59Z",
                       "action": {"label": "Answer the bank", "href": "https://dashboard.stripe.com/test/disputes/dp_1"}}
    assert unmatched["id"] == "po_paid2" and unmatched["cents"] == 24000 and unmatched["arrived_on"] == "2026-11-16"
    assert unmatched["seen_in_bank"] is True
    assert unmatched["action"] == {"label": "Match it", "nav": {"tab": "operate", "sub": "bookkeeping",
                                                                 "bkTab": "reconciliation"}}
    assert out["by_fund"] == [{"fund": "Building", "cents": 25000, "count": 1},
                              {"fund": "General", "cents": 16000, "count": 2},
                              {"fund": "Events", "cents": 7500, "count": 1},
                              {"fund": "Store", "cents": 3000, "count": 1}]
    methods = {m["method"]: m for m in out["methods"]}
    assert sum(m["share_pct"] for m in out["methods"]) == 100
    assert methods["card"]["share_pct"] == 50 and methods["card"]["count"] == 3 and methods["card"]["words"] == "Card"
    assert set(methods) == {"card", "apple_pay", "google_pay", "link"}
    assert out["covered_fee"] == {"givers": 1, "of": 4}
    assert out["counted"] == {"charges": 6, "complete": True}
    assert out["stripe"] == {"payout_words": "every weekday", "bank_last4": "4410", "can_disconnect": True}
    assert out["can"] == {"see_names": True, "see_bank": True, "refund": True, "download": True}
    go = out["going_out"]
    assert go["pay_staff"] == {"next_payday": "2026-11-30", "people": 4, "gross_cents": 637133,
                               "approve_by": "2026-11-25", "projected": False, "run_id": "r1"}
    assert go["contractors"] == {"year_cents": 460000, "people": 2, "w9_on_file": 2}
    assert go["bills"] == {"due_this_week": 2, "cents": 128450, "names": ["City Electric", "Shield Insurance"]}
    # Every Stripe call is made as the church's own connected account.
    assert stripe.calls and all(acct == ACCT for acct, _, _ in stripe.calls)


def test_every_matched_payout_reads_all_matched_and_no_bank_link_reads_unknown(db, stripe):
    db.t["plaid_transactions"].append({"transaction_id": "t3", "id": "t3", "business_id": BIZ, "amount": -240.0,
                                       "date": "2026-11-16", "reconciliation_status": "auto_matched",
                                       "reconciled_to_payout_id": "po_paid2", "pending": False})
    out = overview(OWNER)
    assert out["path"]["in_bank"]["all_matched"] is True
    assert [n["kind"] for n in out["needs_you"]] == ["dispute"]
    po._CACHE.clear()
    db.t["plaid_accounts"] = []
    out = overview(OWNER)
    assert out["path"]["in_bank"]["all_matched"] is None and [n["kind"] for n in out["needs_you"]] == ["dispute"]


def test_no_payout_on_the_way_and_nothing_needing_anyone(db, stripe):
    stripe.payouts = [p for p in stripe.payouts if p["status"] == "paid"]
    stripe.disputes = []
    db.t["plaid_transactions"].append({"transaction_id": "t3", "id": "t3", "business_id": BIZ, "amount": -240.0,
                                       "date": "2026-11-16", "reconciliation_status": "auto_matched",
                                       "reconciled_to_payout_id": "po_paid2", "pending": False})
    out = overview(OWNER)
    assert out["next_payout"] is None and out["needs_you"] == []
    # Still with Stripe: the three newest gifts, their money not yet in any payout.
    assert out["path"]["on_the_way"] == {"cents": 5000, "count": 3, "lands_on": None}
    assert out["partial"] is False


def test_a_church_without_stripe_gets_the_setup(db, stripe):
    assert overview(OWNER, UNCONN) == {"connected": False, "setup_href": None, "can_connect": True}
    assert stripe.calls == []
    assert status_of(feed, OWNER, UNCONN) == 409


# ─── The period ───────────────────────────────────────────────────────

def test_a_week_starts_on_monday_on_the_churchs_clock():
    p = po.period_of("week", NY, NOW)                                # Thursday Nov 19
    assert (p.start, p.end, p.label) == (date(2026, 11, 16), date(2026, 11, 19), "This week")
    assert p.start_at == datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)   # midnight in New York
    assert (p.week_start, p.week_end) == (date(2026, 11, 16), date(2026, 11, 22))
    assert p.prior_start_at == datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc)
    assert p.prior_end_at == NOW.replace(day=12)
    monday = po.period_of("week", NY, datetime(2026, 11, 16, 5, 30, tzinfo=timezone.utc))
    assert monday.start == date(2026, 11, 16)
    sunday_night = po.period_of("week", NY, datetime(2026, 11, 16, 4, 30, tzinfo=timezone.utc))
    assert sunday_night.start == date(2026, 11, 9) and sunday_night.end == date(2026, 11, 15)


def test_a_month_and_a_year_and_the_stretch_before():
    p = po.period_of("month", NY, datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc))   # still Oct 31 in New York
    assert p.label == "October" and p.start == date(2026, 10, 1)
    m = po.period_of("month", NY, datetime(2027, 3, 31, 18, 0, tzinfo=timezone.utc))
    assert m.prior_start_at == datetime(2027, 2, 1, 5, 0, tzinfo=timezone.utc)
    assert m.prior_end_at == datetime(2027, 3, 1, 5, 0, tzinfo=timezone.utc)          # never past February
    y = po.period_of("year", NY, NOW)
    assert y.label == "2026" and y.start == date(2026, 1, 1)
    assert y.prior_start_at.year == 2025 and y.prior_end_at.date() == date(2025, 11, 19)


def test_a_period_that_isnt_one_is_refused(db, stripe):
    assert status_of(overview, OWNER, BIZ, "decade") == 400


def test_the_week_and_the_year_read_their_own_stretch(db, stripe):
    week = overview(OWNER, period="week")
    # Nov 16 to now: the store's 30, the retreat's 75, Ada's 100. Last week by this time: Ben's 250.
    assert week["path"]["given"] == {"cents": 20500, "count": 3, "vs_prior_pct": -18}
    assert week["path"]["in_bank"] == {"cents": 24000, "payouts": 1, "all_matched": False}
    year = overview(OWNER, period="year")
    assert year["path"]["given"]["cents"] == 51500 + 30000 and year["period"]["label"] == "2026"


# ─── The switch ───────────────────────────────────────────────────────

def test_switched_off_the_page_is_not_there(db, stripe, monkeypatch):
    monkeypatch.setenv("PAYMENTS_OVERVIEW", "off")
    assert status_of(overview, OWNER) == 404
    assert status_of(feed, OWNER) == 404
    assert stripe.calls == []


def test_the_default_is_the_platform_owners_church_only(db, stripe, monkeypatch):
    monkeypatch.delenv("PAYMENTS_OVERVIEW", raising=False)
    assert po.mode() == "owner"
    assert overview(OWNER)["connected"] is True
    assert status_of(overview, OTHER_OWNER, OTHER) == 404
    monkeypatch.setenv("PAYMENTS_OVERVIEW", "on")
    stripe.calls.clear()
    assert overview(OTHER_OWNER, OTHER)["connected"] is True
    assert {acct for acct, _, _ in stripe.calls} == {"acct_river1"}


def test_a_business_that_isnt_a_church_is_not_this_page(db, stripe):
    assert status_of(overview, OWNER, SHOP) == 404
    assert status_of(overview, OWNER, "not-a-uuid") == 404
    assert status_of(overview, OWNER, "a1000000-0000-4000-8000-00000000ffff") == 404
    assert stripe.calls == []


# ─── Who sees what ────────────────────────────────────────────────────

def _no_bank(out):
    p = out["path"]
    assert p["fees"] is None and p["on_the_way"] is None and p["in_bank"] is None
    assert out["next_payout"] is None and out["needs_you"] == [] and out["methods"] is None
    assert out["covered_fee"] is None and out["checked_at"] is None
    assert out["stripe"]["payout_words"] is None and out["stripe"]["bank_last4"] is None
    assert out["can"]["see_bank"] is False and out["can"]["refund"] is False and out["can"]["download"] is False


def test_an_admin_sees_the_gifts_but_not_the_bank_while_the_tick_is_off(db, stripe):
    out = overview(ADMIN)
    _no_bank(out)
    assert out["path"]["given"]["cents"] == 51500 and out["by_fund"]
    assert out["can"]["see_names"] is True and out["stripe"]["can_disconnect"] is False
    assert out["going_out"]["pay_staff"] and out["going_out"]["contractors"] and out["going_out"]["bills"]
    assert stripe.calls == []                                     # Stripe is never asked for them
    assert status_of(feed, ADMIN) == 403
    assert status_of(lambda: run(po.payments_feed_csv(BIZ, "month", None, None, user=_u(ADMIN)))) == 403


def test_the_accountant_reads_the_totals(db, stripe):
    out = overview(ACCOUNTANT)
    _no_bank(out)
    assert out["path"]["given"]["count"] == 5
    assert out["going_out"]["pay_staff"] is None                  # payroll's own door wants a seat
    assert out["going_out"]["bills"]["due_this_week"] == 2


def test_a_see_tick_without_who_gave_or_the_bank(db, stripe, monkeypatch):
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "on")
    tick(db, MANAGER, "see")
    out = overview(MANAGER)
    _no_bank(out)
    assert out["can"]["see_names"] is False
    assert out["path"]["given"]["cents"] == 51500
    # Payroll and contractors want Work; the bills list reads with any tick.
    assert out["going_out"]["pay_staff"] is None and out["going_out"]["contractors"] is None
    assert out["going_out"]["bills"]["due_this_week"] == 2
    assert stripe.calls == []


def test_the_bank_tick_without_who_gave_shows_no_names_and_no_card_numbers(db, stripe, monkeypatch):
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "on")
    tick(db, MANAGER, "see", bank=True)
    out = overview(MANAGER)
    assert out["can"] == {"see_names": False, "see_bank": True, "refund": False, "download": True}
    assert out["path"]["on_the_way"]["cents"] == 15500
    assert [i["who"] for i in out["next_payout"]["items"]] == [None, None, None]
    assert out["stripe"]["can_disconnect"] is False
    rows = feed(MANAGER)["rows"]
    assert rows and all(r["who"] is None for r in rows)
    assert {r["how"] for r in rows} <= {"Card", "Apple Pay", "Google Pay", "Link"}       # no last four
    # The church's day only, never the time of day: with the amount, the fund
    # and the method, a time could point at one person in a small church.
    assert [r["when"] for r in rows][:3] == ["2026-11-18", "2026-11-17", "2026-11-16"]
    assert feed(MANAGER, q="ada")["rows"] == []                   # a name can't be found by searching for it
    text = run(po.payments_feed_csv(BIZ, "month", None, None, user=_u(MANAGER))).body.decode()
    table = list(csv.reader(io.StringIO(text)))
    assert table[0] == ["Date", "For", "How", "Amount", "Refunded", "Stripe fee", "Fee covered by the giver",
                        "Where it is", "Payout"]
    assert table[1] == ["2026-11-18", "General", "Apple Pay", "100.00", "", "3.20", "yes", "On the way", "po_next"]
    assert "Ada" not in text and "Lovett" not in text and "4242" not in text and "10:00" not in text


def test_the_bank_tick_at_work_with_who_gave_refunds_and_names(db, stripe, monkeypatch):
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "on")
    tick(db, MANAGER, "work", who=True, bank=True)
    out = overview(MANAGER)
    assert out["can"] == {"see_names": True, "see_bank": True, "refund": True, "download": True}
    assert out["next_payout"]["items"][0]["who"] == "Ada Lovett"
    assert out["stripe"]["can_disconnect"] is False               # connecting and disconnecting stay the owner's


def test_an_admin_given_the_bank_sees_it(db, stripe, monkeypatch):
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "on")
    tick(db, ADMIN, "see", bank=True)
    out = overview(ADMIN)
    assert out["can"] == {"see_names": True, "see_bank": True, "refund": True, "download": True}


def test_a_viewer_seat_another_church_and_a_stranger_are_refused(db, stripe):
    assert status_of(overview, VIEWER) == 403
    assert status_of(overview, OTHER_ADMIN) == 403
    assert status_of(overview, STRANGER) == 403
    assert status_of(overview, OTHER_OWNER) == 403
    assert status_of(feed, OTHER_ADMIN) == 403
    assert stripe.calls == []


def test_the_giving_keeper_holds_the_owner_to_the_key(db, stripe):
    db.t["church_keepers"].append({"business_id": BIZ, "area": "giving_money", "user_id": ADMIN,
                                   "added_by": OWNER, "added_at": iso(2026, 11, 1), "starts_at": iso(2026, 11, 1),
                                   "ends_at": None})
    assert status_of(overview, OWNER) == 403
    assert overview(ADMIN)["can"]["see_bank"] is False            # the keeper reads, without the bank
    assert stripe.calls == []


def test_the_page_asks_the_same_doors_as_the_stripe_proxy_and_the_refund():
    src = pathlib.Path(ROOT, "payments_overview.py").read_text(encoding="utf-8")
    proxy = pathlib.Path(ROOT, "stripe_data_proxy.py").read_text(encoding="utf-8")
    assert 'church_keys.wall(business_id, user, "giving_money")' in src and \
        'church_keys.wall(business_id, user, "giving_money")' in proxy
    assert 'tick_admits(business_id, user, "see", "payouts")' in src
    assert 'tick_admits(business_id, user, "work", "payouts")' in src
    assert 'require_money(business_id, user, "see", "books"' in src
    assert "SUPABASE_ANON" not in src and "sb_get_as_user" not in src
    main = pathlib.Path(ROOT, "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert main.index("app.include_router(payments_overview_router)") < main.index(
        "app.include_router(public_site_router)")


# ─── Stripe: the cache, the caps, failures ────────────────────────────

def test_stripe_is_read_once_a_minute(db, stripe, monkeypatch):
    first = overview(OWNER)
    n = len(stripe.calls)
    assert n > 0
    again = overview(OWNER)
    assert len(stripe.calls) == n and again["checked_at"] == first["checked_at"]
    later = po._wall() + po.CACHE_SECONDS + 1
    monkeypatch.setattr(po, "_wall", lambda: later)
    overview(OWNER)
    assert len(stripe.calls) == 2 * n


def test_a_church_that_reconnects_is_never_shown_the_old_accounts_numbers(db, stripe):
    overview(OWNER)
    biz = next(b for b in db.t["businesses"] if b["id"] == BIZ)
    biz["stripe_account_id"] = "acct_cedar2"
    stripe.calls.clear()
    overview(OWNER)
    assert stripe.calls and {acct for acct, _, _ in stripe.calls} == {"acct_cedar2"}


def test_a_year_of_charges_is_never_hundreds_of_calls(db, stripe, monkeypatch):
    many = [_charge(f"ch_m{i:04d}", ts(2026, 11, 18, 12) - i * 600, 2000, fee=88, available=ts(2026, 11, 20))
            for i in range(5000)]
    stripe.charges = many
    out = overview(OWNER, period="year")
    charge_calls = [c for c in stripe.calls if c[1] == "/charges"]
    assert len(charge_calls) == po.CHARGE_PAGES
    assert len(stripe.calls) <= po.CHARGE_PAGES + po.PAYOUT_PAGES + 2 * po.ITEM_PAGES + 3
    assert out["counted"] == {"charges": po.CHARGE_PAGES * 100, "complete": False}
    # The year's total is the church's own records, every one of them.
    assert out["path"]["given"]["cents"] == 81500


def test_stripe_down_is_a_page_with_holes_never_a_500(db, stripe):
    stripe.down.add("*")
    out = overview(OWNER)
    assert out["partial"] is True and out["checked_at"] is None
    assert out["path"]["given"]["cents"] == 51500 and out["by_fund"]
    assert out["path"]["fees"] is None and out["path"]["on_the_way"] is None and out["path"]["in_bank"] is None
    assert out["next_payout"] is None and out["needs_you"] == [] and out["methods"] is None
    assert out["stripe"]["payout_words"] is None
    assert out["going_out"]["bills"]
    assert status_of(feed, OWNER) == 503


def test_one_part_failing_leaves_the_rest_and_is_read_again(db, stripe):
    stripe.down.add("/balance")
    out = overview(OWNER)
    assert out["partial"] is True and out["path"]["on_the_way"] is None
    assert out["path"]["in_bank"]["cents"] == 33000 and out["next_payout"]["id"] == "po_next"
    stripe.down.clear()
    stripe.calls.clear()
    out = overview(OWNER)
    assert [c[1] for c in stripe.calls] == ["/balance"]           # only what failed is read again
    assert out["partial"] is False and out["path"]["on_the_way"]["cents"] == 15500


def test_the_records_failing_is_a_hole_too(db, stripe):
    db.down.add("invoices")
    out = overview(OWNER)
    assert out["partial"] is True and out["path"]["given"] is None and out["by_fund"] is None
    assert out["path"]["fees"]["cents"] == 1790


def test_no_stripe_key_is_a_hole_and_nothing_is_sent(db, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    sent = []
    monkeypatch.setattr(po.httpx.AsyncClient, "get", lambda *a, **k: sent.append(a))
    out = overview(OWNER)
    assert out["partial"] is True and out["path"]["on_the_way"] is None and out["path"]["given"]["cents"] == 51500
    assert sent == []


# ─── Where each gift is ───────────────────────────────────────────────

def test_where_each_gift_is(db, stripe):
    rows = {r["id"]: r for r in feed(OWNER)["rows"]}
    assert (rows["ch_1"]["where"], rows["ch_1"]["payout_id"], rows["ch_1"]["where_words"]) == \
        ("on_the_way", "po_next", "On the way")
    assert (rows["ch_2"]["where"], rows["ch_2"]["payout_id"]) == ("in_bank", "po_paid1")
    assert (rows["ch_4"]["where"], rows["ch_4"]["where_words"]) == ("refunded", "Refunded")
    assert (rows["ch_fail"]["where"], rows["ch_fail"]["fee_cents"]) == ("failed", None)
    stripe.payouts = [p for p in stripe.payouts if p["id"] != "po_next"]
    po._CACHE.clear()
    rows = {r["id"]: r for r in feed(OWNER)["rows"]}
    assert (rows["ch_1"]["where"], rows["ch_1"]["where_words"], rows["ch_1"]["payout_id"]) == \
        ("on_the_way", "With Stripe, on the way", None)


# ─── The feed ─────────────────────────────────────────────────────────

def test_the_feed_rows(db, stripe):
    out = feed(OWNER)
    assert set(out) >= {"rows", "has_more", "next", "shown", "total"}
    assert out["has_more"] is False and out["next"] is None and out["shown"] == out["total"] == 7
    assert [r["id"] for r in out["rows"]] == [c["id"] for c in CHARGES]               # newest first
    first = out["rows"][0]
    assert first == {"id": "ch_1", "when": "2026-11-18T15:00:00Z", "who": "Ada Lovett", "for": "General",
                     "kind": "gift", "how": "Apple Pay", "method": "apple_pay", "cents": 10000, "refunded_cents": 0,
                     "fee_cents": 320, "fee_covered": True, "where": "on_the_way", "where_words": "On the way",
                     "payout_id": "po_next"}
    by = {r["id"]: r for r in out["rows"]}
    assert by["ch_2"]["how"] == "Card 4242" and by["ch_2"]["who"] == "Ben Carver"
    assert by["ch_3"]["for"] == "General, every month" and by["ch_3"]["kind"] == "gift"
    assert by["ch_5"]["for"] == "Store" and by["ch_5"]["who"] == "Cy Noel" and by["ch_5"]["how"] == "Link"
    assert by["ch_6"]["for"] == "Youth retreat" and by["ch_6"]["kind"] == "event"
    assert by["ch_fail"]["who"] == "Card Tester"


@pytest.mark.parametrize("f,ids", [
    ("gifts", ["ch_1", "ch_4", "ch_2", "ch_3"]),
    ("store", ["ch_5"]),
    ("events", ["ch_6"]),
    ("refunded", ["ch_4"]),
    ("on_the_way", ["ch_1", "ch_6", "ch_5"]),
    ("disputed", []),
])
def test_the_filter_chips(db, stripe, f, ids):
    out = feed(OWNER, filter=f)
    assert [r["id"] for r in out["rows"]] == ids and out["total"] == len(ids)


def test_a_filter_that_isnt_one_is_refused(db, stripe):
    assert status_of(feed, OWNER, filter="everything") == 400
    assert status_of(feed, OWNER, after="ch_1&limit=1") == 400


def test_find_a_gift(db, stripe):
    assert [r["id"] for r in feed(OWNER, q="lovett")["rows"]] == ["ch_1", "ch_3"]
    assert [r["id"] for r in feed(OWNER, q="$250")["rows"]] == ["ch_2"]
    assert [r["id"] for r in feed(OWNER, q="250.00")["rows"]] == ["ch_2"]
    assert [r["id"] for r in feed(OWNER, q="retreat")["rows"]] == ["ch_6"]
    assert feed(OWNER, q="nobody at all")["rows"] == []


def test_the_feed_pages(db, stripe, monkeypatch):
    monkeypatch.setattr(po, "FEED_PAGE", 3)
    one = feed(OWNER)
    assert [r["id"] for r in one["rows"]] == ["ch_1", "ch_6", "ch_5"]
    assert one["has_more"] is True and one["next"] == "ch_5" and one["shown"] == 3 and one["total"] == 7
    two = feed(OWNER, after=one["next"])
    assert [r["id"] for r in two["rows"]] == ["ch_fail", "ch_4", "ch_2"] and two["shown"] == 6
    three = feed(OWNER, after=two["next"])
    assert [r["id"] for r in three["rows"]] == ["ch_3"] and three["has_more"] is False and three["shown"] == 7
    assert status_of(feed, OWNER, after="ch_gone") == 400


def test_past_the_kept_charges_the_feed_reads_on(db, stripe, monkeypatch):
    monkeypatch.setattr(po, "FEED_PAGE", 2)
    monkeypatch.setattr(po, "CHARGE_PAGES", 1)
    stripe.page = 3
    one = feed(OWNER)
    assert [r["id"] for r in one["rows"]] == ["ch_1", "ch_6"] and one["total"] is None and one["shown"] == 2
    two = feed(OWNER, after=one["next"])
    assert [r["id"] for r in two["rows"]] == ["ch_5", "ch_fail"] and two["has_more"] is True
    three = feed(OWNER, after=two["next"])
    assert [r["id"] for r in three["rows"]] == ["ch_4", "ch_2"] and three["shown"] is None
    four = feed(OWNER, after=three["next"])
    assert [r["id"] for r in four["rows"]] == ["ch_3"] and four["has_more"] is False


# ─── The download ─────────────────────────────────────────────────────

def test_the_download_for_the_books(db, stripe):
    stripe.charges[3] = dict(stripe.charges[3], billing_details={"name": "=HYPERLINK(\"http://x\")"})
    resp = run(po.payments_feed_csv(BIZ, "month", None, None, user=_u(OWNER)))
    assert resp.media_type.startswith("text/csv")
    assert resp.headers["content-disposition"] == 'attachment; filename="payments-month-2026-11-19.csv"'
    assert resp.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(resp.body.decode())))
    assert rows[0] == ["Date", "Time", "From", "For", "How", "Amount", "Refunded", "Stripe fee",
                       "Fee covered by the giver", "Where it is", "Payout"]
    assert rows[1] == ["2026-11-18", "10:00", "Ada Lovett", "General", "Apple Pay", "100.00", "", "3.20", "yes",
                       "On the way", "po_next"]
    assert len(rows) == 8
    tester = next(r for r in rows if r[4] == "Card 4242" and r[5] == "50.00")
    assert tester[2].startswith("'=")                               # never runs as a formula
    gifts = list(csv.reader(io.StringIO(run(po.payments_feed_csv(BIZ, "month", "gifts", None,
                                                                 user=_u(OWNER))).body.decode())))
    assert len(gifts) == 5


# ─── After the security review (2026-11-20) ───────────────────────────

def test_the_cache_drops_what_has_run_out_on_every_read_and_write(db, stripe, monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(po, "_wall", lambda: clock[0])
    overview(OWNER)
    assert po._CACHE and any(v[2] >= 7 for v in po._CACHE.values())      # the month's charges are held
    clock[0] += po.CACHE_SECONDS
    assert po._cached(("nobody", "-", "balance")) is None                 # a read ...
    assert po._CACHE == {}                                                 # ... drops every one that ran out
    po._keep(("a", "-", "balance"), {"pending": 0, "available": 0})
    clock[0] += po.CACHE_SECONDS + 1
    po._keep(("b", "-", "balance"), {"pending": 0, "available": 0})       # ... and so does a write
    assert list(po._CACHE) == [("b", "-", "balance")]


def test_the_cache_is_held_under_its_entries_and_rows_oldest_out_first(db, monkeypatch):
    clock = [2_000_000.0]
    monkeypatch.setattr(po, "_wall", lambda: clock[0])
    monkeypatch.setattr(po, "CACHE_MAX_ROWS", 5)
    for name in ("one", "two", "three"):
        po._keep((name, "-", "charges"), {"rows": [{}, {}, {}], "complete": True})
        clock[0] += 1
    assert list(po._CACHE) == [("three", "-", "charges")]                # 3 + 3 > 5: the older ones go
    monkeypatch.setattr(po, "CACHE_MAX_ROWS", 10_000)
    monkeypatch.setattr(po, "CACHE_MAX", 2)
    for name in ("four", "five"):
        po._keep((name, "-", "balance"), {"pending": 0, "available": 0})
        clock[0] += 1
    assert list(po._CACHE) == [("four", "-", "balance"), ("five", "-", "balance")]
    assert sum(v[2] for v in po._CACHE.values()) <= 10_000


def test_the_download_is_rate_limited_per_login(db, stripe, monkeypatch):
    import rate_limit
    monkeypatch.setitem(rate_limit._LIMITS, "payments_feed_csv", (1, 600))
    run(po.payments_feed_csv(BIZ, "month", None, None, user=_u(OWNER)))
    with pytest.raises(HTTPException) as e:
        run(po.payments_feed_csv(BIZ, "month", None, None, user=_u(OWNER)))
    assert e.value.status_code == 429 and e.value.detail == po.DOWNLOADS_429
    assert e.value.headers == {"Retry-After": "600"}
    monkeypatch.setenv("CHURCH_MONEY_TICKS", "on")
    tick(db, ADMIN, "see", bank=True)
    run(po.payments_feed_csv(BIZ, "month", None, None, user=_u(ADMIN)))   # another login has its own


def test_the_feed_is_rate_limited_per_login(db, stripe, monkeypatch):
    import rate_limit
    monkeypatch.setitem(rate_limit._LIMITS, "payments_feed", (2, 60))
    feed(OWNER)
    feed(OWNER, filter="gifts")
    with pytest.raises(HTTPException) as e:
        feed(OWNER, q="lovett")
    assert e.value.status_code == 429 and e.value.detail == po.FEED_429


def test_only_a_read_that_goes_to_stripe_takes_from_the_stripe_budget(db, stripe, monkeypatch):
    import rate_limit
    monkeypatch.setitem(rate_limit._LIMITS, "payments_stripe", (1, 600))
    clock = [3_000_000.0]
    monkeypatch.setattr(po, "_wall", lambda: clock[0])
    overview(OWNER)                                        # cold: Stripe is read, one taken
    overview(OWNER)                                        # kept: nothing taken
    feed(OWNER)                                            # the feed's payouts and charges are kept too
    n = len(stripe.calls)
    clock[0] += po.CACHE_SECONDS + 1
    with pytest.raises(HTTPException) as e:                # cold again, and the budget is spent
        overview(OWNER)
    assert e.value.status_code == 429 and e.value.detail == po.STRIPE_429
    assert len(stripe.calls) == n                          # refused before Stripe was asked
    with pytest.raises(HTTPException) as e:
        feed(OWNER)
    assert e.value.status_code == 429
    for _ in range(3):
        assert overview(ADMIN)["can"]["see_bank"] is False    # no bank part: Stripe is never asked, never limited


def test_a_csv_cell_that_starts_like_a_formula_after_spaces_is_text(db, stripe):
    names = {"ch_fail": " =HYPERLINK(\"http://x\",\"y\")", "ch_4": "\t+cmd|' /C calc'!A0",
             "ch_2": "​@SUM(1+1)", "ch_3": "  Ann   \n Lee  "}
    stripe.charges = [dict(c, billing_details={"name": names.get(c["id"])}, invoice=None,
                           payment_intent=None, metadata={}) for c in stripe.charges]
    rows = list(csv.reader(io.StringIO(run(po.payments_feed_csv(BIZ, "month", None, None,
                                                                user=_u(OWNER))).body.decode())))
    by_amount = {r[5]: r for r in rows[1:]}
    assert by_amount["50.00"][2] == "'=HYPERLINK(\"http://x\",\"y\")"
    assert by_amount["40.00"][2] == "'+cmd|' /C calc'!A0"
    assert by_amount["250.00"][2] == "'@SUM(1+1)"
    assert by_amount["60.00"][2] == "Ann Lee"
    assert all(not cell[:1] in ("=", "+", "-", "@", " ", "\t") for r in rows for cell in r)
    feed_rows = {r["id"]: r for r in feed(OWNER)["rows"]}
    assert feed_rows["ch_3"]["who"] == "Ann Lee" and feed_rows["ch_fail"]["who"].startswith("=")   # JSON: as given


def test_off_or_not_a_church_is_a_404_for_everyone_before_any_door(db, stripe, monkeypatch):
    for who in (STRANGER, OTHER_ADMIN, VIEWER):
        assert status_of(overview, who, SHOP) == 404
    monkeypatch.setenv("PAYMENTS_OVERVIEW", "off")
    for who in (OWNER, ADMIN, STRANGER, OTHER_ADMIN, VIEWER):
        assert status_of(overview, who) == 404, who
        assert status_of(feed, who) == 404, who
    monkeypatch.setenv("PAYMENTS_OVERVIEW", "owner")
    assert status_of(overview, STRANGER, OTHER) == 404       # Riverbend isn't the platform owner's church
    assert status_of(overview, STRANGER) == 403              # open here, so the door answers
    db.reads.clear()
    status_of(overview, STRANGER, SHOP)
    assert not any("business_users" in r or "business_collaborators" in r for r in db.reads)   # no door asked


def test_ids_are_matched_whole_never_up_to_a_trailing_newline(db, stripe):
    assert po._UUID.fullmatch(BIZ) and not po._UUID.fullmatch(BIZ + "\n")
    assert po._STRIPE_ID.fullmatch("po_next") and not po._STRIPE_ID.fullmatch("po_next\n")
    assert status_of(overview, OWNER, BIZ + "\n") == 404
    assert status_of(feed, OWNER, after="ch_1\n") == 400
    src = pathlib.Path(ROOT, "payments_overview.py").read_text(encoding="utf-8")
    assert "_UUID.match(" not in src and "_STRIPE_ID.match(" not in src

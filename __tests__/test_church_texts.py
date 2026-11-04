"""A church plan's monthly texts: the count, the heads-up, the bill
(2026-11-03, Kevin approving the church-pricing plan: "make the fixes").

Each church plan includes texts a month (500 / 1,500 / 3,000 / 8,000).
Past that, extra texts are $20 per 1,000 on the next bill. A text is never
stopped. The church hears at 80% and at 100%. Sign-in codes don't count.
A month is billed once, and never from a count that couldn't be read.

A text is a 160-character part, the way Twilio bills (Kevin, 2026-11-03:
"count what Twilio bills"): a 3-part announcement is 3 texts.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys
from datetime import datetime, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import church_texts as ct
import sb_clients

NOV = datetime(2026, 11, 3, 9, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _church_prices(monkeypatch):
    """businesses.subscription_plan holds the Stripe PRICE id (the webhook
    writes the price), so the tests use price ids the way production does."""
    for key in ("SMALL", "GROWING", "ESTABLISHED", "LARGE"):
        monkeypatch.setenv(f"STRIPE_PRICE_ID_CHURCH_{key}", f"price_{key.lower()}")
        monkeypatch.setenv(f"STRIPE_PRICE_ID_CHURCH_{key}_ANNUAL", f"price_{key.lower()}_yr")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")


def _row(**kw):
    row = {"id": "biz-1", "name": "Grace Church", "settings": {"theme": "dark"},
           "comp_tier": None, "subscription_plan": "price_growing", "subscription_status": "active",
           "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1"}
    row.update(kw)
    return row


# ─── Which plan: the stored value is a price id ──────────────────────

@pytest.mark.parametrize("stored,plan", [("price_small", "church_small"), ("price_growing", "church_growing"),
                                         ("price_large_yr", "church_large"), ("price_pro", None),
                                         ("price_unknown", None), (None, None)])
def test_the_plan_comes_from_the_price(stored, plan):
    assert ct.church_plan_of({"subscription_plan": stored}) == plan


def test_a_plan_key_in_the_price_column_is_not_trusted():
    # The webhook only ever writes a price there; a bare key is not a church.
    assert ct.church_plan_of({"subscription_plan": "church_growing"}) is None


def test_a_comp_wins_and_is_never_billed():
    row = _row(comp_tier="church_established", subscription_plan="price_small")
    assert ct.church_plan_of(row) == "church_established"
    assert ct.paid_church_plan_of(row) is None
    assert ct.paid_church_plan_of(_row()) == "church_growing"


def test_the_tick_finds_churches_by_their_prices_and_comps():
    path = ct._church_rows_path()
    assert path.startswith("/businesses?or=(subscription_plan.in.(")
    for pid in ("price_small", "price_growing_yr", "price_established", "price_large"):
        assert pid in path
    assert "price_pro" not in path
    assert "comp_tier.in.(church_small,church_growing,church_established,church_large)" in path
    assert "comp_tier" in path.split("select=")[1]


def test_with_no_church_prices_set_the_tick_still_finds_comps(monkeypatch):
    for key in ("SMALL", "GROWING", "ESTABLISHED", "LARGE"):
        monkeypatch.delenv(f"STRIPE_PRICE_ID_CHURCH_{key}", raising=False)
        monkeypatch.delenv(f"STRIPE_PRICE_ID_CHURCH_{key}_ANNUAL", raising=False)
    assert ct._church_rows_path().startswith("/businesses?or=(comp_tier.in.(")


# ─── The plan's texts and the price ──────────────────────────────────

@pytest.mark.parametrize("plan,n", [("church_small", 500), ("church_growing", 1500),
                                    ("church_established", 3000), ("church_large", 8000)])
def test_each_church_plan_has_its_texts(plan, n):
    assert ct.included_for(plan) == n


@pytest.mark.parametrize("plan", ["starter", "professional", "practice", "solo", None, ""])
def test_other_plans_have_no_text_allowance(plan):
    assert ct.included_for(plan) is None
    assert ct.summary("biz-1", plan) is None


def test_extra_texts_are_two_cents_each():
    assert ct.extra_cents(0) == 0
    assert ct.extra_cents(-5) == 0
    assert ct.extra_cents(40) == 80
    assert ct.extra_cents(1000) == 2000
    assert ct.extra_cents(2350) == 4700


def test_the_price_follows_the_dial(monkeypatch):
    monkeypatch.setenv("PRICE_EXTRA_TEXTS_CENTS_PER_THOUSAND", "1500")
    assert ct.extra_cents(1000) == 1500


def test_months_roll_over_the_year():
    jan = datetime(2027, 1, 9, tzinfo=timezone.utc)
    assert ct.month_key(ct.previous_month_start(jan)) == "2026-12"
    dec = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert ct.month_key(ct.next_month_start(dec)) == "2027-01"
    assert ct.month_key(ct.previous_month_start(NOV)) == "2026-10"


# ─── Counting: by 160-character part ─────────────────────────────────

def _usage(parts):
    """api_usage rows, one per message, each with the parts Twilio billed."""
    return [{"id": f"{i:06d}", "input_tokens": p} for i, p in enumerate(parts)]


class _Pages:
    """sb_get_as_service over api_usage rows, paged by id the way
    sb_get_all_as_service asks for them. `fail_at` fails that call (1-based)."""

    def __init__(self, rows, fail_at=None):
        self.rows, self.fail_at, self.calls = rows, fail_at, []

    def get(self, path):
        self.calls.append(path)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            return None
        m = re.search(r"&id=gt\.([^&]+)", path)
        rows = [r for r in self.rows if m is None or r["id"] > m.group(1)]
        return rows[:sb_clients.PAGE_ROWS]

    def install(self, monkeypatch):
        monkeypatch.setattr(sb_clients, "sb_get_as_service", self.get)
        return self


def test_the_count_leaves_out_sign_in_codes_and_is_bounded():
    start = ct.previous_month_start(NOV)
    path = ct._count_path("biz-1", start, ct.next_month_start(start))
    assert "endpoint=eq.sms" in path
    assert "task_type=neq.sms_signin_code" in path
    assert "created_at=gte.2026-10-01T00:00:00Z" in path
    assert "created_at=lt.2026-11-01T00:00:00Z" in path
    assert "business_id=eq.biz-1" in path
    assert path.endswith("&select=id,input_tokens")            # the parts, not a HEAD count


@pytest.mark.parametrize("row,parts", [({"input_tokens": 1}, 1), ({"input_tokens": 3}, 3),
                                       ({"input_tokens": 0}, 1), ({"input_tokens": None}, 1),
                                       ({}, 1), ({"input_tokens": "x"}, 1), ({"input_tokens": -2}, 1)])
def test_a_message_counts_its_parts_and_never_less_than_one(row, parts):
    assert ct.parts_of(row) == parts


def test_long_messages_count_as_more_than_one_text(monkeypatch):
    # 148 people get a 3-part announcement, and 10 get a short reminder.
    _Pages(_usage([3] * 148 + [1] * 10)).install(monkeypatch)
    assert ct.counted("biz-1", ct.month_start(NOV)) == (158, 454)
    assert ct.counted_texts("biz-1", ct.month_start(NOV)) == 454


def test_every_page_is_summed_not_the_first_1000(monkeypatch):
    pages = _Pages(_usage([2] * 2300)).install(monkeypatch)
    assert ct.counted("biz-1", ct.month_start(NOV)) == (2300, 4600)
    assert len(pages.calls) == 3
    assert all("order=id.asc" in c and "limit=1000" in c for c in pages.calls)


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_an_unread_page_is_none_never_a_short_count(monkeypatch, fail_at):
    _Pages(_usage([2] * 2300), fail_at=fail_at).install(monkeypatch)
    assert ct.counted("biz-1", ct.month_start(NOV)) is None


def test_no_business_no_count(monkeypatch):
    pages = _Pages(_usage([1])).install(monkeypatch)
    assert ct.counted("", ct.month_start(NOV)) is None
    assert pages.calls == []


def test_an_empty_month_is_zero(monkeypatch):
    _Pages([]).install(monkeypatch)
    assert ct.counted("biz-1", ct.month_start(NOV)) == (0, 0)


def test_an_unread_count_is_none_never_zero(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: None)
    assert ct.counted_texts("biz-1", ct.month_start(NOV)) is None
    s = ct.summary("biz-1", "church_growing", now=NOV)
    assert s["used"] is None and s["left"] is None and s["extra"] is None and s["extra_cents"] is None
    assert s["messages"] is None
    assert s["included"] == 1500


def test_summary_over_the_plan(monkeypatch):
    _Pages(_usage([2] * 800)).install(monkeypatch)              # 800 two-part messages
    s = ct.summary("biz-1", "church_growing", now=NOV)
    assert s["used"] == 1600 and s["messages"] == 800 and s["left"] == 0 and s["extra"] == 100
    assert s["extra_cents"] == 200 and s["pct"] == 107
    assert s["month"] == "2026-11" and s["resets_at"] == "2026-12-01T00:00:00Z"
    assert s["never_blocked"] is True


def test_summary_keeps_the_fields_the_app_reads(monkeypatch):
    _Pages(_usage([1] * 10)).install(monkeypatch)
    s = ct.summary("biz-1", "church_small", now=NOV)
    for key in ("included", "used", "left", "extra", "extra_cents", "pct", "month", "resets_at",
                "per_thousand_cents", "never_blocked", "messages"):
        assert key in s, key
    assert (s["used"], s["left"], s["pct"]) == (10, 490, 2)


# ─── The heads-up ────────────────────────────────────────────────────

@pytest.mark.parametrize("used,level", [(0, None), (1199, None), (1200, 80), (1499, 80),
                                        (1500, 100), (4000, 100), (None, None)])
def test_heads_up_levels(used, level):
    assert ct.level_for(used, 1500) == level


class _Sb:
    """Stand-ins for the service reads and writes, recording each."""

    def __init__(self, count=1200, sent=(), plan="price_growing", fail_sent=False, messages=None):
        self.count, self.sent, self.plan, self.fail_sent = count, list(sent), plan, fail_sent
        self.messages = messages
        self.posts = []

    def get(self, path):
        if path.startswith("/chief_notifications"):
            return None if self.fail_sent else self.sent
        if path.startswith("/businesses"):
            return [{"subscription_plan": self.plan}]
        return []

    def post(self, path, body, prefer=None):
        self.posts.append((path, body))
        return [body]

    def install(self, monkeypatch):
        monkeypatch.setattr(sb_clients, "sb_get_as_service", self.get)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", self.post)
        monkeypatch.setattr(ct, "counted", lambda bid, start, end=None: (
            None if self.count is None else (self.messages, self.count)))
        return self


def test_eighty_percent_heads_up_once(monkeypatch):
    sb = _Sb(count=1250, messages=640).install(monkeypatch)
    assert ct.check_allowance("biz-1", now=NOV) == 80
    path, body = sb.posts[0]
    assert path == "/chief_notifications" and body["type"] == "text_allowance"
    assert body["data"] == {"month": "2026-11", "level": 80, "used": 1250, "messages": 640,
                            "included": 1500, "per_thousand_cents": 2000}
    assert body["title"] == "1,250 of your 1,500 texts used this month"
    assert "$20 per 1,000" in body["body"] and "Nothing stops" in body["body"]
    assert "(640 messages so far)" in body["body"]
    assert "A text is up to 160 characters; a longer one counts as 2 or more." in body["body"]
    # Sent already this month: not again.
    sb.sent = [{"id": "n1", "data": body["data"]}]
    sb.posts.clear()
    assert ct.check_allowance("biz-1", now=NOV) is None
    assert sb.posts == []


def test_hundred_percent_after_eighty(monkeypatch):
    sb = _Sb(count=1500, sent=[{"id": "n1", "data": {"month": "2026-11", "level": 80}}]).install(monkeypatch)
    assert ct.check_allowance("biz-1", now=NOV) == 100
    body = sb.posts[0][1]
    assert body["priority"] == "high"
    assert "Every text still goes out" in body["body"]
    assert "December 1" in body["body"]
    assert body["body"].startswith("1,500 texts so far in November. A text is up to 160 characters")


def test_the_full_heads_up_names_the_messages_behind_the_texts():
    title, body = ct.notice(100, 1520, 1500, ct.month_start(NOV), messages=790)
    assert title == "You've used this month's 1,500 texts"
    assert body.startswith("1,520 texts so far in November, from 790 messages. A text is up to 160 "
                           "characters; a longer one counts as 2 or more. Every text still goes out")


def test_last_months_notice_doesnt_count(monkeypatch):
    sb = _Sb(count=1500, sent=[{"id": "n0", "data": {"month": "2026-10", "level": 100}}]).install(monkeypatch)
    assert ct.check_allowance("biz-1", now=NOV) == 100
    assert len(sb.posts) == 1


def test_no_heads_up_when_what_was_sent_cant_be_read(monkeypatch):
    sb = _Sb(count=1500, fail_sent=True).install(monkeypatch)
    assert ct.check_allowance("biz-1", now=NOV) is None
    assert sb.posts == []


def test_no_heads_up_from_an_unread_count(monkeypatch):
    sb = _Sb(count=None).install(monkeypatch)
    assert ct.check_allowance("biz-1", now=NOV) is None
    assert sb.posts == []


def test_no_heads_up_off_a_church_plan(monkeypatch):
    sb = _Sb(count=99999, plan="price_pro").install(monkeypatch)
    assert ct.check_allowance("biz-1", now=NOV) is None
    assert sb.posts == []


def test_heads_up_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    assert ct.check_allowance("biz-1", now=NOV) is None


def test_the_wording_never_says_a_text_stops():
    for level in (80, 100):
        title, body = ct.notice(level, 1500, 1500, ct.month_start(NOV))
        text = (title + " " + body).lower()
        for word in ("paused", "blocked", "stopped", "won't send", "can't send"):
            assert word not in text


# ─── The settings record: claimed once ───────────────────────────────

class _Settings:
    def __init__(self, settings):
        self.settings = settings
        self.patches = []
        self.patch_result = True

    def get(self, path):
        return [{"id": "biz-1", "settings": dict(self.settings)}]

    def patch(self, path, body):
        self.patches.append((path, body))
        return [body] if self.patch_result else []


def test_record_write_keeps_other_settings_and_filters_on_nothing(monkeypatch):
    s = _Settings({"theme": "dark"})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", s.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", s.patch)
    assert ct._write_record("biz-1", None, None, {"month": "2026-10", "state": "billing"})
    path, body = s.patches[0]
    assert "settings->church_texts_bill=is.null" in path
    assert body["settings"]["theme"] == "dark"
    assert body["settings"]["church_texts_bill"] == {"month": "2026-10", "state": "billing"}


def test_record_write_filters_on_the_month_and_state_it_read(monkeypatch):
    s = _Settings({"church_texts_bill": {"month": "2026-09", "state": "billed"}})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", s.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", s.patch)
    assert ct._write_record("biz-1", "2026-09", "billed", {"month": "2026-10", "state": "billing"})
    path = s.patches[0][0]
    assert "settings->church_texts_bill->>month=eq.2026-09" in path
    assert "settings->church_texts_bill->>state=eq.billed" in path


def test_record_write_refuses_when_someone_else_moved_it(monkeypatch):
    s = _Settings({"church_texts_bill": {"month": "2026-10", "state": "billing"}})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", s.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", s.patch)
    assert ct._write_record("biz-1", "2026-09", "billed", {"month": "2026-10", "state": "billing"}) is False
    assert s.patches == []


def test_record_write_reports_a_lost_race(monkeypatch):
    s = _Settings({})
    s.patch_result = False
    monkeypatch.setattr(sb_clients, "sb_get_as_service", s.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", s.patch)
    assert ct._write_record("biz-1", None, None, {"month": "2026-10", "state": "billing"}) is False


# ─── The bill ────────────────────────────────────────────────────────

class _Bill:
    """bill_month's world: the count, the record writes, and Stripe."""

    def __init__(self, monkeypatch, count=1600, claim_ok=True, existing=None, messages=800):
        self.count, self.claim_ok, self.existing, self.messages = count, claim_ok, existing, messages
        self.writes, self.stripe = [], []
        monkeypatch.setattr(ct, "counted", lambda bid, start, end=None: (
            None if self.count is None else (self.messages, self.count)))
        monkeypatch.setattr(ct, "_write_record", self.write)
        monkeypatch.setattr(ct, "_stripe", self.call)

    def write(self, bid, expect_month, expect_state, rec):
        self.writes.append((expect_month, expect_state, rec))
        return self.claim_ok if rec.get("state") != "billed" else True

    async def call(self, method, path, form=None, idempotency_key=None):
        self.stripe.append((method, path, form, idempotency_key))
        if method == "GET":
            return {"data": self.existing or []}
        return {"id": "ii_new"}


def _run(coro):
    return asyncio.run(coro)


def test_bills_last_month_once_on_the_subscription(monkeypatch):
    w = _Bill(monkeypatch, count=1600)
    out = _run(ct.bill_month(_row(), now=NOV))
    assert out["state"] == "billed" and out["invoice_item"] == "ii_new"
    assert out["month"] == "2026-10" and out["extra"] == 100 and out["cents"] == 200
    # Claimed first (filtered on the empty record), then billed.
    assert w.writes[0][:2] == (None, None) and w.writes[0][2]["state"] == "billing"
    assert w.writes[-1][:2] == ("2026-10", "billing") and w.writes[-1][2]["state"] == "billed"
    assert w.writes[-1][2]["invoice_item"] == "ii_new"
    # One Stripe call: the invoice item, no look-up on a fresh claim.
    assert len(w.stripe) == 1
    method, path, form, key = w.stripe[0]
    assert (method, path) == ("POST", "/invoiceitems")
    assert form["customer"] == "cus_1" and form["subscription"] == "sub_1"
    assert form["amount"] == 200 and form["currency"] == "usd"
    assert form["metadata"]["kind"] == "church_texts" and form["metadata"]["month"] == "2026-10"
    assert form["metadata"]["texts"] == 1600 and form["metadata"]["messages"] == 800
    assert form["metadata"]["unit"] == "160-character part"
    assert form["description"] == ("Extra texts, October 2026: 100 past the plan's 1,500 ($20 per 1,000). "
                                   "Counted by 160-character part: 800 messages went out as 1,600 texts.")
    assert key == "church-texts-biz-1-2026-10"
    # The record keeps both numbers.
    assert w.writes[-1][2]["texts"] == 1600 and w.writes[-1][2]["messages"] == 800


def test_the_bill_counts_parts_not_messages(monkeypatch):
    # 600 messages are well under Growing's 1,500; as 3-part messages they
    # are 1,800 texts, 300 over.
    w = _Bill(monkeypatch, count=1800, messages=600)
    out = _run(ct.bill_month(_row(), now=NOV))
    assert out["state"] == "billed" and out["extra"] == 300 and out["cents"] == 600
    assert w.stripe[0][2]["amount"] == 600


def test_a_billed_month_is_never_billed_again(monkeypatch):
    w = _Bill(monkeypatch)
    row = _row(settings={"church_texts_bill": {"month": "2026-10", "state": "billed"}})
    assert _run(ct.bill_month(row, now=NOV))["why"] == "done"
    assert w.stripe == [] and w.writes == []


def test_under_the_plan_records_nothing_to_bill(monkeypatch):
    w = _Bill(monkeypatch, count=900)
    out = _run(ct.bill_month(_row(), now=NOV))
    assert out["state"] == "none" and out["cents"] == 0
    assert w.stripe == []
    assert w.writes[0][2]["state"] == "none"


def test_a_few_texts_over_stays_under_the_minimum(monkeypatch):
    w = _Bill(monkeypatch, count=1520)      # 20 over = 40 cents, under $1
    assert _run(ct.bill_month(_row(), now=NOV))["state"] == "none"
    assert w.stripe == []


def test_the_minimum_is_a_dial(monkeypatch):
    monkeypatch.setenv("CHURCH_TEXT_BILL_MIN_CENTS", "0")
    w = _Bill(monkeypatch, count=1520)
    assert _run(ct.bill_month(_row(), now=NOV))["state"] == "billed"
    assert w.stripe[0][2]["amount"] == 40


def test_an_unread_count_never_bills(monkeypatch):
    w = _Bill(monkeypatch, count=None)
    out = _run(ct.bill_month(_row(), now=NOV))
    assert out == {"state": "skipped", "why": "count_unread", "month": "2026-10"}
    assert w.stripe == [] and w.writes == []


def test_a_lost_claim_never_bills(monkeypatch):
    w = _Bill(monkeypatch, claim_ok=False)
    assert _run(ct.bill_month(_row(), now=NOV))["why"] == "claimed"
    assert w.stripe == []


def test_a_crashed_run_finds_the_item_it_made(monkeypatch):
    w = _Bill(monkeypatch, existing=[{"id": "ii_old", "metadata": {
        "kind": "church_texts", "month": "2026-10", "business_id": "biz-1"}}])
    row = _row(settings={"church_texts_bill": {"month": "2026-10", "state": "billing",
                                               "texts": 1600, "included": 1500, "extra": 100, "cents": 200}})
    out = _run(ct.bill_month(row, now=NOV))
    assert out["state"] == "billed" and out["invoice_item"] == "ii_old"
    assert [c[:2] for c in w.stripe] == [("GET", "/invoiceitems")]
    # The look covers items an invoice already took, not only pending ones.
    form = w.stripe[0][2]
    assert "pending" not in form and form["created"]["gte"] == int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())
    assert w.writes == [("2026-10", "billing", {**w.writes[0][2]})]
    assert w.writes[0][2]["state"] == "billed"


def test_a_crashed_run_with_no_item_makes_it(monkeypatch):
    w = _Bill(monkeypatch, existing=[{"id": "ii_x", "metadata": {"kind": "church_texts", "month": "2026-09",
                                                                  "business_id": "biz-1"}}])
    row = _row(settings={"church_texts_bill": {"month": "2026-10", "state": "billing", "messages": 700,
                                               "texts": 1600, "included": 1500, "extra": 100, "cents": 200}})
    out = _run(ct.bill_month(row, now=NOV))
    assert out["invoice_item"] == "ii_new"
    assert [c[:2] for c in w.stripe] == [("GET", "/invoiceitems"), ("POST", "/invoiceitems")]
    assert w.stripe[1][2]["amount"] == 200
    # The claim's numbers, not a fresh count's.
    assert "700 messages went out as 1,600 texts" in w.stripe[1][2]["description"]


def test_a_claim_from_before_parts_doesnt_claim_the_unit(monkeypatch):
    # A claim recorded without messages was counted by message: its line says
    # what it was billed for and no more.
    w = _Bill(monkeypatch, messages=900)
    row = _row(settings={"church_texts_bill": {"month": "2026-10", "state": "billing",
                                               "texts": 1600, "included": 1500, "extra": 100, "cents": 200}})
    _run(ct.bill_month(row, now=NOV))
    form = w.stripe[1][2]
    assert form["description"] == "Extra texts, October 2026: 100 past the plan's 1,500 ($20 per 1,000)."
    assert form["metadata"]["messages"] is None and form["metadata"]["unit"] is None


def test_a_price_that_isnt_whole_dollars_reads_right(monkeypatch):
    monkeypatch.setenv("PRICE_EXTRA_TEXTS_CENTS_PER_THOUSAND", "1250")
    line = ct.item_description(ct.previous_month_start(NOV),
                               {"extra": 10, "included": 500, "texts": 510, "messages": 300})
    assert "($12.50 per 1,000)" in line


@pytest.mark.parametrize("kw,why", [
    ({"subscription_plan": "price_pro"}, "not_church_plan"),
    ({"subscription_plan": "church_growing"}, "not_church_plan"),
    ({"comp_tier": "church_growing"}, "comped"),
    ({"comp_tier": "professional"}, "comped"),
    ({"subscription_status": "trialing"}, "not_active"),
    ({"subscription_status": "canceled"}, "not_active"),
    ({"stripe_subscription_id": None}, "no_subscription"),
    ({"stripe_customer_id": ""}, "no_subscription"),
])
def test_who_is_never_billed(monkeypatch, kw, why):
    w = _Bill(monkeypatch)
    assert _run(ct.bill_month(_row(**kw), now=NOV))["why"] == why
    assert w.stripe == [] and w.writes == []


def test_past_due_is_still_billed(monkeypatch):
    w = _Bill(monkeypatch)
    assert _run(ct.bill_month(_row(subscription_status="past_due"), now=NOV))["state"] == "billed"


# ─── The daily tick ──────────────────────────────────────────────────

def _tick_world(monkeypatch, rows, bill=None):
    calls = {"bill": [], "check": []}
    monkeypatch.setattr(ct, "_church_rows", lambda: rows)

    async def fake_bill(row, now=None):
        calls["bill"].append(row["id"])
        if bill:
            return await bill(row)
        return {"state": "billed"}

    monkeypatch.setattr(ct, "bill_month", fake_bill)
    monkeypatch.setattr(ct, "check_allowance", lambda bid, plan=None, now=None: calls["check"].append(bid) or None)
    return calls


def test_tick_bills_and_checks_every_church(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    calls = _tick_world(monkeypatch, [_row(id="a"), _row(id="b")])
    out = _run(ct.bill_tick(now=NOV))
    assert calls["bill"] == ["a", "b"] and calls["check"] == ["a", "b"]
    assert out["billed"] == 2 and out["errors"] == 0


def test_one_church_failing_doesnt_stop_the_rest(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")

    async def bill(row):
        if row["id"] == "a":
            raise RuntimeError("stripe down")
        return {"state": "billed"}

    calls = _tick_world(monkeypatch, [_row(id="a"), _row(id="b")], bill)
    out = _run(ct.bill_tick(now=NOV))
    assert calls["bill"] == ["a", "b"] and out["errors"] == 1 and out["billed"] == 1
    assert calls["check"] == ["a", "b"]


def test_billing_off_still_sends_the_heads_up(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("CHURCH_TEXT_BILLING", "off")
    calls = _tick_world(monkeypatch, [_row(id="a")])
    _run(ct.bill_tick(now=NOV))
    assert calls["bill"] == [] and calls["check"] == ["a"]


def test_no_stripe_key_bills_nothing(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    calls = _tick_world(monkeypatch, [_row(id="a")])
    _run(ct.bill_tick(now=NOV))
    assert calls["bill"] == []


def test_an_unread_church_list_does_nothing(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    calls = _tick_world(monkeypatch, None)
    out = _run(ct.bill_tick(now=NOV))
    assert out["errors"] == 1 and calls["bill"] == [] and calls["check"] == []


# ─── Wiring: never before a send, always on the clock ────────────────

def _src(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_announce_checks_the_count_only_after_sending():
    src = _src("sms_routing.py")
    body = src[src.index("async def announce("):src.index("async def run_scheduled_announcement(")]
    assert "church_texts.check_allowance" in body
    assert body.index("_send_platform_sms(") < body.index("church_texts.check_allowance")


def test_nothing_that_sends_a_text_reads_the_allowance_first():
    for name in ("twilio_sms.py", "sms_service.py", "kids_checkin.py", "member_portal.py"):
        assert "church_texts" not in _src(name), name


def test_the_tick_is_scheduled_on_the_leader():
    assert 'g("church_texts", _church_texts.bill_tick)' in _src("kmj_intake_automation.py")


def test_billing_usage_and_the_composer_show_the_texts():
    assert "church_texts.church_plan_of(biz_row)" in _src("stripe_billing.py")
    assert "church_texts.church_plan_of(plan_rows[0])" in _src("sms_routing.py")
    assert '"texts": texts' in _src("sms_routing.py")


def test_the_tick_hands_the_heads_up_the_plan_not_the_price(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    seen = []
    monkeypatch.setattr(ct, "_church_rows", lambda: [
        _row(id="paid"), _row(id="comped", comp_tier="church_small", stripe_subscription_id=None),
        _row(id="other", subscription_plan="price_pro")])

    async def fake_bill(row, now=None):
        return {"state": "skipped"}

    monkeypatch.setattr(ct, "bill_month", fake_bill)
    monkeypatch.setattr(ct, "check_allowance", lambda bid, plan=None, now=None: seen.append((bid, plan)) or None)
    _run(ct.bill_tick(now=NOV))
    assert seen == [("paid", "church_growing"), ("comped", "church_small")]


def test_a_church_paying_by_price_is_billed(monkeypatch):
    # The regression: the stored value is "price_growing", and it must bill.
    w = _Bill(monkeypatch, count=1600)
    out = _run(ct.bill_month(_row(subscription_plan="price_growing_yr"), now=NOV))
    assert out["state"] == "billed" and out["included"] == 1500

"""What came in, for a day or a span (chief_giving_summary.py), and the
revenue lookup that used to answer "navigating".

Kevin, 2026-11-22: a new church's treasurer asked Chief what the giving was
that day and Chief couldn't find it.

Pins:
  * a day, the last seven days, a month or any from/to, on the church's
    clock, with the same number of days before it
  * the numbers are the Giving page's (giving_week's readers): paid gifts
    less refunds, a gift refunded in full not counted, by fund and by way
  * it works with no services set up for giving (it never asks for one)
  * counts and totals only: never a giver's name or id
  * only the people who may see giving, and only inside a signed-in turn;
    anyone else is refused before a gift is read
  * a failed read is a failure said plainly, never zero; "nothing recorded"
    is said only when the read came back whole
  * a long span comes back whole (no day-by-day, no days before, funds
    capped): never the tool loop's "incomplete sample"
  * how it was given is behind the Giving keeper's key; the rest isn't
  * show_revenue returns figures inside a signed-in turn, in one plain line
    a person can read, refunds taken out, on the business's own clock; with
    nobody signed in it is the screen's action as before
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import action_registry  # noqa: E402
import chief_areas  # noqa: E402
import chief_giving_summary as cgs  # noqa: E402
import chief_of_staff as chief  # noqa: E402
import chief_tool_loop as ctl  # noqa: E402
import giving_records  # noqa: E402
import giving_week as gw  # noqa: E402
import sb_clients  # noqa: E402
from test_church_keys import BIZ, ID, db  # noqa: E402,F401
from test_giving_week import CHICAGO, NOW, WEEK  # noqa: E402

CHURCH = {"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"], "settings": {}}
TODAY = date(2026, 11, 15)          # a Sunday in Chicago (test_giving_week.NOW)


@pytest.fixture
def church(db, monkeypatch):
    db.t["invoices"] = [dict(g) for g in WEEK]
    db.t["business_collaborators"] = []
    monkeypatch.setattr(gw, "_zone", lambda biz: CHICAGO)
    monkeypatch.setattr(gw, "_now", lambda: NOW)
    return db


@pytest.fixture
def as_(monkeypatch):
    """Put a person in the turn (chief_of_staff._TURN_USER_ID)."""
    tokens = []

    def who(name):
        tokens.append(chief._TURN_USER_ID.set(ID[name] if name else ""))
    yield who
    for t in reversed(tokens):
        chief._TURN_USER_ID.reset(t)


def _ask(**action):
    return cgs.summary_sync(CHURCH, action)


# ─── The days ─────────────────────────────────────────────────────────

def test_today_is_the_default_and_is_the_churchs_own_day(church, as_):
    as_("treasurer")                                    # an Admin seat: the treasurer who asked
    got = _ask()
    assert not got.get("failed"), got
    assert got["range"] == {"from": "2026-11-15", "to": "2026-11-15"}
    assert (got["total_cents"], got["gifts"], got["givers"]) == (25000 + 4000, 2, 1)
    assert got["funds"] == [{"fund": "General", "total_cents": 25000, "gifts": 1},
                            {"fund": "Building", "total_cents": 4000, "gifts": 1}]
    assert "$290.00 in 2 gifts from 1 giver on file" in got["result"]
    assert "Sun Nov 15, 2026 (today)" in got["result"]
    # Saturday had a gift refunded in full, an unpaid one and a bill: none is a gift.
    assert got["before"]["gifts"] == 0 and "The day before (Sat Nov 14): nothing recorded." in got["result"]
    assert got["label"] == "$290.00 in 2 gifts"


def test_the_last_seven_days_with_the_seven_before_and_each_day(church, as_):
    as_("owner")
    got = _ask(period="last_7_days")
    assert got["range"] == {"from": "2026-11-09", "to": "2026-11-15"}
    assert (got["total_cents"], got["gifts"], got["givers"], got["no_giver_cents"]) == (56500, 5, 3, 7500)
    assert got["before"] == {"from": "2026-11-02", "to": "2026-11-08", "total_cents": 32000, "gifts": 2,
                             "givers": 2, "no_giver_cents": 0}
    assert _ask()["days"] == []                                        # one day has no day-by-day
    assert got["days"] == [{"date": "2026-11-09", "total_cents": 10000, "gifts": 1},
                           {"date": "2026-11-12", "total_cents": 10000, "gifts": 1},     # $120 less $20 refunded
                           {"date": "2026-11-13", "total_cents": 7500, "gifts": 1},
                           {"date": "2026-11-15", "total_cents": 29000, "gifts": 2}]
    assert "By day: Mon Nov 9 $100.00 (1); Thu Nov 12 $100.00 (1); Fri Nov 13 $75.00 (1); Sun Nov 15 $290.00 (2)" \
        in got["result"]
    assert "$75.00 of it with no giver on file" in got["result"]
    assert "The 7 days before (Mon Nov 2 to Sun Nov 8): $320.00 in 2 gifts." in got["result"]
    assert _ask(period="this week")["range"] == got["range"]          # the words people use


def test_one_named_day_and_how_it_was_given(church, as_):
    as_("owner")
    got = _ask(**{"from": "2026-11-13"})
    assert got["range"] == {"from": "2026-11-13", "to": "2026-11-13"}
    assert got["ways"] == [{"way": "Cash", "total_cents": 7500, "gifts": 1}]
    assert got["givers"] == 0 and got["total_cents"] == 7500
    assert "By how it was given: Cash $75.00 (1)." in got["result"]


def test_a_month_and_a_span_given_backwards(church, as_):
    as_("owner")
    assert _ask(period="this_month")["range"] == {"from": "2026-11-01", "to": "2026-11-15"}
    assert _ask(period="last_month")["range"] == {"from": "2026-10-01", "to": "2026-10-31"}
    assert _ask(period="this_year")["range"] == {"from": "2026-01-01", "to": "2026-11-15"}
    assert _ask(**{"from": "2026-11-12", "to": "2026-11-09"})["range"] == {"from": "2026-11-09", "to": "2026-11-12"}
    # A span that runs past today stops at today.
    assert _ask(**{"from": "2026-11-14", "to": "2026-12-25"})["range"] == {"from": "2026-11-14", "to": "2026-11-15"}


@pytest.mark.parametrize("action, why", [
    ({"from": "2026-12-25"}, "hasn't come yet"),
    ({"from": "next sunday"}, "YYYY-MM-DD"),
    ({"from": "2024-01-01", "to": "2026-11-15"}, "more than 400 days"),
    ({"period": "fortnight"}, "choose today"),
])
def test_a_span_it_cannot_read_is_said_and_nothing_is_read(church, as_, monkeypatch, action, why):
    as_("owner")
    monkeypatch.setattr(giving_records, "read_gifts", lambda *a, **k: pytest.fail("read gifts"))
    got = _ask(**action)
    assert got["failed"] and why in got["result"], got


def test_the_span_is_pure():
    assert cgs.span({}, TODAY) == (TODAY, TODAY, "")
    assert cgs.span({"period": "yesterday"}, TODAY)[:2] == (date(2026, 11, 14), date(2026, 11, 14))
    assert cgs.span({"date": "2026-11-01"}, TODAY)[:2] == (date(2026, 11, 1), date(2026, 11, 1))
    assert cgs.span({"period": "last_month"}, date(2026, 1, 9))[:2] == (date(2025, 12, 1), date(2025, 12, 31))


# ─── Nothing recorded is not "I can't see it" ─────────────────────────

def test_a_day_with_no_gift_says_so_and_is_not_a_failure(church, as_):
    as_("owner")
    got = _ask(**{"from": "2026-11-10"})
    assert not got.get("failed") and got["gifts"] == 0 and got["label"] == "No gifts recorded"
    assert "No gifts are recorded for Tue Nov 10, 2026." in got["result"]
    assert "still on paper" in got["result"]


def test_a_church_that_never_recorded_a_gift_is_told_that(church, as_):
    as_("owner")
    church.t["invoices"] = []
    got = _ask()
    assert not got.get("failed") and "No gift has ever been recorded for this church" in got["result"]


def test_it_never_asks_for_a_service_to_be_set_up(church, as_, monkeypatch):
    """The treasurer's church had no services under Giving by service: the
    service counts said so and nothing else answered."""
    as_("treasurer")
    import giving_services
    monkeypatch.setattr(giving_services, "list_counts", lambda *a, **k: pytest.fail("asked for the service counts"))
    monkeypatch.setenv("GIVING_SERVICES", "off")
    assert _ask()["total_cents"] == 29000


def test_a_read_that_fails_is_a_failure_never_zero(church, as_, monkeypatch):
    as_("owner")

    def down(*a, **k):
        raise HTTPException(503, "Giving records could not be loaded. Please retry.")
    monkeypatch.setattr(giving_records, "read_gifts", down)
    got = _ask()
    assert got["failed"] and "could not be loaded" in got["result"]
    assert "total_cents" not in got and "$0.00" not in got["result"]


# ─── Who ──────────────────────────────────────────────────────────────

def test_the_owner_and_an_admin_get_it_and_the_same(church, as_):
    as_("owner")
    want = _ask(period="last_7_days")
    for who in ("treasurer", "pastor", "admin"):
        as_(who)
        assert _ask(period="last_7_days") == want


def test_any_other_login_is_refused_before_a_gift_is_read(church, as_, monkeypatch):
    read = []
    real = sb_clients.sb_get_as_service

    def spy(path, **k):
        read.append(path)
        return real(path, **k)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", spy)
    for who in ("member", "stranger"):
        as_(who)
        read.clear()
        got = _ask()
        assert got["failed"] and "Giving records require" in got["result"], got
        assert not any(p.startswith("/invoices") for p in read), read


def test_with_nobody_in_the_turn_nothing_is_read(church, as_, monkeypatch):
    as_(None)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: pytest.fail(f"read {path}"))
    got = _ask()
    assert got["failed"] and "signed-in person" in got["result"]


def test_a_business_that_is_not_a_church_is_pointed_at_its_revenue(church, as_, monkeypatch):
    as_("owner")
    monkeypatch.setattr(giving_records, "read_gifts", lambda *a, **k: pytest.fail("read gifts"))
    got = cgs.summary_sync({**CHURCH, "type": "business coaching"}, {})
    assert got["failed"] and "show_revenue" in got["result"]


def test_never_a_giver(church, as_):
    as_("owner")
    for action in ({}, {"period": "last_7_days"}, {"period": "this_year"}):
        said = str(_ask(**action))
        for word in ("Marcus", "marcus@", "contact_id", "c1", "c2", "GIVE-", "notes"):
            assert word not in said, (action, word)


# ─── Where it sits in Chief ───────────────────────────────────────────

def test_it_is_a_read_only_chief_makes_and_never_an_agents():
    assert chief.ACTION_HANDLERS["giving_summary"] is chief.handle_giving_summary
    assert action_registry.effect("giving_summary") == action_registry.READ
    assert not action_registry.may_expose_to_agent("giving_summary")
    assert "giving_summary" in {t["name"] for t in ctl.read_tool_definitions()}
    assert chief._ACTION_PHRASES["giving_summary"] == "adding up what came in"


def test_it_is_giving_and_money_a_read_and_one_the_giving_tick_runs():
    assert chief_areas.VERBS["giving_summary"] == chief_areas.MONEY
    assert "giving_summary" in chief_areas.MONEY_READS and "giving_summary" in chief_areas.TICK_VERBS
    lane = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}
    assert "Giving & money" in chief_areas.refusal("giving_summary", {}, lane)
    # A login that only Sees giving reads it; the handler's own gate decides the rest.
    sees = {**lane, "money": {"level": "see", "can_work": False, "who_gave": False, "bank": False}}
    assert chief_areas.refusal("giving_summary", {}, sees) is None


def test_the_tool_loop_runs_it_mid_turn_and_keeps_a_lane_out(church, as_):
    as_("treasurer")
    ctl.reset_turn()
    err, text = asyncio.run(ctl.execute_tool_use(None, CHURCH, "giving_summary", {"period": "today"}))
    assert not err and "$290.00 in 2 gifts" in text
    token = chief_areas.TURN.set({"areas": ["people_care"], "role": "manager", "lane": "people_care"})
    try:
        ctl.reset_turn()
        err, text = asyncio.run(ctl.execute_tool_use(None, CHURCH, "giving_summary", {}))
    finally:
        chief_areas.TURN.reset(token)
    assert err and "Giving & money" in text and "$" not in text


# ─── A long span comes back whole ─────────────────────────────────────

def _year_of_gifts(funds=3):
    """A gift every other day from Jan 1 to Nov 15, 2026, across `funds` funds."""
    rows, d, i = [], date(2026, 1, 1), 0
    while d <= TODAY:
        rows.append({"id": f"y{i:04d}", "business_id": BIZ, "is_gift": True, "status": "paid",
                     "paid_at": f"{d.isoformat()}T18:00:00Z", "invoice_number": f"GIVE-y{i}", "total": 25.0,
                     "refund_amount_cents": 0, "gift_fund": f"Fund number {i % funds}", "category": None,
                     "notes": "", "payment_method": "card", "contact_id": f"p{i % 40}",
                     "contacts": {"name": "Marcus Hill", "email": "marcus@example.com"}})
        d, i = d + timedelta(days=2), i + 1
    return rows


def test_a_year_comes_back_whole_never_as_an_incomplete_sample(church, as_):
    as_("treasurer")
    church.t["invoices"] = _year_of_gifts(funds=30)
    ctl.reset_turn()
    err, text = asyncio.run(ctl.execute_tool_use(None, CHURCH, "giving_summary", {"period": "this_year"}))
    assert not err
    assert len(text) < ctl.MAX_RESULT_CHARS, len(text)
    got = json.loads(text)
    assert "truncated" not in got and got["gifts"] == 160 and got["total_cents"] == 160 * 2500
    assert got["days"] == [] and "before" not in got and "By day:" not in got["result"]
    assert len(got["funds"]) == cgs.FUNDS_MAX and got["more_funds"]["funds"] == 18
    assert "and 18 more funds with" in got["result"]
    # What is named and what is counted add up to the whole.
    assert sum(f["total_cents"] for f in got["funds"]) + got["more_funds"]["total_cents"] == got["total_cents"]


def test_a_month_of_gifts_every_other_day_still_fits_with_its_days(church, as_):
    as_("treasurer")
    church.t["invoices"] = _year_of_gifts()
    ctl.reset_turn()
    err, text = asyncio.run(ctl.execute_tool_use(None, CHURCH, "giving_summary",
                                                 {"from": "2026-10-01", "to": "2026-10-31"}))
    got = json.loads(text)
    assert not err and "truncated" not in got and len(got["days"]) >= 15
    assert got["before"]["from"] == "2026-08-31" and got["before"]["to"] == "2026-09-30"


def test_a_long_span_reads_only_its_own_days(church, as_, monkeypatch):
    as_("owner")
    asked = []
    real = giving_records.read_gifts

    def spy(biz, start, end, **k):
        asked.append((start, end))
        return real(biz, start, end, **k)
    monkeypatch.setattr(giving_records, "read_gifts", spy)
    _ask(period="this_year")
    assert asked == [("2026-01-01T06:00:00Z", "2026-11-16T06:00:00Z")]


# ─── The Giving keeper ────────────────────────────────────────────────

def test_how_it_was_given_is_behind_the_keepers_key_and_the_rest_is_not(church, as_):
    """Chief's service counts keep cash, check and online behind the keeper;
    the total, the funds and the days are what an Admin already reads
    without the key (GET /giving/{biz}/week and /amounts)."""
    import church_keys as ck
    from test_church_keys import PEOPLE
    ck.put_keeper(BIZ, PEOPLE["admin"], "giving_money", ID["treasurer"], True)
    as_("pastor")                                       # an Admin who isn't the keeper and holds no key
    got = _ask(period="last_7_days")
    assert not got.get("failed") and got["total_cents"] == 56500 and got["funds"] and got["days"]
    assert "ways" not in got and "By how it was given" not in got["result"]
    assert "behind the Giving keeper's key" in got["result"]
    for word in ("Cash", "Check", "Online", "Card"):
        assert word not in got["result"], word
    as_("treasurer")                                    # the keeper
    kept = _ask(period="last_7_days")
    assert kept["ways"] and "By how it was given" in kept["result"]


def test_a_key_that_cannot_be_read_keeps_that_part_shut(church, as_, monkeypatch):
    as_("owner")
    import church_keys as ck

    def down(*a, **k):
        raise HTTPException(503, "couldn't be read")
    monkeypatch.setattr(ck, "is_open", down)
    got = _ask()
    assert not got.get("failed") and got["total_cents"] == 29000 and "ways" not in got


# ─── show_revenue answers with figures ────────────────────────────────

def test_show_revenue_gives_a_church_its_months_giving(church, as_):
    as_("treasurer")
    got = asyncio.run(chief.handle_show_revenue(None, CHURCH, {"type": "show_revenue"}))
    assert got["nav"] and got["label"]
    assert got["result"] == "Giving this month so far: $5,885.00 in 8 gifts."     # Nov 1 to 15 on the church clock
    assert "Giving for Sun Nov 1 to Sun Nov 15, 2026" in got["figures"]["giving_this_month"]
    assert "giving_summary" in got["figures"]["more"]


def test_show_revenue_says_a_refusal_as_one_and_gives_no_figure(church, as_):
    as_("member")
    got = asyncio.run(chief.handle_show_revenue(None, CHURCH, {"type": "show_revenue"}))
    assert got["result"] == ("Giving couldn't be read for this login: Giving records require owner, admin, or "
                             "accountant access.")
    assert "$" not in str(got) and got["nav"]


def _the_line_is_for_a_person(line):
    """The app prints an action's result under Chief's reply: nothing in it
    is an instruction to the model."""
    for word in ("Quote", "Say ", "say so", "do not", "never", "estimate", "lookup", "giving_summary"):
        assert word not in line, (word, line)


SHOP = {"id": BIZ, "type": "business coaching", "owner_id": ID["owner"], "settings": {}}
NEW_YORK = ZoneInfo("America/New_York")


def _shop(monkeypatch, paid, open_rows=({"total": 120.0},), tz=NEW_YORK):
    import group_gatherings
    asked = []

    async def sb(client, method, path, *a, **k):
        asked.append(path)
        return list(paid) if "status=eq.paid" in path else list(open_rows)
    monkeypatch.setattr(chief, "_sb", sb)
    monkeypatch.setattr(group_gatherings, "zone", lambda biz: tz)
    return asked


def test_show_revenue_gives_a_business_its_paid_and_open_invoices(as_, monkeypatch):
    as_("owner")
    month = datetime.now(timezone.utc).astimezone(NEW_YORK).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last = month - timedelta(days=3)
    # As PostgREST returns them: an offset, not a Z.
    asked = _shop(monkeypatch, [
        {"total": 300.0, "refund_amount_cents": 0, "paid_at": month.astimezone(timezone.utc).isoformat()},   # the month's first second
        {"total": 50.5, "refund_amount_cents": None, "paid_at": (month + timedelta(hours=2)).astimezone(timezone.utc).isoformat()},
        {"total": 1000.0, "refund_amount_cents": 100000, "paid_at": (month + timedelta(hours=3)).isoformat()},  # refunded in full
        {"total": 200.0, "refund_amount_cents": 5000, "paid_at": (month + timedelta(hours=4)).isoformat()},     # $50 back
        {"total": 900.0, "refund_amount_cents": 0, "paid_at": last.isoformat()},
        {"total": 10.0, "refund_amount_cents": 0, "paid_at": (month - timedelta(seconds=1)).isoformat()},       # last month's last second
    ])
    got = asyncio.run(chief.handle_show_revenue(None, SHOP, {"type": "show_revenue"}))
    assert got["result"] == (f"{month:%B} so far: $500.50 from 3 paid invoices. {last:%B}: $910.00 from 2 paid "
                             "invoices. Sent and not yet paid: $120.00 on 1 invoice.")
    _the_line_is_for_a_person(got["result"])
    assert got["figures"]["this_month"] == {"month": f"{month:%B %Y}", "paid": 500.5, "invoices": 3}
    assert got["figures"]["last_month"]["paid"] == 910.0 and got["figures"]["at_least"] is False
    assert "Store orders and event tickets are not in these" in got["figures"]["what_this_counts"]
    assert all("is_gift=is.false" in p for p in asked) and got["nav"]
    assert "+" not in "".join(asked)                    # a + in a query string reaches Postgres as a space


def test_show_revenue_cuts_the_month_on_the_businesss_own_clock(as_, monkeypatch):
    """7:30 PM in Chicago on the last day of a month is already the next
    month in UTC: that evening's payment is this month's, not next month's."""
    as_("owner")
    real_datetime = chief.datetime

    class Frozen(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 12, 1, 1, 30, tzinfo=timezone.utc).astimezone(tz or timezone.utc)
    monkeypatch.setattr(chief, "datetime", Frozen)
    _shop(monkeypatch, [{"total": 700.0, "refund_amount_cents": 0, "paid_at": "2026-12-01T01:00:00+00:00"},
                        {"total": 1000.0, "refund_amount_cents": 0, "paid_at": "2026-11-10T15:00:00+00:00"},
                        {"total": 40.0, "refund_amount_cents": 0, "paid_at": "2026-10-31T23:00:00+00:00"}],
          tz=ZoneInfo("America/Chicago"))
    got = asyncio.run(chief.handle_show_revenue(None, SHOP, {"type": "show_revenue"}))
    assert got["result"].startswith("November so far: $1,700.00 from 2 paid invoices. October: $40.00 from 1 paid "
                                    "invoice.")


def test_show_revenue_that_cannot_read_says_so_and_still_opens_the_screen(as_, monkeypatch):
    as_("owner")
    import group_gatherings

    async def sb(*a, **k):
        return None
    monkeypatch.setattr(chief, "_sb", sb)
    monkeypatch.setattr(group_gatherings, "zone", lambda biz: NEW_YORK)
    got = asyncio.run(chief.handle_show_revenue(None, SHOP, {"type": "show_revenue"}))
    assert got["result"] == "Opening Revenue Analytics. The figures couldn't be read just now."
    assert "$" not in str(got) and got["nav"] and got["figures"]["unread"] is True


def test_with_nobody_signed_in_show_revenue_is_the_screens_action_as_before(church, as_, monkeypatch):
    """An outside agent, a scheduled run, the standing agent: no figure of a
    business's money, and nothing read."""
    as_(None)

    async def sb(*a, **k):
        pytest.fail("read the invoices with nobody signed in")
    monkeypatch.setattr(chief, "_sb", sb)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: pytest.fail(f"read {path}"))
    for biz in (SHOP, CHURCH):
        got = asyncio.run(chief.handle_show_revenue(None, biz, {"type": "show_revenue"}))
        assert got == {"type": "show_revenue", "result": "navigating", "label": got["label"], "nav": got["nav"]}

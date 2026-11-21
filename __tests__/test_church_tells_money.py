"""church_tells_money: the treasurer hears when a count closes and when
someone asks to be paid back."""
import re
from datetime import datetime, timezone
from urllib.parse import unquote

import pytest

import church_tells as ct
import church_tells_money as ctm

NOW = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)
CHURCH = {"id": "biz 1&x", "name": "Grace Church", "owner_id": "owner", "settings": {}}
BIZ = "business_id=eq.biz%201%26x"
MONEY = re.compile(r"\$|\d+\.\d\d|\bcents?\b", re.I)


@pytest.fixture
def db(monkeypatch):
    """Table name -> rows (or None for a failed read); every path is kept."""
    tables = {}
    paths = []

    def get(path):
        paths.append(path)
        table = path.split("?")[0].strip("/")
        return tables.get(table, [])

    monkeypatch.setattr(ct, "rows", lambda p: get(p) or [])
    monkeypatch.setattr(ctm, "_strict", get)
    import church_checks
    monkeypatch.setattr(church_checks, "_church_owner_email", lambda owner: "pastor@grace.org")
    return {"t": tables, "paths": paths}


def _path(db, table):
    return [p for p in db["paths"] if p.startswith(f"/{table}?")]


def _quiet(items):
    for it in items:
        assert not MONEY.search(it.title) and not MONEY.search(it.line), it
        assert len(it.title) <= 80 and len(it.line) <= 160


# ─── A count closed ───────────────────────────────────────────────────

def _counts(db):
    db["t"]["giving_counts"] = [
        {"id": "c1", "name": "Sunday Worship", "service_date": "2026-11-22", "status": "closed",
         "closed_at": "2026-11-22T17:00:00+00:00", "closed_by": "counter-a"},
        {"id": "c2", "name": "Wednesday Bible Study", "service_date": "2026-11-18", "status": "closed",
         "closed_at": "2026-11-19T01:00:00+00:00", "closed_by": "counter-b"},
        {"id": "c3", "name": "Card only", "service_date": "2026-11-20", "status": "closed",
         "closed_at": "2026-11-20T20:00:00+00:00", "closed_by": None},
    ]
    db["t"]["invoices"] = [
        {"id": "g1", "giving_count_id": "c1", "payment_method": "cash", "status": "paid"},
        {"id": "g2", "giving_count_id": "c1", "payment_method": "check", "status": "paid"},
        {"id": "g3", "giving_count_id": "c2", "payment_method": "check", "status": "paid"},
        {"id": "g4", "giving_count_id": "c3", "payment_method": "stripe", "status": "paid"},
    ]
    db["t"]["gift_deposit_items"] = [{"ref": "g3"}]       # Wednesday's is matched already


def test_count_closed_tells_the_deposit_duty(db):
    _counts(db)
    items = ctm.count_closed(CHURCH, NOW)
    assert [i.key for i in items] == ["count:c1"]
    it = items[0]
    assert it.duty == "deposit" and it.actor == "counter-a"
    assert it.title == "Nov 22 count is closed"
    assert it.line == "Sunday Worship, Nov 22: match it to the bank deposit when it lands."
    _quiet(items)


def test_count_closed_paths(db):
    _counts(db)
    ctm.count_closed(CHURCH, NOW)
    (p,) = _path(db, "giving_counts")
    assert BIZ in p and "status=eq.closed" in p
    since = re.search(r"closed_at=gte\.([^&]+)", p).group(1)
    assert unquote(since) == "2026-11-19T18:00:00+00:00"     # three days back
    assert "%3A" in since and '"' not in p                     # quoted, never double-quoted
    (g,) = _path(db, "invoices")
    assert BIZ in g and "is_gift=eq.true" in g and "giving_count_id=in.(c1,c2,c3)" in g
    (m,) = _path(db, "gift_deposit_items")
    assert BIZ in m and "side=eq.gift" in m and "ref=in.(g1,g2,g3)" in m


def test_a_count_partly_matched_is_still_told(db):
    _counts(db)
    db["t"]["gift_deposit_items"] = [{"ref": "g1"}, {"ref": "g3"}]
    assert [i.key for i in ctm.count_closed(CHURCH, NOW)] == ["count:c1"]


def test_a_count_with_no_gifts_is_not_told(db):
    db["t"]["giving_counts"] = [{"id": "c9", "name": "Sunday", "service_date": "2026-11-22", "status": "closed"}]
    assert ctm.count_closed(CHURCH, NOW) == []


def test_counts_read_fails_or_guard_fails(db):
    db["t"]["giving_counts"] = None
    assert ctm.count_closed(CHURCH, NOW) == []
    _counts(db)
    db["t"]["gift_deposit_items"] = None          # can't tell if it's matched: hold it back
    assert ctm.count_closed(CHURCH, NOW) == []
    db["t"]["gift_deposit_items"] = []
    db["t"]["invoices"] = None
    assert ctm.count_closed(CHURCH, NOW) == []


def test_count_without_a_date(db):
    db["t"]["giving_counts"] = [{"id": "c5", "name": "", "service_date": None, "status": "closed"}]
    db["t"]["invoices"] = [{"id": "g5", "giving_count_id": "c5", "payment_method": "cash"}]
    (it,) = ctm.count_closed(CHURCH, NOW)
    assert it.title == "A count is closed" and it.actor is None
    assert it.line == "The service: match it to the bank deposit when it lands."


# ─── A pay-back asked for ─────────────────────────────────────────────

def _requests(db):
    db["t"]["church_check_requests"] = [
        {"id": "r1", "contact_id": "p1", "asker_name": "Grace Holloway", "ministry": "Kids", "source": "app",
         "status": "new", "created_at": "2026-11-21T15:00:00+00:00"},
        {"id": "r2", "contact_id": None, "asker_name": None, "ministry": "Youth", "source": "office",
         "status": "new", "created_by": "office-1", "created_at": "2026-11-21T16:00:00+00:00"},
        {"id": "r3", "contact_id": "p2", "asker_name": None, "ministry": None, "source": "app",
         "status": "new", "created_at": "2026-11-21T17:00:00+00:00"},
        {"id": "r4", "contact_id": "p1", "asker_name": "Grace", "ministry": "Kids", "source": "app",
         "status": "new", "created_at": "2026-11-21T18:00:00+00:00"},
        {"id": "r5", "contact_id": "p1", "asker_name": "Grace", "source": "app", "status": "new",
         "decided_by": "someone", "decided_at": "2026-11-21T19:00:00+00:00"},
    ]
    db["t"]["church_check_approvals"] = [{"request_id": "r4"}]   # the treasurer said yes already
    db["t"]["contacts"] = [{"id": "p1", "name": "Grace Holloway", "email": "grace@x.org"},
                           {"id": "p2", "name": "Naiya  Brooks", "email": "Naiya@Grace.org"}]
    db["t"]["business_users"] = [{"user_id": "naiya-login", "invited_email": "naiya@grace.org"}]


def test_payback_asked_tells_the_pay_duty(db):
    _requests(db)
    items = ctm.payback_asked(CHURCH, NOW)
    by = {i.key: i for i in items}
    assert list(by) == ["payback:r1", "payback:r2", "payback:r3"]       # r4 has a yes, r5 a decision
    assert all(i.duty == "pay" for i in items)
    assert by["payback:r1"].title == "Grace asked to be paid back"
    assert by["payback:r1"].line == "Grace asked to be paid back for Kids. It's waiting for your yes or no."
    assert by["payback:r1"].actor is None                               # a member, not a login
    assert by["payback:r2"].title == "A check request is waiting for you"
    assert by["payback:r2"].actor == "office-1"                         # the office login who filed it
    assert by["payback:r3"].title == "Naiya asked to be paid back"
    assert by["payback:r3"].actor == "naiya-login"                      # a member who is also a login
    _quiet(items)


def test_payback_paths(db):
    _requests(db)
    ctm.payback_asked(CHURCH, NOW)
    (p,) = _path(db, "church_check_requests")
    assert BIZ in p and "status=eq.new" in p and "decided_at=is.null" in p
    assert unquote(re.search(r"created_at=gte\.([^&]+)", p).group(1)) == "2026-11-19T18:00:00+00:00"
    assert "amount" not in p and '"' not in p
    (a,) = _path(db, "church_check_approvals")
    assert BIZ in a and "request_id=in.(r1,r2,r3,r4)" in a
    (c,) = _path(db, "contacts")
    assert BIZ in c and "id=in.(p1,p2)" in c
    (u,) = _path(db, "business_users")
    assert BIZ in u and "status=eq.active" in u


def test_payback_reads_that_fail(db):
    db["t"]["church_check_requests"] = None
    assert ctm.payback_asked(CHURCH, NOW) == []
    _requests(db)
    db["t"]["church_check_approvals"] = None      # can't tell if someone said yes: hold it back
    assert ctm.payback_asked(CHURCH, NOW) == []
    db["t"]["church_check_approvals"] = []
    db["t"]["contacts"] = None                    # names unread: the row's own name, else no name
    items = {i.key: i for i in ctm.payback_asked(CHURCH, NOW)}
    assert items["payback:r1"].title == "Grace asked to be paid back"
    assert items["payback:r3"].title == "A check request is waiting for you"


def test_no_logins_read_when_every_request_is_the_offices(db):
    db["t"]["church_check_requests"] = [{"id": "r9", "source": "office", "status": "new", "created_by": "o"}]
    ctm.payback_asked(CHURCH, NOW)
    assert _path(db, "business_users") == []


def test_finders_are_listed_in_the_sweep():
    assert "church_tells_money:count_closed" in ct.FINDERS
    assert "church_tells_money:payback_asked" in ct.FINDERS
    assert ct._finder("church_tells_money:count_closed") is ctm.count_closed
    assert ct._finder("church_tells_money:payback_asked") is ctm.payback_asked


def test_the_duties_exist():
    import church_duties
    assert "deposit" in church_duties.CATALOG and "pay" in church_duties.CATALOG

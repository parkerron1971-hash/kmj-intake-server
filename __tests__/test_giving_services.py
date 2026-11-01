# __tests__/test_giving_services.py
#
# Giving recorded by service (giving_services, Kevin 2026-11-01): the
# schedule, the counts made when their day comes, online gifts placed in the
# week's collecting service, gifts recorded together on the service's day,
# and moving a gift between open counts.

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

import giving_router
import giving_services as gs
import giving_ways

BIZ = "0b1c2d3e-0000-4000-8000-000000000001"
NY = ZoneInfo("America/New_York")
USER = SimpleNamespace(id="u1")


def _split(s):
    return [p for p in s.split(",") if p != ""]


def _cmp(row, col, op, val):
    v = row.get(col)
    if op == "is":
        return v is None if val == "null" else str(v).lower() == val
    if op == "in":
        return str(v) in set(_split(val.strip("()")))
    if op == "eq":
        return str(v).lower() == val.lower() if isinstance(v, bool) else str(v) == val
    if op == "ilike":                                   # * wildcards, any case
        import fnmatch
        return v is not None and fnmatch.fnmatch(" ".join(str(v).lower().split()), val.lower())
    if v is None:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = float(val)
        return {"gt": v > n, "lt": v < n, "gte": v >= n, "lte": v <= n}[op]
    return {"gt": str(v) > val, "lt": str(v) < val, "gte": str(v) >= val, "lte": str(v) <= val}[op]


class FakeDB:
    def __init__(self, **tables):
        self.t = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.posts = []

    def _parse(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        filters, limit = [], None
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            v = unquote(v)
            if k in ("select", "order", "on_conflict"):
                continue
            if k == "limit":
                limit = int(v)
            else:
                op, _, val = v.partition(".")
                filters.append((k, op, val))
        return table, filters, limit

    def sb_get_as_service(self, path, **_):
        table, filters, limit = self._parse(path)
        rows = [dict(r) for r in self.t.get(table, []) if all(_cmp(r, *f) for f in filters)]
        if table == "invoices":
            for r in rows:
                r.setdefault("contacts", None)
        return rows[:limit] if limit else rows

    def sb_post_as_service(self, path, body, prefer=None, **_):
        table = path.lstrip("/").split("?")[0]
        out = []
        for b in (body if isinstance(body, list) else [body]):
            row = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), **b}
            have = self.t.setdefault(table, [])
            if table == "giving_counts":
                row.setdefault("status", "open")
                row.setdefault("counters", [])
                if any(r["service_id"] == row["service_id"] and r["service_date"] == row["service_date"] for r in have):
                    continue
            have.append(row)
            self.posts.append((table, row))
            out.append(dict(row))
        return out

    def sb_patch_as_service(self, path, body):
        table, filters, _ = self._parse(path)
        out = []
        for r in self.t.get(table, []):
            if all(_cmp(r, *f) for f in filters):
                r.update(body)
                out.append(dict(r))
        return out


def _service(**over):
    s = {"id": str(uuid.uuid4()), "business_id": BIZ, "name": "Sunday Worship", "kind": "weekly",
         "weekday": 6, "on_date": None, "start_time": "11:00:00", "collects_online": True,
         "created_at": "2026-10-01T12:00:00+00:00", "archived_at": None}
    s.update(over)
    return s


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(businesses=[{"id": BIZ, "type": "church", "owner_id": "u1",
                               "settings": {"timezone": "America/New_York"}}],
                  giving_services=[], giving_counts=[], invoices=[], contacts=[])
    monkeypatch.setattr(gs, "sb_clients", fake)
    monkeypatch.setattr(giving_router, "sb_clients", fake)
    monkeypatch.setattr(giving_ways, "switched_on", lambda b: True)
    import giving_records, church_keys, vertical_family
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "owner")
    monkeypatch.setattr(church_keys, "wall", lambda *a, **k: None)
    monkeypatch.setattr(gs.church_keys, "wall", lambda *a, **k: None)
    monkeypatch.setattr(vertical_family, "is_nonprofit_like", lambda t: True)
    return fake


# ─── The schedule (pure) ───────────────────────────────────────────────

def test_a_weekly_service_falls_on_its_day_on_the_churchs_clock():
    occ = gs.occurrences([_service()], NY, date(2026, 10, 26), date(2026, 11, 8))
    assert [o["date"] for o in occ] == [date(2026, 11, 1), date(2026, 11, 8)]
    # 11:00 in New York is 15:00 UTC before the clocks change, 16:00 after.
    assert occ[0]["starts_at"].hour == 16 and occ[0]["starts_at"].tzinfo == timezone.utc


def test_a_one_time_service_and_an_archived_one():
    once = _service(kind="once", weekday=None, on_date="2026-12-24", start_time="19:00", name="Christmas Eve")
    gone = _service(archived_at="2026-10-02T00:00:00+00:00")
    occ = gs.occurrences([once, gone], NY, date(2026, 12, 1), date(2026, 12, 31))
    assert [(o["name"], o["date"]) for o in occ] == [("Christmas Eve", date(2026, 12, 24))]


def test_the_online_window_runs_from_last_sundays_service_to_this_ones():
    sun = datetime(2026, 11, 1, 16, tzinfo=timezone.utc)
    prev = sun - timedelta(days=7)
    lo, hi = gs.online_window(sun, [prev, sun])
    assert lo == prev + gs.GRACE and hi == sun + gs.GRACE
    lo, hi = gs.online_window(sun, [sun])                 # the first one: the week before
    assert hi - lo == timedelta(days=7)


def test_totals_split_cash_checks_online_and_the_rest():
    gifts = [{"total": 20, "payment_method": "cash", "invoice_number": "GIVE-manual-1"},
             {"total": 50, "payment_method": "check", "invoice_number": "GIVE-manual-2"},
             {"total": 100, "payment_method": "stripe", "invoice_number": "GIVE-pi_1", "refund_amount_cents": 1000},
             {"total": 15, "payment_method": "cashapp", "invoice_number": "GIVE-manual-3"}]
    t = gs.totals(gifts)
    assert t == {"cash": 2000, "check": 5000, "online": 9000, "other": 1500, "all": 17500, "gifts": 4}


# ─── The counts ────────────────────────────────────────────────────────

def test_counts_are_made_when_their_day_comes_never_before_the_service_was_added(db, monkeypatch):
    svc = _service(created_at="2026-10-20T12:00:00+00:00")
    db.t["giving_services"] = [svc]
    gs.ensure_counts(db.t["businesses"][0], [svc], NY, date(2026, 11, 1))
    made = sorted(c["service_date"] for c in db.t["giving_counts"])
    assert made == ["2026-10-25", "2026-11-01"]           # not Oct 18 or before
    gs.ensure_counts(db.t["businesses"][0], [svc], NY, date(2026, 11, 1))
    assert len(db.t["giving_counts"]) == 2                 # never twice


def test_online_gifts_land_in_the_weeks_sunday_and_cash_never_does(db):
    svc = _service()
    sun = datetime(2026, 11, 1, 16, tzinfo=timezone.utc)
    count = {"id": "c-nov1", "business_id": BIZ, "service_id": svc["id"], "status": "open", "collects_online": True,
             "starts_at": sun.isoformat(), "service_date": "2026-11-01"}
    db.t["giving_counts"] = [count]
    iso = lambda dt: dt.isoformat()
    db.t["invoices"] = [
        {"id": "on-wed", "business_id": BIZ, "is_gift": True, "giving_count_id": None, "invoice_number": "GIVE-pi_a",
         "payment_method": "stripe", "paid_at": iso(sun - timedelta(days=4))},
        {"id": "on-during", "business_id": BIZ, "is_gift": True, "giving_count_id": None, "invoice_number": "GIVE-pi_b",
         "payment_method": "stripe", "paid_at": iso(sun + timedelta(hours=1))},
        {"id": "on-after", "business_id": BIZ, "is_gift": True, "giving_count_id": None, "invoice_number": "GIVE-pi_c",
         "payment_method": "stripe", "paid_at": iso(sun + timedelta(hours=5))},
        {"id": "last-week", "business_id": BIZ, "is_gift": True, "giving_count_id": None, "invoice_number": "GIVE-pi_d",
         "payment_method": "stripe", "paid_at": iso(sun - timedelta(days=7))},
        {"id": "cash", "business_id": BIZ, "is_gift": True, "giving_count_id": None, "invoice_number": "GIVE-manual-x",
         "payment_method": "cash", "paid_at": iso(sun - timedelta(days=1))},
    ]
    placed = gs.attach_online(db.t["businesses"][0], count, [sun - timedelta(days=7), sun])
    assert placed == 2
    got = {r["id"]: r["giving_count_id"] for r in db.t["invoices"]}
    assert got == {"on-wed": "c-nov1", "on-during": "c-nov1", "on-after": None, "last-week": None, "cash": None}


def test_a_closed_or_non_collecting_count_takes_no_online_gifts(db):
    sun = datetime(2026, 11, 1, 16, tzinfo=timezone.utc)
    for c in ({"status": "closed", "collects_online": True}, {"status": "open", "collects_online": False}):
        count = {"id": "c", "starts_at": sun.isoformat(), **c}
        assert gs.attach_online(db.t["businesses"][0], count, [sun]) == 0


def test_the_list_prepares_todays_service_and_shows_whats_coming(db, monkeypatch):
    db.t["giving_services"] = [_service(), _service(name="Bible Study", weekday=3, start_time="18:00",
                                                    collects_online=False)]
    real = gs.datetime

    class Clock(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 11, 1, 13, 0, tzinfo=timezone.utc).astimezone(tz) if tz else real(2026, 11, 1, 13, 0)
    monkeypatch.setattr(gs, "datetime", Clock)
    out = gs.list_counts(BIZ, USER)
    assert out["today"] == "2026-11-01"
    assert out["counts"][0]["name"] == "Sunday Worship" and out["counts"][0]["date"] == "2026-11-01"
    assert [c["date"] for c in out["coming"]][:2] == ["2026-11-05", "2026-11-08"]


def test_gifts_recorded_together_take_the_services_day(db):
    count = {"id": str(uuid.uuid4()), "business_id": BIZ, "status": "open", "service_date": "2026-11-01",
             "starts_at": "2026-11-01T16:00:00+00:00", "collects_online": True, "name": "Sunday Worship"}
    db.t["giving_counts"] = [count]
    rows = [{"request_id": str(uuid.uuid4()), "amount_cents": 5000, "fund": "Tithes", "method": "check",
             "check_number": "1042"},
            {"request_id": str(uuid.uuid4()), "amount_cents": 1234, "fund": "General", "method": "cash", "loose": True},
            {"request_id": str(uuid.uuid4()), "amount_cents": 0, "fund": "General", "method": "cash"}]
    out = gs.record_gifts(BIZ, count["id"], {"rows": rows}, USER)
    assert out["saved"] == 2 and out["results"][2]["ok"] is False and out["results"][2]["error"]
    saved = [r for r in db.t["invoices"] if r.get("giving_count_id") == count["id"]]
    assert {r["paid_at"][:10] for r in saved} == {"2026-11-01"}
    notes = " ".join(r["notes"] for r in saved)
    assert "Check #1042" in notes and "Loose offering" in notes
    again = gs.record_gifts(BIZ, count["id"], {"rows": rows[:1]}, USER)
    assert again["results"][0]["already"] is True          # never twice


def test_a_closed_count_takes_no_gifts(db):
    count = {"id": str(uuid.uuid4()), "business_id": BIZ, "status": "closed", "service_date": "2026-11-01"}
    db.t["giving_counts"] = [count]
    with pytest.raises(HTTPException) as e:
        gs.record_gifts(BIZ, count["id"], {"rows": [{"amount_cents": 100}]}, USER)
    assert e.value.status_code == 409


def test_a_gift_moves_between_open_counts_only(db):
    a = {"id": str(uuid.uuid4()), "business_id": BIZ, "status": "open"}
    b = {"id": str(uuid.uuid4()), "business_id": BIZ, "status": "open"}
    shut = {"id": str(uuid.uuid4()), "business_id": BIZ, "status": "closed"}
    db.t["giving_counts"] = [a, b, shut]
    gift = {"id": str(uuid.uuid4()), "business_id": BIZ, "is_gift": True, "giving_count_id": a["id"]}
    db.t["invoices"] = [gift]
    assert gs.move_gift(BIZ, gift["id"], {"count_id": b["id"]}, USER)["ok"]
    assert db.t["invoices"][0]["giving_count_id"] == b["id"]
    with pytest.raises(HTTPException) as e:
        gs.move_gift(BIZ, gift["id"], {"count_id": shut["id"]}, USER)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        gs.move_gift(BIZ, gift["id"], {}, USER)
    assert e.value.status_code == 400


# ─── The schedule: endpoints ───────────────────────────────────────────

def test_adding_a_service_checks_it(db):
    out = gs.add_service(BIZ, {"name": "Sunday Worship", "kind": "weekly", "weekday": "Sunday",
                               "time": "11:00", "collects_online": True}, USER)
    assert out["service"]["day"] == "Sunday" and out["service"]["time"] == "11:00"
    for bad in ({"name": "", "kind": "weekly", "weekday": 6, "time": "11:00"},
                {"name": "X", "kind": "weekly", "weekday": 9, "time": "11:00"},
                {"name": "X", "kind": "weekly", "weekday": 6, "time": "25:00"},
                {"name": "X", "kind": "once", "date": "not-a-date", "time": "11:00"},
                {"name": "X", "kind": "monthly", "time": "11:00"}):
        with pytest.raises(HTTPException) as e:
            gs.add_service(BIZ, bad, USER)
        assert e.value.status_code == 400


def test_removing_a_service_keeps_its_counts(db):
    svc = _service()
    db.t["giving_services"] = [svc]
    db.t["giving_counts"] = [{"id": "c1", "business_id": BIZ, "service_id": svc["id"], "status": "closed"}]
    assert gs.remove_service(BIZ, svc["id"], USER)["ok"]
    assert db.t["giving_services"][0]["archived_at"] and db.t["giving_counts"][0]["id"] == "c1"


def test_nothing_answers_where_the_switch_is_off(db, monkeypatch):
    monkeypatch.setattr(giving_ways, "switched_on", lambda b: False)
    with pytest.raises(HTTPException) as e:
        gs.list_counts(BIZ, USER)
    assert e.value.status_code == 404


# ─── Review on #1679 ───────────────────────────────────────────────────

def test_windows_come_from_the_counts_made_not_todays_schedule(db):
    """A removed service's closed count keeps its window: a gift left out of
    it doesn't slide into the next count."""
    sun1 = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)
    sun2 = datetime(2026, 11, 1, 16, tzinfo=timezone.utc)
    wed = datetime(2026, 10, 28, 23, tzinfo=timezone.utc)      # a midweek service, since removed
    db.t["giving_counts"] = [
        {"id": "c-sun1", "business_id": BIZ, "collects_online": True, "status": "closed", "starts_at": sun1.isoformat()},
        {"id": "c-wed", "business_id": BIZ, "collects_online": True, "status": "closed", "starts_at": wed.isoformat()},
        {"id": "c-sun2", "business_id": BIZ, "collects_online": True, "status": "open", "starts_at": sun2.isoformat(),
         "service_date": "2026-11-01"},
    ]
    db.t["invoices"] = [
        {"id": "left-out", "business_id": BIZ, "is_gift": True, "giving_count_id": None, "invoice_number": "GIVE-pi_x",
         "payment_method": "stripe", "paid_at": (sun1 + timedelta(days=2)).isoformat()},   # in Wednesday's window
        {"id": "this-week", "business_id": BIZ, "is_gift": True, "giving_count_id": None, "invoice_number": "GIVE-pi_y",
         "payment_method": "stripe", "paid_at": (sun2 - timedelta(days=1)).isoformat()},
    ]
    starts = gs._collecting_starts(BIZ)
    assert gs.attach_online(db.t["businesses"][0], db.t["giving_counts"][2], starts) == 1
    got = {r["id"]: r["giving_count_id"] for r in db.t["invoices"]}
    assert got == {"left-out": None, "this-week": "c-sun2"}


def test_a_moved_service_makes_no_counts_for_the_weeks_before_the_change(db):
    svc = _service(created_at="2026-09-01T12:00:00+00:00", updated_at="2026-10-28T12:00:00+00:00")
    gs.ensure_counts(db.t["businesses"][0], [svc], NY, date(2026, 11, 1))
    assert [c["service_date"] for c in db.t["giving_counts"]] == ["2026-11-01"]


def test_a_church_ahead_of_utc_records_sunday_on_sunday_morning(db, monkeypatch):
    db.t["businesses"][0]["settings"] = {"timezone": "Pacific/Guam"}
    count = {"id": str(uuid.uuid4()), "business_id": BIZ, "status": "open", "service_date": "2026-11-01",
             "starts_at": "2026-10-31T23:00:00+00:00", "collects_online": False, "name": "Sunday Worship"}
    db.t["giving_counts"] = [count]
    real = gs.datetime

    class Clock(real):                       # Sunday 9 AM in Guam is still Saturday in UTC
        @classmethod
        def now(cls, tz=None):
            at = real(2026, 10, 31, 23, 0, tzinfo=timezone.utc)
            return at.astimezone(tz) if tz else at.replace(tzinfo=None)
    monkeypatch.setattr(gs, "datetime", Clock)
    import giving_router as gr
    monkeypatch.setattr(gr, "datetime", Clock)
    out = gs.record_gifts(BIZ, count["id"], {"rows": [{"request_id": str(uuid.uuid4()), "amount_cents": 2000,
                                                       "fund": "General", "method": "cash"}]}, USER)
    assert out["saved"] == 1, out


def test_someone_without_giving_access_is_refused(db, monkeypatch):
    import giving_records

    def refuse(b, u):
        raise HTTPException(403, "Giving records require owner, admin, or accountant access.")
    monkeypatch.setattr(giving_records, "require_finance", refuse)
    for call in (lambda: gs.list_counts(BIZ, USER), lambda: gs.list_services(BIZ, USER),
                 lambda: gs.record_gifts(BIZ, str(uuid.uuid4()), {"rows": [{}]}, USER)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 403


def test_another_churchs_count_and_gift_are_not_found(db):
    other = "0b1c2d3e-0000-4000-8000-000000000002"
    theirs = {"id": str(uuid.uuid4()), "business_id": other, "status": "open", "service_date": "2026-11-01"}
    gift = {"id": str(uuid.uuid4()), "business_id": other, "is_gift": True, "giving_count_id": theirs["id"]}
    mine = {"id": str(uuid.uuid4()), "business_id": BIZ, "status": "open"}
    db.t["giving_counts"] = [theirs, mine]
    db.t["invoices"] = [gift]
    for call in (lambda: gs.get_count(BIZ, theirs["id"], USER),
                 lambda: gs.record_gifts(BIZ, theirs["id"], {"rows": [{"amount_cents": 100}]}, USER),
                 lambda: gs.move_gift(BIZ, gift["id"], {"count_id": mine["id"]}, USER)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404


def test_a_failed_read_is_never_shown_as_nothing(db, monkeypatch):
    db.t["giving_services"] = [_service()]
    real_get = db.sb_get_as_service

    def down(table):
        def get(path, **k):
            return None if path.startswith(f"/{table}?") else real_get(path, **k)
        return get
    monkeypatch.setattr(db, "sb_get_as_service", down("giving_counts"))
    with pytest.raises(HTTPException) as e:
        gs.list_counts(BIZ, USER)
    assert e.value.status_code == 503
    monkeypatch.setattr(db, "sb_get_as_service", real_get)
    db.t["giving_counts"] = [{"id": "c", "business_id": BIZ, "starts_at": "2026-11-01T16:00:00+00:00"}]
    monkeypatch.setattr(db, "sb_get_as_service", down("invoices"))
    assert gs._unplaced_count(BIZ, db.t["giving_counts"]) is None


# ─── Zelle from the bank ───────────────────────────────────────────────

ZELLE_COUNT = "c0000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(db):
    sun = datetime(2026, 11, 1, 16, tzinfo=timezone.utc)
    db.t["giving_counts"] = [{"id": ZELLE_COUNT, "business_id": BIZ, "status": "open", "collects_online": True,
                              "starts_at": sun.isoformat(), "service_date": "2026-11-01", "name": "Sunday Worship"}]
    db.t["plaid_accounts"] = [{"business_id": BIZ, "account_id": "acc1", "included_in_bookkeeping": True,
                               "deleted_at": None}]
    row = lambda tid, day, amt, name, **k: {"business_id": BIZ, "account_id": "acc1", "transaction_id": tid,
                                            "date": day, "amount": amt, "name": name, "merchant_name": None,
                                            "pending": False, "excluded_from_books": False, "money_kind": None, **k}
    db.t["plaid_transactions"] = [
        row("z1", "2026-10-28", -50.0, "Zelle payment from GRACE HOLLOWAY Conf# 8812"),
        row("z2", "2026-10-29", -25.0, "ZELLE FROM UNKNOWN PERSON"),
        row("z3", "2026-10-30", -40.0, "Zelle from Grace Holloway", money_kind="gifts"),     # already matched
        row("z4", "2026-10-30", -10.0, "ATM deposit"),                                      # not Zelle
        row("z5", "2026-10-20", -30.0, "Zelle from Grace Holloway"),                        # last week
        row("z6", "2026-10-31", -15.0, "Zelle from Grace Holloway"),
    ]
    db.t["gift_deposit_items"] = []
    db.t["contacts"] = [{"id": "a0000000-0000-4000-8000-000000000001", "business_id": BIZ, "name": "Grace Holloway"}]
    return db


def test_the_sender_is_read_from_the_bank_words():
    assert gs.zelle_sender("Zelle payment from GRACE HOLLOWAY Conf# 8812") == "Grace Holloway"
    assert gs.zelle_sender("ZELLE FROM MARCUS T. REED ON 10/29") == "Marcus T. Reed"
    assert gs.zelle_sender("Zelle Transfer 8812") == ""


def test_the_weeks_zelle_money_is_suggested_with_its_giver(bank):
    out = gs.count_bank_suggestions(BIZ, ZELLE_COUNT, USER)["suggestions"]
    assert [s["bank_ref"] for s in out] == ["z1", "z2", "z6"]
    assert out[0]["contact_id"] == "a0000000-0000-4000-8000-000000000001" and out[0]["amount_cents"] == 5000
    assert out[1]["name_match"] == "none" and out[1]["sender"] == "Unknown Person"


def test_a_zelle_gift_is_dated_when_the_money_came_and_never_recorded_twice(bank):
    row = {"request_id": str(uuid.uuid4()), "amount_cents": 5000, "fund": "General", "method": "zelle",
           "contact_id": "a0000000-0000-4000-8000-000000000001", "bank_ref": "z1"}
    out = gs.record_gifts(BIZ, ZELLE_COUNT, {"rows": [row]}, USER)
    assert out["saved"] == 1
    gift = [r for r in bank.t["invoices"] if r.get("giving_count_id") == ZELLE_COUNT][0]
    assert gift["paid_at"].startswith("2026-10-28") and "Bank row z1" in gift["notes"]
    assert [s["bank_ref"] for s in gs.count_bank_suggestions(BIZ, ZELLE_COUNT, USER)["suggestions"]] == ["z2", "z6"]
    again = gs.record_gifts(BIZ, ZELLE_COUNT, {"rows": [{**row, "request_id": str(uuid.uuid4())}]}, USER)
    assert again["saved"] == 0 and "already recorded" in again["results"][0]["error"]


def test_a_zelle_gift_must_be_the_deposits_amount(bank):
    row = {"request_id": str(uuid.uuid4()), "amount_cents": 4000, "fund": "General", "method": "zelle", "bank_ref": "z1"}
    out = gs.record_gifts(BIZ, ZELLE_COUNT, {"rows": [row]}, USER)
    assert out["saved"] == 0 and "$50.00" in out["results"][0]["error"]
    bad = gs.record_gifts(BIZ, ZELLE_COUNT, {"rows": [{**row, "bank_ref": "z4", "amount_cents": 1000}]}, USER)
    assert "isn't Zelle" in bad["results"][0]["error"]


def test_no_suggestions_for_a_closed_or_non_collecting_count(bank):
    bank.t["giving_counts"][0]["status"] = "closed"
    assert gs.count_bank_suggestions(BIZ, ZELLE_COUNT, USER)["suggestions"] == []


# __tests__/test_giving_counts_close.py
#
# Giving by service, step 3: closing a count (the counted cash and checks
# must equal what's recorded, who counted, the lock), reopening with a
# reason, a closed count's gift locked against correction, the Sunday match
# trying a closed count's cash and checks as one slip, and Chief recording
# gifts to a service (all or nothing on names) with an undo.

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import chief_giving_counts as cgc
import giving_deposits
import giving_router
import giving_services as gs
import giving_ways
from __tests__.test_giving_services import BIZ, FakeDB, USER

COUNT = "c0000000-0000-4000-8000-000000000001"


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(businesses=[{"id": BIZ, "type": "church", "owner_id": "u1", "settings": {"timezone": "America/New_York"}}],
                  giving_services=[], invoices=[], contacts=[{"id": "a0000000-0000-4000-8000-000000000001", "business_id": BIZ, "name": "Grace Holloway"},
                                                         {"id": "a0000000-0000-4000-8000-000000000002", "business_id": BIZ, "name": "Marcus Reed"},
                                                         {"id": "a0000000-0000-4000-8000-000000000003", "business_id": BIZ, "name": "Marcus Reed"}],
                  chief_undo_log=[],
                  giving_counts=[{"id": COUNT, "business_id": BIZ, "service_id": None, "name": "Sunday Worship",
                                  "service_date": "2026-11-01", "starts_at": "2026-11-01T16:00:00+00:00",
                                  "collects_online": True, "status": "open", "counters": [], "note": ""}])
    for mod in (gs, giving_router, cgc):
        monkeypatch.setattr(mod, "sb_clients", fake)
    monkeypatch.setattr(giving_ways, "switched_on", lambda b: True)
    import giving_records, church_keys, vertical_family
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "owner")
    monkeypatch.setattr(church_keys, "wall", lambda *a, **k: None)
    monkeypatch.setattr(gs.church_keys, "wall", lambda *a, **k: None)
    monkeypatch.setattr(vertical_family, "is_nonprofit_like", lambda t: True)
    fake.sb_delete_as_service = lambda path: _delete(fake, path)
    return fake


def _delete(fake, path):
    table, filters, _ = fake._parse(path)
    from __tests__.test_giving_services import _cmp
    keep = []
    for r in fake.t.get(table, []):
        ok = all((op == "like" and str(r.get(col, "")).startswith(val.rstrip("*"))) or (op != "like" and _cmp(r, col, op, val))
                 for col, op, val in filters)
        if not ok:
            keep.append(r)
    fake.t[table] = keep
    return True


def _gift(method, cents, **over):
    g = {"id": str(uuid.uuid4()), "business_id": BIZ, "is_gift": True, "giving_count_id": COUNT,
         "invoice_number": f"GIVE-manual-{uuid.uuid4()}", "payment_method": method, "total": cents / 100,
         "paid_at": "2026-11-01T12:00:00Z", "status": "paid"}
    g.update(over)
    return g


# ─── Closing ───────────────────────────────────────────────────────────

def test_a_count_closes_only_when_the_count_matches_whats_recorded(db):
    db.t["invoices"] = [_gift("cash", 8350), _gift("check", 15000),
                        _gift("stripe", 10000, invoice_number="GIVE-pi_1")]      # online isn't counted cash
    with pytest.raises(HTTPException) as e:
        gs.close_count(BIZ, COUNT, {"counted_cash_cents": 8400, "counted_checks_cents": 15000,
                                    "counters": ["Ann Lee", "Bo Price"]}, USER)
    assert e.value.status_code == 409 and e.value.detail["cash_difference_cents"] == 50
    assert "cash is $0.50 more than recorded" in e.value.detail["message"]
    out = gs.close_count(BIZ, COUNT, {"counted_cash_cents": 8350, "counted_checks_cents": 15000,
                                      "counters": ["Ann Lee", "Bo Price", "ann lee"]}, USER)
    c = db.t["giving_counts"][0]
    assert out["ok"] and c["status"] == "closed" and c["counters"] == ["Ann Lee", "Bo Price"]
    assert c["counted_cash_cents"] == 8350 and "Closed" in c["note"]


@pytest.mark.parametrize("body", [
    {"counted_cash_cents": -1, "counted_checks_cents": 0, "counters": ["A"]},
    {"counted_cash_cents": "10", "counted_checks_cents": 0, "counters": ["A"]},
    {"counted_cash_cents": 0, "counted_checks_cents": 0, "counters": []},
    {"counted_cash_cents": 0, "counted_checks_cents": 0, "counters": ["A", "B", "C", "D", "E"]},
])
def test_close_needs_the_counted_totals_and_who_counted(db, body):
    with pytest.raises(HTTPException) as e:
        gs.close_count(BIZ, COUNT, body, USER)
    assert e.value.status_code == 400


def test_a_closed_count_is_locked_and_reopens_only_with_a_reason(db, monkeypatch):
    gift = _gift("cash", 2000)
    db.t["invoices"] = [gift]
    gs.close_count(BIZ, COUNT, {"counted_cash_cents": 2000, "counted_checks_cents": 0, "counters": ["Ann"]}, USER)
    with pytest.raises(HTTPException) as e:
        gs.record_gifts(BIZ, COUNT, {"rows": [{"amount_cents": 100}]}, USER)
    assert e.value.status_code == 409
    gift.update(updated_at="2026-11-01T12:00:00Z", notes="")
    with pytest.raises(HTTPException) as e:
        giving_router.correct_manual_gift(BIZ, gift["id"], {"amount_cents": 2500, "received_on": "2026-11-01",
                                                            "method": "cash", "reason": "typo",
                                                            "updated_at": gift["updated_at"]}, USER)
    assert e.value.status_code == 409 and "closed count" in e.value.detail
    with pytest.raises(HTTPException) as e:
        gs.reopen_count(BIZ, COUNT, {"reason": ""}, USER)
    assert e.value.status_code == 400
    import giving_records
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "accountant")
    with pytest.raises(HTTPException) as e:
        gs.reopen_count(BIZ, COUNT, {"reason": "a check was missed"}, USER)
    assert e.value.status_code == 403
    monkeypatch.setattr(giving_records, "require_finance", lambda b, u: "owner")
    assert gs.reopen_count(BIZ, COUNT, {"reason": "a check was missed"}, USER)["ok"]
    c = db.t["giving_counts"][0]
    assert c["status"] == "open" and "Reopened" in c["note"] and "a check was missed" in c["note"]


# ─── The Sunday match ──────────────────────────────────────────────────

def test_a_closed_counts_cash_and_checks_match_one_deposit_as_a_slip():
    gifts = [{"id": "a", "kind": "plate", "date": "2026-11-01", "cents": 8350, "fee": 0, "count": "c1"},
             {"id": "b", "kind": "plate", "date": "2026-11-01", "cents": 15000, "fee": 0, "count": "c1"},
             # An earlier service the same day, deposited on its own.
             {"id": "c", "kind": "plate", "date": "2026-11-01", "cents": 4000, "fee": 0, "count": "c0"}]
    deps = [{"id": "d1", "date": "2026-11-02", "cents": 23350, "channel": "plate"},
            {"id": "d2", "date": "2026-11-02", "cents": 4000, "channel": "plate"}]
    out = giving_deposits.plan(gifts, deps, {"c1": {"name": "Sunday Worship", "date": "2026-11-01"},
                                             "c0": {"name": "Early Service", "date": "2026-11-01"}})
    whys = sorted(p["why"] for p in out)
    assert any(w.startswith("Sunday Worship") and "counted cash and checks" in w for w in whys)
    assert {tuple(p["deposits"]) for p in out} == {("d1",), ("d2",)}
    # Without counts, the day's three gifts are one group, which no single
    # deposit fits on its own: the day grouping still finds both deposits.
    assert giving_deposits.plan(gifts, deps)[0]["deposits"] in (["d1", "d2"], ["d2", "d1"])


# ─── Chief ─────────────────────────────────────────────────────────────

@pytest.fixture
def chief(db, monkeypatch):
    import chief_of_staff
    import period_lock
    monkeypatch.setattr(period_lock, "guard", lambda *a, **k: None)
    token = chief_of_staff._TURN_USER_ID.set("u1")
    yield db
    chief_of_staff._TURN_USER_ID.reset(token)


def test_chief_records_named_gifts_to_the_service_and_undoes_them(chief):
    out = cgc.record_sync(BIZ, {"service": "sunday", "date": "2026-11-01", "gifts": [
        {"name": "Grace Holloway", "amount": 100, "method": "check", "check_number": "1042", "fund": "Tithes"},
        {"name": "loose", "amount": 83.5, "method": "Cash"}]})
    assert not out.get("failed"), out
    assert "Recorded 2 gifts ($183.50) to Sunday Worship" in out["result"] and out["batch_id"]
    saved = [r for r in chief.t["invoices"] if r.get("giving_count_id") == COUNT]
    assert len(saved) == 2 and {r["paid_at"][:10] for r in saved} == {"2026-11-01"}
    back = cgc.undo_sync(BIZ, {"batch_id": out["batch_id"]})
    assert "Took back 2 gifts" in back["result"]
    assert not [r for r in chief.t["invoices"] if r.get("giving_count_id") == COUNT]


def test_chief_records_nothing_when_a_name_isnt_one_person(chief):
    out = cgc.record_sync(BIZ, {"gifts": [{"name": "Grace Holloway", "amount": 50},
                                          {"name": "Marcus Reed", "amount": 20},
                                          {"name": "Nobody Known", "amount": 5}]})
    assert out["failed"] and "nothing was recorded" in out["result"]
    assert "Nobody Known" in out["result"] and "Marcus Reed" in out["result"]
    assert not chief.t["invoices"]


def test_chief_never_records_into_a_closed_count(chief):
    chief.t["giving_counts"][0]["status"] = "closed"
    out = cgc.record_sync(BIZ, {"date": "2026-11-01", "gifts": [{"name": "loose", "amount": 5}]})
    assert out["failed"] and "closed" in out["result"]


def test_chief_says_where_its_switched_off(chief, monkeypatch):
    monkeypatch.setattr(giving_ways, "switched_on", lambda b: False)
    out = cgc.counts_sync(BIZ, {})
    assert out["failed"] and "isn't switched on" in out["result"]


# ─── Review on #1680 ───────────────────────────────────────────────────

def test_a_gift_that_lands_while_closing_keeps_the_count_open(db, monkeypatch):
    db.t["invoices"] = [_gift("cash", 2000)]
    real = gs._gifts_of
    calls = {"n": 0}

    def gifts_of(biz, ids):
        calls["n"] += 1
        if calls["n"] == 2:                      # after the close: a gift arrived
            db.t["invoices"].append(_gift("cash", 500))
        return real(biz, ids)
    monkeypatch.setattr(gs, "_gifts_of", gifts_of)
    with pytest.raises(HTTPException) as e:
        gs.close_count(BIZ, COUNT, {"counted_cash_cents": 2000, "counted_checks_cents": 0, "counters": ["Ann"]}, USER)
    assert e.value.status_code == 409 and "stays open" in e.value.detail
    c = db.t["giving_counts"][0]
    assert c["status"] == "open" and "came in while it was closing" in c["note"]


def test_close_says_so_when_it_couldnt_be_saved(db, monkeypatch):
    monkeypatch.setattr(db, "sb_patch_as_service", lambda path, body: None)
    with pytest.raises(HTTPException) as e:
        gs.close_count(BIZ, COUNT, {"counted_cash_cents": 0, "counted_checks_cents": 0, "counters": ["Ann"]}, USER)
    assert e.value.status_code == 503


def test_chief_asks_when_more_than_one_open_service_fits(chief):
    chief.t["giving_counts"].append({**chief.t["giving_counts"][0], "id": "c0000000-0000-4000-8000-000000000002",
                                     "name": "Sunday Evening", "service_id": "s2",
                                     "starts_at": "2026-11-01T23:00:00+00:00"})
    for action in ({"service": "sunday", "date": "2026-11-01"}, {}):
        out = cgc.record_sync(BIZ, {**action, "gifts": [{"name": "loose", "amount": 5}]})
        assert out["failed"] and "Say which" in out["result"]
    assert not chief.t["invoices"]


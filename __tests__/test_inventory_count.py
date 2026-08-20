# __tests__/test_inventory_count.py
#
# SCAN THE SHELF rung two — the count session. Pins the arithmetic a
# practitioner is going to trust with a shrink number, and the two
# behaviours that make the audit trail honest:
#
#   • a line that MATCHED writes no movement (200 counted, 3 wrong must
#     leave 3 rows, not 200) — asserted via build_report's `off`;
#   • an UNTRACKED product counted for the first time is not a variance.
#     Treating "no expectation" as "expected 0" would invent shrink out
#     of thin air on the very first count a business ever runs.

import inventory_count as ic


_SHELF = {
    "a": {"id": "a", "name": "Pomade 4oz",  "current_price": 21.0, "inventory_qty": 12},
    "b": {"id": "b", "name": "Beard Oil",   "current_price": 14.0, "inventory_qty": 3},
    "c": {"id": "c", "name": "Neck Duster", "current_price": 9.0,  "inventory_qty": None},
    "d": {"id": "d", "name": "Comb",        "current_price": 4.0,  "inventory_qty": 20},
}


def _lines(**kw):
    return [{"offering_id": k, "counted_qty": v} for k, v in kw.items()]


# ─── build_report ────────────────────────────────────────────────────


def test_all_matching_is_a_clean_count():
    r = ic.build_report(_SHELF, _lines(a=12, b=3, d=20))
    assert r["counted"] == 3
    assert r["matched"] == 3
    assert r["off"] == 0
    assert r["units_short"] == 0 and r["units_over"] == 0
    assert r["value_short"] == 0
    assert "every one matched" in ic.summary_line(r)


def test_missing_units_are_valued_at_what_they_sell_for():
    # 3 pomade short at $21 = $63.
    r = ic.build_report(_SHELF, _lines(a=9, b=3))
    assert r["off"] == 1
    assert r["units_short"] == 3
    assert r["value_short"] == 63.0
    s = ic.summary_line(r)
    assert "1 of 2 were off" in s and "3 units missing" in s and "$63" in s


def test_found_stock_never_nets_out_real_shrink():
    # 3 pomade missing ($63) and 5 combs extra. If these netted, a
    # mis-scan on the cheap item would hide the expensive loss — which
    # is the exact number the practitioner is counting to find.
    r = ic.build_report(_SHELF, _lines(a=9, d=25))
    assert r["units_short"] == 3
    assert r["units_over"] == 5
    assert r["value_short"] == 63.0
    assert r["off"] == 2


def test_untracked_product_counted_first_time_is_not_a_variance():
    # THE ALARM. If "no expectation" is ever read as "expected 0", the
    # first count a business runs reports phantom shrink on everything
    # it had not been tracking.
    r = ic.build_report(_SHELF, _lines(c=7))
    item = r["items"][0]
    assert item["expected"] is None
    assert item["delta"] is None
    assert item["was_tracked"] is False
    assert r["off"] == 0
    assert r["units_short"] == 0 and r["units_over"] == 0


def test_unknown_offerings_are_dropped_not_guessed():
    r = ic.build_report(_SHELF, [{"offering_id": "zzz", "counted_qty": 4}])
    assert r["counted"] == 0
    assert ic.summary_line(r) == "Nothing was counted."


def test_a_zero_count_is_a_real_count_not_a_skip():
    r = ic.build_report(_SHELF, _lines(b=0))
    assert r["off"] == 1
    assert r["items"][0]["delta"] == -3
    assert r["units_short"] == 3


def test_missing_price_does_not_crash_the_valuation():
    shelf = {"x": {"id": "x", "name": "Freebie", "current_price": None,
                   "inventory_qty": 5}}
    r = ic.build_report(shelf, [{"offering_id": "x", "counted_qty": 2}])
    assert r["units_short"] == 3
    assert r["value_short"] == 0.0


# ─── repeat_misses ───────────────────────────────────────────────────


def test_repeat_miss_counts_only_items_wrong_right_now():
    now = ic.build_report(_SHELF, _lines(a=9, b=3))["items"]
    past = [
        {"items": [{"offering_id": "a", "delta": -2},
                   {"offering_id": "b", "delta": -1}]},
        {"items": [{"offering_id": "a", "delta": -1},
                   {"offering_id": "b", "delta": 0}]},
    ]
    out = ic.repeat_misses(now, past)
    assert out == {"a": 2}          # b matched this time -> not a finding


def test_repeat_miss_is_empty_when_the_count_was_clean():
    now = ic.build_report(_SHELF, _lines(a=12))["items"]
    past = [{"items": [{"offering_id": "a", "delta": -5}]}]
    assert ic.repeat_misses(now, past) == {}


def test_repeat_miss_ignores_zero_deltas_in_history():
    now = ic.build_report(_SHELF, _lines(a=9))["items"]
    past = [{"items": [{"offering_id": "a", "delta": 0}]},
            {"items": []},
            {"items": [{"offering_id": "a"}]}]
    assert ic.repeat_misses(now, past) == {}


def test_repeat_miss_does_not_double_count_one_session():
    now = ic.build_report(_SHELF, _lines(a=9))["items"]
    past = [{"items": [{"offering_id": "a", "delta": -1},
                       {"offering_id": "a", "delta": -2}]}]
    assert ic.repeat_misses(now, past) == {"a": 1}


def test_lookback_is_bounded():
    now = ic.build_report(_SHELF, _lines(a=9))["items"]
    past = [{"items": [{"offering_id": "a", "delta": -1}]}] * 10
    assert ic.repeat_misses(now, past) == {"a": ic._LOOKBACK_SESSIONS}


# ─── route surface ───────────────────────────────────────────────────


def test_route_exists_and_is_authed():
    from auth_supabase import require_user

    paths = {}
    for r in ic.router.routes:
        paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in paths.get("/store/inventory/{business_id}/count", set())
    for r in ic.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


def test_a_count_line_cannot_be_negative():
    import pydantic
    try:
        ic.CountLine(offering_id="a", counted_qty=-1)
    except pydantic.ValidationError:
        return
    raise AssertionError("counted_qty must reject negatives")

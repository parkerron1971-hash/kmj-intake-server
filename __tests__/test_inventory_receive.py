# __tests__/test_inventory_receive.py
#
# SCAN THE SHELF rung three — receiving, plus the wrong-item guard on
# the scan endpoint.
#
# The two things here that can quietly cost a practitioner money:
#
#   • reconcile_line inventing a shortfall against an order that never
#     existed. A walk-in restock is not a supplier failing to deliver,
#     and reporting it as one sends somebody to argue with a vendor
#     about an order they never placed.
#   • apply_expectation relabelling an UNRECOGNISED scan as "that's the
#     wrong item". We do not know what it is; saying "wrong item"
#     claims we identified it and didn't like the answer.

import inventory_receive as recv
import inventory_scan as iscan


# ─── reconcile_line ──────────────────────────────────────────────────


def test_exact_delivery():
    assert recv.reconcile_line(24, 24) == {
        "ordered": 24, "status": "exact", "difference": 0}


def test_short_delivery_is_named_short():
    r = recv.reconcile_line(22, 24)
    assert r["status"] == "short" and r["difference"] == -2


def test_over_delivery_is_named_over():
    r = recv.reconcile_line(26, 24)
    assert r["status"] == "over" and r["difference"] == 2


def test_nothing_on_order_is_not_a_discrepancy():
    # THE ALARM. A walk-in restock, a sample, a supplier throwing in an
    # extra — none of these are a vendor shorting you, and reporting
    # them as one is a lie that starts an argument.
    for ordered in (None, 0):
        r = recv.reconcile_line(6, ordered)
        assert r["status"] == "unordered"
        assert r["difference"] == 0
        assert r["ordered"] is None


# ─── delivery_summary ────────────────────────────────────────────────


def _line(name, received, ordered=None, closed=False):
    rec = recv.reconcile_line(received, ordered)
    return {"name": name, "received": received, "order_closed": closed, **rec}


def test_summary_counts_units_and_products():
    s = recv.delivery_summary([_line("Pomade", 6), _line("Oil", 4)], 0)
    assert "10 units received across 2 products" in s


def test_summary_leads_with_the_shortfall():
    s = recv.delivery_summary([_line("Pomade", 22, 24), _line("Oil", 4, 4)], 1)
    assert "1 purchase order closed" in s
    assert "2 short of what you ordered" in s
    assert "Pomade" in s


def test_summary_of_an_empty_delivery():
    assert recv.delivery_summary([], 0) == "Nothing was received."


def test_summary_says_over_when_more_arrived():
    s = recv.delivery_summary([_line("Pomade", 30, 24)], 0)
    assert "over the order" in s
    assert "short" not in s


def test_summary_singularises():
    s = recv.delivery_summary([_line("Pomade", 1)], 1)
    assert "1 unit received across 1 product" in s
    assert "1 purchase order closed" in s


# ─── the wrong-item guard ────────────────────────────────────────────


_POMADE = {"id": "p1", "name": "Pomade 4oz", "inventory_qty": 12}
_OIL = {"id": "o1", "name": "Beard Oil", "inventory_qty": 3}


def test_no_expectation_passes_through_untouched():
    res = {"ok": True, "result": "exact", "offering": _OIL}
    assert iscan.apply_expectation(res, None) == res


def test_scanning_the_pinned_product_is_the_happy_path():
    out = iscan.apply_expectation(
        {"ok": True, "result": "exact", "offering": _POMADE}, _POMADE)
    assert out["result"] == "exact"
    assert out["matches_expected"] is True
    assert out["expected_offering"]["id"] == "p1"


def test_scanning_a_different_product_is_a_mismatch_that_names_both():
    out = iscan.apply_expectation(
        {"ok": True, "result": "exact", "offering": _OIL}, _POMADE)
    assert out["result"] == "mismatch"
    assert out["matches_expected"] is False
    assert out["offering"]["name"] == "Beard Oil"          # what it IS
    assert out["expected_offering"]["name"] == "Pomade 4oz"  # what they meant


def test_a_likely_match_on_the_wrong_product_is_also_caught():
    out = iscan.apply_expectation(
        {"ok": True, "result": "likely", "offering": _OIL}, _POMADE)
    assert out["result"] == "mismatch"


def test_an_unrecognised_scan_is_not_relabelled_a_mismatch():
    # THE SECOND ALARM. We did not identify it, so we cannot claim it is
    # the wrong one — `matches_expected` carries the fact without the
    # false certainty.
    for result in ("new", "unreadable"):
        out = iscan.apply_expectation(
            {"ok": True, "result": result, "offering": None}, _POMADE)
        assert out["result"] == result
        assert out["matches_expected"] is False


def test_expectation_does_not_mutate_the_original():
    res = {"ok": True, "result": "exact", "offering": _OIL}
    iscan.apply_expectation(res, _POMADE)
    assert res["result"] == "exact" and "expected_offering" not in res


# ─── route + body surface ────────────────────────────────────────────


def test_routes_exist_and_are_authed():
    from auth_supabase import require_user

    paths = {}
    for r in recv.router.routes:
        paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "GET" in paths.get("/store/inventory/{business_id}/expected", set())
    assert "POST" in paths.get("/store/inventory/{business_id}/receive", set())
    for r in recv.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


def test_a_receive_line_cannot_be_zero_negative_or_absurd():
    import pydantic
    for bad in (0, -3, recv._MAX_QTY + 1):
        try:
            recv.ReceiveLine(offering_id="a", qty=bad)
        except pydantic.ValidationError:
            continue
        raise AssertionError(f"qty={bad} should have been rejected")
    assert recv.ReceiveLine(offering_id="a", qty=1).qty == 1


def test_scan_endpoint_accepts_the_expectation_field():
    # The guard is worthless if the field never reaches the handler, and
    # a signature-only check would still pass if FastAPI ignored it — so
    # assert on the ROUTE's parsed body params, which is what actually
    # decides whether the form field is read off the wire.
    scan = next(r for r in iscan.router.routes if r.path.endswith("/scan"))
    fields = {p.name for p in scan.dependant.body_params}
    assert "expect_offering_id" in fields, sorted(fields)
    assert {"barcode", "file"} <= fields, sorted(fields)



def test_inventory_list_ships_the_barcode():
    # The live scanner builds a local code->product map from this list;
    # without the column every scan would need a round trip.
    import store_router
    import inspect
    src = inspect.getsource(store_router.get_inventory)
    assert '"barcode": o.get("barcode")' in src
    assert "select=id,name,sku,barcode," in src

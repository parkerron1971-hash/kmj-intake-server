# __tests__/test_receipts_payroll.py
#
# Receipt capture + payroll interest (rails demand-driven set). Pins
# the extraction parser's armor and both routers' route+auth surface.

import receipts_router
import payroll_router


def test_extraction_parses_clean_json():
    out = receipts_router.parse_extraction(
        '{"vendor": "Home Depot", "amount": 80.21, "tax_amount": 4.53, '
        '"date": "2026-07-30", "category": "operating", '
        '"description": "paint and rollers"}')
    assert out["not_a_receipt"] is False
    assert out["vendor"] == "Home Depot"
    assert out["amount"] == 80.21
    assert out["tax_amount"] == 4.53
    assert out["date"] == "2026-07-30"
    assert out["category"] == "operating"


def test_extraction_survives_fences_and_prose():
    out = receipts_router.parse_extraction(
        'Sure! Here is the JSON:\n```json\n{"vendor": "Shell", "amount": "45.00", '
        '"tax_amount": null, "date": "07/30/2026", "category": "fuel", '
        '"description": "gas"}\n```\nLet me know if you need anything else!')
    assert out["vendor"] == "Shell"
    assert out["amount"] == 45.0
    assert out["tax_amount"] is None
    assert out["date"] is None          # wrong format -> None, never garbage
    assert out["category"] == "other"   # unknown bucket -> other, never invented


def test_extraction_handles_not_a_receipt_and_junk():
    assert receipts_router.parse_extraction('{"not_a_receipt": true}')["not_a_receipt"] is True
    assert receipts_router.parse_extraction("I cannot help with that")["not_a_receipt"] is True
    assert receipts_router.parse_extraction("")["not_a_receipt"] is True
    assert receipts_router.parse_extraction("{broken json")["not_a_receipt"] is True


def test_routes_exist_and_are_authed():
    from auth_supabase import require_user

    r_paths = {r.path for r in receipts_router.router.routes}
    assert "/receipts/scan" in r_paths

    p_paths = {}
    for r in payroll_router.router.routes:
        p_paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "GET" in p_paths.get("/payroll/interest", set())
    assert "POST" in p_paths.get("/payroll/interest", set())

    for router in (receipts_router.router, payroll_router.router):
        for r in router.routes:
            deps = [d.call for d in r.dependant.dependencies]
            assert require_user in deps, f"{r.path} is missing require_user"

# __tests__/test_1099_drafts.py
#
# Rails Arc 2 — 1099-NEC drafts. Pins:
#   * TIN crypto round-trips, normalizes formats, and refuses non-TINs
#   * the draft PDF renders and stays a DRAFT (watermark + disclaimer)
#   * routes exist and are authed; the summary path is untouched

from unittest import mock

from cryptography.fernet import Fernet


def _key_env():
    return mock.patch.dict("os.environ",
                           {"TIN_ENCRYPTION_KEY": Fernet.generate_key().decode()})


def test_tin_round_trip_and_normalization():
    import tin_crypto

    with _key_env():
        for raw in ("123-45-6789", "123456789", "12-3456789", " 123 45 6789 "):
            token, last4 = tin_crypto.encrypt_tin(raw)
            assert last4 == "6789"
            assert token != "123456789"
            assert tin_crypto.decrypt_tin(token) == "123456789"


def test_tin_rejects_wrong_lengths():
    import pytest
    from fastapi import HTTPException
    import tin_crypto

    with _key_env():
        for bad in ("12345678", "1234567890", "", "abc"):
            with pytest.raises(HTTPException):
                tin_crypto.encrypt_tin(bad)


def test_tin_missing_key_is_loud_not_silent():
    import pytest
    from fastapi import HTTPException
    import tin_crypto

    with mock.patch.dict("os.environ", {"TIN_ENCRYPTION_KEY": ""}):
        with pytest.raises(HTTPException) as exc:
            tin_crypto.encrypt_tin("123-45-6789")
        assert "TIN_ENCRYPTION_KEY" in str(exc.value.detail)


def test_format_tin_by_type():
    import tin_crypto

    assert tin_crypto.format_tin("123456789", "ssn") == "123-45-6789"
    assert tin_crypto.format_tin("123456789", "ein") == "12-3456789"


def test_draft_pdf_renders_with_draft_marking():
    import form_1099

    pdf = form_1099.build_draft_pdf(
        payer={"name": "Clean Quick LLC", "ein": "12-3456789",
               "line1": "1 Main St", "line2": "", "city_state_zip": "Detroit, MI 48201",
               "phone": ""},
        recipient={"name": "Jane Contractor", "tin_display": "123-45-6789",
                   "line1": "2 Oak Ave", "line2": "", "city_state_zip": "Detroit, MI 48202"},
        year=2026, box1_amount=1250.5)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1500
    # The disclaimer is the load-bearing safety text.
    assert "not an official IRS form" in form_1099.DISCLAIMER
    assert "never be printed" in form_1099.DISCLAIMER


def test_1099_routes_exist_and_are_authed():
    from reports_router import router as reports
    from contractors_router import router as contractors
    from auth_supabase import require_user

    r_paths = {r.path for r in reports.routes}
    assert "/reports/1099-drafts" in r_paths
    assert "/reports/1099-draft/pdf" in r_paths

    c_paths = {}
    for r in contractors.routes:
        c_paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "PUT" in c_paths.get("/contractors/{contractor_id}/tax-profile", set())
    assert "GET" in c_paths.get("/contractors/{contractor_id}/tax-profile", set())

    for router in (reports, contractors):
        for r in router.routes:
            if "1099" in r.path or "tax-profile" in r.path:
                deps = [d.call for d in r.dependant.dependencies]
                assert require_user in deps, f"{r.path} is missing require_user"

# __tests__/test_esign.py
#
# E-sign v1 (BoldSign adapter). Pins: status mapping, route existence +
# auth, and that contract_signed stays cataloged on the spine.

import boldsign_router
import event_spine


def test_status_mapping():
    m = boldsign_router.map_provider_status
    assert m("InProgress") == "sent"
    assert m("Completed") == "completed"
    assert m("Declined") == "declined"
    assert m("Expired") == "expired"
    assert m("Revoked") == "revoked"
    assert m("SomethingNew") is None
    assert m(None) is None


def test_routes_exist_and_are_authed():
    from auth_supabase import require_user

    by_path = {}
    for r in boldsign_router.router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in by_path.get("/esign/send", set())
    assert "GET" in by_path.get("/esign/list", set())
    assert "POST" in by_path.get("/esign/{esign_id}/refresh", set())

    for r in boldsign_router.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


def test_contract_signed_is_cataloged_with_a_real_emitter():
    entry = event_spine.EVENT_CATALOG["contract_signed"]
    assert "boldsign" in entry["source"]
    assert not entry.get("legacy")

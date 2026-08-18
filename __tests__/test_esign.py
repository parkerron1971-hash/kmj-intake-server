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


# The one route that cannot carry require_user: BoldSign has no login,
# so the provider's callback has to reach us unauthenticated. It is safe
# because it treats its payload as a rumour — it looks the document up in
# our table and asks the provider for the real status before writing
# anything (see test_esign_webhook.py). Naming it here, rather than
# loosening the loop below, keeps the tripwire pointed at every OTHER
# route: adding a second public endpoint fails this test.
PUBLIC_BY_NECESSITY = {"/esign/webhook"}


def test_routes_exist_and_are_authed():
    from auth_supabase import require_user

    by_path = {}
    for r in boldsign_router.router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in by_path.get("/esign/send", set())
    assert "GET" in by_path.get("/esign/list", set())
    assert "POST" in by_path.get("/esign/{esign_id}/refresh", set())
    assert "POST" in by_path.get("/esign/webhook", set())

    for r in boldsign_router.router.routes:
        if r.path in PUBLIC_BY_NECESSITY:
            continue
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


def test_only_the_webhook_is_public():
    """The exemption list is not a place things quietly get added to.

    If a future route lands without require_user, this fails and names
    it — the exemption has to be a deliberate edit to PUBLIC_BY_NECESSITY
    with a reason, not an oversight that ships."""
    from auth_supabase import require_user

    public = {r.path for r in boldsign_router.router.routes
              if require_user not in [d.call for d in r.dependant.dependencies]}
    assert public == PUBLIC_BY_NECESSITY, (
        f"unauthenticated routes changed: {public ^ PUBLIC_BY_NECESSITY}")


def test_contract_signed_is_cataloged_with_a_real_emitter():
    entry = event_spine.EVENT_CATALOG["contract_signed"]
    assert "boldsign" in entry["source"]
    assert not entry.get("legacy")

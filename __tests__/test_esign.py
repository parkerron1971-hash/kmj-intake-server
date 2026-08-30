# __tests__/test_esign.py
#
# E-sign v1 (DocuSeal adapter). Pins: status mapping, how the submission
# id is read back out of a send, route existence + auth, and that
# contract_signed stays cataloged on the spine.

import docuseal_router
import event_spine


def test_status_mapping():
    m = docuseal_router.map_provider_status
    assert m("pending") == "sent"
    assert m("Completed") == "completed"
    assert m("Declined") == "declined"
    assert m("Expired") == "expired"
    assert m("SomethingNew") is None
    assert m(None) is None


def test_revoked_is_no_longer_a_provider_status():
    """DocuSeal has no 'revoked' — cancelling archives the submission
    instead. The word stays in OUR vocabulary because adapter #1 wrote
    rows carrying it, but nothing maps onto it any more. Pinned so that
    a future adapter that DOES have the concept has to add it back
    deliberately rather than inherit it by accident."""
    assert docuseal_router.map_provider_status("revoked") is None
    assert "revoked" not in docuseal_router._STATUS_MAP.values()


# ── Reading the id back out of a send ────────────────────────────────

def test_submission_id_from_the_submission_object():
    assert docuseal_router.submission_id_from_send({"id": 4021}) == "4021"


def test_submission_id_from_a_bare_submitter_list():
    """The other documented response shape. Both carry the submission
    id; neither is worth a live surprise."""
    out = docuseal_router.submission_id_from_send(
        [{"id": 77, "submission_id": 4021, "email": "a@b.co"}])
    assert out == "4021"


def test_a_submitter_id_is_never_mistaken_for_a_submission_id():
    """THE LOAD-BEARING TEST OF THIS FILE.

    Submitters and submissions are separate integer sequences, so
    submitter 77 and submission 77 both exist and look identical. If the
    reader ever falls back to a bare `id` on a submitter row we would
    store a plausible number that refreshes and webhooks then match
    against the wrong agreement — or nothing — forever, with no error
    anywhere. A shape carrying only a submitter id must yield nothing."""
    assert docuseal_router.submission_id_from_send([{"id": 77}]) == ""
    assert docuseal_router.submission_id_from_send({"submitters": [{"id": 77}]}) == ""


def test_junk_responses_yield_no_id_rather_than_raising():
    for junk in (None, "", [], {}, "a string", [{"nope": 1}]):
        assert docuseal_router.submission_id_from_send(junk) == ""


# The one route that cannot carry require_user: DocuSeal has no login,
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
    for r in docuseal_router.router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in by_path.get("/esign/send", set())
    assert "GET" in by_path.get("/esign/list", set())
    assert "POST" in by_path.get("/esign/{esign_id}/refresh", set())
    assert "POST" in by_path.get("/esign/webhook", set())

    for r in docuseal_router.router.routes:
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

    public = {r.path for r in docuseal_router.router.routes
              if require_user not in [d.call for d in r.dependant.dependencies]}
    assert public == PUBLIC_BY_NECESSITY, (
        f"unauthenticated routes changed: {public ^ PUBLIC_BY_NECESSITY}")


def test_the_frontends_contract_did_not_move():
    """The provider swap must be invisible above the seam. These four
    paths are what ApprovalQueue and DocumentsPanel call; renaming one
    while porting the adapter would break the panel with a green suite
    otherwise."""
    paths = {r.path for r in docuseal_router.router.routes}
    assert {"/esign/send", "/esign/list", "/esign/{esign_id}/refresh",
            "/esign/webhook"} <= paths


def test_contract_signed_is_cataloged_with_a_real_emitter():
    entry = event_spine.EVENT_CATALOG["contract_signed"]
    assert "docuseal" in entry["source"]
    assert not entry.get("legacy")


# ── Rows written by a retired adapter ────────────────────────────────

class _FakeUser:
    id = "owner-1"


def _wire_refresh(monkeypatch, provider):
    def _get(path):
        if path.startswith("/esign_documents"):
            return [{"id": "row-1", "business_id": "biz-1", "provider": provider,
                     "document_id": "legacy-id", "status": "sent",
                     "title": "Revenue Share Agreement",
                     "signer_email": "aunt@example.com", "signer_name": "Aunt"}]
        return [{"id": "biz-1", "name": "KMJ", "owner_id": "owner-1"}]
    monkeypatch.setattr(docuseal_router.sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(docuseal_router.sb_clients, "sb_patch_as_service",
                        lambda *a, **k: None)


def test_refresh_of_a_retired_provider_row_never_asks_docuseal(monkeypatch):
    """A boldsign-era row carries a boldsign id. Asking DocuSeal about it
    404s, and this endpoint would report that as "couldn't reach the
    e-sign provider" — a scary, wrong claim about a healthy provider,
    on a button the panel offers but that can never work. Answer
    honestly and don't make the call at all."""
    import asyncio
    _wire_refresh(monkeypatch, "boldsign")
    called = {"n": 0}

    async def _live(document_id):
        called["n"] += 1
        return "completed"
    monkeypatch.setattr(docuseal_router, "_live_status", _live)

    out = asyncio.run(docuseal_router.esign_refresh("row-1", "biz-1", _FakeUser()))

    assert called["n"] == 0, "asked DocuSeal about another provider's id"
    assert out["ok"] is True
    assert out["changed"] is False
    assert out["status"] == "sent"          # the last status that was ever real
    assert out["retired_provider"] == "boldsign"


def test_refresh_of_a_current_row_does_ask_docuseal(monkeypatch):
    """The guard must not be so eager that it swallows live documents —
    a rejection that applies to everything is the same bug as no
    refresh at all."""
    import asyncio
    _wire_refresh(monkeypatch, "docuseal")
    called = {"n": 0}

    async def _live(document_id):
        called["n"] += 1
        return "completed"
    monkeypatch.setattr(docuseal_router, "_live_status", _live)

    async def _no_emails(biz, doc):
        return None
    monkeypatch.setattr(docuseal_router, "_send_completion_emails", _no_emails)
    import event_spine, audit_log
    monkeypatch.setattr(event_spine, "emit", lambda *a, **k: None)
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: None)

    out = asyncio.run(docuseal_router.esign_refresh("row-1", "biz-1", _FakeUser()))

    assert called["n"] == 1
    assert out["changed"] is True
    assert out["status"] == "completed"


def test_a_row_with_no_provider_is_treated_as_current(monkeypatch):
    """Defaulting a null provider to 'retired' would silently stop
    refreshing real documents. Absent means current."""
    import asyncio
    _wire_refresh(monkeypatch, None)
    called = {"n": 0}

    async def _live(document_id):
        called["n"] += 1
        return "sent"
    monkeypatch.setattr(docuseal_router, "_live_status", _live)

    out = asyncio.run(docuseal_router.esign_refresh("row-1", "biz-1", _FakeUser()))
    assert called["n"] == 1
    assert "retired_provider" not in out

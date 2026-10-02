"""Offline workflow and security tests. No live provider calls."""
import asyncio
import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import lane_mcp as mcp
import lane_store as store
import lane_purchases as p
import chief_lane_wallet as chief

BID = "00000000-0000-4000-8000-000000000001"
UID = "00000000-0000-4000-8000-000000000002"
KEY = "lane_test_synthetic_only"
PROMPT = "Buy one cable from example.com under 20 dollars"
DETAILS = {"merchant_name": "Example Store", "merchant_url": "https://example.com/cable", "max_amount_cents": 2000, "account": "Not account-based"}
DRAFT = {"kind": "draft_ready", "session_id": "sess_test", "approval_url": "https://wallet.getonlane.com/approve/lint_test",
         "draft": {"intent_id": "lint_test", "mandates": [{"mandate_id": "mand_test", "merchant": "example.com", "summary": "One cable", "max_amount_cents": 2000}]}}


@contextmanager
def owner_says(words):
    """The owner's own message this turn, as the chat handler records it."""
    from chief_code import turn_scope
    token = turn_scope.set({"words": words})
    try:
        yield
    finally:
        turn_scope.reset(token)


class Journal:
    """Shared storage test double. SQL claim/lease semantics are also tested in PGlite."""
    def __init__(self):
        self.rows = {}
        self.links = {}

    def link(self, name, a):
        owner = (a["p_business_id"], a["p_user_id"])
        rows = self.links.setdefault(owner, {}) if name == "lane_link_save" else self.links.get(owner, {})
        if name == "lane_link_save":
            if a["p_link_hash"] in rows:
                rows[a["p_link_hash"]]["encrypted_state"] = a["p_encrypted_state"]
                return rows[a["p_link_hash"]]["id"]
            if len(rows) >= 20:
                return None
            rows[a["p_link_hash"]] = {"id": a["p_id"], "link_hash": a["p_link_hash"], "encrypted_state": a["p_encrypted_state"]}
            return a["p_id"]
        if name == "lane_link_list":
            return [copy.deepcopy(r) for r in rows.values()]
        if name == "lane_link_delete":
            for digest, row in list(rows.items()):
                if row["id"] == a["p_id"]:
                    del rows[digest]
                    return True
            return False
        raise AssertionError(name)

    def __call__(self, name, **a):
        if name.startswith("lane_link_"):
            return self.link(name, a)
        identity = (a["p_business_id"], a["p_user_id"], a.get("p_id"))
        if name == "lane_purchase_list":
            return [dict(copy.deepcopy(v), id=k[2]) for k, v in self.rows.items() if k[:2] == identity[:2]]
        row = self.rows.get(identity)
        if name == "lane_purchase_create":
            if row:
                return row["hash"] == a["p_request_hash"]
            self.rows[identity] = {"encrypted_state": a["p_encrypted_state"], "revision": 0,
                                  "checkout_claimed": False, "lease": None, "hash": a["p_request_hash"]}
            return True
        if name == "lane_purchase_acquire":
            if not row or row["lease"]:
                return None
            row["lease"] = a["p_lease"]
            return copy.deepcopy(row)
        if name == "lane_purchase_release":
            if row and row["lease"] == a["p_lease"]:
                row["lease"] = None
                return True
            return False
        if name == "lane_purchase_save":
            if not row or row["lease"] != a["p_lease"] or row["revision"] != a["p_revision"]:
                return None
            if a["p_claim"] and row["checkout_claimed"]:
                return None
            row.update(encrypted_state=a["p_encrypted_state"], revision=row["revision"] + 1,
                       checkout_claimed=row["checkout_claimed"] or a["p_claim"])
            return copy.deepcopy(row)
        raise AssertionError(name)


@pytest.fixture
def env(monkeypatch):
    for key, val in {"LANE_PILOT_ENABLED": "true", "LANE_PURCHASES_ENABLED": "true", "LANE_CHECKOUT_ENABLED": "true",
                     "LANE_PILOT_BUSINESS_ID": BID, "LANE_PILOT_USER_ID": UID, "LANE_PILOT_API_KEY": KEY,
                     "LANE_WALLET_ENCRYPTION_KEY": Fernet.generate_key().decode()}.items():
        monkeypatch.setenv(key, val)
    journal = Journal()
    monkeypatch.setattr(store, "rpc", journal)
    import chief_holds
    chief_holds.clear()
    monkeypatch.setattr(p.merchant, "inspect", lambda url: {"url": url, "status": "page_read", "excerpt": "One cable", "note": "Final total is not verified."})
    calls = []
    responses = {
        "intent_list": {"intents": [{"id": "lint_test", "amount": "20.00", "currency": "USD", "merchants": ["example.com"]}]},
        "intent_submit": copy.deepcopy(DRAFT),
        "intent_get_status": {"kind": "complete", "lane_intent_id": "lint_test"},
        "find_products": {"outcome": "ok", "products": [{"item": "One cable", "url": "https://example.com/cable"}], "unresolved": []},
        "start_session": {"outcome": "running", "intent_id": "lint_test"},
        "get_session_status": {"outcome": "running", "intent_id": "lint_test"},
    }
    def call(key, tool, args):
        assert key == KEY
        calls.append((tool, args))
        if tool == "start_session":
            assert next(iter(journal.rows.values()))["checkout_claimed"], "claim must persist before spending"
        response = responses[tool]
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)
    monkeypatch.setattr(mcp, "call", call)
    return SimpleNamespace(journal=journal, calls=calls, responses=responses)


def prepared(env):
    row = p.draft(BID, UID, uuid4(), PROMPT, **DETAILS)
    row = p.prepare(BID, UID, row["id"], row["revision"])
    return p.refresh(BID, UID, row["id"])


def test_draft_is_idempotent_encrypted_and_bound(env):
    pid = str(uuid4())
    first = p.draft(BID, UID, pid, PROMPT, **DETAILS)
    second = p.draft(BID, UID, pid, PROMPT, **DETAILS)
    assert first == second
    assert env.calls == []
    assert first["phase"] == "new" and first["purchase_details"] == dict(DETAILS, currency="USD")
    raw = next(iter(env.journal.rows.values()))
    assert PROMPT not in raw["encrypted_state"] and KEY not in raw["encrypted_state"]
    with pytest.raises(mcp.LaneError):
        store.unpack(store.binding(BID, UID, "lane_different_synthetic", pid), raw)
    with pytest.raises(mcp.LaneError):
        p.draft(BID, UID, pid, "Changed request", **DETAILS)
    with pytest.raises(mcp.LaneError):
        p.draft(BID, str(uuid4()), uuid4(), PROMPT, **DETAILS)


def test_approval_is_not_an_order_and_checkout_claim_survives_replay(env):
    approved = prepared(env)
    assert approved["phase"] == "approved" and "order_number" not in approved
    result = p.checkout(BID, UID, approved["id"], approved["revision"])
    assert result["phase"] == "running"
    assert [c[0] for c in env.calls][-3:] == ["find_products", "start_session", "get_session_status"]
    p.checkout(BID, UID, result["id"], result["revision"])
    assert len([c for c in env.calls if c[0] == "start_session"]) == 1
    env.responses["get_session_status"] = {"outcome": "ok", "data": {"order_number": "ORDER-TEST", "amount_charged": "12.97"}}
    result = p.refresh(BID, UID, result["id"])
    assert result["phase"] == "placed" and result["order_number"] == "ORDER-TEST"


@pytest.mark.parametrize("outcome", ["failed", "error", "session_not_found", "busy"])
def test_uncertain_orders_never_retry(env, outcome):
    approved = prepared(env)
    env.responses["get_session_status"] = {"outcome": outcome, "reason": "order_unconfirmed"}
    result = p.checkout(BID, UID, approved["id"], approved["revision"])
    assert result["phase"] == "checkout_unknown"
    p.checkout(BID, UID, result["id"], result["revision"])
    assert len([c for c in env.calls if c[0] == "start_session"]) == 1


def test_timeout_after_start_keeps_claim_and_reconciles(env):
    approved = prepared(env)
    env.responses["start_session"] = mcp.LaneError("Timeout")
    result = p.checkout(BID, UID, approved["id"], approved["revision"])
    assert result["checkout_claimed"] and result["phase"] == "checkout_unknown"
    result = p.refresh(BID, UID, result["id"])
    assert result["phase"] == "running"
    p.checkout(BID, UID, result["id"], result["revision"])
    assert len([c for c in env.calls if c[0] == "start_session"]) == 1


def test_timeout_drafting_never_resubmits(env):
    pid = str(uuid4())
    env.responses["intent_submit"] = mcp.LaneError("Timeout")
    row = p.draft(BID, UID, pid, PROMPT, **DETAILS)
    with pytest.raises(mcp.LaneError):
        p.prepare(BID, UID, row["id"], row["revision"])
    result = p.draft(BID, UID, pid, PROMPT, **DETAILS)
    assert result["phase"] == "submitting"
    assert len(env.calls) == 1


def test_stale_view_disabled_checkout_and_wrong_approval_never_spend(env, monkeypatch):
    row = prepared(env)
    with pytest.raises(mcp.LaneError):
        p.checkout(BID, UID, row["id"], row["revision"] - 1)
    monkeypatch.setenv("LANE_CHECKOUT_ENABLED", "false")
    with pytest.raises(mcp.LaneError):
        p.checkout(BID, UID, row["id"], row["revision"])
    monkeypatch.setenv("LANE_CHECKOUT_ENABLED", "true")
    env.responses["intent_get_status"]["lane_intent_id"] = "lint_other"
    with pytest.raises(mcp.LaneError):
        p.checkout(BID, UID, row["id"], row["revision"])
    assert not any(c[0] == "start_session" for c in env.calls)


def test_unresolved_products_and_rejected_approval_block_checkout(env):
    row = prepared(env)
    env.responses["find_products"] = {"outcome": "partial", "products": [], "unresolved": ["cable"]}
    row = p.checkout(BID, UID, row["id"], row["revision"])
    assert row["phase"] == "products_needed" and not row["checkout_claimed"]
    env.responses["intent_get_status"] = {"kind": "rejected"}
    row = p.refresh(BID, UID, row["id"])
    assert row["phase"] == "rejected"
    assert not any(c[0] == "start_session" for c in env.calls)


def test_questions_preserve_all_choices_and_resume_same_draft(env):
    env.responses["intent_submit"] = {"kind": "needs_info", "session_id": "sess_test",
                                     "questions": [{"prompt": "Which length?", "suggestions": ["1 meter", "2 meters"]}]}
    row = p.draft(BID, UID, uuid4(), PROMPT, **DETAILS)
    row = p.prepare(BID, UID, row["id"], row["revision"])
    assert row["questions"][0]["suggestions"] == ["1 meter", "2 meters"]
    env.responses["intent_submit"] = DRAFT
    result = p.answer(BID, UID, row["id"], p.Answer(revision=row["revision"], answer="2 meters"))
    assert result["phase"] == "review"
    assert env.calls[-1][1] == {"session_id": "sess_test", "prompt": "2 meters"}


@pytest.mark.parametrize("url", ["http://wallet.getonlane.com/approve/x", "https://wallet.getonlane.com.evil.com/approve/x",
                               "https://evil@wallet.getonlane.com/approve/x", "https://wallet.getonlane.com:443/approve/x",
                               "https://wallet.getonlane.com/approve/x?redirect=https://evil.com",
                               "https://wallet.getonlane.com/approve/x#bad", "https://wallet.getonlane.com/approve/x\\bad"])
def test_hosted_verification_urls_fail_closed(url):
    with pytest.raises(mcp.LaneError):
        p.safe_url(url)


def test_password_requests_use_hosted_url_not_input_or_logs(env):
    row = prepared(env)
    env.responses["get_session_status"] = {"outcome": "needs_human", "logs": ["PRIVATE"],
        "suspend": {"kind": "sign_in_user_pass", "prompt": "Sign in to the merchant.", "ask_url": "https://wallet.getonlane.com/asks/ask_test"}}
    row = p.checkout(BID, UID, row["id"], row["revision"])
    assert row["ask_prompt"] == "Sign in to the merchant."
    assert row["ask_url"].startswith("https://wallet.getonlane.com/")
    assert "PRIVATE" not in json.dumps(row)
    with pytest.raises(mcp.LaneError):
        p.answer(BID, UID, row["id"], p.Answer(revision=row["revision"], answer="should never be accepted"))


def test_http_owner_and_stepup_boundary(env, monkeypatch):
    monkeypatch.setattr(p, "owner", lambda bid, session: (bid, UID))
    app = FastAPI()
    app.include_router(p.router)
    app.dependency_overrides[p.sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=UID))
    checked = Mock(side_effect=HTTPException(403, "Confirm account"))
    monkeypatch.setattr(p, "require_unlock", checked)
    with TestClient(app) as client:
        row = client.post(f"/lane/wallet/{BID}/purchases", json={"request_id": str(uuid4()), "prompt": PROMPT, **DETAILS}).json()
        response = client.post(f"/lane/wallet/{BID}/purchases/{row['id']}/checkout", json={"revision": row["revision"]})
        assert response.status_code == 403 and response.headers["cache-control"] == "no-store"
        assert not any(c[0] == "start_session" for c in env.calls)
        assert client.post(f"/lane/wallet/{BID}/purchases", json={"request_id": str(uuid4()), "prompt": PROMPT, "api_key": KEY}).status_code == 422
        def denied(*args):
            raise HTTPException(403, "Not owner")
        monkeypatch.setattr(p, "owner", denied)
        assert client.get(f"/lane/wallet/{BID}/purchases").status_code == 403


def test_chief_never_exposes_checkout_or_allows_unattended_calls(env, monkeypatch):
    import chief_of_staff as cos
    import action_registry
    token = cos._TURN_USER_ID.set(UID)
    monkeypatch.setattr(chief.business_access, "assert_access", Mock())
    try:
        for surface, prompted in [("agent", True), ("chat", False)]:
            result = asyncio.run(chief.dispatch(None, {"id": BID}, {"operation": "draft", "prompt": PROMPT, **DETAILS},
                                               surface=surface, prompted=prompted, user_id=UID))
            assert result["failed"]
        for operation in ["approve", "checkout", "wallet_load_credits"]:
            assert asyncio.run(chief.dispatch(None, {"id": BID}, {"operation": operation},
                                              surface="chat", prompted=True, user_id=UID))["failed"]
        result = asyncio.run(chief.dispatch(None, {"id": BID}, {"operation": "draft", "prompt": PROMPT, **DETAILS},
                                           surface="chat", prompted=True, user_id=UID))
        assert result["failed"] and result["needs_confirmation"] and not env.journal.rows
        with owner_says("Go ahead"):
            result = asyncio.run(chief.dispatch(None, {"id": BID}, {"operation": "draft", "prompt": PROMPT, **DETAILS},
                                               surface="chat", prompted=True, user_id=UID))
        assert result["lane"]["phase"] == "new"
        assert not action_registry.may_expose_to_agent("lane_wallet", allow_writes=True)
        assert asyncio.run(chief.handle_lane_wallet(None, {"id": BID}, {}))["failed"]
    finally:
        cos._TURN_USER_ID.reset(token)


def test_mcp_tools_are_allowlisted_and_structured_or_text_results_work():
    # Exercise the real MCP adapter, bypassing the workflow's injected call double.
    for structured in [True, False]:
        calls = []
        def handle(request):
            body = json.loads(request.content)
            calls.append(body["method"])
            if body["method"] == "initialize":
                result = {"protocolVersion": mcp.PROTOCOL, "capabilities": {"tools": {}}}
            elif body["method"] == "notifications/initialized":
                return httpx.Response(202)
            else:
                assert body["params"]["name"] == "intent_get_status"
                data = {"kind": "draft_ready"}
                result = {"structuredContent": data} if structured else {"content": [{"type": "text", "text": json.dumps(data)}]}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
        assert mcp.call(KEY, "intent_get_status", {"session_id": "sess_test"}, transport=httpx.MockTransport(handle)) == {"kind": "draft_ready"}
        assert calls == ["initialize", "notifications/initialized", "tools/call"]
    network = Mock(side_effect=AssertionError("must not connect"))
    for tool in ["intent_approve", "wallet_load_credits", "resume_session", "unknown"]:
        with pytest.raises(mcp.LaneError):
            mcp.call(KEY, tool, {}, transport=httpx.MockTransport(network))
    network.assert_not_called()


def test_native_chief_tool_runs_through_permission_door(env, monkeypatch):
    import chief_of_staff as cos
    import chief_tool_loop as loop
    import policy_engine
    monkeypatch.setattr(chief.business_access, "assert_access", Mock())
    monkeypatch.setattr(policy_engine, "evaluate", lambda *a, **kw: policy_engine.Verdict(True, "chat:owner", "fixture"))
    token = cos._TURN_USER_ID.set(UID)
    taint = cos._UNTRUSTED_TAINT.set(0)
    try:
        loop.reset_turn(writes_allowed=True)
        assert any(t["name"] == "lane_wallet" for t in loop.tool_definitions_for_turn(True))
        def native(args):
            return asyncio.run(loop.execute_tool_use(None, {"id": BID, "owner_id": UID, "settings": {}}, "lane_wallet", args))
        error, result = native({"operation": "look", "merchant_url": DETAILS["merchant_url"]})
        assert not error and "nothing was saved" in result
        error, result = native({"operation": "draft", "prompt": PROMPT, **DETAILS})
        assert error and "HELD" in result and not env.journal.rows
        # The held write closes this turn's writes; the owner's go-ahead is the next turn.
        loop.reset_turn(writes_allowed=True)
        with owner_says("save it"):
            error, result = native({"operation": "draft", "prompt": PROMPT, **DETAILS})
        assert not error, result
        assert len(env.journal.rows) == 1
        assert not env.calls
        assert not any(c[0] == "start_session" for c in env.calls)
    finally:
        cos._TURN_USER_ID.reset(token)
        cos._UNTRUSTED_TAINT.reset(taint)


def test_failed_checkout_claim_blocks_network(env, monkeypatch):
    row = prepared(env)
    real_save = store.Purchase.save
    def deny_claim(self, *, claim=False):
        if claim:
            raise mcp.LaneError("Storage unavailable")
        return real_save(self, claim=claim)
    monkeypatch.setattr(store.Purchase, "save", deny_claim)
    with pytest.raises(mcp.LaneError):
        p.checkout(BID, UID, row["id"], row["revision"])
    assert not any(c[0] == "start_session" for c in env.calls)


def test_incomplete_receipt_does_not_claim_order_placed(env):
    row = prepared(env)
    env.responses["get_session_status"] = {"outcome": "ok", "data": {}}
    row = p.checkout(BID, UID, row["id"], row["revision"])
    assert row["phase"] == "checkout_unknown" and "order_number" not in row


def test_overbudget_draft_is_durable_without_approval_link(env):
    env.responses["intent_submit"]["draft"]["mandates"][0]["max_amount_cents"] = 2600
    row = p.draft(BID, UID, uuid4(), PROMPT, **dict(DETAILS, max_amount_cents=1000))
    row = p.prepare(BID, UID, row["id"], row["revision"])
    assert row["phase"] == "attention" and "approval_url" not in row
    assert "exceeds" in row["message"]
    state = store.listing(BID, UID, KEY)[0]
    assert state["session_id"] == "sess_test" and state["intent_id"] == "lint_test"
    with pytest.raises(mcp.LaneError):
        p.checkout(BID, UID, row["id"], row["revision"])
    env.responses["intent_get_status"] = {"kind": "rejected"}
    assert p.refresh(BID, UID, row["id"])["phase"] == "rejected"
    assert not any(c[0] == "start_session" for c in env.calls)


@pytest.mark.parametrize("change", [
    {"amount": "26.00"}, {"amount": "NaN"}, {"amount": "Infinity"},
    {"currency": "EUR"}, {"merchants": ["other.example"]}, {"id": "lint_other"},
])
def test_fresh_provider_limits_block_changed_purchase(env, change):
    row = prepared(env)
    env.responses["intent_list"]["intents"][0].update(change)
    with pytest.raises(mcp.LaneError):
        p.checkout(BID, UID, row["id"], row["revision"])
    assert not any(c[0] == "start_session" for c in env.calls)


def test_wrong_resolved_product_blocks_checkout(env):
    row = prepared(env)
    env.responses["find_products"]["products"][0]["url"] = "https://example.com/different"
    row = p.checkout(BID, UID, row["id"], row["revision"])
    assert row["phase"] == "products_needed" and not row["checkout_claimed"]


def test_missing_budget_and_account_never_submit(env):
    for details in ({}, dict(DETAILS, max_amount_cents=True), dict(DETAILS, account="")):
        with pytest.raises(mcp.LaneError):
            p.draft(BID, UID, uuid4(), PROMPT, **details)
    assert not env.calls


def test_dismiss_unsent_proposal_and_changed_details(env):
    pid = uuid4()
    row = p.draft(BID, UID, pid, PROMPT, **DETAILS)
    with pytest.raises(mcp.LaneError):
        p.draft(BID, UID, pid, PROMPT, **dict(DETAILS, max_amount_cents=3000))
    assert p.close_proposal(BID, UID, str(pid), row["revision"])["phase"] == "closed"
    assert not env.calls


def test_schema_failure_retains_session_and_never_resubmits(env):
    env.responses["intent_submit"] = {"kind": "draft_ready", "session_id": "sess_test",
                                    "draft": {"intent_id": "lint_test", "mandates": []}}
    row = p.draft(BID, UID, uuid4(), PROMPT, **DETAILS)
    row = p.prepare(BID, UID, row["id"], row["revision"])
    assert row["phase"] == "attention"
    with pytest.raises(mcp.LaneError):
        p.prepare(BID, UID, row["id"], row["revision"])
    assert len([c for c in env.calls if c[0] == "intent_submit"]) == 1


def test_provider_display_name_matches_only_reviewed_name(env):
    env.responses["intent_submit"]["draft"]["mandates"][0]["merchant"] = "Example Store"
    env.responses["intent_list"]["intents"][0]["merchants"] = ["Example Store"]
    row = prepared(env)
    assert p.checkout(BID, UID, row["id"], row["revision"])["phase"] == "running"


@pytest.mark.parametrize("bad_draft", [[], {"currency": "EUR", "mandates": []}, {"mandates": ["unexpected"]}])
def test_malformed_draft_retains_reconciliation_session(env, bad_draft):
    env.responses["intent_submit"] = {"kind": "draft_ready", "session_id": "sess_test", "draft": bad_draft}
    row = p.draft(BID, UID, uuid4(), PROMPT, **DETAILS)
    row = p.prepare(BID, UID, row["id"], row["revision"])
    assert row["phase"] == "attention" and "approval_url" not in row
    env.responses["intent_get_status"] = {"kind": "rejected"}
    assert p.refresh(BID, UID, row["id"])["phase"] == "rejected"


@pytest.mark.parametrize("message, allowed", [
    ("Chief, buy $10 in Claude API credits", True),
    ("Please purchase one USB-C cable under $20", True),
    ("Can you shop for printer paper for the app team?", True),
    ("Approve this purchase", False),
    ("Cancel my purchase", False),
    ("Show my purchase history in the app", False),
    ("Find my invoice in my emails", False),
])
def test_buying_can_search_but_account_records_and_consent_do_not(message, allowed):
    import chief_of_staff as cos
    assert cos._web_search_allowed(message) is allowed


# Look first, then ask; saved merchant links.
import lane_links as links


@pytest.fixture
def chief_turn(env, monkeypatch):
    import chief_of_staff as cos
    monkeypatch.setattr(chief.business_access, "assert_access", Mock())
    token = cos._TURN_USER_ID.set(UID)
    yield env
    cos._TURN_USER_ID.reset(token)


def chief_call(action, words=None):
    def run():
        return asyncio.run(chief.dispatch(None, {"id": BID}, action, surface="chat", prompted=True, user_id=UID))
    if words is None:
        return run()
    with owner_says(words):
        return run()


def wallet_client(monkeypatch):
    monkeypatch.setattr(p, "owner", lambda bid, session: (bid, UID))
    app = FastAPI()
    app.include_router(p.router)
    app.dependency_overrides[p.sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=UID))
    return TestClient(app)


@pytest.mark.parametrize("words, operation, released", [
    ("save it", "draft", True), ("Go ahead.", "draft", True), ("yes, save it for review", "draft", True),
    ("go ahead and remember it", "draft", True), ("save it and remember the link", "draft", True),
    ("ok do it", "draft", True), ("remember it", "remember", True), ("yes remember the link too", "remember", True),
    ("yes", "draft", False), ("ok", "draft", False), ("remember it", "draft", False), ("don't save it", "draft", False),
    ("save it?", "draft", False), ("go ahead and buy two more", "draft", False), ("", "draft", False),
])
def test_only_the_owners_whole_message_go_ahead_releases(words, operation, released):
    assert chief.owner_go_ahead(words, operation) is released


def test_look_reads_the_page_and_saves_nothing(chief_turn):
    result = chief_call({"operation": "look", "merchant_url": DETAILS["merchant_url"]})
    assert not result.get("failed") and result["label"] == "Looked at example.com"
    assert "One cable" in result["result"] and result["lane"]["look"]["status"] == "page_read"
    assert not chief_turn.journal.rows and not chief_turn.journal.links and not chief_turn.calls
    assert chief_call({"operation": "look", "merchant_url": "http://example.com/cable"})["failed"]


def test_draft_is_read_back_and_saved_only_on_the_go_ahead(chief_turn):
    action = {"operation": "draft", "prompt": PROMPT, **DETAILS}
    held = chief_call(action)
    assert held["failed"] and held["needs_confirmation"] and held["label"].startswith("Held for your go-ahead")
    assert "$20.00" in held["result"] and DETAILS["merchant_url"] in held["result"] and "One cable" in held["result"]
    assert chief_call(action, "yes")["needs_confirmation"]  # A bare yes answers too many questions.
    assert not chief_turn.journal.rows
    saved = chief_call(action, "save it")
    assert saved["lane"]["phase"] == "new" and saved["label"] == "Proposal saved for review"
    again = chief_call(action, "save it")  # A duplicate emission on the go-ahead turn
    assert "already saved" in again["result"] and len(chief_turn.journal.rows) == 1
    assert not chief_turn.calls  # Nothing reached Lane.


def test_go_ahead_releases_only_the_limit_that_was_read_back(chief_turn):
    chief_call({"operation": "draft", "prompt": PROMPT, **DETAILS})
    changed = chief_call({"operation": "draft", "prompt": PROMPT, **dict(DETAILS, max_amount_cents=3000)}, "go ahead")
    assert changed["needs_confirmation"] and "$30.00" in changed["result"] and not chief_turn.journal.rows


def test_reworded_request_still_matches_what_was_read_back(chief_turn):
    chief_call({"operation": "draft", "prompt": PROMPT, **DETAILS})
    saved = chief_call({"operation": "draft", "prompt": "One USB cable from Example Store",
                        **dict(DETAILS, merchant_name="example store", account="not account-based")}, "go ahead")
    assert saved["lane"]["phase"] == "new"


def test_remembered_link_is_held_then_encrypted_listed_and_forgotten(chief_turn):
    action = {"operation": "remember", "merchant_url": DETAILS["merchant_url"], "merchant_name": "Example Store",
              "account": "Not account-based"}
    assert chief_call(action)["needs_confirmation"] and not chief_turn.journal.links
    assert chief_call(action, "remember it")["label"] == "Saved link: Example Store"
    raw = json.dumps(list(chief_turn.journal.links.values()))
    assert "example.com" not in raw and "Not account-based" not in raw
    assert chief_call(action)["label"] == "Link already saved"  # No second hold for a link already kept.
    status = chief_call({"operation": "status"})
    assert [s["merchant_url"] for s in status["lane"]["saved_links"]] == [DETAILS["merchant_url"]]
    look = chief_call({"operation": "look", "merchant_url": DETAILS["merchant_url"]})
    assert "Already in the owner's saved links" in look["result"]
    assert chief_call({"operation": "forget", "merchant_url": DETAILS["merchant_url"]})["label"] == "Removed saved link"
    assert links.listing(BID, UID) == []
    assert chief_call({"operation": "forget", "merchant_url": DETAILS["merchant_url"]})["failed"]
    assert not chief_turn.calls


def test_draft_with_remember_keeps_the_link_after_the_go_ahead(chief_turn):
    action = {"operation": "draft", "prompt": PROMPT, **DETAILS, "remember": True}
    held = chief_call(action)
    assert "remember this link" in held["result"] and not chief_turn.journal.links
    saved = chief_call(action, "go ahead and remember it")
    assert "merchant link remembered" in saved["result"]
    assert [s["account"] for s in links.listing(BID, UID)] == ["Not account-based"]


def test_links_stay_with_their_owner_and_one_page_account_is_one_entry(env):
    links.save(BID, UID, DETAILS["merchant_url"], "Acme org")
    links.save(BID, UID, DETAILS["merchant_url"], "ACME ORG", "Example Store")
    assert [(s["account"], s["merchant_name"]) for s in links.listing(BID, UID)] == [("ACME ORG", "Example Store")]
    other = "00000000-0000-4000-8000-000000000009"
    assert links.listing(BID, other) == []
    assert not links.remove(BID, other, links.listing(BID, UID)[0]["id"])
    # A row copied under another owner cannot be opened, so it is never shown or used.
    env.journal.links[(BID, other)] = copy.deepcopy(env.journal.links[(BID, UID)])
    assert links.listing(BID, other) == []


def test_link_cap_never_costs_the_owner_their_proposal(env, monkeypatch):
    for n in range(links.LIMIT):
        links.save(BID, UID, f"https://example.com/item-{n}", "Not account-based")
    with pytest.raises(mcp.LaneError):
        links.save(BID, UID, "https://example.com/one-more", "Not account-based")
    links.save(BID, UID, "https://example.com/item-0", "Not account-based", "Renamed")  # Refreshing one still works.
    with wallet_client(monkeypatch) as client:
        row = client.post(f"/lane/wallet/{BID}/purchases",
                          json={"request_id": str(uuid4()), "prompt": PROMPT, **DETAILS, "remember": True}).json()
    assert row["phase"] == "new" and "20 saved merchant links" in row["link_message"]


def test_wallet_lists_remembers_and_removes_links(env, monkeypatch):
    with wallet_client(monkeypatch) as client:
        body = {"request_id": str(uuid4()), "prompt": PROMPT, **DETAILS}
        assert client.post(f"/lane/wallet/{BID}/purchases", json=dict(body, remember="yes")).status_code == 422
        row = client.post(f"/lane/wallet/{BID}/purchases", json=dict(body, remember=True)).json()
        assert row["phase"] == "new" and "link_message" not in row
        listed = client.get(f"/lane/wallet/{BID}/purchases").json()
        assert [s["merchant_name"] for s in listed["links"]] == ["Example Store"]
        gone = client.post(f"/lane/wallet/{BID}/links/{listed['links'][0]['id']}/remove")
        assert gone.status_code == 200 and gone.headers["cache-control"] == "no-store"
        assert gone.json() == {"removed": True, "links": []}
        assert client.post(f"/lane/wallet/{BID}/links/{uuid4()}/remove").json()["removed"] is False
        monkeypatch.setattr(p.links, "listing", Mock(side_effect=RuntimeError("store down")))
        listed = client.get(f"/lane/wallet/{BID}/purchases").json()
        assert listed["purchases"] and "links" not in listed  # Unavailable, not "none saved".
    assert not env.calls

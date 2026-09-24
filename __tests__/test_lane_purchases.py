"""Offline workflow and security tests. No live provider calls."""
import asyncio
import copy
import json
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
DRAFT = {"kind": "draft_ready", "session_id": "sess_test", "approval_url": "https://wallet.getonlane.com/approve/lint_test",
         "draft": {"intent_id": "lint_test", "mandates": [{"mandate_id": "mand_test", "merchant": "example.com", "summary": "One cable", "max_amount_cents": 2000}]}}


class Journal:
    """Shared storage test double. SQL claim/lease semantics are also tested in PGlite."""
    def __init__(self):
        self.rows = {}

    def __call__(self, name, **a):
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
    calls = []
    responses = {
        "intent_submit": DRAFT,
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
    row = p.draft(BID, UID, uuid4(), PROMPT)
    return p.refresh(BID, UID, row["id"])


def test_draft_is_idempotent_encrypted_and_bound(env):
    pid = str(uuid4())
    first = p.draft(BID, UID, pid, PROMPT)
    second = p.draft(BID, UID, pid, PROMPT)
    assert first == second
    assert [c[0] for c in env.calls] == ["intent_submit"]
    raw = next(iter(env.journal.rows.values()))
    assert PROMPT not in raw["encrypted_state"] and KEY not in raw["encrypted_state"]
    with pytest.raises(mcp.LaneError):
        store.unpack(store.binding(BID, UID, "lane_different_synthetic", pid), raw)
    with pytest.raises(mcp.LaneError):
        p.draft(BID, UID, pid, "Changed request")
    with pytest.raises(mcp.LaneError):
        p.draft(BID, str(uuid4()), uuid4(), PROMPT)


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
    with pytest.raises(mcp.LaneError):
        p.draft(BID, UID, pid, PROMPT)
    result = p.draft(BID, UID, pid, PROMPT)
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
    row = p.draft(BID, UID, uuid4(), PROMPT)
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
        row = client.post(f"/lane/wallet/{BID}/purchases", json={"request_id": str(uuid4()), "prompt": PROMPT}).json()
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
            result = asyncio.run(chief.dispatch(None, {"id": BID}, {"operation": "draft", "prompt": PROMPT},
                                               surface=surface, prompted=prompted, user_id=UID))
            assert result["failed"]
        for operation in ["approve", "checkout", "wallet_load_credits"]:
            assert asyncio.run(chief.dispatch(None, {"id": BID}, {"operation": operation},
                                              surface="chat", prompted=True, user_id=UID))["failed"]
        result = asyncio.run(chief.dispatch(None, {"id": BID}, {"operation": "draft", "prompt": PROMPT},
                                           surface="chat", prompted=True, user_id=UID))
        assert result["lane"]["phase"] == "review"
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
        async def native():
            error, result = await loop.execute_tool_use(None, {"id": BID, "owner_id": UID, "settings": {}},
                                                       "lane_wallet", {"operation": "draft", "prompt": PROMPT})
            assert not error, result
        asyncio.run(native())
        assert len([c for c in env.calls if c[0] == "intent_submit"]) == 1
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

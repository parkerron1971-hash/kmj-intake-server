"""A password confirmed for one business opens nothing at another (2026-11-18).

The step-up endpoint decides who may re-prove a password by the business
named to it: the owner for danger; the owner, an Admin or whoever sets up
jobs and sheets for access. The token it handed back said only "this
person, this scope, fifteen minutes", so that decision did not travel with
it: anyone who owned ANY business could confirm their password there and
carry the token to a business where they were a Manager. An invite the
step-up should have stopped went through (the invite route itself needs
only a Manager), and so did every danger gate whose own route lets a
Manager or an Admin act.

Now an access or danger token names the business it was confirmed for, and
every gate names the business its action is for. A token for another
business, or one that names none, is the same `ledger_locked` as no token,
so the app's prompt asks again for the right one. The ledger scope is not
bound: its pre-check is "may you read this ledger", which each ledger route
asks again for its own business.

The routes are pinned beside their own tests too (test_church_sheet.py,
test_church_login_areas.py, test_church_duties.py, test_chief_office.py,
test_access_asks_by_result.py, test_financial_stepup_routes.py,
test_card_connections.py). People and businesses here are made up."""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-step-up")

import ledger_unlock as L  # noqa: E402
from fastapi import HTTPException  # noqa: E402

A = "0a0a0a0a-0000-4000-8000-00000000000a"      # the business the password was confirmed for
B = "0b0b0b0b-0000-4000-8000-00000000000b"      # another one
USER = "a0000000-0000-4000-8000-000000000001"


def _req(token=None):
    return SimpleNamespace(headers={L.UNLOCK_HEADER: token} if token else {})


@pytest.mark.parametrize("scope", [L.SCOPE_ACCESS, L.SCOPE_DANGER])
def test_a_token_opens_its_own_business_and_no_other(scope):
    tok = L.mint(USER, scope, A)["token"]
    assert L.verify(tok, USER, scope, A) is True
    assert L.verify(tok, USER, scope, B) is False
    assert L.verify(tok, USER, scope) is False, "a gate that names no business opens for nothing"
    assert L.verify(tok, USER, scope, "") is False and L.verify(tok, USER, scope, []) is False
    L.require_unlock(_req(tok), USER, scope, A)                       # no raise
    with pytest.raises(HTTPException) as e:
        L.require_unlock(_req(tok), USER, scope, B)
    # The standard refusal, so the app's prompt asks again (stepUpFetch reads this code).
    assert e.value.status_code == 403
    assert e.value.detail == {"code": "ledger_locked", "scope": scope, "message": L.SCOPE_PROMPT[scope]}


@pytest.mark.parametrize("scope", [L.SCOPE_ACCESS, L.SCOPE_DANGER])
def test_a_token_that_names_no_business_opens_nothing(scope):
    """One minted before 2026-11-18 (at most fifteen minutes old at the
    deploy), or by a caller that forgot the business: a prompt, never a pass."""
    tok = L.mint(USER, scope)["token"]
    assert L.verify(tok, USER, scope, A) is False and L.verify(tok, USER, scope) is False
    with pytest.raises(HTTPException) as e:
        L.require_unlock(_req(tok), USER, scope, A)
    assert e.value.detail["code"] == "ledger_locked"


def test_one_business_however_its_id_is_spelled():
    tok = L.mint(USER, L.SCOPE_ACCESS, A.upper())["token"]
    assert L.verify(tok, USER, L.SCOPE_ACCESS, A)
    assert L.verify(tok, USER, L.SCOPE_ACCESS, A.replace("-", ""))
    assert L.verify(tok, USER, L.SCOPE_ACCESS, f"  {A} ")
    # A short id (the tests of other modules use them) is compared as it is.
    short = L.mint(USER, L.SCOPE_DANGER, "biz1")["token"]
    assert L.verify(short, USER, L.SCOPE_DANGER, "biz1") and not L.verify(short, USER, L.SCOPE_DANGER, "biz2")


def test_an_action_that_covers_several_businesses_takes_a_token_for_any_one_of_them():
    tok = L.mint(USER, L.SCOPE_DANGER, A)["token"]
    assert L.verify(tok, USER, L.SCOPE_DANGER, [B, A]) is True
    assert L.verify(tok, USER, L.SCOPE_DANGER, [B]) is False
    assert L.verify(tok, USER, L.SCOPE_DANGER, [None, ""]) is False


def test_the_business_is_signed_with_the_rest_of_the_token():
    import base64
    import json
    tok = L.mint(USER, L.SCOPE_DANGER, A)["token"]
    p, sig = tok.split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    assert claims["biz"] == A
    claims["biz"] = B
    forged = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    assert L.verify(f"{forged}.{sig}", USER, L.SCOPE_DANGER, B) is False


def test_the_ledger_scope_is_as_it_was():
    """Not bound: reading the ledger is asked again by each ledger route's
    own read gate, so a carried unlock opens nothing its holder couldn't."""
    tok = L.mint(USER)["token"]
    assert L.verify(tok, USER) is True and L.verify(tok, USER, L.SCOPE_LEDGER, B) is True
    L.require_unlock(_req(tok), USER)                                  # no raise
    assert L.verify(L.mint(USER, L.SCOPE_LEDGER, A)["token"], USER, L.SCOPE_LEDGER, B) is True


def test_the_step_up_hands_back_a_token_for_the_business_it_checked(monkeypatch):
    import audit_log
    import rate_limit
    checked = []
    monkeypatch.setattr(L, "_require_actor", lambda biz, uid, scope: checked.append((biz, uid, scope)) or {"id": biz})

    async def right(email, password):
        return True
    monkeypatch.setattr(L, "check_password", right)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: None)
    user = SimpleNamespace(id=USER, email="owner@example.com")
    for scope in (L.SCOPE_ACCESS, L.SCOPE_DANGER):
        out = asyncio.run(L.step_up(L._StepUpBody(business_id=A.upper(), password="pw", scope=scope), user))
        assert checked[-1] == (A, USER, scope)
        assert L.verify(out["token"], USER, scope, A) and not L.verify(out["token"], USER, scope, B)


# ─── Every gate names its business ────────────────────────────────────

def _gates():
    """Every require_unlock call in the server's own modules that asks for
    access or danger: (file, line, names a business?)."""
    out = []
    for name in sorted(os.listdir(ROOT)):
        if not name.endswith(".py") or name == "ledger_unlock.py":
            continue
        src = open(os.path.join(ROOT, name), encoding="utf-8").read()
        if "require_unlock" not in src:
            continue
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if called != "require_unlock":
                continue
            scope = node.args[2] if len(node.args) > 2 else next(
                (k.value for k in node.keywords if k.arg == "scope"), None)
            text = ast.unparse(scope) if scope is not None else "SCOPE_LEDGER"
            if "SCOPE_LEDGER" in text:
                continue
            assert "SCOPE_ACCESS" in text or "SCOPE_DANGER" in text, f"{name}:{node.lineno} asks for {text}"
            names = len(node.args) > 3 or any(k.arg == "business_id" for k in node.keywords)
            out.append((name, node.lineno, names))
    return out


def test_every_access_and_danger_gate_names_the_business_it_is_for():
    gates = _gates()
    assert len(gates) >= 25, "the gates this was written against; fewer means the search stopped finding them"
    missing = [f"{name}:{line}" for name, line, names in gates if not names]
    assert not missing, ("a gate that names no business refuses every token (verify), so this would be a prompt "
                         f"that never clears: {missing}")
    files = {name for name, _, _ in gates}
    for name in ("business_users_router.py", "business_collaborators_router.py", "auditor_portal.py",
                 "church_sheet.py", "church_areas.py", "church_duties.py", "account_lifecycle.py",
                 "stripe_billing.py", "stripe_connect_router.py", "stripe_payments_router.py",
                 "contractors_router.py", "financial_policy_router.py", "card_connections.py",
                 "chief_errands.py", "lane_purchases.py", "link_wallet.py", "agentcard_wallet.py"):
        assert name in files, f"{name} no longer asks for a step-up"


# ─── Deleting a business, and an account ──────────────────────────────

OWNER_USER = SimpleNamespace(id=USER, email="owner@example.com")


@pytest.fixture
def deleting(monkeypatch):
    import account_lifecycle as al
    gone = []

    async def mine(client, uid):
        return [{"id": A, "name": "First Light Church"}, {"id": B, "name": "First Light Books"}]

    async def delete(client, biz):
        gone.append(biz["id"])
        return {}

    async def rows(client, uid):
        return {}
    monkeypatch.setattr(al, "_owned_businesses", mine)
    monkeypatch.setattr(al, "_delete_business", delete)
    monkeypatch.setattr(al, "_delete_user_rows", rows)
    return al, gone


def test_deleting_a_business_takes_the_password_confirmed_for_that_business(deleting):
    al, gone = deleting
    other = _req(L.mint(USER, L.SCOPE_DANGER, B)["token"])
    with pytest.raises(HTTPException) as e:
        asyncio.run(al.delete_business(A, request=other, user=OWNER_USER))
    assert e.value.detail["code"] == "ledger_locked" and e.value.detail["scope"] == "danger" and gone == []
    out = asyncio.run(al.delete_business(A, request=_req(L.mint(USER, L.SCOPE_DANGER, A)["token"]),
                                         user=OWNER_USER))
    assert out["deleted_business"] == A and gone == [A]


def test_deleting_an_account_takes_it_for_a_business_the_person_owns(deleting, monkeypatch):
    al, gone = deleting
    elsewhere = "0c0c0c0c-0000-4000-8000-00000000000c"          # not one of theirs
    for token in (None, L.mint(USER, L.SCOPE_DANGER, elsewhere)["token"], L.mint(USER, L.SCOPE_DANGER)["token"],
                  L.mint(USER, L.SCOPE_ACCESS, A)["token"]):
        with pytest.raises(HTTPException) as e:
            asyncio.run(al.delete_account(request=_req(token), user=OWNER_USER))
        assert e.value.status_code == 403 and e.value.detail["code"] == "ledger_locked"
    assert gone == [], "nothing is deleted before the password is checked"

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def delete(self, *a, **k):
            return SimpleNamespace(status_code=200)
    monkeypatch.setattr(al.httpx, "AsyncClient", lambda *a, **k: _Client())
    out = asyncio.run(al.delete_account(request=_req(L.mint(USER, L.SCOPE_DANGER, B)["token"]), user=OWNER_USER))
    assert out["account_deleted"] and gone == [A, B]

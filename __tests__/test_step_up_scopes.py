"""
test_step_up_scopes.py — re-proving a password buys ONE kind of action.

WHY SCOPES. The ledger unlock existed first and was a single
undifferentiated grant: fifteen minutes of "this person typed their
password". A practitioner opens their history several times a day, so
that grant is common — and without a scope it would equally have
authorised disconnecting their payouts or deleting the business.

Two very different questions answered by one prompt the practitioner
thought was about something else.

This is the same domain-separation rule the module already applied
between auditor links and unlock tokens: one credential must not
silently become another.

WHAT IS GATED, AND WHAT DELIBERATELY IS NOT. Grants, money and
destruction are gated. REVOKES ARE NOT — revoking a seat, a
collaborator or an auditor link is the emergency brake, and putting a
password prompt in front of the brake is how someone fails to stop
something in time.
"""
import os
import time

import pytest

os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-step-up")

import ledger_unlock as L


class _Req:
    def __init__(self, token=None):
        self.headers = {L.UNLOCK_HEADER: token} if token else {}


# ── the scope wall ──────────────────────────────────────────────────

def test_a_token_only_opens_its_own_scope():
    tok = L.mint("u1", L.SCOPE_DANGER)["token"]
    assert L.verify(tok, "u1", L.SCOPE_DANGER) is True
    assert L.verify(tok, "u1", L.SCOPE_ACCESS) is False
    assert L.verify(tok, "u1", L.SCOPE_LEDGER) is False


def test_a_ledger_unlock_cannot_delete_a_business():
    """The whole reason scopes exist. Reading history is routine;
    it must not carry destruction with it."""
    ledger = L.mint("u1", L.SCOPE_LEDGER)["token"]
    with pytest.raises(Exception) as e:
        L.require_unlock(_Req(ledger), "u1", L.SCOPE_DANGER)
    assert e.value.detail["code"] == "ledger_locked"
    assert e.value.detail["scope"] == L.SCOPE_DANGER


def test_an_access_unlock_cannot_disconnect_payouts():
    access = L.mint("u1", L.SCOPE_ACCESS)["token"]
    with pytest.raises(Exception):
        L.require_unlock(_Req(access), "u1", L.SCOPE_DANGER)


def test_the_right_scope_passes():
    danger = L.mint("u1", L.SCOPE_DANGER)["token"]
    L.require_unlock(_Req(danger), "u1", L.SCOPE_DANGER)   # no raise


# ── the user wall (unchanged, re-pinned) ────────────────────────────

def test_one_users_unlock_is_not_anothers():
    tok = L.mint("u1", L.SCOPE_DANGER)["token"]
    assert L.verify(tok, "u2", L.SCOPE_DANGER) is False


# ── tampering ───────────────────────────────────────────────────────

def test_the_scope_cannot_be_edited_by_the_holder():
    """The scope is inside the signed payload, not beside it. Someone
    who reads their own ledger token out of memory must not be able to
    promote it."""
    import base64, json
    tok = L.mint("u1", L.SCOPE_LEDGER)["token"]
    p, sig = tok.split(".", 1)
    claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    claims["scp"] = L.SCOPE_DANGER
    forged = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    assert L.verify(f"{forged}.{sig}", "u1", L.SCOPE_DANGER) is False


def test_an_unknown_scope_is_refused_at_both_ends():
    with pytest.raises(ValueError):
        L.mint("u1", "whatever")
    with pytest.raises(ValueError):
        L.require_unlock(_Req(), "u1", "whatever")


def test_no_header_is_a_403_not_a_crash():
    with pytest.raises(Exception) as e:
        L.require_unlock(_Req(), "u1", L.SCOPE_ACCESS)
    assert e.value.status_code == 403


def test_expiry_is_enforced(monkeypatch):
    tok = L.mint("u1", L.SCOPE_DANGER)["token"]
    monkeypatch.setattr(time, "time", lambda: time.time() + L.UNLOCK_TTL_SECONDS + 60)
    assert L.verify(tok, "u1", L.SCOPE_DANGER) is False


# ── back-compat, so shipping this does not sign anyone out ──────────

def test_a_pre_scope_token_still_opens_the_ledger():
    """Tokens minted before scopes existed carry no `scp`. They were
    ledger unlocks, because that was the only gate. Reading them as
    anything else would have kicked every practitioner mid-session out
    of a ledger they had just unlocked."""
    import base64, json
    now = int(time.time())
    claims = {"typ": "unlock", "sub": "u1", "iat": now,
              "exp": now + L.UNLOCK_TTL_SECONDS}
    p = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    legacy = f"{p}.{L._sig(p)}"
    assert L.verify(legacy, "u1", L.SCOPE_LEDGER) is True
    assert L.verify(legacy, "u1", L.SCOPE_DANGER) is False, \
        "a legacy token must not inherit the new powers"


# ── what is actually wired ──────────────────────────────────────────

def _routes(module_name, attr="router"):
    import importlib
    mod = importlib.import_module(module_name)
    return {getattr(r, "path", "") for r in getattr(mod, attr).routes}


def test_the_step_up_endpoint_exists():
    assert "/auth/step-up" in _routes("ledger_unlock")


def test_the_gated_endpoints_take_a_request():
    """require_unlock reads a header, so the handler must receive the
    Request. A handler that forgot it would fail at import-time in
    FastAPI — this catches it in CI instead of on the deploy."""
    import inspect
    import account_lifecycle, stripe_connect_router, stripe_billing
    import business_users_router, business_collaborators_router
    gated = [
        (account_lifecycle, "delete_business"),
        (account_lifecycle, "delete_account"),
        (stripe_connect_router, "stripe_connect_disconnect"),
        (stripe_billing, "create_portal"),
        (business_users_router, "invite"),
        (business_collaborators_router, "invite"),
    ]
    for mod, fn in gated:
        sig = inspect.signature(getattr(mod, fn))
        assert "request" in sig.parameters, f"{mod.__name__}.{fn} has no request"


def test_revokes_are_not_gated():
    """The emergency brake keeps no gate. If this ever fails, someone
    added friction to the thing you reach for when access has to stop
    RIGHT NOW."""
    import inspect
    import business_users_router, business_collaborators_router
    for mod, fn in [(business_users_router, "revoke"),
                    (business_collaborators_router, "revoke")]:
        f = getattr(mod, fn, None)
        if f is None:
            continue
        src = inspect.getsource(f)
        assert "require_unlock" not in src, \
            f"{mod.__name__}.{fn} must not require step-up — it REMOVES access"

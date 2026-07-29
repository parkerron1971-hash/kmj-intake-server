"""
test_restricted_role_grants.py — delegating access to a restricted module
without handing over ownership.

restricted_modules._authorize has carried a "25b SEAM" comment since Fork 25
saying the owner check should become a role lookup when multi-staff lands.
Multi-staff landed — business_users.role is viewer/member/manager/admin —
but the seam was never closed, so a church with a bookkeeper still had
exactly one person who could open Giving.

The tests that matter here are the REFUSALS. This path guards the most
confidential data in the system, so the default and every uncertain case
must deny.
"""
from __future__ import annotations

import pytest

import restricted_modules as rm


# ─── role ordering ───────────────────────────────────────────────────

@pytest.mark.parametrize("role,minimum,expected", [
    ("admin",   "member",  True),
    ("admin",   "manager", True),
    ("admin",   "admin",   True),
    ("manager", "member",  True),
    ("manager", "manager", True),
    ("manager", "admin",   False),
    ("member",  "member",  True),
    ("member",  "manager", False),
    ("viewer",  "member",  False),
    ("viewer",  "admin",   False),
])
def test_role_ranking(role, minimum, expected):
    assert rm._role_at_least(role, minimum) is expected


def test_viewer_never_clears_any_configurable_minimum():
    """viewer is the read-only tier and is deliberately not an allowed
    minimum in the migration. It must also never clear one."""
    for minimum in ("member", "manager", "admin"):
        assert rm._role_at_least("viewer", minimum) is False


# ─── the refusals ────────────────────────────────────────────────────

def test_no_role_is_refused():
    """Someone with no row on the business at all."""
    assert rm._role_at_least(None, "member") is False
    assert rm._role_at_least("", "member") is False


def test_unknown_role_is_refused():
    """A role string the ordering does not recognise must deny, not crash
    and not pass. Same default-deny posture as action_registry."""
    assert rm._role_at_least("superuser", "member") is False
    assert rm._role_at_least("owner", "member") is False


def test_unknown_minimum_is_refused():
    """A module configured with a minimum outside the known set — which the
    DB CHECK should prevent, but the code must not depend on that."""
    assert rm._role_at_least("admin", "wizard") is False


# ─── the lookup denies rather than raising ───────────────────────────

class _U:
    id = "user-1"


def test_role_lookup_denies_when_supabase_errors(monkeypatch):
    """A read that blows up must produce a denial, never an accidental
    grant. This guards financial data — failing open is not an option."""
    def boom(*a, **k):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(rm, "_sb", boom)
    assert rm._role_for("biz-1", _U()) is None
    assert rm._role_at_least(rm._role_for("biz-1", _U()), "member") is False


def test_role_lookup_requires_an_ACTIVE_membership(monkeypatch):
    """An invited-but-not-accepted or revoked collaborator holds a role row.
    A row existing is not the same as a person having access, so the query
    must filter status=active."""
    seen = {}

    def fake_sb(method, path, *a, **k):
        seen["path"] = path
        return []

    monkeypatch.setattr(rm, "_sb", fake_sb)
    rm._role_for("biz-1", _U())
    assert "status=eq.active" in seen["path"]
    assert "user_id=eq.user-1" in seen["path"]
    assert "business_id=eq.biz-1" in seen["path"]


def test_role_lookup_returns_the_role(monkeypatch):
    monkeypatch.setattr(rm, "_sb", lambda *a, **k: [{"role": "manager"}])
    assert rm._role_for("biz-1", _U()) == "manager"


# ─── the default is unchanged behaviour ──────────────────────────────

def test_owner_only_is_still_expressible():
    """NULL restricted_min_role means owner-only — the behaviour that
    existed before this change. Applying the migration widened nothing."""
    # An empty/None minimum can never be cleared by any role, which is what
    # makes NULL mean owner-only in _authorize.
    for role in ("viewer", "member", "manager", "admin", None):
        assert rm._role_at_least(role, "") is False

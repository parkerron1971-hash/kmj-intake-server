"""Handlers that take a business id from the caller must check the caller.

    def save(business_id: str, body: dict,
             _: UserSession = Depends(sb_clients.authed_request)):

That authenticates and discards the session. It proves somebody is
signed in and nothing about whose data is being written, and it reads as
guarded because there is a Depends on the line.

WHAT CHANGED, AND WHY IT MATTERED

This file used to carry its own sweep, which asked one question of each
handler: does its own source contain something that looks like a check?
That cannot see a check the handler DELEGATES, and almost every router
here delegates — `_owner(biz, user)` into `_access` into a raise, or
`chief_bookkeeping.owner_business(...)` in another module entirely.

138 handlers were reported as gaps that were already guarded:
reports_router 33 (via _owner_or_reader), rules_router 15, plaid_router
10, quickbooks_router 6, and so on. The true count was 57, not 195.

The damage ran the opposite way to the obvious one. This is a ratchet:
its job is to FAIL when a new unguarded handler ships. Pinned at 203
against a true 57, it had ~146 handlers of slack — that many genuinely
unguarded routes could have landed before it made a sound. A ceiling
measured against noise is not a ceiling.

The sweep now lives in ownership_sweep.py and follows the call graph to
a fixed point, across modules. See that file for why `raise
HTTPException` is required before a helper counts as a gate.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import ownership_sweep

RESULT = ownership_sweep.sweep()
ALL = RESULT["handlers"]
UNGUARDED = RESULT["unguarded"]
RESIDUAL = [h for h in UNGUARDED
            if not h["public_by_design"] and not h["verified_by_hand"]]

# The measured floor, 2026-08-10. Lower it when handlers are fixed;
# never raise it. A rise means a new route ships taking a business id
# from the caller without resolving the caller's relationship to it.
#
# Two numbers, because they mean different things. The residual is the
# one that is a bug list. The total includes surfaces that are anonymous
# on purpose (public sites, public forms, signature-verified webhooks) —
# still worth pinning, so that set cannot grow quietly either.
# 52 -> 46 (2026-08-26): the six SMS practitioner handlers
# (/sms/send, /sms/conversation, /sms/session-reminder,
# /sms/keyword x2, /sms/broadcast) now assert_access. They used to
# sit inside PUBLIC_BY_DESIGN's 'inbound webhooks' entry, which was
# never true of them — the webhooks are in twilio_sms.py. Lowered
# rather than left, because six units of new slack is how a ratchet
# stops ratcheting.
# 46 -> 44 (2026-08-26, billing audit): booking_series' two handlers
# stopped being false positives. They always called
# _require_member_writer -> require_role; the sweep could see through
# neither the function-local import nor the aliased _HTTPException,
# and the module had been parked on PUBLIC_BY_DESIGN to quieten it.
# Both blind spots are fixed, so the entry is gone and the two
# handlers now resolve as what they are: guarded.
MAX_UNGUARDED_TOTAL = 44
MAX_UNGUARDED_RESIDUAL = 0


def _fmt(rows):
    return "\n".join(f"    {h['file']}:{h['line']} {h['fn']}"
                     f"{' [WRITE]' if h['write'] else ''}"
                     for h in sorted(rows, key=lambda h: (not h["write"], h["file"])))


def test_the_sweep_actually_found_routes():
    """Guards the guard: a refactor that broke the AST walk would
    otherwise make this whole file pass by finding nothing."""
    assert len(ALL) > 300, f"only found {len(ALL)} handlers — sweep is broken"


def test_the_sweep_resolves_delegated_checks():
    """The whole point of the rewrite. reports_router delegates every
    check into _owner_or_reader; if that stops resolving, 33 handlers
    reappear as false gaps and the number goes back to meaning nothing."""
    names = {(h["file"], h["fn"]) for h in UNGUARDED}
    assert ("reports_router.py", "pl") not in names
    assert ("contractors_router.py", "list_contractors") not in names, (
        "a two-hop delegation (_owner -> _access -> raise) stopped resolving")
    assert ("chief_bookkeeping_router.py", "analyze_unmatched") not in names, (
        "a CROSS-MODULE delegation stopped resolving")


def test_unguarded_handlers_do_not_increase():
    count = len(UNGUARDED)
    assert count <= MAX_UNGUARDED_TOTAL, (
        f"{count} handlers take a business id without resolving the caller's "
        f"relationship to it (ceiling {MAX_UNGUARDED_TOTAL}).\n"
        f"Use Depends(business_access(...)) — or assert_access(...) when the "
        f"id arrives in a form or body.\nFirst offenders:\n{_fmt(UNGUARDED)[:1200]}")


def test_the_real_gap_list_does_not_increase():
    """Excluding surfaces that are anonymous by design, and the five
    read by hand and found to be scoped on another axis.

    This ceiling is ZERO. Every handler that takes a business id from
    the caller either checks it, is deliberately public, or is written
    down in VERIFIED_BY_HAND with a reason. A new one has nowhere to
    hide."""
    count = len(RESIDUAL)
    assert count <= MAX_UNGUARDED_RESIDUAL, (
        f"{count} non-public handlers take a business id without checking "
        f"the caller (ceiling {MAX_UNGUARDED_RESIDUAL}):\n{_fmt(RESIDUAL)}")


@pytest.mark.parametrize("ceiling,rows,label", [
    (MAX_UNGUARDED_TOTAL, UNGUARDED, "MAX_UNGUARDED_TOTAL"),
    (MAX_UNGUARDED_RESIDUAL, RESIDUAL, "MAX_UNGUARDED_RESIDUAL"),
])
def test_the_ceilings_track_reality(ceiling, rows, label):
    """A ratchet that has gone slack stops ratcheting — which is exactly
    how the old one came to allow 146 new gaps without complaining."""
    slack = ceiling - len(rows)
    assert slack < 10, (
        f"{len(rows)} unguarded vs a ceiling of {ceiling} — "
        f"lower {label} to about {len(rows)}")


def test_the_public_allowlist_does_not_grow_quietly():
    """PUBLIC_BY_DESIGN is where a judgement gets recorded. It is also
    the cheapest possible way to make this test pass while shipping an
    unguarded handler, so its size is pinned too."""
    assert len(ownership_sweep.PUBLIC_BY_DESIGN) <= 15, (
        "the public-by-design allowlist grew — every entry must be a "
        "surface that a stranger is SUPPOSED to reach, not a handler that "
        "was inconvenient to guard")


def test_brand_engine_router_is_fully_guarded():
    """The router the original audit named: 7 endpoints, 6 of them
    writes, every one authenticated-then-discarded."""
    gaps = [h for h in UNGUARDED if h["file"] == "brand_engine_router.py"]
    assert not gaps, f"brand_engine_router still has gaps:\n{_fmt(gaps)}"


class TestTheOwnerGap:
    """A brand-new business has an owner_id and NO business_users row.

    A parallel session hit this exact class on 2026-08-09 (backend #464):
    seat-only RLS policies locked out the owner, because the owner has no
    seat. It breaks 100% of new signups and it looks correct in review —
    every policy present, every role handled, except the one that never
    appears in the table. It is not hypothetical for storage either:
    business_users has zero rows in production today.

    business_access is safe because role_of compares owner_id BEFORE
    looking at business_users. That is an ordering, not a guarantee.
    """

    OWNER = "11111111-1111-1111-1111-111111111111"
    BIZ = "22222222-2222-2222-2222-222222222222"

    @pytest.fixture
    def brand_new_business(self, monkeypatch):
        import sb_clients

        def _get(path):
            if path.startswith("/businesses?"):
                return [{"id": self.BIZ, "owner_id": self.OWNER}]
            if path.startswith("/business_users?"):
                return []          # the gap: no seat row exists yet
            return []

        monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)

    def test_role_of_ranks_the_owner_without_a_seat_row(self, brand_new_business):
        from business_users_router import role_of
        assert role_of(self.BIZ, self.OWNER) == "owner"

    def test_the_owner_passes_the_strictest_gate(self, brand_new_business):
        import business_access

        class _U:
            id = TestTheOwnerGap.OWNER
        assert business_access.assert_access(self.BIZ, _U(), "owner") == "owner"

    def test_a_stranger_is_still_refused(self, brand_new_business):
        """The guard must not have been made permissive to let owners in."""
        import business_access
        from fastapi import HTTPException

        class _S:
            id = "99999999-9999-9999-9999-999999999999"
        with pytest.raises(HTTPException) as e:
            business_access.assert_access(self.BIZ, _S(), "viewer")
        assert e.value.status_code == 404


def test_the_guard_binds_the_jwt_not_just_the_role():
    """business_access depends on authed_request, not require_user.

    authed_request also binds the token to the request contextvar, which
    is what makes brand_engine's helpers forward it to PostgREST. Swap it
    for require_user and those helpers fall through to the SERVICE ROLE —
    the guard would tighten authorization while disabling RLS beneath it.
    """
    import inspect
    import business_access
    src = inspect.getsource(business_access)
    assert "Depends(sb_clients.authed_request)" in src


class TestTheThreeThatWereReal:
    """The gaps the corrected sweep actually found, now closed.

    All three took business_id from a BODY, so they use assert_access
    rather than the dependency — a dependency's parameters resolve from
    the QUERY STRING, and putting business_access on a body route makes
    FastAPI look for a query param that never arrives.
    """

    @pytest.mark.parametrize("module,fn", [
        ("push_notifications", "subscribe"),
        ("contract_agent", "contract_pdf"),
        ("email_sender", "send_email"),
    ])
    def test_it_now_asserts_access(self, module, fn):
        import importlib
        import inspect
        src = inspect.getsource(getattr(importlib.import_module(module), fn))
        assert "assert_access" in src, f"{module}.{fn} lost its ownership check"

    def test_push_subscribe_is_the_one_that_leaked_alerts(self):
        """send_to_business() fans out to every push_subscriptions row
        carrying that business_id, so an unchecked subscribe meant a
        stranger could receive another practitioner's morning brief,
        overdue invoices and session alerts."""
        import inspect
        import push_notifications
        fan = inspect.getsource(push_notifications.send_to_business)
        assert "business_id=eq." in fan
        sub = inspect.getsource(push_notifications.subscribe)
        assert "assert_access" in sub

    def test_the_check_runs_before_the_work(self):
        """A check after the read has already disclosed the row."""
        import inspect
        import contract_agent
        src = inspect.getsource(contract_agent.contract_pdf)
        assert src.index("assert_access") < src.index("/businesses?id=eq.")


def test_the_verified_by_hand_list_does_not_grow_quietly():
    """The other way to make a zero ceiling pass. Every entry is a
    handler someone read and justified; growing it is a decision."""
    import ownership_sweep
    assert len(ownership_sweep.VERIFIED_BY_HAND) <= 5, (
        "VERIFIED_BY_HAND grew — add the ownership check instead, or "
        "explain the new entry the way the existing five are explained")

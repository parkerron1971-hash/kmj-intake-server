"""Handlers that take a business id from the caller must check the caller.

The audit named "37 handlers missing an ownership check". An AST sweep
puts it far higher: 446 handlers accept a client-supplied business id and
roughly half have nothing in the body that resolves ownership or role.
The count is soft — a handler can delegate the check into a helper this
sweep cannot see — but the shape is not: **the check is something you
have to remember to write**, and the pattern that omits it is invisible
on review:

    def save(business_id: str, body: dict,
             _: UserSession = Depends(sb_clients.authed_request)):

That authenticates and discards the session. It proves somebody is
signed in and nothing about whose data is being written, and it reads as
guarded because there is a Depends on the line.

So this file is a ratchet, not a wall. It pins the current number and
fails if it grows. Fixing all of them is a migration; letting it get
worse while that happens is the thing worth preventing.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Anything in a handler body that plausibly resolves who the caller is
# relative to the business. Deliberately generous: a false "covered" is
# a missed gap, but a false "gap" makes the ratchet noisy and it gets
# raised to shut it up, which is worse.
COVER_HINTS = (
    "business_access", "assert_access", "_require_owner", "require_owner",
    "_access(", "require_role", "role_of", "require_business_admin",
    "owner_id", "_assert_owner", "_require_business", "_require_membership",
    "authed_request",  # binds the JWT so RLS scopes the query itself
)

BIZ_PARAMS = ("business_id", "biz", "biz_id", "businessId")

# The measured floor. Lower it when handlers are fixed; never raise it.
# A rise means a new route shipped taking a business id from the caller
# without resolving the caller's relationship to it.
MAX_UNGUARDED = 203


def _handlers():
    for path in sorted(ROOT.rglob("*.py")):
        s = str(path)
        if "__pycache__" in s or "__tests__" in s or "site-packages" in s:
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods = []
            for d in node.decorator_list:
                f = d.func if isinstance(d, ast.Call) else d
                if isinstance(f, ast.Attribute) and f.attr in (
                        "get", "post", "put", "patch", "delete"):
                    methods.append(f.attr)
            if not methods:
                continue
            body = ast.get_source_segment(src, node) or ""
            args = ([a.arg for a in node.args.args]
                    + [a.arg for a in node.args.kwonlyargs])
            takes_biz = any(a in BIZ_PARAMS for a in args) or bool(
                re.search(r"\.business_id\b|\[[\"']business_id[\"']\]", body))
            if not takes_biz:
                continue
            yield {
                "file": path.name, "fn": node.name, "line": node.lineno,
                "write": any(m in ("post", "put", "patch", "delete")
                             for m in methods),
                "covered": any(h in body for h in COVER_HINTS),
            }


ALL = list(_handlers())
UNGUARDED = [h for h in ALL if not h["covered"]]


def test_the_sweep_actually_found_routes():
    """Guards the guard: a refactor that breaks the AST walk would
    otherwise make this whole file pass by finding nothing."""
    assert len(ALL) > 300, f"only found {len(ALL)} handlers — sweep is broken"


def test_unguarded_handlers_do_not_increase():
    count = len(UNGUARDED)
    worst = "\n".join(
        f"    {h['file']}:{h['line']} {h['fn']}"
        for h in sorted(UNGUARDED, key=lambda h: (not h["write"], h["file"]))[:15])
    assert count <= MAX_UNGUARDED, (
        f"{count} handlers take a business id without resolving the caller's "
        f"relationship to it (ceiling {MAX_UNGUARDED}).\n"
        f"Use Depends(business_access(...)) — or assert_access(...) when the "
        f"id arrives in a form or body.\nFirst offenders:\n{worst}")


def test_the_ceiling_tracks_reality():
    """If the real number drops well below the ceiling, lower it — a
    ratchet that has gone slack stops ratcheting."""
    slack = MAX_UNGUARDED - len(UNGUARDED)
    assert slack < 25, (
        f"{len(UNGUARDED)} unguarded vs a ceiling of {MAX_UNGUARDED} — "
        f"lower MAX_UNGUARDED to about {len(UNGUARDED) + 5}")


def test_brand_engine_router_is_fully_guarded():
    """The router the audit named: 7 endpoints, 6 of them writes, and
    every one authenticated-then-discarded."""
    gaps = [h for h in UNGUARDED if h["file"] == "brand_engine_router.py"]
    assert not gaps, f"brand_engine_router still has gaps: {gaps}"


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

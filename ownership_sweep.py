"""ownership_sweep.py — which handlers take a business id without checking it?

This is the measurement behind the business_access ratchet. It lives in
the tree rather than inside the test because the number it produces is
the thing the test pins, and a number nobody can reproduce outside CI is
hard to argue with.

WHY IT WAS REWRITTEN

The first version asked one question of each handler: does its own source
contain something that looks like an ownership check? That is easy to
implement and wrong in a specific, expensive way — it cannot see a check
the handler DELEGATES. Almost every router in this codebase delegates:

    def list_contractors(biz, user = Depends(require_user)):
        _owner(biz, user)          # -> _access(...) -> raises
        ...

    def analyze_unmatched(business_id, user = Depends(require_user)):
        chief_bookkeeping.owner_business(business_id, user.id)

Neither handler body contains a hint string, so both were counted
unguarded. Across the repo that was 138 handlers reported as gaps that
were already guarded — reports_router (33, via _owner_or_reader),
rules_router (15), plaid_router (10), quickbooks_router (6) and so on.

That mattered in the direction people do not expect. The ratchet's job is
to fail when a NEW unguarded handler ships. Pinned at 203 while the true
number was 57, it had roughly 146 handlers of slack: someone could add
that many genuinely unguarded routes before it made a sound. A ceiling
measured against noise is not a ceiling.

HOW IT WORKS NOW

A function is a GATE if it refuses — `raise HTTPException` — and consults
ownership (one of the hint strings). Gate-ness then propagates along the
call graph to a fixed point, ACROSS modules as well as within them, so
`_owner` -> `_access` -> raise, and `router` -> `chief_bookkeeping.owner_business`,
both resolve. A handler is covered if its own body checks, or it calls
anything that is transitively a gate.

Deliberately conservative in two places:

  * `raise HTTPException` is required. A helper that merely READS
    owner_id and returns it is not a gate — it is a fetch. Without that
    condition another 20 handlers "resolve" to helpers that never refuse.
  * Only calls to plain names and `module.attr` are followed. A gate
    reached through a variable, a dict of callables, or a decorator is
    not seen, so this still UNDER-counts coverage. Under-counting
    coverage is the safe direction: it reports a gap that is not there,
    rather than missing one that is.
"""
from __future__ import annotations

import ast
import pathlib
import re
from typing import Any, Dict, List, Set, Tuple

ROOT = pathlib.Path(__file__).resolve().parent

# Anything that plausibly resolves who the caller is relative to a
# business. Deliberately generous — this is only half the test; the
# other half is that the function containing it also refuses.
HINTS = (
    "business_access", "assert_access", "_require_owner", "require_owner",
    "_access(", "require_role", "role_of", "require_business_admin",
    "owner_id", "_assert_owner", "_require_business", "_require_membership",
    "owner_business",
    "authed_request",  # binds the JWT so RLS scopes the query itself
    "set_user_jwt",    # the same thing, called directly (chief_of_staff)
)

BIZ_PARAMS = ("business_id", "biz", "biz_id", "businessId")

METHODS = ("get", "post", "put", "patch", "delete")

# Surfaces that are anonymous ON PURPOSE, and would be broken by an
# ownership check rather than improved by one. Each is a decision:
#
#   public_site, site_composer, site_concierge, store_router, store_files
#       the customer-facing website and storefront. Their whole job is to
#       serve a stranger who has never signed in.
#   booking_widget_router, booking_series, events_rsvp_router, giving_router,
#   intake_endpoint
#       public forms. A client booking an appointment or giving to a
#       church has no account and should not need one.
#   stripe_proxy, stripe_payments_router
#       inbound webhooks. Authenticated by SIGNATURE, not by session —
#       see webhook_guard. A session check here would reject Stripe.
#
#       sms_service and sms_routing USED TO SIT ON THIS LINE, and did not
#       belong on it. SMS's inbound webhooks live in twilio_sms.py, which
#       is signature-validated and takes no business id from the caller;
#       these two modules hold the PRACTITIONER endpoints — /sms/send,
#       /sms/conversation, /sms/session-reminder, /sms/keyword,
#       /sms/broadcast. Every one of them read business_id out of the
#       request and trusted it, and the exemption is why nothing said so
#       for a year. An entry here is a judgement about a module, and a
#       module is the wrong unit when one file holds both a webhook and a
#       session endpoint. Removed 2026-08-26; all six now assert_access.
#   meta_oauth
#       the OAuth redirect. It cannot carry a bearer token, which is the
#       entire reason the connect TICKET exists (#468).
#
# This list is a place to record a judgement, not a place to hide a
# handler. It is pinned by its own test.
PUBLIC_BY_DESIGN = frozenset({
    "public_site", "site_composer", "site_concierge",
    "store_router", "store_files",
    "booking_widget_router", "booking_series",
    "events_rsvp_router", "giving_router", "intake_endpoint",
    "stripe_proxy", "stripe_payments_router",
    "meta_oauth",
})


# Handlers that take a business id, are NOT a public surface, and still
# do not resolve ownership against it — because they are scoped on a
# different axis that this sweep cannot express. Each was read by hand.
# This is a list of judgements, not a snooze button, and its size is
# pinned by a test.
#
#   chief_jobs.list_jobs / retry_job
#       scoped by USER, not business: every query carries
#       user_id=eq.<session uid>, and retry re-reads the job under that
#       filter before re-queueing. business_id is an optional narrowing
#       filter on top of an already-scoped set.
#
#   whisper_proxy.text_to_speech
#       auth is optional BY DESIGN — OpenAI voices work for anyone and
#       never touch business data. The premium ElevenLabs path does check,
#       via _owns_business(), which returns a bool instead of raising, so
#       the gate rule cannot see it. Every deny falls back to OpenAI.
#
#   auditor_portal.auditor_navigate
#       built for a reader with a link and no account. It also never sees
#       a row: the model receives the question and a verb vocabulary and
#       returns a FILTER.
#
#   vertical_intelligence_router.get_vertical
#       a public read of the terminology dictionary ("Clients" vs
#       "Members"). business_id only selects which overrides to apply to
#       a vocabulary the frontend renders publicly anyway.
VERIFIED_BY_HAND = frozenset({
    ("chief_jobs", "list_jobs"),
    ("chief_jobs", "retry_job"),
    ("whisper_proxy", "text_to_speech"),
    ("auditor_portal", "auditor_navigate"),
    ("vertical_intelligence_router", "get_vertical"),
})


def _source_files():
    for path in sorted(ROOT.rglob("*.py")):
        s = str(path)
        if "__pycache__" in s or "__tests__" in s or "site-packages" in s:
            continue
        # SKIP DOT-DIRECTORIES, and why it is not housekeeping.
        #
        # rglob walked everything, so any stray copy of the tree — a
        # worktree-context snapshot, a vendored checkout, a backup —
        # produced a SECOND module under the same name, and the duplicate
        # won. This was found the hard way: a real ownership fix landed on
        # sms_service.py and the sweep kept reporting the handler
        # unguarded, because it was reading a months-old copy of that file
        # out of an untracked .claude-wt-ctx/ directory.
        #
        # A ratchet that can be computed against files which are not the
        # repository reports a number for something nobody is shipping,
        # and it fails in the dangerous direction: it hides a fix, so the
        # next person concludes the guard does not work and takes it out.
        if any(part.startswith(".") and part not in (".", "..")
               for part in path.relative_to(ROOT).parts[:-1]):
            continue
        yield path


def _calls_of(node: ast.AST) -> Set[Tuple[str, str]]:
    """Calls made inside a function, as ('*', name) or ('module', attr)."""
    out: Set[Tuple[str, str]] = set()
    for c in ast.walk(node):
        if not isinstance(c, ast.Call):
            continue
        if isinstance(c.func, ast.Name):
            out.add(("*", c.func.id))
        elif isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name):
            out.add((c.func.value.id, c.func.attr))
    return out


def sweep() -> Dict[str, Any]:
    """Returns {'handlers': [...], 'unguarded': [...], 'modules': n}."""
    mods: Dict[str, Dict[str, Tuple[str, Set[Tuple[str, str]]]]] = {}
    handlers: List[Dict[str, Any]] = []

    for path in _source_files():
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except Exception:
            continue
        stem = path.stem
        fns = mods.setdefault(stem, {})
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(src, node) or ""
            calls = _calls_of(node)
            # First definition wins: a later same-named function must not
            # clobber the one a handler was recorded against.
            fns.setdefault(node.name, (body, calls))

            deco = [(d.func if isinstance(d, ast.Call) else d)
                    for d in node.decorator_list]
            methods = [d.attr for d in deco
                       if isinstance(d, ast.Attribute) and d.attr in METHODS]
            if not methods:
                continue
            args = ([a.arg for a in node.args.args]
                    + [a.arg for a in node.args.kwonlyargs])
            takes_biz = any(a in BIZ_PARAMS for a in args) or bool(
                re.search(r"\.business_id\b|\[[\"']business_id[\"']\]", body))
            if not takes_biz:
                continue
            handlers.append({
                "module": stem, "fn": node.name, "file": path.name,
                "line": node.lineno, "body": body, "calls": calls,
                "write": any(m in ("post", "put", "patch", "delete")
                             for m in methods),
                "public_by_design": stem in PUBLIC_BY_DESIGN,
                "verified_by_hand": (stem, node.name) in VERIFIED_BY_HAND,
            })

    # A gate refuses AND consults ownership.
    gate: Dict[Tuple[str, str], bool] = {
        (m, n): bool(re.search(r"raise\s+HTTPException", b))
                and any(h in b for h in HINTS)
        for m, fns in mods.items() for n, (b, _) in fns.items()
    }

    def resolve(mod: str, call: Tuple[str, str]):
        who, fn = call
        if who == "*":
            return (mod, fn) if fn in mods.get(mod, {}) else None
        return (who, fn) if fn in mods.get(who, {}) else None

    changed = True
    while changed:                       # fixed point over the call graph
        changed = False
        for m, fns in mods.items():
            for n, (_b, calls) in fns.items():
                if gate.get((m, n)):
                    continue
                for c in calls:
                    t = resolve(m, c)
                    if t and gate.get(t):
                        gate[(m, n)] = True
                        changed = True
                        break

    unguarded = []
    for h in handlers:
        if any(hint in h["body"] for hint in HINTS):
            continue
        if any(gate.get(resolve(h["module"], c)) for c in h["calls"]
               if resolve(h["module"], c)):
            continue
        unguarded.append(h)

    return {"handlers": handlers, "unguarded": unguarded, "modules": len(mods)}

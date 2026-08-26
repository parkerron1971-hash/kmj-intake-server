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
#   booking_widget_router, events_rsvp_router, giving_router,
#   intake_endpoint
#       public forms. A client booking an appointment or giving to a
#       church has no account and should not need one.
#
#       booking_series USED TO BE ON THIS LINE and never belonged: both
#       its handlers call _require_member_writer -> require_role, and a
#       recurring series is a practitioner action, not a public form. It
#       was here to silence a FALSE positive — require_role raises an
#       aliased _HTTPException through a function-local import, and the
#       sweep could see through neither. Both are fixed above, so the
#       entry is gone. A false positive absorbed into this list costs
#       more than the noise it hides: the list stops reading as a set of
#       judgements, and the next REAL gap in that module is invisible.
#   stripe_proxy, stripe_payments_router — NAMED HANDLERS ONLY
#       These were whole-module entries under the same "inbound webhooks"
#       claim, and the claim is no more true of them than it was of SMS.
#       /stripe/webhook IS a webhook and verifies its signature (fails
#       closed on a missing secret). Everything else in those two files is
#       a session endpoint, and the money-moving ones — create-payment-link,
#       product-link, invoice-checkout, charge-no-show, refund — already
#       carry _require_owner. A blanket over the module said nothing about
#       any of that and would have swallowed the next handler added to it.
#       So the exemption is now per-handler, and it is three:
#
#         stripe_payments_router.booking_checkout
#             a customer paying for their own booking, from the wizard or
#             an email button, with no account. The amount is derived
#             server-side from the booking row — the caller cannot
#             influence it.
#         stripe_proxy.payments_connect
#             answers from the payments_core registry. Static copy about
#             which providers are connectable; reaches no database.
#         stripe_proxy.payments_providers
#             the render-time provider read a storefront needs before a
#             visitor has signed in to anything. It stays anonymous, and
#             it no longer answers with connect_account_id /
#             oauth_merchant_id — see the note on the handler. Nothing
#             deciding whether to draw a Buy button needs a merchant id,
#             and business ids are public (they ride in the intake embed
#             snippet), so anything this returns is returned to everyone.
#             payments_callback needs no entry: it takes no business id,
#             so the sweep never asks about it.
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
    "booking_widget_router",
    "events_rsvp_router", "giving_router", "intake_endpoint",
    "meta_oauth",
    # Per-handler entries. A module name here exempts the whole file; a
    # (module, handler) pair exempts exactly one door. Reach for the pair
    # whenever a file mixes public and session endpoints — which is the
    # shape that hid six unguarded SMS handlers for a year.
    ("stripe_payments_router", "booking_checkout"),
    ("stripe_proxy", "payments_connect"),
    ("stripe_proxy", "payments_providers"),
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


def _imported_names(tree: ast.AST) -> Dict[str, str]:
    """`from X import Y` bindings in a module, INCLUDING function-local
    ones, as {bound_name: source_module_stem}.

    WHY THIS EXISTS. Gate-ness propagates along the call graph, and a
    plain-name call used to resolve only against functions defined in the
    SAME module. That is wrong for this codebase's dominant shape:

        def _require_member_writer(business_id, user):
            from business_users_router import require_role   # local import
            return require_role(business_id, str(user.id), "member")

    `require_role` is a real gate in another module, and the call is a
    bare Name, so the link was lost and both /series handlers were
    reported unguarded. They are not — and somebody silenced that by
    putting `booking_series` on PUBLIC_BY_DESIGN under "public forms",
    which it is not. A false positive absorbed into the exemption list
    costs more than the noise: the list stops being readable as a set of
    judgements, and the next real gap in that module is invisible.

    Only EXPLICIT `from X import Y` is followed. A name reached through a
    variable, a dict of callables or a decorator is still not seen, so
    this remains an under-count of coverage — the safe direction.
    """
    out: Dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and not n.level:
            src = n.module.split(".")[-1]
            for a in n.names:
                if a.name != "*":
                    out[a.asname or a.name] = src
    return out


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
    imported: Dict[str, Dict[str, str]] = {}
    handlers: List[Dict[str, Any]] = []

    for path in _source_files():
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except Exception:
            continue
        stem = path.stem
        fns = mods.setdefault(stem, {})
        imported.setdefault(stem, {}).update(_imported_names(tree))
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
                "public_by_design": (stem in PUBLIC_BY_DESIGN
                                     or (stem, node.name) in PUBLIC_BY_DESIGN),
                "verified_by_hand": (stem, node.name) in VERIFIED_BY_HAND,
            })

    # A gate refuses AND consults ownership.
    # `raise <anything>HTTPException` — dotted or aliased.
    #
    # The pattern was `raise\s+HTTPException`, which missed
    # `business_users_router.require_role`:
    #
    #     from fastapi import HTTPException as _HTTPException
    #     ...
    #     raise _HTTPException(403, f"requires {min_role} access or above")
    #
    # That function is the SHARED ROLE LADDER — the gate a whole family of
    # handlers delegates to — so one alias made every one of them look
    # unguarded. It still has to be a literal raise of something named
    # HTTPException; this widens the spelling, not the rule.
    _RAISES = re.compile(r"raise\s+[\w.]*HTTPException")
    gate: Dict[Tuple[str, str], bool] = {
        (m, n): bool(_RAISES.search(b)) and any(h in b for h in HINTS)
        for m, fns in mods.items() for n, (b, _) in fns.items()
    }

    def resolve(mod: str, call: Tuple[str, str]):
        who, fn = call
        if who == "*":
            if fn in mods.get(mod, {}):
                return (mod, fn)
            # Not local — follow an explicit `from X import fn`.
            src = imported.get(mod, {}).get(fn)
            return (src, fn) if src and fn in mods.get(src, {}) else None
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

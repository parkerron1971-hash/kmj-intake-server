"""The billing surface, and the checker that was supposed to be watching it.

WHAT THE AUDIT FOUND
  The money endpoints are in good shape and this file pins that: every
  handler that moves money resolves the caller against the business
  first, and the Stripe webhook fails closed without its secret. That was
  already true — these tests exist so it stays true.

  What was NOT in good shape was the exemption that covered them.
  `ownership_sweep.PUBLIC_BY_DESIGN` listed `stripe_proxy` and
  `stripe_payments_router` whole, under "inbound webhooks. Authenticated
  by SIGNATURE, not by session." One handler in those two files is a
  webhook. The rest are session endpoints, four of them money-moving. The
  blanket said nothing true about any of them and would have swallowed
  the next handler added to either file — which is exactly how six SMS
  handlers stayed unguarded for a year behind the same sentence.

  So the list now takes (module, handler) pairs, and the three genuinely
  anonymous doors are named one by one.

AND TWO BLIND SPOTS IN THE SWEEP ITSELF
  `require_role` — the shared role ladder a whole family of handlers
  delegates to — raises an ALIASED `_HTTPException` imported inside the
  function body. The gate test matched `raise HTTPException` literally,
  and plain-name calls resolved only within the defining module. So every
  handler guarded through that ladder read as unguarded, and
  `booking_series` had been parked on PUBLIC_BY_DESIGN to quieten it.
  Both are fixed; the parking space is gone.
"""
from __future__ import annotations

import inspect
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import ownership_sweep
import stripe_payments_router
import stripe_proxy

# Handlers that move money or mint a way to take it. Each must resolve the
# caller's relationship to the business BEFORE it reaches Stripe.
MONEY = [
    (stripe_proxy, "create_payment_link"),
    (stripe_proxy, "create_product_payment_link"),
    (stripe_payments_router, "invoice_checkout"),
    (stripe_payments_router, "charge_no_show"),
    (stripe_payments_router, "refund_charge"),
]


@pytest.mark.parametrize("mod,fn", MONEY,
                         ids=[f"{m.__name__}.{f}" for m, f in MONEY])
def test_money_handlers_resolve_the_caller_against_the_business(mod, fn):
    src = inspect.getsource(getattr(mod, fn))
    assert re.search(r"_require_owner|assert_access|require_role", src), (
        f"{mod.__name__}.{fn} moves money and does not check the caller")


@pytest.mark.parametrize("mod,fn", MONEY,
                         ids=[f"{m.__name__}.{f}" for m, f in MONEY])
def test_the_check_runs_before_stripe_is_reached(mod, fn):
    """A gate below the charge is not a gate.

    create_payment_link's own comment makes the point: an unauthorized
    request must not fall through to the platform account, because that
    turns a refusal into a successful charge on the wrong books."""
    src = inspect.getsource(getattr(mod, fn))
    gate = min(i for i in (src.find("_require_owner"), src.find("assert_access"),
                           src.find("require_role")) if i != -1)
    for marker in ("stripe.", "_create_stripe_payment_link(",
                   "checkout.Session", "Refund.create"):
        at = src.find(marker)
        if at != -1:
            assert gate < at, f"{mod.__name__}.{fn}: check runs after {marker}"


def test_the_stripe_webhook_fails_closed_without_its_secret():
    src = inspect.getsource(stripe_proxy.stripe_webhook)
    assert "_verify_stripe_signature" in src
    assert re.search(r"if not _wh_secret", src), (
        "a missing secret must reject the event, not skip verification")


# ─── the anonymous doors, named one by one ────────────────────────────

def test_booking_checkout_derives_the_amount_itself():
    """It is anonymous BECAUSE the caller cannot influence what is
    charged — the booking is loaded server-side and the amount comes off
    that row. That property is what makes the exemption safe, so it is
    the property under test."""
    src = inspect.getsource(stripe_payments_router.booking_checkout)
    assert "sb_get_as_service" in src
    assert "booking_id" in src
    body = src.split('"""', 2)[-1]
    assert not re.search(r"body\.(amount|price|total)", body), (
        "an anonymous checkout must never take the amount from the caller")


def test_the_anonymous_provider_read_returns_no_merchant_identifiers():
    """It has no auth, takes a business id from the caller, and reads
    settings with the SERVICE ROLE key — so whatever it returns, it
    returns to anyone who can name a business. Business ids are not
    secret: they ride in the intake-form embed snippet.

    `connect_account_id` and `oauth_merchant_id` turned a render hint
    into an enumerable directory of the platform's merchant accounts.
    Nothing that decides whether to draw a Buy button needs one."""
    src = inspect.getsource(stripe_proxy.payments_providers)
    payload = src.split("out[pid] = {", 1)[1]
    for leaked in ('"connect_account_id":', '"oauth_merchant_id":'):
        assert leaked not in payload, f"{leaked} is back in the response"
    assert '"connected"' in payload, (
        "the renderer still needs to know whether a provider is hooked up")


# ─── the exemption list is a set of judgements, not a hiding place ────

STRIPE_PUBLIC = {
    ("stripe_payments_router", "booking_checkout"),
    ("stripe_proxy", "payments_connect"),
    ("stripe_proxy", "payments_providers"),
}


def test_the_stripe_modules_are_no_longer_blanket_exempt():
    for mod in ("stripe_proxy", "stripe_payments_router"):
        assert mod not in ownership_sweep.PUBLIC_BY_DESIGN, (
            f"{mod} is exempt as a whole module again — it holds session "
            f"endpoints, and a blanket over it hides the next one added")


def test_exactly_the_three_anonymous_stripe_doors_are_exempt():
    got = {e for e in ownership_sweep.PUBLIC_BY_DESIGN
           if isinstance(e, tuple) and e[0].startswith("stripe")}
    assert got == STRIPE_PUBLIC


def test_a_new_unguarded_stripe_handler_would_be_reported():
    """The property the narrowing buys. Under the old blanket every
    handler in these two files was invisible; now only the three named
    ones are."""
    rows = ownership_sweep.sweep()["unguarded"]
    flagged = {(r["module"], r["fn"]) for r in rows
               if r["module"].startswith("stripe")}
    assert flagged <= STRIPE_PUBLIC, (
        f"unexpected unguarded stripe handlers: {sorted(flagged - STRIPE_PUBLIC)}")
    for r in rows:
        if (r["module"], r["fn"]) in STRIPE_PUBLIC:
            assert r["public_by_design"], (
                f"{r['module']}.{r['fn']} is declared but not recognised — "
                f"the per-handler form of the exemption stopped working")


def test_booking_series_is_not_parked_on_the_exemption_list():
    """Both its handlers call _require_member_writer. It was on the list
    to silence a false positive, described as a "public form" — which a
    recurring practitioner booking is not."""
    assert "booking_series" not in ownership_sweep.PUBLIC_BY_DESIGN


# ─── the sweep's two blind spots ──────────────────────────────────────

def test_an_aliased_http_exception_still_counts_as_refusing():
    """business_users_router.require_role is THE shared role ladder and
    raises `_HTTPException`. Matching the literal name missed it, so
    every handler delegating to it read as unguarded."""
    import business_users_router
    src = inspect.getsource(business_users_router.require_role)
    assert "raise _HTTPException" in src, (
        "fixture drift — this test is about the aliased spelling")
    rows = ownership_sweep.sweep()["unguarded"]
    delegating = [r for r in rows
                  if "require_role" in r["body"] and not r["public_by_design"]]
    assert not delegating, (
        f"handlers guarded through require_role reported unguarded: "
        f"{[(r['module'], r['fn']) for r in delegating]}")


def test_a_function_local_import_still_resolves_across_modules():
    """The dominant shape in this codebase:

        def _require_member_writer(business_id, user):
            from business_users_router import require_role
            return require_role(...)

    A bare Name call used to resolve only inside its own module, so the
    link to the real gate was lost."""
    import booking_series
    src = inspect.getsource(booking_series._require_member_writer)
    assert "from business_users_router import require_role" in src, (
        "fixture drift — this test is about the function-local import")
    rows = ownership_sweep.sweep()["unguarded"]
    assert not [r for r in rows if r["module"] == "booking_series"]


def test_only_explicit_from_imports_are_followed():
    """The resolver stays conservative on purpose. A name reached through
    a variable, a dict of callables or a decorator is still invisible, so
    the sweep keeps UNDER-counting coverage — the safe direction."""
    src = inspect.getsource(ownership_sweep._imported_names)
    assert "ast.ImportFrom" in src
    assert "ast.Import)" not in src, "plain `import X` binds a module, not a name"


def test_the_exemption_list_stays_readable():
    """A list that grows without argument is a list nobody reads. Modules
    and pairs are counted together — the cap is on judgements, not rows."""
    assert len(ownership_sweep.PUBLIC_BY_DESIGN) <= 15

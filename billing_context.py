"""
billing_context.py — whose bill is this AI call on?

Every paid Anthropic call should land on an api_usage row naming the
business it was spent for. 42 of the 49 direct log_api_usage call sites
already pass one. The gap is llm_call._meter: ONE call site, standing in
for 22 modules that reach the seam and never metered themselves —
brand_engine, growth_engine, discovery, foundation_agent, contract_agent,
module_spec_generator, site_llm, studio_designer_agent and the rest.

The seam cannot pass a business id because it does not have one. It sees
an HTTP payload and a caller module name; the business was decided
several frames up, by a request handler or a scheduled job iterating
tenants. Threading a parameter down through every one of those call
chains is a large change that every future caller then has to remember
to repeat — which is the same shape as the bug it would be fixing.

So the business travels out-of-band, in a ContextVar, the way the
request JWT already does (sb_clients.authed_request). Anything that
knows which tenant it is working for declares it once; anything that
bills reads it without being told.

    with billing_context.bill_to(business_id):
        ...                      # any AI call in here is attributed

Two properties make this safe to default on:

  * A ContextVar is per-task. Concurrent requests for different
    businesses cannot read each other's value, and an async task
    inherits the context it was created in.
  * It only ever supplies a DEFAULT. An explicit business_id passed to
    log_api_usage always wins, so the 42 correct call sites are
    unaffected.

What this deliberately does NOT do is decide anything. It is
bookkeeping, not authorization — being "in" a business's billing context
grants no access to it. The ownership check is business_access, and it
runs first.
"""
from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from typing import Iterator, Optional

logger = logging.getLogger("billing_context")

_CURRENT: ContextVar[Optional[str]] = ContextVar(
    "billing_business_id", default=None)


def current() -> Optional[str]:
    """The business this task's AI spend belongs to, or None."""
    try:
        return _CURRENT.get()
    except Exception:          # pragma: no cover - defensive
        return None


def set_current(business_id: Optional[str]) -> None:
    """Declare the billing tenant for the rest of this task.

    No reset token is returned — this is the request-scoped form, for a
    dependency or handler that owns the whole task. Use bill_to() when
    the scope is a block inside a longer-lived task, such as a scheduled
    job looping over tenants; leaking one business's id into the next
    iteration would misattribute real money.
    """
    if not business_id:
        return
    try:
        _CURRENT.set(str(business_id))
    except Exception as e:     # pragma: no cover - defensive
        logger.warning("[billing] could not set context: %s", e)


@contextlib.contextmanager
def bill_to(business_id: Optional[str]) -> Iterator[None]:
    """Scope AI spend to one business, restoring the previous value.

    Never raises: attribution failing must not fail the work being
    attributed. A missing business_id is a no-op rather than an error —
    plenty of legitimate calls (platform-level jobs, health checks) have
    no tenant, and they should stay unattributed rather than borrow one.
    """
    if not business_id:
        yield
        return
    token = None
    try:
        token = _CURRENT.set(str(business_id))
    except Exception as e:     # pragma: no cover - defensive
        logger.warning("[billing] could not enter context: %s", e)
    try:
        yield
    finally:
        if token is not None:
            try:
                _CURRENT.reset(token)
            except Exception:  # pragma: no cover - defensive
                pass

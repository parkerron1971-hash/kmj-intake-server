"""
first_run_arc.py — Chief's first seven days: the row that remembers.

A trial is the one week where the practitioner is still deciding whether
any of this is real, and until now nothing in the system knew it had
started. The Stripe webhook wrote `trial_ends_at` and stopped there; no
code reacted to a subscription entering `trialing`. This module is that
missing event, and the memory that hangs off it.

ONE ROW PER BUSINESS, OPENED BY WHICHEVER DOOR THEY CAME THROUGH

  · `subscription` — a Stripe subscription entered `trialing`. For
    anyone who pays, this is the real start, and it fires while they are
    ALREADY standing in the workspace: business creation runs during
    signup, checkout runs later from the paywall.
  · `signup` — business creation. Comped, invited and grandfathered
    accounts never reach Stripe, and an arc that only ever opened from a
    webhook would silently skip every one of them.

begin() is idempotent: one row per business, guaranteed by a unique
index, so the two doors can race and only one arc exists.

WHEN DAY ONE IS ALLOWED TO MOVE, AND WHEN IT IS NOT
Signup almost always fires FIRST in the self-serve flow — the business is
created during onboarding, and checkout happens minutes later from the
paywall. If the first door simply won outright, day one would be pegged
to signup, which is right by two minutes for most people and badly wrong
for the person who signs up, wanders off, and subscribes three weeks
later. Their trial starts the day they subscribe; being told it is day 22
of their first week would be nonsense.

So the rule is narrower than "first door wins":

  · The subscription door may re-stamp `started_at` to the real trial
    start — but only ONCE, and only while `intro_delivered_at` is still
    null. `source` is the latch: it flips signup -> subscription in the
    same write, and an already-subscription-anchored arc is never
    re-stamped. This is not hypothetical tidiness — Stripe sends
    `customer.subscription.updated` with status `trialing` for any change
    during a trial, so without the latch a plan tweak on day three would
    quietly move them back to day one.
  · Once Chief has introduced herself, `started_at` is frozen outright. A
    re-subscribe, a plan change, an out-of-order `updated` before
    `created`, or a replayed webhook can never restart someone's week or
    replay an introduction they have already had.
  · The signup door never moves anything that already exists.

A later call may also fill in a `trial_ends_at` the first call could not
know, which is exactly the signup-then-subscribe order.

WHY THE START DATE IS STAMPED AND NOT DERIVED
usage_metering.trial_window_start() derives the trial's first instant by
subtracting the configured length from `trial_ends_at`, and documents
that it moves if the dial moves. Correct for a credit tank, which is a
budget. Wrong for a narrative: "which day of your week is this" must not
shift under someone because BILLING_TRIAL_DAYS changed on a Thursday.

NOTHING HERE RAISES. Both callers sit on paths where failing loudly costs
something real — a Stripe webhook and business creation — and a missing
day-one arc is a worse product, not a broken one. Every function returns
None / 0 on failure and logs it.

All access is service-role: the table is RLS-on with no policies, on
purpose (see supabase/APPLY-2026-08-28-first-run-arc.sql).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import sb_clients

logger = logging.getLogger("first_run_arc")

# The two doors. Anything else is a caller bug, refused rather than
# stored — the column has the same CHECK, and a 400 from PostgREST is a
# worse way to find out.
SOURCES = ("subscription", "signup")

_SELECT = ("id,business_id,source,started_at,trial_ends_at,status,"
           "intro_delivered_at,completed_steps,shared_links,"
           "last_beat_day,last_beat_at")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse(ts: Any) -> Optional[datetime]:
    """Postgres timestamptz -> aware datetime. None when it can't be read
    — callers treat that as 'don't know', never as 'epoch'."""
    s = str(ts or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def state(business_id: Any) -> Optional[Dict[str, Any]]:
    """This business's arc row, or None.

    None means BOTH "no arc" and "the read failed", deliberately: the
    only thing any caller does with this is decide whether there is an
    arc to act on, and a failed read must produce the quiet answer rather
    than a half-arc.
    """
    biz = str(business_id or "").strip()
    if not biz:
        return None
    try:
        rows = sb_clients.sb_get_as_service(
            f"/first_run_arc?business_id=eq.{biz}&select={_SELECT}&limit=1")
        return (rows or [None])[0] if rows else None
    except Exception as e:  # pragma: no cover - transport is caught inside sb_clients
        logger.warning(f"[first-run] state read failed for {biz}: {e}")
        return None


def begin(business_id: Any, *, source: str,
          trial_ends_at: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Open this business's day-one arc, once.

    Idempotent by the unique index on business_id. If a row already
    exists it is returned as-is, except for the two corrections the
    subscription door is allowed to make before the introduction has been
    delivered — see _align_to_trial. Returns the row, or None if it could
    not be opened, which is not an error worth propagating to either
    caller.
    """
    biz = str(business_id or "").strip()
    if not biz:
        return None
    if source not in SOURCES:
        logger.warning(f"[first-run] refusing unknown source {source!r} for {biz}")
        return None

    try:
        existing = state(biz)
        if existing:
            return _align_to_trial(existing, source, trial_ends_at)

        body: Dict[str, Any] = {
            "business_id": biz,
            "source": source,
            "started_at": _now_iso(),
        }
        if trial_ends_at:
            body["trial_ends_at"] = trial_ends_at

        written = sb_clients.sb_post_as_service("/first_run_arc", body)
        row = (written or [None])[0] if isinstance(written, list) else written
        if row:
            logger.info(f"[first-run] arc opened for {biz} via {source}")
            return row

        # sb_* returns None on any 4xx/5xx, and the most likely 4xx here
        # is the unique index doing its job because the other door opened
        # the arc microseconds ago. A row that already exists is the
        # success case, not the failure case — so look before concluding.
        raced = state(biz)
        if raced:
            logger.info(f"[first-run] arc for {biz} already opened by "
                        f"{raced.get('source')}; {source} stood down")
            return _align_to_trial(raced, source, trial_ends_at)
        logger.warning(f"[first-run] arc insert refused for {biz} via {source}")
        return None
    except Exception as e:
        logger.warning(f"[first-run] begin failed for {biz}: {e}")
        return None


def _align_to_trial(row: Dict[str, Any], source: str,
                    trial_ends_at: Optional[str]) -> Dict[str, Any]:
    """The two corrections an existing arc will accept, both from the
    subscription door and both only before the introduction has landed.

      1. Learn the trial's end date, which a signup-opened arc could not
         have known.
      2. Move `started_at` to the real trial start. Day one belongs to
         the trial, not to whenever the account was made — a signup in
         March and a subscription in April are one business and two very
         different first weeks.

    Two things bound the re-stamp, and both matter. `intro_delivered_at`
    is the outer freeze: before it nothing has been said and there is no
    conversation to contradict; after it, Chief has introduced herself
    and no billing event may replay that. `source` is the inner latch: it
    flips to 'subscription' in the same write, so the re-stamp happens
    at most once even though Stripe sends `trialing` on every
    trial-period update, not only on `created`.

    Returns the row either way. A failed patch is not worth failing a
    webhook over, and the arc still works without an end date — the beats
    count forward from the start, not back from the end.
    """
    if source != "subscription" or row.get("intro_delivered_at"):
        return row

    patch: Dict[str, Any] = {}
    if trial_ends_at and not row.get("trial_ends_at"):
        patch["trial_ends_at"] = trial_ends_at
    if row.get("source") != "subscription":
        # Opened at signup, and the trial is only starting now.
        patch["started_at"] = _now_iso()
        patch["source"] = "subscription"
    if not patch:
        return row

    biz = row.get("business_id")
    patch["updated_at"] = _now_iso()
    try:
        if sb_clients.sb_patch_as_service(
                f"/first_run_arc?business_id=eq.{biz}", patch) is None:
            logger.warning(f"[first-run] trial alignment refused for {biz}")
            return row
    except Exception as e:
        logger.warning(f"[first-run] trial alignment failed for {biz}: {e}")
        return row
    logger.info(f"[first-run] arc for {biz} aligned to its trial "
                f"({', '.join(sorted(k for k in patch if k != 'updated_at'))})")
    return {**row, **patch}


def day_of(row: Optional[Dict[str, Any]], *,
           now: Optional[datetime] = None) -> int:
    """Which day of the arc this is, 1-based: the day it opened is day 1.

    Uncapped on purpose. A practitioner who comes back on day twelve
    should not be told it is day seven — the caller decides how to talk
    about a number past the end of the beats, and "day 12 of a 7-day
    trial" is a sentence somebody eventually needs to write honestly.

    Returns 0 for "don't know" (no row, or an unreadable start), which is
    falsy so callers can treat it as "say nothing about days".
    """
    if not row:
        return 0
    started = _parse(row.get("started_at"))
    if not started:
        return 0
    return max(1, ((now or _now()) - started).days + 1)

"""
sample_church.py — a church looks around a sample church before it starts (BE-1, 2026-11-15).

Kevin approved it on 2026-11-14 ("top tier, no cut corners"). A church that
signs up gets no working trial. It looks around a PRIVATE copy of a made-up,
fully set-up church, Grace Street Fellowship, where nothing is saved or
sent; Chief answers ten questions about it; choosing a plan starts the
church for real and the sample is deleted. Businesses that are not churches,
and churches already on a trial, keep exactly what they have today.

THE SHAPE
  · Each church (the "home") gets its OWN sample: a second `businesses` row,
    is_sample=true, sample_of=<home id>, owned by the same person, and
    is_active=false, which keeps it out of the business list, the business
    count (billing_limits.business_count) and every is_active sweep. Every
    owner check and RLS policy works unchanged, because the visitor really
    does own it, and no visitor can see another's by construction.
  · supabase/APPLY-2026-11-15-sample-church.sql adds the two columns, one
    sample per home (a unique index), and a trigger: the app's own login can
    never make a sample, turn a row into one, or change or delete one. Only
    the server (the service role) does.
  · Deleting a sample is account_lifecycle._delete_business, the tested path
    that deletes a whole business.

WHO GETS ONE (applies): derived from the home row, never from a marker. A
church (vertical_registry.resolve(type) == "ministry", as
church_billing.is_church), not itself a sample, with no comp, no Stripe
subscription, no trial ever (trial_ends_at) and no subscription status,
whose owner is not grandfathered, while billing is enforced, the columns
exist, and the switch allows it.

THE SWITCH — CHURCH_SAMPLE:
  off   nobody; every church signs up exactly as before (no-card trial).
  test  (the shipped default) only owners whose sign-in email is listed in
        CHURCH_SAMPLE_TESTERS (comma separated). Listed nobody, it is off.
  on    every new church.
Turning it off later never strands anyone: a home that was in sample mode
simply meets the no-card trial at its next /billing/access, as before.

WHAT THIS PR (BE-1) DOES NOT DO YET, AND WHERE IT GOES
  BE-2  the seed: the made-up church's records and site (seed_hook below).
        Until then a sample is an empty row whose status stays "pending".
  BE-3  send and spend guards on every path, skip() in the sweeps, the
        "nothing is ever sent" test, and the daily cleanup.
  BE-4  the sample's Chief (ten questions, its own lane, sample_church_questions).
  FE-1..4 the app.

Every read here fails OPEN (a sample answers "not a sample" when the database
can't be read), like every billing read in this codebase; the trigger is the
database's own wall behind it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger("sample_church")

NAME = "Grace Street Fellowship"
SETTINGS_KEY = "sample_church"      # businesses.settings.sample_church on the SAMPLE row
SEED_VERSION = 0                    # BE-2 raises it when the seed changes
QUESTIONS_OF = 10                   # what Chief answers in a sample (BE-4)
COLUMNS = ("is_sample", "sample_of")

MESSAGE = ("This is a sample church, so nothing here is saved or sent. "
           "Start your church to do this for real.")

# POST routes that only READ (a search, a preview). BE-3's write guard lets
# these through for a sample; every other POST/PUT/PATCH/DELETE on a sample
# answers 409 sample_church. Empty until BE-3 names them: an empty list is
# the safe direction, since a missing entry only refuses a read.
READ_POSTS: Tuple[str, ...] = ()

# BE-2 fills this: seed_hook(sample_row, home_row) seeds the made-up church
# and marks settings.sample_church.status "ready". ensure() calls it for a
# sample still "pending". None here, so a sample stays an empty row.
seed_hook: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Any]] = None

_MODES = ("off", "test", "on")
_EMAIL_TTL_S = 600.0
_CACHE_CAP = 50_000

# id -> is it a sample? Kept for good, both ways: business ids are never
# reused, a row is born a sample or not, and nothing ever changes it (the
# trigger refuses the app; the server never writes is_sample after insert).
_KIND: Dict[str, bool] = {}
# owner id -> (read at, sign-in email); only real answers are kept.
_EMAILS: Dict[str, Tuple[float, str]] = {}
_TASKS: set = set()


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    """off | test | on. Shipped default: test. Anything else reads as off,
    the direction that changes nothing."""
    raw = (os.environ.get("CHURCH_SAMPLE") or "test").strip().lower()
    return raw if raw in _MODES else "off"


def testers() -> frozenset:
    return frozenset(e.strip().lower() for e in
                     (os.environ.get("CHURCH_SAMPLE_TESTERS") or "").split(",")
                     if e.strip() and "@" in e)


def _columns_ready() -> bool:
    """Has the migration been applied? The shared cached probe; without the
    columns everything here behaves as if the switch were off."""
    import schema_probe
    return schema_probe.has_columns("businesses", COLUMNS)


def open_to_all() -> bool:
    """Whether every new church signs up into a sample (the switch is on, the
    columns exist, billing is enforced). /access/open says it, for the sign-up
    wording. In test mode this is False: testers see the usual wording."""
    import feature_gates
    return mode() == "on" and feature_gates.enforcement_on() and _columns_ready()


# ─── Who gets one ─────────────────────────────────────────────────────

_NEEDED = ("id", "type", "owner_id", "comp_tier", "stripe_subscription_id",
           "trial_ends_at", "subscription_status", "is_sample")
_EMPTY_ON_A_HOME = ("comp_tier", "stripe_subscription_id", "trial_ends_at",
                    "subscription_status")


def _church(row: Dict[str, Any]) -> bool:
    import vertical_registry
    return vertical_registry.resolve(str(row.get("type") or "")) == "ministry"


def _ruled_out(row: Dict[str, Any]) -> bool:
    """True when a key the row DOES carry already rules it out. Missing keys
    rule nothing out here; _full() reads them."""
    for k in _EMPTY_ON_A_HOME:
        if k in row and str(row.get(k) or "").strip():
            return True
    if row.get("is_sample") is True:
        return True
    if "type" in row and not _church(row):
        return True
    return False


def _full(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The row with every key applies() reads, or None when it can't be read.
    One read, and only for a row a narrower select left short."""
    if all(k in row for k in _NEEDED):
        return row
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{row['id']}&select=*&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    _remember(rows[0])
    return {**rows[0], **{k: v for k, v in row.items() if k not in _NEEDED}}


def _owner_email(owner_id: str) -> Optional[str]:
    """The owner's sign-in email, kept ten minutes; None when it can't be read."""
    hit = _EMAILS.get(owner_id)
    if hit and time.monotonic() - hit[0] < _EMAIL_TTL_S:
        return hit[1]
    try:
        import messaging_router
        email = messaging_router.owner_email_read(owner_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] owner email read failed: {type(e).__name__}")
        return None
    if email is None:
        return None
    if len(_EMAILS) > _CACHE_CAP:
        _EMAILS.clear()
    _EMAILS[owner_id] = (time.monotonic(), email)
    return email


def applies(home_row: Optional[Dict[str, Any]], owner_email: Optional[str] = None, *,
            grandfathered: Optional[bool] = None) -> bool:
    """Does this business sign up into a sample church instead of a trial?

    `owner_email` is the OWNER's sign-in email when the caller already knows
    it (the person signing up); otherwise test mode reads it. `grandfathered`
    is the caller's answer when it has one; None reads it.

    Ordered so the shipped default costs nothing: with the switch off, or in
    test mode with nobody listed, this answers False before any read. Never
    raises: an error answers False, which is today's behaviour."""
    try:
        m = mode()
        if m == "off" or (m == "test" and not testers()):
            return False
        import feature_gates
        if not feature_gates.enforcement_on():
            return False
        row = dict(home_row or {})
        if not row.get("id") or _ruled_out(row):
            return False
        if not _columns_ready():
            return False
        row = _full(row)
        if row is None or _ruled_out(row) or not _church(row):
            return False
        owner = str(row.get("owner_id") or "")
        if not owner:
            return False
        if grandfathered is None:
            import usage_metering
            grandfathered = usage_metering.is_grandfathered_user(owner)
        if grandfathered:
            return False
        if m == "test":
            email = (owner_email or "").strip().lower() or _owner_email(owner)
            if not email or email not in testers():
                return False
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] applies() answered no after an error: {type(e).__name__}: {e}")
        return False


# ─── What is a sample ─────────────────────────────────────────────────

def _remember(row: Optional[Dict[str, Any]]) -> None:
    if not row or not row.get("id") or "is_sample" not in row:
        return
    if len(_KIND) > _CACHE_CAP:
        _KIND.clear()
    _KIND[str(row["id"])] = bool(row.get("is_sample"))


def is_sample(business_id: Any) -> bool:
    """Is this business a sample church? Kept for good once read (both ways).
    Fails OPEN: an unreadable answer is "no" and is asked again next time."""
    bid = str(business_id or "").strip()
    if not bid:
        return False
    hit = _KIND.get(bid)
    if hit is not None:
        return hit
    try:
        if not _columns_ready():
            return False
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{bid}&select=id,is_sample&limit=1")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] is_sample read failed open: {type(e).__name__}")
        return False
    if not isinstance(rows, list) or not rows:
        return False
    _remember(rows[0])
    return bool(rows[0].get("is_sample"))


async def is_sample_async(business_id: Any) -> bool:
    hit = _KIND.get(str(business_id or "").strip())
    if hit is not None:
        return hit
    return await asyncio.to_thread(is_sample, business_id)


def row_is_sample(row: Optional[Dict[str, Any]]) -> bool:
    """is_sample() for a row in hand: its own column when it carries one."""
    if not row:
        return False
    if "is_sample" in row:
        _remember(row)
        return row.get("is_sample") is True
    return is_sample(row.get("id"))


def skip(biz_row: Optional[Dict[str, Any]]) -> bool:
    """For the sweeps (BE-3 wires them): True when this business is a sample,
    so a sweep that would mail, text, bill or report on it passes it by."""
    return row_is_sample(biz_row)


_SAMPLE_SELECT = "id,owner_id,name,type,settings,is_active,is_sample,sample_of,created_at"


def sample_for(home_id: Any) -> Optional[Dict[str, Any]]:
    """The home's sample row, or None (none yet, or it can't be read)."""
    hid = str(home_id or "").strip()
    if not hid or not _columns_ready():
        return None
    rows = sb_clients.sb_get_as_service(
        f"/businesses?sample_of=eq.{hid}&is_sample=is.true&select={_SAMPLE_SELECT}&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    _remember(rows[0])
    return rows[0]


def home_of(sample_id: Any) -> Optional[str]:
    """The home a sample belongs to, or None (not a sample, its home is gone,
    or it can't be read). Read fresh: a home's deletion nulls sample_of."""
    sid = str(sample_id or "").strip()
    if not sid or not _columns_ready():
        return None
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{sid}&select=id,is_sample,sample_of&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    _remember(rows[0])
    if rows[0].get("is_sample") is not True:
        return None
    return str(rows[0].get("sample_of") or "") or None


def status_of(sample_row: Optional[Dict[str, Any]]) -> str:
    m = ((sample_row or {}).get("settings") or {}).get(SETTINGS_KEY)
    return str((m or {}).get("status") or "pending") if isinstance(m, dict) else "pending"


def ready(sample_row: Optional[Dict[str, Any]]) -> bool:
    """Seeded and ready to look around (BE-2 sets status "ready")."""
    return bool(sample_row) and status_of(sample_row) == "ready"


# ─── Making one ───────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample_settings(home: Dict[str, Any]) -> Dict[str, Any]:
    """A sample is born with every send switched off. Nothing in it should
    ever send (BE-3 guards each path); these are the switches the system
    already reads, set the quiet way, so even a path BE-3 missed stays quiet."""
    hs = home.get("settings") if isinstance(home.get("settings"), dict) else {}
    out: Dict[str, Any] = {
        SETTINGS_KEY: {"version": SEED_VERSION, "status": "pending", "created_at": _now_iso()},
        # The rules engine, journeys and Chief's agent (policy_engine).
        "automations_paused": True,
        # Client-facing autonomy, the shape launch_access gives a regulated practice.
        "autonomy": {"client_facing_autonomy": "disabled", "disabled_reason": "sample_church",
                     "acknowledgment_required": True, "acknowledged_at": None},
        # Every agent asks first (chief_of_staff._autopilot_level reads "manual").
        "autopilot": {"overall": "manual", "per_team": {}},
        # Booking confirmations and reminders by text (chief_sms_actions).
        "sms_alerts": {"confirmations": False, "reminders": False},
    }
    # The home's clock and the pastor's name, so the sample reads as theirs.
    if hs.get("practitioner_name"):
        out["practitioner_name"] = hs["practitioner_name"]
    for k in ("timezone", "tz"):
        if hs.get(k):
            out[k] = hs[k]
    tz = (hs.get("availability") or {}).get("timezone") if isinstance(hs.get("availability"), dict) else None
    if tz:
        out["availability"] = {"timezone": tz}
    return out


def _seed(sample: Dict[str, Any], home: Dict[str, Any]) -> None:
    if seed_hook is None or status_of(sample) != "pending":
        return
    try:
        seed_hook(sample, home)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] seed for {str(sample.get('id'))[:8]} failed (stays pending): "
                       f"{type(e).__name__}: {e}")


def ensure(home_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The home's sample row, made if it has none. Idempotent and race-safe:
    the unique index (one sample per home) lets only one insert through, and
    the loser reads the winner's row. Makes the ROW only; the seed is BE-2's
    (seed_hook). Never raises; None when it couldn't be made or read.

    The caller decides WHETHER (applies()); this holds only the invariants
    that make a sample a sample: a church home, with an owner, that is not
    itself a sample."""
    try:
        home = dict(home_row or {})
        hid = str(home.get("id") or "").strip()
        owner = str(home.get("owner_id") or "").strip()
        if not hid or not owner or not _columns_ready():
            return None
        if row_is_sample(home) or not _church(home):
            return None
        have = sample_for(hid)
        if have:
            _seed(have, home)
            return have
        res = sb_clients.sb_post_as_service("/businesses", {
            "owner_id": owner,
            "name": NAME,
            "type": str(home.get("type") or "ministry")[:60],
            "voice_profile": {},
            "settings": _sample_settings(home),
            "is_active": False,
            "is_sample": True,
            "sample_of": hid,
        })
        row = (res or [None])[0] if isinstance(res, list) else res
        if row:
            _remember(row)
            logger.info(f"[sample] made a sample for {hid[:8]}: {str(row.get('id'))[:8]}")
        else:
            # Most likely the unique index refusing a second sample because a
            # racing ensure() made it a moment ago. That is the success case.
            row = sample_for(hid)
            if not row:
                logger.warning(f"[sample] could not make a sample for {hid[:8]}")
                return None
        _seed(row, home)
        return row
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] ensure failed for {str((home_row or {}).get('id'))[:8]}: "
                       f"{type(e).__name__}: {e}")
        return None


# ─── Ending one ───────────────────────────────────────────────────────

def _background(coro) -> None:
    """Run it after the caller returns, holding a reference so it isn't
    collected mid-delete. A deploy can still cut it short; the sample is
    marked "ending" first, so BE-3's daily cleanup finishes it."""
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _safe(sample: Optional[Dict[str, Any]], home_id: str) -> bool:
    """Only ever delete a row that IS a sample of THIS home, and never the home."""
    return bool(sample and sample.get("is_sample") is True
                and str(sample.get("sample_of") or "") == home_id
                and str(sample.get("id") or "") not in ("", home_id))


def _mark_ending(sample: Dict[str, Any]) -> None:
    settings = dict(sample.get("settings") or {})
    m = dict(settings.get(SETTINGS_KEY) or {})
    m.update(status="ending", ended_at=_now_iso())
    settings[SETTINGS_KEY] = m
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{sample['id']}&is_sample=is.true", {"settings": settings})


async def delete(sample: Dict[str, Any]) -> bool:
    """Delete a sample through account_lifecycle's whole-business delete,
    after reading it again to be sure it is still a sample. Never raises."""
    sid = str((sample or {}).get("id") or "")
    try:
        fresh = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/businesses?id=eq.{sid}&is_sample=is.true&select=id,is_sample,sample_of&limit=1")
        if not isinstance(fresh, list) or not fresh or fresh[0].get("is_sample") is not True:
            logger.warning(f"[sample] {sid[:8]} not deleted: it no longer reads as a sample")
            return False
        import httpx
        import account_lifecycle
        async with httpx.AsyncClient(timeout=account_lifecycle.HTTP_TIMEOUT) as client:
            counts = await account_lifecycle._delete_business(client, {"id": sid})
        logger.info(f"[sample] deleted {sid[:8]} ({sum(counts.values())} rows)")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] delete of {sid[:8]} failed (left 'ending' for the cleanup): "
                       f"{type(e).__name__}: {e}")
        return False


async def end(home_id: Any, *, wait: bool = False) -> Optional[str]:
    """The home started for real: mark its sample "ending" and delete it (in
    the background unless `wait`). Idempotent: a home with no sample is a
    no-op. Never touches the home. Never raises. Returns the sample's id, or
    None when there was none.

    Not gated on the switch: a sample made while testing must still go when
    its church starts after the switch has moved."""
    hid = str(home_id or "").strip()
    try:
        if not hid or not await asyncio.to_thread(_columns_ready):
            return None
        sample = await asyncio.to_thread(sample_for, hid)
        if not sample:
            return None
        if not _safe(sample, hid):
            logger.error(f"[sample] refused to end {str(sample.get('id'))[:8]} for {hid[:8]}")
            return None
        await asyncio.to_thread(_mark_ending, sample)
        if wait:
            await delete(sample)
        else:
            _background(delete(sample))
        return str(sample["id"])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] end failed for {hid[:8]}: {type(e).__name__}: {e}")
        return None


# ─── Refusing what a sample can't do ──────────────────────────────────

def detail(what: str) -> Dict[str, Any]:
    """The 409 the app reads. Not a 402: a 402 opens the app's "Open Billing"
    toast, and a sample has nothing to pay for; its home does."""
    return {"error": "sample_church", "what": what, "message": MESSAGE}


def refuse(business: Any, what: str = "this") -> None:
    """409 sample_church when `business` (an id, or a row in hand) is a sample."""
    sample = row_is_sample(business) if isinstance(business, dict) else is_sample(business)
    if sample:
        raise HTTPException(status_code=409, detail=detail(what))


async def refuse_async(business: Any, what: str = "this") -> None:
    if isinstance(business, dict) and "is_sample" in business:
        sample = row_is_sample(business)
    else:
        bid = business.get("id") if isinstance(business, dict) else business
        sample = await is_sample_async(bid)
    if sample:
        raise HTTPException(status_code=409, detail=detail(what))


# ─── What /billing/access tells the app ───────────────────────────────

def questions_left(user_id: Any) -> Optional[int]:
    """Questions Chief has left to answer in this person's sample: ten less
    the ones asked (sample_church_questions, BE-4 writes it). Per PERSON, so a
    new sample is never ten more. None when it can't be read."""
    uid = str(user_id or "").strip()
    if not uid:
        return None
    rows = sb_clients.sb_get_as_service(
        f"/sample_church_questions?user_id=eq.{uid}&select=n&limit=50")
    if not isinstance(rows, list):
        return None
    return max(0, QUESTIONS_OF - len(rows))


def free_moves_left() -> Optional[int]:
    """Founding (free) moves still open; None when the count can't be read."""
    import church_billing
    import pricing_config
    taken = church_billing._founding_taken()
    if taken is None:
        return None
    return max(0, pricing_config.founding_church_moves() - taken)


def access_block(*, home_id: Any, sample: Optional[Dict[str, Any]],
                 owner_id: Any) -> Dict[str, Any]:
    """The `sample` block of GET /billing/access. Sync (it reads); the
    endpoint runs it off the event loop."""
    import church_site
    return {
        "business_id": str(sample["id"]) if sample else None,
        "home_business_id": str(home_id) if home_id else None,
        "ready": ready(sample),
        "questions_left": questions_left(owner_id),
        "questions_of": QUESTIONS_OF,
        "read_posts": list(READ_POSTS),
        "promise": church_site.PROMISE,
        "free_moves_left": free_moves_left(),
    }


def _reset_for_tests() -> None:
    _KIND.clear()
    _EMAILS.clear()

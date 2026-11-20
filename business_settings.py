"""business_settings.py — who may write which key of businesses.settings, and
writes that touch only their own keys.

The first paying church lost its founding place on 2026-11-16: the place was
written to settings.founding_church when its first payment landed, and about
two hours later something wrote the whole settings object back from a copy
read before the payment, so the key was gone. Every writer of this column
read the whole object, changed one key and wrote the whole object back: the
app's rooms (RoomOrientationStrip's rooms_visited stamp, one write per room a
young business opens, from the copy the app loaded at sign-in) and about
eighty server paths, church_billing._merge_setting among them. Any two of
them a moment apart could drop each other's keys. The reverse was a hole: an
owner or admin can PATCH their own businesses row through RLS, so the app's
login could write settings.founding_church (the founding price at checkout),
extra_logins (seats), churchsavvy_only (dropped, everything opens) or
computer (Chief's spending limits, behind a step-up unlock in the API).

Two pieces fix it:

  1. SERVER_KEYS: the keys only the server writes. The database keeps them
     (trigger businesses_guard_server_settings,
     supabase/APPLY-2026-11-17-settings-server-keys.sql): a write from the
     app's own logins (anon, authenticated) can neither set, change nor drop
     one; its other keys land as sent. The service role and the SQL editor
     are not held. The list is the inventory in
     worklog/2026-11-17-settings-server-keys.md: every key a server path
     writes that the app never writes itself and that no server path writes
     with the user's login (Chief's _sb inside a chat, brand_engine). A test
     pins the SQL list to this one.

  2. merge(): settings = (settings - drop) || set in ONE UPDATE (the
     database function merge_business_settings), so a key the call doesn't
     name is never touched, whatever another writer did a moment ago. Until
     the migration is applied it falls back to a fresh read and a whole
     write (the old way), and says so in the log once every few minutes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import sb_clients

logger = logging.getLogger("business_settings")

# ─── The server's keys ───────────────────────────────────────────────
# Grouped by why a login in the app must never set or drop them. Adding a
# key here means adding it to the SQL list too (the test says so); a key the
# app writes itself must never be here, or the app's write of it would be
# kept out silently.
SERVER_KEYS: Tuple[str, ...] = (
    # Money, plans and offers: a forged one is a price, a seat or a trial.
    "founding_church",      # church_founding: the founding place and price
    "no_card_trial",        # no_card_trial: the trial marker, credits, phone check
    "sample_church",        # sample_church: the sample's state (sample rows)
    "church_move",          # church_billing: the paid move and its founding share
    "extra_logins",         # church_billing: paid extra office logins (seats)
    "extra_storage",        # church_billing: paid extra storage (100 GB blocks)
    "church_texts_bill",    # church_texts: the texting registration bill
    "stripe",               # stripe_connect_router: Connect account state
    "churchsavvy_only",     # set at birth; dropped, a ChurchSavvy-only church opens everything
    "platform_books",       # platform_console: Solutionist's own books
    # Gates the API holds behind the owner, a role or a step-up unlock.
    "computer",             # chief_errands: Chief's spend limit and hosts (step-up)
    "email_domain",         # email_domains_router: the verified sending domain
    "autonomy",             # standing_permissions / launch_access: client-facing autonomy, the regulated-vertical acknowledgment
    "content_autonomy",     # content_approval: publishing without approval (owner only)
    "automations_paused",   # rules_router: the owner's pause switch
    "church_owner_contact_id",  # church_assignments: the owner's person
    # The server's own records: dropped, a send repeats or a run is paid again.
    "lifecycle_emails",     # lifecycle_emails: send stamps (sample_follow_up_at too)
    "chief_insights",       # chief_insights: last run
    "chief_playbook",       # chief_playbook: last run and fingerprint
    "maturity",             # maturity_engine: the cached stage
    "church_leaders_note",  # church_leaders_note: the last send
    "church_team_rollup",   # church_team_week: the last roll-up
    "interview_events",     # site_composer: the builder interview's events
    # Settings with their own checked endpoint; the app never writes them here.
    "availability", "booking_page", "business_picture", "church_serving", "churchsavvy",
    "client_sources", "concierge", "doc_defaults", "giving", "journeys", "member_portal",
    "messaging", "new_here", "news", "reading_plan", "site_prefs", "sms_replies", "studio",
    "superbill", "texting_hours",
    "payroll",              # PUT /payroll/settings (payroll_calendar): deposit schedule, the state's day
    "guest_calls",          # PUT /church/guest-calls (guest_calls): who calls the church's guests
)

# Keys the app's login may set when it makes a business and never change
# after: the ChurchSavvy app makes its church with churchsavvy_only = true,
# which only narrows what the church opens.
BIRTH_KEYS = frozenset({"churchsavvy_only"})

_SERVER = frozenset(SERVER_KEYS)

RPC = "merge_business_settings"
_MISSING_TTL = 300.0            # how long to trust "the function isn't there yet"
_missing = {"until": 0.0}


def server_owned(key: Any) -> bool:
    return str(key) in _SERVER


def for_new_business(settings: Any) -> Dict[str, Any]:
    """Settings a client sent for a business it is making (the signup door,
    an account import): every server key is left out except BIRTH_KEYS, so
    nobody is born with a founding place, a trial, seats or a step-up limit
    they were never given."""
    if not isinstance(settings, dict):
        return {}
    return {k: v for k, v in settings.items() if not server_owned(k) or k in BIRTH_KEYS}


def merge_at(doc: Any, under: Sequence[str], put: Dict[str, Any], drop: Iterable[str]) -> Dict[str, Any]:
    """The merge, the same as the database's business_settings_merge_at:
    at the object `under` points to (created when missing, replaced when it
    isn't an object), remove `drop` and lay `put` over it. A shallow merge,
    so a value in `put` replaces that key's value whole."""
    base = dict(doc) if isinstance(doc, dict) else {}
    if not under:
        for k in drop:
            base.pop(k, None)
        base.update(put)
        return base
    base[under[0]] = merge_at(base.get(under[0]), list(under[1:]), put, drop)
    return base


def _rpc_missing(err: Optional[Dict[str, Any]]) -> bool:
    """PostgREST's answer when the function isn't in its schema cache: the
    migration hasn't been applied (or PostgREST hasn't reloaded)."""
    if not err:
        return False
    return str(err.get("code") or "") in ("PGRST202", "42883")


def _by_hand(bid: str, put: Dict[str, Any], drop: Sequence[str], under: Sequence[str]) -> Optional[Dict[str, Any]]:
    """The old way, for until the function exists: a fresh read, the merge,
    the whole object written back. A writer a moment apart can still drop a
    key here; that is what the migration ends."""
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{bid}&select=settings&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    merged = merge_at(rows[0].get("settings"), under, put, drop)
    if sb_clients.sb_patch_as_service(f"/businesses?id=eq.{bid}", {"settings": merged}) is None:
        return None
    return merged


def merge(business_id: Any, set: Optional[Dict[str, Any]] = None, drop: Iterable[str] = (),
          under: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    """Write these keys of one business's settings, and no other:
    settings = (settings - drop) || set, in one UPDATE as the server. With
    `under`, the merge happens inside that nested object instead
    (under=["lifecycle_emails"] stamps one send without touching the other
    stamps). Returns the settings as they are after the write; None when
    nothing was written (no such business, or the write failed: the log
    says which). Never raises for a database failure."""
    bid = str(business_id or "").strip()
    put = dict(set or {})
    gone = [str(k) for k in (drop or ())]
    path = [str(k) for k in (under or ())]
    if not bid:
        return None
    if not put and not gone:
        raise ValueError("business_settings.merge: nothing to write")
    if any(not str(k) for k in [*put, *gone, *path]):
        raise ValueError("business_settings.merge: an empty key")
    if time.monotonic() >= _missing["until"]:
        out = sb_clients.sb_post_as_service(
            f"/rpc/{RPC}", {"p_business": bid, "p_set": put, "p_drop": gone, "p_under": path})
        if isinstance(out, dict):
            return out
        err = sb_clients.last_error()
        if not _rpc_missing(err):
            if err:
                logger.warning("settings merge for %s refused: %s %s", bid[:8], err.get("code"), err.get("message"))
            return None
        _missing["until"] = time.monotonic() + _MISSING_TTL
        # Railway shows print() only.
        print("[settings] merge_business_settings isn't in the database yet: writing the whole "
              "object from a fresh read until supabase/APPLY-2026-11-17-settings-server-keys.sql "
              "is applied", flush=True)
    return _by_hand(bid, put, gone, path)


async def amerge(business_id: Any, set: Optional[Dict[str, Any]] = None, drop: Iterable[str] = (),
                 under: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    """merge() from async code, off the event loop."""
    return await asyncio.to_thread(merge, business_id, set, list(drop or ()), list(under or ()))

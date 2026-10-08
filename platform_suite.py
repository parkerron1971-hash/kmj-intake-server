"""platform_suite.py — Solutionist's own marketing desk on the suite (B15).

Step 5 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md. Mission Control's
Marketing desk stops being a separate single-tenant system (Buffer, the
platform_marketing_* tables, marketing_engine's Thursday job) and becomes the
desk for Solutionist's own business on the suite every business uses: one
posting path (Post for Me, through the business's own connected accounts),
one store (marketing_*), one planner.

Two switches, both server-side only:

  MC_MARKETING_SUITE   off (default) | on. Off: today's platform desk, exactly
                       as before. On, with a valid platform business (below):
                       Mission Control's desk runs on the suite
                       (/platform/marketing/suite/*, platform_marketing_suite),
                       nothing new goes to Buffer, and posts approved there
                       before the switch are left to go out (the drain).
  PLATFORM_BUSINESS_ID the businesses.id of Solutionist's own business (the
                       row platform_console sets up with settings.platform_books
                       true under the platform owner's account).

THE ONE PREDICATE. "The platform business" is the configured id only once it
is VALIDATED: its row is readable, its settings.platform_books is true, and
its owner is the platform owner's user (the auth user whose email is
PLATFORM_OWNER_EMAIL, read as the service role, as platform_chief_authority
reads a business owner's address). state() answers one of:

  valid    the id is Solutionist's own business
  invalid  the id names some other row (a tenant's id put in by mistake gets
           nothing special: no level, no profile, no exclusion)
  unknown  a read failed: fail closed, nothing is the platform business, and
           nothing is planned for that id this hour on either side
  unset    no id

The suite is ACTIVE when MC_MARKETING_SUITE is on AND the state is valid.
Everything keys on that: close_buffer, Platform Chief's create verbs, the old
Thursday job's early return, the fan-out's inclusion, the level, the profile,
the numbers, the plays, the site and the clock. Switch on but the id unset or
invalid: the Buffer desk keeps working exactly as before, a loud warning is
logged, and GET /platform/marketing/suite/status and /drain say so in a plain
sentence (problem()). Switch on but unknown: neither desk takes anything new
that minute (a 503 in plain words), and neither loop plans.

Verdicts are cached for 5 minutes (a failed read for 1), so the reads behind
them are rare; forget() empties the cache.

WHY AN ID AND NOT THE FLAG ALONE. settings is the owner's own JSON: any
business admin can set settings.platform_books on their own row (the
businesses_admin_update policy). books_business() is the flag lookup the news
page and the Buffer desk's flyers use, with the same owner check, so a
tenant's flag never makes its row the platform's.

ONE LOOP A WEEK. Off (or not active), the platform business is never in the
suite's fan-out once the id validates (desk_on_for answers False for it), and
marketing_engine's Thursday job plans the week. Active, the old job does
nothing and the suite plans. Across the switch: the suite does not plan a
week whose Buffer plan already has a post approved or out
(buffer_week_live), and the old job does not plan a week whose suite plan
does (suite_week_live). A read that fails plans nothing that hour.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any, Callable, Dict, Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

FLAG = 'MC_MARKETING_SUITE'
ID_ENV = 'PLATFORM_BUSINESS_ID'
TZ = ZoneInfo('America/New_York')          # marketing_engine.TZ: the platform desk's clock
LEVEL_PLAN = 'practice'                    # the plan whose features are the autopilot level

VALID, INVALID, UNKNOWN, UNSET = 'valid', 'invalid', 'unknown', 'unset'
TTL_OK = 300.0
TTL_FAILED = 60.0

# What the old desk refuses while the suite is active (409), and what
# Platform Chief says instead of making a Buffer post.
BUFFER_CLOSED = ("Solutionist's marketing runs on the marketing suite now, so nothing new goes to Buffer. "
                 'Make, approve and post it on the suite desk. Posts already approved here still go out.')
UNCONFIRMED = ("Solutionist's own business couldn't be confirmed just now, so neither marketing desk takes "
               'anything new this minute. Nothing was changed. Try again shortly.')
NOT_ON = ("Solutionist's own desk isn't on the marketing suite yet (MC_MARKETING_SUITE is off). "
          'The Buffer desk is still the one in use.')
NO_ID = ("MC_MARKETING_SUITE is on, but PLATFORM_BUSINESS_ID is not set, so the server doesn't know which "
         'business is Solutionist\'s own. The Buffer desk is still the one in use; nothing moved to the suite.')
WRONG_ID = ("MC_MARKETING_SUITE is on, but PLATFORM_BUSINESS_ID doesn't name Solutionist's own business (a "
            "business marked as the platform's own books and owned by the platform owner). The Buffer desk is "
            'still the one in use; nothing moved to the suite.')
BUFFER_WEEK = ("That week was planned on the Buffer desk before the switch, and some of its posts are already "
               "approved or out, so Chief won't plan it again here. Make single posts on this desk, or plan "
               'next week from Thursday.')
BUFFER_WEEK_UNREAD = ("The Buffer desk's plan for that week couldn't be read just now, so Chief didn't plan it "
                      'here. It tries again later.')

LIVE_BUFFER = ('approved', 'dispatching', 'submitted', 'published', 'uncertain')
LIVE_SUITE = ('approved', 'dispatching', 'submitted', 'published', 'partly_published', 'uncertain')


class _Unread(Exception):
    """A read the verdict needs did not happen. Never "not the platform's"."""


# ── the switch and the configured id ──────────────────────────────────

def suite_on() -> bool:
    return (os.environ.get(FLAG) or 'off').strip().lower() == 'on'


def platform_id() -> Optional[str]:
    """PLATFORM_BUSINESS_ID as a canonical uuid, or None (unset or not a
    uuid). Configured, not yet validated: see state()."""
    raw = (os.environ.get(ID_ENV) or '').strip()
    if not raw:
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        log.warning('platform suite: %s is not a business id; the suite desk stays closed.', ID_ENV)
        return None


def _same(business_id: Any, pid: Optional[str]) -> bool:
    if not pid or business_id is None:
        return False
    try:
        return str(UUID(str(business_id))) == pid
    except ValueError:
        return False


# ── the reads behind a verdict (service role) ─────────────────────────

def _platform_email() -> str:
    from lead_admin import PLATFORM_OWNER_EMAIL
    return PLATFORM_OWNER_EMAIL


def _owner_email(owner_id: Any) -> Optional[str]:
    """The auth user's email (lower case), None for no such user. Raises
    _Unread when it cannot be read."""
    import httpx
    import sb_clients
    base = sb_clients.sb_url()
    if not base or not owner_id:
        raise _Unread('auth')
    try:
        response = httpx.get(f'{base}/auth/v1/admin/users/{UUID(str(owner_id))}',
                             headers=sb_clients.sb_headers_service(), timeout=10)
    except Exception:
        raise _Unread('auth') from None
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise _Unread('auth')
    return str((response.json() or {}).get('email') or '').strip().lower() or None


def _is_platform_owner(owner_id: Any) -> bool:
    """Raises _Unread when the owner's address cannot be read."""
    return bool(owner_id) and _owner_email(owner_id) == _platform_email()


def _books(row: Dict[str, Any]) -> bool:
    """settings.platform_books from the narrow select (platform_books) or a whole row."""
    if 'platform_books' in row:
        flag = row.get('platform_books')
    else:
        settings = row.get('settings') if isinstance(row.get('settings'), dict) else {}
        flag = settings.get('platform_books')
    return flag is True or str(flag).strip().lower() == 'true'


def _get(path: str):
    import sb_clients
    try:
        return sb_clients.sb_get_as_service(path)
    except Exception:
        return None


def _read_business(business_id: str):
    """[row] / [] / None (failed) for one business, the columns a verdict needs."""
    return _get(f'/businesses?id=eq.{business_id}&select=id,owner_id,platform_books:settings->>platform_books'
                '&limit=1')


def _flagged_rows():
    """Rows whose settings say platform_books (anyone can say so of their own row)."""
    return _get('/businesses?settings->>platform_books=eq.true&select=id,owner_id&order=created_at.asc&limit=10')


def _check_id(pid: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    rows = _read_business(pid)
    if not isinstance(rows, list):
        return UNKNOWN, None
    if not rows or str(rows[0].get('id')) != pid or not _books(rows[0]):
        return INVALID, None
    try:
        owned = _is_platform_owner(rows[0].get('owner_id'))
    except _Unread:
        return UNKNOWN, None
    if not owned:
        return INVALID, None
    return VALID, {'id': pid, 'owner_id': str(rows[0]['owner_id'])}


def _find_books() -> Tuple[str, Optional[Dict[str, Any]]]:
    rows = _flagged_rows()
    if not isinstance(rows, list):
        return UNKNOWN, None
    for row in rows:
        try:
            if _is_platform_owner(row.get('owner_id')):
                return VALID, {'id': str(row['id']), 'owner_id': str(row['owner_id'])}
        except _Unread:
            return UNKNOWN, None
    return INVALID, None


_cache: Dict[str, Tuple[float, Tuple[str, Optional[Dict[str, Any]]]]] = {}


def forget() -> None:
    _cache.clear()


def _remember(key: str, compute: Callable[[], Tuple[str, Optional[Dict[str, Any]]]], *, loud: bool = False):
    at = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > at:
        return hit[1]
    verdict = compute()
    _cache[key] = (at + (TTL_FAILED if verdict[0] == UNKNOWN else TTL_OK), verdict)
    if loud and verdict[0] != VALID and suite_on():
        # Loud, once per verdict: the switch is on and the suite is not.
        log.error('platform suite: MC_MARKETING_SUITE is on but %s is %s for Solutionist\'s own business; '
                  'the Buffer desk %s.', ID_ENV, verdict[0],
                  'stays in use' if verdict[0] == INVALID else 'and the suite take nothing new until it is read')
    return verdict


# ── the one predicate ─────────────────────────────────────────────────

def state() -> Tuple[str, Optional[str]]:
    """(valid | invalid | unknown | unset, the configured id)."""
    pid = platform_id()
    if not pid:
        if suite_on() and _cache.get('unset', (0.0,))[0] <= time.monotonic():
            _cache['unset'] = (time.monotonic() + TTL_OK, (UNSET, None))
            log.error('platform suite: MC_MARKETING_SUITE is on but %s is not set; the Buffer desk stays in use.',
                      ID_ENV)
        return UNSET, None
    return _remember(f'id:{pid}', lambda: _check_id(pid), loud=True)[0], pid


def valid_id() -> Optional[str]:
    """The configured id once validated, whatever the switch says."""
    verdict, pid = state()
    return pid if verdict == VALID else None


def active_id() -> Optional[str]:
    """The platform business's id while its desk is on the suite: the switch
    on AND the id valid. None otherwise."""
    return valid_id() if suite_on() else None


def is_platform(business_id: Any) -> bool:
    """This is Solutionist's own business AND its desk is on the suite. Every
    platform-only behaviour (level, profile, signals, plays, site, clock) asks
    this. Validated only for the configured id itself; False for every other
    business without a read."""
    pid = platform_id()
    return suite_on() and _same(business_id, pid) and state()[0] == VALID


def problem() -> Optional[str]:
    """Why the switch is on and the suite is not active, in a plain
    sentence; None when the switch is off or the suite is active."""
    if not suite_on():
        return None
    verdict, _ = state()
    return {UNSET: NO_ID, INVALID: WRONG_ID, UNKNOWN: UNCONFIRMED}.get(verdict)


def buffer_state() -> str:
    """'open' (the Buffer desk as before), 'closed' (the suite is active) or
    'unknown' (the switch is on and the business couldn't be confirmed)."""
    if not suite_on():
        return 'open'
    verdict, _ = state()
    return {VALID: 'closed', UNKNOWN: 'unknown'}.get(verdict, 'open')


def close_buffer() -> None:
    """Refuse a write that would put a new post on Buffer's way while the
    suite is active (409), or while it cannot be confirmed (503). A no-op
    while the switch is off, or on with the id unset or invalid (logged)."""
    closed = buffer_state()
    if closed == 'open':
        return
    from fastapi import HTTPException
    if closed == 'closed':
        raise HTTPException(409, BUFFER_CLOSED)
    raise HTTPException(503, UNCONFIRMED)


def chief_closed() -> Optional[str]:
    """Platform Chief's words for the same refusal, or None (go ahead)."""
    closed = buffer_state()
    return None if closed == 'open' else BUFFER_CLOSED if closed == 'closed' else UNCONFIRMED


def desk_switch(business_id: Any) -> Optional[bool]:
    """MARKETING_DESK's answer for the platform business, or None for any
    other business (an unset or invalid id included: it gets nothing
    special). Valid: on the suite it is always switched on, off the suite
    never, so the two loops never both plan its week. Unknown: not this
    hour."""
    pid = platform_id()
    if not _same(business_id, pid):
        return None
    verdict, _ = state()
    if verdict in (UNSET, INVALID):
        return None
    return verdict == VALID and suite_on()


def with_platform(scope: Any) -> Any:
    """MARKETING_DESK's scope (None, '*' or a frozenset of ids) with the
    platform business in it while the suite is active, and out of it
    otherwise once the id validates (or cannot be read). Unchanged when the
    id is unset or invalid."""
    pid = platform_id()
    if not pid:
        return scope
    verdict, _ = state()
    if verdict in (UNSET, INVALID):
        return scope
    if verdict == VALID and suite_on():
        if scope is None:
            return frozenset({pid})
        return scope if scope == '*' else frozenset(scope) | {pid}
    if scope is None or scope == '*':
        return scope                       # '*': desk_on_for answers False for it
    return (frozenset(scope) - {pid}) or None


def effective_row(row: Any) -> Any:
    """The platform business's row as the plan gates read it: comp_tier
    practice (the autopilot level) whatever its billing says, in memory only,
    while the suite is active. Any other row comes back as it is. Never
    written anywhere; never from a request."""
    if isinstance(row, dict) and is_platform(row.get('id')):
        return {**row, 'comp_tier': LEVEL_PLAN}
    return row


def zone_for(business_id: Any) -> Optional[ZoneInfo]:
    """The platform desk's clock for the platform business on the suite, else None."""
    return TZ if is_platform(business_id) else None


# ── the platform's own books, by the flag (news page, Buffer flyers) ──

def books_business() -> Tuple[str, Optional[Dict[str, Any]]]:
    """(valid | invalid | unknown, {id, owner_id}): Solutionist's own
    business as the platform_books flag names it, owned by the platform
    owner. A validated PLATFORM_BUSINESS_ID wins; otherwise the first flagged
    row (oldest first) whose owner is the platform owner. A tenant flagging
    its own row is never it. Unknown when a read fails."""
    pid = platform_id()
    if pid:
        verdict = _remember(f'id:{pid}', lambda: _check_id(pid), loud=True)
        if verdict[0] == VALID:
            return verdict
    return _remember('books', _find_books)


# ── one loop a week ───────────────────────────────────────────────────

async def buffer_week_live(week_of: date) -> Optional[bool]:
    """Whether the Buffer desk's own weekly plan for this week (its run id is
    marketing_engine.run_id_for(week)) has a post approved or out. None when
    that cannot be read: the suite then plans nothing for the hour."""
    import marketing_engine
    import platform_marketing as marketing
    from fastapi import HTTPException
    rid = marketing_engine.run_id_for(week_of)
    try:
        rows = await marketing.db('GET', f"/platform_marketing_posts?run_id=eq.{rid}"
                                         f"&status=in.({','.join(LIVE_BUFFER)})&select=id&limit=1")
    except HTTPException:
        return None
    except Exception:
        log.warning('platform suite: the Buffer week could not be read', exc_info=True)
        return None
    return bool(rows)


async def suite_week_live(week_of: date) -> Optional[bool]:
    """Whether the suite's plan for the platform business this week has a
    post approved or out. False at once (no read) while the id is unset or
    invalid; None when the business or its posts cannot be read (the old job
    then waits an hour)."""
    verdict, pid = state()
    if verdict in (UNSET, INVALID):
        return False
    if verdict == UNKNOWN:
        return None
    import business_marketing_store as store
    rid = store.run_id_for(pid, week_of)
    try:
        rows = await store.rows(f"/marketing_posts?business_id=eq.{pid}&run_id=eq.{rid}"
                                f"&status=in.({','.join(LIVE_SUITE)})&select=id&limit=1")
    except store.StoreError:
        return None
    return bool(rows)


# ── its site: mysolutionist.app ───────────────────────────────────────

def platform_site(business_id: Any) -> Optional[Dict[str, Any]]:
    """The platform business's "site" for its links: mysolutionist.app itself
    (business_marketing_links reads `platform`: hosts mysolutionist.app and
    www, origin https://mysolutionist.app). None for any other business, and
    for an id that does not validate. Keyed on the validated id, not the
    switch, so a link already out still resolves if the switch goes back off."""
    pid = platform_id()
    if not _same(business_id, pid) or state()[0] != VALID:
        return None
    from business_sites_helpers import PUBLIC_DOMAIN
    return {'business_id': pid, 'slug': '', 'domain': PUBLIC_DOMAIN, 'published': True, 'platform': True}

"""business_marketing.py — the marketing desk for one business: its API.

  GET  /marketing/{business_id}/engine                    owner + members   the desk, read
  GET  /marketing/{business_id}/ideas/next-slot           owner             the next open time
  POST /marketing/{business_id}/ideas                     owner             a new post (a draft, or post now)
  POST /marketing/{business_id}/approve                   owner             approve exact reviewed versions
  POST /marketing/{business_id}/slot/edit                 owner             change a post; it goes back to draft
  POST /marketing/{business_id}/slot/cancel               owner             skip a post
  POST /marketing/{business_id}/post-now                  owner             a reviewed post goes out in two minutes
  POST /marketing/{business_id}/posts/{post_id}/not-sent  owner             an unconfirmed delivery did not go out
  PUT  /marketing/{business_id}/settings                  owner             the desk's settings
  GET  /marketing/{business_id}/results                   owner + members   what came through the post links (B6)

B4 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md: Mission Control's
marketing desk (platform_marketing, /platform/marketing/*) for every business,
on the marketing_* tables (supabase/APPLY-2026-10-07-marketing-suite.sql)
through business_marketing_store.

WHO. Reading the desk is for the owner and the business's members
(business_access viewer role). Every change is the owner's alone: auth
(require_user) plus an owner check, a service-role read of
businesses.owner_id, like contacts_router and clip_posting. Posting puts the
business's name on public feeds; a member never approves, edits or posts.

NOTHING SENDS HERE. This module saves drafts, records approvals and moves
times. The sender (B5, `marketing_claim_due` every minute) is what hands an
approved post to Post for Me, and it re-checks everything at send time. "Post
now" therefore refuses until sending is switched on (MARKETING_DESK_PUBLISHING,
B5's switch, default off): an approval that nothing would act on is not a post.

THE LINK (B6, business_marketing_links). Every post of a business with a
site carries its own short link, {origin}/go/{code}, in publish_text; the
redirect behind it adds the tags (tracked_url) that let /results follow a
visit or a lead back to the post. Where it goes: the post's own link, else
the desk's, else the booking page when anything is bookable, else the site's
home. A business with no site posts with no link.

THE APPROVAL. A post's content_hash is business_marketing_store.digest: its
words (publish_text, short link included), where its link goes, media,
accounts and time. /approve binds exactly what the owner
reviewed ({id, revision, content_hash}) through marketing_approve, all or
nothing; any change to a post bumps its revision, recomputes the hash and puts
it back to draft.

THIS BUSINESS'S ROWS ONLY. Every post, picture, clip and account named in a
request is read with this business's id in the filter, so another business's
id answers exactly like a missing one.

FAIL CLOSED. A read that fails is a 503 in plain words, never an empty desk,
"no posts at that time" or "no accounts". Timestamps in query strings are
written with Z (a '+' would be read as a space).

THE LEVEL. GET /engine says how much of the work Chief does for this business
(`level`) from its real plan (feature_gates.plan_includes, which ignores
BILLING_ENFORCE), and the next step up (`upgrade`). The frontend reads these,
not useEntitlements().has(), which lets everything through.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import business_marketing_desk as reading
import business_marketing_links as links
import business_marketing_store as store
import feature_gates
import post_for_me
import sb_clients
import social_publish_router as social
from auth_supabase import AuthedUser, require_user
from business_access import business_access

router = APIRouter(prefix='/marketing/{business_id}', tags=['marketing-desk'])
log = logging.getLogger(__name__)

PROVIDER = 'post_for_me'                  # social_connect_router.PROVIDER: the accounts posts go to
CONNECTION_COLUMNS = 'id,business_id,platform,username,profile_photo_url,status,connected_at,provider_account_id'
EDITABLE = ('draft', 'approved', 'failed')
SENDABLE = ('draft', 'approved')
WINDOW = timedelta(hours=6)               # how long past its time a post may still go out (the platform's)
MAX_AHEAD = timedelta(days=90)
POST_NOW_LEAD = timedelta(minutes=2)      # the approve RPC needs a future time; the sender runs every minute
SLOT_AFTER = timedelta(hours=1)           # the next open time is at least this far away
OTHER_HOUR = 15                           # a one-off takes the desk's hour or 3:00 PM, as on the platform
SLOT_DAYS = 60
TAKEN_LIMIT = 1000
HEX64 = r'^[a-f0-9]{64}$'
Shape = Literal['story', 'wide']

CHANGED = 'A post changed or its time passed; refresh and review again'
STALE = ('This post changed since the desk was loaded, or it is already going out. '
         'Nothing was changed. Refresh the desk and try again.')
GONE_POST = 'A post here no longer exists. Refresh the desk.'
NOT_CONNECTED = "One of those accounts isn't connected to this business."
STORE_DOWN = 'The marketing desk could not be reached just now. Nothing was changed. Try again in a minute.'
READ_DOWN = "The marketing desk couldn't be read just now. Try again in a minute."
OWNER_ONLY = 'Only the business owner can change its marketing.'
# The owner's own "not sent" (an unconfirmed delivery they checked). The
# sender's delivery watch (business_marketing_dispatch) does not announce a
# failure the owner made themselves.
NOT_SENT_NOTE = 'Checked the accounts and marked not sent. Change it or give it a new time to post it again.'


def now() -> datetime:
    return datetime.now(timezone.utc)


def publishing_on() -> bool:
    """B5's switch: the desk's sender hands approved posts to Post for Me."""
    return (os.environ.get('MARKETING_DESK_PUBLISHING') or 'off').strip().lower() == 'on'


# ── who ───────────────────────────────────────────────────────────────

def _owner_row(business_id: str, user_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f'/businesses?id=eq.{business_id}&select=id,owner_id,type,availability:settings->availability,'
        'booking_page:settings->booking_page&limit=1')
    if rows is None:
        raise HTTPException(503, "Couldn't confirm this business just now. Nothing was changed. Try again in a minute.")
    if not rows:
        raise HTTPException(404, 'Business not found.')
    if str(rows[0].get('owner_id')) != str(user_id):
        raise HTTPException(403, OWNER_ONLY)
    return rows[0]


async def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """The owner check: a service-role read of businesses.owner_id against
    the signed-in person, independent of RLS. Returns the business row."""
    return await asyncio.to_thread(_owner_row, str(business_id), str(user.id))


async def _call(awaitable, *, down: str = STORE_DOWN):
    """A store call in plain words: a refusal is 409, an unreachable store 503."""
    try:
        return await awaitable
    except store.StoreConflict as exc:
        raise HTTPException(409, str(exc) or CHANGED) from None
    except store.StoreUnavailable:
        raise HTTPException(503, down) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc) or "That didn't read right.") from None


# ── the business's clock ──────────────────────────────────────────────

def _zone(name: Any) -> Optional[ZoneInfo]:
    name = str(name or '').strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def _availability(row: Dict[str, Any]) -> Any:
    if 'availability' in row:
        return row.get('availability')
    return (row.get('settings') or {}).get('availability')


def business_tz(row: Dict[str, Any]) -> ZoneInfo:
    """The engine's one chain (availability_engine.resolved_tz_name):
    availability.timezone, then the owner's practitioner_profiles.timezone,
    then PLATFORM_DEFAULT_TZ, then UTC. A name that does not resolve is
    skipped. A failed read of the profile refuses: posting at the wrong hour
    is not a safe default."""
    from availability import BusinessAvailability
    zone = _zone(BusinessAvailability.from_settings_dict(_availability(row)).timezone)
    if zone:
        return zone
    owner = row.get('owner_id')
    if owner:
        prof = sb_clients.sb_get_as_service(f'/practitioner_profiles?owner_id=eq.{owner}&select=timezone&limit=1')
        if prof is None:
            raise HTTPException(503, "Couldn't read this business's time zone just now. Try again in a minute.")
        zone = _zone(prof[0].get('timezone') if prof else None)
        if zone:
            return zone
    return _zone(os.environ.get('PLATFORM_DEFAULT_TZ')) or ZoneInfo('UTC')


# ── what the plan includes ────────────────────────────────────────────

LEVELS = ('suggest', 'week', 'openings', 'autopilot')
NEXT_FEATURE = {'suggest': 'marketing_week', 'week': 'marketing_autopilot',
                'openings': 'marketing_autopilot', 'autopilot': None}


def has_chair_calendar(row: Dict[str, Any]) -> bool:
    """A chair-and-appointment business (vertical_registry: personal_services)
    whose booking calendar is live: its booking page is published and it has
    an active booking_calendar module (booking_widget_router.booking_is_live).
    Read fail-closed: an unreadable calendar is a 503, not "no calendar"."""
    import vertical_registry
    if vertical_registry.resolve(str(row.get('type') or '')) != 'personal_services':
        return False
    settings = row.get('settings') if isinstance(row.get('settings'), dict) else {}
    page = settings.get('booking_page') if isinstance(settings.get('booking_page'), dict) else {}
    if not page.get('published'):
        return False
    rows = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{row['id']}&archetype=eq.booking_calendar&is_active=eq.true"
        '&select=id&limit=1')
    if rows is None:
        raise HTTPException(503, "Couldn't read the booking calendar just now. Try again in a minute.")
    return bool(rows)


def level_for(row: Dict[str, Any]) -> Dict[str, Any]:
    """How much of the work Chief does, from the business's real plan:
    autopilot (marketing_autopilot), openings (marketing_week on a chair
    business with a live calendar: Boss), week (marketing_week), else suggest.
    `upgrade` is the next level's feature and the cheapest plan that has it
    from where the business stands (feature_gates.upgrade_plan_for), or None
    at the top."""
    from billing_limits import PLAN_DISPLAY
    plan = feature_gates.plan_of(row)
    if feature_gates.plan_includes(row, 'marketing_autopilot'):
        level = 'autopilot'
    elif feature_gates.plan_includes(row, 'marketing_week'):
        level = 'openings' if has_chair_calendar(row) else 'week'
    else:
        level = 'suggest'
    feature = NEXT_FEATURE[level]
    up = feature_gates.upgrade_plan_for(feature, plan) if feature else None
    return {'level': level, 'plan': plan,
            'upgrade': {'feature': feature, 'plan': up, 'label': PLAN_DISPLAY.get(up, up.title())} if up else None}


# ── accounts ──────────────────────────────────────────────────────────

def _connected(business_id: str) -> List[Dict[str, Any]]:
    """The business's connected Post for Me accounts. Never None: a failed read refuses."""
    rows = sb_clients.sb_get_as_service(
        f'/social_connections?business_id=eq.{business_id}&provider=eq.{PROVIDER}&status=eq.connected'
        f'&order=connected_at.asc&select={CONNECTION_COLUMNS}')
    if rows is None:
        raise HTTPException(503, "Couldn't read the connected accounts just now. Nothing was changed. "
                                 'Try again in a minute.')
    return [r for r in rows if str(r.get('business_id')) == str(business_id)]


async def connected(business_id: str) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_connected, business_id)


def public_connection(row: Dict[str, Any], desk_ids=()) -> Dict[str, Any]:
    """An account as the desk shows it: display fields only."""
    return {'id': str(row['id']), 'platform': row.get('platform'),
            'label': social.post_for_me_label(str(row.get('platform') or '')),
            'username': row.get('username'), 'profile_photo_url': row.get('profile_photo_url'),
            'connected_at': row.get('connected_at'), 'in_desk': str(row['id']) in {str(i) for i in desk_ids}}


def _target(row: Dict[str, Any]) -> Dict[str, Any]:
    return {'connection_id': str(row['id']), 'platform': row['platform'], 'username': row.get('username'),
            'provider_account_id': row['provider_account_id']}


def pick_targets(accounts: List[Dict[str, Any]], desk: Optional[Dict[str, Any]],
                 connection_ids: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """The accounts a post goes to. Named: each must be one of this
    business's connected accounts. Not named: the desk's accounts (those
    still connected), or every connected account when the desk names none."""
    by_id = {str(a['id']): a for a in accounts}
    if connection_ids is not None:
        ids = list(dict.fromkeys(str(i) for i in connection_ids))
        if any(i not in by_id for i in ids):
            raise HTTPException(422, NOT_CONNECTED)
        chosen = [by_id[i] for i in ids]
    else:
        desk_ids = [str(i) for i in (desk or {}).get('connection_ids') or []]
        chosen = [by_id[i] for i in dict.fromkeys(desk_ids) if i in by_id] if desk_ids else list(by_id.values())
        if desk_ids and not chosen:
            raise HTTPException(422, "None of the desk's accounts is still connected. Reconnect one in Build, "
                                     'Social Media, or choose accounts for this post.')
    if not chosen:
        raise HTTPException(422, 'Connect an account first, in Build, Social Media.')
    return [_target(a) for a in chosen]


def media_kind(media: Optional[Dict[str, Any]]) -> Optional[str]:
    if (media or {}).get('clip_id'):
        return 'video'
    return 'image' if (media or {}).get('artwork_ids') else None


def fit(targets: List[Dict[str, Any]], kind: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(kept, dropped): Instagram needs a picture or video; TikTok and YouTube
    take only videos (the shared door's rules, social_publish_router)."""
    kept, dropped = [], []
    for t in targets:
        if t['platform'] in social.NEEDS_VIDEO and kind != 'video':
            dropped.append({'platform': t['platform'], 'username': t.get('username'), 'why': 'needs_video'})
        elif t['platform'] in social.NEEDS_MEDIA and kind is None:
            dropped.append({'platform': t['platform'], 'username': t.get('username'), 'why': 'needs_picture'})
        else:
            kept.append(t)
    return kept, dropped


def dropped_note(dropped: List[Dict[str, Any]]) -> Optional[str]:
    """'Instagram needs a picture, so this post leaves it out.'"""
    import image_posting
    why = image_posting.why_dropped(dropped)
    if not why:
        return None
    many = len({d['platform'] for d in dropped}) > 1
    return f"{'; '.join(why)}, so this post leaves {'them' if many else 'it'} out."


def _public_dropped(dropped):
    return [{'platform': d['platform'], 'label': social.post_for_me_label(d['platform']),
             'username': d.get('username'), 'why': d['why']} for d in dropped]


_PENDING = {'image': [{'url': 'https://picture.pending/design.jpg', 'kind': 'image'}],
            'video': [{'url': 'https://clip.pending/clip.mp4', 'kind': 'video'}], None: []}


def check_rules(caption: str, kind: Optional[str], targets: List[Dict[str, Any]]) -> None:
    """The shared door's rules (social_publish_router._check): words or a
    picture, each network's caption length, media where a network needs it."""
    try:
        social._check(caption, _PENDING[kind], targets)
    except HTTPException as exc:
        raise HTTPException(422, exc.detail) from None


def ready_to_post(fitted: List[Dict[str, Any]], kind: Optional[str], caption: str,
                  text: Optional[str] = None) -> List[Dict[str, Any]]:
    """The accounts left once fitted, or a plain refusal when none is. The
    caption must have words or a picture; what goes out (`text`: the
    caption with its short link) must fit each network."""
    kept, dropped = fit(fitted, kind)
    if not kept:
        import image_posting
        why = image_posting.why_dropped(dropped)
        raise HTTPException(422, f"None of those accounts can take this post ({'; '.join(why)}). Nothing was saved.")
    check_rules(caption, kind, kept)
    if text and text != caption:
        check_rules(text, kind, kept)
    return kept


# ── pictures and clips ────────────────────────────────────────────────

ART_COLUMNS = 'id,business_id,status,storage_path'


def _artwork(business_id: str, artwork_id: Any) -> Dict[str, Any]:
    """A ready Image Studio artwork of THIS business; another business's id
    answers like a missing one."""
    rows = sb_clients.sb_get_as_service(
        f'/image_artworks?id=eq.{UUID(str(artwork_id))}&business_id=eq.{business_id}&select={ART_COLUMNS}&limit=1')
    if rows is None:
        raise HTTPException(503, "Couldn't read that picture just now. Nothing was saved. Try again in a minute.")
    if not rows or str(rows[0].get('business_id')) != str(business_id):
        raise HTTPException(404, "That picture isn't in this business's Media Library.")
    row = rows[0]
    if row.get('status') in ('queued', 'working'):
        raise HTTPException(409, 'That picture is still being made. Add it once it is ready.')
    if row.get('status') != 'ready' or not row.get('storage_path'):
        raise HTTPException(409, "That picture didn't finish, so it can't be posted.")
    return row


async def build_media(business_id: str, *, artwork_id=None, clip_id=None, clip_fingerprint=None,
                      covers=None) -> Dict[str, Any]:
    """The media a post binds: a ready picture of this business, or a ready
    clip of this business approved as it is now (its review fingerprint) with
    the covers chosen for it (none: the newest ready cover of each shape; {}:
    no cover). Nothing is fetched or published here."""
    if artwork_id and clip_id:
        raise HTTPException(422, 'A post carries a clip or a picture, not both.')
    if (covers is not None or clip_fingerprint) and not clip_id:
        raise HTTPException(422, 'Choose the clip along with its covers.')
    if artwork_id:
        row = await asyncio.to_thread(_artwork, business_id, artwork_id)
        return {'artwork_ids': [str(row['id'])]}
    if clip_id:
        import clip_posting
        import media_library
        row = await asyncio.to_thread(clip_posting._clip, business_id, str(UUID(str(clip_id))))
        problem = clip_posting.approval_problem(row)
        if problem == 'unapproved':
            raise HTTPException(409, 'Approve this clip in Ready to post before adding it to a post.')
        if problem == 'changed':
            raise HTTPException(409, 'This clip changed after it was approved. Check it and approve it again first.')
        fingerprint = media_library.fingerprint(row)
        if clip_fingerprint and clip_fingerprint != fingerprint:
            raise HTTPException(409, 'This clip changed since you opened it. Open it again and check it first.')
        wanted = None if covers is None else {str(k): str(v) for k, v in covers.items()}
        found = await asyncio.to_thread(clip_posting.ready_covers, business_id, str(row['id']), wanted)
        return {'clip_id': str(row['id']), 'clip_fingerprint': fingerprint,
                'covers': {shape: str(art['id']) for shape, art in sorted(found.items())}}
    return {}


# ── the link a post carries ───────────────────────────────────────────

SITE_DOWN = "Couldn't read this business's site just now. Nothing was changed. Try again in a minute."
OFF_SITE = ('Use a link to your own site or booking page. Links elsewhere are not tracked '
            'or checked, so the desk does not post them.')


def _site(business_id: str) -> Optional[Dict[str, Any]]:
    """The business's site (business_marketing_links.site_for), or None when it has none."""
    try:
        return links.site_for(business_id)
    except links.LinksUnavailable:
        raise HTTPException(503, SITE_DOWN) from None


def _own_hosts(business_id: str) -> set:
    """The hosts this business's site and booking page answer on: its
    platform subdomain, and its custom domain once verified (a pending one
    has no DNS yet, and a dead link in a post is worse than none)."""
    return set(links.own_hosts(_site(business_id)))


_UNREAD = object()


def landing_url(business_id: str, raw: Optional[str], site: Any = _UNREAD) -> Optional[str]:
    """A post's link: empty, or an https page on the business's own site or
    booking page. `site`: the business's site when the caller already read it."""
    value = (raw or '').strip()
    if not value:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise HTTPException(422, "That link didn't read right. Use your own site's https address.") from None
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or not host or parts.username or parts.password or port not in (None, 443):
        raise HTTPException(422, "Use an https link to your own site or booking page.")
    hosts = _own_hosts(business_id) if site is _UNREAD else links.own_hosts(site)
    if host not in hosts:
        raise HTTPException(422, OFF_SITE)
    return value


def default_landing(business_id: str, business: Dict[str, Any], site: Optional[Dict[str, Any]],
                    desk: Optional[Dict[str, Any]]) -> Optional[str]:
    """Where a post goes when it names no link of its own: the desk's link
    (while it is still on the business's own site), else the booking page
    when anything is bookable, else the site's home, else nowhere (no site)."""
    chosen = (desk or {}).get('landing_url')
    if chosen and links.on_site(chosen, site):
        return chosen
    try:
        return links.default_landing(business_id, business, site)
    except links.LinksUnavailable:
        raise HTTPException(503, "Couldn't read this business's booking page just now. Nothing was changed. "
                                 'Try again in a minute.') from None


def link_fields(post_id: str, caption: str, landing: Optional[str], site: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """landing_url, tracked_url, link_code and publish_text for a post."""
    try:
        return links.fields(post_id, caption, landing, site)
    except ValueError:
        raise HTTPException(422, OFF_SITE) from None


# ── time ──────────────────────────────────────────────────────────────

def _aware(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(422, "That date and time didn't read right.") from None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise HTTPException(422, 'Choose a time with its time zone.')
    return value.astimezone(timezone.utc)


def schedule(run_at: Any, expires_at: Any = None) -> Tuple[datetime, datetime]:
    run = _aware(run_at)
    if not now() < run <= now() + MAX_AHEAD:
        raise HTTPException(422, 'Choose a time in the next 90 days.')
    expires = _aware(expires_at) if expires_at else run + WINDOW
    if expires <= run:
        raise HTTPException(422, 'A post stops trying after its time, not before it.')
    return run, expires


def open_hours(post_hour: Any) -> Tuple[int, ...]:
    """The desk's posting hour and 3:00 PM (11:00 and 3:00 PM by default, as
    on the platform desk)."""
    try:
        hour = int(post_hour)
    except (TypeError, ValueError):
        hour = 11
    hour = hour if 6 <= hour <= 21 else 11
    return tuple(sorted({hour, OTHER_HOUR}))


async def next_open_slot(business_id: str, tz: ZoneInfo, post_hour: Any = 11,
                         at: Optional[datetime] = None) -> datetime:
    """The soonest weekday at the desk's hour or 3:00 PM, on the business's
    own clock (so across a daylight-saving change it stays the local hour),
    at least an hour away, with no post of this business at that time."""
    at = at or now()
    since, until = reading.query_time(at), reading.query_time(at + timedelta(days=SLOT_DAYS + 2))
    taken_rows = await _call(store.rows(
        f'/marketing_posts?business_id=eq.{business_id}&select=run_at&status=not.in.(cancelled,pulled)'
        f'&run_at=gte.{since}&run_at=lt.{until}&order=run_at.asc&limit={TAKEN_LIMIT}'), down=READ_DOWN)
    if len(taken_rows) >= TAKEN_LIMIT:
        raise HTTPException(503, 'The calendar is too full to find an open time. Choose a time for this post.')
    taken = {_aware(r['run_at']).timestamp() for r in taken_rows}
    local = at.astimezone(tz)
    for offset in range(SLOT_DAYS):
        day = local.date() + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for hour in open_hours(post_hour):
            slot = datetime.combine(day, time(hour), tz)
            if slot > at + SLOT_AFTER and slot.timestamp() not in taken:
                return slot
    raise HTTPException(422, 'There is no open weekday time in the next 60 days. Choose a time for this post.')


# ── the desk row ──────────────────────────────────────────────────────

DESK_DEFAULTS = {'plan_enabled': False, 'paused': False, 'connection_ids': [], 'post_hour': 11,
                 'audience': None, 'landing_url': None, 'work_photo_ids': []}
DESK_PUBLIC = ('plan_enabled', 'paused', 'connection_ids', 'post_hour', 'audience', 'landing_url',
               'work_photo_ids', 'updated_at')


def public_desk(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    row = row or {}
    out = {k: row.get(k, DESK_DEFAULTS.get(k)) for k in DESK_PUBLIC}
    out['connection_ids'] = [str(i) for i in out['connection_ids'] or []]
    out['work_photo_ids'] = [str(i) for i in out['work_photo_ids'] or []]
    out['exists'] = bool(row)
    return out


async def ensure_desk(business_id: str) -> Dict[str, Any]:
    """The business's desk row, made with its defaults when it has none (the
    sender never claims a post whose business has no desk row)."""
    desk = await _call(store.get_desk(business_id))
    if desk is not None:
        return desk
    try:
        made = await store.request('POST', '/marketing_desks', {'business_id': business_id})
    except store.StoreConflict:
        made = None                     # another request made it first
    except store.StoreUnavailable:
        raise HTTPException(503, STORE_DOWN) from None
    if isinstance(made, list) and made:
        return made[0]
    desk = await _call(store.get_desk(business_id))
    if desk is None:
        raise HTTPException(503, STORE_DOWN)
    return desk


# ── posts ─────────────────────────────────────────────────────────────

def idea_post_id(business_id: str, idea_id: Any) -> str:
    """The post's id from the caller's idea id: a retried save is the same
    post, and two businesses can never collide on one id."""
    return str(uuid5(NAMESPACE_URL, f'marketing-idea:{business_id}:{UUID(str(idea_id))}'))


def new_post(business_id: str, post_id: str, *, caption: str, media: Dict[str, Any],
             targets: List[Dict[str, Any]], run_at: datetime, expires_at: datetime,
             landing: Optional[str], source: str = 'owner',
             site: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A draft row. With a landing on the business's site, it carries its
    tracked link (link_fields); without one, the caption goes out as written."""
    row = {'id': post_id, 'business_id': business_id, 'source': source, 'caption': caption,
           **link_fields(post_id, caption, landing, site),
           'media': media, 'targets': targets, 'run_at': run_at.isoformat(), 'expires_at': expires_at.isoformat(),
           'status': 'draft', 'revision': 1, 'design_status': 'none'}
    row['content_hash'] = store.digest(row)
    return row


def changed(row: Dict[str, Any], **content) -> Dict[str, Any]:
    """The patch for a changed post: the new content, the next revision, a
    fresh content_hash, and back to draft with its approval dropped. A new
    caption or link comes with its publish_text (link_fields), so the words
    that go out are never stale."""
    patch = dict(content)
    if ('caption' in patch or 'landing_url' in patch) and 'publish_text' not in patch:
        raise ValueError('A changed caption or link needs its publish_text (link_fields).')
    for key in ('run_at', 'expires_at'):
        if isinstance(patch.get(key), datetime):
            patch[key] = patch[key].isoformat()
    patch.update(revision=int(row['revision']) + 1, status='draft', approved_hash=None, approved_by=None,
                 approved_at=None, approved_via=None, error=None)
    patch['content_hash'] = store.digest({**row, **patch})
    return patch


async def _write_post(business_id: str, row: Dict[str, Any], patch: Dict[str, Any], statuses) -> Optional[Dict[str, Any]]:
    """Patch one post only if it is still at the revision and in a state the
    caller checked. None when it moved on in the meantime."""
    out = await _call(store.request(
        'PATCH', f"/marketing_posts?id=eq.{row['id']}&business_id=eq.{business_id}"
                 f"&revision=eq.{int(row['revision'])}&status=in.({','.join(statuses)})", patch))
    return out[0] if isinstance(out, list) and out else None


async def _slot_rows(business_id: str, items, statuses) -> List[Dict[str, Any]]:
    """Every post named, checked BEFORE anything is written: this business's,
    at the revision the caller saw, in a state that allows the change."""
    ids = [str(i.id) for i in items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, 'Name each post once.')
    rows = []
    for item in items:
        row = await _call(store.get_post(business_id, item.id), down=READ_DOWN)
        if not row:
            raise HTTPException(409, GONE_POST)
        if row.get('revision') != item.revision or row.get('status') not in statuses:
            raise HTTPException(409, STALE)
        if row.get('design_status') == 'designing':
            raise HTTPException(409, 'A flyer is still being made for this post. Change it when the flyer is ready.')
        rows.append(row)
    return rows


async def _write_all(business_id: str, pairs, statuses, what: str) -> List[Dict[str, Any]]:
    """Write each (row, patch). A write that fails after others succeeded says
    exactly which posts changed."""
    done = []
    for row, patch in pairs:
        saved = await _write_post(business_id, row, patch, statuses)
        if saved is None:
            if not done:
                raise HTTPException(409, STALE)
            raise HTTPException(409, f"Only part of this was {what}: {len(done)} of {len(pairs)} posts changed. "
                                     'Refresh the desk and try again.')
        done.append(saved)
    return done


# What a post-now restores when its approval is refused: the post's own
# time, state and approval, exactly as the owner left them.
_RESTORED = ('run_at', 'expires_at', 'status', 'content_hash', 'approved_hash', 'approved_by',
             'approved_at', 'approved_via', 'error')


async def _put_back(business_id: str, moved: List[Dict[str, Any]], originals: List[Dict[str, Any]]) -> bool:
    """Undo a post-now move whose approval was refused. Each write only lands
    if the post is still the draft the move made (nothing else touched it);
    the revision moves on once more so an open screen refreshes. True when
    every post is back."""
    by_id = {str(o['id']): o for o in originals}
    ok = True
    for row in moved:
        original = by_id.get(str(row['id']))
        if not original:
            ok = False
            continue
        patch = {k: original.get(k) for k in _RESTORED}
        patch['revision'] = int(row['revision']) + 1
        try:
            saved = await _write_post(business_id, row, patch, ('draft',))
        except HTTPException:
            saved = None
        ok = ok and saved is not None
    return ok


async def approve_rows(business_id: str, rows: List[Dict[str, Any]], actor: str) -> int:
    items = [{'id': str(r['id']), 'revision': int(r['revision']), 'content_hash': r['content_hash']} for r in rows]
    return await _call(store.approve(business_id, items, actor=actor, via='owner'))


def _sendable_now(business_id: str, desk: Optional[Dict[str, Any]]) -> None:
    """Why nothing can go out right away, before anything is saved or moved."""
    if not publishing_on():
        raise HTTPException(409, 'Sending from the marketing desk is not switched on yet, so nothing can go out '
                                 'right away. Nothing was changed.')
    social._require_pilot(business_id)
    if desk and desk.get('paused'):
        raise HTTPException(409, 'Posting is paused. Resume it on the desk, then post again. Nothing was changed.')


# ── request bodies ────────────────────────────────────────────────────

class Idea(BaseModel):
    """One new post, written once, for every account it goes to."""
    model_config = ConfigDict(extra='forbid')
    id: UUID = Field(default_factory=uuid4)          # the caller's: a retry with the same id is not a second post
    caption: str = Field(default='', max_length=5000)
    artwork_id: Optional[UUID] = None
    clip_id: Optional[UUID] = None
    clip_fingerprint: Optional[str] = Field(default=None, pattern=HEX64)
    covers: Optional[Dict[Shape, UUID]] = None       # None: newest ready cover of each shape; {}: none
    connection_ids: Optional[List[UUID]] = Field(default=None, min_length=1, max_length=10)
    run_at: Optional[datetime] = None                # None: the next open time
    expires_at: Optional[datetime] = None
    # None or '': the desk's link, else the booking page (anything bookable), else the site's home
    landing_url: Optional[str] = Field(default=None, max_length=1500)
    post_now: bool = False                           # the owner's own "Post now": approved, out in minutes


class ReviewItem(BaseModel):
    id: UUID
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=HEX64)


class Review(BaseModel):
    items: List[ReviewItem] = Field(min_length=1, max_length=store.MAX_APPROVE)


class PostNow(BaseModel):
    items: List[ReviewItem] = Field(min_length=1, max_length=10)


class SlotItem(BaseModel):
    id: UUID
    revision: int = Field(ge=1)


class SlotEdit(BaseModel):
    """A change to a post (or a few, the same change to each). Any change puts
    it back to draft for review."""
    model_config = ConfigDict(extra='forbid')
    items: List[SlotItem] = Field(min_length=1, max_length=10)
    caption: Optional[str] = Field(default=None, max_length=5000)
    run_at: Optional[datetime] = None
    connection_ids: Optional[List[UUID]] = Field(default=None, min_length=1, max_length=10)
    artwork_id: Optional[UUID] = None
    clip_id: Optional[UUID] = None
    clip_fingerprint: Optional[str] = Field(default=None, pattern=HEX64)
    covers: Optional[Dict[Shape, UUID]] = None
    remove_media: bool = False
    landing_url: Optional[str] = Field(default=None, max_length=1500)   # '': back to the default link


class SlotCancel(BaseModel):
    items: List[SlotItem] = Field(min_length=1, max_length=30)


class Revision(BaseModel):
    revision: int = Field(ge=1)


class Settings(BaseModel):
    """Only the fields sent change. connection_ids [] means every connected account."""
    model_config = ConfigDict(extra='forbid')
    paused: Optional[bool] = None
    plan_enabled: Optional[bool] = None
    connection_ids: Optional[List[UUID]] = Field(default=None, max_length=20)
    post_hour: Optional[int] = Field(default=None, ge=6, le=21)
    audience: Optional[str] = Field(default=None, max_length=600)
    landing_url: Optional[str] = Field(default=None, max_length=1500)


# ── read ──────────────────────────────────────────────────────────────

@router.get('/engine')
async def engine(business_id: UUID, biz: dict = Depends(business_access('viewer'))):
    """The desk for this business: its settings, this week's and next week's
    posts, Chief's read and what needs a look, how much Chief does (level)
    and the next step up (upgrade), and its connected accounts."""
    bid = str(business_id)
    at = now()
    tz = await asyncio.to_thread(business_tz, biz)
    plan = await asyncio.to_thread(level_for, biz)
    accounts = await connected(bid)
    try:
        state = await reading.read_state(bid, tz=tz, now=at, connections=accounts, strict=True)
    except store.StoreError:
        raise HTTPException(503, READ_DOWN) from None
    import marketing_engine
    runs = state['runs'] or []
    latest = runs[0] if runs else None
    role = biz.get('_caller_role')
    desk = state['desk']
    return {
        'business_id': bid, 'role': role, 'can_edit': role == 'owner',
        **plan,
        'time_zone': tz.key,
        'desk': public_desk(desk),
        'connections': [public_connection(a, (desk or {}).get('connection_ids') or ()) for a in accounts],
        'posting': {'configured': post_for_me.configured(), 'allowed': post_for_me.allowed_for(bid),
                    'sending': publishing_on()},
        **reading.weeks(state),
        'latest': latest, 'planning': marketing_engine.is_planning(latest, at),
        'truncated': len(state['posts'] or []) >= reading.POSTS_LIMIT,
        **reading.desk(state),
    }


@router.get('/ideas/next-slot')
async def next_slot_route(business_id: UUID, user: AuthedUser = Depends(require_user)):
    bid = str(business_id)
    row = await _require_owner(bid, user)
    tz = await asyncio.to_thread(business_tz, row)
    desk = await _call(store.get_desk(bid), down=READ_DOWN)
    slot = await next_open_slot(bid, tz, (desk or {}).get('post_hour', 11))
    import marketing_desk as words
    return {'run_at': slot.astimezone(timezone.utc).isoformat(), 'time_zone': tz.key,
            'when': f'{words.day_name(slot, tz)} {words.clock(slot, tz)}'}


# ── new posts ─────────────────────────────────────────────────────────

async def create_idea(business_id: str, business: Dict[str, Any], req: Idea, actor: str) -> Dict[str, Any]:
    """Save one post (a draft) for every chosen account; with post_now, also
    approve it as the owner's, due in two minutes. Every check runs before
    anything is written."""
    bid = business_id
    desk = await _call(store.get_desk(bid), down=READ_DOWN)
    if req.post_now:
        _sendable_now(bid, desk)
    accounts = await connected(bid)
    media = await build_media(bid, artwork_id=req.artwork_id, clip_id=req.clip_id,
                              clip_fingerprint=req.clip_fingerprint, covers=req.covers)
    kind = media_kind(media)
    caption = (req.caption or '').strip()
    chosen = pick_targets(accounts, desk, req.connection_ids)
    _, dropped = fit(chosen, kind)
    site = await asyncio.to_thread(_site, bid)
    landing = await asyncio.to_thread(landing_url, bid, req.landing_url, site)
    if landing is None:
        landing = await asyncio.to_thread(default_landing, bid, business, site, desk)
    post_id = idea_post_id(bid, req.id)
    link = link_fields(post_id, caption, landing, site)
    targets = ready_to_post(chosen, kind, caption, link['publish_text'])
    if req.post_now:
        run_at, expires_at = schedule(now() + POST_NOW_LEAD)
    elif req.run_at is not None:
        run_at, expires_at = schedule(req.run_at, req.expires_at)
    else:
        tz = await asyncio.to_thread(business_tz, business)
        run_at, expires_at = schedule(await next_open_slot(bid, tz, (desk or {}).get('post_hour', 11)),
                                      req.expires_at)
    out = {'dropped': _public_dropped(dropped), 'note': dropped_note(dropped),
           'accounts': [social.post_for_me_label(t['platform']) for t in targets],
           'link': links.short_link(site, link['link_code']) if link['tracked_url'] else None}

    existing = await _call(store.get_post(bid, post_id), down=READ_DOWN)
    if existing is None:
        if desk is None:
            await ensure_desk(bid)
        row = new_post(bid, post_id, caption=caption, media=media, targets=targets, run_at=run_at,
                       expires_at=expires_at, landing=landing, site=site)
        try:
            saved = await store.request('POST', '/marketing_posts', row)
            existing, already = (saved[0] if isinstance(saved, list) and saved else row), False
        except store.StoreConflict:
            # Two taps at once: the other one saved this post first.
            existing, already = await _call(store.get_post(bid, post_id), down=READ_DOWN), True
            if existing is None:
                raise HTTPException(409, CHANGED) from None
        except store.StoreUnavailable:
            raise HTTPException(503, STORE_DOWN) from None
    else:
        already = True
    if req.post_now:
        if already and _aware(existing['run_at']) > now() + POST_NOW_LEAD + timedelta(minutes=1):
            # Saved earlier for a later time, not by a "post now": it stays at its time.
            raise HTTPException(409, 'This post is already on the desk for a later time. Use Approve and post now '
                                     'there to send it now.')
        if existing['status'] == 'draft':
            if _aware(existing['run_at']) <= now():
                raise HTTPException(409, 'An earlier try saved this post, but its time passed before it was '
                                         'approved. It is on the desk: use Approve and post now there.')
            await approve_rows(bid, [existing], actor)
            existing = await _call(store.get_post(bid, post_id), down=READ_DOWN) or existing
        elif existing['status'] != 'approved':
            raise HTTPException(409, STALE)
    return {**out, 'post': reading.public_post(existing), 'run_at': existing['run_at'],
            'already_saved': already, 'posting': bool(req.post_now)}


@router.post('/ideas')
async def create_idea_route(business_id: UUID, req: Idea, user: AuthedUser = Depends(require_user)):
    bid = str(business_id)
    business = await _require_owner(bid, user)
    return await create_idea(bid, business, req, str(user.id))


# ── approve ───────────────────────────────────────────────────────────

@router.post('/approve')
async def approve_route(business_id: UUID, req: Review, user: AuthedUser = Depends(require_user)):
    """Approve every one of these exact reviewed versions, or none of them
    (marketing_approve). Each must be this business's, and every account it
    goes to still connected."""
    bid = str(business_id)
    await _require_owner(bid, user)
    live = {str(a['id']) for a in await connected(bid)}
    for item in req.items:
        row = await _call(store.get_post(bid, item.id), down=READ_DOWN)
        if not row:
            raise HTTPException(409, CHANGED)
        if any(str(t.get('connection_id')) not in live for t in row.get('targets') or []):
            raise HTTPException(409, 'An account this post goes to is no longer connected. Change its accounts, '
                                     'then approve it again.')
    count = await _call(store.approve(bid, [i.model_dump(mode='json') for i in req.items],
                                      actor=str(user.id), via='owner'))
    return {'approved': count}


# ── change, skip ──────────────────────────────────────────────────────

LINK_GONE = ("This post's link no longer goes to your own site. Choose a new link for it (or leave the link "
             'empty for your booking page or home), then save again. Nothing was changed.')


def _business_row(business_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f'/businesses?id=eq.{business_id}&select=id,booking_page:settings->booking_page&limit=1')
    if rows is None:
        raise HTTPException(503, "Couldn't confirm this business just now. Nothing was changed. Try again in a minute.")
    if not rows:
        raise HTTPException(404, 'Business not found.')
    return rows[0]


async def edit_slot(business_id: str, req: SlotEdit, business: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Change the words, time, accounts, picture or link of a post. Every post
    is checked and every changed post validated before any is saved; each
    goes back to draft with a new revision and content_hash. Its link is
    rebuilt on the business's site as it is now: the link sent, else the
    post's own (refused if it has left the site), else the default."""
    bid = business_id
    sent = {k for k in ('caption', 'run_at', 'connection_ids', 'artwork_id', 'clip_id') if getattr(req, k) is not None}
    if req.remove_media:
        sent.add('remove_media')
    if 'landing_url' in req.model_fields_set:
        sent.add('landing_url')
    if not sent:
        raise HTTPException(422, 'Change the words, the time, the accounts, the picture or the link.')
    if req.remove_media and (req.artwork_id or req.clip_id):
        raise HTTPException(422, 'Remove the picture or choose a new one, not both.')
    rows = await _slot_rows(bid, req.items, EDITABLE)
    new_media = None
    if req.artwork_id or req.clip_id or req.covers is not None or req.clip_fingerprint:
        new_media = await build_media(bid, artwork_id=req.artwork_id, clip_id=req.clip_id,
                                      clip_fingerprint=req.clip_fingerprint, covers=req.covers)
    elif req.remove_media:
        new_media = {}
    accounts = await connected(bid) if req.connection_ids is not None else None
    site = await asyncio.to_thread(_site, bid)
    sent_landing = None
    if 'landing_url' in sent:
        sent_landing = await asyncio.to_thread(landing_url, bid, req.landing_url, site)
    fallback: Any = _UNREAD
    moved = schedule(req.run_at) if req.run_at is not None else None
    pairs, notes, dropped_all = [], [], []
    for row in rows:
        caption = req.caption.strip() if req.caption is not None else (row.get('caption') or '')
        media = new_media if new_media is not None else (row.get('media') or {})
        kind = media_kind(media)
        chosen = (pick_targets(accounts, None, req.connection_ids) if accounts is not None
                  else list(row.get('targets') or []))
        _, dropped = fit(chosen, kind)
        if sent_landing is not None:
            landing = sent_landing
        elif 'landing_url' not in sent and row.get('landing_url'):
            landing = row['landing_url']
            if not links.on_site(landing, site):
                raise HTTPException(422, LINK_GONE)
        else:
            if fallback is _UNREAD:
                desk = await _call(store.get_desk(bid), down=READ_DOWN)
                if business is None:
                    business = await asyncio.to_thread(_business_row, bid)
                fallback = await asyncio.to_thread(default_landing, bid, business, site, desk)
            landing = fallback
        link = link_fields(str(row['id']), caption, landing, site)
        targets = ready_to_post(chosen, kind, caption, link['publish_text'])
        dropped_all += dropped
        content = {'caption': caption, 'media': media, 'targets': targets, **link}
        if moved:
            # A new time gets a fresh delivery window; the old one would end before it.
            content['run_at'], content['expires_at'] = moved
        pairs.append((row, changed(row, **content)))
    saved = await _write_all(bid, pairs, EDITABLE, 'changed')
    note = dropped_note(dropped_all)
    return {'posts': [reading.public_post(r) for r in saved], 'dropped': _public_dropped(dropped_all),
            'note': note}


@router.post('/slot/edit')
async def edit_slot_route(business_id: UUID, req: SlotEdit, user: AuthedUser = Depends(require_user)):
    bid = str(business_id)
    business = await _require_owner(bid, user)
    return await edit_slot(bid, req, business)


@router.post('/slot/cancel')
async def cancel_slot_route(business_id: UUID, req: SlotCancel, user: AuthedUser = Depends(require_user)):
    """Skip a post, or let missed drafts go, after checking every one can be."""
    bid = str(business_id)
    await _require_owner(bid, user)
    rows = await _slot_rows(bid, req.items, EDITABLE)
    pairs = [(row, {'status': 'cancelled', 'revision': int(row['revision']) + 1}) for row in rows]
    saved = await _write_all(bid, pairs, EDITABLE, 'skipped')
    return {'cancelled': len(saved), 'posts': [reading.public_post(r) for r in saved]}


# ── post now ──────────────────────────────────────────────────────────

async def post_existing_now(business_id: str, items: List[ReviewItem], actor: str) -> Dict[str, Any]:
    """A waiting (or approved, or missed) post goes out now, exactly as
    reviewed: each must still carry the revision and content the owner saw.
    Only its time changes, to two minutes from now, and the owner's approval
    follows in the same step. Every check runs before anything is moved."""
    bid = business_id
    desk = await _call(store.get_desk(bid), down=READ_DOWN)
    _sendable_now(bid, desk)
    live = {str(a['id']) for a in await connected(bid)}
    ids = [str(i.id) for i in items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, 'Name each post once.')
    rows = []
    for item in items:
        row = await _call(store.get_post(bid, item.id), down=READ_DOWN)
        if (not row or row.get('status') not in SENDABLE or row.get('revision') != item.revision
                or row.get('content_hash') != item.content_hash):
            raise HTTPException(409, 'This post changed since it was reviewed, or it is no longer waiting. '
                                     'Nothing was sent. Refresh and review it again.')
        if row.get('design_status') == 'designing':
            raise HTTPException(409, 'A flyer is still being made for this post. Nothing was sent.')
        targets = list(row.get('targets') or [])
        if not targets or any(str(t.get('connection_id')) not in live for t in targets):
            raise HTTPException(409, 'An account this post goes to is no longer connected. Nothing was sent.')
        kind = media_kind(row.get('media'))
        kept, dropped = fit(targets, kind)
        if dropped:
            import image_posting
            raise HTTPException(409, f"{'; '.join(image_posting.why_dropped(dropped))}. Change the post's accounts "
                                     'or add a picture. Nothing was sent.')
        check_rules(row.get('publish_text') or row.get('caption') or '', kind, kept)
        rows.append(row)
    run_at, expires_at = schedule(now() + POST_NOW_LEAD)
    moved = await _write_all(bid, [(r, changed(r, run_at=run_at, expires_at=expires_at)) for r in rows],
                             SENDABLE, 'moved')
    try:
        await approve_rows(bid, moved, actor)
    except HTTPException as exc:
        if exc.status_code != 409:
            # The store did not answer: the approval may or may not have
            # happened, so nothing is undone on a guess.
            raise HTTPException(exc.status_code, 'The posts were moved to now, but the approval could not be '
                                                 'confirmed. Refresh the desk before trying again.') from None
        # marketing_approve is all-or-nothing, so none was approved: put each
        # post back exactly as it was (review of #1313), or say what moved.
        back = await _put_back(bid, moved, rows)
        raise HTTPException(409, (f'{exc.detail} Nothing was sent, and the posts are back as they were.' if back else
                                  f'{exc.detail} Nothing was sent, but the posts were moved to now and are drafts '
                                  'again: review and approve them on the desk.')) from None
    after = [await _call(store.get_post(bid, r['id']), down=READ_DOWN) or r for r in moved]
    return {'posts': [reading.public_post(r) for r in after], 'posting': True, 'run_at': after[0]['run_at']}


@router.post('/post-now')
async def post_now_route(business_id: UUID, req: PostNow, user: AuthedUser = Depends(require_user)):
    bid = str(business_id)
    await _require_owner(bid, user)
    return await post_existing_now(bid, req.items, str(user.id))


@router.post('/posts/{post_id}/not-sent')
async def mark_not_sent(business_id: UUID, post_id: UUID, req: Revision, user: AuthedUser = Depends(require_user)):
    """The owner checked the accounts and the post is not there: an
    unconfirmed delivery becomes a plain failure, which can be changed and
    approved again."""
    bid = str(business_id)
    await _require_owner(bid, user)
    rows = await _call(store.request(
        'PATCH', f'/marketing_posts?id=eq.{post_id}&business_id=eq.{bid}&revision=eq.{req.revision}'
                 '&status=eq.uncertain',
        {'status': 'failed', 'revision': req.revision + 1, 'checked_at': now().isoformat(),
         'error': NOT_SENT_NOTE}))
    if not rows:
        raise HTTPException(409, 'Only an unconfirmed delivery can be marked not sent. Refresh the desk.')
    return {'post': reading.public_post(rows[0])}


# ── settings ──────────────────────────────────────────────────────────

@router.put('/settings')
async def save_settings(business_id: UUID, req: Settings, user: AuthedUser = Depends(require_user)):
    """The desk's settings. Creates the desk row if the business has none."""
    bid = str(business_id)
    await _require_owner(bid, user)
    sent = req.model_fields_set
    patch: Dict[str, Any] = {}
    for key in ('paused', 'plan_enabled', 'post_hour'):
        if key in sent:
            if getattr(req, key) is None:
                raise HTTPException(422, f'Choose a value for {key.replace("_", " ")}.')
            patch[key] = getattr(req, key)
    if 'connection_ids' in sent:
        ids = list(dict.fromkeys(str(i) for i in req.connection_ids or []))
        if ids:
            live = {str(a['id']) for a in await connected(bid)}
            if any(i not in live for i in ids):
                raise HTTPException(422, NOT_CONNECTED)
        patch['connection_ids'] = ids
    if 'audience' in sent:
        patch['audience'] = (req.audience or '').strip() or None
    if 'landing_url' in sent:
        patch['landing_url'] = await asyncio.to_thread(landing_url, bid, req.landing_url)
    desk = await _call(store.get_desk(bid), down=READ_DOWN)
    if desk is None:
        try:
            made = await store.request('POST', '/marketing_desks', {'business_id': bid, **patch})
            return {'desk': public_desk(made[0] if isinstance(made, list) and made else None)}
        except store.StoreConflict:
            pass                        # made a moment ago by another request: change it below
        except store.StoreUnavailable:
            raise HTTPException(503, STORE_DOWN) from None
    if not patch:
        return {'desk': public_desk(desk or await _call(store.get_desk(bid), down=READ_DOWN))}
    saved = await _call(store.request('PATCH', f'/marketing_desks?business_id=eq.{bid}', patch))
    if not saved:
        raise HTTPException(503, STORE_DOWN)
    return {'desk': public_desk(saved[0])}


# ── results ───────────────────────────────────────────────────────────

@router.get('/results')
async def results_route(business_id: UUID, biz: dict = Depends(business_access('viewer'))):
    """What came through the links in this business's posts over the last 30
    days, per post and in total (business_marketing_outcomes). Recorded, never
    causal: "came through", not "brought". A source that cannot be read is
    unavailable, never 0; the posts themselves unreadable is a 503."""
    import business_marketing_outcomes as outcomes
    try:
        return await outcomes.for_business(str(business_id), now=now())
    except store.StoreError:
        raise HTTPException(503, READ_DOWN) from None

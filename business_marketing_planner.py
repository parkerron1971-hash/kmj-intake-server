"""business_marketing_planner.py — Chief's weekly suggestion for every business, and the hourly fan-out.

B8 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (D2's flyers and fan-out
rules). A business at the `suggest` level (its real plan includes
marketing_suggestion and not marketing_week: Starter, Solo, Booked) gets ONE
suggested post a week, as a draft on its marketing desk, to approve or skip.

  run_suggestion(business_id, trigger=)   one business's suggestion for one week
  marketing_tick()                        hourly, on the worker: every business that is due
  manual_tick()                           every minute, on the worker: the owner's queued requests
  POST /marketing/{business_id}/engine/run   owner: queue a suggestion now (the worker writes it)
  GET  /marketing/{business_id}/preview      owner: what Chief would write about, read-only

ONE SUGGESTION
  claim the week (marketing_claim_run, kind suggestion: one run per business
  per week) -> the business's numbers, profile and facts (B7) -> diagnose ->
  ONE play and ONE time in that week -> ONE caption call (metered, small,
  low effort; held to the business caption checks: numbers and prices only
  from the facts, links only to the business's own site, at most three
  hashtags) -> the FREE composer flyer in the business's own colours with its
  own name and site in the footer (cost_usd 0; never a Creative Director
  render) -> ONE draft post (source 'suggestion', the desk's accounts or every
  connected one, its tracked link, its content hash) -> the owner is told once,
  by push and a Today item. The run is marked succeeded, skipped or failed
  with its reason. Nothing here approves or sends: the post waits for the
  owner's OK on the desk, and only the sender (B5) ever posts it, and only
  while MARKETING_DESK_PUBLISHING=on.

THE FAN-OUT (marketing_tick, hourly, worker only, leader-gated)
  Does nothing unless MARKETING_DESK names the business (comma-separated ids)
  or is '*'. Candidates: a desk row with plan_enabled (none is made here), at
  least one connected account, the posting pilot on, the suggest level by the
  real plan (feature_gates.plan_includes, whatever BILLING_ENFORCE says),
  access full or grace, automations not paused.
  Due, on the business's own clock:
    * Thursday from 7:00 + a jitter of 0-119 minutes (a stable hash of the
      business id; Python's hash() changes per process), through Sunday:
      next week;
    * Monday to Wednesday: this week, and only when this week was never
      planned (the claim decides, as on the platform desk);
    * never overnight: nothing before 7:00 + jitter, nothing from 21:00.
  At most MARKETING_MAX_PER_TICK businesses a tick (default 10). Before each:
  the platform's spend today under 60% of DAILY_SPEND_CAP_USD (else every
  remaining business waits for a later tick), the platform and the business
  under their spend ceilings. Each business has its own try and its own claim:
  one failure never stops the batch.

THE OWNER'S OWN REQUEST (POST /engine/run)
  The web process never calls the model. It checks the owner, the plan, the
  switch, the accounts, the rate limit and one request a day, claims the week
  (as a manual start-over: a suggestion still waiting as a draft is replaced;
  an approved one is never touched), marks the run queued, and answers 202.
  manual_tick on the worker starts each queued run once (a conditional write
  on design.started_at) and writes the suggestion.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException

import business_marketing as bm
import business_marketing_desk as reading
import business_marketing_engine as engine
import business_marketing_links as links
import business_marketing_store as store
import feature_gates
import marketing_desk as words
import marketing_profile
import marketing_signals
import post_for_me
import sb_clients
from auth_supabase import AuthedUser, require_user

router = APIRouter(prefix='/marketing/{business_id}', tags=['marketing-desk'])
log = logging.getLogger(__name__)

KIND = 'suggestion'
TASK = 'business_marketing_suggestion'
RUN_HOUR = 7                          # local: a suggestion (and its push) lands in the morning
QUIET_HOUR = 21                       # nothing is written or pushed from 21:00 to the next morning
JITTER_MINUTES = 120
PLAN_AHEAD_DAY = 3                    # Thursday: next week's suggestion, with the weekend to look at it
RECLAIM = timedelta(minutes=15)       # marketing_claim_run: a run stuck this long is reclaimable
MAX_ATTEMPTS = 3                      # marketing_claim_run: a failed scheduled week is retried this often
HEADROOM_SHARE = 0.6                  # the fan-out waits once today's platform spend reaches this share
DEFAULT_PER_TICK = 10
MAX_PER_TICK = 100
MAX_TOKENS = 1200                     # one caption and a flyer's three lines
EFFORT = 'low'
CALL_TIMEOUT = 60
MANUAL_BATCH = 5
WEEK_SLOTS = 5                        # what a week level's preview shows (B9 writes them)
CHUNK = 100                           # ids per PostgREST in.() filter
DESK_PAGE = 500
DESK_PAGES = 10
FLYER_SCALES = (1.0, 0.88, 0.78, 0.68)
LEVEL = 'suggest'

PLAN_COLUMNS = 'comp_tier,subscription_status,subscription_plan,trial_ends_at,stripe_subscription_id'
FULL_COLUMNS = f'{marketing_profile.BUSINESS_COLUMNS},{PLAN_COLUMNS}'
CANDIDATE_COLUMNS = (f'id,owner_id,type,{PLAN_COLUMNS},availability:settings->availability,'
                     'automations_paused:settings->automations_paused')
RUN_COLUMNS = 'id,business_id,week_of,kind,trigger,status,attempts,design,created_at'

# What the owner reads (on the desk's "could not be written", in Today, in a
# push): plain words, never the machinery.
NOT_SWITCHED_ON = "Chief's weekly suggestion isn't switched on for this business yet."
NO_ACCOUNTS = 'Connect an account first, in Build, Social Media.'
NO_POSTING = "Posting to your social accounts isn't switched on for this business yet."
NO_PLAN = "Chief's weekly suggestion comes with every plan. Choose a plan to get one."
WEEK_LEVEL = "Your plan comes with Chief's full weekly plan, which isn't open yet. Nothing was queued."
NO_ACCESS = "Chief can't write a suggestion while the account needs attention. Check Settings, Billing."
PAUSED = 'Automations are paused for this business, so Chief wrote nothing this week.'
NO_WRITER = "Chief's writing isn't available right now, so nothing was written. It tries again later."
NOTHING = 'There was nothing Chief could say from your site this week, so nothing was written.'
NO_TIME = "There's no open weekday time left in that week for a post."
CAPTION_BROKE = ('The caption Chief wrote said something your site does not (a number, a price or an address), '
                 'so nothing was saved.')
READ_FAILED = "Your numbers couldn't be read just now, so nothing was written."
SAVE_FAILED = "The suggested post couldn't be saved just now. Nothing was posted."
FAILED = 'The suggestion could not be finished. Nothing was posted.'
ONCE_A_DAY = 'Chief already wrote you a suggestion today. Ask again tomorrow.'
BUSY = ('A suggestion for that week is being written, or the one Chief wrote is already approved. '
        'Nothing new was queued.')
QUEUED = 'Chief is writing a suggested post. It shows up here in a minute or two.'
TOO_SOON = 'Please wait a moment before asking again.'


class Skip(Exception):
    """This week gets no suggestion, for a reason the owner can read."""


class Unavailable(Exception):
    """A read the suggestion needs did not happen. Never "nothing there"."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── the switches ──────────────────────────────────────────────────────

def desk_scope() -> Any:
    """MARKETING_DESK: None (off: unset, empty or 'off'), '*' (every
    business), or the set of business ids it names. A token that is not a
    business id is ignored, so a typo switches nobody on."""
    raw = (os.environ.get('MARKETING_DESK') or '').strip()
    if not raw or raw.lower() == 'off':
        return None
    if raw == '*':
        return '*'
    ids = set()
    for part in raw.split(','):
        try:
            ids.add(str(UUID(part.strip())))
        except ValueError:
            continue
    return frozenset(ids) or None


def desk_on_for(business_id: Any) -> bool:
    scope = desk_scope()
    if scope is None:
        return False
    if scope == '*':
        return True
    try:
        return str(UUID(str(business_id))) in scope
    except ValueError:
        return False


def max_per_tick() -> int:
    try:
        n = int(os.environ.get('MARKETING_MAX_PER_TICK') or DEFAULT_PER_TICK)
    except ValueError:
        n = DEFAULT_PER_TICK
    return max(1, min(n, MAX_PER_TICK))


# ── when a suggestion is due ──────────────────────────────────────────

def jitter_minutes(business_id: Any) -> int:
    """0-119 minutes after 7:00, the same for a business on every server and
    every week (sha256 of its id: Python's hash() changes per process)."""
    digest = hashlib.sha256(f'marketing-jitter:{UUID(str(business_id))}'.encode()).digest()
    return int.from_bytes(digest[:8], 'big') % JITTER_MINUTES


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def plans_ahead(local: datetime) -> bool:
    """From Thursday at 7:00 on, a suggestion is for next week."""
    return local.weekday() > PLAN_AHEAD_DAY or (local.weekday() == PLAN_AHEAD_DAY and local.hour >= RUN_HOUR)


def target_week(at: datetime, tz: ZoneInfo) -> date:
    """The Monday of the week a suggestion written now is for: next week from
    Thursday 7:00 to Sunday, this week Monday to Thursday morning."""
    local = at.astimezone(tz)
    monday = monday_of(local.date())
    return monday + timedelta(days=7) if plans_ahead(local) else monday


def due_week(at: datetime, tz: ZoneInfo, business_id: Any) -> Optional[date]:
    """The week a scheduled suggestion is due for at this moment, or None.

    Every day it opens at 7:00 + the business's jitter and closes at 21:00,
    on its own clock: never overnight. From Thursday on it is next week's;
    Monday to Wednesday this week's, which the claim allows only when the
    week was never planned (or its plan failed fewer than three times)."""
    local = at.astimezone(tz)
    opens = datetime.combine(local.date(), time(RUN_HOUR), tz) + timedelta(minutes=jitter_minutes(business_id))
    if local < opens or local.hour >= QUIET_HOUR:
        return None
    return target_week(at, tz)


def claimable(run: Optional[Dict[str, Any]], at: datetime) -> bool:
    """Whether the scheduler's claim of this week would succeed (the
    migration's marketing_claim_run): no run yet; a failed or skipped one
    under three attempts; a run stuck 15 minutes. Read first, so a planned
    week costs the fan-out nothing and never counts against its cap."""
    if not run:
        return True
    status = run.get('status')
    if status in ('failed', 'skipped'):
        return int(run.get('attempts') or 1) < MAX_ATTEMPTS
    if status == 'running':
        started = words._stamp(run.get('created_at'))
        return bool(started and started < at - RECLAIM)
    return False


# ── who is eligible ───────────────────────────────────────────────────

def level_problem(row: Dict[str, Any]) -> Optional[str]:
    """None at the suggest level by the real plan; else why not, in plain
    words. A week level waits for its own plan (B9)."""
    if feature_gates.plan_includes(row, 'marketing_week'):
        return WEEK_LEVEL
    if not feature_gates.plan_includes(row, 'marketing_suggestion'):
        return NO_PLAN
    return None


def access_ok(row: Dict[str, Any]) -> bool:
    """feature_gates.access_state is full or grace. Read only while billing
    is enforced (it answers full otherwise); a failed read is not eligible,
    because this is money spent unasked."""
    if not feature_gates.enforcement_on():
        return feature_gates.access_state(row).get('state') in ('full', 'grace')
    try:
        import usage_metering
        bid = str(row.get('id'))
        grandfathered = usage_metering.is_grandfathered_business(bid, row)
        spent = usage_metering.trial_credits_exhausted(bid, row)
        return feature_gates.access_state(row, grandfathered, spent).get('state') in ('full', 'grace')
    except Exception:
        log.warning('marketing planner: access for %s could not be read', str(row.get('id'))[:8], exc_info=True)
        return False


def _paused(row: Dict[str, Any]) -> bool:
    import policy_engine
    settings = row.get('settings') if isinstance(row.get('settings'), dict) else {}
    if 'automations_paused' in row and 'automations_paused' not in settings:
        settings = {**settings, 'automations_paused': row.get('automations_paused')}
    return policy_engine.is_paused({**row, 'settings': settings})


def eligibility(row: Dict[str, Any], *, scheduled: bool) -> Optional[str]:
    """Why this business gets no suggestion now (plain words), or None.
    The owner's own request is not an automation, so a pause does not stop it."""
    bid = str(row.get('id') or '')
    if not desk_on_for(bid):
        return NOT_SWITCHED_ON
    if not post_for_me.allowed_for(bid):
        return NO_POSTING
    problem = level_problem(row)
    if problem:
        return problem
    if not access_ok(row):
        return NO_ACCESS
    if scheduled and _paused(row):
        return PAUSED
    return None


# ── reads ─────────────────────────────────────────────────────────────

def _chunks(items: List[str], n: int = CHUNK) -> Iterable[List[str]]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise Unavailable(path.split('?')[0])
    return rows


def read_business(business_id: str) -> Dict[str, Any]:
    """The whole row a suggestion reads (the profile's columns and the
    plan's). A failed read raises Unavailable; a missing one LookupError."""
    rows = _get(f'/businesses?id=eq.{UUID(str(business_id))}&select={FULL_COLUMNS}&limit=1')
    if not rows:
        raise LookupError('Business not found.')
    return rows[0]


def zones(rows: List[Dict[str, Any]]) -> Dict[str, Optional[ZoneInfo]]:
    """Each business's clock, by the desk's one chain (business_marketing.
    business_tz): availability.timezone, the owner's practitioner_profiles.
    timezone, PLATFORM_DEFAULT_TZ, UTC. The profiles are read in one go for
    the businesses that need them; a failed read leaves those None (skipped
    this tick), never UTC by accident."""
    from availability import BusinessAvailability
    default = bm._zone(os.environ.get('PLATFORM_DEFAULT_TZ')) or ZoneInfo('UTC')
    out: Dict[str, Optional[ZoneInfo]] = {}
    need: List[Dict[str, Any]] = []
    for row in rows:
        bid = str(row['id'])
        zone = bm._zone(BusinessAvailability.from_settings_dict(bm._availability(row)).timezone)
        if zone:
            out[bid] = zone
        elif row.get('owner_id'):
            need.append(row)
        else:
            out[bid] = default
    owners = sorted({str(r['owner_id']) for r in need})
    found: Dict[str, Any] = {}
    failed = False
    for chunk in _chunks(owners):
        prof = sb_clients.sb_get_as_service(
            f"/practitioner_profiles?owner_id=in.({','.join(chunk)})&select=owner_id,timezone")
        if prof is None:
            failed = True
            break
        for p in prof:
            found.setdefault(str(p.get('owner_id')), p.get('timezone'))
    for row in need:
        out[str(row['id'])] = None if failed else (bm._zone(found.get(str(row['owner_id']))) or default)
    return out


async def _desk_ids(scope: Any) -> List[str]:
    """Businesses whose desk has the weekly suggestion on (plan_enabled).
    No desk row is made here: a business without one has not switched it on."""
    out: List[str] = []
    if scope != '*':
        for chunk in _chunks(sorted(scope)):
            found = await store.rows(f"/marketing_desks?plan_enabled=eq.true&business_id=in.({','.join(chunk)})"
                                     f'&select=business_id&limit={len(chunk)}')
            out += [str(r['business_id']) for r in found]
        return out
    for page in range(DESK_PAGES):
        found = await store.rows(f'/marketing_desks?plan_enabled=eq.true&select=business_id'
                                 f'&order=business_id.asc&limit={DESK_PAGE}&offset={page * DESK_PAGE}')
        out += [str(r['business_id']) for r in found]
        if len(found) < DESK_PAGE:
            break
    return out


def _connected_ids(ids: List[str]) -> set:
    """The businesses among these with at least one connected account."""
    out = set()
    for chunk in _chunks(ids):
        rows = _get(f"/social_connections?provider=eq.{bm.PROVIDER}&status=eq.connected"
                    f"&business_id=in.({','.join(chunk)})&select=business_id")
        out |= {str(r.get('business_id')) for r in rows}
    return out


def _business_rows(ids: List[str]) -> List[Dict[str, Any]]:
    out = []
    for chunk in _chunks(ids):
        out += _get(f"/businesses?id=in.({','.join(chunk)})&select={CANDIDATE_COLUMNS}")
    return out


async def candidates(scope: Any) -> List[Dict[str, Any]]:
    """Every business the fan-out may write for. Raises on a failed read:
    a blip never reads as "nobody to do"."""
    ids = await _desk_ids(scope)
    if not ids:
        return []
    with_accounts = await asyncio.to_thread(_connected_ids, ids)
    ids = [i for i in ids if i in with_accounts]
    if not ids:
        return []
    rows = await asyncio.to_thread(_business_rows, ids)
    return [r for r in rows if eligibility(r, scheduled=True) is None]


async def _runs_for(ids: List[str], weeks: List[date]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out = {}
    week_list = ','.join(sorted({w.isoformat() for w in weeks}))
    for chunk in _chunks(ids):
        rows = await store.rows(f"/marketing_runs?business_id=in.({','.join(chunk)})&week_of=in.({week_list})"
                                f'&select={RUN_COLUMNS}&limit={len(chunk) * 3}')
        for r in rows:
            out[(str(r['business_id']), str(r['week_of'])[:10])] = r
    return out


# ── the caption: the one model call ───────────────────────────────────

def caption_request(slot: Dict[str, Any], facts: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    play = engine.PLAYS[slot['play_id']]
    return {'audience': profile.get('audience'), 'voice': profile.get('voice'), 'facts': facts,
            'slots': [{'slot': 1, 'play': play['label'], 'play_brief': play['brief'],
                       'subject': slot.get('subject'), 'offering': slot.get('offering')}]}


def _parse(raw: str) -> Dict[str, Any]:
    raw = (raw or '').strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    start, end = raw.find('{'), raw.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('no JSON object')
    out = json.loads(raw[start:end + 1])
    if not isinstance(out, dict):
        raise ValueError('not an object')
    return out


def judge(parsed: Dict[str, Any], slot: Dict[str, Any], facts: Dict[str, Any],
          profile: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, str]], List[Dict[str, Any]]]:
    """(caption, flyer copy, dropped). A caption that breaks a rule is not
    used at all; flyer copy that breaks one costs the post its picture only."""
    items = parsed.get('captions') if isinstance(parsed.get('captions'), list) else []
    item = next((i for i in items if isinstance(i, dict) and i.get('slot') == 1),
                next((i for i in items if isinstance(i, dict)), None))
    text = item.get('text') if item else None
    if not isinstance(text, str):
        return None, None, [{'slot': 1, 'reason': 'missing'}]
    offering = slot.get('offering')
    problem = engine.check_caption(text, facts, profile, offering)
    if problem:
        return None, None, [{'slot': 1, 'reason': problem}]
    flyer = item.get('flyer')
    flyer_problem = engine.check_flyer(flyer, facts, profile, offering) if isinstance(flyer, dict) else 'no flyer copy'
    if flyer_problem:
        return text.strip(), None, [{'slot': 1, 'reason': flyer_problem, 'flyer_only': True}]
    import marketing_engine
    return text.strip(), {f: flyer[f].strip() for f in marketing_engine.FLYER_LIMITS}, []


async def write_caption(business_id: str, slot: Dict[str, Any], facts: Dict[str, Any],
                        profile: Dict[str, Any]):
    """One small model call, metered to the business (units=0: Chief's own
    proactive work bills the owner nothing)."""
    import llm_call
    import model_ladder
    from chief_models import model_for
    model = model_for('draft')
    payload = {'model': model, 'max_tokens': MAX_TOKENS, 'system': profile['system_prompt'],
               'messages': [{'role': 'user', 'content': json.dumps(caption_request(slot, facts, profile),
                                                                   default=str)}],
               **model_ladder.effort_kwargs(model, EFFORT)}
    async with httpx.AsyncClient() as client:
        response = await llm_call.apost(client, payload, timeout=CALL_TIMEOUT, task=TASK,
                                        business_id=business_id, units=0)
    response.raise_for_status()
    return judge(_parse(llm_call.text_of(response.json())), slot, facts, profile)


# ── the flyer: free, the business's own ───────────────────────────────

async def make_flyer(business: Dict[str, Any], run_id: UUID, attempt: int, slot: Dict[str, Any],
                     copy: Optional[Dict[str, str]], profile: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """The composer flyer (code-built, rendered, cost_usd 0) in the
    business's own colours, with its own name and site in the footer. Made
    under image_studio.build_actor bound to this business and its owner (read
    as the service role), reset in a finally. Returns (artwork id or None,
    the design record). A flyer that cannot be made never costs the post."""
    import chief_flyer_composer as composer
    import image_studio as images
    import marketing_design
    design: Dict[str, Any] = {'flyer': None, 'cost_usd': 0, 'made_by': 'composer', 'failed': []}
    if not copy:
        design['failed'].append({'what': 'flyer', 'reason': 'no flyer words passed the checks'})
        return None, design
    bid, owner = str(business['id']), str(business.get('owner_id') or '')
    if not owner:
        design['failed'].append({'what': 'flyer', 'reason': 'no owner on record'})
        return None, design
    palette = marketing_design.brand_palette(marketing_design.brand_colors(business))
    footer = profile.get('flyer_footer') or marketing_profile.flyer_footer(business.get('name'), None)
    eyebrow = engine.PLAYS[slot['play_id']]['eyebrow']
    token = images.build_actor.set({'business_id': bid, 'user_id': owner})
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            last = None
            for step, scale in enumerate(FLYER_SCALES):
                try:
                    layout = marketing_design.flyer_layout(slot['play_id'], copy, scale=scale, eyebrow=eyebrow,
                                                           footer=footer, palette=palette)
                    request_id = uuid5(run_id, f'suggestion-flyer:{attempt}:{step}')
                    result = await composer.compose(client, {'id': bid}, {'layout': layout}, request_id)
                    art = str(result['image']['id'])
                    design.update(flyer=art, palette=palette, footer=footer)
                    return art, design
                except HTTPException as exc:
                    last = exc
                    if exc.status_code != 422:
                        break
            design['failed'].append({'what': 'flyer', 'reason': str(getattr(last, 'detail', 'render failed'))[:200]})
    except Exception as exc:
        log.warning('marketing planner: flyer for %s failed', bid[:8], exc_info=True)
        design['failed'].append({'what': 'flyer', 'reason': str(getattr(exc, 'detail', 'render failed'))[:200]})
    finally:
        images.build_actor.reset(token)
    return None, design


# ── telling the owner, once ───────────────────────────────────────────

def about(slot: Dict[str, Any], brand: Optional[str]) -> str:
    """What the post is about, in a few words for a push."""
    play, subject = slot.get('play_id'), slot.get('subject')
    if play in ('offer_spotlight', 'whats_new') and subject:
        return f'about "{str(subject)[:60]}"'
    return {'book_a_time': 'an invitation to book a time', 'useful_tip': 'a useful tip',
            'meet_us': f'an introduction to {brand}' if brand else 'an introduction to the business',
            'come_back': 'a welcome back to people who have been before'}.get(play, 'a post for your accounts')


def tell_words(post: Dict[str, Any], slot: Dict[str, Any], *, which: Optional[str], tz: ZoneInfo,
               brand: Optional[str]) -> Dict[str, str]:
    when = f"{words.day_name(post['run_at'], tz)} at {words.clock(post['run_at'], tz)}"
    return {'title': f"Chief has a post ready for {which or 'next week'}",
            'body': (f"It's {about(slot, brand)}. It goes out {when} once you approve it; nothing posts until "
                     'you do.')}


def dedup_key(post_id: Any) -> str:
    return f'marketing_suggestion:{UUID(str(post_id))}'


def _already_told(business_id: str, key: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f'/chief_notifications?business_id=eq.{business_id}&action_payload->>dedup_key=eq.{key}&select=id&limit=1')
    if rows is None:
        return None
    return bool(rows)


def _today_item(business_id: str, post: Dict[str, Any], said: Dict[str, str], key: str) -> bool:
    saved = sb_clients.sb_post_as_service('/chief_notifications', {
        'business_id': business_id, 'type': 'reminder', 'priority': 'normal',
        'title': said['title'][:120], 'body': said['body'][:300], 'suggested_action': 'Review the post',
        'action_payload': {'type': 'navigate', 'tab': 'grow', 'sub': 'marketing', 'post_id': str(post['id']),
                           'dedup_key': key},
    })
    return bool(saved)


def _push(owner_id: str, post: Dict[str, Any], said: Dict[str, str]) -> int:
    try:
        import push_notifications
        return push_notifications.send_to_user(owner_id, title=said['title'][:80], body=said['body'][:160],
                                               nav=reading.NAV, tag=f"marketing-suggestion-{post['id']}")
    except Exception:
        log.warning('marketing planner: push for %s failed', post.get('id'), exc_info=True)
        return 0


async def tell_owner(business: Dict[str, Any], post: Dict[str, Any], slot: Dict[str, Any], tz: ZoneInfo,
                     week_of: Any, at: datetime) -> bool:
    """One Today item and one push for this suggestion, never twice (keyed
    by the post in chief_notifications.action_payload.dedup_key). If what
    was said cannot be read, nothing is said rather than risk saying it
    twice. Never by text message (Kevin, 2026-10-07)."""
    bid = str(business['id'])
    key = dedup_key(post['id'])
    try:
        if await asyncio.to_thread(_already_told, bid, key) is not False:
            return False
        said = tell_words(post, slot, which=reading.relation(week_of, at, tz), tz=tz, brand=business.get('name'))
        if not await asyncio.to_thread(_today_item, bid, post, said, key):
            return False
        if business.get('owner_id'):
            await asyncio.to_thread(_push, str(business['owner_id']), post, said)
        return True
    except Exception:
        log.warning('marketing planner: could not tell the owner of %s', bid[:8], exc_info=True)
        return False


# ── one suggestion ────────────────────────────────────────────────────

def suggestion_post_id(run_id: Any, attempt: int) -> str:
    """One post per attempt of the week's run: a retry inside an attempt is
    the same post, and a start-over (whose drafts the claim cancelled) gets
    a new one."""
    return str(uuid5(UUID(str(run_id)), f'{int(attempt)}:suggestion'))


async def slot_time(business_id: str, tz: ZoneInfo, post_hour: Any, week_of: date,
                    at: datetime) -> Optional[datetime]:
    """The first open time in that week (a weekday, at the desk's hour or
    3:00 PM on the business's clock, at least an hour away, not taken), or
    None when the week has none left."""
    start = datetime.combine(week_of, time(0), tz)
    try:
        slot = await bm.next_open_slot(business_id, tz, post_hour, at=max(at, start))
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise Unavailable('the calendar could not be read') from None
        return None
    return slot if slot.astimezone(tz).date() < week_of + timedelta(days=7) else None


async def _finish(business_id: str, run_id: Any, at: datetime, **fields) -> None:
    """Record how the run ended, onto the claim this caller holds."""
    try:
        await store.request('PATCH', f'/marketing_runs?id=eq.{UUID(str(run_id))}&business_id=eq.{business_id}'
                                     '&status=eq.running', {**fields, 'finished_at': at.isoformat()})
    except store.StoreError:
        log.warning('marketing planner: the run %s could not be recorded (%s)', str(run_id)[:8], fields.get('status'))


def _record_slot(slot: Dict[str, Any], run_at: Optional[datetime]) -> Dict[str, Any]:
    out = {k: slot.get(k) for k in ('slot', 'play_id', 'subject_key', 'subject', 'offering', 'landing_url')}
    out['run_at'] = run_at.isoformat() if run_at else None
    return out


async def run_suggestion(business_id: Any, *, trigger: str, now: Optional[datetime] = None,
                         business: Optional[Dict[str, Any]] = None,
                         run: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Write one business's suggested post for one week, as a draft.

    trigger: 'scheduled' (the fan-out) or 'manual' (the owner's queued
    request, whose claimed run is passed as `run`). A scheduled call claims
    the week itself; a week already planned answers {'status': 'exists'}.
    Never approves or sends anything."""
    if trigger not in store.RUN_TRIGGERS:
        raise ValueError('Unknown trigger.')
    bid = str(UUID(str(business_id)))
    at = now or _now()
    row = business if business and all(k in business for k in FULL_COLUMNS.split(',')) else None
    run_id = UUID(str(run['id'])) if run else None
    try:
        row = row or await asyncio.to_thread(read_business, bid)
        tz = await asyncio.to_thread(marketing_profile.time_zone, row)
        desk = await store.get_desk(bid)
    except LookupError:
        if run_id:
            await _finish(bid, run_id, at, status='skipped', error='This business no longer exists.')
        return {'status': 'not_eligible', 'reason': 'Business not found.'}
    except (Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        if run_id:
            await _finish(bid, run_id, at, status='failed', error=READ_FAILED)
        return {'status': 'unavailable', 'reason': READ_FAILED}

    reason = eligibility(row, scheduled=trigger == 'scheduled')
    if reason is None and trigger == 'scheduled' and not (desk or {}).get('plan_enabled'):
        reason = NOT_SWITCHED_ON
    if reason:
        if run_id:
            await _finish(bid, run_id, at, status='skipped', error=reason)
        return {'status': 'not_eligible', 'reason': reason}

    week_of = date.fromisoformat(str(run['week_of'])[:10]) if run else target_week(at, tz)
    try:
        when = await slot_time(bid, tz, (desk or {}).get('post_hour', 11), week_of, at)
    except Unavailable:
        if run_id:
            await _finish(bid, run_id, at, status='failed', error=READ_FAILED)
        return {'status': 'unavailable', 'reason': READ_FAILED}
    if when is None:
        if run_id:
            await _finish(bid, run_id, at, status='skipped', error=NO_TIME)
        return {'status': 'no_time', 'reason': NO_TIME, 'week_of': week_of.isoformat()}

    if run is None:
        try:
            if not await store.claim_run(bid, week_of, kind=KIND, source=trigger):
                return {'status': 'exists', 'week_of': week_of.isoformat()}
        except store.StoreError:
            return {'status': 'unavailable', 'reason': READ_FAILED}
        run_id = store.run_id_for(bid, week_of)
        try:
            run = await store.get_run(bid, run_id)
        except store.StoreError:
            run = None
        if not run:
            # Claimed, but its attempt count cannot be read: retried later, never guessed.
            await _finish(bid, run_id, at, status='failed', error=READ_FAILED)
            return {'status': 'failed', 'reason': READ_FAILED, 'run_id': str(run_id)}
    attempt = int(run.get('attempts') or 1)
    queued = run.get('design') if trigger == 'manual' and isinstance(run.get('design'), dict) else {}
    request = {k: queued[k] for k in ('queued_at', 'queued_by', 'started_at') if k in queued}
    return await _plan(row, desk, tz, run_id, week_of, when, attempt, at, request)


async def _plan(row: Dict[str, Any], desk: Optional[Dict[str, Any]], tz: ZoneInfo, run_id: UUID, week_of: date,
                when: datetime, attempt: int, at: datetime, request: Dict[str, Any]) -> Dict[str, Any]:
    """The claimed run, written and recorded. Every way out marks the run."""
    import creative_director
    import llm_call
    import spend_guard
    bid = str(row['id'])
    record: Dict[str, Any] = {}
    design: Dict[str, Any] = dict(request)
    try:
        if not llm_call.api_key():
            raise Skip(NO_WRITER)
        if await asyncio.to_thread(spend_guard.over_budget, bid):
            raise Skip(spend_guard.block_message())
        existing = await store.rows(f'/marketing_posts?run_id=eq.{run_id}&business_id=eq.{bid}'
                                    '&status=neq.cancelled&select=id,run_at,play_id&limit=5')
        if existing:
            # An earlier attempt saved its draft and stopped before recording
            # that (or before telling the owner, which tell_owner does once).
            await _finish(bid, run_id, at, status='succeeded', post_ids=[str(p['id']) for p in existing], error=None)
            await tell_owner(row, existing[0], {'play_id': existing[0].get('play_id')}, tz, week_of, at)
            return {'status': 'succeeded', 'run_id': str(run_id), 'post_id': str(existing[0]['id']),
                    'week_of': week_of.isoformat(), 'resumed': True}
        try:
            accounts = await bm.connected(bid)
        except HTTPException:
            raise Unavailable('accounts') from None
        if not accounts:
            raise Skip(NO_ACCOUNTS)
        signals = await marketing_signals.read_signals(bid, now=at, business=row, tz=tz)
        profile = await marketing_profile.read_profile(bid, business=row)
        raw_facts = await asyncio.to_thread(creative_director.business_facts, bid)
        facts = engine.verified_facts(raw_facts, new_offerings=signals.get('new_offerings'),
                                      news=signals.get('fresh_news'))
        diagnosis = engine.diagnose(signals)
        plan = engine.pick_plays(diagnosis, 1, signals, profile, facts)
        if not plan['slots']:
            raise Skip(NOTHING)
        slot = plan['slots'][0]
        record = {'signals': marketing_signals.summary(signals), 'diagnosis': diagnosis, 'plays': plan['plays'],
                  'slots': [_record_slot(slot, when)]}

        caption, copy, dropped = await write_caption(bid, slot, facts, profile)
        record['dropped'] = dropped
        if caption is None:
            await _finish(bid, run_id, at, status='failed', error=CAPTION_BROKE, design=design, **record)
            return {'status': 'failed', 'reason': CAPTION_BROKE, 'run_id': str(run_id)}

        art, made = await make_flyer(row, run_id, attempt, slot, copy, profile)
        design.update(made)
        media = {'artwork_ids': [art]} if art else {}
        kind = bm.media_kind(media)
        try:
            chosen = bm.pick_targets(accounts, desk, None)
        except HTTPException as exc:
            raise Skip(str(exc.detail)) from None
        # No plan gates a network (Kevin, 2026-10-07): TikTok and YouTube take
        # only videos, so a picture or words-only post leaves them out, and
        # Instagram needs a picture. The shared door's fit rules decide.
        kept, gone = bm.fit(chosen, kind)
        if gone:
            design['left_out'] = bm._public_dropped(gone)
        if not kept:
            raise Skip(f"{bm.dropped_note(gone) or 'None of your accounts can take this post.'} Nothing was saved.")
        try:
            site = await asyncio.to_thread(bm._site, bid)
            landing = slot.get('landing_url') if links.on_site(slot.get('landing_url'), site) else None
            if landing is None:
                landing = await asyncio.to_thread(bm.default_landing, bid, row, site, desk)
        except HTTPException:
            raise Unavailable('site') from None
        post_id = suggestion_post_id(run_id, attempt)
        try:
            link = bm.link_fields(post_id, caption, landing, site)
            targets = bm.ready_to_post(chosen, kind, caption, link['publish_text'])
            run_at, expires_at = bm.schedule(when)
            post = bm.new_post(bid, post_id, caption=caption, media=media, targets=targets, run_at=run_at,
                               expires_at=expires_at, landing=landing, source=KIND, site=site)
        except HTTPException as exc:
            raise Skip(str(exc.detail)) from None
        post.update(run_id=str(run_id), play_id=slot['play_id'], design_status='ready' if art else 'none')
        try:
            if desk is None:
                await bm.ensure_desk(bid)      # the sender claims nothing for a business with no desk row
            saved = await store.request('POST', '/marketing_posts', post)
            post = saved[0] if isinstance(saved, list) and saved else post
        except store.StoreConflict:
            post = await store.get_post(bid, post_id) or post      # this attempt saved it a moment ago
        except (store.StoreUnavailable, HTTPException):
            await _finish(bid, run_id, at, status='failed', error=SAVE_FAILED, design=design, **record)
            return {'status': 'failed', 'reason': SAVE_FAILED, 'run_id': str(run_id)}
        await _finish(bid, run_id, at, status='succeeded', post_ids=[post_id], error=None, design=design, **record)
        await tell_owner(row, post, slot, tz, week_of, at)
        return {'status': 'succeeded', 'run_id': str(run_id), 'post_id': post_id, 'week_of': week_of.isoformat()}
    except Skip as reason:
        await _finish(bid, run_id, at, status='skipped', error=str(reason), design=design, **record)
        return {'status': 'skipped', 'reason': str(reason), 'run_id': str(run_id)}
    except (Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        log.warning('marketing planner: a read for %s failed', bid[:8], exc_info=True)
        await _finish(bid, run_id, at, status='failed', error=READ_FAILED, design=design, **record)
        return {'status': 'failed', 'reason': READ_FAILED, 'run_id': str(run_id)}
    except Exception:
        log.warning('marketing planner: the suggestion for %s could not be finished', bid[:8], exc_info=True)
        await _finish(bid, run_id, at, status='failed', error=FAILED, design=design, **record)
        return {'status': 'failed', 'reason': FAILED, 'run_id': str(run_id)}


# ── the hourly fan-out ────────────────────────────────────────────────

def _headroom_low() -> bool:
    """Today's platform spend has reached 60% of DAILY_SPEND_CAP_USD."""
    import spend_guard
    return spend_guard.platform_share() >= HEADROOM_SHARE


def _platform_over() -> bool:
    import spend_guard
    return spend_guard.over_budget('')      # '': the platform ceiling only, never an ambient tenant's


def _business_over(business_id: str) -> bool:
    import spend_guard
    return spend_guard.over_budget(business_id)


async def marketing_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Hourly, on the worker, on the scheduler leader. Writes the weekly
    suggestion for every business that is due, at most max_per_tick() of
    them, each in its own try with its own claim."""
    scope = desk_scope()
    if scope is None:
        return {'skipped': 'off'}
    import llm_call
    if not llm_call.api_key():
        return {'skipped': 'no writer'}
    if not post_for_me.configured():
        return {'skipped': 'posting not configured'}
    at = now or _now()
    if await asyncio.to_thread(_headroom_low):
        return {'deferred': 'platform spend'}
    try:
        rows = await candidates(scope)
        clocks = await asyncio.to_thread(zones, rows)
    except (Unavailable, store.StoreError):
        log.warning('marketing planner: the candidates could not be read this hour.')
        return {'skipped': 'unreadable'}
    due = []
    for row in rows:
        tz = clocks.get(str(row['id']))
        week = due_week(at, tz, row['id']) if tz else None
        if week:
            due.append((row, tz, week))
    tally: Counter = Counter(candidates=len(rows), due=len(due))
    if not due:
        return dict(tally)
    try:
        runs = await _runs_for([str(r['id']) for r, _, _ in due], [w for _, _, w in due])
    except store.StoreError:
        log.warning('marketing planner: the weeks already planned could not be read this hour.')
        return {**tally, 'skipped': 'unreadable'}
    todo = [(r, tz, w) for r, tz, w in due if claimable(runs.get((str(r['id']), w.isoformat())), at)]
    todo.sort(key=lambda item: (jitter_minutes(item[0]['id']), str(item[0]['id'])))
    tally['to_do'] = len(todo)
    limit = max_per_tick()
    for index, (row, tz, week) in enumerate(todo):
        bid = str(row['id'])
        if index >= limit:
            tally['next_tick'] = len(todo) - index
            break
        try:
            if await asyncio.to_thread(_headroom_low) or await asyncio.to_thread(_platform_over):
                tally['deferred'] = len(todo) - index           # every remaining business waits
                break
            if await asyncio.to_thread(_business_over, bid):
                tally['over_budget'] += 1
                continue
            out = await run_suggestion(bid, trigger='scheduled', now=at)
            tally[str(out.get('status'))] += 1
        except Exception:
            log.exception('marketing planner: the suggestion for %s stopped unexpectedly', bid[:8])
            tally['error'] += 1
    return dict(tally)


# ── the owner's own request ───────────────────────────────────────────

async def _start(run: Dict[str, Any], at: datetime) -> Optional[Dict[str, Any]]:
    """Take one queued run: a write that lands only while nobody has started
    it, so two ticks never write the same request twice."""
    design = run.get('design') if isinstance(run.get('design'), dict) else {}
    out = await store.request(
        'PATCH', f"/marketing_runs?id=eq.{UUID(str(run['id']))}&business_id=eq.{UUID(str(run['business_id']))}"
                 '&status=eq.running&trigger=eq.manual&design->>started_at=is.null',
        {'design': {**design, 'started_at': words._z(at)}})
    return out[0] if isinstance(out, list) and out else None


async def manual_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every minute, on the worker: write the suggestions owners asked for.
    A request older than the claim's 15 minutes is left to the claim's own
    reclaim; it is never written twice."""
    if desk_scope() is None:
        return {'skipped': 'off'}
    at = now or _now()
    try:
        queued = await store.rows(
            f'/marketing_runs?status=eq.running&trigger=eq.manual&kind=eq.{KIND}'
            f'&created_at=gte.{reading.query_time(at - RECLAIM)}'
            '&design->>queued_at=not.is.null&design->>started_at=is.null'
            f'&select={RUN_COLUMNS}&order=created_at.asc&limit={MANUAL_BATCH}')
    except store.StoreError:
        return {'skipped': 'storage'}
    tally: Counter = Counter()
    for run in queued:
        bid = str(run.get('business_id'))
        try:
            started = await _start(run, at)
            if not started:
                tally['taken'] += 1
                continue
            if await asyncio.to_thread(_business_over, bid):
                import spend_guard
                await _finish(bid, run['id'], at, status='skipped', error=spend_guard.block_message())
                tally['over_budget'] += 1
                continue
            out = await run_suggestion(bid, trigger='manual', now=at, run=started)
            tally[str(out.get('status'))] += 1
        except Exception:
            log.exception('marketing planner: the request for %s stopped unexpectedly', bid[:8])
            tally['error'] += 1
    return dict(tally)


def _local_midnight(at: datetime, tz: ZoneInfo) -> datetime:
    return datetime.combine(at.astimezone(tz).date(), time(0), tz)


async def asked_today(business_id: str, tz: ZoneInfo, at: datetime) -> bool:
    """Whether the owner already asked for a suggestion today, on the
    business's clock. A failed read raises (the route answers 503)."""
    rows = await store.rows(f'/marketing_runs?business_id=eq.{business_id}&trigger=eq.manual'
                            f'&created_at=gte.{reading.query_time(at - timedelta(days=2))}'
                            '&select=id,design,created_at&limit=20')
    since = _local_midnight(at, tz)
    for r in rows:
        stamp = words._stamp((r.get('design') or {}).get('queued_at') if isinstance(r.get('design'), dict) else None)
        if stamp and stamp >= since:
            return True
    return False


@router.post('/engine/run', status_code=202)
async def run_route(business_id: UUID, user: AuthedUser = Depends(require_user)):
    """Queue this week's suggestion now. The owner only; the worker writes
    it (the model never runs on the web process)."""
    import rate_limit
    bid = str(business_id)
    owner_row = await bm._require_owner(bid, user)
    if not desk_on_for(bid):
        raise HTTPException(409, NOT_SWITCHED_ON)
    try:
        row = await asyncio.to_thread(read_business, bid)
    except Unavailable:
        raise HTTPException(503, bm.READ_DOWN) from None
    except LookupError:
        raise HTTPException(404, 'Business not found.') from None
    problem = level_problem(row)
    if problem:
        raise HTTPException(409 if problem == WEEK_LEVEL else 403, problem)
    if not access_ok(row):
        raise HTTPException(402, NO_ACCESS)
    if not post_for_me.allowed_for(bid):
        raise HTTPException(409, NO_POSTING)
    if not rate_limit.allow('business_marketing_engine', f'{user.id}:{bid}'):
        raise HTTPException(429, TOO_SOON)
    tz = await asyncio.to_thread(bm.business_tz, owner_row)
    at = _now()
    if not await bm.connected(bid):
        raise HTTPException(409, NO_ACCOUNTS)
    if await asyncio.to_thread(_business_over, bid):
        import spend_guard
        raise HTTPException(429, spend_guard.block_message())
    try:
        if await asked_today(bid, tz, at):
            raise HTTPException(429, ONCE_A_DAY)
    except store.StoreError:
        raise HTTPException(503, bm.READ_DOWN) from None
    week = target_week(at, tz)
    await bm.ensure_desk(bid)             # the sender claims nothing for a business with no desk row
    # A manual start-over: a suggestion still waiting as a draft is replaced
    # (the claim cancels it); a week with an approved or sent post is refused.
    claimed = await bm._call(store.claim_run(bid, week, kind=KIND, source='manual', replan=True))
    if not claimed:
        raise HTTPException(409, BUSY)
    run_id = store.run_id_for(bid, week)
    # Marked queued for the worker. If this write is lost, the run waits out
    # the claim's 15 minutes and can be asked for again (it is not counted
    # as today's request without its queued_at).
    marked = await bm._call(store.request(
        'PATCH', f'/marketing_runs?id=eq.{run_id}&business_id=eq.{bid}&status=eq.running',
        {'design': {'queued_at': words._z(at), 'queued_by': str(user.id)}, 'signals': None, 'diagnosis': None,
         'plays': None, 'slots': None, 'dropped': None, 'post_ids': [], 'error': None}))
    if not marked:
        raise HTTPException(503, bm.STORE_DOWN)
    return {'queued': True, 'run_id': str(run_id), 'week_of': week.isoformat(), 'message': QUEUED}


# ── the preview ───────────────────────────────────────────────────────

PROFILE_PUBLIC = ('brand_name', 'business_type', 'vertical', 'audience', 'audience_from', 'voice', 'timezone',
                  'site_host', 'site_url', 'booking_url', 'landing_url', 'landing_from', 'shape', 'flyer_footer')


async def preview(business_id: str, *, at: Optional[datetime] = None) -> Dict[str, Any]:
    """What Chief would write about for this business right now: its
    numbers, profile and facts, the diagnosis and the plays. Reads only: no
    model call, no write, no spend."""
    import creative_director
    at = at or _now()
    row = await asyncio.to_thread(read_business, business_id)
    level = await asyncio.to_thread(bm.level_for, row)
    tz = await asyncio.to_thread(marketing_profile.time_zone, row)
    profile = await marketing_profile.read_profile(business_id, business=row)
    signals = await marketing_signals.read_signals(business_id, now=at, business=row, tz=tz)
    raw_facts = await asyncio.to_thread(creative_director.business_facts, business_id)
    facts = engine.verified_facts(raw_facts, new_offerings=signals.get('new_offerings'),
                                  news=signals.get('fresh_news'))
    diagnosis = engine.diagnose(signals)
    n = 1 if level['level'] == LEVEL else WEEK_SLOTS
    plan = engine.pick_plays(diagnosis, n, signals, profile, facts)
    return {'business_id': business_id, 'level': level['level'], 'upgrade': level['upgrade'],
            'switched_on': desk_on_for(business_id), 'time_zone': tz.key,
            'week_of': target_week(at, tz).isoformat(), 'diagnosis': diagnosis, 'plays': plan['plays'],
            'slots': plan['slots'], 'facts': facts, 'signals': marketing_signals.summary(signals),
            'profile': {k: profile.get(k) for k in PROFILE_PUBLIC}}


@router.get('/preview')
async def preview_route(business_id: UUID, user: AuthedUser = Depends(require_user)):
    bid = str(business_id)
    await bm._require_owner(bid, user)
    try:
        return await preview(bid)
    except LookupError:
        raise HTTPException(404, 'Business not found.') from None
    except (Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        raise HTTPException(503, bm.READ_DOWN) from None

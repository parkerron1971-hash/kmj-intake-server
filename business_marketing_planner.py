"""business_marketing_planner.py — Chief's weekly suggestion and weekly plan for every business, and the fan-out.

B8 and B9 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (D2's flyers and
fan-out rules). A business at the `suggest` level (its real plan includes
marketing_suggestion and not marketing_week: Starter, Solo, Booked) gets ONE
suggested post a week, as a draft on its marketing desk, to approve or skip.
A business at the `week` level (marketing_week: Professional; Practice, the
autopilot level, gets the same week plus its own clips, B12) gets the WEEKLY
PLAN: five drafts, each with a Creative Director flyer included in its plan.
A chair business with a live calendar (the `openings` level, Boss) gets the
OPEN-CHAIRS WEEK (B11): three posts made from its booking calendar
(business_marketing_openings has the calendar's half).

  run_suggestion(business_id, trigger=)   one business's suggestion for one week
  run_week(business_id, trigger=)         one business's five-post week (B9)
  run_openings(business_id, trigger=)     one Boss business's open-chairs week (B11)
  marketing_tick()                        hourly, on the worker: every business that is due
  manual_tick()                           every minute, on the worker: the owner's queued requests
  marketing_design_tick()                 every 2 minutes, on the worker: the week's flyers land (B9)
  openings_watch_tick()                   every 15 minutes, on the worker: pull a post whose chairs booked (B11)
  POST /marketing/{business_id}/engine/run   owner: queue a suggestion, a week or open chairs now
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
  switch, the accounts, the rate limit and one request a day, then claims the
  week and marks it queued in ONE write (queue_request), so a failed write
  changes nothing, and answers 202. Nothing is cancelled then: manual_tick on
  the worker starts each queued run once (a conditional write on
  design.started_at), saves the new suggestion, and only then cancels the
  week's earlier suggestion draft (if that cancel fails the owner sees two,
  never none). A request that writes nothing (skipped, failed, over a spend
  ceiling, no time left) leaves the earlier suggestion exactly as it was and
  does not count against the day. A week with an approved or sent post is
  never touched.

THE WEEKLY PLAN (B9, run_week)
  The suggestion's steps, five times over in one run (kind 'week'): up to
  five weekday times on the business's clock at the desk's hour (3:00 PM
  when that hour is taken), the plays leaning on what did well through the
  business's own links once a play has 3 results (business_marketing_outcomes
  .play_scores; otherwise the default order), ONE caption call for all five,
  then all five drafts saved in one write with design_status 'designing'.
  Then one Creative Director flyer per post, 4:5 (1088x1360, Instagram's
  tallest feed picture), in the business's own colours, under the build
  actor bound to the business and its owner, request id uuid5(run, 'flyer:'
  + post id) so a retried run lands on the same design. The flyers are
  INCLUDED in the plan (Kevin, 2026-10-07): creative_director.include_in_plan,
  server-set here only, skips the credit charge; the cost is still metered
  (units=0) and the spend guards and the 20-a-day design limit still apply.
  At most 5 plan flyers per business per week (a replan gets what is left);
  at most MARKETING_DESIGNS_AT_ONCE designs in progress across every
  business; a post whose flyer hits the daily limit (429), cannot start, or
  is not ready 20 minutes after it started goes as words only, Instagram
  left out, with a plain note. It never holds up the week.

  marketing_design_tick (every 2 minutes) attaches each finished flyer to its
  post (media, a new revision and content hash, design_status 'ready'; the
  post stays a draft for the owner's OK) and gives up on late or failed
  ones. Once no post of the run is designing, the owner is told ONCE: a
  push and a Today item, "Chief planned next week: 5 posts wait for your OK".
  At the autopilot level (Solutionist, B13) the kinds the owner's standing
  OK covers are approved first (business_marketing_standing.approve_run,
  through marketing_approve with approved_via 'standing') and the one tell
  says so: "Chief approved 5 posts for next week under your standing OK".
  The same tick puts back to waiting any post approved on a standing OK
  that no longer covers it (business_marketing_standing.lapse_sweep).

  The owner's request for a week (POST /engine/run) queues it like a
  suggestion; a week can be re-planned at most twice, only while none of its
  posts is approved, sent or still designing, and the new drafts are saved
  before the old ones are retired.

CLIPS IN THE WEEK (B12, Solutionist: the autopilot level, D6)
  The week above, plus up to TWO of the business's own video clips
  (business_marketing_clips has the clips' half): ready, kept, approved at
  the fingerprint they have now, not posted anywhere, not in a waiting post,
  with a ready story cover; best score first, then newest. Each on its own
  weekday at the desk's hour or the next free hour, 3 hours from any other
  post that day. They ADD to the five (seven at most). Each is one more slot
  in the week's ONE caption call (no flyer, the same business checks), then a
  source 'clip' draft in the week's one insert: media is the clip with its
  fingerprint and covers (inside the content hash), to every desk account
  that takes a video, TikTok and YouTube included, with its tracked link.
  The sender posts it through clip_posting.post_clip_for. Professional and
  Boss never get clips. No eligible clip: the week is exactly B9's.

THE OPEN-CHAIRS WEEK (B11, run_openings; Boss, D5)
  The week's machinery (kind 'openings': the same claim, fan-out, jitter,
  per-tick cap, spend headroom, owner's request and save-new-before-retire-
  old), planned from the chair calendar instead of the numbers: the
  most-booked offering's open slots next week, grouped into windows; the
  three biggest (slow days first), one per day; each post the day before
  (or that morning) at least two hours before its window; Instagram first,
  Facebook too; linking to the booking page. ONE small caption call for the
  three (a caption that breaks a rule, says a seat count or names the wrong
  day gets the plain caption instead); the owner's newest work photo with
  the words laid over by the free composer (cost 0), else the branded flyer.
  Every post stores its `opening`; openings_watch_tick and the sender pull
  it when its window books first (business_marketing_openings).
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
import business_marketing_clips as clips
import business_marketing_desk as reading
import business_marketing_engine as engine
import business_marketing_links as links
import business_marketing_openings as openings
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

# The weekly plan (B9).
WEEK_KIND = 'week'
WEEK_TASK = 'business_marketing_week'
WEEK_LEVELS = ('week', 'autopilot')   # autopilot (Practice): the week plus its own clips (B12) and standing OKs (B13)
WEEK_MAX_TOKENS = 4000                # five captions and five flyers' three lines
FLYERS_PER_WEEK = 5                   # plan flyers per business per week, replans included
FLYER_SIZE = '1088x1360'              # 4:5: Instagram's tallest feed picture, shown whole
FLYER_SQUARE = '1024x1024'            # for an image model without custom sizes (gpt-image-2): still Instagram-safe
FLYER_QUALITY = 'high'
DESIGN_TIMEOUT = timedelta(minutes=20)
DEFAULT_DESIGNS_AT_ONCE = 10          # plan flyers in progress across every business
MAX_DESIGNS_AT_ONCE = 50
REPLANS_PER_WEEK = 2
MANUAL_WAIT = timedelta(minutes=10)   # an owner's week that cannot start for want of design room
DESIGN_BATCH = 100
TELL_BATCH = 50
# Conservative estimates for the fan-out's spend headroom (USD). One Creative
# Director design at high quality, 1088x1360: a planning call, the render
# (about $0.20 at the image model's rates), the review, and the one repair
# render it may take. The captions are one small Sonnet-class call.
DESIGN_ESTIMATE_USD = 0.50
CAPTIONS_ESTIMATE_USD = 0.05
WEEK_ESTIMATE_USD = CAPTIONS_ESTIMATE_USD + FLYERS_PER_WEEK * DESIGN_ESTIMATE_USD

# The open-chairs week (B11).
OPENINGS_KIND = 'openings'
OPENINGS_TASK = 'business_marketing_openings'
OPENINGS_MAX_TOKENS = 2000            # three short captions
OPENINGS_SLOTS = openings.POSTS_PER_WEEK
CHAIR_PLATFORMS = ('instagram', 'facebook')   # Instagram first, Facebook too when connected

PLAN_COLUMNS = 'comp_tier,subscription_status,subscription_plan,trial_ends_at,stripe_subscription_id'
FULL_COLUMNS = f'{marketing_profile.BUSINESS_COLUMNS},{PLAN_COLUMNS}'
CANDIDATE_COLUMNS = (f'id,owner_id,type,{PLAN_COLUMNS},availability:settings->availability,'
                     'automations_paused:settings->automations_paused,booking_page:settings->booking_page')
RUN_COLUMNS = 'id,business_id,week_of,kind,trigger,status,attempts,design,created_at'

# What the owner reads (on the desk's "could not be written", in Today, in a
# push): plain words, never the machinery.
NOT_SWITCHED_ON = "Chief's weekly suggestion isn't switched on for this business yet."
NO_ACCOUNTS = 'Connect an account first, in Build, Social Media.'
NO_POSTING = "Posting to your social accounts isn't switched on for this business yet."
NO_PLAN = "Chief's weekly suggestion comes with every plan. Choose a plan to get one."
WEEK_LEVEL = "Your plan comes with Chief's weekly plan of five posts, so Chief writes that instead of one suggestion."
OPENINGS_LEVEL = ("Your plan comes with Chief's open-chairs week, made from your booking calendar, so Chief writes "
                  'that instead.')
NOT_WEEK = "Chief's weekly plan of five posts comes with the Professional plan. Nothing was queued."
NOT_OPENINGS = ("Chief's open-chairs week comes with the Boss plan and a live booking calendar. Nothing was "
                'queued.')
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
KEPT = 'The earlier suggestion is still on the desk.'
WEEK_KEPT = "The week's earlier plan is still on the desk."
APPROVED_MEANWHILE = "The week's suggestion was approved in the meantime, so Chief left it as it is."
# The weekly plan's words (B9).
WEEK_QUEUED = 'Chief is planning your week: five posts, each with a flyer. They show up here in a few minutes.'
WEEK_CLIPS_QUEUED = ('Chief is planning your week: five posts, each with a flyer, and up to two of your own video '
                     'clips. They show up here in a few minutes.')
WEEK_BUSY = ("That week is being planned, or one of its posts is already approved or sent, so Chief can't "
             'plan it again. Nothing new was queued.')
STILL_DESIGNING = "Chief is still making this week's flyers. Ask again once they are ready. Nothing new was queued."
REPLANNED_TWICE = ('Chief has already planned this week again twice. Change or skip the posts on the desk instead. '
                   'Nothing new was queued.')
WEEK_APPROVED_MEANWHILE = "A post of this week was approved in the meantime, so Chief left the week as it is."
DESIGNS_BUSY = "Chief is making a lot of flyers right now, so your week couldn't be planned yet. Ask again soon."
WEEK_CAPTIONS_BROKE = ('Every caption Chief wrote said something your site does not (a number, a price or an '
                       'address), so nothing was saved.')
WEEK_SAVE_FAILED = "This week's posts couldn't be saved just now. Nothing was posted."
WEEK_FAILED = 'The weekly plan could not be finished. Nothing was posted.'
# The open-chairs week's words (B11).
OPENINGS_QUEUED = ('Chief is planning your open chairs: up to three posts from your booking calendar. They show up '
                   'here in a minute or two.')
OPENINGS_KEPT = "The week's earlier open-chairs posts are still on the desk."
NO_HOURS = ("Your booking calendar has no weekly hours set, so Chief can't tell which chairs are open. Set your "
            'hours in Settings, Availability.')
NOTHING_BOOKABLE = 'Nothing on your booking calendar is booked by the slot, so there are no open chairs to post.'
CALENDAR_FULL = "Every time on that week's calendar is already booked, so there are no open chairs to post."
NO_OPENING_TIME = "No open time that week leaves room to post about it beforehand, so nothing was written."
NO_CHAIR_ACCOUNTS = 'Open chairs go to Instagram and Facebook. Connect one of them in Build, Social Media.'
OPENINGS_SAVE_FAILED = "This week's open-chairs posts couldn't be saved just now. Nothing was posted."
OPENINGS_FAILED = 'The open-chairs week could not be finished. Nothing was posted.'
# Why a plan post goes without its flyer: "<why>, so this post goes as words only[, and Instagram is left out]."
NO_FLYER = {
    'timeout': "The flyer wasn't ready in time",
    'failed': "The flyer couldn't be made",
    'limit': "This business reached today's limit on new pictures",
    'week': "This week's five included flyers are already made",
    'words': "The flyer's words didn't pass Chief's checks",
    'start': "The flyer couldn't be started",
}
LOOK_CLOSELY = "Chief's own check of this flyer found something to look at{issue}. Look at the picture before you approve."
# What an owner's request adds to marketing_runs.design. The first three
# travel with the run; made and outcome say how the request ended (made: the
# new post's id, the one thing the once-a-day rule counts).
QUEUE_KEYS = ('queued_at', 'queued_by', 'started_at', 'made', 'outcome')


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


def designs_at_once() -> int:
    """MARKETING_DESIGNS_AT_ONCE: how many weekly-plan flyers may be in
    progress at once across every business (default 10: two weeks)."""
    try:
        n = int(os.environ.get('MARKETING_DESIGNS_AT_ONCE') or DEFAULT_DESIGNS_AT_ONCE)
    except ValueError:
        n = DEFAULT_DESIGNS_AT_ONCE
    return max(FLYERS_PER_WEEK, min(n, MAX_DESIGNS_AT_ONCE))


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
    words. A week level gets its weekly plan instead (B9)."""
    if feature_gates.plan_includes(row, 'marketing_week'):
        return WEEK_LEVEL
    if not feature_gates.plan_includes(row, 'marketing_suggestion'):
        return NO_PLAN
    return None


def _with_settings(row: Dict[str, Any]) -> Dict[str, Any]:
    """A candidate row (settings read as columns) in the shape the desk's
    level reads (business_marketing.has_chair_calendar reads settings)."""
    if isinstance(row.get('settings'), dict):
        return row
    return {**row, 'settings': {'booking_page': row.get('booking_page'), 'availability': row.get('availability')}}


def _level(row: Dict[str, Any]) -> str:
    """The desk's own level (business_marketing.level_for). Raises
    Unavailable when the calendar cannot be read: never a guess at the level."""
    try:
        return bm.level_for(_with_settings(row))['level']
    except HTTPException:
        raise Unavailable('the booking calendar') from None


def week_problem(row: Dict[str, Any]) -> Optional[str]:
    """None at a week level by the real plan (week, or autopilot, which gets
    the plain week until B12/B13); else why not. A chair business with a
    live calendar is the openings level: it gets the open-chairs week (B11)
    instead of this one. Raises Unavailable when the calendar cannot be read."""
    if not feature_gates.plan_includes(row, 'marketing_week'):
        return NOT_WEEK
    return None if _level(row) in WEEK_LEVELS else OPENINGS_LEVEL


def openings_problem(row: Dict[str, Any]) -> Optional[str]:
    """None at the openings level (marketing_week on a chair business with
    a live calendar: Boss); else why not. Raises Unavailable when the
    calendar cannot be read."""
    if not feature_gates.plan_includes(row, 'marketing_week'):
        return NOT_OPENINGS
    return None if _level(row) == OPENINGS_KIND else NOT_OPENINGS


def run_kind(row: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """What Chief writes for this business each week: (KIND, None) at the
    suggest level, (WEEK_KIND, None) at a week level, (OPENINGS_KIND, None)
    at the openings level, else (None, why not)."""
    if feature_gates.plan_includes(row, 'marketing_week'):
        level = _level(row)
        if level == OPENINGS_KIND:
            return OPENINGS_KIND, None
        return (WEEK_KIND, None) if level in WEEK_LEVELS else (None, NOT_WEEK)
    problem = level_problem(row)
    return (None, problem) if problem else (KIND, None)


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


def eligibility(row: Dict[str, Any], *, scheduled: bool, kind: str = KIND) -> Optional[str]:
    """Why this business gets no suggestion (kind KIND), weekly plan
    (WEEK_KIND) or open-chairs week (OPENINGS_KIND) now, in plain words, or
    None. The owner's own request is not an automation, so a pause does not
    stop it."""
    bid = str(row.get('id') or '')
    if not desk_on_for(bid):
        return NOT_SWITCHED_ON
    if not post_for_me.allowed_for(bid):
        return NO_POSTING
    problem = (week_problem(row) if kind == WEEK_KIND else openings_problem(row) if kind == OPENINGS_KIND
               else level_problem(row))
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


def _eligible_kind(row: Dict[str, Any]) -> Optional[str]:
    """The kind of run the fan-out may write for this business now, or None.
    A calendar that cannot be read leaves the business out this hour."""
    try:
        kind, _ = run_kind(row)
        if kind and eligibility(row, scheduled=True, kind=kind) is None:
            return kind
    except Unavailable:
        log.warning('marketing planner: the level of %s could not be read this hour', str(row.get('id'))[:8])
    return None


async def candidates(scope: Any) -> List[Dict[str, Any]]:
    """Every business the fan-out may write for, each with the kind of run
    it gets (`_kind`: a suggestion, the weekly plan or the open-chairs
    week). Raises on a failed read: a blip never reads as "nobody to do"."""
    ids = await _desk_ids(scope)
    if not ids:
        return []
    with_accounts = await asyncio.to_thread(_connected_ids, ids)
    ids = [i for i in ids if i in with_accounts]
    if not ids:
        return []
    rows = await asyncio.to_thread(_business_rows, ids)
    kinds = await asyncio.to_thread(lambda: [_eligible_kind(r) for r in rows])
    return [{**r, '_kind': k} for r, k in zip(rows, kinds) if k]


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
          profile: Dict[str, Any], *, number: int = 1,
          first_if_missing: bool = True) -> Tuple[Optional[str], Optional[Dict[str, str]], List[Dict[str, Any]]]:
    """(caption, flyer copy, dropped) for slot `number`. A caption that
    breaks a rule is not used at all; flyer copy that breaks one costs the
    post its picture only. The one-slot suggestion takes the first entry if
    the model numbered it wrong; the week (first_if_missing=False) never
    gives one slot another's words."""
    items = parsed.get('captions') if isinstance(parsed.get('captions'), list) else []
    item = next((i for i in items if isinstance(i, dict) and i.get('slot') == number),
                next((i for i in items if isinstance(i, dict)), None) if first_if_missing else None)
    text = item.get('text') if item else None
    if not isinstance(text, str):
        return None, None, [{'slot': number, 'reason': 'missing'}]
    offering = slot.get('offering')
    problem = engine.check_caption(text, facts, profile, offering)
    if problem:
        return None, None, [{'slot': number, 'reason': problem}]
    flyer = item.get('flyer')
    flyer_problem = engine.check_flyer(flyer, facts, profile, offering) if isinstance(flyer, dict) else 'no flyer copy'
    if flyer_problem:
        return text.strip(), None, [{'slot': number, 'reason': flyer_problem, 'flyer_only': True}]
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


async def _standing(business_id: str, run_id: Any) -> Optional[List[Dict[str, Any]]]:
    """The week's posts that are not cancelled, or None when they cannot be read."""
    try:
        return await store.rows(f'/marketing_posts?run_id=eq.{UUID(str(run_id))}&business_id=eq.{business_id}'
                                '&status=neq.cancelled&select=id,status,revision,run_at,play_id&limit=10')
    except store.StoreError:
        return None


async def _close(business_id: str, run_id: Any, at: datetime, *, status: str, error: str, manual: bool,
                 prior: Optional[Dict[str, Any]] = None, design: Optional[Dict[str, Any]] = None,
                 record: Optional[Dict[str, Any]] = None,
                 standing: Optional[List[Dict[str, Any]]] = None, kept_note: str = KEPT) -> str:
    """End a run that wrote nothing new; returns how it ended.

    An owner's start-over that wrote nothing leaves the week's earlier
    suggestion exactly as it was: the run goes back to succeeded over it
    ('kept'), the reason in its error, and nothing counts against the
    once-a-day request (no design.made). Otherwise the run is skipped or
    failed with the reason. If the earlier posts cannot be read, the run is
    marked skipped or failed: a warning on the desk, never a lost post."""
    if manual:
        if standing is None:
            standing = await _standing(business_id, run_id)
        if standing:
            keep = {**(prior if isinstance(prior, dict) else {}), 'outcome': 'kept'}
            keep.pop('made', None)
            await _finish(business_id, run_id, at, status='succeeded', post_ids=[str(p['id']) for p in standing],
                          error=f'{error} {kept_note}', design=keep)
            return 'kept'
    fields = dict(record or {})
    if design is not None:
        fields['design'] = design
    await _finish(business_id, run_id, at, status=status, error=error, **fields)
    return status


async def _retire(business_id: str, run_id: Any, previous: List[Dict[str, Any]], keep_id: Any) -> List[str]:
    """Cancel the week's earlier drafts (a suggestion's, or a week's), only
    once the new ones are saved. keep_id: the new post's id, or the new
    posts' ids. Each write lands only on a draft still at the revision read;
    one that moved on (approved meanwhile) or a write that fails is left
    standing, so the owner sees two and can skip one, never none. Returns the
    ids still standing."""
    keep = {keep_id} if isinstance(keep_id, str) else {str(k) for k in keep_id}
    left = []
    for p in previous:
        pid = str(p['id'])
        if pid in keep:
            continue
        revision = int(p.get('revision') or 1)
        try:
            out = await store.request(
                'PATCH', f'/marketing_posts?id=eq.{UUID(pid)}&business_id=eq.{business_id}'
                         f'&run_id=eq.{UUID(str(run_id))}&status=eq.draft&revision=eq.{revision}',
                {'status': 'cancelled', 'revision': revision + 1})
        except store.StoreError:
            out = None
        if not out:
            log.warning('marketing planner: an earlier suggestion %s was left standing', pid[:8])
            left.append(pid)
    return left


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
    A manual start-over replaces the week's waiting suggestion only once the
    new one is saved; when it writes nothing, the earlier one stays exactly
    as it was. Never approves or sends anything."""
    if trigger not in store.RUN_TRIGGERS:
        raise ValueError('Unknown trigger.')
    bid = str(UUID(str(business_id)))
    at = now or _now()
    manual = trigger == 'manual'
    row = business if business and all(k in business for k in FULL_COLUMNS.split(',')) else None
    run_id = UUID(str(run['id'])) if run else None
    prior = run.get('design') if run and isinstance(run.get('design'), dict) else {}

    async def stop(status: str, error: str, out: Dict[str, Any]) -> Dict[str, Any]:
        if run_id:
            ended = await _close(bid, run_id, at, status=status, error=error, manual=manual, prior=prior)
            return {**out, 'status': ended if ended == 'kept' else out['status']}
        return out

    try:
        row = row or await asyncio.to_thread(read_business, bid)
        tz = await asyncio.to_thread(marketing_profile.time_zone, row)
        desk = await store.get_desk(bid)
    except LookupError:
        return await stop('skipped', 'This business no longer exists.',
                          {'status': 'not_eligible', 'reason': 'Business not found.'})
    except (Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        return await stop('failed', READ_FAILED, {'status': 'unavailable', 'reason': READ_FAILED})

    reason = eligibility(row, scheduled=not manual)
    if reason is None and not manual and not (desk or {}).get('plan_enabled'):
        reason = NOT_SWITCHED_ON
    if reason:
        return await stop('skipped', reason, {'status': 'not_eligible', 'reason': reason})

    week_of = date.fromisoformat(str(run['week_of'])[:10]) if run else target_week(at, tz)
    try:
        when = await slot_time(bid, tz, (desk or {}).get('post_hour', 11), week_of, at)
    except Unavailable:
        return await stop('failed', READ_FAILED, {'status': 'unavailable', 'reason': READ_FAILED})
    if when is None:
        return await stop('skipped', NO_TIME, {'status': 'no_time', 'reason': NO_TIME,
                                               'week_of': week_of.isoformat()})

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
    request = {k: prior[k] for k in QUEUE_KEYS[:3] if k in prior} if manual else {}
    return await _plan(row, desk, tz, run_id, week_of, when, attempt, at, request, manual=manual, prior=prior)


async def _plan(row: Dict[str, Any], desk: Optional[Dict[str, Any]], tz: ZoneInfo, run_id: UUID, week_of: date,
                when: datetime, attempt: int, at: datetime, request: Dict[str, Any], *, manual: bool,
                prior: Dict[str, Any]) -> Dict[str, Any]:
    """The claimed run, written and recorded. Every way out marks the run."""
    import creative_director
    import llm_call
    import spend_guard
    bid = str(row['id'])
    record: Dict[str, Any] = {}
    design: Dict[str, Any] = dict(request)
    standing: Optional[List[Dict[str, Any]]] = None

    async def close(status: str, error: str) -> Dict[str, Any]:
        ended = await _close(bid, run_id, at, status=status, error=error, manual=manual, prior=prior,
                             design=design, record=record, standing=standing)
        return {'status': ended, 'reason': error, 'run_id': str(run_id)}

    try:
        if not llm_call.api_key():
            raise Skip(NO_WRITER)
        if await asyncio.to_thread(spend_guard.over_budget, bid):
            raise Skip(spend_guard.block_message())
        standing = await store.rows(f'/marketing_posts?run_id=eq.{run_id}&business_id=eq.{bid}'
                                    '&status=neq.cancelled&select=id,status,revision,run_at,play_id&limit=10')
        own = suggestion_post_id(run_id, attempt)
        mine = [p for p in standing if str(p['id']) == own]
        if mine or (standing and not manual):
            # This attempt (or, for the scheduler, an earlier one) saved its
            # draft and stopped before recording it or telling the owner.
            keep = mine or standing
            ids, fields = [str(p['id']) for p in standing], {}
            if mine and manual:
                left = await _retire(bid, run_id, [p for p in standing if p.get('status') == 'draft'], own)
                ids, fields = [own] + left, {'design': {**prior, 'made': own}}
            await _finish(bid, run_id, at, status='succeeded', post_ids=ids, error=None, **fields)
            await tell_owner(row, keep[0], {'play_id': keep[0].get('play_id')}, tz, week_of, at)
            return {'status': 'succeeded', 'run_id': str(run_id), 'post_id': str(keep[0]['id']),
                    'week_of': week_of.isoformat(), 'resumed': True}
        if manual and any(p.get('status') != 'draft' for p in standing):
            raise Skip(APPROVED_MEANWHILE)
        previous = [p for p in standing if p.get('status') == 'draft']
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
            return await close('failed', CAPTION_BROKE)

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
        post_id = own
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
            return await close('failed', SAVE_FAILED)
        # The new suggestion exists; only now does the earlier one go.
        left = await _retire(bid, run_id, previous, post_id)
        design['made'] = post_id
        if previous:
            design['replaced'] = [str(p['id']) for p in previous if str(p['id']) not in left]
        await _finish(bid, run_id, at, status='succeeded', post_ids=[post_id] + left, error=None, design=design,
                      **record)
        await tell_owner(row, post, slot, tz, week_of, at)
        return {'status': 'succeeded', 'run_id': str(run_id), 'post_id': post_id, 'week_of': week_of.isoformat()}
    except Skip as reason:
        return await close('skipped', str(reason))
    except (Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        log.warning('marketing planner: a read for %s failed', bid[:8], exc_info=True)
        return await close('failed', READ_FAILED)
    except Exception:
        log.warning('marketing planner: the suggestion for %s could not be finished', bid[:8], exc_info=True)
        return await close('failed', FAILED)


# ── the weekly plan (B9) ──────────────────────────────────────────────

def week_post_id(run_id: Any, attempt: int, slot: int) -> str:
    """One post per slot per attempt of the week's run: a retry inside an
    attempt is the same post, and a replan (a new attempt) gets new ones."""
    return str(uuid5(UUID(str(run_id)), f'{int(attempt)}:week:{int(slot)}'))


def flyer_request_id(run_id: Any, post_id: Any) -> UUID:
    """A plan flyer's Image Studio request id: uuid5(run, 'flyer:' + the
    slot's post id). A retried run, or a second start for the same post,
    lands on the same image_artworks row (image_studio.create answers with it
    and never reserves or pays twice); a replan's new posts get new designs."""
    return uuid5(UUID(str(run_id)), f'flyer:{UUID(str(post_id))}')


def _hours(post_hour: Any) -> Tuple[int, ...]:
    """The desk's hour, then 3:00 PM (business_marketing.open_hours, in the order to try them)."""
    try:
        hour = int(post_hour)
    except (TypeError, ValueError):
        hour = 11
    hour = hour if 6 <= hour <= 21 else 11
    return tuple(dict.fromkeys((hour, bm.OTHER_HOUR)))


async def week_times(business_id: str, tz: ZoneInfo, post_hour: Any, week_of: date,
                     at: datetime) -> List[datetime]:
    """The week's posting times, like the platform's week_window: each
    weekday of that week at the desk's hour (3:00 PM when the desk's hour
    already has a post), on the business's own clock, at least an hour away.
    A week planned Monday to Wednesday gets the weekdays it has left. Raises
    Unavailable when the calendar cannot be read."""
    start = datetime.combine(week_of, time(0), tz)
    end = datetime.combine(week_of + timedelta(days=7), time(0), tz)
    try:
        taken_rows = await store.rows(
            f'/marketing_posts?business_id=eq.{business_id}&select=run_at&status=not.in.(cancelled,pulled)'
            f'&run_at=gte.{reading.query_time(start)}&run_at=lt.{reading.query_time(end)}&limit={bm.TAKEN_LIMIT}')
    except store.StoreError:
        raise Unavailable('the calendar') from None
    taken = {bm._aware(r['run_at']).timestamp() for r in taken_rows}
    out: List[datetime] = []
    for offset in range(5):
        day = week_of + timedelta(days=offset)
        for hour in _hours(post_hour):
            slot = datetime.combine(day, time(hour), tz)
            if slot > at + bm.SLOT_AFTER and slot.timestamp() not in taken:
                out.append(slot)
                break
    return out[:WEEK_SLOTS]


def week_caption_request(slots: List[Dict[str, Any]], facts: Dict[str, Any],
                         profile: Dict[str, Any]) -> Dict[str, Any]:
    out = []
    for slot in slots:
        if slot.get('clip'):
            out.append(clips.request_item(slot))          # B12: one of the business's own clips
            continue
        play = engine.PLAYS[slot['play_id']]
        out.append({'slot': slot['slot'], 'play': play['label'], 'play_brief': play['brief'],
                    'subject': slot.get('subject'), 'offering': slot.get('offering')})
    return {'audience': profile.get('audience'), 'voice': profile.get('voice'), 'facts': facts, 'slots': out}


async def write_week_captions(business_id: str, slots: List[Dict[str, Any]], facts: Dict[str, Any],
                              profile: Dict[str, Any]) -> Dict[int, Tuple[Optional[str], Optional[Dict[str, str]],
                                                                          List[Dict[str, Any]]]]:
    """ONE model call for every caption of the week, metered to the business
    (units=0: the plan bills the owner nothing), each held to the same
    business caption checks as the suggestion. {slot: (caption, flyer copy,
    dropped)}; a slot the model skipped or numbered wrong has no caption. A
    clip's slot (B12) is one more caption in the same call, with no flyer."""
    import llm_call
    import model_ladder
    from chief_models import model_for
    model = model_for('draft')
    room = WEEK_MAX_TOKENS + clips.MAX_TOKENS_EACH * sum(1 for s in slots if s.get('clip'))
    payload = {'model': model, 'max_tokens': room, 'system': profile['system_prompt'],
               'messages': [{'role': 'user', 'content': json.dumps(week_caption_request(slots, facts, profile),
                                                                   default=str)}],
               **model_ladder.effort_kwargs(model, EFFORT)}
    async with httpx.AsyncClient() as client:
        response = await llm_call.apost(client, payload, timeout=CALL_TIMEOUT * 2, task=WEEK_TASK,
                                        business_id=business_id, units=0)
    response.raise_for_status()
    parsed = _parse(llm_call.text_of(response.json()))
    return {s['slot']: (clips.judge(parsed, s, facts, profile) if s.get('clip')
                        else judge(parsed, s, facts, profile, number=s['slot'], first_if_missing=False))
            for s in slots}


# Every desk picture is Instagram-safe as delivered: the feed takes 4:5 to
# 1.91:1 and shows a 4:5 picture whole. The profile grid shows a 3:4 crop of
# it (of 1088x1360, 34 pixels off each side), so the words keep a margin.
SAFE_AREA = {
    FLYER_SIZE: ("Portrait 4:5, the tallest picture Instagram's feed shows whole, made for Instagram and Facebook "
                 'feeds. Keep every word, the button and the main subject at least a twentieth of the width in '
                 'from every edge: the profile grid trims a little off each side.'),
    FLYER_SQUARE: ('Square, made for Instagram and Facebook feeds, which show it whole. Keep every word, the button '
                   'and the main subject at least a twentieth of the width in from every edge.'),
}


def flyer_size() -> str:
    """4:5 (1088x1360) on the image models that take custom sizes; square
    on one that does not (gpt-image-2 makes only its three sizes, and its
    2:3 portrait is taller than Instagram's feed takes)."""
    import image_studio as images
    try:
        return FLYER_SIZE if FLYER_SIZE in images.model_sizes(images.configured_model()) else FLYER_SQUARE
    except HTTPException:
        return FLYER_SIZE          # an unsupported model: create() refuses it in plain words


def flyer_goal(slot: Dict[str, Any], profile: Dict[str, Any], business: Dict[str, Any],
               size: str = FLYER_SIZE) -> str:
    play = engine.PLAYS[slot['play_id']]
    name = profile.get('brand_name') or business.get('name') or 'the business'
    subject = slot.get('subject') if slot.get('play_id') in ('offer_spotlight', 'whats_new') else None
    return (f'A social media flyer for {name}, posted with this week\'s "{play["label"]}" post'
            + (f' about "{str(subject)[:120]}"' if subject else '') + '. ' + SAFE_AREA[size]
            + " Use the business's own brand colours from the facts when it has them, and nobody else's. "
            'The words are exactly the copy, in this order: the headline set large, the supporting line, the call '
            "to action as a button, and the business's name small at the foot. No other words, numbers, prices "
            'or claims, and no people.')


def flyer_copy(copy: Dict[str, str], profile: Dict[str, Any], business: Dict[str, Any]) -> List[str]:
    name = ' '.join(str(profile.get('brand_name') or business.get('name') or '').split())
    return [copy['headline'], copy['line'], copy['cta']] + ([name[:120]] if name else [])


async def start_flyer(business: Dict[str, Any], post: Dict[str, Any], slot: Dict[str, Any],
                      copy: Dict[str, str], profile: Dict[str, Any], run_id: Any) -> Tuple[str, Optional[str]]:
    """Start one plan post's Creative Director flyer: 4:5 (flyer_size), the
    business's own colours, its words checked, INCLUDED in the plan
    (creative_director.include_in_plan, set here and nowhere else: no credit
    charge, still metered and spend-guarded, still one of the business's 20
    designs a day). Made under image_studio.build_actor bound to this
    business and its owner (`business` is a service-role read), reset in a
    finally; the design itself runs on as Image Studio's worker task.
    Returns ('started', None); ('limit', why) when the daily design limit
    answered 429; ('start', why) when it could not start; ('unknown', why)
    when it did not start here and whether its design already exists cannot
    be read. A design that already exists (a retried run, a race with one)
    is 'started' whatever this call met: its post is never given up on here,
    and the design tick settles it."""
    import creative_director
    import image_studio as images
    bid, owner = str(business['id']), str(business.get('owner_id') or '')
    if not owner:
        return 'start', 'no owner on record'
    request_id = flyer_request_id(run_id, post['id'])
    size = flyer_size()
    action = {'goal': flyer_goal(slot, profile, business, size), 'exact_copy': flyer_copy(copy, profile, business),
              'size': size}
    outcome, why = 'started', None
    token = images.build_actor.set({'business_id': bid, 'user_id': owner})
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            req = creative_director.flyer_request(action)
            biz = await images.business(client, bid)
            spec = await creative_director.prepare_for_business(
                client, biz, req, owner_request=f"Chief's weekly plan: the flyer for a {engine.PLAYS[slot['play_id']]['label'].lower()} post",
                owner_context=f"The post's caption: {post.get('caption') or ''}")
            spec = creative_director.include_in_plan(spec)
            await images.create(images.CreateImage(
                business_id=bid, request_id=request_id, prompt=req.goal, quality=FLYER_QUALITY, size=size,
                reference_ids=[r['id'] for r in spec['references']]), client, director=spec)
    except HTTPException as exc:
        detail = exc.detail.get('message') if isinstance(exc.detail, dict) else exc.detail
        outcome, why = ('limit' if exc.status_code == 429 else 'start'), str(detail or '')[:200]
    except Exception:
        log.warning('marketing planner: a flyer for %s could not start', bid[:8], exc_info=True)
        outcome, why = 'start', 'the design could not start'
    finally:
        images.build_actor.reset(token)
    if outcome == 'started':
        return outcome, why
    try:
        if await asyncio.to_thread(flyer_rows, bid, [str(request_id)]):
            return 'started', None          # it is being made (or made): never words only over it
    except Unavailable:
        return 'unknown', why
    return outcome, why


def no_flyer_note(reason: str, gone: List[Dict[str, Any]], *, picture_needed: bool = False) -> str:
    """'<why>, so this post goes as words only, and Instagram is left out.'"""
    why = NO_FLYER.get(reason, NO_FLYER['failed'])
    if picture_needed:
        return f'{why}, and Instagram needs a picture: add one on the desk, or skip this post.'
    labels = list(dict.fromkeys(d['label'] for d in bm._public_dropped(gone)))
    if not labels:
        return f'{why}, so this post goes as words only.'
    names = ' and '.join(labels)
    return f"{why}, so this post goes as words only, and {names} {'is' if len(labels) == 1 else 'are'} left out."


def without_flyer(post: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """The patch for a plan post that goes without its flyer: words only,
    Instagram left out (when nothing would be left, it stays and the note
    says to add a picture), design_status 'failed', a new revision and
    content hash. It stays a draft."""
    targets = list(post.get('targets') or [])
    kept, gone = bm.fit(targets, None)
    if kept:
        note = no_flyer_note(reason, gone)
    else:
        kept, note = targets, no_flyer_note(reason, gone, picture_needed=True)
    patch = {'media': {}, 'targets': kept, 'design_status': 'failed', 'error': note,
             'revision': int(post.get('revision') or 1) + 1}
    patch['content_hash'] = store.digest({**post, **patch})
    return patch


def with_flyer(post: Dict[str, Any], image: Dict[str, Any]) -> Dict[str, Any]:
    """The patch that puts a finished flyer on its post: the artwork as its
    media, a new revision and content hash, design_status 'ready'. It stays a
    draft, for the owner's OK. A flyer Chief's own check was unsure about
    says so in the post's note."""
    note = None
    if image.get('phase') != 'complete':
        issues = (image.get('review') or {}).get('issues') if isinstance(image.get('review'), dict) else None
        first = str(issues[0])[:160] if isinstance(issues, list) and issues else ''
        note = LOOK_CLOSELY.format(issue=f' ({first})' if first else '')
    patch = {'media': {'artwork_ids': [str(image['id'])]}, 'design_status': 'ready', 'error': note,
             'revision': int(post.get('revision') or 1) + 1}
    patch['content_hash'] = store.digest({**post, **patch})
    return patch


async def _settle_post(business_id: str, post: Dict[str, Any], patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Write a designing post's outcome, only while it is still the draft
    read (same revision, still designing). None when it moved on."""
    out = await store.request(
        'PATCH', f"/marketing_posts?id=eq.{UUID(str(post['id']))}&business_id=eq.{business_id}"
                 f"&revision=eq.{int(post.get('revision') or 1)}&status=eq.draft&design_status=eq.designing", patch)
    return out[0] if isinstance(out, list) and out else None


FLYER_COLUMNS = 'id,business_id,status,storage_path,created_at,phase:director->>phase,review:director->review'


def flyer_rows(business_id: str, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """These flyers' image_artworks rows (this business's only), by id.
    A failed read raises Unavailable: never "not started"."""
    out: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunks(sorted(set(ids))):
        for r in _get(f"/image_artworks?business_id=eq.{business_id}&id=in.({','.join(chunk)})"
                      f'&select={FLYER_COLUMNS}'):
            if str(r.get('business_id')) == str(business_id):
                out[str(r['id'])] = r
    return out


def flyers_made(business_id: str, run_id: Any, posts: List[Dict[str, Any]]) -> int:
    """How many plan flyers this week's run has started so far, every
    attempt and replan included (the image rows that exist for its posts)."""
    ids = [str(flyer_request_id(run_id, p['id'])) for p in posts]
    return len(flyer_rows(business_id, ids)) if ids else 0


async def designs_in_progress() -> Optional[int]:
    """Plan posts whose flyer is still being made, across every business
    (None when it cannot be read: the caller then starts no design)."""
    try:
        rows = await store.rows(f'/marketing_posts?design_status=eq.designing&select=id&limit={MAX_DESIGNS_AT_ONCE + 1}')
    except store.StoreError:
        return None
    return len(rows)


async def run_week(business_id: Any, *, trigger: str, now: Optional[datetime] = None,
                   business: Optional[Dict[str, Any]] = None,
                   run: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Plan one business's week: up to five drafts, each with a flyer on the way.

    trigger: 'scheduled' (the fan-out) or 'manual' (the owner's queued
    request, whose claimed run is passed as `run`). A scheduled call claims
    the week itself (kind 'week'); a week already planned answers
    {'status': 'exists'}. A replan saves its new drafts before it retires
    the old ones, and writes nothing over a week with an approved, sent or
    still-designing post. Never approves or sends anything."""
    if trigger not in store.RUN_TRIGGERS:
        raise ValueError('Unknown trigger.')
    bid = str(UUID(str(business_id)))
    at = now or _now()
    manual = trigger == 'manual'
    row = business if business and all(k in business for k in FULL_COLUMNS.split(',')) else None
    run_id = UUID(str(run['id'])) if run else None
    prior = run.get('design') if run and isinstance(run.get('design'), dict) else {}

    async def stop(status: str, error: str, out: Dict[str, Any]) -> Dict[str, Any]:
        if run_id:
            ended = await _close(bid, run_id, at, status=status, error=error, manual=manual, prior=prior,
                                 kept_note=WEEK_KEPT)
            return {**out, 'status': ended if ended == 'kept' else out['status']}
        return out

    try:
        row = row or await asyncio.to_thread(read_business, bid)
        tz = await asyncio.to_thread(marketing_profile.time_zone, row)
        desk = await store.get_desk(bid)
        reason = await asyncio.to_thread(eligibility, row, scheduled=not manual, kind=WEEK_KIND)
    except LookupError:
        return await stop('skipped', 'This business no longer exists.',
                          {'status': 'not_eligible', 'reason': 'Business not found.'})
    except (Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        return await stop('failed', READ_FAILED, {'status': 'unavailable', 'reason': READ_FAILED})

    if reason is None and not manual and not (desk or {}).get('plan_enabled'):
        reason = NOT_SWITCHED_ON
    if reason:
        return await stop('skipped', reason, {'status': 'not_eligible', 'reason': reason})

    week_of = date.fromisoformat(str(run['week_of'])[:10]) if run else target_week(at, tz)
    try:
        times = await week_times(bid, tz, (desk or {}).get('post_hour', 11), week_of, at)
    except Unavailable:
        return await stop('failed', READ_FAILED, {'status': 'unavailable', 'reason': READ_FAILED})
    if not times:
        return await stop('skipped', NO_TIME, {'status': 'no_time', 'reason': NO_TIME, 'week_of': week_of.isoformat()})

    if run is None:
        try:
            if not await store.claim_run(bid, week_of, kind=WEEK_KIND, source=trigger):
                return {'status': 'exists', 'week_of': week_of.isoformat()}
        except store.StoreError:
            return {'status': 'unavailable', 'reason': READ_FAILED}
        run_id = store.run_id_for(bid, week_of)
        try:
            run = await store.get_run(bid, run_id)
        except store.StoreError:
            run = None
        if not run:
            await _finish(bid, run_id, at, status='failed', error=READ_FAILED)
            return {'status': 'failed', 'reason': READ_FAILED, 'run_id': str(run_id)}
    attempt = int(run.get('attempts') or 1)
    replans = int(((run.get('design') if isinstance(run.get('design'), dict) else None) or {}).get('replans') or 0)
    request = {k: prior[k] for k in QUEUE_KEYS[:3] if k in prior} if manual else {}
    return await _plan_week(row, desk, tz, run_id, week_of, times, attempt, at, request, manual=manual,
                            prior=prior, replans=replans)


async def _plan_week(row: Dict[str, Any], desk: Optional[Dict[str, Any]], tz: ZoneInfo, run_id: UUID,
                     week_of: date, times: List[datetime], attempt: int, at: datetime, request: Dict[str, Any], *,
                     manual: bool, prior: Dict[str, Any], replans: int) -> Dict[str, Any]:
    """The claimed week, written and recorded. Every way out marks the run."""
    import business_marketing_outcomes as outcomes
    import creative_director
    import llm_call
    import spend_guard
    bid = str(row['id'])
    record: Dict[str, Any] = {}
    design: Dict[str, Any] = {**request, 'replans': replans}
    standing: Optional[List[Dict[str, Any]]] = None
    own = {week_post_id(run_id, attempt, n): n for n in range(1, WEEK_SLOTS + 1)}
    own_clips = {clips.post_id(run_id, attempt, n) for n in range(1, clips.PER_WEEK + 1)}     # B12

    async def close(status: str, error: str) -> Dict[str, Any]:
        ended = await _close(bid, run_id, at, status=status, error=error, manual=manual, prior=prior,
                             design=design, record=record, standing=standing, kept_note=WEEK_KEPT)
        return {'status': ended, 'reason': error, 'run_id': str(run_id)}

    try:
        if not llm_call.api_key():
            raise Skip(NO_WRITER)
        if await asyncio.to_thread(spend_guard.over_budget, bid):
            raise Skip(spend_guard.block_message())
        every = await store.rows(f'/marketing_posts?run_id=eq.{run_id}&business_id=eq.{bid}'
                                 '&select=id,status,revision,run_at,play_id,design_status,source&limit=60')
        standing = [p for p in every if p.get('status') != 'cancelled']
        mine = [p for p in standing if str(p['id']) in own or str(p['id']) in own_clips]
        if mine or (standing and not manual):
            # This attempt (or, for the scheduler, an earlier one) saved its
            # drafts and stopped before recording them. Their flyers are
            # left to the design tick (a late one goes without); the owner
            # is told once they have settled.
            ids = [str(p['id']) for p in standing]
            kept_design = {**(prior if manual else {}), 'replans': replans, 'tell': 'pending'}
            if mine and manual:
                left = await _retire(bid, run_id, [p for p in standing if p.get('status') == 'draft'],
                                     set(own) | own_clips)
                ids = [str(p['id']) for p in mine] + left
                kept_design['made'] = [str(p['id']) for p in mine]
            await _finish(bid, run_id, at, status='succeeded', post_ids=ids, error=None, design=kept_design)
            return {'status': 'succeeded', 'run_id': str(run_id), 'post_ids': ids, 'week_of': week_of.isoformat(),
                    'resumed': True, 'designing': 0}
        if manual and any(p.get('status') != 'draft' for p in standing):
            raise Skip(WEEK_APPROVED_MEANWHILE)
        if manual and any(p.get('design_status') == 'designing' for p in standing):
            raise Skip(STILL_DESIGNING)
        previous = [p for p in standing if p.get('status') == 'draft']
        try:
            accounts = await bm.connected(bid)
        except HTTPException:
            raise Unavailable('accounts') from None
        if not accounts:
            raise Skip(NO_ACCOUNTS)
        signals = await marketing_signals.read_signals(bid, now=at, business=row, tz=tz)
        try:
            scores = await outcomes.play_scores(bid, now=at)
        except store.StoreError:
            log.warning('marketing planner: the plays\' own results for %s could not be read', bid[:8])
            scores = {}
        signals['play_scores'] = scores
        profile = await marketing_profile.read_profile(bid, business=row)
        raw_facts = await asyncio.to_thread(creative_director.business_facts, bid)
        facts = engine.verified_facts(raw_facts, new_offerings=signals.get('new_offerings'),
                                      news=signals.get('fresh_news'))
        diagnosis = engine.diagnose(signals)
        plan = engine.pick_plays(diagnosis, len(times), signals, profile, facts)
        if not plan['slots']:
            raise Skip(NOTHING)
        slots = plan['slots']
        when = {s['slot']: times[i] for i, s in enumerate(slots)}
        record = {'signals': {**marketing_signals.summary(signals), 'play_scores': scores}, 'diagnosis': diagnosis,
                  'plays': plan['plays'], 'slots': [_record_slot(s, when[s['slot']]) for s in slots]}

        # B12: Solutionist's own clips, folded into the same week (never
        # Professional or Boss). A read that fails picks none: the week is B9's.
        picks: List[Dict[str, Any]] = []
        if clips.takes_clips(row):
            try:
                picks, design['clips'] = await clips.plan_clips(
                    bid, run_id=run_id, week_of=week_of, tz=tz, desk=desk, at=at, plan_times=list(when.values()),
                    previous=previous, first_slot=len(slots) + 1)
            except Exception:
                log.warning('marketing planner: the clips for %s could not be picked', bid[:8], exc_info=True)
                picks, design['clips'] = [], {'state': 'error', 'picked': [], 'skipped': []}
        clip_slots = [clips.caption_slot(p['slot'], p['clip']) for p in picks]

        written = await write_week_captions(bid, slots + clip_slots, facts, profile)
        record['dropped'] = [d for s in slots + clip_slots for d in written[s['slot']][2]]
        good = [s for s in slots if written[s['slot']][0]]
        if not good and not any(written[c['slot']][0] for c in clip_slots):
            return await close('failed', WEEK_CAPTIONS_BROKE)

        try:
            chosen = bm.pick_targets(accounts, desk, None)
            site = await asyncio.to_thread(bm._site, bid)
            fallback = await asyncio.to_thread(bm.default_landing, bid, row, site, desk)
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise Unavailable('site') from None
            raise Skip(str(exc.detail)) from None
        # The week's five included flyers are shared by its replans.
        budget = max(0, FLYERS_PER_WEEK - await asyncio.to_thread(flyers_made, bid, run_id, every))
        posts: List[Dict[str, Any]] = []
        wanted: Dict[str, Tuple[Dict[str, Any], Dict[str, str]]] = {}
        left_out: List[Dict[str, Any]] = []
        for s in good:
            caption, copy, _ = written[s['slot']]
            pid = week_post_id(run_id, attempt, s['slot'])
            wants = bool(copy) and budget > 0
            kind = 'image' if wants else None
            # No plan gates a network (Kevin, 2026-10-07): TikTok and YouTube
            # take only videos; Instagram waits for the flyer, or is left out.
            kept, gone = bm.fit(chosen, kind)
            if not kept:
                record['dropped'].append({'slot': s['slot'], 'reason': bm.dropped_note(gone) or 'no account fits'})
                continue
            landing = s.get('landing_url') if links.on_site(s.get('landing_url'), site) else fallback
            try:
                link = bm.link_fields(pid, caption, landing, site)
                targets = bm.ready_to_post(chosen, kind, caption, link['publish_text'])
                run_at, expires_at = bm.schedule(when[s['slot']])
                post = bm.new_post(bid, pid, caption=caption, media={}, targets=targets, run_at=run_at,
                                   expires_at=expires_at, landing=landing, source='plan', site=site)
            except HTTPException as exc:
                record['dropped'].append({'slot': s['slot'], 'reason': str(exc.detail)[:200]})
                continue
            # Every row of the one insert carries the same columns (PostgREST
            # refuses a bulk insert whose objects' keys differ).
            post.update(run_id=str(run_id), play_id=s['play_id'], error=None)
            if wants:
                budget -= 1
                post['design_status'] = 'designing'
                wanted[pid] = (s, copy)
            else:
                # The note names what the missing flyer costs (Instagram); the
                # video-only networks are left out of every picture post anyway.
                post.update(design_status='failed', error=no_flyer_note(
                    'words' if not copy else 'week', [d for d in gone if d['why'] == 'needs_picture']))
            left_out += gone
            posts.append(post)
        # B12: each clip whose caption passed is a draft beside them (source
        # 'clip', no flyer): every desk account that takes a video, TikTok and
        # YouTube included; its tracked link; the clip's fingerprint and covers
        # in its media, so in its content hash.
        clip_posts = _clip_posts(bid, run_id, attempt, picks, written, chosen, fallback, site, record, design)
        posts += clip_posts
        if not posts:
            raise Skip(f"{bm.dropped_note(left_out) or 'None of your accounts can take these posts.'} "
                       'Nothing was saved.')
        if left_out:
            once = {(d['platform'], d.get('username'), d['why']): d for d in left_out}
            design['left_out'] = bm._public_dropped(list(once.values()))
        # All of the week at once: one write, every draft designing until its flyer lands.
        try:
            if desk is None:
                await bm.ensure_desk(bid)      # the sender claims nothing for a business with no desk row
            await store.request('POST', '/marketing_posts', posts)
        except store.StoreConflict:
            saved = {str(p['id']) for p in await store.rows(
                f'/marketing_posts?run_id=eq.{run_id}&business_id=eq.{bid}&select=id&limit=60')}
            if not {str(p['id']) for p in posts} <= saved:
                return await close('failed', WEEK_SAVE_FAILED)
        except (store.StoreUnavailable, HTTPException):
            return await close('failed', WEEK_SAVE_FAILED)
        new_ids = [str(p['id']) for p in posts]
        # The new week exists; only now does the earlier plan go.
        left = await _retire(bid, run_id, previous, new_ids)
        flyers: Dict[str, Dict[str, Any]] = {}
        for post in posts:
            pid = str(post['id'])
            if post.get('source') == 'clip':
                continue                        # a clip is its own picture: no flyer
            if pid not in wanted:
                flyers[pid] = {'state': 'failed', 'why': 'words' if not written[own[pid]][1] else 'week'}
                continue
            s, copy = wanted[pid]
            outcome, why = await start_flyer(row, post, s, copy, profile, run_id)
            if outcome in ('started', 'unknown'):
                # 'unknown': it may exist; the design tick attaches it, or
                # gives up on it at 20 minutes, never a guess now.
                flyers[pid] = {'state': 'designing', 'image_id': str(flyer_request_id(run_id, pid)),
                               **({'why': outcome, 'detail': why} if outcome == 'unknown' else {})}
                continue
            # The daily design limit (429) or a design that could not start:
            # this post goes as words only now, rather than wait.
            try:
                settled = await _settle_post(bid, post, without_flyer(post, 'limit' if outcome == 'limit' else 'start'))
            except store.StoreError:
                settled = None          # still designing: the design tick gives up on it within 20 minutes
            flyers[pid] = {'state': 'failed' if settled else 'designing', 'why': outcome, 'detail': why}
        design.update(made=new_ids, flyers=flyers, tell='pending')
        if previous:
            design['replaced'] = [str(p['id']) for p in previous if str(p['id']) not in left]
            if manual and any(p.get('source') == 'plan' for p in previous):
                design['replans'] = replans + 1          # a week planned again (not a suggestion taken over)
        await _finish(bid, run_id, at, status='succeeded', post_ids=new_ids + left, error=None, design=design,
                      **record)
        return {'status': 'succeeded', 'run_id': str(run_id), 'post_ids': new_ids, 'week_of': week_of.isoformat(),
                'designing': sum(1 for f in flyers.values() if f.get('state') == 'designing')}
    except Skip as reason:
        return await close('skipped', str(reason))
    except (Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        log.warning('marketing planner: a read for the week of %s failed', bid[:8], exc_info=True)
        return await close('failed', READ_FAILED)
    except Exception:
        log.warning('marketing planner: the week for %s could not be finished', bid[:8], exc_info=True)
        return await close('failed', WEEK_FAILED)


def _clip_posts(business_id: str, run_id: UUID, attempt: int, picks: List[Dict[str, Any]],
                written: Dict[int, Tuple[Optional[str], Any, List[Dict[str, Any]]]], chosen: List[Dict[str, Any]],
                landing: Optional[str], site: Optional[Dict[str, Any]], record: Dict[str, Any],
                design: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The week's clip drafts (B12), with the same columns as its flyer
    posts (one insert). A clip whose caption broke a rule, or that no account
    can take, is left out (it stays eligible next week); the run records
    which clip went where, with which cover on each network."""
    out: List[Dict[str, Any]] = []
    noted = (design.get('clips') or {}).get('picked') or []
    by_clip = {str(n.get('clip_id')): n for n in noted}
    kept, gone = clips.video_targets(chosen)
    if gone and picks and isinstance(design.get('clips'), dict):
        design['clips']['left_out'] = bm._public_dropped(gone)
    for p in picks:
        caption = written.get(p['slot'], (None, None, []))[0]
        entry = by_clip.get(str(p['clip']['id']), {})
        if not caption:
            entry['saved'] = False
            continue
        pid = clips.post_id(run_id, attempt, p['n'])
        try:
            if not kept:
                raise HTTPException(422, 'None of your accounts takes a video.')
            link = bm.link_fields(pid, caption, landing, site)
            targets = bm.ready_to_post(kept, 'video', caption, link['publish_text'])
            run_at, expires_at = bm.schedule(p['run_at'])
            post = bm.new_post(business_id, pid, caption=caption, media=p['media'], targets=targets, run_at=run_at,
                               expires_at=expires_at, landing=landing, source='clip', site=site)
        except HTTPException as exc:
            record['dropped'].append({'slot': p['slot'], 'clip_id': str(p['clip']['id']),
                                      'reason': str(exc.detail)[:200]})
            entry['saved'] = False
            continue
        post.update(run_id=str(run_id), play_id=clips.PLAY_ID, error=None)
        entry.update(saved=True, post_id=pid, covers=clips.covers_by_network(targets, p['media'].get('covers') or {}))
        out.append(post)
    return out


# ── the week's flyers land (B9) ───────────────────────────────────────

POST_DESIGN_COLUMNS = ('id,business_id,run_id,source,status,revision,caption,publish_text,landing_url,media,'
                       'targets,run_at,expires_at,design_status,created_at')
WEEK_RUN_COLUMNS = 'id,business_id,week_of,kind,status,attempts,design,created_at'


def week_dedup_key(run_id: Any, attempt: int) -> str:
    return f'marketing_week:{UUID(str(run_id))}:{int(attempt)}'


def week_words(drafts: int, without: int, which: Optional[str], clip_posts: int = 0) -> Dict[str, str]:
    """'Chief planned next week: 5 posts wait for your OK', and what comes
    with them. clip_posts: how many of them are the business's own video
    clips (B12), which carry their covers instead of a flyer."""
    many = drafts != 1
    title = (f"Chief planned {which or 'next week'}: {drafts} post{'s' if many else ''} "
             f"wait{'' if many else 's'} for your OK")
    if clip_posts and clip_posts >= drafts:
        lead = ('They are your own video clips, with their covers.' if many
                else 'It is your own video clip, with its cover.')
    elif clip_posts:
        flyered = max(0, drafts - clip_posts - without)
        parts = []
        if flyered:
            parts.append(f"{flyered} {'has' if flyered == 1 else 'have'} a flyer")
        if without:
            parts.append(f"{without} {'goes' if without == 1 else 'go'} as words only")
        parts.append(f'{clip_posts} is your own video clip, with its cover' if clip_posts == 1
                     else f'{clip_posts} are your own video clips, with their covers')
        lead = words._cap(words._join(parts)) + '.'
    elif not without:
        lead = 'Each has its flyer.' if many else 'It has its flyer.'
    elif without >= drafts:
        lead = 'They go as words only this time.' if many else 'It goes as words only this time.'
    else:
        flyered = drafts - without
        lead = (f"{flyered} {'have' if flyered != 1 else 'has'} a flyer; {without} "
                f"{'go' if without != 1 else 'goes'} as words only.")
    return {'title': title, 'body': f"{lead} Nothing posts until you approve {'them' if many else 'it'}."}


def _week_today_item(business_id: str, run_id: str, said: Dict[str, str], key: str) -> bool:
    saved = sb_clients.sb_post_as_service('/chief_notifications', {
        'business_id': business_id, 'type': 'reminder', 'priority': 'normal',
        'title': said['title'][:120], 'body': said['body'][:300], 'suggested_action': 'Review the week',
        'action_payload': {'type': 'navigate', 'tab': 'grow', 'sub': 'marketing', 'run_id': run_id, 'dedup_key': key},
    })
    return bool(saved)


def _week_push(owner_id: str, run_id: str, said: Dict[str, str]) -> int:
    try:
        import push_notifications
        return push_notifications.send_to_user(owner_id, title=said['title'][:80], body=said['body'][:160],
                                               nav=reading.NAV, tag=f'marketing-week-{run_id}')
    except Exception:
        log.warning('marketing planner: the week push for %s failed', run_id[:8], exc_info=True)
        return 0


async def _mark_told(run: Dict[str, Any], at: datetime) -> None:
    design = run.get('design') if isinstance(run.get('design'), dict) else {}
    try:
        await store.request(
            'PATCH', f"/marketing_runs?id=eq.{UUID(str(run['id']))}&business_id=eq.{UUID(str(run['business_id']))}"
                     f"&attempts=eq.{int(run.get('attempts') or 1)}&design->>tell=eq.pending",
            {'design': {**design, 'tell': 'done', 'told_at': words._z(at)}})
    except store.StoreError:
        log.warning('marketing planner: the week %s could not be marked told', str(run['id'])[:8])


async def tell_week(run: Dict[str, Any], at: datetime) -> str:
    """Tell the owner about a planned week ONCE, and only when every post of
    it has settled (none still designing): one Today item and one push,
    keyed by the run and its attempt in chief_notifications.action_payload.
    dedup_key. If what was said cannot be read, nothing is said."""
    bid, rid = str(UUID(str(run['business_id']))), str(UUID(str(run['id'])))
    posts = await store.rows(f'/marketing_posts?run_id=eq.{rid}&business_id=eq.{bid}&status=neq.cancelled'
                             '&select=id,status,design_status,source,approved_via&limit=60')
    if any(p.get('design_status') == 'designing' for p in posts):
        return 'waiting'
    drafts = [p for p in posts if p.get('status') == 'draft']
    key = week_dedup_key(rid, int(run.get('attempts') or 1))
    told = await asyncio.to_thread(_already_told, bid, key)
    if told is None:
        return 'unreadable'
    by_standing = [p for p in posts if p.get('approved_via') == 'standing' and p.get('status') != 'draft']
    if not told and (drafts or by_standing):
        business = await asyncio.to_thread(read_business, bid)
        tz = await asyncio.to_thread(marketing_profile.time_zone, business)
        which = reading.relation(run.get('week_of'), at, tz)
        if drafts:
            # B13: the kinds the owner's standing OK covers are approved now
            # that the week has settled, through marketing_approve (approved_via
            # 'standing'); approve_run checks the grant, the plan and autonomy
            # itself, so nothing is approved for any other level.
            import business_marketing_standing as standing
            approved = set(await standing.approve_run(business, rid, at, tz=tz))
            for p in drafts:
                if str(p['id']) in approved:
                    p.update(status='approved', approved_via='standing')
                    by_standing.append(p)
            drafts = [p for p in drafts if str(p['id']) not in approved]
        if by_standing:
            import business_marketing_standing as standing
            said = standing.week_words(len(by_standing), len(drafts), which)
        else:
            # A clip (B12) carries its own covers: never counted as words only.
            clip_posts = sum(1 for p in drafts if p.get('source') == 'clip')
            without = sum(1 for p in drafts if p.get('source') != 'clip' and p.get('design_status') != 'ready')
            said = week_words(len(drafts), without, which, clip_posts)
        if not await asyncio.to_thread(_week_today_item, bid, rid, said, key):
            return 'not_told'
        if business.get('owner_id'):
            await asyncio.to_thread(_week_push, str(business['owner_id']), rid, said)
        await _mark_told(run, at)
        return 'told'
    await _mark_told(run, at)
    return 'nothing_to_tell'


async def settle_designs(posts: List[Dict[str, Any]], at: datetime) -> Counter:
    """Attach each finished flyer to its post, and give up on a flyer that
    failed or is not ready 20 minutes after it started (or after its post
    was saved, when it never started): that post goes as words only."""
    tally: Counter = Counter()
    by_business: Dict[str, List[Dict[str, Any]]] = {}
    for p in posts:
        by_business.setdefault(str(p['business_id']), []).append(p)
    for bid, items in by_business.items():
        try:
            found = await asyncio.to_thread(flyer_rows, bid, [str(flyer_request_id(p['run_id'], p['id']))
                                                              for p in items if p.get('run_id')])
        except Unavailable:
            tally['unreadable'] += len(items)
            continue
        for p in items:
            try:
                if not p.get('run_id') or p.get('status') != 'draft':
                    # Not a draft any more (it cannot be approved while designing,
                    # so it was skipped): it stops counting as a design in progress.
                    await store.request('PATCH', f"/marketing_posts?id=eq.{UUID(str(p['id']))}&business_id=eq.{bid}"
                                                 '&design_status=eq.designing&status=neq.draft',
                                        {'design_status': 'failed'})
                    tally['not_a_draft'] += 1
                    continue
                image = found.get(str(flyer_request_id(p['run_id'], p['id'])))
                started = words._stamp((image or {}).get('created_at') or p.get('created_at'))
                if image and image.get('status') == 'ready' and image.get('storage_path'):
                    outcome, patch = 'attached', with_flyer(p, image)
                elif image and image.get('status') == 'failed':
                    outcome, patch = 'failed', without_flyer(p, 'failed')
                elif started is None or at - started >= DESIGN_TIMEOUT:
                    outcome, patch = 'timed_out', without_flyer(p, 'timeout')
                else:
                    tally['waiting'] += 1
                    continue
                tally[outcome if await _settle_post(bid, p, patch) else 'moved_on'] += 1
            except Exception:
                log.warning('marketing planner: the flyer of %s could not be settled', str(p.get('id'))[:8],
                            exc_info=True)
                tally['error'] += 1
    return tally


async def marketing_design_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every 2 minutes, on the worker, on the scheduler leader: the weekly
    plans' flyers land on their posts, and each owner whose week has settled
    is told once. Does nothing unless MARKETING_DESK covers the business."""
    scope = desk_scope()
    if scope is None:
        return {'skipped': 'off'}
    at = now or _now()
    only = '' if scope == '*' else f"&business_id=in.({','.join(sorted(scope))})"
    try:
        posts = await store.rows(f'/marketing_posts?design_status=eq.designing&source=eq.plan{only}'
                                 f'&select={POST_DESIGN_COLUMNS}&order=created_at.asc&limit={DESIGN_BATCH}')
    except store.StoreError:
        return {'skipped': 'storage'}
    tally = await settle_designs([p for p in posts if desk_on_for(p.get('business_id'))], at)
    try:
        runs = await store.rows(f'/marketing_runs?kind=eq.{WEEK_KIND}&status=eq.succeeded&design->>tell=eq.pending{only}'
                                f'&select={WEEK_RUN_COLUMNS}&order=created_at.asc&limit={TELL_BATCH}')
    except store.StoreError:
        return {**tally, 'skipped': 'storage'}
    for run in runs:
        if not desk_on_for(run.get('business_id')):
            continue
        try:
            tally[f"week_{await tell_week(run, at)}"] += 1
        except Exception:
            log.warning('marketing planner: the owner of week %s could not be told', str(run.get('id'))[:8],
                        exc_info=True)
            tally['week_error'] += 1
    # B13: posts approved on a standing OK that no longer covers them (the
    # plan lapsed, client-facing autonomy or the permission turned off,
    # automations paused) go back to waiting for the owner at once.
    try:
        import business_marketing_standing as standing
        tally.update(await standing.lapse_sweep(only=only, on_for=desk_on_for))
    except Exception:
        log.warning('marketing planner: the standing sweep failed', exc_info=True)
    return dict(tally)


# ── the open-chairs week (B11) ────────────────────────────────────────

def openings_post_id(run_id: Any, attempt: int, slot: int) -> str:
    """One post per window per attempt of the week's run: a retry inside an
    attempt is the same post, and a replan (a new attempt) gets new ones."""
    return str(uuid5(UUID(str(run_id)), f'{int(attempt)}:openings:{int(slot)}'))


def openings_dedup_key(run_id: Any, attempt: int) -> str:
    return f'marketing_openings:{UUID(str(run_id))}:{int(attempt)}'


def chair_targets(chosen: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The desk's accounts an open-chairs post goes to: Instagram first,
    Facebook too (D5); every other network is left out."""
    keep = [t for t in chosen if t.get('platform') in CHAIR_PLATFORMS]
    return sorted(keep, key=lambda t: CHAIR_PLATFORMS.index(t['platform']))


def openings_caption_request(slots: List[Dict[str, Any]], facts: Dict[str, Any],
                             profile: Dict[str, Any]) -> Dict[str, Any]:
    return {'audience': profile.get('audience'), 'voice': profile.get('voice'), 'facts': facts,
            'slots': [{'slot': s['slot'], 'play': openings.PLAY_LABEL, 'play_brief': openings.PLAY_BRIEF,
                       'subject': f"{s['words']['day']} {s['words']['time']}", 'offering': None,
                       'opening': s['words']} for s in slots]}


async def write_openings_captions(business_id: str, slots: List[Dict[str, Any]], facts: Dict[str, Any],
                                  profile: Dict[str, Any]) -> Tuple[Dict[int, str], List[Dict[str, Any]]]:
    """ONE small model call for the week's captions, metered to the business
    (units=0). Each is held to the business caption checks plus the open
    chairs' own (business_marketing_openings.check_caption: no seat count,
    its own day and no other). A caption that is missing or breaks a rule,
    or a call that does not answer, gets the plain caption, which always
    holds: an open chair is never lost to a wording slip."""
    import llm_call
    import model_ladder
    from chief_models import model_for
    items: List[Any] = []
    dropped: List[Dict[str, Any]] = []
    answered = False
    try:
        model = model_for('draft')
        payload = {'model': model, 'max_tokens': OPENINGS_MAX_TOKENS, 'system': profile['system_prompt'],
                   'messages': [{'role': 'user', 'content': json.dumps(
                       openings_caption_request(slots, facts, profile), default=str)}],
                   **model_ladder.effort_kwargs(model, EFFORT)}
        async with httpx.AsyncClient() as client:
            response = await llm_call.apost(client, payload, timeout=CALL_TIMEOUT, task=OPENINGS_TASK,
                                            business_id=business_id, units=0)
        response.raise_for_status()
        parsed = _parse(llm_call.text_of(response.json()))
        items = parsed.get('captions') if isinstance(parsed.get('captions'), list) else []
        answered = True
    except Exception:
        log.warning('marketing planner: the open-chairs captions for %s were not written', business_id[:8],
                    exc_info=True)
        dropped.append({'slot': None, 'reason': 'the writer did not answer', 'plain': True})
    out: Dict[int, str] = {}
    for s in slots:
        item = next((i for i in items if isinstance(i, dict) and i.get('slot') == s['slot']), None)
        text = item.get('text') if item else None
        problem = openings.check_caption(text, facts, profile, s['words']) if answered else 'not written'
        if problem:
            if answered:
                dropped.append({'slot': s['slot'], 'reason': problem, 'plain': True})
            out[s['slot']] = openings.plain_caption(s['words'])
        else:
            out[s['slot']] = text.strip()
    return out, dropped


async def make_opening_flyer(business: Dict[str, Any], run_id: UUID, attempt: int, slot: int,
                             copy: Dict[str, str], photo_id: Optional[str],
                             profile: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """The free composer picture for one open-chairs post (cost_usd 0): the
    owner's work photo with the words laid over it, or, with no photo (or
    one that cannot be placed), the business's branded flyer. Made under
    image_studio.build_actor bound to this business and its owner (read as
    the service role), reset in a finally. Never an image-model render:
    nothing here can redraw a real haircut."""
    import chief_flyer_composer as composer
    import image_studio as images
    import marketing_design
    made: Dict[str, Any] = {'flyer': None, 'cost_usd': 0, 'made_by': 'composer', 'picture': None,
                            'photo': photo_id, 'failed': []}
    bid, owner = str(business['id']), str(business.get('owner_id') or '')
    if not owner:
        made['failed'].append({'what': 'picture', 'reason': 'no owner on record'})
        return None, made
    palette = marketing_design.brand_palette(marketing_design.brand_colors(business))
    footer = profile.get('flyer_footer') or marketing_profile.flyer_footer(business.get('name'), None)
    token = images.build_actor.set({'business_id': bid, 'user_id': owner})
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            for picture in (('photo', 'flyer') if photo_id else ('flyer',)):
                last = None
                for step, scale in enumerate(FLYER_SCALES):
                    try:
                        if picture == 'photo':
                            layout = openings.photo_layout(photo_id, copy, scale=scale, footer=footer, palette=palette)
                        else:
                            layout = marketing_design.flyer_layout(openings.PLAY_ID, copy, scale=scale,
                                                                   eyebrow=openings.EYEBROW, footer=footer,
                                                                   palette=palette)
                        request_id = uuid5(run_id, f'openings-{picture}:{attempt}:{slot}:{photo_id or "-"}:{step}')
                        result = await composer.compose(client, {'id': bid}, {'layout': layout}, request_id)
                        art = str(result['image']['id'])
                        made.update(flyer=art, picture=picture, palette=palette, footer=footer)
                        return art, made
                    except HTTPException as exc:
                        last = exc
                        if exc.status_code != 422:
                            break
                made['failed'].append({'what': picture, 'reason': str(getattr(last, 'detail', 'render failed'))[:200]})
    except Exception as exc:
        log.warning('marketing planner: an open-chairs picture for %s failed', bid[:8], exc_info=True)
        made['failed'].append({'what': 'picture', 'reason': str(getattr(exc, 'detail', 'render failed'))[:200]})
    finally:
        images.build_actor.reset(token)
    return None, made


def openings_words(drafts: int, photos: Optional[int], flyers: Optional[int], which: Optional[str]) -> Dict[str, str]:
    """'Chief planned next week's open chairs: 3 posts wait for your OK', and what they show."""
    many = drafts != 1
    title = (f"Chief planned {which or 'next week'}'s open chairs: {drafts} post{'s' if many else ''} "
             f"wait{'' if many else 's'} for your OK")
    words_only = drafts - (photos or 0) - (flyers or 0)
    if photos is None:
        lead = ''
    elif photos == drafts:
        lead = 'Each shows one of your work photos. ' if many else 'It shows one of your work photos. '
    elif not photos and flyers == drafts:
        lead = ('They use your brand flyer; add work photos on the desk to show your own work. ' if many else
                'It uses your brand flyer; add work photos on the desk to show your own work. ')
    else:
        parts = []
        if photos:
            parts.append(f"{photos} show{'s' if photos == 1 else ''} your work photos")
        if flyers:
            parts.append(f"{flyers} use{'s' if flyers == 1 else ''} your brand flyer")
        if words_only:
            parts.append(f"{words_only} go{'es' if words_only == 1 else ''} as words only")
        lead = '; '.join(parts).capitalize() + '. '
    return {'title': title,
            'body': (f"{lead}Nothing posts until you approve {'them' if many else 'it'}, and a post comes down "
                     'by itself if its time books first.')}


async def tell_openings(business: Dict[str, Any], run_id: Any, attempt: int, tz: ZoneInfo, week_of: Any,
                        at: datetime, *, photos: Optional[int] = None, flyers: Optional[int] = None) -> str:
    """Tell the owner about the open-chairs week ONCE: one Today item and one
    push, keyed by the run and its attempt in chief_notifications.
    action_payload.dedup_key. If what was said cannot be read, nothing is said."""
    bid, rid = str(UUID(str(business['id']))), str(UUID(str(run_id)))
    try:
        posts = await store.rows(f'/marketing_posts?run_id=eq.{rid}&business_id=eq.{bid}&status=eq.draft'
                                 '&select=id&limit=10')
        if not posts:
            return 'nothing_to_tell'
        key = openings_dedup_key(rid, attempt)
        told = await asyncio.to_thread(_already_told, bid, key)
        if told is None:
            return 'unreadable'
        if told:
            return 'told_before'
        said = openings_words(len(posts), photos, flyers, reading.relation(week_of, at, tz))
        if not await asyncio.to_thread(_week_today_item, bid, rid, said, key):
            return 'not_told'
        if business.get('owner_id'):
            await asyncio.to_thread(_week_push, str(business['owner_id']), rid, said)
        return 'told'
    except Exception:
        log.warning('marketing planner: could not tell the owner of %s about open chairs', bid[:8], exc_info=True)
        return 'not_told'


async def _taken_times(business_id: str, week_of: date, tz: ZoneInfo) -> set:
    """The times already taken by this business's posts around that week
    (from the Sunday before: a Monday window posts the day before)."""
    start = datetime.combine(week_of - timedelta(days=1), time(0), tz)
    end = datetime.combine(week_of + timedelta(days=7), time(0), tz)
    try:
        rows = await store.rows(
            f'/marketing_posts?business_id=eq.{business_id}&select=run_at&status=not.in.(cancelled,pulled)'
            f'&run_at=gte.{reading.query_time(start)}&run_at=lt.{reading.query_time(end)}&limit={bm.TAKEN_LIMIT}')
    except store.StoreError:
        raise Unavailable('the calendar') from None
    return {bm._aware(r['run_at']).timestamp() for r in rows}


def _openings_record(calendar: Dict[str, Any], picked: List[Dict[str, Any]], slots: List[Dict[str, Any]],
                     tz: ZoneInfo, which: Optional[str]) -> Dict[str, Any]:
    """What the run records: the calendar it read, the reading Chief gives
    the desk, the play and the windows. Counts here are for the owner's desk,
    never for a caption."""
    days = sorted({w['day'] for w in calendar['windows']})
    names = [openings.WEEKDAYS[date.fromisoformat(d).weekday()] for d in days]
    offering = calendar['offering']
    evidence = (f"{(which or 'That week').capitalize()} still has open times on {words._join(names)}. Chief picked "
                f"the {_plural_word(len(picked), 'longest open stretch', 'longest open stretches')}, slow days "
                'first; each post comes down by itself if its time books first.')
    return {
        'signals': {'calendar': {'offering': offering.get('name'), 'offering_id': str(offering.get('id')),
                                 'offering_from': calendar['offering_from'], 'history': calendar['history'],
                                 'open_slots': calendar['open_slots'], 'windows': len(calendar['windows']),
                                 'open_days': len(days), 'weekday_bookings': {
                                     openings.WEEKDAYS[k]: v for k, v in sorted(calendar['counts'].items())}}},
        'diagnosis': {'primary_problem': 'fill_the_calendar', 'rule': 'open_chairs', 'urgency': 'medium',
                      'headline': 'Open chairs to fill', 'evidence': evidence,
                      'numbers': {'open_days': len(days), 'windows': len(calendar['windows'])}},
        'plays': [{'play_id': openings.PLAY_ID, 'label': openings.PLAY_LABEL, 'posts': len(slots),
                   'reason': 'Each post names one open stretch of the calendar and links to the booking page.'}],
        'slots': [{'slot': s['slot'], 'play_id': openings.PLAY_ID, 'subject_key': None,
                   'subject': f"{s['words']['day']} {s['words']['time']}", 'offering': offering.get('name'),
                   'landing_url': None, 'run_at': s['window']['run_at'].isoformat(),
                   'score': s['window'].get('score'), 'opening': s['opening']} for s in slots],
    }


def _plural_word(n: int, one: str, many: str) -> str:
    return f'{words._word(n)} {one if n == 1 else many}' if n else f'no {many}'


async def run_openings(business_id: Any, *, trigger: str, now: Optional[datetime] = None,
                       business: Optional[Dict[str, Any]] = None,
                       run: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Plan one Boss business's open-chairs week: up to three drafts.

    trigger: 'scheduled' (the fan-out) or 'manual' (the owner's queued
    request, whose claimed run is passed as `run`). A scheduled call claims
    the week itself (kind 'openings'); a week already planned answers
    {'status': 'exists'}. A replan saves its new drafts before it retires
    the old ones, and writes nothing over a week with an approved or sent
    post. Never approves or sends anything."""
    if trigger not in store.RUN_TRIGGERS:
        raise ValueError('Unknown trigger.')
    bid = str(UUID(str(business_id)))
    at = now or _now()
    manual = trigger == 'manual'
    row = business if business and all(k in business for k in FULL_COLUMNS.split(',')) else None
    run_id = UUID(str(run['id'])) if run else None
    prior = run.get('design') if run and isinstance(run.get('design'), dict) else {}

    async def stop(status: str, error: str, out: Dict[str, Any]) -> Dict[str, Any]:
        if run_id:
            ended = await _close(bid, run_id, at, status=status, error=error, manual=manual, prior=prior,
                                 kept_note=OPENINGS_KEPT)
            return {**out, 'status': ended if ended == 'kept' else out['status']}
        return out

    try:
        row = row or await asyncio.to_thread(read_business, bid)
        tz = await asyncio.to_thread(marketing_profile.time_zone, row)
        desk = await store.get_desk(bid)
        reason = await asyncio.to_thread(eligibility, row, scheduled=not manual, kind=OPENINGS_KIND)
    except LookupError:
        return await stop('skipped', 'This business no longer exists.',
                          {'status': 'not_eligible', 'reason': 'Business not found.'})
    except (Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        return await stop('failed', READ_FAILED, {'status': 'unavailable', 'reason': READ_FAILED})

    if reason is None and not manual and not (desk or {}).get('plan_enabled'):
        reason = NOT_SWITCHED_ON
    if reason:
        return await stop('skipped', reason, {'status': 'not_eligible', 'reason': reason})

    week_of = date.fromisoformat(str(run['week_of'])[:10]) if run else target_week(at, tz)
    if run is None:
        try:
            if not await store.claim_run(bid, week_of, kind=OPENINGS_KIND, source=trigger):
                return {'status': 'exists', 'week_of': week_of.isoformat()}
        except store.StoreError:
            return {'status': 'unavailable', 'reason': READ_FAILED}
        run_id = store.run_id_for(bid, week_of)
        try:
            run = await store.get_run(bid, run_id)
        except store.StoreError:
            run = None
        if not run:
            await _finish(bid, run_id, at, status='failed', error=READ_FAILED)
            return {'status': 'failed', 'reason': READ_FAILED, 'run_id': str(run_id)}
    attempt = int(run.get('attempts') or 1)
    replans = int(((run.get('design') if isinstance(run.get('design'), dict) else None) or {}).get('replans') or 0)
    request = {k: prior[k] for k in QUEUE_KEYS[:3] if k in prior} if manual else {}
    return await _plan_openings(row, desk, tz, run_id, week_of, attempt, at, request, manual=manual, prior=prior,
                                replans=replans)


async def _plan_openings(row: Dict[str, Any], desk: Optional[Dict[str, Any]], tz: ZoneInfo, run_id: UUID,
                         week_of: date, attempt: int, at: datetime, request: Dict[str, Any], *, manual: bool,
                         prior: Dict[str, Any], replans: int) -> Dict[str, Any]:
    """The claimed open-chairs week, written and recorded. Every way out marks the run."""
    import creative_director
    import llm_call
    import spend_guard
    bid = str(row['id'])
    record: Dict[str, Any] = {}
    design: Dict[str, Any] = {**request, 'replans': replans}
    standing: Optional[List[Dict[str, Any]]] = None
    own = {openings_post_id(run_id, attempt, n): n for n in range(1, OPENINGS_SLOTS + 1)}
    which = reading.relation(week_of, at, tz)

    async def close(status: str, error: str) -> Dict[str, Any]:
        ended = await _close(bid, run_id, at, status=status, error=error, manual=manual, prior=prior,
                             design=design, record=record, standing=standing, kept_note=OPENINGS_KEPT)
        return {'status': ended, 'reason': error, 'run_id': str(run_id)}

    try:
        if not llm_call.api_key():
            raise Skip(NO_WRITER)
        if await asyncio.to_thread(spend_guard.over_budget, bid):
            raise Skip(spend_guard.block_message())
        every = await store.rows(f'/marketing_posts?run_id=eq.{run_id}&business_id=eq.{bid}'
                                 '&select=id,status,revision,run_at,play_id,design_status,source&limit=60')
        # A pulled post is not on the desk any more: never "the earlier plan is still there".
        standing = [p for p in every if p.get('status') not in ('cancelled', 'pulled')]
        mine = [p for p in standing if str(p['id']) in own]
        if mine or (standing and not manual):
            # This attempt (or, for the scheduler, an earlier one) saved its
            # posts and stopped before recording them or telling the owner.
            ids = [str(p['id']) for p in standing]
            kept_design = {**(prior if manual else {}), 'replans': replans}
            if mine and manual:
                left = await _retire(bid, run_id, [p for p in standing if p.get('status') == 'draft'], set(own))
                ids = [str(p['id']) for p in mine] + left
                kept_design['made'] = [str(p['id']) for p in mine]
            await _finish(bid, run_id, at, status='succeeded', post_ids=ids, error=None, design=kept_design)
            await tell_openings(row, run_id, attempt, tz, week_of, at)
            return {'status': 'succeeded', 'run_id': str(run_id), 'post_ids': ids, 'week_of': week_of.isoformat(),
                    'resumed': True}
        if manual and any(p.get('status') != 'draft' for p in standing):
            raise Skip(WEEK_APPROVED_MEANWHILE)
        previous = [p for p in standing if p.get('status') == 'draft']
        try:
            accounts = await bm.connected(bid)
        except HTTPException:
            raise Unavailable('accounts') from None
        if not accounts:
            raise Skip(NO_ACCOUNTS)
        try:
            chosen = chair_targets(bm.pick_targets(accounts, desk, None))
        except HTTPException as exc:
            raise Skip(str(exc.detail)) from None
        if not chosen:
            raise Skip(NO_CHAIR_ACCOUNTS)

        calendar = await asyncio.to_thread(openings.read_calendar, row, tz, week_of, at)
        if calendar['state'] == 'no_hours':
            raise Skip(NO_HOURS)
        if calendar['state'] == 'nothing_bookable':
            raise Skip(NOTHING_BOOKABLE)
        if not calendar['windows']:
            raise Skip(CALENDAR_FULL)
        # A replan's earlier drafts are retired once the new ones are saved: their times are free.
        taken = await _taken_times(bid, week_of, tz) - {bm._aware(p['run_at']).timestamp() for p in previous
                                                        if p.get('run_at')}
        picked = openings.pick(calendar['windows'], calendar['counts'], tz=tz,
                               post_hour=(desk or {}).get('post_hour', 11), at=at, gap=calendar['gap'], taken=taken)
        if not picked:
            raise Skip(NO_OPENING_TIME)
        offering, duration = calendar['offering'], calendar['duration_min']
        slots = [{'slot': n, 'window': w, 'words': openings.opening_facts(w, tz),
                  'opening': openings.opening_record(w, offering, duration, tz, calendar['gap'])}
                 for n, w in enumerate(picked, 1)]
        record = _openings_record(calendar, picked, slots, tz, which)

        profile = await marketing_profile.read_profile(bid, business=row)
        raw_facts = await asyncio.to_thread(creative_director.business_facts, bid)
        facts = engine.verified_facts(raw_facts)
        captions, dropped = await write_openings_captions(bid, slots, facts, profile)
        record['dropped'] = dropped
        photos = await asyncio.to_thread(openings.work_photos, bid, (desk or {}).get('work_photo_ids') or [])
        try:
            site = await asyncio.to_thread(bm._site, bid)
            booking = profile.get('booking_url')
            landing = (booking if links.on_site(booking, site)
                       else await asyncio.to_thread(bm.default_landing, bid, row, site, desk))
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise Unavailable('site') from None
            raise Skip(str(exc.detail)) from None

        posts: List[Dict[str, Any]] = []
        pictures: Dict[str, Any] = {}
        left_out: List[Dict[str, Any]] = []
        for s in slots:
            n, w = s['slot'], s['window']
            caption = captions[n]
            copy = openings.flyer_copy(s['words'])
            photo = photos[(n - 1) % len(photos)] if photos else None
            problem = openings.check_flyer(copy, facts, profile, s['words'])
            if problem:
                art, made = None, {'flyer': None, 'cost_usd': 0, 'failed': [{'what': 'picture', 'reason': problem}]}
            else:
                art, made = await make_opening_flyer(row, run_id, attempt, n, copy, photo, profile)
            pictures[str(n)] = {k: made.get(k) for k in ('flyer', 'picture', 'photo', 'cost_usd', 'failed')}
            media = {'artwork_ids': [art]} if art else {}
            kind = bm.media_kind(media)
            kept, gone = bm.fit(chosen, kind)
            if not kept:
                record['dropped'].append({'slot': n, 'reason': bm.dropped_note(gone) or 'no account fits'})
                left_out += gone
                continue
            pid = openings_post_id(run_id, attempt, n)
            try:
                link = bm.link_fields(pid, caption, landing, site)
                targets = bm.ready_to_post(chosen, kind, caption, link['publish_text'])
                run_at, expires_at = bm.schedule(w['run_at'], w['expires_at'])
                post = bm.new_post(bid, pid, caption=caption, media=media, targets=targets, run_at=run_at,
                                   expires_at=expires_at, landing=landing, source='opening', site=site)
            except HTTPException as exc:
                record['dropped'].append({'slot': n, 'reason': str(exc.detail)[:200]})
                continue
            # Every row of the one insert carries the same columns.
            post.update(run_id=str(run_id), play_id=openings.PLAY_ID, opening=s['opening'],
                        design_status='ready' if art else 'none',
                        error=None if art else no_flyer_note('failed', [d for d in gone if d['why'] == 'needs_picture']))
            left_out += gone
            posts.append(post)
        if not posts:
            raise Skip(f"{bm.dropped_note(left_out) or 'None of your accounts can take these posts.'} "
                       'Nothing was saved.')
        if left_out:
            once = {(d['platform'], d.get('username'), d['why']): d for d in left_out}
            design['left_out'] = bm._public_dropped(list(once.values()))
        design['pictures'] = pictures
        # All of the week at once, in one write.
        try:
            if desk is None:
                await bm.ensure_desk(bid)      # the sender claims nothing for a business with no desk row
            await store.request('POST', '/marketing_posts', posts)
        except store.StoreConflict:
            saved = {str(p['id']) for p in await store.rows(
                f'/marketing_posts?run_id=eq.{run_id}&business_id=eq.{bid}&select=id&limit=60')}
            if not {str(p['id']) for p in posts} <= saved:
                return await close('failed', OPENINGS_SAVE_FAILED)
        except (store.StoreUnavailable, HTTPException):
            return await close('failed', OPENINGS_SAVE_FAILED)
        new_ids = [str(p['id']) for p in posts]
        # The new week exists; only now does the earlier one go.
        left = await _retire(bid, run_id, previous, new_ids)
        design['made'] = new_ids
        if previous:
            design['replaced'] = [str(p['id']) for p in previous if str(p['id']) not in left]
            if manual and any(p.get('source') == 'opening' for p in previous):
                design['replans'] = replans + 1          # a week planned again (not a plan taken over)
        await _finish(bid, run_id, at, status='succeeded', post_ids=new_ids + left, error=None, design=design,
                      **record)
        saved_ids = set(new_ids)
        photo_posts = sum(1 for n, p in pictures.items() if p.get('picture') == 'photo'
                          and openings_post_id(run_id, attempt, int(n)) in saved_ids)
        flyer_posts = sum(1 for n, p in pictures.items() if p.get('picture') == 'flyer'
                          and openings_post_id(run_id, attempt, int(n)) in saved_ids)
        await tell_openings(row, run_id, attempt, tz, week_of, at, photos=photo_posts, flyers=flyer_posts)
        return {'status': 'succeeded', 'run_id': str(run_id), 'post_ids': new_ids, 'week_of': week_of.isoformat(),
                'photos': photo_posts}
    except Skip as reason:
        return await close('skipped', str(reason))
    except (Unavailable, openings.Unavailable, marketing_profile.ProfileUnavailable, store.StoreError):
        log.warning('marketing planner: a read for the open chairs of %s failed', bid[:8], exc_info=True)
        return await close('failed', READ_FAILED)
    except Exception:
        log.warning('marketing planner: the open chairs for %s could not be finished', bid[:8], exc_info=True)
        return await close('failed', OPENINGS_FAILED)


async def openings_watch_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every 15 minutes, on the worker, on the scheduler leader: recount the
    window of every approved or draft open-chairs post going out in the next
    48 hours and pull the ones whose chairs booked first (never needs the
    owner's yes: the safe direction); then tell each owner once per pulled
    post, the sender's pulls included. A calendar that cannot be read
    changes nothing. Does nothing unless MARKETING_DESK covers the business."""
    scope = desk_scope()
    if scope is None:
        return {'skipped': 'off'}
    at = now or _now()
    only = '' if scope == '*' else f"&business_id=in.({','.join(sorted(scope))})"
    try:
        posts = await store.rows(
            f'/marketing_posts?source=eq.opening&status=in.(draft,approved)'
            f'&run_at=lt.{reading.query_time(at + openings.WATCH_AHEAD)}&expires_at=gt.{reading.query_time(at)}'
            f'{only}&select={openings.WATCH_COLUMNS}&order=run_at.asc&limit={openings.WATCH_LIMIT}')
    except store.StoreError:
        return {'skipped': 'storage'}
    tally = await openings.watch([p for p in posts if desk_on_for(p.get('business_id'))], at)
    try:
        tally['told'] += await openings.tell_pulled(at, only)
    except Exception:
        log.warning('marketing planner: the pulled posts could not be told this time.', exc_info=True)
        tally['tell_skipped'] += 1
    return dict(tally)


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


def _week_fits(reserved_usd: float) -> bool:
    """Whether one more weekly plan fits under 60% of DAILY_SPEND_CAP_USD,
    counted conservatively: today's platform spend, plus what is already on
    its way (designs in progress and the weeks this tick started, at their
    estimates, since a design's cost is booked only once it is made), plus
    this week's estimate (five captions and five flyers, WEEK_ESTIMATE_USD)."""
    import spend_guard
    cap = spend_guard.platform_cap_usd()
    if cap <= 0:
        return False
    return spend_guard.platform_share() * cap + reserved_usd + WEEK_ESTIMATE_USD < HEADROOM_SHARE * cap


async def marketing_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Hourly, on the worker, on the scheduler leader. Writes the weekly
    suggestion, the weekly plan or the open-chairs week for every business
    that is due, at most max_per_tick() of them, each in its own try with its
    own claim. A week
    also needs room for its five flyers (MARKETING_DESIGNS_AT_ONCE across
    every business) and its estimated cost under the spend headroom; one
    that does not fit waits for a later hour while the suggestions go on."""
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
    room: Optional[int] = None          # flyers that may still start (read at the first week)
    reserved = 0.0                      # USD on its way: designs in progress, weeks started this tick
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
            if row.get('_kind') == OPENINGS_KIND:
                # One small caption call and free pictures: counted like a suggestion.
                out = await run_openings(bid, trigger='scheduled', now=at)
                tally[f"openings_{out.get('status')}"] += 1
                continue
            if row.get('_kind') == WEEK_KIND:
                if room is None:
                    busy = await designs_in_progress()
                    room = 0 if busy is None else designs_at_once() - busy
                    reserved = (busy or 0) * DESIGN_ESTIMATE_USD
                if room < FLYERS_PER_WEEK:
                    tally['week_waits_for_designs'] += 1
                    continue
                if not await asyncio.to_thread(_week_fits, reserved):
                    tally['week_waits_for_headroom'] += 1
                    continue
                reserved += WEEK_ESTIMATE_USD
                out = await run_week(bid, trigger='scheduled', now=at)
                room -= int(out.get('designing') or 0)
                tally[f"week_{out.get('status')}"] += 1
                continue
            out = await run_suggestion(bid, trigger='scheduled', now=at)
            tally[str(out.get('status'))] += 1
        except Exception:
            log.exception('marketing planner: the run for %s stopped unexpectedly', bid[:8])
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
    """Every minute, on the worker: write the suggestions and weeks owners
    asked for. A week waits (queued) while MARKETING_DESIGNS_AT_ONCE has no
    room for its five flyers, and gives up in plain words after 10 minutes,
    keeping the week's earlier plan. A request older than the claim's 15
    minutes is left to the claim's own reclaim; it is never written twice."""
    if desk_scope() is None:
        return {'skipped': 'off'}
    at = now or _now()
    try:
        queued = await store.rows(
            f'/marketing_runs?status=eq.running&trigger=eq.manual&kind=in.({KIND},{WEEK_KIND},{OPENINGS_KIND})'
            f'&created_at=gte.{reading.query_time(at - RECLAIM)}'
            '&design->>queued_at=not.is.null&design->>started_at=is.null'
            f'&select={RUN_COLUMNS}&order=created_at.asc&limit={MANUAL_BATCH}')
    except store.StoreError:
        return {'skipped': 'storage'}
    tally: Counter = Counter()
    room: Optional[int] = None
    for run in queued:
        bid = str(run.get('business_id'))
        week = run.get('kind') == WEEK_KIND
        chairs = run.get('kind') == OPENINGS_KIND
        kept_note = WEEK_KEPT if week else OPENINGS_KEPT if chairs else KEPT
        try:
            if week:
                if room is None:
                    busy = await designs_in_progress()
                    room = 0 if busy is None else designs_at_once() - busy
                if room < FLYERS_PER_WEEK:
                    asked = words._stamp(((run.get('design') or {}) if isinstance(run.get('design'), dict)
                                          else {}).get('queued_at'))
                    if asked and asked >= at - MANUAL_WAIT:
                        tally['week_waiting'] += 1
                        continue
                    started = await _start(run, at)
                    if started:
                        await _close(bid, run['id'], at, status='skipped', error=DESIGNS_BUSY, manual=True,
                                     prior=started.get('design'), kept_note=kept_note)
                    tally['week_busy'] += 1
                    continue
            started = await _start(run, at)
            if not started:
                tally['taken'] += 1
                continue
            if await asyncio.to_thread(_business_over, bid):
                import spend_guard
                await _close(bid, run['id'], at, status='skipped', error=spend_guard.block_message(), manual=True,
                             prior=started.get('design'), kept_note=kept_note)
                tally['over_budget'] += 1
                continue
            if week:
                out = await run_week(bid, trigger='manual', now=at, run=started)
                room -= int(out.get('designing') or 0)
                tally[f"week_{out.get('status')}"] += 1
                continue
            if chairs:
                out = await run_openings(bid, trigger='manual', now=at, run=started)
                tally[f"openings_{out.get('status')}"] += 1
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
    """Whether the owner already got a suggestion from a request today, on
    the business's clock. Only a request that saved a new post counts
    (design.made): one that was skipped, failed or kept the earlier
    suggestion leaves the owner free to ask again. A failed read raises (the
    route answers 503)."""
    rows = await store.rows(f'/marketing_runs?business_id=eq.{business_id}&trigger=eq.manual'
                            f'&created_at=gte.{reading.query_time(at - timedelta(days=2))}'
                            '&select=id,status,design,created_at&limit=20')
    since = _local_midnight(at, tz)
    for r in rows:
        design = r.get('design') if isinstance(r.get('design'), dict) else {}
        stamp = words._stamp(design.get('queued_at'))
        if stamp and stamp >= since and design.get('made'):
            return True
    return False


async def queue_request(business_id: str, week: date, user_id: str, at: datetime, *, kind: str = KIND) -> UUID:
    """Claim the week for the owner's request and mark it queued, in ONE
    write, so a write that fails changes nothing.

    Not marketing_claim_run: its manual start-over cancels the waiting
    drafts at claim time, before anything has replaced them. Here nothing is
    cancelled; the worker retires the earlier suggestion (or the week's
    earlier plan) only after the new one is saved (_retire), and keeps it
    when it writes nothing (_close). The claim's own rules otherwise: a week
    with no run is inserted; a failed or skipped one, a run stuck 15
    minutes, or a succeeded one whose posts are all still drafts is taken
    over by a write conditional on its status and attempt count. A running
    week, or one with an approved or sent post, is busy (409).

    kind WEEK_KIND (a weekly plan): a planned week is planned again at most
    twice (design.replans, 429), never while a flyer of it is still being
    made (409), and may take over the week's suggestion (a business that
    moved up a level).

    kind OPENINGS_KIND (the open-chairs week, B11): the week's rules (twice
    at most, 429), may take over the week's suggestion or plain week, and a
    pulled post (its chairs booked) does not hold the week."""
    busy = WEEK_BUSY if kind in (WEEK_KIND, OPENINGS_KIND) else BUSY
    run_id = store.run_id_for(business_id, week)
    marker = {'queued_at': words._z(at), 'queued_by': str(user_id)}
    current = await bm._call(store.get_run(business_id, run_id), down=bm.READ_DOWN)
    try:
        if current is None:
            await store.request('POST', '/marketing_runs', {
                'id': str(run_id), 'business_id': business_id, 'week_of': week.isoformat(), 'kind': kind,
                'trigger': 'manual', 'status': 'running', 'attempts': 1, 'design': marker})
            return run_id
        status, attempts = current.get('status'), int(current.get('attempts') or 1)
        design = current.get('design') if isinstance(current.get('design'), dict) else {}
        where = (f'/marketing_runs?id=eq.{run_id}&business_id=eq.{business_id}&status=eq.{status}'
                 f'&attempts=eq.{attempts}')
        takes_over = ((kind == WEEK_KIND and current.get('kind') == KIND)
                      or (kind == OPENINGS_KIND and current.get('kind') in (KIND, WEEK_KIND)))
        if current.get('kind') not in (None, kind) and not takes_over:
            raise HTTPException(409, busy)
        if status == 'running':
            started = words._stamp(current.get('created_at'))
            if not started or started >= at - RECLAIM:
                raise HTTPException(409, busy)
            where += f'&created_at=lt.{reading.query_time(at - RECLAIM)}'
        elif status == 'succeeded':
            settled = 'draft,cancelled,pulled' if kind == OPENINGS_KIND else 'draft,cancelled'
            sent = await store.rows(f'/marketing_posts?run_id=eq.{run_id}&business_id=eq.{business_id}'
                                    f'&status=not.in.({settled})&select=id&limit=1')
            if sent:
                raise HTTPException(409, busy)
            if kind == WEEK_KIND:
                designing = await store.rows(f'/marketing_posts?run_id=eq.{run_id}&business_id=eq.{business_id}'
                                             '&status=neq.cancelled&design_status=eq.designing&select=id&limit=1')
                if designing:
                    raise HTTPException(409, STILL_DESIGNING)
            if (kind in (WEEK_KIND, OPENINGS_KIND) and current.get('kind') == kind
                    and int(design.get('replans') or 0) >= REPLANS_PER_WEEK):
                raise HTTPException(429, REPLANNED_TWICE)
        elif status not in ('failed', 'skipped'):
            raise HTTPException(409, busy)
        kept = {k: v for k, v in design.items() if k not in QUEUE_KEYS and k not in ('tell', 'told_at')}
        saved = await store.request('PATCH', where, {
            'status': 'running', 'trigger': 'manual', 'kind': kind, 'attempts': attempts + 1, 'error': None,
            'created_at': at.isoformat(), 'finished_at': None, 'design': {**kept, **marker}})
    except store.StoreConflict:
        raise HTTPException(409, busy) from None
    except store.StoreUnavailable:
        raise HTTPException(503, bm.STORE_DOWN) from None
    if not saved:
        raise HTTPException(409, busy)
    return run_id


@router.post('/engine/run', status_code=202)
async def run_route(business_id: UUID, user: AuthedUser = Depends(require_user)):
    """Queue this week's suggestion (suggest level), weekly plan (week
    levels) or open-chairs week (openings level, B11) now. The owner only;
    the worker writes it (the model never runs on the web process)."""
    import rate_limit
    bid = str(business_id)
    owner_row = await bm._require_owner(bid, user)
    if not desk_on_for(bid):
        raise HTTPException(409, NOT_SWITCHED_ON)
    try:
        row = await asyncio.to_thread(read_business, bid)
        kind, problem = await asyncio.to_thread(run_kind, row)
    except Unavailable:
        raise HTTPException(503, bm.READ_DOWN) from None
    except LookupError:
        raise HTTPException(404, 'Business not found.') from None
    if problem:
        raise HTTPException(409 if problem in (WEEK_LEVEL, OPENINGS_LEVEL) else 403, problem)
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
    if kind == KIND:
        # A week is held to its two replans instead (queue_request).
        try:
            if await asked_today(bid, tz, at):
                raise HTTPException(429, ONCE_A_DAY)
        except store.StoreError:
            raise HTTPException(503, bm.READ_DOWN) from None
    week = target_week(at, tz)
    # One write claims the week and marks it queued; nothing is cancelled
    # here, and no desk row is made (the worker makes one before it saves).
    run_id = await queue_request(bid, week, str(user.id), at, kind=kind)
    week_said = WEEK_CLIPS_QUEUED if clips.takes_clips(row) else WEEK_QUEUED
    return {'queued': True, 'run_id': str(run_id), 'week_of': week.isoformat(), 'kind': kind,
            'message': week_said if kind == WEEK_KIND else OPENINGS_QUEUED if kind == OPENINGS_KIND else QUEUED}


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
    if level['level'] != LEVEL:
        # A week leans on what did well through the business's own links (B9).
        import business_marketing_outcomes as outcomes
        try:
            signals['play_scores'] = await outcomes.play_scores(business_id, now=at)
        except store.StoreError:
            signals['play_scores'] = {}
    plan = engine.pick_plays(diagnosis, n, signals, profile, facts)
    out = {'business_id': business_id, 'level': level['level'], 'upgrade': level['upgrade'],
           'switched_on': desk_on_for(business_id), 'time_zone': tz.key,
           'week_of': target_week(at, tz).isoformat(), 'diagnosis': diagnosis, 'plays': plan['plays'],
           'slots': plan['slots'], 'facts': facts, 'signals': marketing_signals.summary(signals),
           'profile': {k: profile.get(k) for k in PROFILE_PUBLIC}}
    if level['level'] == OPENINGS_KIND:
        out['openings'] = await openings_preview(row, tz, target_week(at, tz), at)
    return out


async def openings_preview(row: Dict[str, Any], tz: ZoneInfo, week_of: date, at: datetime) -> Optional[Dict[str, Any]]:
    """The open chairs Chief would post about that week, and when each post
    would go out (B11). Reads only; None when the calendar cannot be read."""
    try:
        desk = await store.get_desk(str(row['id']))
        calendar = await asyncio.to_thread(openings.read_calendar, row, tz, week_of, at)
    except (openings.Unavailable, store.StoreError):
        return None
    if calendar['state'] != 'ok':
        return {'state': calendar['state'], 'windows': []}
    picked = openings.pick(calendar['windows'], calendar['counts'], tz=tz, post_hour=(desk or {}).get('post_hour', 11),
                           at=at, gap=calendar['gap'])
    return {'state': 'ok', 'offering': calendar['offering'].get('name'), 'offering_from': calendar['offering_from'],
            'open_windows': len(calendar['windows']),
            'windows': [{'when': openings.when_words(w['starts_at'], w['ends_at'], tz),
                         'starts_at': w['starts_at'].isoformat(), 'ends_at': w['ends_at'].isoformat(),
                         'run_at': w['run_at'].isoformat(), 'score': w['score']} for w in picked]}


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

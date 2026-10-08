"""business_marketing_clips.py — the clips' half of Solutionist's week (marketing suite B12).

D6 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md. A business at the
desk's `autopilot` level (its real plan includes marketing_autopilot and
ai_clips: Solutionist, `practice`) gets Chief's weekly plan (B9's five posts,
business_marketing_planner._plan_week) with up to TWO of its own video
clips folded in. Professional and Boss never get clips (Boss: "No Video
Clips"), and neither does the suggest level: takes_clips() is False for
every plan but Practice. This module is the clips' half: which clip, when,
to which accounts, with which cover; the planner writes the caption (in the
week's one caption call) and saves the post with the week's other drafts.

WHICH CLIPS (eligible, every one of these):
  * ready, still stored (source_removed_at empty), kind clip, this business's;
  * KEPT by the owner in Video Clips (decision 'kept': not skipped, not
    undecided);
  * approved in "Ready to post?" AT THE FINGERPRINT IT HAS NOW
    (clip_posting.approval_problem is None);
  * not posted anywhere yet: no publication of it through the one posting
    door (social_publications, status other than failed or cancelled), which
    is where Chief's post_clip, the clip screen and the desk all send;
  * not already in a post that is waiting or went out (a marketing_posts row
    naming it, status other than cancelled, failed or pulled), except this
    week's own drafts that a replan is about to retire;
  * a READY story (9:16) cover: the cover every vertical network shows.
  A read that fails puts no clip in the week (never a guess that could post a
  clip twice); the week itself is planned as B9's.

THE PICK. Best first: the clip finder's score (configuration.score, highest
first; a clip without one after every scored clip), then the newest, then
the id. At most PER_WEEK (2), each clip once.

WHEN. Each clip on its own weekday of the week, in DAY_ORDER (Tuesday,
Thursday, Wednesday, Monday, Friday: the two clips land two days apart when
they can), never two the same day; at the desk's hour or the next free hour
up to 21:00, then 3:00 PM and after (the desk's other hour), on the
business's own clock; at least an hour from now; and at least GAP (3 hours)
from every other post of the business that day: the week's flyer posts, the
owner's own posts, anything already planned. Instants are compared in UTC,
so a daylight-saving change never moves one.

ADD, NOT REPLACE. The clips come on top of the five flyer posts (seven at
most a week). Nothing it touches caps that lower: the posting door's daily
cap is 25 posts a business per day and a clip day has two; the week's five
included flyers and MARKETING_DESIGNS_AT_ONCE count designs, and a clip needs
none; marketing_approve takes 50 at once.

WHERE. The desk's accounts (or every connected one when the desk names
none) that can take a video: every network clip_posting knows how to place
a vertical clip on (COVER_SHAPES), TikTok and YouTube included (Kevin,
2026-10-07: no plan gates a network). The cover each network shows is
clip_posting.cover_for's, at send time: the story cover everywhere a
vertical clip plays (Instagram and Facebook Reels, TikTok, YouTube Shorts,
X, Threads, Pinterest), the wide cover on LinkedIn (falling back to the
story cover). The post binds both covers by id; the run records which
network shows which.

THE APPROVAL. The post's media is business_marketing.build_media's for a
clip ({clip_id, clip_fingerprint, covers}), so the fingerprint is inside
the post's content_hash. The sender (business_marketing_dispatch) refuses a
clip that is no longer approved as it is now, or whose fingerprint is not
the one the post was approved with, and clip_posting.post_clip_for checks
again. Nothing here approves or sends.

COST. No call of its own: each clip is one more slot in the week's caption
call (business_marketing_planner.write_week_captions).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from fastapi import HTTPException

import business_marketing as bm
import business_marketing_desk as reading
import business_marketing_engine as engine
import business_marketing_store as store
import clip_covers
import clip_posting
import feature_gates
import marketing_desk as words
import media_library
import sb_clients

log = logging.getLogger(__name__)

FEATURES = ('marketing_autopilot', 'ai_clips')   # D4: the autopilot level, and clips on the plan
PER_WEEK = 2
CANDIDATES = 50                       # the newest kept, approved, ready clips read per week
GAP = timedelta(hours=3)              # from every other post of the business that day
LAST_HOUR = 21                        # the desk's latest hour (post_hour 6..21)
DAY_ORDER = (1, 3, 2, 0, 4)           # Tuesday, Thursday, Wednesday, Monday, Friday
NEEDS = 'story'                       # the cover every vertical network shows
VIDEO_PLATFORMS = frozenset(clip_posting.COVER_SHAPES)
PLAY_ID = 'video_clip'                # marketing_posts.play_id: the clips' own results (play_scores)
PLAY_LABEL = 'Share a video clip'
PLAY_BRIEF = ("This post is one of the business's own short videos, posted as it is. Its title and the words the "
              'owner checked are in `clip`. Write a caption that makes someone want to watch it: what it is about '
              'and why it is worth a minute, from its title and words only. Nobody has watched it for you, so say '
              'nothing about what is shown or said beyond them. Leave out any number in its title unless the facts '
              'give it. The video is the picture: give no flyer for this slot. ' + engine.NO_NAMES)
MAX_TOKENS_EACH = 300                 # one short caption more in the week's call
WORDS_MAX = 500
TAGS_MAX = 5
NOTED_MAX = 20                        # skipped clips recorded on the run
OPEN = 'cancelled,failed,pulled'      # a marketing post in any other status holds its clip
NOT_POSTED = 'failed,cancelled'       # a publication in any other status means the clip went (or is going) out
POSTED_LIMIT = 500
COVER_LIMIT = 500
CLIP_COLUMNS = ('id,business_id,kind,source_id,name,status,configuration,sha256,approval,decision,decided_at,'
                'source_removed_at,duration_seconds,created_at,finished_at')
COVER_COLUMNS = 'id,business_id,status,size,storage_path,created_at,clip_id:director->>clip_id'


class Unavailable(Exception):
    """A read the clips need did not happen. Never "no clips" or "not posted"."""


# ── who gets clips ────────────────────────────────────────────────────

def takes_clips(row: Optional[Dict[str, Any]]) -> bool:
    """The autopilot level (marketing_autopilot) with clips on the plan
    (ai_clips), from the real plan (feature_gates.plan_includes, whatever
    BILLING_ENFORCE says): Practice only. Professional, Boss, Starter, Solo
    and Booked never get clips in their week."""
    return all(feature_gates.plan_includes(row, f) for f in FEATURES)


# ── one clip ──────────────────────────────────────────────────────────

def problem(row: Dict[str, Any], business_id: Optional[str] = None) -> Optional[str]:
    """Why this clip cannot go in the week by itself, or None. The reads
    (posted, in a waiting post, its cover) are checked by plan_clips."""
    if business_id and str(row.get('business_id')) != str(business_id):
        return 'not_this_business'
    if row.get('kind') != 'clip' or row.get('status') != 'ready':
        return 'not_ready'
    if row.get('source_removed_at'):
        return 'not_stored'
    if row.get('decision') != 'kept':
        return 'not_kept'
    return clip_posting.approval_problem(row)          # 'unapproved', 'changed' or None


def _stamp(row: Dict[str, Any]) -> float:
    for key in ('finished_at', 'created_at'):
        when = words._stamp(row.get(key))
        if when:
            return when.timestamp()
    return 0.0


def _score(row: Dict[str, Any]) -> Optional[float]:
    raw = (row.get('configuration') or {}).get('score') if isinstance(row.get('configuration'), dict) else None
    try:
        return None if raw is None or isinstance(raw, bool) else float(raw)
    except (TypeError, ValueError):
        return None


def rank(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Best first: the clip finder's score (highest first; none after every
    scored clip), then the newest, then the id (so the order never wobbles)."""
    def key(row):
        score = _score(row)
        return (score is None, -(score or 0.0), -_stamp(row), str(row.get('id')))
    return sorted(rows, key=key)


def post_id(run_id: Any, attempt: int, n: int) -> str:
    """The n-th clip post of an attempt of the week's run: a retry inside an
    attempt is the same post, and a replan gets new ones."""
    return str(uuid5(UUID(str(run_id)), f'{int(attempt)}:clip:{int(n)}'))


# ── when ──────────────────────────────────────────────────────────────

def _hours(post_hour: Any) -> List[int]:
    """The desk's hour and each hour after it to 21:00, then 3:00 PM and after."""
    try:
        hour = int(post_hour)
    except (TypeError, ValueError):
        hour = 11
    hour = hour if 6 <= hour <= LAST_HOUR else 11
    return list(dict.fromkeys(list(range(hour, LAST_HOUR + 1)) + list(range(bm.OTHER_HOUR, LAST_HOUR + 1))))


def place(count: int, *, week_of: date, tz: ZoneInfo, post_hour: Any, at: datetime,
          busy: Iterable[datetime]) -> List[datetime]:
    """Up to `count` times, one per weekday (DAY_ORDER), each at the desk's
    hour or the next free one, at least an hour from now and at least GAP
    from every time in `busy` (and from each other). Fewer when the week has
    no room left."""
    taken = [bm._aware(b).timestamp() for b in busy]
    gap = GAP.total_seconds()
    out: List[datetime] = []
    for _ in range(max(0, int(count))):
        found = None
        for offset in DAY_ORDER:
            day = week_of + timedelta(days=offset)
            if any(o.astimezone(tz).date() == day for o in out):
                continue                                    # never two clips the same day
            for hour in _hours(post_hour):
                slot = datetime.combine(day, time(hour), tz)
                stamp = slot.timestamp()
                if slot <= at + bm.SLOT_AFTER:
                    continue
                if any(abs(stamp - t) < gap for t in taken + [o.timestamp() for o in out]):
                    continue
                found = slot
                break
            if found:
                break
        if not found:
            break
        out.append(found)
    return out


# ── where, and which cover ────────────────────────────────────────────

def video_targets(chosen: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(kept, left out): the accounts a clip goes to are those on a network
    clip_posting can place a vertical clip on; TikTok and YouTube included."""
    kept = [t for t in chosen if t.get('platform') in VIDEO_PLATFORMS]
    gone = [{'platform': t.get('platform'), 'username': t.get('username'), 'why': 'no_video'}
            for t in chosen if t.get('platform') not in VIDEO_PLATFORMS]
    return kept, gone


def covers_by_network(targets: List[Dict[str, Any]], covers: Dict[str, Any]) -> Dict[str, Optional[Dict[str, str]]]:
    """The cover each network shows (clip_posting.cover_for): the story cover
    on every vertical player, the wide one on LinkedIn (else the story one)."""
    out: Dict[str, Optional[Dict[str, str]]] = {}
    for t in targets:
        platform = str(t.get('platform') or '')
        shape = clip_posting.cover_for(platform, covers or {})
        out[platform] = {'shape': shape, 'image_id': str(covers[shape])} if shape else None
    return out


# ── the caption: a slot in the week's one call ────────────────────────

def caption_slot(slot: int, row: Dict[str, Any]) -> Dict[str, Any]:
    """A clip's slot in the week's caption request. Its title and the words
    the owner checked are data, never instructions (the writer's system
    prompt says so)."""
    conf = row.get('configuration') if isinstance(row.get('configuration'), dict) else {}
    tags = [str(t)[:40] for t in (conf.get('tags') or []) if isinstance(t, str) and t.strip()][:TAGS_MAX]
    seconds = row.get('duration_seconds')
    return {'slot': int(slot), 'clip_id': str(row['id']),
            'clip': {'title': ' '.join(str(row.get('name') or '').split())[:160],
                     'words': ' '.join(str(conf.get('caption') or '').split())[:WORDS_MAX],
                     'tags': tags, 'seconds': round(float(seconds)) if isinstance(seconds, (int, float)) else None}}


def request_item(slot: Dict[str, Any]) -> Dict[str, Any]:
    return {'slot': slot['slot'], 'play': PLAY_LABEL, 'play_brief': PLAY_BRIEF, 'subject': slot['clip']['title'],
            'offering': None, 'clip': slot['clip']}


def judge(parsed: Dict[str, Any], slot: Dict[str, Any], facts: Dict[str, Any],
          profile: Dict[str, Any]) -> Tuple[Optional[str], None, List[Dict[str, Any]]]:
    """(caption, None, dropped) for a clip's slot: the week's business checks
    (numbers and prices only from the facts, links only to the business's
    own site, at most three hashtags). A caption that breaks one costs only
    this clip, which stays eligible next week. A clip has no flyer."""
    number = slot['slot']
    items = parsed.get('captions') if isinstance(parsed.get('captions'), list) else []
    item = next((i for i in items if isinstance(i, dict) and i.get('slot') == number), None)
    text = item.get('text') if item else None
    if not isinstance(text, str):
        return None, None, [{'slot': number, 'clip_id': slot['clip_id'], 'reason': 'missing'}]
    why = engine.check_caption(text, facts, profile, None)
    if why:
        return None, None, [{'slot': number, 'clip_id': slot['clip_id'], 'reason': why}]
    return text.strip(), None, []


# ── reads ─────────────────────────────────────────────────────────────

def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise Unavailable(path.split('?')[0])
    return rows


def read_clips(business_id: str) -> List[Dict[str, Any]]:
    """The business's newest ready, stored, kept clips with an approval (at
    most CANDIDATES). Whether the approval is for the clip as it is now is
    problem()'s to say."""
    rows = _get(f'/media_assets?business_id=eq.{business_id}&kind=eq.clip&status=eq.ready&decision=eq.kept'
                f'&approval=not.is.null&source_removed_at=is.null&select={CLIP_COLUMNS}'
                f'&order=created_at.desc&limit={CANDIDATES}')
    return [r for r in rows if str(r.get('business_id')) == str(business_id)]


def posted(business_id: str, ids: List[str]) -> set:
    """The clips among these that already went (or are going) out through the
    one posting door: Chief's post_clip, the clip screen and the desk all
    record a clip's publication with media [{kind: video, clip_id}]."""
    if not ids:
        return set()
    rows = _get(f"/social_publications?business_id=eq.{business_id}&status=not.in.({NOT_POSTED})"
                f"&media->0->>clip_id=in.({','.join(ids)})&select=id,business_id,media,status&limit={POSTED_LIMIT}")
    if len(rows) >= POSTED_LIMIT:
        raise Unavailable('social_publications')     # at the limit: never "the rest were not posted"
    out = set()
    for r in rows:
        if str(r.get('business_id')) != str(business_id):
            continue
        for m in r.get('media') or []:
            if isinstance(m, dict) and m.get('clip_id'):
                out.add(str(m['clip_id']))
    return out & set(ids)


def ready_covers(business_id: str, ids: List[str]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{clip id: {shape: the newest ready cover of that shape}} for these
    clips (clip_posting.ready_covers' rule, read in one go)."""
    if not ids:
        return {}
    rows = _get(f"/image_artworks?business_id=eq.{business_id}&director->>clip_id=in.({','.join(ids)})"
                f'&status=eq.ready&select={COVER_COLUMNS}&order=created_at.desc&limit={COVER_LIMIT}')
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        clip = str(r.get('clip_id') or '')
        if str(r.get('business_id')) != str(business_id) or clip not in ids or not r.get('storage_path'):
            continue
        shape = clip_posting._shape_of(r)
        if shape in clip_covers.SHAPES:
            out.setdefault(clip, {}).setdefault(shape, r)
    return out


async def in_posts(business_id: str, ids: List[str], skip: Iterable[str]) -> set:
    """The clips among these already in one of the business's posts that is
    waiting or went out (any status but cancelled, failed or pulled). `skip`:
    this week's own drafts a replan is about to retire."""
    if not ids:
        return set()
    skip = {str(s) for s in skip}
    try:
        rows = await store.rows(f"/marketing_posts?business_id=eq.{business_id}&media->>clip_id=in.({','.join(ids)})"
                                f'&status=not.in.({OPEN})&select=id,status,media&limit={POSTED_LIMIT}')
    except store.StoreError:
        raise Unavailable('marketing_posts') from None
    if len(rows) >= POSTED_LIMIT:
        raise Unavailable('marketing_posts')         # at the limit: never "the rest are free"
    return {str((r.get('media') or {}).get('clip_id')) for r in rows if str(r.get('id')) not in skip} & set(ids)


async def busy_times(business_id: str, week_of: date, tz: ZoneInfo, skip: Iterable[str]) -> List[datetime]:
    """Every other post of the business that week (its own clock), but the
    drafts a replan is about to retire."""
    skip = {str(s) for s in skip}
    start = datetime.combine(week_of, time(0), tz)
    end = datetime.combine(week_of + timedelta(days=7), time(0), tz)
    try:
        rows = await store.rows(
            f'/marketing_posts?business_id=eq.{business_id}&select=id,run_at&status=not.in.(cancelled,pulled)'
            f'&run_at=gte.{reading.query_time(start)}&run_at=lt.{reading.query_time(end)}&limit={bm.TAKEN_LIMIT}')
    except store.StoreError:
        raise Unavailable('marketing_posts') from None
    if len(rows) >= bm.TAKEN_LIMIT:
        raise Unavailable('marketing_posts')
    return [bm._aware(r['run_at']) for r in rows if r.get('run_at') and str(r.get('id')) not in skip]


# ── the week's clips ──────────────────────────────────────────────────

def _noted(row: Dict[str, Any], why: str) -> Dict[str, Any]:
    return {'clip_id': str(row.get('id')), 'name': str(row.get('name') or '')[:80], 'why': why}


async def plan_clips(business_id: str, *, run_id: Any, week_of: date, tz: ZoneInfo, desk: Optional[Dict[str, Any]],
                     at: datetime, plan_times: Iterable[datetime], previous: Iterable[Dict[str, Any]],
                     first_slot: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The week's clips: ([pick], record). Each pick is {n, slot, clip,
    media, run_at}: media is business_marketing.build_media's for the clip
    (re-read fail-closed, approved as it is now, its covers checked), run_at
    its time. The record goes on the run (design.clips). A read that fails
    picks nothing: the week goes out as B9's, saying why."""
    bid = str(UUID(str(business_id)))
    skip = [str(p['id']) for p in previous]
    record: Dict[str, Any] = {'state': 'ok', 'per_week': PER_WEEK, 'eligible': 0, 'picked': [], 'skipped': []}
    try:
        rows = await asyncio.to_thread(read_clips, bid)
        ranked = rank(rows)
        skipped = [_noted(r, why) for r in ranked for why in [problem(r, bid)] if why]
        candidates = [r for r in ranked if not problem(r, bid)]
        ids = [str(r['id']) for r in candidates]
        gone = await asyncio.to_thread(posted, bid, ids)
        held = await in_posts(bid, ids, skip)
        covers = await asyncio.to_thread(ready_covers, bid, ids)
        eligible = []
        for r in candidates:
            cid = str(r['id'])
            why = ('posted' if cid in gone else 'in_a_post' if cid in held
                   else 'no_cover' if NEEDS not in covers.get(cid, {}) else None)
            if why:
                skipped.append(_noted(r, why))
            else:
                eligible.append(r)
        record['eligible'] = len(eligible)
        times: List[datetime] = []
        if eligible:
            busy = await busy_times(bid, week_of, tz, skip) + list(plan_times)
            times = place(min(PER_WEEK, len(eligible)), week_of=week_of, tz=tz,
                          post_hour=(desk or {}).get('post_hour', 11), at=at, busy=busy)
    except Unavailable as exc:
        log.warning('marketing clips: a read for %s failed (%s); no clips this week', bid[:8], exc)
        return [], {**record, 'state': 'unreadable', 'picked': [], 'skipped': []}
    picks: List[Dict[str, Any]] = []
    for r in eligible:
        if len(picks) >= PER_WEEK:
            break
        if len(picks) >= len(times):
            skipped.append(_noted(r, 'no_time'))          # the week has no room left for it
            break
        cid = str(r['id'])
        wanted = {shape: str(art['id']) for shape, art in sorted(covers[cid].items())}
        try:
            media = await bm.build_media(bid, clip_id=cid, clip_fingerprint=media_library.fingerprint(r),
                                         covers=wanted)
        except HTTPException as exc:
            # Changed or gone since the read, or the read failed: never this clip on a guess.
            skipped.append(_noted(r, 'unreadable' if exc.status_code >= 500 else 'changed'))
            continue
        if NEEDS not in (media.get('covers') or {}):
            skipped.append(_noted(r, 'no_cover'))
            continue
        n = len(picks) + 1
        picks.append({'n': n, 'slot': int(first_slot) + n - 1, 'clip': r, 'media': media,
                      'run_at': times[n - 1]})
    record['skipped'] = skipped[:NOTED_MAX]
    record['picked'] = [{'clip_id': str(p['clip']['id']), 'name': str(p['clip'].get('name') or '')[:80],
                         'score': _score(p['clip']), 'slot': p['slot'], 'run_at': p['run_at'].isoformat()}
                        for p in picks]
    return picks, record

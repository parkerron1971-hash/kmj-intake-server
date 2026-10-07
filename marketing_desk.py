"""marketing_desk.py — where Solutionist's own marketing stands, said plainly.

The weekly plan (marketing_engine) writes the week; the publisher
(platform_marketing) delivers it. This module reads both and says where
things stand, in each place the owner meets it:

  the desk     Chief's read (note), the masthead, and what needs a look
  Today        one queue item per thing waiting on the owner (platform_today)
  Chief        a digest in the Mission Control snapshot, so "what needs me?"
               includes marketing without opening the marketing drawer
  the phone    a push when a scheduled week is drafted or cannot be, and when
               a post does not go out

Kevin, 2026-10-02: "chief should be involved and proactive when it comes to
the business and marketing." Before this, fifteen drafts sat on the desk while
Today counted a different calendar and showed none of them, and nothing said
when a post failed.

All of it is arithmetic over rows. No model call, so the desk can read it on
every load and Today on every open, and every sentence carries a counted
number or a row's own words. A "post" here is one idea: the same caption on
each connected channel, which the desk shows and approves together.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

import platform_marketing as marketing

log = logging.getLogger(__name__)

TZ = ZoneInfo('America/New_York')        # the engine's posting clock (marketing_engine.TZ)
LOOKBACK = timedelta(days=21)
MISSED_WINDOW = timedelta(days=14)       # a draft whose time passed longer ago is history, not a to-do
FAILED_WINDOW = timedelta(days=14)
SOON = timedelta(hours=24)
NAV = 'studio:platform-growth'
SERVICE = {'twitter': 'X', 'facebook': 'Facebook', 'instagram': 'Instagram', 'linkedin': 'LinkedIn'}

PLAY_PHRASES = {
    'feature_spotlight': ('new thing that shipped', 'new things that shipped'),
    'founder_invitation': ('founding-seat invitation', 'founding-seat invitations'),
    'workflow_tip': ('useful move', 'useful moves'),
    'behind_the_build': ('story behind the build', 'stories behind the build'),
    'question_answered': ('real question answered', 'real questions answered'),
}
HEADLINES = {
    'unmarketed_news': 'Something shipped, and nobody has been told yet.',
    'visits_without_signups': 'People are looking, and not joining.',
    'traffic_down': 'Fewer people are finding the site.',
    'gone_quiet': 'It has gone quiet.',
    'steady': 'Nothing is off, so the week stays steady.',
}
TONE_KICKER = {'steady': 'STEADY', 'push': 'WORTH A PUSH', 'attention': 'NEEDS ATTENTION'}
WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']


# ── small words ───────────────────────────────────────────────────────

def _stamp(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _z(d):
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _local(value, tz=None):
    """The instant on the owner's clock: Eastern for Solutionist's own desk
    (the default), the business's own zone for a business desk
    (business_marketing_desk passes it)."""
    d = _stamp(value) if not isinstance(value, datetime) else value
    return d.astimezone(tz or TZ) if d else None


def _word(n):
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def _plural(n, one, many=None):
    return f'{_word(n)} {one if n == 1 else (many or one + "s")}'


def _join(parts):
    parts = [p for p in parts if p]
    return parts[0] if len(parts) == 1 else ', '.join(parts[:-1]) + ' and ' + parts[-1] if parts else ''


def _cap(text):
    return text[:1].upper() + text[1:] if text else text


def day_name(value, tz=None):
    d = _local(value, tz)
    return f'{d:%A}' if d else 'The next'


def clock(value, tz=None):
    d = _local(value, tz)
    return f'{d:%I:%M %p}'.lstrip('0') if d else ''


def short_day(value, tz=None):
    d = _local(value, tz)
    return f'{d:%a} {d:%b} {d.day}' if d else ''


def week_label(week_of):
    d = datetime.fromisoformat(str(week_of)).date() if week_of else None
    return f'{d:%B} {d.day}' if d else ''


def span(slots, tz=None):
    """'October 5–9' for a plan's posting days ('September 28–October 2' across months)."""
    days = sorted(d for d in (_local(s['run_at'], tz) for s in slots) if d)
    if not days:
        return ''
    a, b = days[0], days[-1]
    if a.date() == b.date():
        return f'{a:%B} {a.day}'
    return f'{a:%B} {a.day}–{b.day}' if a.month == b.month else f'{a:%B} {a.day}–{b:%B} {b.day}'


# ── reading ───────────────────────────────────────────────────────────

async def _safe(fetch):
    try:
        return await fetch()
    except HTTPException:
        return None          # unreadable is None, never an empty desk


async def read_state(now=None, runs=None):
    """The rows everything below is computed from. Each source is None when it
    could not be read, so a storage blip never reads as "nothing to do"."""
    now = now or marketing.now()
    if runs is None:
        runs = await _safe(lambda: marketing.db(
            'GET', '/platform_marketing_runs?select=id,week_of,status,trigger,attempts,signals,diagnosis,plays,'
                   'post_ids,error,design,created_at,finished_at&order=week_of.desc&limit=3'))
    since = _z(now - LOOKBACK)
    posts, cfg = await asyncio.gather(
        _safe(lambda: marketing.db(
            'GET', '/platform_marketing_posts?select=id,revision,status,run_at,expires_at,run_id,play_id,campaign,'
                   f'payload,error,content_hash,external_url&or=(run_at.gte.{since},status.eq.uncertain)'
                   '&status=neq.cancelled&order=run_at.asc&limit=400')),
        _safe(marketing.config))
    return {'now': now, 'runs': runs, 'posts': posts, 'config': cfg}


def slot_key(post):
    p = post.get('payload') or {}
    return f"{post.get('run_id') or post.get('campaign')}|{post['run_at']}|{p.get('text', '')}"


def slots(posts):
    """Posts grouped into ideas, in posting order: one caption, every channel it goes to."""
    out = {}
    for post in sorted(posts, key=lambda p: (str(p['run_at']), str(p['id']))):
        p = post.get('payload') or {}
        group = out.setdefault(slot_key(post), {
            'key': slot_key(post), 'run_at': post['run_at'], 'play_id': post.get('play_id'),
            'text': p.get('text', ''), 'channels': [], 'items': [], 'statuses': []})
        name = SERVICE.get(p.get('service'), p.get('service') or 'a channel')
        if name not in group['channels']:
            group['channels'].append(name)
        group['items'].append({'id': post['id'], 'revision': post['revision']})
        group['statuses'].append(post['status'])
    return list(out.values())


def _week_over(run, now, tz=None):
    start = datetime.fromisoformat(str(run['week_of'])).date()
    return now.astimezone(tz or TZ).date() >= start + timedelta(days=7)


def facts(state):
    """Counted things, in one place, for every sentence below."""
    import marketing_engine as engine
    now = state['now']
    posts = state['posts'] or []
    runs = state['runs'] or []
    latest = runs[0] if runs else None
    current = latest if latest and not _week_over(latest, now) else None

    def at(p):
        return _stamp(p['run_at']) or now
    drafts = [p for p in posts if p['status'] == 'draft']
    waiting = [p for p in drafts if at(p) > now]
    plan_posts = [p for p in posts if current and p.get('run_id') == current['id']]
    plan_waiting = [p for p in plan_posts if p in waiting]
    cfg = state['config'] or {}
    return {
        'now': now, 'latest': latest, 'current': current,
        'planning': engine.is_planning(latest, now),
        'which_week': engine.relation(current['week_of'], now) if current else None,
        'readable': state['posts'] is not None,
        'waiting': slots(waiting),
        'plan': slots(plan_posts),
        'plan_waiting': slots(plan_waiting),
        'missed': slots([p for p in drafts if now - MISSED_WINDOW <= at(p) <= now]),
        'failed': slots([p for p in posts if p['status'] == 'failed' and at(p) >= now - FAILED_WINDOW]),
        'failed_rows': [p for p in posts if p['status'] == 'failed' and at(p) >= now - FAILED_WINDOW],
        'uncertain': slots([p for p in posts if p['status'] == 'uncertain']),
        'approved': slots([p for p in posts if p['status'] == 'approved' and at(p) > now]),
        'going': slots([p for p in posts if p['status'] in ('dispatching', 'submitted')]),
        'published': slots([p for p in posts if p['status'] == 'published']),
        'paused': cfg.get('paused') if state['config'] is not None else None,
        'channels': [SERVICE.get(c.get('service'), c.get('service')) for c in cfg.get('channels') or []],
        'next_run': engine.next_run(now),
    }


# ── what needs a look ─────────────────────────────────────────────────

def _missed_when(missed, now, tz=None):
    local = now.astimezone(tz or TZ)
    monday = local.date() - timedelta(days=local.weekday())
    return 'this week' if all(_local(s['run_at'], tz).date() >= monday for s in missed) else 'the last two weeks'


def attention(f):
    """The desk's "Needs a look", in the order to deal with it. Each carries the
    ideas it is about, with the ids and revisions an action needs."""
    now, items = f['now'], []
    if f['failed']:
        rows = f['failed_rows']
        first = rows[0]
        where = SERVICE.get((first.get('payload') or {}).get('service'), 'a channel')
        n = len(f['failed'])
        items.append({'id': 'marketing:failed', 'kind': 'failed', 'tone': 'red',
                      'title': f"A post didn't go out on {where}" if n == 1 and len(rows) == 1
                               else f"{_cap(_plural(n, 'post'))} didn't go out",
                      'detail': (first.get('error') or 'Buffer did not accept it.')[:220],
                      'slots': f['failed']})
    if f['uncertain']:
        n = len(f['uncertain'])
        items.append({'id': 'marketing:uncertain', 'kind': 'uncertain', 'tone': 'amber',
                      'title': f"{_cap(_plural(n, 'post'))} may or may not have gone out",
                      'detail': 'Delivery was interrupted. Check Buffer, then mark each one sent or not sent.',
                      'slots': f['uncertain']})
    if f['paused'] and (f['approved'] or f['plan_waiting']):
        k = len(f['approved'])
        items.append({'id': 'marketing:paused', 'kind': 'paused', 'tone': 'amber',
                      'title': 'Publishing is paused',
                      'detail': (f"{_cap(_plural(k, 'approved post'))} will not go out until you resume it." if k
                                 else 'Nothing you approve will go out until you resume it.'),
                      'slots': f['approved']})
    if f['missed']:
        n = len(f['missed'])
        items.append({'id': 'marketing:missed', 'kind': 'missed', 'tone': 'amber',
                      'title': f"{_cap(_plural(n, 'post'))} from {_missed_when(f['missed'], now)} missed "
                               f"{'its' if n == 1 else 'their'} time",
                      'detail': f"{'It was' if n == 1 else 'They were'} never approved, so "
                                f"{'it' if n == 1 else 'they'} never went out. Reschedule or let "
                                f"{'it' if n == 1 else 'them'} go.",
                      'slots': f['missed']})
    latest = f['latest']
    if (latest and not f['planning'] and latest.get('status') in ('failed', 'skipped')
            and not _week_over(latest, now)):
        items.append({'id': f"marketing:plan:{latest['id']}", 'kind': 'plan_failed', 'tone': 'amber',
                      'title': f"The plan for the week of {week_label(latest['week_of'])} could not be written",
                      'detail': (latest.get('error') or 'Nothing was saved.')[:220], 'slots': []})
    quiet = (f['readable'] and not f['planning'] and not f['waiting'] and not f['approved'] and not f['going']
             and f['channels'] and not any(i['kind'] == 'plan_failed' for i in items))
    if quiet:
        items.append({'id': 'marketing:quiet', 'kind': 'quiet', 'tone': 'gold',
                      'title': 'Nothing is going out in the next 7 days',
                      'detail': f"Next week's plan is written {day_name(f['next_run'])} at {clock(f['next_run'])}. "
                                'You can plan the rest of this week now.',
                      'slots': []})
    return items


# ── Chief's read and the masthead ─────────────────────────────────────

def _plays_sentence(plays):
    parts = []
    for play in plays or []:
        one, many = PLAY_PHRASES.get(play.get('play_id'), (play.get('label', 'post').lower(),) * 2)
        n = int(play.get('posts') or 0)
        if n:
            parts.append(f'{_word(n)} {one if n == 1 else many}')
    return f'The plan: {_join(parts)}.' if parts else ''


def _evidence(run):
    diagnosis = run.get('diagnosis') or {}
    traffic = (run.get('signals') or {}).get('traffic')
    if diagnosis.get('rule') == 'steady' and traffic:
        return (f"{traffic['visits']} {'person' if traffic['visits'] == 1 else 'people'} visited and "
                f"{traffic['signups']} signed up in the 7 days before it was planned.")
    return diagnosis.get('evidence') or ''


GONE = ('dispatching', 'submitted', 'published')


def _progress(f):
    """The plan's posts by where they are: approved or out, waiting, missed."""
    plan = f['plan']
    done = [x for x in plan if all(st in ('approved',) + GONE for st in x['statuses'])]
    out = [x for x in plan if all(st in GONE for st in x['statuses'])]
    return {'n': len(plan), 'done': len(done), 'out': len(out), 'waiting': f['plan_waiting']}


def _approved_of(k, n):
    return f"{_cap(_word(k))} of {_word(n)} posts {'is' if k == 1 else 'are'} approved"


def _deadline_sentence(f):
    g = _progress(f)
    if g['waiting']:
        first = g['waiting'][0]
        due = f"{day_name(first['run_at'])}'s"
        if not g['done']:
            return f"{due} post goes out at {clock(first['run_at'])} once you approve it."
        return f"{_approved_of(g['done'], g['n'])}; {due} goes out at {clock(first['run_at'])} once you approve it."
    if g['n'] and g['out'] == g['n']:
        return f"All {_word(g['n'])} have gone out."
    if g['n'] and g['done'] == g['n']:
        return f"All {_word(g['n'])} are approved; they go out at their times."
    if g['done']:
        return f"{_approved_of(g['done'], g['n'])}."
    return ''


def _attention_sentences(items):
    out = []
    for item in items:
        if item['kind'] in ('failed', 'uncertain', 'paused', 'missed'):
            out.append(item['title'] + '.')
    return out


def note(f, items=None):
    """Chief's read: the same words on the desk, in Chief's drawer as its first
    message, and read aloud by Listen."""
    items = attention(f) if items is None else items
    latest, current = f['latest'], f['current']
    extra = _attention_sentences(items)
    if f['planning']:
        headline, body, tone = ('Chief is writing the week.',
                                ['It reads the numbers, writes the posts and makes their flyers. '
                                 'This takes a minute or two.'], 'steady')
    elif current and current.get('status') == 'succeeded':
        diagnosis = current.get('diagnosis') or {}
        headline = HEADLINES.get(diagnosis.get('rule'), 'Here is the week.')
        body = [' '.join(s for s in (_evidence(current), _plays_sentence(current.get('plays'))) if s),
                _deadline_sentence(f)] + extra
        urgency = diagnosis.get('urgency')
        soon = f['plan_waiting'] and (_stamp(f['plan_waiting'][0]['run_at']) - f['now']) < SOON
        tone = ('attention' if any(i['tone'] == 'red' for i in items) or urgency == 'high'
                else 'push' if urgency == 'medium' or soon or extra else 'steady')
    elif latest and latest.get('status') in ('failed', 'skipped') and not _week_over(latest, f['now']):
        headline = f"The plan for the week of {week_label(latest['week_of'])} could not be written."
        body = [latest.get('error') or 'Nothing was saved.',
                'Plan it again from the desk, or ask me what went wrong.'] + extra
        tone = 'attention'
    else:
        headline = 'There is no plan for the days ahead yet.'
        body = [f"Next week's plan is written {day_name(f['next_run'])} at {clock(f['next_run'])}. "
                'You can also plan the rest of this week now.'] + extra
        tone = 'push' if extra else 'steady'
    body = [b for b in body if b]
    replies = []
    if current and current.get('status') == 'succeeded':
        replies.append('Walk me through the week')
    if f['plan_waiting']:
        replies.append('Which post is strongest?')
    if any(i['kind'] == 'missed' for i in items):
        replies.append('What should I do with the missed posts?')
    if any(i['kind'] in ('failed', 'uncertain') for i in items):
        replies.append("Why didn't a post go out?")
    if f['published'] or len(replies) < 3:
        replies.append('How did last week do?')
    key = hashlib.sha256(('\n'.join([headline] + body)).encode()).hexdigest()[:16]
    return {'key': key, 'tone': tone, 'kicker': f"CHIEF'S READ · {TONE_KICKER[tone]}", 'headline': headline,
            'body': body, 'quick_replies': replies[:4]}


def masthead(f):
    current, latest = f['current'], f['latest']
    week = (f['which_week'] or 'this week').capitalize()
    kicker = 'GROWTH · MARKETING'
    if current:
        kicker += f" · WEEK OF {week_label(current['week_of']).upper()}"
    if f['planning']:
        return {'kicker': kicker, 'title': 'The week is', 'accent': 'being written.',
                'sub': 'Chief is reading the numbers and drafting the posts and their flyers.'}
    if current and current.get('status') == 'succeeded' and f['plan']:
        plan, g = f['plan'], _progress(f)
        made = _local(current.get('finished_at') or current.get('created_at'))
        when = (f" on {made:%A} {'morning' if made.hour < 12 else 'afternoon' if made.hour < 17 else 'evening'}"
                if made else '')
        channels = _join(f['channels']) or _join(sorted({c for x in plan for c in x['channels']}))
        if g['waiting']:
            first = g['waiting'][0]
            due = f"{day_name(first['run_at'])} {clock(first['run_at'])}"
            if not g['done']:
                return {'kicker': kicker, 'title': f'{week} is', 'accent': 'drafted.',
                        'sub': f"Chief planned {span(plan)}{when}: {_plural(len(plan), 'post')} on {channels}. "
                               f"Approve by {due} and {day_name(first['run_at'])}'s post goes out on time."}
            return {'kicker': kicker, 'title': f'{week} is', 'accent': 'under way.',
                    'sub': f"{_approved_of(g['done'], g['n'])}. {day_name(first['run_at'])}'s still needs your OK "
                           f"by {clock(first['run_at'])}."}
        if g['out'] and g['out'] == g['n']:
            return {'kicker': kicker, 'title': f'{week}', 'accent': 'went out.',
                    'sub': f"All {_word(g['n'])} posts have gone out. Results come in through each post's link."}
        if g['out']:
            return {'kicker': kicker, 'title': f'{week} is', 'accent': 'going out.',
                    'sub': f"{_cap(_word(g['out']))} of {_word(g['n'])} posts have gone out; "
                           'the approved ones go out at their times.'}
        if g['done']:
            return {'kicker': kicker, 'title': f'{week} is', 'accent': 'ready.',
                    'sub': f"{_approved_of(g['done'], g['n'])}. They go out at their times."}
        return {'kicker': kicker, 'title': f'{week}', 'accent': 'needs you.',
                'sub': 'None of its posts can go out as they are. Reschedule the missed ones or plan again.'}
    if latest and latest.get('status') in ('failed', 'skipped') and not _week_over(latest, f['now']):
        return {'kicker': kicker, 'title': 'The week', 'accent': 'needs you.',
                'sub': latest.get('error') or 'The plan could not be written.'}
    return {'kicker': kicker, 'title': 'No plan', 'accent': 'yet.',
            'sub': f"Next week's plan is written {day_name(f['next_run'])} at {clock(f['next_run'])}. "
                   'You can plan the rest of this week now.'}


def desk(state):
    """Everything the desk's This week view reads beyond the plan itself."""
    f = facts(state)
    items = attention(f)
    first = f['plan_waiting'][0]['run_at'] if f['plan_waiting'] else (
        f['waiting'][0]['run_at'] if f['waiting'] else None)
    return {'note': note(f, items), 'masthead': masthead(f), 'attention': [_public(i) for i in items],
            'deadline': first}


def _public(item):
    return {**item, 'slots': [{k: s[k] for k in ('key', 'run_at', 'channels', 'text', 'items')}
                              for s in item['slots']]}


# ── Today ─────────────────────────────────────────────────────────────

ACTION = {'failed': 'See what happened', 'uncertain': 'Check it', 'paused': 'Resume publishing',
          'missed': 'Reschedule or let go', 'plan_failed': 'Plan it now', 'quiet': 'Plan the week'}


def today_items(state):
    """Today's queue items for marketing. The desk is where each is dealt with."""
    f = facts(state)
    out = []
    if f['waiting']:
        n = len(f['waiting'])
        first = f['waiting'][0]
        whole_plan = f['plan_waiting'] and len(f['plan_waiting']) == len(f['plan']) == n
        title = (f"Chief drafted {f['which_week']}. {_cap(_plural(n, 'post'))} wait for your OK"
                 if whole_plan else f"{_cap(_plural(n, 'post'))} {'waits' if n == 1 else 'wait'} for your OK")
        due = _stamp(first['run_at']) - f['now']
        out.append({
            'id': f"marketing:waiting:{(f['current'] or {}).get('id') or 'posts'}", 'kind': 'posts',
            'source': 'Marketing', 'title': title,
            'detail': f"{day_name(first['run_at'])}'s goes out at {clock(first['run_at'])} if you approve it by then. "
                      'Nothing publishes as The Solutionist System until you have read it.',
            'lanes': ['people'], 'room': 'growth', 'tone': 'amber' if due < SOON else 'blue', 'seen': 1,
            'count': n, 'action': {'label': 'Review the week', 'nav': 'platform-growth'},
            'secondary': {'label': 'Ask Chief',
                          'chief': "Walk me through the marketing plan waiting for my approval: what it pushes, "
                                   "why, and which post is strongest. Use the plan's own numbers."}})
    for item in attention(f):
        out.append({
            'id': item['id'], 'kind': 'marketing', 'source': 'Marketing', 'title': item['title'],
            'detail': item['detail'],
            'lanes': ['systems'] if item['kind'] == 'plan_failed' else ['people'], 'room': 'growth',
            'tone': item['tone'], 'seen': 1, 'count': len(item['slots']) or None,
            'action': {'label': ACTION[item['kind']], 'nav': 'platform-growth'}})
    return out


# ── Chief ─────────────────────────────────────────────────────────────

DIGEST_PROMPT = '''
MARKETING (snapshot.marketing): Solutionist's own weekly marketing, run from Mission Control → Growth →
Marketing. Next week's plan is written every Thursday at 7:00 AM ET and saved as drafts; nothing publishes
until Kevin approves it there. When Kevin asks what needs him, or how the business is doing, include what
marketing is waiting on (posts waiting with the time the first one goes out, missed or failed posts, a plan
that could not be written) from needs_owner, in plain words. Never say a post was approved or published
unless the digest says so, and never approve for him: approving happens on the desk.
'''


def chief_digest(state):
    f = facts(state)
    items = attention(f)
    current = f['current']
    return {
        'where': 'Mission Control → Growth → Marketing',
        'plan': None if not current else {
            'week_of': current['week_of'], 'which_week': f['which_week'], 'status': current.get('status'),
            'evidence': (current.get('diagnosis') or {}).get('evidence'),
            'plays': [f"{p.get('label')} × {p.get('posts')}" for p in current.get('plays') or []]},
        'planning_now': f['planning'],
        'posts_waiting_for_approval': len(f['waiting']),
        'first_waiting_goes_out': (f"{day_name(f['waiting'][0]['run_at'])} {clock(f['waiting'][0]['run_at'])}"
                                   if f['waiting'] else None),
        'approved_upcoming': len(f['approved']),
        'publishing_paused': f['paused'],
        'needs_owner': ([i['title'] for i in today_items(state) if i['kind'] == 'posts']
                        + [f"{i['title']}: {i['detail']}" for i in items]),
        'read': note(f, items)['body'],
        'next_plan': f"{day_name(f['next_run'])} {clock(f['next_run'])}",
        'posts_readable': f['readable'],
    }


async def digest():
    return chief_digest(await read_state())


# ── the phone ─────────────────────────────────────────────────────────

async def _owner_id():
    import httpx
    import platform_watchdog as watchdog
    async with httpx.AsyncClient(timeout=10) as client:
        return await watchdog._owner_user_id(client, watchdog._service_headers())


async def push(title, body, tag):
    import push_notifications
    owner = await _owner_id()
    if not owner:
        return 0
    return await asyncio.to_thread(push_notifications.send_to_user, owner, title=title, body=body[:180],
                                   nav=NAV, tag=tag)


async def tell_owner_about_plan(what, run_id, reason=None):
    """After a scheduled plan: the drafts are ready (with the deadline), or why not."""
    if what == 'succeeded':
        f = facts(await read_state())
        waiting = [s for s in f['plan_waiting']] if f['current'] and str(f['current']['id']) == str(run_id) else []
        if not waiting:
            return 0
        first = waiting[0]
        return await push(f"Chief drafted {f['which_week'] or 'the week'}",
                          f"{_cap(_plural(len(waiting), 'post'))} {'is' if len(waiting) == 1 else 'are'} ready for "
                          f"your review. {day_name(first['run_at'])}'s needs your OK by {clock(first['run_at'])}.",
                          'marketing-week')
    return await push("The marketing plan couldn't be written",
                      f"{reason or 'Nothing was saved.'} Details in Mission Control.", 'marketing-week')


async def tell_owner_about_delivery(rows):
    """After a delivery tick: one push for whatever did not go out."""
    first = rows[0]
    where = SERVICE.get((first.get('payload') or {}).get('service'), 'a channel')
    title = "A post didn't go out" if len(rows) == 1 else f"{len(rows)} posts didn't go out"
    return await push(title, f"{where}: {first.get('error') or 'Buffer did not accept it.'}", 'marketing-delivery')

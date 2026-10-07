"""business_marketing_desk.py — where one business's marketing stands, said plainly.

The marketing suite's desk for every business (B4 of
docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md). It reads the business's own
rows (marketing_desks, marketing_runs, marketing_posts) and says where things
stand, the way marketing_desk.py does for Solutionist's own desk:

  the desk     Chief's read (note), the masthead, and what needs a look
  Today        one item per thing waiting on the owner (today_items)
  Chief        a digest of what marketing is waiting on (chief_digest)

All of it is arithmetic over rows. No model call, so the desk can read it on
every load, and every sentence carries a counted number or a row's own words.
The small wording helpers (day names, clock times, plurals) are
marketing_desk's, on the business's own clock: its time zone is passed in as
`tz` (business_marketing.business_tz resolves it).

Where it differs from the platform desk, on purpose:
  * A post here is one row: one caption for every account in its targets.
    The platform keeps one row per channel and groups them into an idea;
    here a row IS the idea, so a slot carries exactly one item.
  * The words name the business's own accounts. Where the platform says
    "Buffer", this says "your accounts" or "the posting service".
  * Nothing promises a weekly plan. The business planner is not built yet
    (B8/B9), so a sentence about the next plan appears only when the caller
    passes next_run.
  * Nothing pushes. Telling the owner by phone comes with sending (B5).

A source that cannot be read is never "nothing there". With strict=True
(the API) read_state raises and the desk answers 503. With strict=False (a
Today card, Chief's digest) the source is None and nothing is said about it,
so a storage blip never reads as "nothing to do".
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import business_marketing_store as store
import marketing_desk as words
from marketing_desk import _approved_of, _cap, _join, _plural, _stamp, _word, clock, day_name, span, week_label
from social_publish_router import post_for_me_label

LOOKBACK = timedelta(days=21)
MISSED_WINDOW = timedelta(days=14)       # a draft whose time passed longer ago is history, not a to-do
FAILED_WINDOW = timedelta(days=14)
SOON = timedelta(hours=24)
QUIET_AHEAD = timedelta(days=7)
POSTS_LIMIT = 400
RUNS_LIMIT = 3
NAV = 'grow:marketing'
CONNECT_NAV = 'build:social-media'
WHERE = 'Grow → Marketing'
GONE = ('dispatching', 'submitted', 'published', 'partly_published')

POST_COLUMNS = ('id,business_id,revision,status,source,play_id,run_id,caption,publish_text,landing_url,'
                'link_code,media,targets,opening,design_status,content_hash,approved_at,approved_via,'
                'run_at,expires_at,error,external_urls,created_at,updated_at')
RUN_COLUMNS = 'id,week_of,kind,trigger,status,attempts,diagnosis,plays,post_ids,error,created_at,finished_at'
PUBLIC_POST = ('id', 'business_id', 'revision', 'content_hash', 'status', 'source', 'play_id', 'run_id',
               'caption', 'publish_text', 'landing_url', 'link_code', 'media', 'opening', 'design_status',
               'run_at', 'expires_at', 'approved_at', 'approved_via', 'error', 'external_urls',
               'created_at', 'updated_at')


# ── small words ───────────────────────────────────────────────────────

def query_time(d: datetime) -> str:
    """An instant for a PostgREST query string: UTC to the second, written
    with Z. A '+' would read as a space there, so any that ever appears is
    sent as %2B."""
    return words._z(d).replace('+', '%2B')


def relation(week_of: Any, now: datetime, tz) -> Optional[str]:
    """'this week' or 'next week' for a planned week, on the business's clock."""
    if not week_of:
        return None
    local = now.astimezone(tz)
    monday = local.date() - timedelta(days=local.weekday())
    week = week_of if isinstance(week_of, date) else date.fromisoformat(str(week_of)[:10])
    return 'next week' if week > monday else 'this week' if week == monday else 'an earlier week'


def channels_of(post: Dict[str, Any]) -> List[str]:
    """The accounts a post goes to, by network name, in its own order."""
    names = (post_for_me_label(str(t.get('platform') or '')) for t in post.get('targets') or [])
    return [n for n in dict.fromkeys(names) if n]


def public_post(row: Dict[str, Any]) -> Dict[str, Any]:
    """A post as the desk shows it. The accounts are named by connection,
    network and handle; the posting service's own account ids stay here."""
    out = {k: row.get(k) for k in PUBLIC_POST if k in row}
    out['targets'] = [{'connection_id': t.get('connection_id'), 'platform': t.get('platform'),
                       'label': post_for_me_label(str(t.get('platform') or '')), 'username': t.get('username')}
                      for t in row.get('targets') or []]
    out['accounts'] = channels_of(row)
    return out


# ── reading ───────────────────────────────────────────────────────────

async def read_state(business_id: Any, *, tz, now: Optional[datetime] = None,
                     connections: Optional[List[Dict[str, Any]]] = None,
                     next_run: Optional[str] = None, strict: bool = True) -> Dict[str, Any]:
    """The rows everything below is computed from.

    strict: a source that cannot be read raises StoreError. Otherwise it is
    None and named in `unreadable`. The desk row is {} when the business has
    none yet (a desk with its defaults), never when it could not be read.
    `connections` are the business's connected accounts as the caller read
    them (None: not read)."""
    now = now or datetime.now(timezone.utc)
    biz = str(UUID(str(business_id)))
    since = query_time(now - LOOKBACK)
    sources = {
        'runs': store.rows(f'/marketing_runs?business_id=eq.{biz}&select={RUN_COLUMNS}'
                           f'&order=week_of.desc&limit={RUNS_LIMIT}'),
        'posts': store.rows(f'/marketing_posts?business_id=eq.{biz}&select={POST_COLUMNS}'
                            f'&or=(run_at.gte.{since},status.eq.uncertain)&status=neq.cancelled'
                            f'&order=run_at.asc&limit={POSTS_LIMIT}'),
        'desk': store.get_desk(biz),
    }
    results = await asyncio.gather(*sources.values(), return_exceptions=True)
    got, unreadable = {}, []
    for name, result in zip(sources, results):
        if isinstance(result, BaseException):
            if strict or not isinstance(result, store.StoreError):
                raise result
            unreadable.append(name)
            got[name] = None
        else:
            got[name] = result
    desk = got['desk'] if got['desk'] is not None else ({} if 'desk' not in unreadable else None)
    return {'business_id': biz, 'now': now, 'tz': tz, 'runs': got['runs'], 'posts': got['posts'],
            'desk': desk, 'connections': connections, 'next_run': next_run, 'unreadable': unreadable}


def slots(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Posts in posting order, in the platform desk's slot shape: one item
    each, since a row here is a whole idea."""
    out = []
    for p in sorted(posts, key=lambda p: (str(p['run_at']), str(p['id']))):
        out.append({'key': str(p['id']), 'run_at': p['run_at'], 'play_id': p.get('play_id'),
                    'source': p.get('source'), 'text': p.get('caption') or '', 'channels': channels_of(p),
                    'items': [{'id': str(p['id']), 'revision': p.get('revision')}],
                    'statuses': [p.get('status')]})
    return out


def facts(state: Dict[str, Any]) -> Dict[str, Any]:
    """Counted things, in one place, for every sentence below."""
    import marketing_engine as engine
    now, tz = state['now'], state['tz']
    posts = state['posts'] or []
    runs = state['runs'] or []
    latest = runs[0] if runs else None
    current = latest if latest and not words._week_over(latest, now, tz) else None

    def at(p):
        return _stamp(p['run_at']) or now
    drafts = [p for p in posts if p['status'] == 'draft']
    waiting = [p for p in drafts if at(p) > now]
    plan_posts = [p for p in posts if current and str(p.get('run_id')) == str(current['id'])]
    plan_waiting = [p for p in plan_posts if p in waiting]
    recent = now - FAILED_WINDOW
    failed_rows = [p for p in posts if p['status'] == 'failed' and at(p) >= recent]
    partly_rows = [p for p in posts if p['status'] == 'partly_published' and at(p) >= recent]
    approved = [p for p in posts if p['status'] == 'approved' and at(p) > now]
    desk = state['desk']
    connections = state.get('connections')
    return {
        'now': now, 'tz': tz, 'latest': latest, 'current': current,
        'planning': engine.is_planning(latest, now),
        'which_week': relation(current['week_of'], now, tz) if current else None,
        'readable': state['posts'] is not None,
        'waiting': slots(waiting),
        'plan': slots(plan_posts),
        'plan_waiting': slots(plan_waiting),
        'missed': slots([p for p in drafts if now - MISSED_WINDOW <= at(p) <= now]),
        'failed': slots(failed_rows), 'failed_rows': failed_rows,
        'partly': slots(partly_rows), 'partly_rows': partly_rows,
        'uncertain': slots([p for p in posts if p['status'] == 'uncertain']),
        'approved': slots(approved),
        'going': slots([p for p in posts if p['status'] in ('dispatching', 'submitted')]),
        'published': slots([p for p in posts if p['status'] in ('published', 'partly_published')]),
        'soon': [p for p in waiting + approved if at(p) <= now + QUIET_AHEAD],
        'paused': None if desk is None else bool(desk.get('paused')),
        'connections_readable': connections is not None,
        'channels': list(dict.fromkeys(post_for_me_label(str(c.get('platform') or ''))
                                       for c in connections or [])),
        'next_run': state.get('next_run'),
    }


# ── what needs a look ─────────────────────────────────────────────────

def _next_plan_sentence(f) -> str:
    if not f['next_run']:
        return ''
    return f"Next week's plan is written {day_name(f['next_run'], f['tz'])} at {clock(f['next_run'], f['tz'])}."


def _it_them(n, one, many):
    return one if n == 1 else many


def attention(f: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The desk's "Needs a look", in the order to deal with it. Each carries
    the posts it is about, with the ids and revisions an action needs."""
    now, tz, items = f['now'], f['tz'], []
    if f['failed']:
        rows = f['failed_rows']
        first = rows[0]
        n = len(rows)
        where = _join(channels_of(first)) or 'your accounts'
        items.append({'id': 'marketing:failed', 'kind': 'failed', 'tone': 'red',
                      'title': f"A post didn't go out on {where}" if n == 1 else f"{_cap(_plural(n, 'post'))} didn't go out",
                      'detail': (first.get('error') or 'The posting service did not accept it.')[:220],
                      'slots': f['failed']})
    if f['partly']:
        first = f['partly_rows'][0]
        n = len(f['partly'])
        items.append({'id': 'marketing:partly', 'kind': 'partly', 'tone': 'amber',
                      'title': (f"A post went out on only some of {_join(channels_of(first)) or 'its accounts'}" if n == 1
                                else f"{_cap(_plural(n, 'post'))} went out on only some accounts"),
                      'detail': (first.get('error') or 'Some accounts did not take it. Open the post to see which.')[:220],
                      'slots': f['partly']})
    if f['uncertain']:
        n = len(f['uncertain'])
        items.append({'id': 'marketing:uncertain', 'kind': 'uncertain', 'tone': 'amber',
                      'title': f"{_cap(_plural(n, 'post'))} may or may not have gone out",
                      'detail': ('Sending was interrupted. Check your accounts; if '
                                 f"{_it_them(n, 'it is', 'one is')} not there, mark "
                                 f"{_it_them(n, 'it', 'that one')} not sent and give it a new time."),
                      'slots': f['uncertain']})
    if f['paused'] and (f['approved'] or f['waiting']):
        k = len(f['approved'])
        items.append({'id': 'marketing:paused', 'kind': 'paused', 'tone': 'amber',
                      'title': 'Posting is paused',
                      'detail': (f"{_cap(_plural(k, 'approved post'))} will not go out until you resume it." if k
                                 else 'Nothing you approve will go out until you resume it.'),
                      'slots': f['approved']})
    if f['missed']:
        n = len(f['missed'])
        items.append({'id': 'marketing:missed', 'kind': 'missed', 'tone': 'amber',
                      'title': f"{_cap(_plural(n, 'post'))} from {words._missed_when(f['missed'], now, tz)} missed "
                               f"{'its' if n == 1 else 'their'} time",
                      'detail': f"{'It was' if n == 1 else 'They were'} never approved, so "
                                f"{'it' if n == 1 else 'they'} never went out. Reschedule or let "
                                f"{'it' if n == 1 else 'them'} go.",
                      'slots': f['missed']})
    latest = f['latest']
    if (latest and not f['planning'] and latest.get('status') in ('failed', 'skipped')
            and not words._week_over(latest, now, tz)):
        items.append({'id': f"marketing:plan:{latest['id']}", 'kind': 'plan_failed', 'tone': 'amber',
                      'title': f"The plan for the week of {week_label(latest['week_of'])} could not be written",
                      'detail': (latest.get('error') or 'Nothing was saved.')[:220], 'slots': []})
    if f['connections_readable'] and not f['channels']:
        items.append({'id': 'marketing:connect', 'kind': 'connect', 'tone': 'gold',
                      'title': 'No accounts are connected yet',
                      'detail': 'Connect Instagram, Facebook or another account in Build, Social Media, '
                                'and posts can go out from here.',
                      'slots': []})
    quiet = (f['readable'] and not f['planning'] and not f['soon'] and not f['going'] and f['channels']
             and not any(i['kind'] == 'plan_failed' for i in items))
    if quiet:
        items.append({'id': 'marketing:quiet', 'kind': 'quiet', 'tone': 'gold',
                      'title': 'Nothing is going out in the next 7 days',
                      'detail': ' '.join(s for s in ('Write a post and it takes the next open time, '
                                                     'or ask Chief to draft one.', _next_plan_sentence(f)) if s),
                      'slots': []})
    return items


# ── Chief's read and the masthead ─────────────────────────────────────

def _progress(f):
    """The plan's posts by where they are: approved or out, waiting."""
    plan = f['plan']
    done = [x for x in plan if all(st in ('approved',) + GONE for st in x['statuses'])]
    out = [x for x in plan if all(st in GONE for st in x['statuses'])]
    return {'n': len(plan), 'done': len(done), 'out': len(out), 'waiting': f['plan_waiting']}


def _deadline_sentence(f):
    g, tz = _progress(f), f['tz']
    if g['waiting']:
        first = g['waiting'][0]
        due = f"{day_name(first['run_at'], tz)}'s"
        if not g['done']:
            return f"{due} post goes out at {clock(first['run_at'], tz)} once you approve it."
        return f"{_approved_of(g['done'], g['n'])}; {due} goes out at {clock(first['run_at'], tz)} once you approve it."
    if g['n'] and g['out'] == g['n']:
        return f"All {_word(g['n'])} have gone out."
    if g['n'] and g['done'] == g['n']:
        return f"All {_word(g['n'])} are approved; they go out at their times."
    if g['done']:
        return f"{_approved_of(g['done'], g['n'])}."
    return ''


PROBLEMS = ('failed', 'partly', 'uncertain', 'paused', 'missed')


def note(f: Dict[str, Any], items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Chief's read: the same words on the desk, in Chief's drawer as its first
    message, and read aloud by Listen."""
    items = attention(f) if items is None else items
    tz, now = f['tz'], f['now']
    latest, current = f['latest'], f['current']
    extra = [i['title'] + '.' for i in items if i['kind'] in PROBLEMS]
    red = any(i['tone'] == 'red' for i in items)
    if not f['readable']:
        headline = "The posts couldn't be read just now."
        body, tone = ['That is not the same as nothing waiting. Try again in a minute.'], 'push'
    elif f['planning']:
        headline, body, tone = ('Chief is writing the week.',
                                ['It reads your numbers and writes the posts. This takes a minute or two.'], 'steady')
    elif current and current.get('status') == 'succeeded':
        diagnosis = current.get('diagnosis') or {}
        headline = diagnosis.get('headline') or 'Here is the week.'
        body = [diagnosis.get('evidence') or '', _deadline_sentence(f)] + extra
        urgency = diagnosis.get('urgency')
        soon = f['plan_waiting'] and (_stamp(f['plan_waiting'][0]['run_at']) - now) < SOON
        tone = ('attention' if red or urgency == 'high'
                else 'push' if urgency == 'medium' or soon or extra else 'steady')
    elif latest and latest.get('status') in ('failed', 'skipped') and not words._week_over(latest, now, tz):
        headline = f"The plan for the week of {week_label(latest['week_of'])} could not be written."
        body = [latest.get('error') or 'Nothing was saved.',
                'Ask me what went wrong, or write a post yourself.'] + extra
        tone = 'attention'
    elif f['waiting']:
        n, first = len(f['waiting']), f['waiting'][0]
        headline = f"{_cap(_plural(n, 'post'))} {'waits' if n == 1 else 'wait'} for your OK."
        body = [f"{day_name(first['run_at'], tz)}'s goes out at {clock(first['run_at'], tz)} once you approve it."] + extra
        soon = (_stamp(first['run_at']) - now) < SOON
        tone = 'attention' if red else 'push' if soon or extra else 'steady'
    elif f['approved']:
        n, first = len(f['approved']), f['approved'][0]
        headline = f"{_cap(_plural(n, 'post'))} {'is' if n == 1 else 'are'} ready to go out."
        body = [f"The next goes out {day_name(first['run_at'], tz)} at {clock(first['run_at'], tz)}."] + extra
        tone = 'attention' if red else 'push' if extra else 'steady'
    else:
        headline = 'Nothing is lined up to go out yet.'
        body = ['Write a post and it takes the next open time, or ask me to draft one.',
                _next_plan_sentence(f)] + extra
        tone = 'attention' if red else 'push' if extra else 'steady'
    body = [b for b in body if b]
    replies = []
    if current and current.get('status') == 'succeeded':
        replies.append('Walk me through the week')
    if f['waiting']:
        replies.append('Which post is strongest?')
    if any(i['kind'] == 'missed' for i in items):
        replies.append('What should I do with the missed posts?')
    if any(i['kind'] in ('failed', 'partly', 'uncertain') for i in items):
        replies.append("Why didn't a post go out?")
    if f['readable'] and not f['waiting'] and not f['approved']:
        replies.append('Write a post for this week')
    if f['published'] or len(replies) < 3:
        replies.append('How did last week do?')
    key = hashlib.sha256(('\n'.join([headline] + body)).encode()).hexdigest()[:16]
    return {'key': key, 'tone': tone, 'kicker': f"CHIEF'S READ · {words.TONE_KICKER[tone]}", 'headline': headline,
            'body': body, 'quick_replies': replies[:4]}


def masthead(f: Dict[str, Any]) -> Dict[str, Any]:
    tz = f['tz']
    current, latest = f['current'], f['latest']
    week = (f['which_week'] or 'this week').capitalize()
    kicker = 'GROW · MARKETING'
    if current:
        kicker += f" · WEEK OF {week_label(current['week_of']).upper()}"
    if f['planning']:
        return {'kicker': kicker, 'title': 'The week is', 'accent': 'being written.',
                'sub': 'Chief is reading your numbers and drafting the posts.'}
    if current and current.get('status') == 'succeeded' and f['plan']:
        plan, g = f['plan'], _progress(f)
        made = words._local(current.get('finished_at') or current.get('created_at'), tz)
        when = (f" on {made:%A} {'morning' if made.hour < 12 else 'afternoon' if made.hour < 17 else 'evening'}"
                if made else '')
        channels = _join(sorted({c for x in plan for c in x['channels']})) or 'your accounts'
        if g['waiting']:
            first = g['waiting'][0]
            due = f"{day_name(first['run_at'], tz)} {clock(first['run_at'], tz)}"
            if not g['done']:
                return {'kicker': kicker, 'title': f'{week} is', 'accent': 'drafted.',
                        'sub': f"Chief planned {span(plan, tz)}{when}: {_plural(len(plan), 'post')} on {channels}. "
                               f"Approve by {due} and {day_name(first['run_at'], tz)}'s post goes out on time."}
            return {'kicker': kicker, 'title': f'{week} is', 'accent': 'under way.',
                    'sub': f"{_approved_of(g['done'], g['n'])}. {day_name(first['run_at'], tz)}'s still needs "
                           f"your OK by {clock(first['run_at'], tz)}."}
        if g['out'] and g['out'] == g['n']:
            return {'kicker': kicker, 'title': f'{week}', 'accent': 'went out.',
                    'sub': f"All {_word(g['n'])} posts have gone out."}
        if g['out']:
            return {'kicker': kicker, 'title': f'{week} is', 'accent': 'going out.',
                    'sub': f"{_cap(_word(g['out']))} of {_word(g['n'])} posts have gone out; "
                           'the approved ones go out at their times.'}
        if g['done']:
            return {'kicker': kicker, 'title': f'{week} is', 'accent': 'ready.',
                    'sub': f"{_approved_of(g['done'], g['n'])}. They go out at their times."}
        return {'kicker': kicker, 'title': f'{week}', 'accent': 'needs you.',
                'sub': 'None of its posts can go out as they are. Reschedule the missed ones.'}
    if latest and latest.get('status') in ('failed', 'skipped') and not words._week_over(latest, f['now'], tz):
        return {'kicker': kicker, 'title': 'The week', 'accent': 'needs you.',
                'sub': latest.get('error') or 'The plan could not be written.'}
    if f['waiting']:
        n, first = len(f['waiting']), f['waiting'][0]
        return {'kicker': kicker, 'title': _cap(_plural(n, 'post')), 'accent': 'needs your OK.' if n == 1 else 'need your OK.',
                'sub': f"Approve by {day_name(first['run_at'], tz)} {clock(first['run_at'], tz)} and "
                       f"{day_name(first['run_at'], tz)}'s post goes out on time."}
    if f['approved']:
        n, first = len(f['approved']), f['approved'][0]
        return {'kicker': kicker, 'title': 'Ready', 'accent': 'to go out.',
                'sub': f"{_cap(_plural(n, 'post'))} {'is' if n == 1 else 'are'} approved. The next goes out "
                       f"{day_name(first['run_at'], tz)} at {clock(first['run_at'], tz)}."}
    if f['going']:
        return {'kicker': kicker, 'title': 'Posts are', 'accent': 'going out.',
                'sub': f"{_cap(_plural(len(f['going']), 'post'))} {'is' if len(f['going']) == 1 else 'are'} on the way."}
    return {'kicker': kicker, 'title': 'Nothing', 'accent': 'lined up yet.',
            'sub': ' '.join(s for s in ('Write a post and it takes the next open time.', _next_plan_sentence(f)) if s)}


def desk(state: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the desk's This week view reads beyond the posts themselves."""
    f = facts(state)
    items = attention(f)
    first = f['plan_waiting'][0]['run_at'] if f['plan_waiting'] else (
        f['waiting'][0]['run_at'] if f['waiting'] else None)
    return {'note': note(f, items), 'masthead': masthead(f), 'attention': [words._public(i) for i in items],
            'deadline': first}


def weeks(state: Dict[str, Any]) -> Dict[str, Any]:
    """This week's and next week's posts (Monday to Sunday on the business's
    clock), in posting order. Cancelled posts are not read."""
    now, tz = state['now'], state['tz']
    local = now.astimezone(tz)
    monday = local.date() - timedelta(days=local.weekday())
    out = {}
    for name, start in (('this_week', monday), ('next_week', monday + timedelta(days=7))):
        posts = [p for p in state['posts'] or []
                 if start <= (words._local(p['run_at'], tz) or local).date() < start + timedelta(days=7)]
        out[name] = {'week_of': start.isoformat(),
                     'posts': [public_post(p) for p in sorted(posts, key=lambda p: (str(p['run_at']), str(p['id'])))]}
    return out


# ── Today ─────────────────────────────────────────────────────────────

ACTION = {'failed': 'See what happened', 'partly': 'See which accounts', 'uncertain': 'Check it',
          'paused': 'Resume posting', 'missed': 'Reschedule or let go', 'plan_failed': 'See why',
          'quiet': 'Write a post', 'connect': 'Connect an account'}


def today_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Today's queue items for this business's marketing. The desk is where
    each is dealt with; nothing here approves or sends."""
    f = facts(state)
    tz, biz = f['tz'], state['business_id']
    out = []
    if f['waiting']:
        n = len(f['waiting'])
        first = f['waiting'][0]
        whole_plan = f['plan_waiting'] and len(f['plan_waiting']) == len(f['plan']) == n
        title = (f"Chief drafted {f['which_week']}. {_cap(_plural(n, 'post'))} wait for your OK"
                 if whole_plan else f"{_cap(_plural(n, 'post'))} {'waits' if n == 1 else 'wait'} for your OK")
        due = _stamp(first['run_at']) - f['now']
        out.append({
            'id': f'marketing:{biz}:waiting', 'kind': 'posts', 'source': 'Marketing', 'title': title,
            'detail': f"{day_name(first['run_at'], tz)}'s goes out at {clock(first['run_at'], tz)} if you approve "
                      'it by then. Nothing posts until you have read it.',
            'lanes': ['people'], 'room': 'grow', 'tone': 'amber' if due < SOON else 'blue', 'seen': 1,
            'count': n, 'action': {'label': 'Review the posts', 'nav': NAV},
            'secondary': {'label': 'Ask Chief',
                          'chief': 'Walk me through the marketing posts waiting for my OK: what each one says, '
                                   'where it goes and when, and which is strongest.'}})
    for item in attention(f):
        out.append({
            'id': f"marketing:{biz}:{item['kind']}", 'kind': 'marketing', 'source': 'Marketing',
            'title': item['title'], 'detail': item['detail'],
            'lanes': ['systems'] if item['kind'] in ('plan_failed', 'connect') else ['people'], 'room': 'grow',
            'tone': item['tone'], 'seen': 1, 'count': len(item['slots']) or None,
            'action': {'label': ACTION[item['kind']], 'nav': CONNECT_NAV if item['kind'] == 'connect' else NAV}})
    return out


# ── Chief ─────────────────────────────────────────────────────────────

DIGEST_PROMPT = '''
MARKETING (snapshot.marketing): this business's marketing desk, in Grow → Marketing. Nothing posts until the
owner approves it there. When the owner asks what needs them, or how the business is doing, include what
marketing is waiting on (posts waiting with the time the first one goes out, missed or failed posts) from
needs_owner, in plain words. Never say a post was approved or published unless the digest says so, and never
approve for the owner: approving happens on the desk.
'''


def chief_digest(state: Dict[str, Any]) -> Dict[str, Any]:
    f = facts(state)
    items = attention(f)
    current, tz = f['current'], f['tz']
    read = note(f, items)
    return {
        'where': WHERE,
        'time_zone': getattr(tz, 'key', str(tz)),
        'plan': None if not current else {
            'week_of': current['week_of'], 'which_week': f['which_week'], 'status': current.get('status'),
            'evidence': (current.get('diagnosis') or {}).get('evidence')},
        'planning_now': f['planning'],
        'posts_waiting_for_approval': len(f['waiting']),
        'first_waiting_goes_out': (f"{day_name(f['waiting'][0]['run_at'], tz)} {clock(f['waiting'][0]['run_at'], tz)}"
                                   if f['waiting'] else None),
        'approved_upcoming': len(f['approved']),
        'posting_paused': f['paused'],
        'accounts': f['channels'] if f['connections_readable'] else None,
        'needs_owner': ([i['title'] for i in today_items(state) if i['kind'] == 'posts']
                        + [f"{i['title']}: {i['detail']}" for i in items]),
        'headline': read['headline'],
        'read': read['body'],
        'next_plan': (f"{day_name(f['next_run'], tz)} {clock(f['next_run'], tz)}" if f['next_run'] else None),
        'posts_readable': f['readable'],
    }


async def digest(business_id: Any, tz, connections: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Chief's digest for one business. A source that cannot be read is said
    to be unreadable, never empty."""
    return chief_digest(await read_state(business_id, tz=tz, connections=connections, strict=False))

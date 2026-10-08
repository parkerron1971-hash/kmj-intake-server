"""platform_chief_suite.py — with the suite on, Platform Chief, MC Today and
the Chief digest work Solutionist's own suite desk (B15b).

B15 (platform_suite, platform_marketing_suite) moved Mission Control's
Marketing desk onto the marketing suite behind MC_MARKETING_SUITE, and left
three things on the Buffer desk: Platform Chief's marketing verbs (they
refused anything new), MC Today and the Mission Control Chief digest. This
module moves them, and keys every decision on platform_suite's one
predicate: the suite is ACTIVE when the switch is on AND PLATFORM_BUSINESS_ID
names a validated platform business (`active()`).

SWITCH OFF: nothing here is reached. `handlers()` and `card_handlers()` are
empty, and every call site (platform_console, platform_today,
platform_chief_authority.propose) takes today's Buffer path without a read.
Switch on but not active (the id unset, invalid or unconfirmed): the shared
verbs, Today and the digest stay on the Buffer desk exactly as B15 left them;
the suite-only verbs refuse in platform_suite's own sentence.

PLATFORM CHIEF'S VERBS (suite active). Each calls B10's own handler
(chief_marketing_actions), which calls the desk's own functions
(business_marketing, business_marketing_planner): no second write path.

  verb                 group (platform_chief_authority)    B10 handler
  marketing_desk       read                                handle_marketing_desk
  marketing_new_post   drafts (as on the Buffer desk)      handle_marketing_new_post (source 'chief')
  marketing_edit_post  drafts                              handle_marketing_edit_post
  marketing_skip_post  marketing_stop                      handle_marketing_skip_post
  marketing_replan     review: always a card (class C)     handle_marketing_replan
  marketing_post_now   review: always a card (class C)     handle_marketing_post_now

WHICH BUSINESS. Always the validated platform business (platform_suite),
read as the service role and checked against the signed-in platform owner
(platform_marketing_suite._platform_row), never an id from the model's tag:
a tag naming another business is refused before anything is read. B10's
owner check then runs as well (the turn's user is the platform owner).

CLASS C. B10 posts now and plans again only on the owner's yes in the turn.
Platform Chief's yes is the owner's approval on the action's card (model
output is never consent there): post-now and replan are `review` (a card
every time), and their handlers refuse, before anything is read, unless they
run from a card the owner approved (current_authorization, automatic False).
B10's own `_unattended` gate is set from that, never from the tag.

NO APPROVE VERB. The owner approves on the desk; the only other approval is
B13's standing OK, which Chief's planner applies itself.

THE BUFFER DESK DRAINS. marketing_save_draft (an edit), marketing_edit_slot,
marketing_skip_slot, marketing_cancel_post and marketing_pause still manage
posts already there; nothing new goes to Buffer (B15).

MC TODAY AND THE DIGEST read the suite desk for the platform business
(business_marketing_desk: what waits for Kevin's OK, failures and unconfirmed
sends, missed posts) plus what Chief approved on the standing OK and pulled
posts, and keep the Buffer desk's leftovers that need a hand while it drains.
A read that fails says "couldn't read", never nothing.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException

import platform_suite

log = logging.getLogger(__name__)

SUITE_ONLY = ('marketing_desk', 'marketing_edit_post', 'marketing_skip_post', 'marketing_replan')
SHARED = ('marketing_new_post', 'marketing_post_now')
CLASS_C = ('marketing_post_now', 'marketing_replan')
NAV = 'platform-growth'
WHERE_MC = 'Mission Control → Growth → Marketing'
PULLED_WINDOW = timedelta(days=7)

NOTHING = {'marketing_desk': 'nothing was read', 'marketing_new_post': 'nothing was saved',
           'marketing_edit_post': 'nothing was changed', 'marketing_skip_post': 'nothing was changed',
           'marketing_replan': 'nothing was queued', 'marketing_post_now': 'nothing was posted'}
NOT_CARD = {
    'marketing_post_now': ('Posting right away needs your approval on its card, so nothing was posted.',
                           'Needs your OK on its card'),
    'marketing_replan': ('Planning the week again needs your approval on its card, so nothing was queued.',
                         'Needs your OK on its card'),
}
OTHER_BUSINESS = ("Platform Chief works only Solutionist's own marketing desk, and that names another "
                  'business, so {nothing}.')
CHANGED_SINCE_CARD = ("That post changed after its card was made, so nothing was posted. Ask me again and I'll "
                      'make a fresh card from the desk as it is now.')
SUITE_NOTE = ("Solutionist's marketing runs on the marketing suite desk: the same desk every business has, for "
              "Solutionist's own business, posting through its own connected accounts. The Buffer desk is "
              'draining: posts approved there before the switch still go out; nothing new goes there.')
UNREAD_TITLE = "Solutionist's marketing desk couldn't be read just now"
UNREAD_DETAIL = 'That is not the same as nothing waiting. Today reads it again on its next refresh.'
BUFFER_UNREAD_TITLE = "The Buffer desk's leftover posts couldn't be read just now"
BUFFER_UNREAD_DETAIL = ('That is not the same as nothing left: posts approved there before the switch may still be '
                        'going out. Today reads it again on its next refresh.')
BUFFER_MISSED_DETAIL = {
    1: ('It was never approved, so it never went out, and nothing new is approved on the Buffer desk now. Let it go '
        'there, or make it again on the suite desk.'),
    2: ('They were never approved, so they never went out, and nothing new is approved on the Buffer desk now. Let '
        'them go there, or make them again on the suite desk.'),
}
BUFFER_KINDS = ('failed', 'uncertain', 'paused', 'missed')


# ── the predicate ─────────────────────────────────────────────────────

def active() -> bool:
    """The suite is active: MC_MARKETING_SUITE on AND a validated platform
    business (platform_suite.buffer_state 'closed'). Off: no read at all."""
    return platform_suite.buffer_state() == 'closed'


def _not_active() -> str:
    """Why the suite desk isn't Platform Chief's right now, in a plain sentence."""
    return platform_suite.problem() or platform_suite.NOT_ON


# ── small words ───────────────────────────────────────────────────────

def _sentence(text: str) -> str:
    text = (text or '').strip()
    return text if text.endswith(('.', '!', '?')) else text + '.'


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _mc(text: Any) -> str:
    """B10 talks to a practitioner in Grow → Marketing; Kevin's desk is Mission Control's."""
    return str(text or '').replace('Grow → Marketing', WHERE_MC)


def _no(result: str, label: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    """Platform Chief's reply shape for a refusal: ok, label and result, always."""
    said = _sentence(result)
    return {'ok': False, 'label': said, 'result': said, 'title': label or 'Nothing changed', **extra}


KEEP = ('post_id', 'revision', 'status', 'was', 'already', 'dropped', 'queued', 'kind', 'week_of', 'level',
        'goes_out_at', 'stale', 'revision_now', 'need', 'upgrade', 'plan_gives', 'unavailable', 'switched_on',
        'time_zone', 'you_can_change', 'sending', 'posting_paused', 'accounts', 'chief_read',
        'waiting_for_owner_ok', 'planning_now', 'posts', 'more_posts', 'needs_a_look', 'results')


def answer(out: Dict[str, Any]) -> Dict[str, Any]:
    """B10's answer ({result, label, ok, failed, ...}) in Platform Chief's
    reply shape: `label` is the card's sentence (B10's result, in Mission
    Control's words), `result` the same, `title` B10's short label."""
    said = _mc(out.get('result') or out.get('label') or '')
    ok = bool(out.get('ok')) and not out.get('failed')
    return {'ok': ok, 'label': said, 'result': said, 'title': _mc(out.get('label') or ''),
            **{k: out[k] for k in KEEP if k in out}}


def _attended() -> bool:
    """Running from a card the owner approved (Platform Chief's yes)."""
    import platform_chief_authority as authority
    ctx = authority.current_authorization.get()
    return bool(ctx) and ctx[1].get('automatic', True) is False


def _other_business(action: Dict[str, Any], pid: Optional[str]) -> bool:
    raw = (action or {}).get('business_id')
    return raw not in (None, '') and not platform_suite._same(raw, pid)


def _clean(verb: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """The tag as B10 reads it: no control field from the model (anything
    starting with _, a business id), and Buffer-desk spellings read as B10's
    (text -> caption, channels -> platforms, run_at -> when)."""
    out = {k: v for k, v in (action or {}).items()
           if not str(k).startswith('_') and k not in ('business_id', 'approval', 'type')}
    for old, new in (('text', 'caption'), ('channels', 'platforms'), ('run_at', 'when')):
        if old in out and new not in out:
            out[new] = out.pop(old)
    out['type'] = verb
    return out


def _b10(verb: str) -> Callable[..., Awaitable[Dict[str, Any]]]:
    import chief_marketing_actions as cma
    return {'marketing_desk': cma.handle_marketing_desk, 'marketing_new_post': cma.handle_marketing_new_post,
            'marketing_edit_post': cma.handle_marketing_edit_post, 'marketing_skip_post': cma.handle_marketing_skip_post,
            'marketing_replan': cma.handle_marketing_replan, 'marketing_post_now': cma.handle_marketing_post_now}[verb]


async def platform_row(owner) -> Dict[str, Any]:
    """Solutionist's own business row, checked: the suite active, the id
    validated, the row platform_books and owned by the signed-in platform
    owner (platform_marketing_suite's own check). Raises HTTPException in
    plain words otherwise."""
    import platform_marketing_suite as pms
    return await asyncio.to_thread(pms._platform_row, str(owner.id))


async def work(verb: str, owner, turn: str, action: Dict[str, Any], *, attended: bool = False) -> Dict[str, Any]:
    """One verb on the suite desk, through B10's own handler, for the
    platform business only. Never raises: a refusal is {ok: False, label}."""
    nothing = NOTHING[verb]
    try:
        if not active():
            return _no(f'{_not_active()} {_cap(nothing)}.', "Solutionist's desk isn't on the suite")
        pid = platform_suite.active_id()
        if _other_business(action, pid):
            return _no(OTHER_BUSINESS.format(nothing=nothing), "Only Solutionist's own desk")
        if verb in CLASS_C and not attended:
            # Before anything is read, as B10's own unattended gate.
            return _no(*NOT_CARD[verb])
        try:
            row = await platform_row(owner)
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else "Solutionist's own business couldn't be read"
            return _no(f'{_sentence(detail)} {_cap(nothing)}.' if 'nothing' not in detail.lower() else detail,
                       "Couldn't confirm Solutionist's business")
        if verb == 'marketing_replan':
            held = await _buffer_week_held()
            if held:
                return _no(held, 'Planned on the Buffer desk')
        clean = _clean(verb, action)
        if verb in CLASS_C:
            clean['_unattended'] = not attended
        import billing_context
        import chief_of_staff as cos
        import image_studio as images
        user = cos._TURN_USER_ID.set(str(owner.id))
        same_turn = images.turn_id.set(turn)
        try:
            with billing_context.bill_to(str(row['id'])):
                out = await _b10(verb)(None, row, clean)
        finally:
            images.turn_id.reset(same_turn)
            cos._TURN_USER_ID.reset(user)
        return answer(out or {})
    except Exception as e:  # a card is never blank and never a half-claim
        log.exception('platform chief %s on the suite failed: %s', verb, e)
        return _no(f"I couldn't do that on Solutionist's marketing desk just now, so {nothing}. Try again in a minute.",
                   'Not done')


async def _buffer_week_held() -> Optional[str]:
    """Mission Control's own POST /suite/engine/run rule (one loop a week): a
    week the Buffer desk planned, with a post approved or out, is not planned
    again here. The refusal in the route's words, or None."""
    import business_marketing_planner as planner
    held = await platform_suite.buffer_week_live(planner.target_week(planner._now(), platform_suite.TZ))
    if held is None:
        return platform_suite.BUFFER_WEEK_UNREAD
    return platform_suite.BUFFER_WEEK if held else None


# ── the handlers Platform Chief's dispatch merges in ──────────────────

def _turn(request_id: Any) -> str:
    return f'platform-chief:{request_id}'


def handlers(owner, request_id) -> Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]]:
    """For platform_chief_actions.dispatch_actions. Empty with the switch
    off (every tag is answered exactly as before). With the switch on: the
    suite-only verbs (each refuses in platform_suite's words while the suite
    is not active), and, while it is active, marketing_new_post on the suite
    desk. marketing_post_now never runs here: it is always a card."""
    if not platform_suite.suite_on():
        return {}

    def bound(verb):
        async def run(action):
            return await work(verb, owner, _turn(request_id), action, attended=_attended())
        return run
    out = {verb: bound(verb) for verb in SUITE_ONLY}
    if active():
        out['marketing_new_post'] = bound('marketing_new_post')
    return out


def card_handlers(owner, request_id, action: Dict[str, Any]):
    """For platform_chief_authority.decide: the suite's handler for a card
    the suite made (a suite-only verb, a suite post-now card, or a new post
    while the suite is active). Empty for any other card, so a Buffer card
    runs exactly as before."""
    kind = (action or {}).get('type')
    if kind in SUITE_ONLY or (kind == 'marketing_post_now' and (action or {}).get('desk') == 'suite'):
        pass
    elif kind == 'marketing_new_post' and platform_suite.suite_on() and active():
        pass
    else:
        return {}

    async def run(act):
        if kind == 'marketing_post_now':
            return await post_now(owner, request_id, act)
        return await work(kind, owner, _turn(request_id), act, attended=_attended())
    return {kind: run}


# ── post now: the card freezes what goes out ──────────────────────────

async def post_now_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    """What the owner's card shows and approves (platform_chief_authority.
    propose). The suite inactive: the Buffer desk's own review, exactly as
    before. Active: a post on the suite desk exactly as read now (post_id,
    revision, content hash, words, accounts), or a new post's words,
    networks, picture and link. A refusal is an HTTPException in plain words
    (dispatch makes it that action's answer)."""
    import platform_chief_marketing as pcm
    if not active():
        return await pcm.post_now_review(payload)
    import business_marketing_desk as bmd
    import chief_marketing_actions as cma
    from chief_clip_actions import Refusal
    pid = platform_suite.active_id()
    nothing = NOTHING['marketing_post_now']
    if _other_business(payload, pid):
        raise HTTPException(422, OTHER_BUSINESS.format(nothing=nothing))
    review = {'type': 'marketing_post_now', 'desk': 'suite', 'business_id': pid,
              'goes_out': 'About two minutes after your approval'}
    try:
        if payload.get('post_id') or payload.get('id'):
            ref = cma._post_ref(payload, nothing)
            row = await cma._current(pid, ref['id'], nothing)
            cma._same_revision(row, ref, nothing)
            cma._open_for(row, ('draft', 'approved'), nothing, what='posted now')
            return {**review, 'post_id': ref['id'], 'revision': ref['revision'], 'content_hash': row['content_hash'],
                    'caption': row.get('caption') or '', 'accounts': bmd.channels_of(row),
                    'picture': cma._picture_words(row)}
        if payload.get('post_ids'):
            raise Refusal('On the marketing suite desk a post is named by its post_id and revision from the desk, so '
                          f'{nothing}.', 'Which post?')
        if payload.get('flyer'):
            raise Refusal('A new flyer goes out right away only once it is made: save it as a draft first (it gets its '
                          f'flyer), then ask me to post that one now. {_cap(nothing)}.', 'Save it as a draft first')
        clean = _clean('marketing_post_now', payload)
        raw = clean.get('caption') if clean.get('caption') is not None else clean.get('words')
        caption = raw.strip() if isinstance(raw, str) else ''
        image_id = await cma._picture(pid, clean, nothing)
        if not caption and not image_id:
            raise Refusal(f'What should the post say? Tell me the words, or which picture to use. {_cap(nothing)}.',
                          'What should it say?')
        platforms = clean.get('platforms')
        if isinstance(platforms, str):
            platforms = [platforms]
        ids = await cma._connection_ids(pid, platforms, nothing)
        names = list(dict.fromkeys(cma._platform(p) for p in platforms or [] if cma._platform(p))) if ids else None
        out = {**review, 'caption': caption,
               'accounts': [cma._network(p) for p in names] if names else "the desk's accounts",
               'platforms': names, 'image_id': image_id}
        if clean.get('link') is not None:
            out['link'] = str(clean['link'])
        return out
    except Refusal as r:
        raise HTTPException(422, r.result) from None


async def post_now(owner, request_id, action: Dict[str, Any]) -> Dict[str, Any]:
    """A suite post-now card the owner approved: what the card froze goes
    out in about two minutes, through B10's own Post now. A Buffer card
    (no desk 'suite') is the Buffer desk's own handler, as before."""
    if (action or {}).get('desk') != 'suite':
        from platform_chief_actions import HANDLERS
        return await HANDLERS['marketing_post_now'](action)
    verb, nothing = 'marketing_post_now', NOTHING['marketing_post_now']
    if not _attended():
        return _no(*NOT_CARD[verb])
    if not active():
        return _no(f'{_not_active()} {_cap(nothing)}.', "Solutionist's desk isn't on the suite")
    pid = platform_suite.active_id()
    if not platform_suite._same(action.get('business_id'), pid):
        return _no(OTHER_BUSINESS.format(nothing=nothing), "Only Solutionist's own desk")
    if action.get('post_id'):
        import business_marketing_store as store
        try:
            row = await store.get_post(pid, str(action['post_id']))
        except store.StoreError:
            return _no(f"I couldn't read that post just now, so {nothing}. Try again in a minute.",
                       "Couldn't read the post")
        if (not row or int(row.get('revision') or 0) != int(action.get('revision') or 0)
                or row.get('content_hash') != action.get('content_hash')):
            return _no(CHANGED_SINCE_CARD, 'The post changed')
        b10 = {'post_id': action['post_id'], 'revision': action['revision']}
    else:
        b10 = {'caption': action.get('caption') or '', 'platforms': action.get('platforms'),
               'image_id': action.get('image_id')}
        if action.get('link') is not None:
            b10['link'] = action['link']
    return await work(verb, owner, _turn(request_id), {**b10, 'business_id': pid}, attended=True)


# ── Platform Chief's marketing context (the drawer over the desk) ─────

PROMPT = '''
You are also the Mission Control marketing partner for The Solutionist System itself.
Solutionist's own marketing now runs on the MARKETING SUITE DESK (live data: desk): the same desk every business
has, for Solutionist's own business, posting through its own connected accounts on Eastern time. desk.posts lists
this week's and next week's posts with post_id, revision, when, status, words, accounts and picture; desk.chief_read
is the desk's own read; desk.needs_a_look what needs a hand; desk.waiting_for_owner_ok what waits for Kevin's OK.
If desk says unavailable, say you couldn't read the desk, never that nothing is there. results (when loaded) counts
what came THROUGH each post's link: never say a post caused it, and never read an unavailable count as zero.
Use founder_offer for the founder billing interval, credits and live seat availability (a lifetime-locked monthly
rate is NOT a one-time purchase; the seat limit is not the number remaining). Never invent testimonials, pricing,
statistics, guarantees or customer results; distinguish verified product facts from ideas, and treat earlier
assistant copy as unverified drafts. When asked for suggestions or image comparison, only discuss.
MAKING A POST: you lead. When Kevin asks for a post, or says yes to one you suggested, write it and save it in the
same reply; do not ask first where or when:
[ACTION:{"type":"marketing_new_post","caption":"the words","platforms":["facebook","instagram"],"when":"ISO time with its offset"}]
Leave out "platforms" for the desk's accounts and "when" for the desk's next open time. For a picture use
"image_id" (an artwork id from this conversation) or "image":"latest", or "flyer":{"headline":"6-42 characters",
"line":"10-120 characters","cta":"3-22 characters"} for a free flyer; Instagram needs a picture. No links in the
words (the post adds its own mysolutionist.app link) and no hashtags. It saves a draft that waits for Kevin's OK.
To change ONE post (words, time, accounts, picture or link; an approved post goes back to a draft and needs his OK
again): [ACTION:{"type":"marketing_edit_post","post_id":"<post_id>","revision":2,"caption":"New words.","when":"ISO time"}]
To skip one (it never goes out): [ACTION:{"type":"marketing_skip_post","post_id":"<post_id>","revision":2}]
Only when Kevin asks you to plan or write the week again: [ACTION:{"type":"marketing_replan"}] (his OK on a card
first; planning runs in the background, so say it has started, never that drafts are ready).
POSTING RIGHT AWAY, only when Kevin wants it out now: [ACTION:{"type":"marketing_post_now","post_id":"<post_id>","revision":3}]
or a new one [ACTION:{"type":"marketing_post_now","caption":"the words","platforms":["facebook"]}]. It never runs on
its own: Kevin gets a card with the exact words and accounts, and it goes out about two minutes after he approves it
there. Say you are asking for his OK on the card.
post_id and revision come from desk.posts; never invent them. A result that says the post changed means the desk
moved on: say so, and use the desk as it is in the next message.
You NEVER approve a post; there is no verb for it. Kevin approves on the desk, or Chief's weekly posts are approved
on his standing OK when he has turned it on (he can take any back before it goes out).
THE BUFFER DESK is draining (buffer_drain): posts approved there before the switch still go out; nothing new goes to
Buffer. To let one of its stuck posts go: [ACTION:{"type":"marketing_skip_slot","post_ids":["UUID"]}] with its
post_ids from buffer_drain.
Say sent or posted only when a status or a result says so. Action result cards establish success; describe proposed
actions as requests, not completed work. Do not repeat an action already recorded as successful. Do not expose
internal IDs in prose.
'''

DIGEST_PROMPT = '''
MARKETING (snapshot.marketing, desk "suite"): Solutionist's own marketing runs on the marketing suite desk in
Mission Control → Growth → Marketing. Nothing posts until Kevin approves it there, or Chief approves a weekly post on
his standing OK (approved_on_standing_ok; each can be taken back until it goes out). When Kevin asks what needs him,
or how the business is doing, include what marketing is waiting on from needs_owner, in plain words: posts waiting
for his OK with when the first goes out, posts Chief approved on his standing OK, posts that failed or may not have
gone out, pulled posts, and what the draining Buffer desk still needs (buffer_drain). posts_readable false means the
desk couldn't be read: say so, never that nothing is waiting. Never say a post was approved or published unless the
digest says so, and never approve for him: approving happens on the desk.
'''


async def snapshot(owner) -> Dict[str, Any]:
    """Platform Chief's live marketing data while the suite is active: the
    suite desk as B10 reads it (posts with what an action needs), its link
    results, the founder offer, and what the Buffer desk still needs. Each
    source that fails is named unavailable, never empty."""
    import chief_marketing_actions as cma
    import platform_chief_marketing as pcm
    from zoneinfo import ZoneInfo
    pid = platform_suite.active_id()
    result: Dict[str, Any] = {
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'suite': {'on': True, 'business_id': pid, 'note': SUITE_NOTE},
        'source_status': {},
    }

    async def read(key, fetch):
        try:
            data = await fetch()
        except Exception as e:  # each source fails on its own, said plainly
            log.warning('platform chief suite snapshot: %s unavailable: %s', key, type(e).__name__)
            result[key] = {'unavailable': f"{key.replace('_', ' ').capitalize()} couldn't be read just now."}
            result['source_status'][key] = {'status': 'unavailable'}
            return None
        result[key] = data
        result['source_status'][key] = {'status': 'loaded'}
        return data

    async def desk():
        import business_marketing as bm
        row = await platform_row(owner)
        payload = await bm.engine(UUID(str(row['id'])), {**row, '_caller_role': 'owner'})
        return cma.desk_digest(payload)

    got = await read('desk', desk)
    if got is not None:
        await read('results', lambda: cma._results(pid, ZoneInfo(got['time_zone'])))
    await read('founder_offer', pcm.founder_offer)
    await read('buffer_drain', _buffer_drain_for_chief)
    return result


async def _buffer_drain_for_chief() -> Dict[str, Any]:
    state = await _buffer_read(datetime.now(timezone.utc))
    if state is None or state.get('posts') is None:
        raise RuntimeError('buffer unreadable')
    return {'note': 'Posts approved on the Buffer desk before the switch still go out. Nothing new goes there.',
            'needs_a_hand': [{'title': i['title'], 'detail': i['detail'], 'post_ids': i.get('post_ids', [])}
                             for i in buffer_items(state)]}


# ── reading both desks (Today and the digest) ─────────────────────────

def _now() -> datetime:
    import business_marketing as bm
    return bm.now()


async def _suite_read(pid: str, now: datetime) -> Optional[Dict[str, Any]]:
    """The suite desk's rows for the platform business (strict=False: a
    source that cannot be read is None and named), or None when the read
    itself failed."""
    import business_marketing as bm
    import business_marketing_desk as bmd
    try:
        try:
            accounts = await bm.connected(pid)
        except HTTPException:
            accounts = None
        return await bmd.read_state(pid, tz=platform_suite.TZ, now=now, connections=accounts, strict=False)
    except Exception as e:
        log.warning("platform suite: Solutionist's desk couldn't be read: %s", type(e).__name__)
        return None


async def _buffer_read(now: datetime) -> Optional[Dict[str, Any]]:
    import marketing_desk
    try:
        return await marketing_desk.read_state(now)
    except Exception as e:
        log.warning("platform suite: the Buffer desk's leftovers couldn't be read: %s", type(e).__name__)
        return None


def _readable(state: Optional[Dict[str, Any]]) -> bool:
    return state is not None and state.get('posts') is not None


def _at(post: Dict[str, Any], now: datetime) -> datetime:
    import marketing_desk as words
    return words._stamp(post.get('run_at')) or now


def standing(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Posts Chief approved on Kevin's standing OK that are still to go out, soonest first."""
    now = state['now']
    rows = [p for p in state['posts'] or [] if p.get('status') == 'approved' and p.get('approved_via') == 'standing'
            and _at(p, now) > now]
    return sorted(rows, key=lambda p: (str(p['run_at']), str(p['id'])))


def pulled(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Posts pulled before they went out (B11: their time booked first), the last week's."""
    now = state['now']
    return [p for p in state['posts'] or [] if p.get('status') == 'pulled' and _at(p, now) >= now - PULLED_WINDOW]


def _item(id_: str, title: str, detail: str, *, tone: str, lanes=('people',), count=None, label='Review the posts',
          source='Marketing') -> Dict[str, Any]:
    return {'id': id_, 'kind': 'marketing', 'source': source, 'title': title, 'detail': detail,
            'lanes': list(lanes), 'room': 'growth', 'tone': tone, 'seen': 1, 'count': count,
            'action': {'label': label, 'nav': NAV}}


def suite_items(state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """MC Today's items from the suite desk: the business desk's own Today
    items (what waits for Kevin's OK, failed, partly sent, unconfirmed,
    paused, missed, a plan not written, no accounts, quiet), in Mission
    Control's room, plus what Chief approved on the standing OK and pulled
    posts. A desk that couldn't be read is one item saying so."""
    import business_marketing_desk as bmd
    import marketing_desk as words
    if not _readable(state):
        return [_item('marketing:suite:unread', UNREAD_TITLE, UNREAD_DETAIL, tone='amber', lanes=('systems',),
                      label='Open the desk')]
    out = []
    for item in bmd.today_items(state):
        out.append({**item, 'room': 'growth', 'title': _mc(item.get('title')), 'detail': _mc(item.get('detail')),
                    'action': {**(item.get('action') or {}), 'nav': NAV}})
    tz = state['tz']
    ok = standing(state)
    if ok:
        n, first = len(ok), ok[0]
        out.append(_item('marketing:suite:standing', f"Chief approved {words._plural(n, 'post')} on your standing OK",
                         f"The next goes out {words.day_name(first['run_at'], tz)} at {words.clock(first['run_at'], tz)}. "
                         'Review or take back any on the desk before it goes out.', tone='blue', count=n))
    gone = pulled(state)
    if gone:
        n = len(gone)
        out.append(_item('marketing:suite:pulled',
                         'A post was pulled before it went out' if n == 1 else
                         f"{words._cap(words._plural(n, 'post'))} were pulled before they went out",
                         str(gone[0].get('error') or 'Nothing was posted. Nothing needs your OK.')[:220],
                         tone='blue', count=n, label='See the desk'))
    return out


def buffer_items(state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The Buffer desk's leftovers that need a hand while it drains: posts
    that didn't go out, may or may not have gone out, are held by paused
    publishing, missed their time, or were approved but missed their window.
    The waiting drafts are not asked about: nothing is approved there now."""
    import marketing_desk as words
    if not _readable(state):
        return [_item('buffer:unread', BUFFER_UNREAD_TITLE, BUFFER_UNREAD_DETAIL, tone='amber', lanes=('systems',),
                      label='Open the desk', source='Buffer desk')]
    f = words.facts(state)
    out = []
    for item in words.attention(f):
        kind = item['kind']
        if kind not in BUFFER_KINDS or (kind == 'paused' and not f['approved']):
            continue
        n = len(item['slots'])
        detail = item['detail']
        if kind == 'missed':
            detail = BUFFER_MISSED_DETAIL[1 if n == 1 else 2]
        out.append({**_item(f"buffer:{item['id']}", f"{item['title']} (Buffer desk)", detail, tone=item['tone'],
                            count=n or None, label=words.ACTION[kind], source='Buffer desk'),
                    'post_ids': [i['id'] for s in item['slots'] for i in s['items']]})
    now = state['now']
    expired = [p for p in state['posts'] or [] if p.get('status') == 'approved'
               and (words._stamp(p.get('expires_at')) or now + timedelta(days=1)) <= now]
    if expired:
        group = words.slots(expired)
        n = len(group)
        out.append({**_item('buffer:marketing:window', f"{words._cap(words._plural(n, 'approved post'))} missed "
                            f"{'its' if n == 1 else 'their'} window (Buffer desk)",
                            f"{'It was' if n == 1 else 'They were'} approved before the switch but not handed to Buffer "
                            f"in time, so {'it' if n == 1 else 'they'} will not go out. Make {'it' if n == 1 else 'them'} "
                            'again on the suite desk if it still matters.', tone='amber', count=n,
                            label='See the desk', source='Buffer desk'),
                    'post_ids': [i['id'] for s in group for i in s['items']]})
    return out


async def today_items() -> List[Dict[str, Any]]:
    """MC Today's marketing items while the suite is active (platform_today._marketing)."""
    now = _now()
    suite, buffer = await asyncio.gather(_suite_read(platform_suite.active_id(), now), _buffer_read(now))
    return suite_items(suite) + buffer_items(buffer)


async def digest() -> Dict[str, Any]:
    """The Mission Control Chief digest's marketing while the suite is
    active: the business desk's own digest for the platform business, in
    Mission Control's words, plus the standing OK, pulled posts and the
    Buffer desk's leftovers. A desk that couldn't be read says so."""
    import business_marketing_desk as bmd
    now = _now()
    suite, buffer = await asyncio.gather(_suite_read(platform_suite.active_id(), now), _buffer_read(now))
    if suite is None:
        out: Dict[str, Any] = {'posts_readable': False, 'read': [UNREAD_DETAIL],
                               'needs_owner': [f'{UNREAD_TITLE}: {UNREAD_DETAIL}']}
    else:
        out = bmd.chief_digest(suite)
        out['needs_owner'] = [_mc(n) for n in out.get('needs_owner') or []]
        if not out.get('posts_readable'):
            out['needs_owner'].insert(0, f'{UNREAD_TITLE}: {UNREAD_DETAIL}')
        else:
            extra = [i for i in suite_items(suite) if i['id'] in ('marketing:suite:standing', 'marketing:suite:pulled')]
            out['needs_owner'] += [f"{i['title']}: {i['detail']}" for i in extra]
        out['approved_on_standing_ok'] = len(standing(suite)) if _readable(suite) else None
        out['pulled_last_7_days'] = len(pulled(suite)) if _readable(suite) else None
    leftovers = buffer_items(buffer)
    out.update(desk='suite', where=WHERE_MC)
    out['buffer_drain'] = {'readable': _readable(buffer),
                           'needs_a_hand': [f"{i['title']}: {i['detail']}" for i in leftovers]}
    out['needs_owner'] = list(out.get('needs_owner') or []) + out['buffer_drain']['needs_a_hand']
    return out

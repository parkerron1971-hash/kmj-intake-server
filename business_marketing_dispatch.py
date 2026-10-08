"""business_marketing_dispatch.py — the marketing desk's sender and delivery watch, for every business.

B5 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (decision D3). The desk
API (business_marketing.py, B4) saves posts and records the owner's approval;
this module is what hands an approved post to Post for Me, and what finds out
how it went.

  due_tick        every minute   claim due approved posts (marketing_claim_due)
                                 and send each one through the one posting door
  delivery_tick   every 5 min    read how each sent post went; tell the owner
                                 once per problem

Both do nothing until MARKETING_DESK_PUBLISHING=on (business_marketing.
publishing_on, default off). Both run only where scheduled jobs run
(PROCESS_ROLE worker or all), on the scheduler leader.

ONE DOOR. Every post goes through social_publish_router.send_post: the daily
cap, the record of who approved what, the hand-off with our row id as
external_id, a refused hand-off recorded as failed. A picture or words-only
post calls it directly; a clip goes through clip_posting.post_clip_for, which
re-checks the clip's own approval and fingerprint and adds its covers.

RE-CHECKED AT SEND TIME, whatever happened since the approval:
  * the content still hashes to what was approved (business_marketing_store.
    digest == approved_hash == content_hash), and its window is still open;
  * the desk is not paused (a pause wins even after the claim: the post goes
    back to approved and waits, as the desk tells the owner it will);
  * the posting pilot is on for the business (post_for_me.allowed_for). Off,
    the post is held, not failed: back to approved, saying why, no push; it
    goes out if the business is switched back on while its window is open.
    A server with no posting key or an empty pilot list claims nothing;
  * every account is still connected to THIS business, and is the same
    account the owner approved (social._targets);
  * the picture is a ready artwork of THIS business; the clip is approved as
    it is now, at the fingerprint the post was approved with (the
    fingerprint is in the post's content hash); a clip Chief folded into the
    week (source 'clip', B12) is still among the owner's kept clips;
  * an open-chairs post (source 'opening', B11) still has its chairs: its
    window is recounted on the calendar (business_marketing_openings.
    recheck). Booked into, filled up or too close: the post is `pulled`
    (never sent, never needs a yes; the planner's watch tells the owner
    once). A calendar that cannot be read holds it: back to approved, tried
    again next minute, never sent on a guess.

THE BUILD ACTOR. On the worker there is no JWT, so making a picture's public
JPEG (images.delivery_jpeg, also used for a clip's covers) needs
image_studio.build_actor bound to {business_id, user_id: owner}. It is bound
only after the owner has been read (a service-role read of
businesses.owner_id), for this one post, and reset in a finally: storage then
refuses any path outside this business's folder, and the binding never
reaches the next post.

WHAT HAPPENS WHEN SOMETHING GOES WRONG (the platform desk's dispatch rules):
  * nothing left this server (a storage blip, a read that failed): the post
    goes back to `approved` and the next tick tries again until its window
    closes. The publication id is uuid5(post id, 'rev:<revision>'), so a retry
    of the same revision can never post twice;
  * a check said no, or the posting service refused the hand-off: `failed`,
    with the reason in plain words;
  * anything else once the hand-off is under way: `uncertain`, until the
    delivery watch or the owner settles it. Never sent again automatically;
  * a hand-off whose receipt is not on the record (the door answered with a
    publication that has no provider_post_id: an earlier record that never
    got one, or a receipt that could not be written) is `uncertain` too,
    never `submitted`.
A result that cannot be recorded is logged and left `dispatching`; the claim
RPC's sweep makes it `uncertain` after ten minutes, and never resends it.

THE DELIVERY WATCH. There is no webhook: every five minutes the posts handed
over (submitted, and uncertain ones from the last two days) are refreshed
through social._refresh and mapped to published, partly_published or failed,
with each live post's link in external_urls. A post still in flight two hours
after it was claimed becomes uncertain. The publication is read fail-closed:
a read that fails leaves the post exactly as it is until the next tick. Then
each problem (failed, partly_published, uncertain) gets one push to the owner
and one Today item, deduplicated by post, revision and status, so it is said
exactly once; the newest problems are considered first and the ones already
told are left out before any limit. A success is never pushed. A failure the
owner made themselves (marking an unconfirmed post not sent) is not announced
back to them.

All blocking Supabase calls run in a thread. Each post has its own try: one
bad post never stops the batch.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid5

import httpx
from fastapi import HTTPException

import business_marketing_desk as reading
import business_marketing_openings as openings
import business_marketing_store as store
import clip_posting
import image_posting
import image_studio as images
import post_for_me
import sb_clients
import social_publish_router as social
from business_marketing import NOT_SENT_NOTE, publishing_on
from marketing_desk import _join

log = logging.getLogger(__name__)

CLAIM_LIMIT = 5                        # posts per minute; each send may take a while
CLAIM_ROUNDS = 4                       # more claims in a tick only while every claimed post was held
IN_FLIGHT_LIMIT = timedelta(hours=2)   # handed over, no answer yet: uncertain after this
WATCH_WINDOW = timedelta(days=2)       # how long an uncertain post is still looked up
WATCH_LIMIT = 50
TELL_WINDOW = timedelta(hours=6)       # a problem is announced within this long of happening
TELL_LIMIT = 100                       # announcements per tick
TELL_PAGE = 200
TELL_PAGES = 5
ANNOUNCED_LOOKBACK = timedelta(days=1)  # announcements read back beyond TELL_WINDOW
MAX_PICTURES = 10                      # the posting door takes at most ten
PROBLEMS = ('failed', 'partly_published', 'uncertain')
NAV = reading.NAV                      # 'grow:marketing'

RETRY = 'A check before sending did not finish; it will try again in a minute.'
CHANGED = ('This post changed after it was approved, so it was not sent. Review it and approve it again.')
UNREADABLE = ("This post couldn't be read as it was approved, so it was not sent. Open it, check it and "
              'approve it again.')
EXPIRED = 'Its time to post passed before it went out. Edit it and approve a new time.'
PILOT_HELD = ("Posting to your social accounts isn't switched on for this business right now. It goes out once "
              'it is, while its time to post is still open.')
NO_OWNER = 'This business has no owner on record, so nothing was posted for it.'
NO_ACCOUNTS = "This post has no accounts to go to. Choose its accounts and approve it again."
REFUSED = ("The posting service didn't accept the post. Nothing went out. Change it or give it a new time "
           'to try again.')
CAPPED = (f'This business has already posted {social.POSTS_PER_DAY_CAP} times in the last day, the most it may. '
          'Nothing went out. Give this post a new time tomorrow.')
PICTURE_GONE = ("The picture for this post couldn't be used, so nothing went out. Choose the picture again "
                'and approve the post.')
PICTURE_BROKEN = ("The picture for this post couldn't be read, so nothing went out. Choose another picture "
                  'and approve the post again.')
INTERRUPTED = ('Sending was interrupted after the post was handed to the posting service. Check your accounts; '
               'if it is not there, mark it not sent and give it a new time.')
STILL_GOING = ('Two hours on, the posting service still has not said whether it went out. Check your accounts; '
               'if it is not there, mark it not sent and give it a new time.')
UNCONFIRMED = ("Sending could not be confirmed: the posting service's receipt for this post was not recorded. "
               'Check your accounts; if it is not there, mark it not sent and give it a new time.')
CANCELLED = 'It was cancelled before it went out.'
CHAIRS_UNCHECKED = ("The booking calendar couldn't be checked just before sending, so this post waits and tries "
                    'again in a minute.')
OPENING_UNREADABLE = ("This post's open chairs couldn't be read, so it was not sent. Skip it, or write a new post "
                      'for that time.')
UNKEPT = ("This clip is no longer among your kept clips in Video Clips, so nothing went out. Keep it again, "
          'then approve the post again.')

# Refusals from inside the shared door that a failed READ can also produce
# (social._targets and clip_posting._require_owner read with `or []`). The
# sender has already checked both fail-closed, so one of these right after
# means a blip: the post is retried, and the next tick's own checks decide.
_AMBIGUOUS = frozenset({"One of those accounts isn't connected to this business.", 'Business not found.'})
# social._require_pilot's refusal: the pilot was switched off in the instant
# after the sender's own check. Held, like the sender's own pilot check.
_PILOT_OFF = "Posting to your social accounts isn't switched on for this business yet."


class Hold(Exception):
    """Nothing left this server: back to approved, the next tick tries again.
    `note` is what the post says meanwhile (None: nothing)."""

    def __init__(self, why: str, *, note: Optional[str] = RETRY):
        super().__init__(why)
        self.note = note


class Refuse(Exception):
    """A check said no: the post fails, with this reason in plain words."""


class Unreadable(Exception):
    """A read that failed: not the same as "nothing there"."""


class Pull(Exception):
    """An open-chairs post whose chairs booked first: it comes down, unsent."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


async def _chairs_still_open(business_id: str, row: Dict[str, Any]) -> None:
    """An open-chairs post's window, recounted just before sending (B11).
    Raises Pull when it booked into, filled up or is too close; Hold when the
    calendar cannot be read (never sent on a guess); Refuse when the post
    carries no readable opening."""
    opening = row.get('opening')
    if not openings.valid(opening):
        raise Refuse(OPENING_UNREADABLE)
    try:
        availability = await asyncio.to_thread(openings.read_availability, business_id)
        why = await asyncio.to_thread(openings.recheck, business_id, opening, availability, now())
    except openings.Unavailable:
        raise Hold('the booking calendar could not be read', note=CHAIRS_UNCHECKED) from None
    if why:
        raise Pull(why)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _when(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    try:
        out = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else None


# ── the publication id ────────────────────────────────────────────────

def request_id(row: Dict[str, Any]) -> UUID:
    """One per post per revision: every retry of the same approved version
    names the same send, and an edited post (a new revision) is a new one."""
    return uuid5(UUID(str(row['id'])), f"rev:{int(row['revision'])}")


def publication_id_for(row: Dict[str, Any]) -> str:
    """The social_publications id this post's send gets: the request id for a
    picture or words, and clip_posting.post_clip_for's own id for a clip."""
    rid = request_id(row)
    clip = (row.get('media') or {}).get('clip_id')
    if clip:
        return str(uuid5(UUID(str(clip)), f'post:{rid}'))
    return str(rid)


def read_publication(business_id: str, publication_id: str) -> Optional[Dict[str, Any]]:
    """One of this business's publications, or None when there is none.
    Unlike social._publication, a failed read raises Unreadable: it is never
    "no publication"."""
    rows = sb_clients.sb_get_as_service(
        f'/social_publications?id=eq.{UUID(str(publication_id))}&business_id=eq.{business_id}'
        f'&select={social._SELECT}&limit=1')
    if rows is None:
        raise Unreadable('the publication could not be read')
    return rows[0] if rows else None


# ── checks at send time (each runs in a thread) ──────────────────────

def _owner_of(business_id: str) -> str:
    """The business's owner, read as the service role. A failed read holds."""
    rows = sb_clients.sb_get_as_service(f'/businesses?id=eq.{business_id}&select=id,owner_id&limit=1')
    if rows is None:
        raise Hold('the business could not be read')
    if not rows or not rows[0].get('owner_id'):
        raise Refuse(NO_OWNER)
    return str(rows[0]['owner_id'])


def _name(target: Dict[str, Any]) -> str:
    label = social.post_for_me_label(str(target.get('platform') or ''))
    user = str(target.get('username') or '').strip().lstrip('@')
    return f'{label} (@{user})' if user else label


def _not_connected(gone: List[Dict[str, Any]]) -> str:
    names = image_posting.said_and([_name(t) for t in gone])
    verb = 'is' if len(gone) == 1 else 'are'
    return (f'{names} {verb} no longer connected to this business, so nothing went out. Reconnect in Build, '
            "Social Media, or change the post's accounts and approve it again.")


def _live_targets(business_id: str, post: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every account the post was approved for, still connected to THIS
    business and still the same account (network and Post for Me id)."""
    bound = [t for t in post.get('targets') or [] if isinstance(t, dict)]
    if not bound:
        raise Refuse(NO_ACCOUNTS)
    ids = [str(t.get('connection_id')) for t in bound]
    try:
        live = social._targets(business_id, ids)
    except HTTPException:
        live = None
    if live is None:
        # social._targets reads `or []`, so a failed read looks like a
        # disconnected account. Ask again, failing closed, before saying so.
        rows = sb_clients.sb_get_as_service(
            f"/social_connections?business_id=eq.{business_id}&status=eq.connected"
            f"&id=in.({','.join(sorted(set(ids)))})&select=id")
        if rows is None:
            raise Hold('the accounts could not be read')
        here = {str(r.get('id')) for r in rows}
        gone = [t for t in bound if str(t.get('connection_id')) not in here]
        if not gone:
            raise Hold('the accounts read failed once')
        raise Refuse(_not_connected(gone))
    by_id = {str(t['connection_id']): t for t in live}
    out = []
    for t in bound:
        fresh = by_id.get(str(t.get('connection_id')))
        if (not fresh or fresh.get('platform') != t.get('platform')
                or str(fresh.get('provider_account_id')) != str(t.get('provider_account_id'))):
            raise Refuse(f'{_name(t)} changed since this post was approved, so nothing went out. '
                         "Check the post's accounts and approve it again.")
        if fresh not in out:
            out.append(fresh)
    return out


async def _clip_ready(business_id: str, media: Dict[str, Any], *, chief_pick: bool = False) -> None:
    """The clip is this business's, ready, and approved as it is now, at the
    fingerprint this post was approved with. post_clip_for checks the same
    again; checking here first keeps a refusal apart from a hand-off.
    chief_pick: a clip Chief folded into the week (source 'clip', B12) was
    picked because the owner kept it; one taken off the kept clips since is
    not sent."""
    try:
        row = await asyncio.to_thread(clip_posting._clip, business_id, str(UUID(str(media['clip_id']))))
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise Hold('the clip could not be read') from None
        raise Refuse(f'{exc.detail} Nothing went out.') from None
    problem = clip_posting.approval_problem(row)
    if problem == 'unapproved':
        raise Refuse('This clip is no longer approved in Ready to post, so nothing went out. Approve the clip, '
                     'then approve the post again.')
    if problem == 'changed' or clip_posting.media_library.fingerprint(row) != media.get('clip_fingerprint'):
        raise Refuse('This clip changed after the post was approved, so nothing went out. Check the clip, '
                     'then approve the post again.')
    if chief_pick and row.get('decision') != 'kept':
        raise Refuse(UNKEPT)


async def _pictures(business_id: str, media: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each picture as a public JPEG, in the approved order. Only a ready
    artwork of THIS business is ever read; the build actor (bound by the
    caller) keeps storage inside this business's folder."""
    out = []
    for art_id in list(media.get('artwork_ids') or [])[:MAX_PICTURES]:
        try:
            row = await asyncio.to_thread(image_posting.ready_artwork, business_id, art_id)
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise Hold('the picture could not be read') from None
            raise Refuse(str(exc.detail).replace('Nothing was posted.', 'Nothing went out.')) from None
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                link = await images.delivery_jpeg(client, business_id, row)
        except HTTPException as exc:
            if exc.status_code in (401, 403, 404, 409):
                log.warning('marketing send: picture %s refused (%s)', row.get('id'), exc.status_code)
                raise Refuse(PICTURE_GONE) from None
            raise Hold('the picture could not be prepared') from None
        except httpx.HTTPError:
            raise Hold('the picture could not be prepared') from None
        except (OSError, ValueError):
            raise Refuse(PICTURE_BROKEN) from None
        out.append({'url': link, 'kind': 'image', 'image_id': str(row['id']),
                    'title': image_posting.design_title(row)})
    return out


def _after_handoff(exc: HTTPException) -> Dict[str, Any]:
    """An HTTPException from inside the shared door. Every one of these is
    raised before Post for Me is called (the refused hand-off excepted), so
    none can mean "maybe sent"."""
    code, detail = exc.status_code, str(exc.detail or '')
    if code == 502 and detail == social.REFUSED:
        return {'status': 'failed', 'error': REFUSED}
    if code == 429:
        return {'status': 'failed', 'error': CAPPED}
    if code == 403 and detail == _PILOT_OFF:
        return {'status': 'approved', 'claimed_at': None, 'error': PILOT_HELD}
    if code >= 500 or detail in _AMBIGUOUS:
        return {'status': 'approved', 'claimed_at': None, 'error': RETRY}
    return {'status': 'failed', 'error': detail or 'A check before sending said no. Nothing went out.'}


# ── sending ───────────────────────────────────────────────────────────

async def dispatch(row: Dict[str, Any]) -> Dict[str, Any]:
    """Send one claimed post and record what happened; returns the patch.
    Never raises."""
    post_id = str(row.get('id'))
    biz = str(row.get('business_id'))
    attempted = False
    token = None
    pub_id = None
    try:
        try:
            pub_id = publication_id_for(row)
            fresh = store.digest(row)
        except (KeyError, TypeError, ValueError):
            raise Refuse(UNREADABLE) from None
        if not row.get('approved_hash') or not (fresh == row.get('approved_hash') == row.get('content_hash')):
            raise Refuse(CHANGED)
        expires = _when(row.get('expires_at'))
        if expires is None or expires <= now():
            raise Refuse(EXPIRED)
        desk = await store.get_desk(biz)
        if desk is None or desk.get('paused'):
            raise Hold('the desk is paused', note=None)
        if not post_for_me.allowed_for(biz):
            # The pilot can be switched back on: the post waits, it does not fail.
            raise Hold('posting is not switched on for this business', note=PILOT_HELD)
        if row.get('source') == 'opening':
            await _chairs_still_open(biz, row)
        owner = await asyncio.to_thread(_owner_of, biz)
        targets = await asyncio.to_thread(_live_targets, biz, row)
        media = row.get('media') or {}
        caption = row.get('publish_text') or ''
        # Bound only now that the owner is known; reset in the finally below.
        token = images.build_actor.set({'business_id': biz, 'user_id': owner})
        if media.get('clip_id'):
            await _clip_ready(biz, media, chief_pick=row.get('source') == 'clip')
            attempted = True
            done = await clip_posting.post_clip_for(
                biz, owner, str(media['clip_id']), request_id=request_id(row),
                fingerprint=str(media.get('clip_fingerprint')), caption=caption,
                connection_ids=[str(t['connection_id']) for t in targets], scheduled_at=None,
                covers={str(k): str(v) for k, v in (media.get('covers') or {}).items()})
            sent_id = str((done.get('publication') or {}).get('id') or pub_id)
            # post_clip_for answers with the public shape (no provider id), so
            # the record itself says whether the hand-off was confirmed.
            try:
                sent = await asyncio.to_thread(read_publication, biz, sent_id) or {'id': sent_id}
            except Unreadable:
                sent = {'id': sent_id}
        else:
            pictures = await _pictures(biz, media)
            try:
                social._check(caption, pictures, targets)
            except HTTPException as exc:
                raise Refuse(f'{exc.detail} Nothing went out.') from None
            attempted = True
            sent, _ = await social.send_post(
                biz, str(row.get('approved_by') or owner), caption=caption, media=pictures, targets=targets,
                scheduled_at=None, approved_hash=row['approved_hash'], publication_id=pub_id)
        sent_id = str(sent.get('id') or pub_id)
        if sent.get('provider_post_id'):
            patch = {'status': 'submitted', 'publication_id': sent_id, 'error': None}
        else:
            # An earlier record that never got the posting service's id, or a
            # hand-off whose receipt could not be written: maybe out, unconfirmed.
            patch = {'status': 'uncertain', 'publication_id': sent_id, 'error': UNCONFIRMED}
    except Hold as hold:
        log.info('marketing send %s held: %s', post_id[:8], hold)
        patch = {'status': 'approved', 'claimed_at': None, 'error': hold.note}
    except Pull as pull:
        log.info('marketing send %s pulled: %s', post_id[:8], pull.why)
        patch = {**openings.pull_patch(row, pull.why, now()), 'claimed_at': None}
    except Refuse as refusal:
        patch = {'status': 'failed', 'error': str(refusal)}
    except store.StoreError:
        log.warning('marketing send %s: storage did not answer before sending', post_id[:8])
        patch = {'status': 'approved', 'claimed_at': None, 'error': RETRY}
    except HTTPException as exc:
        if attempted:
            patch = _after_handoff(exc)
        else:
            log.warning('marketing send %s stopped before sending: %s', post_id[:8], exc.status_code)
            patch = {'status': 'approved', 'claimed_at': None, 'error': RETRY}
    except Exception:
        log.warning('marketing send %s stopped %s the hand-off.', post_id[:8],
                    'after starting' if attempted else 'before', exc_info=True)
        patch = ({'status': 'uncertain', 'error': INTERRUPTED, **({'publication_id': pub_id} if pub_id else {})}
                 if attempted else {'status': 'approved', 'claimed_at': None, 'error': RETRY})
    finally:
        if token is not None:
            images.build_actor.reset(token)
    return await _record(row, patch)


async def _record(row: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Write the result, only onto the claim this tick holds."""
    try:
        saved = await store.request(
            'PATCH', f"/marketing_posts?id=eq.{UUID(str(row['id']))}&business_id=eq.{UUID(str(row['business_id']))}"
                     '&status=eq.dispatching', patch)
    except (store.StoreError, ValueError, KeyError):
        # Left dispatching: the claim RPC's sweep makes it uncertain after ten
        # minutes, and nothing ever sends it again on its own.
        log.error('marketing send result for %s could not be recorded (%s); it will read as unconfirmed.',
                  row.get('id'), patch.get('status'))
        return {'status': 'dispatching', 'error': 'not recorded'}
    if not saved:
        log.warning('marketing send %s: the post moved on before its result was recorded', row.get('id'))
    return patch


async def due_tick(limit: int = CLAIM_LIMIT) -> Dict[str, Any]:
    """Every minute: claim the approved posts that are due and send each.

    A server without the posting key or the pilot list claims nothing: a
    configuration slip never becomes a failed post. A business whose pilot is
    off has its claimed posts held (back to approved, saying why, no push).
    They stay claimed until the end of the tick, so while a whole claim was
    held the tick claims again and that business never crowds out the rest."""
    if not publishing_on():
        return {'skipped': 'off'}
    if not post_for_me.configured() or not post_for_me.pilot_businesses():
        return {'skipped': 'not configured'}
    tally: Counter = Counter()
    claimed, held = 0, []
    try:
        for _ in range(CLAIM_ROUNDS):
            try:
                rows = await store.claim_due(limit)
            except store.StoreError:
                log.warning('marketing send: could not claim due posts this minute.')
                if not claimed:
                    return {'skipped': 'storage'}
                break
            claimed += len(rows)
            sendable = [r for r in rows if post_for_me.allowed_for(str(r.get('business_id')))]
            held += [r for r in rows if r not in sendable]
            for row in sendable:
                try:
                    tally[str((await dispatch(row)).get('status'))] += 1
                except Exception:                  # dispatch never raises; one post never stops the rest
                    log.exception('marketing send %s failed unexpectedly', row.get('id'))
                    tally['error'] += 1
            if sendable or len(rows) < limit:
                break
    finally:
        for row in held:
            done = await _record(row, {'status': 'approved', 'claimed_at': None, 'error': PILOT_HELD})
            tally['held' if done.get('status') == 'approved' else str(done.get('status'))] += 1
    return {'claimed': claimed, **tally}


# ── the delivery watch ────────────────────────────────────────────────

WATCH_COLUMNS = 'id,business_id,revision,status,media,targets,publication_id,claimed_at'
TELL_COLUMNS = 'id,business_id,revision,status,error,targets,updated_at'


def _who(results: List[Dict[str, Any]]) -> str:
    names = []
    for r in results:
        label = social.post_for_me_label(str(r.get('platform') or '')) if r.get('platform') else ''
        if label:
            names.append(label)
    return _join(list(dict.fromkeys(names)))


def outcome_of(publication: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """How the send went, as the post records it, or None while it is still
    on its way. The network's own error text stays on the publication
    (Build, Social Media shows it); the post carries plain words."""
    status = publication.get('status')
    results = [r for r in publication.get('results') or [] if isinstance(r, dict)]
    ok = [r for r in results if r.get('success')]
    bad = [r for r in results if not r.get('success')]
    links = [{'platform': r.get('platform'), 'label': social.post_for_me_label(str(r.get('platform') or '')),
              'username': r.get('username'), 'url': r.get('url')} for r in ok]
    if status == 'posted':
        return {'status': 'published', 'external_urls': links, 'error': None}
    if status == 'partly_posted':
        return {'status': 'partly_published', 'external_urls': links,
                'error': (f"It went out on {_who(ok) or 'some accounts'}, but {_who(bad) or 'one account'} did not "
                          'take it. Open Build, Social Media to see why.')}
    if status == 'failed':
        return {'status': 'failed', 'external_urls': [],
                'error': (f"{_who(bad) or 'The posting service'} did not take it, so it didn't go out. "
                          'Change it or give it a new time to try again.')}
    if status == 'cancelled':
        return {'status': 'failed', 'external_urls': [], 'error': CANCELLED}
    return None


async def watch(row: Dict[str, Any], at: datetime) -> str:
    """Settle one handed-over post from its publication. Returns what it is now.
    A publication that cannot be read leaves the post exactly as it is until
    the next tick: a failed read never makes a post uncertain or pushes."""
    biz, status = str(UUID(str(row['business_id']))), row.get('status')
    pub_id = str(row.get('publication_id') or publication_id_for(row))
    try:
        publication = await asyncio.to_thread(read_publication, biz, pub_id)
    except Unreadable:
        return 'unreadable'
    if publication and publication.get('status') in social._IN_FLIGHT and publication.get('provider_post_id'):
        publication = await social._refresh(publication)
    outcome = outcome_of(publication) if publication else None
    if outcome is None:
        claimed = _when(row.get('claimed_at'))
        if status != 'submitted' or not claimed or at - claimed < IN_FLIGHT_LIMIT:
            return 'in_flight' if status == 'submitted' else str(status)
        outcome = {'status': 'uncertain', 'error': STILL_GOING}
    patch = {**outcome, 'checked_at': at.isoformat()}
    if publication and str(publication.get('id')) != str(row.get('publication_id') or ''):
        patch['publication_id'] = str(publication['id'])
    saved = await store.request(
        'PATCH', f"/marketing_posts?id=eq.{UUID(str(row['id']))}&business_id=eq.{biz}&status=eq.{status}"
                 f"&revision=eq.{int(row['revision'])}", patch)
    return outcome['status'] if saved else 'moved on'


# ── telling the owner, once per problem ───────────────────────────────

ACTION = {'failed': 'See what happened', 'partly_published': 'See which accounts', 'uncertain': 'Check it'}


def dedup_key(row: Dict[str, Any]) -> str:
    """One announcement per post, revision and problem: a post that fails,
    is fixed and approved again, and fails again is told twice; the same
    failure is never told twice."""
    return f"marketing_post:{UUID(str(row['id']))}:r{int(row['revision'])}:{row['status']}"


def words_for(row: Dict[str, Any]) -> Dict[str, str]:
    where = _join(reading.channels_of(row)) or 'your accounts'
    status = row['status']
    if status == 'failed':
        title, default = f"A post didn't go out on {where}", 'The posting service did not accept it.'
    elif status == 'partly_published':
        title, default = (f'A post went out on only some of {where}',
                          'Some accounts did not take it. Open the post to see which.')
    else:
        title, default = (f'A post may not have gone out on {where}',
                          'Sending was interrupted. Check your accounts; if it is not there, mark it not sent '
                          'and give it a new time.')
    return {'title': title, 'body': str(row.get('error') or default)}


def _owners(business_ids: List[str]) -> Optional[Dict[str, str]]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=in.({','.join(business_ids)})&select=id,owner_id")
    if rows is None:
        return None
    return {str(r.get('id')): str(r['owner_id']) for r in rows if r.get('owner_id')}


def _announced(since: datetime) -> Optional[set]:
    """The marketing posts' announcements made since then, by dedup key, for
    every business, so the ones already told never crowd out a new one.
    None when it could not be read."""
    rows = sb_clients.sb_get_as_service(
        f'/chief_notifications?action_payload->>dedup_key=like.marketing_post:*'
        f'&created_at=gte.{reading.query_time(since)}&select=dedup_key:action_payload->>dedup_key&limit=20000')
    if rows is None:
        return None
    return {str(r.get('dedup_key') or (r.get('action_payload') or {}).get('dedup_key') or '') for r in rows}


def _already_told(business_id: str, key: str) -> Optional[bool]:
    """True when told, False when not, None when it could not be read (then
    nothing is said this time, rather than risk saying it twice)."""
    rows = sb_clients.sb_get_as_service(
        f'/chief_notifications?business_id=eq.{business_id}&action_payload->>dedup_key=eq.{key}&select=id&limit=1')
    if rows is None:
        return None
    return bool(rows)


def _today_item(business_id: str, row: Dict[str, Any], said: Dict[str, str], key: str) -> bool:
    saved = sb_clients.sb_post_as_service('/chief_notifications', {
        'business_id': business_id, 'type': 'reminder',
        'priority': 'high' if row['status'] == 'failed' else 'normal',
        'title': said['title'][:120], 'body': said['body'][:300], 'suggested_action': ACTION[row['status']],
        'action_payload': {'type': 'navigate', 'tab': 'grow', 'sub': 'marketing',
                           'post_id': str(row['id']), 'dedup_key': key},
    })
    return bool(saved)


def _push(owner_id: str, row: Dict[str, Any], said: Dict[str, str]) -> int:
    try:
        import push_notifications
        return push_notifications.send_to_user(owner_id, title=said['title'][:80], body=said['body'][:160],
                                               nav=NAV, tag=f"marketing-post-{row['id']}")
    except Exception:
        log.warning('marketing: push for %s failed', row.get('id'), exc_info=True)
        return 0


async def tell_owners(at: datetime) -> int:
    """One Today item and one push per problem, never twice. Reads every
    business's recent problems, so a failure the claim RPC made (a window
    that closed, an interrupted send) is told the same way as the sender's
    own.

    Posts already told are left out before the limit applies, and the newest
    problems come first, so one that just happened is always considered: the
    announcements are read back first, then the problems page by page."""
    announced = await asyncio.to_thread(_announced, at - TELL_WINDOW - ANNOUNCED_LOOKBACK)
    if announced is None:
        return 0                                     # cannot tell what was said: say nothing this time
    rows: List[Dict[str, Any]] = []
    for page in range(TELL_PAGES):
        batch = await store.rows(
            f"/marketing_posts?status=in.({','.join(PROBLEMS)})&updated_at=gte.{reading.query_time(at - TELL_WINDOW)}"
            f'&select={TELL_COLUMNS}&order=updated_at.desc,id.asc&limit={TELL_PAGE}&offset={page * TELL_PAGE}')
        rows += [r for r in batch if r.get('status') in PROBLEMS
                 and not str(r.get('error') or '').startswith(NOT_SENT_NOTE)
                 and dedup_key(r) not in announced]
        if len(batch) < TELL_PAGE or len(rows) >= TELL_LIMIT:
            break
    rows = rows[:TELL_LIMIT]
    if not rows:
        return 0
    owners = await asyncio.to_thread(_owners, sorted({str(UUID(str(r['business_id']))) for r in rows}))
    if owners is None:
        return 0
    told = 0
    for row in rows:
        biz = str(UUID(str(row['business_id'])))
        try:
            key = dedup_key(row)
            if await asyncio.to_thread(_already_told, biz, key) is not False:
                continue
            said = words_for(row)
            if not await asyncio.to_thread(_today_item, biz, row, said, key):
                continue
            if owners.get(biz):
                await asyncio.to_thread(_push, owners[biz], row, said)
            told += 1
        except Exception:
            log.warning('marketing: could not tell the owner about %s', row.get('id'), exc_info=True)
    return told


async def delivery_tick(at: Optional[datetime] = None) -> Dict[str, Any]:
    """Every five minutes: settle the posts handed over, then tell owners
    about any new problem."""
    if not publishing_on():
        return {'skipped': 'off'}
    at = at or now()
    tally: Counter = Counter()
    try:
        rows = await store.rows(
            f'/marketing_posts?status=in.(submitted,uncertain)&claimed_at=gte.{reading.query_time(at - WATCH_WINDOW)}'
            f'&select={WATCH_COLUMNS}&order=claimed_at.asc&limit={WATCH_LIMIT}')
    except store.StoreError:
        log.warning('marketing delivery: the posts could not be read this time.')
        rows = []
        tally['unreadable'] += 1
    for row in rows:
        try:
            tally[await watch(row, at)] += 1
        except Exception:
            log.warning('marketing delivery: %s could not be checked', row.get('id'), exc_info=True)
            tally['error'] += 1
    try:
        tally['told'] += await tell_owners(at)
    except Exception:
        log.warning('marketing delivery: could not tell owners this time.', exc_info=True)
    return dict(tally)

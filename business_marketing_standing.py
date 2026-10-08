"""business_marketing_standing.py — Solutionist's standing OK on the marketing desk (B13).

B13 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (decision D6; Kevin
approved the design on 2026-10-07). At the `autopilot` level (Practice, the
Solutionist plan) the owner can let Chief APPROVE chosen kinds of posts
without asking each time. The grant itself is standing_permissions' (the same
storage, the same owner-only door, extended with MARKETING_KINDS); this module
is the desk's half.

THE KINDS. Exactly two, each one source of marketing_posts:

  marketing_post   Chief's weekly flyer posts            source 'plan'
  post_clip        the owner's clips folded into the week source 'clip' (B12)

Nothing else is ever approved here: the suggestion (Starter/Solo/Booked), the
open-chairs posts (Boss), the owner's and Chief's one-offs and Post now.

WHERE EACH CHECK SITS. The kind is covered (`covers`) only while ALL hold: the
grant exists and was given by the business's current owner; STANDING_PERMISSIONS
is not off; the real plan includes it (feature_gates.plan_includes
marketing_autopilot, and ai_clips for a clip) and client-facing autonomy is
enabled (standing_permissions.marketing_eligible); automations are not paused.

  grant time     standing_permissions.grant (eligible) behind its owner-only door
  approval time  approve_run, from the planner's tell_week, once the week has
                 settled (no post still designing)
  send time      send_check, from business_marketing_dispatch.dispatch, for a
                 post approved_via 'standing': not covered -> back to a draft,
                 never sent on a stale permission, the owner told
  every 2 min    lapse_sweep, from the design tick: approved standing posts of a
                 kind no longer covered go back to drafts at once

THE APPROVAL is the desk's own: business_marketing_store.approve, i.e. the
marketing_approve RPC, one post at a time (all-or-nothing per call, so one
post that moved on never holds up the others), via 'standing', actor = the
owner the permission belongs to, at the revision and content hash read. Only a
post as Chief meant it: a flyer post whose flyer is ready with no note to the
owner (a flyer Chief's own check was unsure about, or a words-only fallback,
waits for the owner), a clip post whose clip is still kept and approved at the
post's fingerprint; every account still connected and able to take it; due at
least an hour from now (time to take it back). Each one is on Chief's log:
an audit_log row and a chief_activity row naming the permission. The owner
gets ONE Today item and ONE push for the week (the planner's week tell, its
words from week_words here).

TAKE BACK. POST /marketing/{business_id}/posts/{post_id}/take-back (owner):
any approved post that has not been claimed for sending goes back to a draft.

ASK AFTER THREE, RETIRE AFTER THREE, off the posts' own history
(marketing_post_events: a snapshot of every insert and update, written by the
database). For each post: Chief's draft (the content hash once its flyer
settled), each approval (by approved_at), who approved it, and what became of
it: sent, edited (or taken back), skipped, marked not sent, withdrawn here,
failed, pulled, or still waiting.
  * Ask: the owner's last three approvals of a kind were each of Chief's draft
    unchanged and stood (not edited or skipped afterwards). Asked ONCE
    (settings.autonomy.standing_offered), with a Today item and a push; the
    approve route also answers with the question. The owner taps to grant
    (POST /agents/chief/standing).
  * Retire: the last three settled standing approvals of a kind since the
    grant were all edited, taken back, skipped or marked not sent: the grant
    is revoked (via 'retire'), its waiting posts go back to drafts and the
    owner is told. A post that went out ends the run, as in outcome_ledger.

No migration: grants live in businesses.settings.autonomy (jsonb);
marketing_posts.approved_via already allows 'standing' and marketing_approve
already takes p_via (supabase/APPLY-2026-10-07-marketing-suite.sql).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException

import business_marketing as bm
import business_marketing_store as store
import sb_clients
import standing_permissions as sp

log = logging.getLogger(__name__)

KINDS = sp.MARKETING_KINDS
KIND_SOURCES = {'marketing_post': 'plan', 'post_clip': 'clip'}
SOURCE_KINDS = {v: k for k, v in KIND_SOURCES.items()}
NAV = 'grow:marketing'

ASK_AFTER = 3
RETIRE_AFTER = 3
TAKE_BACK_LEAD = timedelta(hours=1)       # a post Chief approves is at least this far from going out
HISTORY_DAYS = 120
HISTORY_LIMIT = 1500
SWEEP_LIMIT = 500
WITHDRAW_LIMIT = 100

OVERRIDES = ('edited', 'skipped', 'not_sent')
KEPT = ('sent', 'posted_now')

# Every note a withdrawn post carries starts with this: the history reads it
# to tell Chief's own withdrawal from the owner's edit.
WITHDRAWN = "Chief's standing OK"
TURNED_OFF = 'you turned it off'
SWITCHED_OFF = 'standing permissions are switched off'
NEW_OWNER = "it was given before this business's owner changed"
PAUSED = 'automations are paused'
NOT_A_KIND = 'this kind of post always needs your OK'
RETIRED = 'you changed, skipped or marked not sent the last three it approved'
APPROVE_COLUMNS = ('id,business_id,run_id,source,status,revision,caption,publish_text,landing_url,media,targets,'
                   'run_at,expires_at,design_status,content_hash,error')
EVENT_SELECT = ('id,post_id,created_at,status:snapshot->>status,revision:snapshot->>revision,'
                'via:snapshot->>approved_via,approved_at:snapshot->>approved_at,hash:snapshot->>content_hash,'
                'approved_hash:snapshot->>approved_hash,design:snapshot->>design_status,error:snapshot->>error,'
                'run_at:snapshot->>run_at')


class Unavailable(Exception):
    """A read that failed: never the same as "not covered"."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    if not isinstance(value, str) or not value:
        return None
    try:
        out = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def kind_of(post: Dict[str, Any]) -> Optional[str]:
    """The kind a standing OK would cover for this post, or None."""
    return SOURCE_KINDS.get(str(post.get('source') or ''))


# ── the business, and whether a kind is covered ───────────────────────

def read_business(business_id: str) -> Dict[str, Any]:
    """The business row the checks read (settings and the plan's columns),
    as the service role. Raises Unavailable on a failed read, LookupError
    when it is gone."""
    try:
        rows = sb_clients.sb_get_as_service(
            f'/businesses?id=eq.{UUID(str(business_id))}&select={sp.BUSINESS_COLUMNS}&limit=1')
    except RuntimeError:
        rows = None
    if not isinstance(rows, list):
        raise Unavailable('the business could not be read')
    if not rows:
        raise LookupError('Business not found.')
    return rows[0]


def covers(biz: Dict[str, Any], kind: str) -> Tuple[bool, str]:
    """(True, '') while the owner's standing OK covers this kind of post
    right now; else (False, why) in words that fit "(...)"."""
    if kind not in KINDS:
        return False, NOT_A_KIND
    if not sp.enabled():
        return False, SWITCHED_OFF
    grant = sp.granted(biz).get(kind)
    if not grant:
        return False, TURNED_OFF
    if not biz.get('owner_id') or str(grant.get('granted_by') or '') != str(biz.get('owner_id')):
        return False, NEW_OWNER
    ok, why = sp.eligible(biz, kind)
    if not ok:
        return False, why
    try:
        import policy_engine
        if policy_engine.is_paused(biz):
            return False, PAUSED
    except Exception:
        return False, PAUSED
    return True, ''


def ready(post: Dict[str, Any]) -> bool:
    """A post as Chief meant it, with nothing for the owner to look at: a
    flyer post whose flyer is ready (no note: an unsure flyer or a
    words-only fallback waits for the owner), or a clip post with its clip."""
    kind = kind_of(post)
    media = post.get('media') if isinstance(post.get('media'), dict) else {}
    if post.get('status') != 'draft' or post.get('error'):
        return False
    if kind == 'marketing_post':
        return post.get('design_status') == 'ready' and bool(media.get('artwork_ids'))
    if kind == 'post_clip':
        return post.get('design_status') == 'none' and bool(media.get('clip_id'))
    return False


def _clip_still_good(business_id: str, media: Dict[str, Any]) -> bool:
    """The clip is still the owner's kept clip, approved at the fingerprint
    the post carries (the sender checks the same again). A failed read: no."""
    import clip_posting
    import media_library
    try:
        row = clip_posting._clip(business_id, str(UUID(str(media['clip_id']))))
    except (HTTPException, KeyError, ValueError):
        return False
    return (not clip_posting.approval_problem(row) and row.get('decision') == 'kept'
            and media_library.fingerprint(row) == media.get('clip_fingerprint'))


# ── approval time ─────────────────────────────────────────────────────

def _label(post: Dict[str, Any], tz) -> str:
    import marketing_desk as words
    when = _ts(post.get('run_at'))
    kind = 'clip post' if kind_of(post) == 'post_clip' else 'post'
    if when is None:
        return kind
    return f'{words.day_name(when, tz)} {words.clock(when, tz)} {kind}'


def _log_approval(biz: Dict[str, Any], post: Dict[str, Any], kind: str, tz) -> None:
    """Chief's log for one standing approval: what, when, which permission."""
    bid = str(biz['id'])
    grant = sp.granted(biz).get(kind) or {}
    label = _label(post, tz)
    try:
        import audit_log
        audit_log.record(bid, actor_type='chief', actor_id='standing', verb='marketing_standing_approve', ok=True,
                         summary=f'Approved on your standing OK: {label}',
                         payload={'post_id': str(post['id']), 'run_id': post.get('run_id'), 'kind': kind,
                                  'revision': post.get('revision'), 'content_hash': post.get('content_hash'),
                                  'run_at': post.get('run_at'), 'granted_at': grant.get('granted_at'),
                                  'granted_by': grant.get('granted_by')},
                         target_type='marketing_post', target_id=str(post['id']), source='standing',
                         authorized_by=f'standing:{kind}')
    except Exception:
        log.warning('marketing standing: the audit row for %s failed', str(post.get('id'))[:8], exc_info=True)
    try:
        sb_clients.sb_post_as_service('/chief_activity', {
            'user_id': biz.get('owner_id'), 'business_id': bid, 'source': 'system',
            'action_type': 'marketing_standing_approve',
            'label': f'Approved on your standing OK: {label}'[:120],
            'summary': (f"{sp.words(kind).capitalize()} (standing OK since "
                        f"{str(grant.get('granted_at') or '')[:10]}): {post.get('caption') or ''}")[:240],
            'nav': NAV,
        }, prefer='return=minimal')
    except Exception:
        log.warning('marketing standing: the activity row for %s failed', str(post.get('id'))[:8], exc_info=True)


async def approve_run(business: Dict[str, Any], run_id: Any, at: datetime, *, tz=None) -> List[str]:
    """Approve the run's drafts of every kind the owner's standing OK covers
    right now, each through marketing_approve with approved_via 'standing'
    and the owner as the actor. Returns the ids approved. Never raises; a
    read that fails approves nothing (the posts wait for the owner)."""
    try:
        bid = str(UUID(str(business['id'])))
        kinds = [k for k in KINDS if covers(business, k)[0]]
        # A retire that is due (a revoke that did not take last time) is
        # done before Chief uses the permission again; the kind is not used.
        kinds = [k for k in kinds if await retire_if_due(business, k, at) is None]
        if not kinds:
            return []
        owner = str(business['owner_id'])
        sources = ','.join(KIND_SOURCES[k] for k in kinds)
        posts = await store.rows(f'/marketing_posts?run_id=eq.{UUID(str(run_id))}&business_id=eq.{bid}'
                                 f'&status=eq.draft&source=in.({sources})&select={APPROVE_COLUMNS}'
                                 '&order=run_at.asc&limit=60')
        candidates = [p for p in posts if ready(p) and (_ts(p.get('run_at')) or at) >= at + TAKE_BACK_LEAD]
        if not candidates:
            return []
        live = {str(a['id']) for a in await bm.connected(bid)}
        if tz is None:
            import marketing_profile
            tz = await asyncio.to_thread(marketing_profile.time_zone, business)
    except (store.StoreError, HTTPException, Unavailable, KeyError, ValueError, TypeError):
        log.warning('marketing standing: the run %s could not be read for approval', str(run_id)[:8])
        return []
    except Exception:
        log.warning('marketing standing: the run %s could not be read for approval', str(run_id)[:8], exc_info=True)
        return []
    done: List[str] = []
    for post in candidates:
        kind = kind_of(post)
        targets = [t for t in post.get('targets') or [] if isinstance(t, dict)]
        if not targets or any(str(t.get('connection_id')) not in live for t in targets):
            continue
        _, dropped = bm.fit(targets, bm.media_kind(post.get('media')))
        if dropped:
            continue
        try:
            if post.get('content_hash') != store.digest(post):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if kind == 'post_clip' and not await asyncio.to_thread(_clip_still_good, bid, post.get('media') or {}):
            continue
        try:
            n = await store.approve(bid, [{'id': str(post['id']), 'revision': int(post['revision']),
                                           'content_hash': post['content_hash']}], actor=owner, via='standing')
        except store.StoreConflict:
            continue                        # it moved on (the owner changed it, its time passed): theirs now
        except (store.StoreUnavailable, ValueError):
            log.warning('marketing standing: approving %s did not answer', str(post['id'])[:8])
            break
        if n == 1:
            done.append(str(post['id']))
            await asyncio.to_thread(_log_approval, business, post, kind, tz)
    return done


def week_words(approved: int, waiting: int, which: Optional[str]) -> Dict[str, str]:
    """The week's one Today item and push when Chief approved some of it:
    'Chief approved 5 posts for next week under your standing OK'."""
    many = approved != 1
    title = (f"Chief approved {approved} post{'s' if many else ''} for {which or 'next week'} "
             'under your standing OK')
    body = (f"Review or take back {'any' if many else 'it'} before {'they go' if many else 'it goes'} out: "
            'each one waits on the desk until its time.')
    if waiting:
        body += (f" {waiting} more {'wait' if waiting != 1 else 'waits'} for your OK; nothing else posts until "
                 'you approve it.')
    return {'title': title, 'body': body}


# ── going back to waiting ─────────────────────────────────────────────

def withdrawn_note(why: str) -> str:
    return f"{WITHDRAWN} no longer covers this post ({why}), so it waits for your OK."


def withdrawn_patch(row: Dict[str, Any], why: str) -> Dict[str, Any]:
    """An approved (or claimed) standing post back to a draft: the approval
    dropped, the next revision, the reason in its note. Its content and
    hash are unchanged, so the owner can approve it as it is."""
    return {'status': 'draft', 'revision': int(row.get('revision') or 1) + 1, 'approved_hash': None,
            'approved_by': None, 'approved_at': None, 'approved_via': None, 'claimed_at': None,
            'error': withdrawn_note(why)}


def _already_told(business_id: str, key: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f'/chief_notifications?business_id=eq.{business_id}&action_payload->>dedup_key=eq.{key}&select=id&limit=1')
    if rows is None:
        return None
    return bool(rows)


def _tell(biz: Dict[str, Any], title: str, body: str, key: str, *, extra: Optional[Dict[str, Any]] = None,
          action: str = 'Open the desk') -> bool:
    """One Today item and one push, once per key. If what was said cannot be
    read, nothing is said rather than risk saying it twice."""
    bid = str(biz.get('id'))
    if _already_told(bid, key) is not False:
        return False
    saved = sb_clients.sb_post_as_service('/chief_notifications', {
        'business_id': bid, 'type': 'reminder', 'priority': 'normal', 'title': title[:120], 'body': body[:300],
        'suggested_action': action,
        'action_payload': {'type': 'navigate', 'tab': 'grow', 'sub': 'marketing', **(extra or {}), 'dedup_key': key},
    })
    if not saved:
        return False
    if biz.get('owner_id'):
        try:
            import push_notifications
            push_notifications.send_to_user(str(biz['owner_id']), title=title[:80], body=body[:160], nav=NAV,
                                            tag=f"marketing-standing-{hashlib.sha256(key.encode()).hexdigest()[:12]}")
        except Exception:
            log.warning('marketing standing: a push failed', exc_info=True)
    return True


def _tell_withdrawn(biz: Dict[str, Any], posts: List[Dict[str, Any]], why: str) -> bool:
    n = len(posts)
    marks = ','.join(sorted(f"{p['id']}:{p.get('revision')}" for p in posts))
    key = f"marketing_standing_held:{hashlib.sha256(marks.encode()).hexdigest()[:24]}"
    title = "Chief's standing OK no longer covers your posts"
    body = (f"{why[:1].upper()}{why[1:]}, so {n} post{'s' if n != 1 else ''} Chief approved "
            f"{'are' if n != 1 else 'is'} back to waiting for your OK. Nothing goes out until you approve "
            f"{'them' if n != 1 else 'it'}.")
    return _tell(biz, title, body, key, action='Review the posts')


async def withdraw(biz: Dict[str, Any], kinds: Iterable[str], why: str, *, tell: bool = True,
                   also: Iterable[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """Every approved, not yet claimed post of these kinds that Chief approved
    on the standing OK goes back to a draft, each only as it was read.
    `also`: posts already put back by the caller (the sender), told with
    these. Raises store.StoreError when the posts cannot be read."""
    bid = str(UUID(str(biz['id'])))
    sources = ','.join(KIND_SOURCES[k] for k in kinds if k in KIND_SOURCES)
    done: List[Dict[str, Any]] = []
    if sources:
        rows = await store.rows(f'/marketing_posts?business_id=eq.{bid}&status=eq.approved&approved_via=eq.standing'
                                f'&source=in.({sources})&select=id,revision,source,run_at'
                                f'&order=run_at.asc&limit={WITHDRAW_LIMIT}')
        for row in rows:
            out = await store.request(
                'PATCH', f"/marketing_posts?id=eq.{UUID(str(row['id']))}&business_id=eq.{bid}"
                         f"&revision=eq.{int(row['revision'])}&status=eq.approved&approved_via=eq.standing",
                withdrawn_patch(row, why))
            if isinstance(out, list) and out:
                done.append(out[0])
    told = list(also) + done
    if tell and told:
        await asyncio.to_thread(_tell_withdrawn, biz, told, why)
    return done


# ── send time ─────────────────────────────────────────────────────────

def send_check(business_id: str, row: Dict[str, Any]) -> Optional[str]:
    """For a post approved on the standing OK, just before it is handed
    over: None while the standing OK still covers it, else why not. Raises
    Unavailable when the business cannot be read (the sender then holds it
    and tries again; never sent on a guess)."""
    kind = kind_of(row)
    if not kind:
        return NOT_A_KIND
    try:
        biz = read_business(business_id)
    except LookupError:
        return NEW_OWNER
    ok, why = covers(biz, kind)
    return None if ok else why


async def after_send_withdrawal(business_id: str, row: Dict[str, Any], why: str) -> None:
    """The sender put a post back to waiting: put back the rest of its kind
    too, and tell the owner once. Best-effort."""
    try:
        biz = await asyncio.to_thread(read_business, business_id)
        kind = kind_of(row)
        await withdraw(biz, [kind] if kind else [], why,
                       also=[{'id': str(row['id']), 'revision': int(row.get('revision') or 1) + 1}])
    except Exception:
        log.warning('marketing standing: after a send-time withdrawal of %s', str(row.get('id'))[:8],
                    exc_info=True)


# ── every two minutes ─────────────────────────────────────────────────

async def lapse_sweep(*, only: str = '', on_for=None) -> Counter:
    """Posts Chief approved on the standing OK whose kind it no longer
    covers go back to drafts at once. The owner is told, unless they
    turned the permission off themselves (they know)."""
    tally: Counter = Counter()
    try:
        rows = await store.rows(f'/marketing_posts?status=eq.approved&approved_via=eq.standing{only}'
                                f'&select=business_id,source&limit={SWEEP_LIMIT}')
    except store.StoreError:
        tally['standing_unreadable'] += 1
        return tally
    by_business: Dict[str, set] = {}
    for r in rows:
        kind = kind_of(r)
        if kind and (on_for is None or on_for(r.get('business_id'))):
            by_business.setdefault(str(r['business_id']), set()).add(kind)
    for bid, kinds in by_business.items():
        try:
            biz = await asyncio.to_thread(read_business, bid)
        except (Unavailable, LookupError):
            tally['standing_unreadable'] += 1
            continue
        for kind in sorted(kinds):
            ok, why = covers(biz, kind)
            if ok:
                continue
            try:
                done = await withdraw(biz, [kind], why, tell=why != TURNED_OFF)
            except store.StoreError:
                tally['standing_unreadable'] += 1
                continue
            tally['standing_withdrawn'] += len(done)
    return tally


# ── the history: ask after three, retire after three ──────────────────

def _settled(last: Optional[str], error: Any) -> str:
    if last == 'cancelled':
        return 'skipped'
    if last == 'failed':
        return 'not_sent' if error == bm.NOT_SENT_NOTE else 'failed'
    if last in ('submitted', 'published', 'partly_published', 'uncertain'):
        return 'sent'
    if last == 'pulled':
        return 'pulled'
    return 'waiting'


def _posted_now(cleared: Dict[str, Any], nxt: Optional[Dict[str, Any]]) -> bool:
    """The desk's Post now on an approved post: the move to two minutes out
    (approval cleared) and the owner's own approval right after."""
    if not nxt or nxt.get('via') != 'owner' or not nxt.get('approved_at'):
        return False
    run_at, approved = _ts(cleared.get('run_at')), _ts(nxt.get('approved_at'))
    return bool(run_at and approved and abs(run_at - approved) <= timedelta(minutes=10))


def approvals_from(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each approval in these posts' history: {post_id, via, at, hash,
    chief_hash, fate}. A post whose first snapshot is not in the events
    (history older than the window) is left out: its draft is unknown.

    fate: sent (handed over), posted_now (the owner sent it now), edited
    (changed or taken back while waiting), skipped, not_sent (the owner
    marked it), withdrawn (Chief's own, here), failed, pulled, waiting."""
    by_post: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        by_post.setdefault(str(e.get('post_id')), []).append(e)
    out: List[Dict[str, Any]] = []
    for pid, evs in by_post.items():
        evs.sort(key=lambda e: int(e.get('id') or 0))
        if not any(str(e.get('revision')) == '1' for e in evs):
            continue
        chief_hash = next((e.get('hash') for e in evs if e.get('design') != 'designing'), None)
        found: Dict[str, Dict[str, Any]] = {}
        order: List[Dict[str, Any]] = []
        cur: Optional[Dict[str, Any]] = None
        for i, e in enumerate(evs):
            at, via = e.get('approved_at'), e.get('via')
            if at and via in store.APPROVED_VIA:
                rec = found.get(at)
                if rec is None:
                    rec = {'post_id': pid, 'via': via, 'at': at, 'hash': e.get('approved_hash'),
                           'chief_hash': chief_hash, 'fate': None, 'settled_at': None, 'now': None}
                    found[at] = rec
                    order.append(rec)
                else:
                    rec['fate'] = None              # put back as it was (a refused Post now)
                rec['last'], rec['error'] = e.get('status'), e.get('error')
                state = _settled(rec['last'], rec['error'])
                if state != rec['now']:
                    # When what became of it last changed (not the delivery
                    # watch's later updates of the same outcome).
                    rec['now'], rec['settled_at'] = state, e.get('created_at')
                cur = rec
            elif cur is not None:
                if cur['fate'] is None and cur.get('last') in ('approved', 'dispatching'):
                    if str(e.get('error') or '').startswith(WITHDRAWN):
                        cur['fate'] = 'withdrawn'
                    elif _posted_now(e, evs[i + 1] if i + 1 < len(evs) else None):
                        cur['fate'] = 'posted_now'
                    else:
                        cur['fate'] = 'edited'
                    cur['settled_at'] = e.get('created_at')
                cur = None
        for rec in order:
            if rec['fate'] is None:
                rec['fate'] = _settled(rec.get('last'), rec.get('error'))
            out.append({k: rec[k] for k in ('post_id', 'via', 'at', 'hash', 'chief_hash', 'fate', 'settled_at')})
    return out


async def history(business_id: str, kind: str, at: datetime) -> List[Dict[str, Any]]:
    """This kind's approvals over the last HISTORY_DAYS, from the posts' own
    snapshots. Raises store.StoreError when they cannot be read."""
    since = _z(at - timedelta(days=HISTORY_DAYS))
    rows = await store.rows(f'/marketing_post_events?business_id=eq.{UUID(str(business_id))}'
                            f'&snapshot->>source=eq.{KIND_SOURCES[kind]}&created_at=gte.{since}'
                            f'&select={EVENT_SELECT}&order=id.desc&limit={HISTORY_LIMIT}')
    return approvals_from(rows)


def earns_offer(approvals: List[Dict[str, Any]]) -> bool:
    """The owner's last ASK_AFTER posts of the kind were each approved as
    Chief drafted them, and stood."""
    latest: Dict[str, Dict[str, Any]] = {}
    for a in approvals:
        if a['via'] != 'owner':
            continue
        if a['post_id'] not in latest or str(a['at']) > str(latest[a['post_id']]['at']):
            latest[a['post_id']] = a
    last = sorted(latest.values(), key=lambda a: _ts(a['at']) or datetime.min.replace(tzinfo=timezone.utc),
                  reverse=True)[:ASK_AFTER]
    return len(last) >= ASK_AFTER and all(
        a['hash'] and a['hash'] == a['chief_hash'] and a['fate'] not in ('edited', 'skipped') for a in last)


def retires(approvals: List[Dict[str, Any]], since: Optional[datetime]) -> bool:
    """The last RETIRE_AFTER settled standing approvals since the grant
    (latest outcome first: a week is approved all at once, so it is the
    owner's last three reactions that count) were all overridden by the
    owner (edited, taken back, skipped, marked not sent). One that went out
    ends the run."""
    floor = datetime.min.replace(tzinfo=timezone.utc)
    settled = [a for a in approvals
               if a['via'] == 'standing' and a['fate'] in OVERRIDES + KEPT
               and (since is None or (_ts(a['at']) or since) >= since)]
    last = sorted(settled, key=lambda a: (_ts(a.get('settled_at')) or _ts(a['at']) or floor, _ts(a['at']) or floor),
                  reverse=True)[:RETIRE_AFTER]
    return len(last) >= RETIRE_AFTER and all(a['fate'] in OVERRIDES for a in last)


def _offer_said(biz: Dict[str, Any], kind: str, offer: Dict[str, Any]) -> bool:
    title = f"Want Chief to approve your {sp.words(kind)}?"
    return _tell(biz, title, offer['question'], f'marketing_standing_offer:{kind}',
                 extra={'standing_offer': kind}, action='Answer on the desk')


async def after_owner_approval(business_id: str, approved: List[Dict[str, Any]],
                               at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """After the owner approved posts on the desk: the one-time question, or
    None. Best-effort: it never touches the approval itself."""
    at = at or _now()
    kinds = list(dict.fromkeys(k for k in (kind_of(r) for r in approved) if k))
    if not kinds or not sp.enabled():
        return None
    try:
        biz = await asyncio.to_thread(read_business, business_id)
    except (Unavailable, LookupError):
        return None
    for kind in kinds:
        if not sp.eligible(biz, kind)[0] or kind in sp.granted(biz) or sp.offered(biz, kind):
            continue
        declined = (sp._autonomy(biz).get('standing_declined') or {})
        if isinstance(declined, dict) and declined.get(kind):
            continue
        try:
            if not earns_offer(await history(business_id, kind, at)):
                continue
        except store.StoreError:
            continue
        if not await asyncio.to_thread(sp.mark_offered, str(biz['id']), kind):
            continue
        offer = {'verb': kind, 'kind': sp.words(kind), 'count': ASK_AFTER, 'question': sp.question(kind)}
        try:
            await asyncio.to_thread(_offer_said, biz, kind, offer)
        except Exception:
            log.warning('marketing standing: the question could not be said', exc_info=True)
        return offer
    return None


def _tell_retired(biz: Dict[str, Any], kind: str, grant: Dict[str, Any]) -> bool:
    title = f"I'm back to asking before your {sp.words(kind)}"
    body = (f"You changed, skipped or marked not sent the last {RETIRE_AFTER} {sp.words(kind)} I approved on my "
            'own, so I turned that standing OK off. Every one waits for your OK again; you can turn it back on '
            'from the marketing desk.')
    return _tell(biz, title, body, f"marketing_standing_retired:{kind}:{grant.get('granted_at') or ''}")


async def _revoked(business_id: str, kind: str) -> bool:
    """Retire the grant; True only when it is gone. A write that failed
    (WriteFailed: the patch answered nothing) or found nothing to revoke is
    False. A write that landed is then confirmed by a fresh read: still
    granted there is False; a read that fails trusts the landed write."""
    try:
        if not await asyncio.to_thread(sp.revoke, str(business_id), kind, by='chief', via='retire',
                                       reason=RETIRED):
            return False
    except sp.WriteFailed as e:
        log.warning('marketing standing: the retire of %s was not saved: %s', kind, e)
        return False
    try:
        fresh = await asyncio.to_thread(read_business, business_id)
    except (Unavailable, LookupError):
        return True
    return kind not in sp.granted(fresh)


async def after_override(business_id: str, rows: List[Dict[str, Any]], at: Optional[datetime] = None) -> List[str]:
    """The owner edited, took back, skipped or marked not sent posts Chief
    approved on the standing OK: three in a row retire it. Returns the kinds
    retired. Best-effort: never touches the owner's own change."""
    at = at or _now()
    kinds = list(dict.fromkeys(k for k in (kind_of(r) for r in rows if r.get('approved_via') == 'standing') if k))
    if not kinds:
        return []
    try:
        biz = await asyncio.to_thread(read_business, business_id)
    except (Unavailable, LookupError):
        return []
    retired: List[str] = []
    for kind in kinds:
        if await retire_if_due(biz, kind, at) == 'retired':
            retired.append(kind)
    return retired


async def retire_if_due(biz: Dict[str, Any], kind: str, at: datetime) -> Optional[str]:
    """Retire this kind's grant when its history says so (retires): 'retired'
    once the grant is confirmed gone, its waiting posts are put back and the
    owner is told; 'not_saved' when it is due but the revoke did not take
    (nothing withdrawn, nothing said; tried again at the next override and
    before Chief next approves anything on it); None when it is not due, or
    the history cannot be read."""
    business_id = str(biz['id'])
    grant = sp.granted(biz).get(kind)
    if not grant:
        return None
    try:
        if not retires(await history(business_id, kind, at), _ts(grant.get('granted_at'))):
            return None
    except store.StoreError:
        log.warning('marketing standing: the history of %s for %s could not be read', kind, business_id[:8])
        return None
    if not await _revoked(business_id, kind):
        log.warning('marketing standing: retiring %s for %s did not take; left as it was', kind, business_id[:8])
        return 'not_saved'
    try:
        await withdraw(biz, [kind], RETIRED, tell=False)
    except store.StoreError:
        pass                            # the sweep and the sender's own check catch the rest
    try:
        await asyncio.to_thread(_tell_retired, biz, kind, grant)
    except Exception:
        log.warning('marketing standing: the owner could not be told of a retire', exc_info=True)
    return 'retired'


# ── what the desk shows ───────────────────────────────────────────────

def desk_block(biz: Dict[str, Any]) -> Dict[str, Any]:
    """GET /engine's `standing`: per kind, whether the plan allows it, the
    grant, whether it covers posts right now (and why not), and Chief's open
    question. Members read it; only the owner changes it (POST
    /agents/chief/standing)."""
    out = []
    grants = sp.granted(biz)
    declined = sp._autonomy(biz).get('standing_declined') or {}
    for kind in KINDS:
        available, why = sp.eligible(biz, kind)
        grant = grants.get(kind)
        active, held = covers(biz, kind) if grant else (False, '')
        open_offer = (available and not grant and bool(sp.offered(biz, kind))
                      and not (isinstance(declined, dict) and declined.get(kind)))
        out.append({'kind': kind, 'label': sp.words(kind), 'available': available, 'why': None if available else why,
                    'granted': bool(grant), 'since': (grant or {}).get('granted_at'),
                    'active': bool(grant) and active, 'held': held if grant and not active else None,
                    'offer': sp.question(kind) if open_offer else None})
    return {'kinds': out, 'ask_after': ASK_AFTER, 'retire_after': RETIRE_AFTER}

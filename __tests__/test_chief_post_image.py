"""Chief posts a picture to the connected accounts (chief_social_actions.post_image).
No live services.

  1. Which picture: by id; "latest" (the newest ready design of the day,
     asked about when two were made together); none, for words only.
  2. Every refusal is plain words with a result and a label, says nothing
     was posted, and nothing is prepared or sent.
  3. Where it goes: every connected account that can take it, or the
     networks asked for; one asked for with no account is refused.
  4. Never twice: the same turn asking again returns the first post; a new
     turn with the same post is caught by the day's guard.
  5. Unattended runs are held, at the handler and through the door;
     schedule_action will not wrap it.
  6. The registry: class C, client-facing, registered, never an agent tool.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

import action_registry
import chief_of_staff as cos
import chief_social_actions as csa
import image_posting as ip
import image_studio as images
import policy_engine
import post_for_me as pfm
import sb_clients
from __tests__._social_fakes import (BIZ, FLYER, FLYER_PREFIX, MANAGER, OTHER, OWNER, THEIRS, ago, art,
                                     install, jpeg_link)

BIZ_ROW = {'id': BIZ, 'owner_id': OWNER, 'name': 'Fade Street Barbers', 'type': 'barber', 'settings': {}}
NEWER, OLDER, COVER, UPLOAD = (str(uuid4()) for _ in range(4))

# Back-room names a practitioner must never read (CLAUDE.md).
FORBIDDEN = re.compile(r'\b(post for me|provider|api|github|claude|builder)\b', re.I)
# A post is "sent" or "scheduled": the networks report back later.
CLAIMS_POSTED = re.compile(r'^posted\b|\b(?<!nothing )(was|were|been|is) posted\b|\bposted (it|your|to)\b', re.I)


@pytest.fixture
def s(monkeypatch):
    state = install(monkeypatch)
    user_token = cos._TURN_USER_ID.set(OWNER)
    turn_token = images.turn_id.set('turn-1')
    state.turn = lambda t: images.turn_id.set(t)
    state.user = lambda u: cos._TURN_USER_ID.set(u)
    yield state
    images.turn_id.reset(turn_token)
    cos._TURN_USER_ID.reset(user_token)


def run(action, biz=BIZ_ROW):
    return asyncio.run(cos.ACTION_HANDLERS['post_image'](None, biz, {'type': 'post_image', **action}))


def plain(out):
    """A card the app can always show: both keys, real words, no back-room names."""
    assert isinstance(out.get('result'), str) and out['result'].strip()
    assert isinstance(out.get('label'), str) and out['label'].strip()
    assert not FORBIDDEN.search(out['result'] + ' ' + out['label']), out
    assert not CLAIMS_POSTED.search(out['result']) and not CLAIMS_POSTED.search(out['label']), out
    return out


def refused(s, out):
    plain(out)
    assert out['failed'] is True and out['ok'] is False and cos._action_failed(out)
    assert 'nothing' in out['result'].lower()
    assert s.sent == [] and s.db.pubs == [] and s.originals == [] and s.stored == []
    return out


def sent(out):
    plain(out)
    assert out['ok'] is True and out.get('failed') is not True and not cos._action_failed(out)
    return out


# ─── 1. which picture ────────────────────────────────────────────────

def test_by_id_it_goes_to_every_connected_account(s):
    out = sent(run({'image_id': FLYER, 'caption': 'Saturday fades. Book at the link.'}))
    assert sorted(s.sent[0]['account_ids']) == ['spc_fb', 'spc_ig']
    assert s.sent[0]['media_urls'] == [jpeg_link(FLYER)]
    assert out['label'] == 'Sent your design to Instagram and Facebook'
    assert out['result'].startswith('Sent “Saturday fade special” to Instagram (fadestreet) and Facebook (Fade Street)')
    assert 'the caption “Saturday fades. Book at the link.”' in out['result']
    assert 'Build, Social Media' in out['result'] and out['nav'] == {'tab': 'build', 'sub': 'social-media'}
    assert out['image_id'] == FLYER and s.db.pubs[0]['approved_by'] == OWNER


def test_a_photo_is_called_a_picture(s):
    s.db.artworks.append(art(UPLOAD, prompt='IMG_0412.jpg', model=None))
    out = sent(run({'image_id': UPLOAD, 'caption': 'Fresh cut.'}))
    assert out['label'] == 'Sent your picture to Instagram and Facebook'


def test_latest_takes_the_newest_design_of_the_day(s):
    s.db.artworks += [
        art(OLDER, goal='Last week special', at=ago(days=2)),
        art(NEWER, goal='Fall fade special', at=ago(minutes=5)),
        # Newer still, but none of them is a design to post:
        art(COVER, goal='A clip cover', at=ago(minutes=1), clip_id=str(uuid4())),
        art(UPLOAD, prompt='IMG_0412.jpg', model=None, at=ago(minutes=2)),
        art(str(uuid4()), prompt='Website screenshot from https://example.com', model=None, at=ago(minutes=3)),
        art(str(uuid4()), status='working', at=ago(minutes=1)),
    ]
    out = sent(run({'image': 'latest', 'caption': 'Fall fades are here.'}))
    assert out['image_id'] == NEWER and '“Fall fade special”' in out['result']


def test_latest_counts_a_composed_flyer(s):
    s.db.artworks.append(art(NEWER, prompt=FLYER_PREFIX + '{"title": "Open chairs"}', model=None, at=ago(minutes=4)))
    out = sent(run({'image': 'latest', 'caption': 'Open chairs today.'}))
    assert out['image_id'] == NEWER and '“Open chairs”' in out['result']


def test_latest_asks_when_two_were_made_together(s):
    s.db.artworks += [art(NEWER, goal='Fade special, bold', at=ago(minutes=3)),
                      art(OLDER, goal='Fade special, calm', at=ago(minutes=9))]
    out = refused(s, run({'image': 'latest', 'caption': 'Fades.'}))
    assert out['label'] == 'Which design?'
    assert [d['image_id'] for d in out['designs']] == [NEWER, OLDER]
    assert '“Fade special, bold” (made 3 minutes ago, id ' + NEWER + ')' in out['result']
    assert OLDER in out['result'] and 'Which one should I post?' in out['result']


def test_latest_with_nothing_from_the_last_day(s):
    s.db.artworks = [art(FLYER, at=ago(days=2))]
    out = refused(s, run({'image': 'latest', 'caption': 'Fades.'}))
    assert out['label'] == 'Which design?' and 'last day' in out['result']


def test_latest_read_failing_posts_nothing(s):
    s.db.fail = ('created_at=gte',)
    assert "couldn't read your designs" in refused(s, run({'image': 'latest', 'caption': 'x'}))['result']


def test_an_unknown_image_word_is_asked_about(s):
    assert refused(s, run({'image': 'the blue one', 'caption': 'x'}))['label'] == 'Which design?'


def test_an_id_in_the_image_field_is_used(s):
    out = sent(run({'image': FLYER, 'caption': 'Fades.'}))
    assert out['image_id'] == FLYER


# ─── 2. refusals ──────────────────────────────────────────────────────

def test_an_unattended_run_is_held_before_anything_is_read(s):
    out = refused(s, run({'image_id': FLYER, 'caption': 'x', '_unattended': True}))
    assert 'only when you ask me' in out['result'] and s.db.reads == []


def test_no_signed_in_turn_posts_nothing(s):
    s.user('')
    out = refused(s, run({'image_id': FLYER, 'caption': 'x'}))
    assert 'owner asks me in chat' in out['result'] and s.db.reads == []


def test_only_the_owner_and_nothing_is_read_first(s):
    s.user(MANAGER)
    out = refused(s, run({'image_id': FLYER, 'caption': 'x'}))
    assert out['label'] == 'Only the owner can post'
    assert not any(r.startswith(('/social_connections', '/image_artworks')) for r in s.db.reads)


def test_posting_switched_off_for_the_business(s, monkeypatch):
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', OTHER)
    assert "isn't switched on" in refused(s, run({'image_id': FLYER, 'caption': 'x'}))['result']


def test_posting_not_set_up(s, monkeypatch):
    monkeypatch.delenv('POST_FOR_ME_API_KEY')
    assert "isn't set up" in refused(s, run({'image_id': FLYER, 'caption': 'x'}))['result']


def test_no_account_connected(s):
    s.db.connections = [c for c in s.db.connections if c['business_id'] != BIZ or c['status'] != 'connected']
    out = refused(s, run({'image_id': FLYER, 'caption': 'x'}))
    assert 'Connect an account in Build, Social Media' in out['result']
    assert out['nav'] == {'tab': 'build', 'sub': 'social-media'}


def test_a_failed_accounts_read_posts_nothing(s):
    s.db.fail = ('/social_connections',)
    assert "couldn't read your connected accounts" in refused(s, run({'image_id': FLYER, 'caption': 'x'}))['result']


def test_another_business_s_design_is_refused(s):
    out = refused(s, run({'image_id': THEIRS, 'caption': 'x'}))
    assert out['label'] == 'Design not found' and out['nav'] == {'tab': 'build', 'page': 'media-library'}


def test_a_design_not_ready_yet(s):
    s.db.artworks[0] = art(FLYER, status='working')
    assert refused(s, run({'image_id': FLYER, 'caption': 'x'}))['label'] == 'Design not ready yet'
    s.db.artworks[0] = art(FLYER, status='failed')
    assert refused(s, run({'image_id': FLYER, 'caption': 'x'}))['label'] == 'Design not finished'


def test_a_failed_design_read_posts_nothing(s):
    s.db.fail = ('/image_artworks',)
    assert "couldn't read that design" in refused(s, run({'image_id': FLYER, 'caption': 'x'}))['result']


def test_a_time_in_the_past(s):
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    out = refused(s, run({'image_id': FLYER, 'caption': 'x', 'when': past}))
    assert out['label'] == 'That time has passed' and 'already passed' in out['result']


@pytest.mark.parametrize('when', ['next thursday', '2026-12-01T09:00:00'])
def test_a_time_that_does_not_read_or_has_no_zone(s, when):
    refused(s, run({'image_id': FLYER, 'caption': 'x', 'when': when}))


def test_a_time_more_than_90_days_out(s):
    far = (datetime.now(timezone.utc) + timedelta(days=120)).isoformat()
    out = refused(s, run({'image_id': FLYER, 'caption': 'x', 'when': far}))
    assert '90 days' in out['result'] and 'Nothing was posted' in out['result']


def test_a_failed_duplicate_read_posts_nothing(s):
    s.db.fail = ('approved_hash=',)
    out = refused(s, run({'image_id': FLYER, 'caption': 'x'}))
    assert 'earlier post' in out['result']


def test_a_refused_hand_off_says_nothing_went_out(s, monkeypatch):
    async def refuse(**kw):
        s.sent.append(kw)
        raise pfm.PostForMeError('answered 422.', 422)
    monkeypatch.setattr(pfm, 'create_post', refuse)
    out = plain(run({'image_id': FLYER, 'caption': 'x'}))
    assert out['failed'] is True and 'nothing went out' in out['result']
    assert s.db.pubs[0]['status'] == 'failed'


def test_a_picture_that_cannot_be_prepared_stops_the_post(s, monkeypatch):
    async def broken(client, row):
        raise ip.HTTPException(502, 'The original image could not be loaded.')
    monkeypatch.setattr(images, 'original', broken)
    out = refused(s, run({'image_id': FLYER, 'caption': 'x'}))
    assert 'could not be prepared' in out['result'] and images.build_actor.get() is None


def test_network_rules_still_apply(s):
    s.db.connections.append({'id': 'c-x', 'business_id': BIZ, 'status': 'connected', 'platform': 'x',
                             'username': 'fade', 'provider_account_id': 'spc_x'})
    out = refused(s, run({'image_id': FLYER, 'platforms': ['twitter'], 'caption': 'x' * 281}))
    assert '280' in out['result']


def test_a_crash_is_still_a_plain_refusal(s, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError('kaboom')
    monkeypatch.setattr(ip, 'post_image_for', boom)
    out = refused(s, run({'image_id': FLYER, 'caption': 'x'}))
    assert 'kaboom' not in out['result']


# ─── 3. where it goes ─────────────────────────────────────────────────

def test_the_networks_asked_for_and_only_those(s):
    out = sent(run({'image_id': FLYER, 'platforms': ['ig'], 'caption': 'x'}))
    assert s.sent[0]['account_ids'] == ['spc_ig'] and out['label'] == 'Sent your design to Instagram'


def test_a_network_with_no_account_is_refused_not_dropped(s):
    out = refused(s, run({'image_id': FLYER, 'platforms': ['instagram', 'linkedin'], 'caption': 'x'}))
    assert 'No LinkedIn account is connected' in out['result'] and 'Instagram (fadestreet)' in out['result']


def test_a_disconnected_or_another_business_s_account_is_never_used(s):
    refused(s, run({'image_id': FLYER, 'platforms': ['x'], 'caption': 'x'}))
    sent(run({'image_id': FLYER, 'caption': 'x'}))
    assert not {'spc_x_old', 'spc_o'} & set(s.sent[0]['account_ids'])


def test_a_video_only_network_is_left_out_and_said(s):
    s.db.connections.append({'id': 'c-tt', 'business_id': BIZ, 'status': 'connected', 'platform': 'tiktok',
                             'username': 'fadestreet', 'provider_account_id': 'spc_tt'})
    out = sent(run({'image_id': FLYER, 'caption': 'x'}))
    assert 'spc_tt' not in s.sent[0]['account_ids']
    assert 'TikTok takes only videos, so the design didn' in out['result']
    assert out['dropped'] == [{'platform': 'tiktok', 'username': 'fadestreet', 'why': 'needs_video'}]


def test_words_only_leave_instagram_out_and_say_so(s):
    out = sent(run({'caption': 'Open chairs today until 5.'}))
    assert s.sent[0]['account_ids'] == ['spc_fb'] and s.sent[0]['media_urls'] == []
    assert out['label'] == 'Sent your post to Facebook'
    assert 'the words “Open chairs today until 5.”' in out['result']
    assert 'Instagram needs a picture, so this post didn' in out['result']
    assert s.originals == [] and s.stored == []


def test_words_only_to_instagram_alone_posts_nothing(s):
    out = refused(s, run({'caption': 'Open chairs today.', 'platforms': ['instagram']}))
    assert 'Instagram needs a picture' in out['result']


def test_words_only_with_no_words_asks_what_to_say(s):
    out = refused(s, run({'caption': '  '}))
    assert out['label'] == 'What should it say?'


# ─── 4. a time, and never twice ───────────────────────────────────────

def test_a_scheduled_post_says_when_in_the_owner_s_time(s):
    zone = timezone(timedelta(hours=-4))
    at = (datetime.now(zone) + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
    out = sent(run({'image_id': FLYER, 'caption': 'x', 'when': at.isoformat()}))
    assert out['publication']['status'] == 'scheduled'
    assert out['label'] == f'Scheduled your design for {at:%A} {at:%b} {at.day}, 9:00 AM'
    assert 'cancel it in Build, Social Media' in out['result']
    assert s.sent[0]['scheduled_at'] and s.db.pubs[0]['status'] == 'scheduled'


def test_the_same_turn_twice_posts_once(s):
    first = sent(run({'image_id': FLYER, 'platforms': ['instagram', 'facebook'], 'caption': 'x'}))
    again = sent(run({'image_id': FLYER, 'platforms': ['facebook', 'instagram'], 'caption': 'x'}))
    assert first['already'] is False and again['already'] is True
    assert len(s.sent) == 1 and len(s.db.pubs) == 1
    assert again['publication']['id'] == first['publication']['id']
    assert again['label'] == 'Already sent, not posted twice'


def test_latest_twice_in_a_turn_posts_once(s):
    s.db.artworks.append(art(NEWER, goal='Fall fade special', at=ago(minutes=5)))
    sent(run({'image': 'latest', 'caption': 'x'}))
    again = sent(run({'image': 'latest', 'caption': 'x'}))
    assert again['already'] is True and len(s.sent) == 1


def test_a_new_turn_with_the_same_post_is_caught_by_the_day_s_guard(s):
    run({'image_id': FLYER, 'caption': 'x'})
    s.turn('turn-2')
    out = sent(run({'image_id': FLYER, 'caption': 'x'}))
    assert out['already'] is True and len(s.sent) == 1 and len(s.db.pubs) == 1


def test_different_words_in_the_same_turn_are_a_different_post(s):
    run({'image_id': FLYER, 'caption': 'x'})
    assert sent(run({'image_id': FLYER, 'caption': 'Another line'}))['already'] is False
    assert len(s.sent) == 2


def test_chief_calls_the_one_post_function(s, monkeypatch):
    seen = []
    real = ip.post_image_for

    async def spy(*a, **k):
        seen.append((a, k))
        return await real(*a, **k)
    monkeypatch.setattr(ip, 'post_image_for', spy)
    run({'image_id': FLYER, 'caption': ' Fades. '})
    (args, kw), = seen
    assert args == (BIZ, OWNER, FLYER)
    assert kw['caption'] == 'Fades.' and kw['scheduled_at'] is None
    assert sorted(kw['connection_ids']) == ['c-fb', 'c-ig']


# ─── 5. unattended ────────────────────────────────────────────────────

def _quiet_policy(monkeypatch):
    seen = []

    class _V:
        allowed, rule, reason = True, 'spy', 'ok'

    def evaluate(business_id, *, verb, surface, prompted, user_id=None, biz_row=None):
        seen.append({'verb': verb, 'surface': surface, 'prompted': prompted})
        return _V()
    monkeypatch.setattr(policy_engine, 'evaluate', evaluate)
    return seen


def test_through_the_door_unattended_is_held_and_cannot_claim_otherwise(s, monkeypatch):
    seen = _quiet_policy(monkeypatch)
    taken = asyncio.run(cos._execute_actions(
        None, BIZ_ROW, [{'type': 'post_image', 'image_id': FLYER, 'caption': 'x', '_unattended': False}],
        user_id=OWNER, surface='agent', prompted=False))
    assert seen == [{'verb': 'post_image', 'surface': 'agent', 'prompted': False}]
    refused(s, taken[0])
    assert 'only when you ask me' in taken[0]['result']


def test_through_the_door_when_the_owner_asks_it_sends(s, monkeypatch):
    _quiet_policy(monkeypatch)
    cos._UNTRUSTED_TAINT.set(0)
    taken = asyncio.run(cos._execute_actions(
        None, BIZ_ROW, [{'type': 'post_image', 'image_id': FLYER, 'caption': 'x'}], user_id=OWNER))
    out = sent(taken[0])
    assert len(s.sent) == 1 and out['_authorized_by'] == 'spy'


def test_schedule_action_will_not_wrap_a_picture_post(monkeypatch):
    import chief_strategy_actions as cstrat
    monkeypatch.setattr(sb_clients, 'sb_post_as_service',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('nothing is scheduled')))
    out = asyncio.run(cos.ACTION_HANDLERS['schedule_action'](None, BIZ_ROW, {
        'type': 'schedule_action', 'in_minutes': 60,
        'action': {'type': 'post_image', 'image_id': FLYER, 'caption': 'x'}}))
    assert cos._action_failed(out) and 'when' in out['result'] and 'post_image' in out['result']
    assert 'post_image' in inspect.getsource(cstrat.handle_schedule_action)


def test_a_spoken_hold_names_where_it_goes():
    assert cos._confirmation_subject({'type': 'post_image', 'platforms': ['instagram', 'facebook']}) == \
        'to instagram, facebook'
    assert cos._confirmation_subject({'type': 'post_image'}) == 'to every connected account'


# ─── 6. the registry ──────────────────────────────────────────────────

def test_post_image_is_class_c_client_facing_and_never_an_agent_tool():
    cls = action_registry.classification('post_image')
    assert cls['effect'] == 'write' and cls['reversibility'] == 'C' and not cls.get('bulk')
    assert 'cancelled' in cls['why'] and 'recalled' in cls['why']
    assert not action_registry.is_autonomy_eligible('post_image')
    assert not action_registry.is_autonomy_eligible('post_image', granted_scope=True)
    assert not action_registry.may_expose_to_agent('post_image', allow_writes=True)
    assert 'post_image' in policy_engine.CLIENT_FACING
    assert cos.ACTION_HANDLERS['post_image'] is cos.handle_post_image is csa.handle_post_image
    import mcp_server
    assert 'post_image' not in getattr(mcp_server, 'WRITE_TOOL_SCHEMAS', {})


def test_the_prompt_teaches_the_tag_and_its_rules():
    import chief_prompt
    src = inspect.getsource(chief_prompt)
    assert '"type":"post_image"' in src and '"image":"latest"' in src
    rule = src[src.index('POSTING A FLYER, DESIGN OR PHOTO'):][:2000]
    for must in ('only when the owner asks', 'prefer it over publish_post', 'state the caption and the accounts',
                 'never claim it was posted unless the result says so', 'never wrap post_image in schedule_action'):
        assert must in rule, must


def test_the_wording_checks_bite():
    """Guarding the guards: a pattern that matched nothing would pass every
    wording check above."""
    assert FORBIDDEN.search('The Post for Me API said no') and FORBIDDEN.search('provider error')
    assert CLAIMS_POSTED.search('Posted your flyer') and CLAIMS_POSTED.search('Your flyer was posted')
    assert not CLAIMS_POSTED.search('Already sent, not posted twice')
    assert not CLAIMS_POSTED.search('so nothing was posted')

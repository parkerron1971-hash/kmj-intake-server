"""Post a finished design, or words, to the connected accounts
(image_posting.post_image_for). No live services.

  1. Only the owner; posting switched on; only a ready design of THIS business.
  2. The design goes as a public JPEG made under the build actor, bound to
     this business and person for that one call and reset after.
  3. Words only: Instagram (needs a picture) is left out and said; a picture
     never goes to a video-only network; nowhere left, nothing posted.
  4. Never twice: the same request returns the first post; the same post
     within a day is returned as already sent.
  5. Every failed read refuses: nothing is ever posted on a guess.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

import image_posting as ip
import image_studio as images
import post_for_me as pfm
from __tests__._social_fakes import (BIZ, FLYER, FLYER_PREFIX, MANAGER, OTHER, OWNER, THEIRS, art,
                                     install, jpeg_link)


@pytest.fixture
def s(monkeypatch):
    return install(monkeypatch)


def post(image_id=FLYER, *, user=OWNER, request_id=None, caption='Saturday fades. Book at the link.',
         connection_ids=('c-ig', 'c-fb'), scheduled_at=None):
    return asyncio.run(ip.post_image_for(
        BIZ, user, image_id, request_id=request_id or uuid4(), caption=caption,
        connection_ids=list(connection_ids), scheduled_at=scheduled_at))


def refused(s, status, words=''):
    """Nothing prepared, nothing saved, nothing sent."""
    def check(call):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == status, e.value.detail
        assert words.lower() in str(e.value.detail).lower()
        assert s.sent == [] and s.db.pubs == [] and s.originals == [] and s.stored == []
        return e.value
    return check


# ─── 1. who, and which picture ───────────────────────────────────────

def test_a_design_goes_to_the_accounts_as_a_jpeg(s):
    out = post()
    assert out['ok'] is True and out['already'] is False and out['dropped'] == []
    assert out['image'] == {'id': FLYER, 'title': 'Saturday fade special', 'design': True}
    (sent,) = s.sent
    assert sorted(sent['account_ids']) == ['spc_fb', 'spc_ig']
    assert sent['media_urls'] == [jpeg_link(FLYER)] and sent['caption'] == 'Saturday fades. Book at the link.'
    # Our row id is the external id; the record keeps the picture and who asked.
    (row,) = s.db.pubs
    assert sent['external_id'] == row['id'] and row['approved_by'] == OWNER
    assert row['media'] == [{'url': jpeg_link(FLYER), 'kind': 'image', 'image_id': FLYER,
                             'title': 'Saturday fade special'}]
    assert s.stored == [('business-assets', f'{BIZ}/published-artwork/{FLYER}.jpg', 'image/jpeg', b'\xff\xd8\xff')]


def test_only_the_owner_and_nothing_is_read_past_the_check(s):
    refused(s, 403, 'only the business owner')(lambda: post(user=MANAGER))
    assert all(r.startswith('/businesses') for r in s.db.reads)


def test_a_failed_owner_read_refuses(s):
    s.db.fail = ('/businesses',)
    refused(s, 503, 'nothing was posted')(lambda: post())


def test_posting_switched_off_or_not_set_up(s, monkeypatch):
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', OTHER)
    refused(s, 403, "isn't switched on")(lambda: post())
    monkeypatch.delenv('POST_FOR_ME_API_KEY')
    refused(s, 503, "isn't set up")(lambda: post())


def test_another_business_s_design_is_refused_and_never_fetched(s):
    refused(s, 404, "isn't in this business's media library")(lambda: post(THEIRS))
    assert not any(THEIRS in r and 'business_id=eq.' + OTHER in r for r in s.db.reads)


@pytest.mark.parametrize('image_id', ['not-a-uuid', str(uuid4())])
def test_an_unknown_or_malformed_id(s, image_id):
    refused(s, 404)(lambda: post(image_id))
    assert not any('not-a-uuid' in r for r in s.db.reads), 'a malformed id never reaches a query'


@pytest.mark.parametrize('status,words', [('queued', 'still being made'), ('working', 'still being made'),
                                          ('failed', "didn't finish")])
def test_a_design_that_is_not_ready(s, status, words):
    s.db.artworks[0] = art(FLYER, status=status)
    refused(s, 409, words)(lambda: post())


def test_a_failed_design_read_refuses(s):
    s.db.fail = ('/image_artworks',)
    refused(s, 503, "couldn't read that design")(lambda: post())


# ─── 2. the build actor ──────────────────────────────────────────────

def test_the_build_actor_is_bound_for_the_jpeg_only(s):
    assert images.build_actor.get() is None
    post()
    assert s.actors == [{'business_id': BIZ, 'user_id': OWNER}]
    assert images.build_actor.get() is None


def test_an_outer_actor_is_restored_and_never_used(s):
    outer = {'business_id': OTHER, 'user_id': MANAGER}
    token = images.build_actor.set(outer)
    try:
        post()
        assert s.actors == [{'business_id': BIZ, 'user_id': OWNER}]
        assert images.build_actor.get() == outer
    finally:
        images.build_actor.reset(token)


def test_the_actor_is_reset_when_the_picture_cannot_be_made(s, monkeypatch):
    async def broken(client, row):
        raise HTTPException(502, 'The original image could not be loaded.')
    monkeypatch.setattr(images, 'original', broken)
    refused(s, 502, 'could not be prepared')(lambda: post())
    assert images.build_actor.get() is None


def test_a_picture_stored_outside_this_business_s_folder_is_never_fetched(s):
    s.db.artworks[0] = art(FLYER, storage_path=f'{OTHER}/{FLYER}.png')
    refused(s, 502, 'could not be prepared')(lambda: post())


def test_without_the_actor_storage_refuses():
    """Guarding the guard: with no JWT and no actor, storage says no."""
    with pytest.raises(HTTPException) as e:
        images.token()
    assert e.value.status_code == 401


# ─── 3. where it can go ──────────────────────────────────────────────

def test_words_only_leave_instagram_out_and_say_so(s):
    out = post(None, caption='Open chairs today until 5.')
    assert out['image'] is None
    assert out['dropped'] == [{'platform': 'instagram', 'username': 'fadestreet', 'why': 'needs_picture'}]
    (sent,) = s.sent
    assert sent['account_ids'] == ['spc_fb'] and sent['media_urls'] == []
    assert s.originals == [] and s.stored == []
    assert [t['platform'] for t in s.db.pubs[0]['targets']] == ['facebook']


def test_words_only_to_instagram_alone_posts_nothing(s):
    e = refused(s, 400, 'instagram needs a picture')(lambda: post(None, connection_ids=['c-ig']))
    assert 'Nothing was posted' in e.detail


def test_words_only_need_words(s):
    refused(s, 400, 'write something')(lambda: post(None, caption='  '))


def test_a_picture_never_goes_to_a_video_only_network(s):
    s.db.connections.append({'id': 'c-tt', 'business_id': BIZ, 'status': 'connected', 'platform': 'tiktok',
                             'username': 'fadestreet', 'provider_account_id': 'spc_tt'})
    out = post(connection_ids=['c-ig', 'c-tt'])
    assert out['dropped'] == [{'platform': 'tiktok', 'username': 'fadestreet', 'why': 'needs_video'}]
    assert s.sent[0]['account_ids'] == ['spc_ig']


def test_an_account_that_is_not_this_business_s_is_refused(s):
    refused(s, 400, "isn't connected")(lambda: post(connection_ids=['c-ig', 'c-other']))
    refused(s, 400, "isn't connected")(lambda: post(connection_ids=['c-gone']))


def test_the_words_are_checked_before_the_picture_is_made(s):
    s.db.connections.append({'id': 'c-x', 'business_id': BIZ, 'status': 'connected', 'platform': 'x',
                             'username': 'fade', 'provider_account_id': 'spc_x'})
    refused(s, 400, '280')(lambda: post(caption='x' * 281, connection_ids=['c-x']))


def test_a_time_in_the_past_or_too_far_out(s):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    refused(s, 400, 'a minute from now')(lambda: post(scheduled_at=past))
    far = (datetime.now(timezone.utc) + timedelta(days=120)).isoformat()
    refused(s, 400, '90 days')(lambda: post(scheduled_at=far))


def test_a_scheduled_post(s):
    at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    out = post(scheduled_at=at)
    assert out['publication']['status'] == 'scheduled' and s.sent[0]['scheduled_at']


# ─── 4. never twice ──────────────────────────────────────────────────

def test_the_same_request_twice_posts_once(s):
    rid = uuid4()
    first = post(request_id=rid)
    again = post(request_id=rid)
    assert first['already'] is False and again['already'] is True
    assert len(s.sent) == 1 and len(s.db.pubs) == 1
    assert again['publication']['id'] == first['publication']['id']


def test_the_post_id_comes_from_the_request(s):
    rid = uuid4()
    post(request_id=rid)
    assert s.db.pubs[0]['id'] == ip.publication_id_for(BIZ, FLYER, rid)


def test_the_same_post_within_a_day_is_already_sent(s):
    post()
    again = post(connection_ids=['c-fb', 'c-ig'])        # a new request, the same post
    assert again['already'] is True and len(s.sent) == 1


def test_different_words_are_a_different_post(s):
    post()
    assert post(caption='Another line')['already'] is False and len(s.sent) == 2


def test_a_failed_duplicate_read_refuses(s):
    s.db.fail = ('approved_hash=',)
    refused(s, 503, 'earlier post')(lambda: post())


def test_a_failed_read_of_this_request_s_post_refuses(s):
    s.db.fail = ('/social_publications?id=',)
    refused(s, 503, 'earlier post')(lambda: post())


def test_a_refused_hand_off_is_recorded_and_answered_the_same_way(s, monkeypatch):
    async def refuse(**kw):
        s.sent.append(kw)
        raise pfm.PostForMeError('answered 422.', 422)
    monkeypatch.setattr(pfm, 'create_post', refuse)
    rid = uuid4()
    with pytest.raises(HTTPException) as e:
        post(request_id=rid)
    assert e.value.status_code == 502 and s.db.pubs[0]['status'] == 'failed'
    with pytest.raises(HTTPException) as again:
        post(request_id=rid)
    assert again.value.status_code == 502 and len(s.sent) == 1


# ─── 5. the shape of the code ────────────────────────────────────────

def test_every_database_call_runs_off_the_event_loop(s):
    post()
    assert s.db.threads and not any(s.db.threads), 'a database call ran on the event loop'


def test_the_design_title(s):
    assert ip.design_title({'goal': 'Fall  open\nhouse'}) == 'Fall open house'
    assert ip.design_title({'prompt': FLYER_PREFIX + '{"title": "Fade special", "layers": []}'}) == 'Fade special'
    assert ip.design_title({'prompt': 'Create an original, professionally art-directed marketing composition.\n'
                                      'OWNER BRIEF:\nA warm open house\nCOMPOSITION DIRECTION:\nx'}) == 'A warm open house'
    assert ip.design_title({'prompt': FLYER_PREFIX + 'not json'}) == ''
    assert ip.design_title({'prompt': 'y' * 200}).endswith('…') and len(ip.design_title({'prompt': 'y' * 200})) == 78
    assert ip.is_design({'model': 'gpt-image-2'}) and not ip.is_design({'prompt': 'IMG_0001.jpg'})


def test_one_door():
    src = inspect.getsource(ip.post_image_for)
    assert 'social.send_post(' in src and 'publication_id=publication_id' in src


def test_the_fake_database_rejects_an_unencoded_plus_in_a_time_filter():
    """Review of #1306: real PostgREST reads a raw '+' as a space, so the fake
    must not accept what production would break on."""
    import pytest as _pytest
    from __tests__._social_fakes import _query_when
    with _pytest.raises(AssertionError):
        _query_when('2026-10-07T10:00:00+00:00')
    assert _query_when('2026-10-07T10:00:00%2B00:00').utcoffset().total_seconds() == 0

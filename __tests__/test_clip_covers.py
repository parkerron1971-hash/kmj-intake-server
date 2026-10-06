"""Make cover: a clip's clean frame through the Creative Director. No live services or paid calls."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4, uuid5, UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import clip_covers as cc
import image_studio as images
import sb_clients

BIZ = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
OWNER = '11111111-1111-1111-1111-111111111111'
CLIP = '22222222-2222-4222-8222-222222222222'


def clip(**configuration):
    return {'id': CLIP, 'business_id': BIZ, 'kind': 'clip', 'status': 'ready', 'name': "Don't Measure Rightness By Feelings",
            'configuration': {'origin': 'ai', 'poster': True, 'frame': True, 'caption': '', **configuration}}


@pytest.fixture
def app(monkeypatch):
    s = SimpleNamespace(rows=[clip()], patched=[], designed=[], stored=[], posted=[], fetched=[], artworks=[])
    monkeypatch.setattr(cc.media_library, 'read', lambda path: list(s.rows))
    monkeypatch.setattr(cc.sb_clients, 'sb_patch_as_service', lambda path, body: s.patched.append((path, body)) or [body])
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': BIZ, 'owner_id': OWNER}))

    async def db(client, method, path, body=None, **kw):
        if method == 'GET':
            return [a for a in s.artworks if a['id'] in path]
        s.posted.append(body); s.artworks.append(body); return [body]
    monkeypatch.setattr(images, 'db', db)
    monkeypatch.setattr(images, 'store', AsyncMock(side_effect=lambda c, path, raw, mime: s.stored.append(path)))
    monkeypatch.setattr(images, 'normalize_image', lambda raw: b'png')

    class Response:
        is_success = True
        content = b'jpg'
    async def get(self, url, headers=None):
        s.fetched.append(url); return Response()
    monkeypatch.setattr(cc.httpx.AsyncClient, 'get', get)

    async def design(client, biz, action):
        s.designed.append((images.turn_id.get(), action))
        return {'type': 'design_flyer', 'result': 'Designing.', 'label': 'Designing your flyer',
                'image': {'id': str(uuid4()), 'status': 'queued'}}
    monkeypatch.setattr(cc.creative_director, 'handle_design_flyer', design)
    api = FastAPI(); api.include_router(cc.router)
    api.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=OWNER))
    s.client = TestClient(api)
    return s


def post(app, **body):
    return app.client.post(f'/media-library/{BIZ}/clips/{CLIP}/cover', json={'request_id': str(uuid4()), **body})


def test_a_cover_is_designed_from_the_clean_frame_with_the_clip_title(app):
    response = post(app)
    assert response.status_code == 202 and response.json()['cover']['status'] == 'queued'
    turn, action = app.designed[0]
    frame_id = str(uuid5(UUID(CLIP), 'cover-frame'))
    assert action['references'] == [{'id': frame_id, 'role': 'subject', 'use': 'The speaker on stage: pose, body and clothes. Keep their exact likeness.'}]
    assert action['exact_copy'] == ["Don't Measure Rightness By Feelings"] and action['size'] == '1088x1920'
    assert "Don't Measure Rightness By Feelings" in action['goal']
    # The frame comes from the clip's private storage and lands in the owner's gallery.
    assert app.fetched[0].endswith(f'/storage/v1/object/program-media/{BIZ}/{CLIP}-frame.jpg')
    assert app.stored == [f'{BIZ}/{frame_id}.png'] and app.posted[0]['owner_id'] == OWNER
    # The design names its clip; the clip itself is never written (its configuration is
    # permanent in the database: preserve_media_review).
    assert action['clip_id'] == CLIP and response.json()['clip_id'] == CLIP
    assert not app.patched


def test_the_frame_is_copied_once_and_each_request_is_its_own_design(app):
    post(app, words=['Feelings Lie'])
    post(app, words=['Feelings Lie'], size='1920x1088')
    assert len(app.fetched) == 1 and len(app.posted) == 1
    (first, a), (second, b) = app.designed
    assert first != second and b['size'] == '1920x1088' and a['exact_copy'] == ['Feelings Lie']


def test_a_clip_without_a_clean_frame_or_from_elsewhere_is_refused(app):
    app.rows = [clip(frame=False)]
    assert post(app).status_code == 409
    app.rows = []
    assert post(app).status_code == 404
    assert not app.designed


def test_a_cover_needs_words(app):
    app.rows = [dict(clip(), name='')]
    assert post(app).status_code == 422
    assert post(app, words=['   ']).status_code == 422


def test_only_the_owner_makes_covers(app, monkeypatch):
    monkeypatch.setattr(images, 'business', AsyncMock(side_effect=HTTPException(403, 'Business access denied.')))
    assert post(app).status_code == 403
    assert not app.designed and not app.patched
    # Checked first: a stranger learns nothing about whether the clip exists or has a frame.
    app.rows = []
    assert post(app).status_code == 403
    app.rows = [clip(frame=False)]
    assert post(app).status_code == 403


def test_each_clip_shows_its_newest_cover(monkeypatch):
    """2026-10-06: writing the cover id into the clip failed in production (the
    trigger keeps a clip's configuration permanent). The link is read back from
    the designs that name the clip, newest first."""
    other = '33333333-3333-4333-8333-333333333333'
    asked = []
    def get(path):
        asked.append(path)
        return [{'id': 'cover-new', 'clip_id': CLIP, 'status': 'ready', 'created_at': '2026-10-06T01:00:00Z'},
                {'id': 'cover-old', 'clip_id': CLIP, 'status': 'ready', 'created_at': '2026-10-06T00:00:00Z'},
                {'id': 'cover-2', 'clip_id': other, 'status': 'working', 'created_at': '2026-10-06T00:30:00Z'}]
    monkeypatch.setattr(cc.sb_clients, 'sb_get_as_service', get)
    rows = [clip(), dict(clip(), id=other), {'id': 'src', 'kind': 'source'}]
    # A cover still designing shows as designing, so the card never offers a second paid tap.
    assert cc.covers_for(BIZ, rows) == {CLIP: 'cover-new', other: 'cover-2'}
    assert f'business_id=eq.{BIZ}' in asked[0] and 'director->>clip_id=in.(' in asked[0] and 'order=created_at.desc' in asked[0]
    assert cc.covers_for(BIZ, [{'id': 'src', 'kind': 'source'}]) == {}
    monkeypatch.setattr(cc.sb_clients, 'sb_get_as_service', lambda path: None)
    assert cc.covers_for(BIZ, rows) == {}


def test_a_cover_needs_a_signed_in_user():
    api = FastAPI(); api.include_router(cc.router)
    response = TestClient(api).post(f'/media-library/{BIZ}/clips/{CLIP}/cover', json={'request_id': str(uuid4())})
    assert response.status_code in (401, 403)


def test_a_failed_cover_never_hides_an_earlier_good_one(monkeypatch):
    rows_back = [{'id': 'failed-new', 'clip_id': CLIP, 'status': 'failed', 'created_at': '2026-10-06T02:00:00Z'},
                 {'id': 'good-old', 'clip_id': CLIP, 'status': 'ready', 'created_at': '2026-10-06T01:00:00Z'}]
    monkeypatch.setattr(cc.sb_clients, 'sb_get_as_service', lambda path: rows_back)
    assert cc.covers_for(BIZ, [clip()]) == {CLIP: 'good-old'}
    # Only failures: the newest failure shows, so the card can say it could not be made.
    rows_back[1]['status'] = 'failed'
    assert cc.covers_for(BIZ, [clip()]) == {CLIP: 'failed-new'}


def test_many_clips_are_read_in_short_batches(monkeypatch):
    asked = []
    monkeypatch.setattr(cc.sb_clients, 'sb_get_as_service', lambda path: asked.append(path) or [])
    many = [dict(clip(), id=f'00000000-0000-4000-8000-{i:012d}') for i in range(250)]
    cc.covers_for(BIZ, many)
    ids_per_batch = [len(p.split('in.(')[1].split(')')[0].split(',')) for p in asked]
    assert ids_per_batch == [100, 100, 50]


def test_a_face_close_up_leads_the_cover_when_the_clip_has_one(app):
    """Kevin, 2026-10-06: covers must look over 90% like the person. The close-up
    of the face goes first and is the authority on the face and hair."""
    app.rows = [clip(face=True)]
    post(app)
    refs = app.designed[0][1]['references']
    assert [r['id'] for r in refs] == [str(uuid5(UUID(CLIP), 'cover-face')), str(uuid5(UUID(CLIP), 'cover-frame'))]
    assert 'face' in refs[0]['use'] and all(r['role'] == 'subject' for r in refs)
    assert any(u.endswith(f'/{BIZ}/{CLIP}-face.jpg') for u in app.fetched)


def test_a_close_up_that_cannot_be_read_leaves_the_cover_to_the_frame(app, monkeypatch):
    """Review of #1286: the close-up is best effort; a missing file never fails the cover."""
    class Response:
        def __init__(self, ok): self.is_success, self.content = ok, b'jpg'
    async def get(self, url, headers=None):
        app.fetched.append(url); return Response(not url.endswith('-face.jpg'))
    monkeypatch.setattr(cc.httpx.AsyncClient, 'get', get)
    app.rows = [clip(face=True)]
    post(app)
    refs = app.designed[0][1]['references']
    assert [r['id'] for r in refs] == [str(uuid5(UUID(CLIP), 'cover-frame'))]


# -- both shapes, a look to follow, and covers made with the clips ---------

def test_one_tap_designs_the_story_cover_and_the_widescreen_thumbnail(app):
    """Kevin, 2026-10-06: covers in the full-screen shape along with the story size."""
    response = post(app, sizes=['story', 'wide'])
    body = response.json()
    assert response.status_code == 202 and set(body['covers']) == {'story', 'wide'} and body['errors'] == {}
    (turn_a, story), (turn_b, wide) = app.designed
    assert story['size'] == '1088x1920' and wide['size'] == '1920x1088'
    assert turn_a.endswith(':story') and turn_b.endswith(':wide') and turn_a != turn_b
    assert 'bottom-right corner' in wide['goal'] and 'top 8%' in story['goal']
    assert 'thumbnail' in wide['owner_request'] and 'cover' in story['owner_request']
    # The speaker's pictures are copied once and shared by both designs.
    assert story['references'] == wide['references'] and len(app.stored) == 1


def test_a_single_size_keeps_the_original_turn_id(app):
    """A retried tap from an older app must land on the design it already started."""
    request_id = str(uuid4())
    app.client.post(f'/media-library/{BIZ}/clips/{CLIP}/cover', json={'request_id': request_id})
    assert app.designed[0][0] == f'clip-cover:{CLIP}:{request_id}'


def test_a_cover_can_follow_a_picture_and_a_note(app):
    style = str(uuid4())
    post(app, sizes=['wide'], style_image_id=style, note='Keep it dark, almost black and white.')
    action = app.designed[0][1]
    assert action['references'][-1] == {'id': style, 'role': 'style', 'use': cc.STYLE_USE}
    assert 'never its words, people or logos' in cc.STYLE_USE
    assert action['goal'].endswith('The owner asked for this look: Keep it dark, almost black and white.')


def test_when_the_second_shape_cannot_start_the_first_still_stands(app, monkeypatch):
    calls = []

    async def design(client, biz, action):
        calls.append(action['size'])
        if action['size'] == '1920x1088':
            raise HTTPException(402, 'Out of credits.')
        return {'result': 'Designing.', 'label': 'Designing', 'image': {'id': 'story-id', 'status': 'queued'}}
    monkeypatch.setattr(cc.creative_director, 'handle_design_flyer', design)
    body = post(app, sizes=['story', 'wide']).json()
    assert body['covers'] == {'story': {'id': 'story-id', 'status': 'queued'}} and body['errors'] == {'wide': 'Out of credits.'}
    assert calls == ['1088x1920', '1920x1088']


def test_covers_are_read_back_by_shape(monkeypatch):
    rows = [
        {'id': 'w1', 'status': 'ready', 'size': '1920x1088', 'clip_id': CLIP, 'created_at': '2026-10-06T02:00:00Z'},
        {'id': 's2', 'status': 'failed', 'size': '1088x1920', 'clip_id': CLIP, 'created_at': '2026-10-06T03:00:00Z'},
        {'id': 's1', 'status': 'ready', 'size': '1088x1920', 'clip_id': CLIP, 'created_at': '2026-10-06T01:00:00Z'},
    ]
    monkeypatch.setattr(cc.sb_clients, 'sb_get_as_service', lambda path: rows)
    assert cc.shaped_covers(BIZ, [clip()]) == {CLIP: {'story': 's1', 'wide': 'w1'}}
    assert cc.covers_for(BIZ, [clip()]) == {CLIP: 's1'}


RUN = '33333333-3333-4333-8333-333333333333'


def run_row(**covers):
    return {'id': RUN, 'business_id': BIZ, 'created_by': OWNER, 'options': {'covers': {'sizes': ['story', 'wide'], **covers}}}


def test_a_run_covers_its_best_clips_once_as_its_owner(app, monkeypatch):
    best = dict(clip(score=9.1), id='44444444-4444-4444-8444-444444444444', name='Best')
    skipped = dict(clip(score=9.9), id='55555555-5555-4555-8555-555555555555', decision='skipped')
    plain = dict(clip(score=4.0), id='66666666-6666-4666-8666-666666666666', name='Plain')
    no_frame = dict(clip(score=8.0, frame=False), id='77777777-7777-4777-8777-777777777777')
    app.rows = [plain, skipped, best, no_frame]
    monkeypatch.setattr(cc, 'AUTO_CLIP_LIMIT', 1)
    monkeypatch.setattr(cc, '_tries', {})
    existing = {}
    monkeypatch.setattr(cc, 'shaped_covers', lambda biz, rows: existing)
    actors = []

    async def business(client, biz):
        actors.append(images.build_actor.get())
        return {'id': BIZ, 'owner_id': OWNER}
    monkeypatch.setattr(images, 'business', business)
    made = asyncio.run(cc.cover_run(cc.httpx.AsyncClient(), run_row(style_image_id='88888888-8888-4888-8888-888888888888')))
    assert made == 2 and [a['clip_id'] for _, a in app.designed] == [best['id'], best['id']]
    assert [t for t, _ in app.designed] == [f'clip-cover:{best["id"]}:auto-{RUN}:story', f'clip-cover:{best["id"]}:auto-{RUN}:wide']
    assert app.designed[0][1]['references'][-1]['role'] == 'style'
    assert actors == [{'business_id': BIZ, 'user_id': OWNER}] and images.build_actor.get() is None
    # The frame is copied as the server, which must say it cost nothing.
    assert all(p.get('cost_usd') == 0 for p in app.posted)
    # Called again with both covers in place: nothing new.
    existing[best['id']] = {'story': 'a', 'wide': 'b'}
    assert asyncio.run(cc.cover_run(cc.httpx.AsyncClient(), run_row())) == 0 and len(app.designed) == 2


def test_a_cover_that_cannot_start_is_tried_twice_then_left_to_make_cover(app, monkeypatch):
    monkeypatch.setattr(cc, '_tries', {})
    monkeypatch.setattr(cc, 'shaped_covers', lambda biz, rows: {})
    tries = []

    async def broke(client, biz, action):
        tries.append(action['size'])
        raise HTTPException(402, 'This business is out of credits.')
    monkeypatch.setattr(cc.creative_director, 'handle_design_flyer', broke)
    for _ in range(2):
        with pytest.raises(HTTPException):
            asyncio.run(cc.cover_run(cc.httpx.AsyncClient(), run_row(sizes=['story'])))
    assert asyncio.run(cc.cover_run(cc.httpx.AsyncClient(), run_row(sizes=['story']))) == 0
    assert tries == ['1088x1920', '1088x1920']


def test_the_owner_is_told_once_when_covers_stop(monkeypatch):
    monkeypatch.setattr(cc, '_told', set())
    told = []
    monkeypatch.setattr(cc.sb_clients, 'sb_post_as_service', lambda path, body: told.append((path, body)) or [body])
    cc.tell_owner_covers_stopped(run_row(), 'This business is out of credits.')
    cc.tell_owner_covers_stopped(run_row(), 'This business is out of credits.')
    assert len(told) == 1 and told[0][0] == '/chief_notifications'
    assert 'Make cover' in told[0][1]['body'] and told[0][1]['data']['kind'] == 'clip_covers_stopped'


def test_the_cover_step_only_looks_at_recent_runs_that_asked(monkeypatch):
    asked = []
    monkeypatch.setattr(cc.sb_clients, 'sb_get_as_service', lambda path: asked.append(path) or [])
    cc.runs_wanting_covers()
    assert 'status=eq.completed' in asked[0] and 'options->covers=not.is.null' in asked[0]
    assert '+' not in asked[0].split('finished_at=gte.')[1].split('&')[0]

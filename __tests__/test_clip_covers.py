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
    s = SimpleNamespace(rows=[clip()], patched=[], designed=[], stored=[], posted=[], fetched=[], artworks=[], busy=set(),
                        faces=False, extra=False, backfilled=[])
    monkeypatch.setattr(cc.media_library, 'read', lambda path: list(s.rows))
    monkeypatch.setattr(cc, 'designing_now', lambda biz, clip_id: set(s.busy))
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
        def __init__(self, ok): self.is_success, self.content = ok, b'jpg'
    async def get(self, url, headers=None):
        # A face close-up is in storage only when the test says one is.
        s.fetched.append(url)
        if url.endswith('-face.jpg'):
            return Response(s.faces)
        return Response(s.extra if url.endswith(('-face2.jpg', '-face3.jpg')) else True)
    monkeypatch.setattr(cc.httpx.AsyncClient, 'get', get)
    monkeypatch.setattr(cc, 'backfill_faces', lambda row, need_first=False: s.backfilled.append((row['id'], need_first)) or 0)
    monkeypatch.setattr(cc, '_asked', set())

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
    assert [u for u in app.fetched if u.endswith('-frame.jpg')] == app.fetched[:1] and len(app.posted) == 1
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
    app.faces = True
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
        app.fetched.append(url); return Response(url.endswith('-frame.jpg'))
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
    made, stopped = asyncio.run(cc.cover_run(cc.httpx.AsyncClient(), run_row(style_image_id='88888888-8888-4888-8888-888888888888')))
    assert made == 2 and stopped is None and [a['clip_id'] for _, a in app.designed] == [best['id'], best['id']]
    assert [t for t, _ in app.designed] == [f'clip-cover:{best["id"]}:auto-{RUN}:story', f'clip-cover:{best["id"]}:auto-{RUN}:wide']
    assert app.designed[0][1]['references'][-1]['role'] == 'style'
    assert actors == [{'business_id': BIZ, 'user_id': OWNER}] and images.build_actor.get() is None
    # The frame is copied as the server, which must say it cost nothing.
    assert all(p.get('cost_usd') == 0 for p in app.posted)
    # Called again with both covers in place: nothing new.
    existing[best['id']] = {'story': 'a', 'wide': 'b'}
    assert asyncio.run(cc.cover_run(cc.httpx.AsyncClient(), run_row())) == (0, None) and len(app.designed) == 2


def test_a_cover_that_cannot_start_is_tried_twice_then_left_to_make_cover(app, monkeypatch):
    monkeypatch.setattr(cc, '_tries', {})
    monkeypatch.setattr(cc, 'shaped_covers', lambda biz, rows: {})
    tries = []

    async def broke(client, biz, action):
        tries.append(action['size'])
        raise HTTPException(402, 'This business is out of credits.')
    monkeypatch.setattr(cc.creative_director, 'handle_design_flyer', broke)
    run = lambda: asyncio.run(cc.cover_run(cc.httpx.AsyncClient(), run_row(sizes=['story'])))
    # The first miss is not the end: the owner is not told yet.
    assert run() == (0, None)
    # The second spends the last try: now the reason comes back, once.
    assert run() == (0, 'This business is out of credits.')
    assert run() == (0, None)
    assert tries == ['1088x1920', '1088x1920']


def test_the_owner_is_told_once_when_covers_stop(monkeypatch):
    monkeypatch.setattr(cc, '_told', set())
    told, answers = [], [None, [{}], [{}]]
    monkeypatch.setattr(cc.sb_clients, 'sb_post_as_service', lambda path, body: told.append((path, body)) or answers.pop(0))
    # A notice that could not be written is not "told": the next stop tries again.
    cc.tell_owner_covers_stopped(run_row(), 'This business is out of credits.')
    cc.tell_owner_covers_stopped(run_row(), 'This business is out of credits.')
    cc.tell_owner_covers_stopped(run_row(), 'This business is out of credits.')
    assert len(told) == 2 and told[1][0] == '/chief_notifications'
    assert 'Make cover' in told[1][1]['body'] and told[1][1]['data']['kind'] == 'clip_covers_stopped'


def test_the_tick_tells_the_owner_only_when_every_try_is_spent(monkeypatch):
    monkeypatch.setattr(cc.clip_finder, 'enabled', lambda business_id=None: True)
    monkeypatch.setattr(cc, 'runs_wanting_covers', lambda: [run_row()])
    told = []
    monkeypatch.setattr(cc, 'tell_owner_covers_stopped', lambda run, reason: told.append(reason))
    outcomes = [(0, None), (0, 'Out of credits.'), HTTPException(503, 'Storage is unavailable.'), RuntimeError('boom')]

    async def cover_run(client, run):
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(cc, 'cover_run', cover_run)
    for _ in range(4):
        asyncio.run(cc.cover_tick())
    assert told == ['Out of credits.']


def test_the_tick_does_nothing_when_switched_off(monkeypatch):
    monkeypatch.setattr(cc.clip_finder, 'enabled', lambda business_id=None: False)
    monkeypatch.setattr(cc, 'runs_wanting_covers', lambda: pytest.fail('read while switched off'))
    asyncio.run(cc.cover_tick())


def test_make_cover_never_pays_twice_for_a_shape_still_designing(app):
    """The cover made with the clips may still be designing when the owner taps."""
    app.busy = {'1920x1088'}
    body = post(app, sizes=['story', 'wide']).json()
    assert set(body['covers']) == {'story'} and body['errors'] == {'wide': 'A cover in this shape is already being designed.'}
    assert [a['size'] for _, a in app.designed] == ['1088x1920']
    app.busy = {'1088x1920', '1920x1088'}
    response = post(app, sizes=['story', 'wide'])
    assert response.status_code == 409 and len(app.designed) == 1


def test_the_cover_step_only_looks_at_recent_runs_that_asked(monkeypatch):
    asked = []
    monkeypatch.setattr(cc.sb_clients, 'sb_get_as_service', lambda path: asked.append(path) or [])
    cc.runs_wanting_covers()
    assert 'status=eq.completed' in asked[0] and 'options->covers=not.is.null' in asked[0]
    assert '+' not in asked[0].split('finished_at=gte.')[1].split('&')[0]


# -- older clips get a close-up made when their cover is (2026-10-06) ---

def test_an_older_clip_gets_its_close_up_made_then_leads_the_cover(app, monkeypatch):
    """Kevin's "Don't Judge Rightness By Feelings" cover was about 75% him: the
    clip predates close-ups, so only a wide shot with a 30 px face guided it."""
    def backfill(row, need_first=False):
        app.backfilled.append((row['id'], need_first))
        app.faces = app.extra = True  # the clip service made three and they were saved
        return 3
    monkeypatch.setattr(cc, 'backfill_faces', backfill)
    post(app)
    refs = app.designed[0][1]['references']
    assert app.backfilled == [(CLIP, True)]
    assert [r['id'] for r in refs] == [str(uuid5(UUID(CLIP), k)) for k in ('cover-face', 'cover-face2', 'cover-face3', 'cover-frame')]
    assert 'Another close-up' in refs[1]['use']


def test_no_close_up_to_be_had_leaves_the_cover_to_the_frame(app):
    post(app)
    assert app.backfilled == [(CLIP, True)]
    assert [r['id'] for r in app.designed[0][1]['references']] == [str(uuid5(UUID(CLIP), 'cover-frame'))]


def test_a_clip_that_had_a_close_up_is_only_asked_for_more_views(app):
    """configuration.face says it was made; a storage miss is not a reason to remake it."""
    app.rows = [clip(face=True)]
    post(app)
    assert app.backfilled == [(CLIP, False)]


def test_a_style_picture_keeps_the_frame_and_two_close_ups(app):
    """Four pictures a design: never drop the stage frame or the look to follow."""
    app.faces = app.extra = True
    style = str(uuid4())
    post(app, style_image_id=style)
    refs = app.designed[0][1]['references']
    assert [r['id'] for r in refs] == [str(uuid5(UUID(CLIP), 'cover-face')), str(uuid5(UUID(CLIP), 'cover-face2')),
                                       str(uuid5(UUID(CLIP), 'cover-frame')), style]


def test_three_close_ups_and_the_frame_without_a_style(app):
    app.faces = app.extra = True
    post(app)
    assert len(app.designed[0][1]['references']) == 4 and app.backfilled == []


import base64 as _b64


def faces_payload(*names):
    return {'faces': [{'jpeg_b64': _b64.b64encode(n).decode(), 'size': [80, 100]} for n in names]}


class Clipper:
    def __init__(self, status=200, payload=None, detail=None):
        self.calls, self.status = [], status
        self.payload = payload if payload is not None else (faces_payload(b'one', b'two', b'three') if status == 200 else {'detail': detail})

    def __call__(self, method, path, **kw):
        self.calls.append((method, path, kw.get('json')))
        return SimpleNamespace(status_code=self.status, content=b'', json=lambda: self.payload)


def backfill_env(monkeypatch, source_rows, clipper):
    monkeypatch.setenv('CLIPPER_URL', 'https://clipper.example.test')
    monkeypatch.setenv('CLIPPER_TOKEN', 't' * 40)
    monkeypatch.setattr(cc, '_no_face', set())
    monkeypatch.setattr(cc, '_asked', set())
    monkeypatch.setattr(cc.media_library, 'read', lambda path: list(source_rows))
    monkeypatch.setattr(cc.storage_links, 'signed_url_sync', lambda bucket, path, ttl=0: f'https://store.example.test/{path}')
    monkeypatch.setattr(cc.clip_finder, 'clipper', clipper)
    saved = []
    monkeypatch.setattr(cc.clip_finder, 'put_file', lambda local, path, kind: saved.append((open(local, 'rb').read(), path, kind)))
    return saved


SOURCE = '99999999-9999-4999-8999-999999999999'


def older(**extra):
    return dict(clip(start_seconds=291.0, end_seconds=381.0), source_id=SOURCE, duration_seconds=90.0, **extra)


def test_the_close_up_comes_from_the_recording_while_it_is_kept(monkeypatch):
    clipper = Clipper()
    saved = backfill_env(monkeypatch, [{'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'ready'}], clipper)
    assert cc.backfill_face(older()) is True
    method, path, body = clipper.calls[0]
    assert (method, path) == ('POST', '/faces') and body['start'] == 291.0 and body['end'] == 381.0 and body['count'] == 3
    assert body['source_url'].endswith(f'{BIZ}/{SOURCE}.source')
    assert saved == [(b'one', f'{BIZ}/{CLIP}-face.jpg', 'image/jpeg'), (b'two', f'{BIZ}/{CLIP}-face2.jpg', 'image/jpeg'),
                     (b'three', f'{BIZ}/{CLIP}-face3.jpg', 'image/jpeg')]


def test_a_clip_with_its_close_up_only_gets_the_extra_views(monkeypatch):
    clipper = Clipper()
    saved = backfill_env(monkeypatch, [{'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'ready'}], clipper)
    assert cc.backfill_faces(older(face=True), need_first=False) == 2
    assert [p for _, p, _ in saved] == [f'{BIZ}/{CLIP}-face2.jpg', f'{BIZ}/{CLIP}-face3.jpg']
    assert CLIP in cc._asked


def test_every_save_failing_is_not_the_final_answer_either(monkeypatch):
    clipper = Clipper()
    backfill_env(monkeypatch, [{'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'ready'}], clipper)

    def broken(local, path, kind):
        raise cc.clip_finder.RunFailed('storage blip')
    monkeypatch.setattr(cc.clip_finder, 'put_file', broken)
    assert cc.backfill_faces(older(), need_first=True) == 0 and CLIP not in cc._asked


def test_one_usable_face_is_a_final_answer_for_more_views(monkeypatch):
    clipper = Clipper(payload=faces_payload(b'only'))
    saved = backfill_env(monkeypatch, [{'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'ready'}], clipper)
    assert cc.backfill_faces(older(face=True), need_first=False) == 0 and saved == [] and CLIP in cc._asked


def test_a_failure_is_never_the_final_answer(monkeypatch):
    """Only an answer with faces marks the clip asked; a 502 lets the next cover try again."""
    clipper = Clipper(status=502, detail='The video could not be read.')
    backfill_env(monkeypatch, [], clipper)
    assert cc.backfill_faces(older(), need_first=True) == 0 and CLIP not in cc._asked


def test_after_the_recording_is_gone_the_clip_itself_is_read(monkeypatch):
    clipper = Clipper()
    backfill_env(monkeypatch, [{'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'ready',
                                'source_removed_at': '2026-10-13T00:00:00Z'}], clipper)
    assert cc.backfill_face(older()) is True
    body = clipper.calls[0][2]
    assert body['source_url'].endswith(f'{BIZ}/{CLIP}.mp4') and body['start'] == 0.0 and body['end'] == 90.0


def test_no_face_in_the_stretch_is_asked_once(monkeypatch):
    clipper = Clipper(status=404, detail='No usable face in that stretch')
    saved = backfill_env(monkeypatch, [], clipper)
    assert cc.backfill_face(older()) is False and cc.backfill_face(older()) is False
    assert len(clipper.calls) == 1 and saved == []


def test_a_clip_service_without_faces_yet_is_asked_again_later(monkeypatch):
    """Deployed before the clip service: its 404 is 'Not Found', not this clip's verdict."""
    clipper = Clipper(status=404, detail='Not Found')
    backfill_env(monkeypatch, [], clipper)
    assert cc.backfill_face(older()) is False and cc.backfill_face(older()) is False
    assert len(clipper.calls) == 2


def test_without_the_clip_service_nothing_is_asked(monkeypatch):
    clipper = Clipper()
    backfill_env(monkeypatch, [], clipper)
    monkeypatch.delenv('CLIPPER_URL')
    assert cc.backfill_face(older()) is False and clipper.calls == []


def test_a_failed_read_is_asked_again(monkeypatch):
    """502 from /faces (an expired link, a network blip) is never the clip's verdict."""
    clipper = Clipper(status=502, detail='The video could not be read.')
    backfill_env(monkeypatch, [], clipper)
    assert cc.backfill_face(older()) is False and cc.backfill_face(older()) is False
    assert len(clipper.calls) == 2


def test_the_face_request_is_bounded(monkeypatch):
    seen = []
    backfill_env(monkeypatch, [], lambda method, path, **kw: seen.append(kw.get('timeout')) or SimpleNamespace(status_code=200, content=b'', json=lambda: faces_payload(b'j')))
    cc.backfill_face(older())
    assert seen[0].read == 75

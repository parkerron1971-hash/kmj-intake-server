"""Make cover: a clip's clean frame through the Creative Director. No live services or paid calls."""
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

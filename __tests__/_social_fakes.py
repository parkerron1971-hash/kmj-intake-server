"""A fake database and posting service for picture posts (image_posting,
chief_social_actions). No live services: every read and write lands here."""
from __future__ import annotations

import io
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from PIL import Image

import image_studio as images
import post_for_me as pfm
import sb_clients

BIZ = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
OWNER = '11111111-1111-4111-8111-111111111111'
MANAGER = '33333333-3333-4333-8333-333333333333'
FLYER = '22222222-2222-4222-8222-222222222222'
THEIRS = '44444444-4444-4444-8444-444444444444'
FLYER_PREFIX = 'EDITABLE_FLYER_V1\n'


def ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def art(image_id, *, biz=BIZ, status='ready', at=None, goal=None, prompt='A bold fade special flyer',
        model='gpt-image-2.5-sunburst', clip_id=None, storage_path=None):
    return {'id': image_id, 'business_id': biz, 'status': status, 'size': '1024x1536',
            'storage_path': storage_path if storage_path is not None else
            (f'{biz}/{image_id}.png' if status == 'ready' else None),
            'prompt': prompt, 'model': model, 'created_at': at or ago(hours=1),
            'goal': goal, 'clip_id': clip_id}


def q(path):
    query = path.split('?', 1)[1] if '?' in path else ''
    return dict(p.split('=', 1) for p in query.split('&') if '=' in p)


def _when(raw):
    return datetime.fromisoformat(raw.replace('%2B', '+').replace('Z', '+00:00'))


def png() -> bytes:
    out = io.BytesIO()
    Image.new('RGBA', (8, 12), (200, 40, 40, 255)).save(out, 'PNG')
    return out.getvalue()


class FakeDB:
    def __init__(self):
        self.owner = OWNER
        self.artworks = [art(FLYER, goal='Saturday fade special'),
                         art(THEIRS, biz=OTHER, goal='Someone else\'s flyer')]
        self.connections = [
            {'id': 'c-ig', 'business_id': BIZ, 'status': 'connected', 'platform': 'instagram', 'username': 'fadestreet', 'provider_account_id': 'spc_ig'},
            {'id': 'c-fb', 'business_id': BIZ, 'status': 'connected', 'platform': 'facebook', 'username': 'Fade Street', 'provider_account_id': 'spc_fb'},
            {'id': 'c-gone', 'business_id': BIZ, 'status': 'disconnected', 'platform': 'x', 'username': 'old', 'provider_account_id': 'spc_x_old'},
            {'id': 'c-other', 'business_id': OTHER, 'status': 'connected', 'platform': 'x', 'username': 'elsewhere', 'provider_account_id': 'spc_o'},
        ]
        self.pubs = []
        self.reads = []
        self.threads = []
        self.fail = ()

    def get(self, path):
        self.reads.append(path)
        self.threads.append(threading.current_thread() is threading.main_thread())
        if any(f in path for f in self.fail):
            return None
        p = q(path)
        if path.startswith('/businesses'):
            return [{'owner_id': self.owner}] if p['id'] == f'eq.{BIZ}' else []
        if path.startswith('/social_connections'):
            rows = [c for c in self.connections if c['business_id'] == p['business_id'][3:]
                    and c['status'] == p['status'][3:]]
            if 'id' in p:
                rows = [c for c in rows if c['id'] in p['id'][4:-1].split(',')]
            return [dict(c) for c in rows]
        if path.startswith('/image_artworks'):
            rows = [a for a in self.artworks if a['business_id'] == p['business_id'][3:]]
            if 'id' in p:
                rows = [a for a in rows if a['id'] == p['id'][3:]]
            if 'status' in p:
                rows = [a for a in rows if a['status'] == p['status'][3:]]
            if p.get('storage_path') == 'not.is.null':
                rows = [a for a in rows if a.get('storage_path')]
            if 'created_at' in p:
                since = _when(p['created_at'][4:])
                rows = [a for a in rows if _when(a['created_at']) >= since]
            if p.get('director->>clip_id') == 'is.null':
                rows = [a for a in rows if not a.get('clip_id')]
            if p.get('or') == '(model.not.is.null,prompt.like.EDITABLE_FLYER_V1*)':
                rows = [a for a in rows if a.get('model') or (a.get('prompt') or '').startswith('EDITABLE_FLYER_V1')]
            if p.get('order') == 'created_at.desc':
                rows = sorted(rows, key=lambda a: _when(a['created_at']), reverse=True)
            return [dict(a) for a in rows]
        if path.startswith('/social_publications'):
            rows = [r for r in self.pubs if r['business_id'] == p['business_id'][3:]]
            if 'id' in p:
                rows = [r for r in rows if r['id'] == p['id'][3:]]
            if 'approved_hash' in p:
                rows = [r for r in rows if r.get('approved_hash') == p['approved_hash'][3:]]
            if p.get('status') == 'neq.failed':
                rows = [r for r in rows if r['status'] != 'failed']
            if p.get('status') == 'not.in.(failed,cancelled)':
                rows = [r for r in rows if r['status'] not in ('failed', 'cancelled')]
            return [dict(r) for r in rows]
        raise AssertionError(f'unexpected read {path}')

    def post(self, path, body, prefer=None):
        assert path == '/social_publications', path
        self.threads.append(threading.current_thread() is threading.main_thread())
        if any(r['id'] == body.get('id') for r in self.pubs):
            return None
        row = {'created_at': datetime.now(timezone.utc).isoformat(), 'provider_post_id': None, 'results': [], **body}
        row.setdefault('id', f'pub{len(self.pubs) + 1}')
        self.pubs.append(row)
        return [dict(row)]

    def patch(self, path, body):
        self.threads.append(threading.current_thread() is threading.main_thread())
        rid = q(path)['id'][3:]
        for r in self.pubs:
            if r['id'] == rid:
                r.update(body)


def install(monkeypatch):
    """Patch the database, storage and posting service; returns the state."""
    monkeypatch.setenv('POST_FOR_ME_API_KEY', 'pfm_test_key')
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', BIZ)
    monkeypatch.setenv('SUPABASE_URL', 'https://sb.test')
    db = FakeDB()
    state = SimpleNamespace(db=db, sent=[], originals=[], stored=[], actors=[])
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', db.get)
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', db.post)
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', db.patch)
    monkeypatch.setattr(sb_clients, 'sb_headers_service', lambda prefer=None: {'Authorization': 'Bearer service'})
    # No signed-in browser here: storage works only under the build actor.
    monkeypatch.setattr(sb_clients, 'get_current_user_jwt', lambda: None)

    async def original(client, row):
        # The real storage_headers: refuses with no actor, or a path outside
        # the actor's business folder.
        images.storage_headers(row['storage_path'])
        state.actors.append(images.build_actor.get())
        state.originals.append(row['id'])
        return png()
    monkeypatch.setattr(images, 'original', original)

    async def store(client, path, content, mime, bucket=images.BUCKET):
        images.storage_headers(path)
        state.stored.append((bucket, path, mime, content[:3]))
    monkeypatch.setattr(images, 'store', store)

    async def create_post(**kw):
        state.sent.append(kw)
        return {'id': f'sp_{len(state.sent)}', 'status': 'processing'}
    monkeypatch.setattr(pfm, 'create_post', create_post)
    return state


def jpeg_link(image_id, biz=BIZ):
    return f'https://sb.test/storage/v1/object/public/business-assets/{biz}/published-artwork/{image_id}.jpg'

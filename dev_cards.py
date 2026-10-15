"""Validated device uploads to a private bucket; signed owner-only reads."""
import hashlib
import io
import json
import re
import warnings
from datetime import timedelta
from typing import Literal, Optional
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError
from PIL import Image

import dev_redact
import dev_relay as store
import storage_links
from dev_bridge import HTTP_TIMEOUT, _require_device
from lead_admin import require_owner

router = APIRouter(tags=['dev-bridge'], route_class=store.BoundedRoute)
BUCKET = 'dev-desk'
_IMAGE = {'PNG': ('image/png', 'png'), 'JPEG': ('image/jpeg', 'jpg'),
          'WEBP': ('image/webp', 'webp'), 'GIF': ('image/gif', 'gif')}
_TEXT = {'text/plain': 'txt', 'text/markdown': 'md', 'application/json': 'json', 'text/csv': 'csv'}
_COLUMNS = 'id,kind,title,caption,url,mime,bytes,width,height,worker,mission,created_at'


class CardMeta(BaseModel):
    kind: Literal['link', 'image', 'file', 'screenshot', 'preview']
    title: str = Field(default='', max_length=120)
    caption: str = Field(default='', max_length=500)
    url: Optional[str] = Field(default=None, max_length=2048)
    worker: Optional[str] = Field(default=None, max_length=40)
    mission: Optional[str] = Field(default=None, max_length=80)


def _url(raw):
    if not raw:
        return None
    try:
        u = urlsplit(raw)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username is not None or u.password is not None:
            raise ValueError()
        if any(ord(ch) < 32 for ch in raw):
            raise ValueError()
        _ = u.port
    except ValueError:
        raise HTTPException(422, 'Card URL must be http(s), with no credentials')
    return dev_redact.text(raw)


async def _read(file, cap):
    data = await file.read(cap + 1)
    if len(data) > cap:
        raise HTTPException(413, 'Card file is too large')
    return data


def _image(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                mime, ext = _IMAGE[im.format]
                width, height = im.size
                im.verify()
        return mime, ext, width, height
    except Exception:
        raise HTTPException(415, 'Unsupported or invalid image bytes')


def _file(data, declared, filename):
    name = (filename or '').replace('\\', '/').split('/')[-1].lower()
    if (name.startswith(('.env', 'id_rsa', 'credentials', 'secrets')) or
            name in ('.npmrc', '.netrc') or name.endswith(('.pem', '.key', '.pfx', '.p12', '.html', '.htm', '.svg'))):
        raise HTTPException(415, 'This file type cannot be relayed')
    if data.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'GIF87a', b'GIF89a')) or (data[:4] == b'RIFF' and data[8:12] == b'WEBP'):
        mime, ext, w, h = _image(data)
        return data, mime, ext, w, h
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, 'Files are limited to 5 MB')
    if data.startswith(b'%PDF-'):
        if b'%%EOF' not in data[-2048:]:
            raise HTTPException(415, 'Invalid PDF')
        return data, 'application/pdf', 'pdf', None, None
    if declared not in _TEXT:
        raise HTTPException(415, 'Unsupported file MIME type')
    try:
        value = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise HTTPException(415, 'Text must be UTF-8')
    if re.search(r'<\s*(?:!doctype\s+html|html|head|body|script|svg|iframe)\b', value, re.I) or any(ord(ch) < 32 and ch not in '\n\r\t' for ch in value):
        raise HTTPException(415, 'HTML and binary content are refused')
    if declared == 'application/json':
        try:
            parsed = json.loads(value)
        except ValueError:
            raise HTTPException(415, 'Invalid JSON')
        value = json.dumps(dev_redact.deep(parsed, keep=frozenset()), ensure_ascii=False)
    else:
        value = dev_redact.text(value)
    redacted = value.encode('utf-8')
    if len(redacted) > 5 * 1024 * 1024:
        raise HTTPException(413, 'Redacted file exceeds 5 MB')
    return redacted, declared, _TEXT[declared], None, None


async def _upload(c, path, data, mime):
    r = await c.post(f'{storage_links._base()}/storage/v1/object/{BUCKET}/{path}',
                     headers={**storage_links.service_headers(), 'Content-Type': mime}, content=data)
    if r.status_code >= 400:
        raise HTTPException(502, f'Private card storage unavailable; apply {store.MIGRATION}')


async def _remove_objects(c, paths):
    if not paths:
        return
    r = await c.request('DELETE', f'{storage_links._base()}/storage/v1/object/{BUCKET}',
                        headers=storage_links.service_headers(), json={'prefixes': paths})
    if r.status_code >= 400:
        raise HTTPException(502, 'Card storage deletion failed; retry the purge')


async def shown(c, row):
    out = {k: row.get(k) for k in _COLUMNS.split(',')}
    out.update(has_file=bool(row.get('object_path')), has_thumb=bool(row.get('thumb_path')),
               url_expires_at=store.z(store.now() + timedelta(seconds=900)))
    if row.get('object_path'):
        out['file_url'] = await storage_links.signed_url(c, BUCKET, row['object_path'], ttl=900,
            download_as=row.get('filename') if row['kind'] == 'file' else None)
    if row.get('thumb_path'):
        out['thumb_url'] = await storage_links.signed_url(c, BUCKET, row['thumb_path'], ttl=900)
    return out


async def card_map(c, messages):
    ids = set()
    for m in messages:
        raw = (m.get('meta') or {}).get('card')
        if raw:
            try:
                ids.add(store.uid(raw))
            except HTTPException:
                pass
    if not ids:
        return {}
    rows = await store.get(c, 'dev_cards', {'id': f"in.({','.join(sorted(ids))})",
                                          'expires_at': f'gt.{store.z(store.now())}', 'select': '*'})
    return {r['id']: await shown(c, r) for r in rows}


@router.post('/dev-bridge/cards')
async def card_upload(meta: str = Form(...), file: Optional[UploadFile] = File(None),
                      thumb: Optional[UploadFile] = File(None), authorization: Optional[str] = Header(None)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        try:
            info = CardMeta.model_validate_json(meta)
        except (ValueError, ValidationError):
            raise HTTPException(422, 'Invalid card metadata')
        url = _url(info.url)
        if info.kind in ('link', 'preview') and not url:
            raise HTTPException(422, 'This card needs a URL')
        if info.kind in ('image', 'file', 'screenshot') and file is None:
            raise HTTPException(422, 'This card needs a file')
        if info.kind == 'link' and (file or thumb):
            raise HTTPException(422, 'Link cards do not carry files')
        if thumb and not file:
            raise HTTPException(422, 'A thumbnail needs an original')
        card_id = str(uuid4())
        row = {**dev_redact.deep(info.model_dump()), 'url': url, 'id': card_id, 'device_id': device['id'],
               'created_at': store.z(store.now()), 'expires_at': store.z(store.now()+timedelta(days=30))}
        objects = []
        if file:
            data = await _read(file, 8 * 1024 * 1024)
            data, mime, ext, w, h = _file(data, file.content_type, file.filename)
            if info.kind in ('image', 'screenshot', 'preview') and not mime.startswith('image/'):
                raise HTTPException(415, 'This card requires an image')
            row.update(mime=mime, bytes=len(data), width=w, height=h, sha256=hashlib.sha256(data).hexdigest(),
                       filename=dev_redact.text((file.filename or 'file').replace('\\', '/').split('/')[-1])[:120],
                       object_path=f"{device['id']}/{card_id}/original.{ext}")
            objects.append((row['object_path'], data, mime))
        if thumb:
            data = await _read(thumb, 300 * 1024)
            mime, _, w, _ = _image(data)
            if mime != 'image/jpeg' or w > 480:
                raise HTTPException(415, 'Thumbnail must be JPEG and at most 480 px wide')
            row['thumb_path'] = f"{device['id']}/{card_id}/thumb.jpg"
            objects.append((row['thumb_path'], data, mime))
        # Persist the cleanup record first. It stays expired until every upload
        # succeeds; failed/in-flight uploads never appear in owner reads.
        expiry = row['expires_at']
        row['expires_at'] = store.z(store.now())
        await store.insert(c, 'dev_cards', row)
        try:
            for path, data, mime in objects:
                await _upload(c, path, data, mime)
            # The SQL trigger rechecks revocation while locking the device.
            updated = await store.patch(c, 'dev_cards', {'id': f'eq.{card_id}'}, {'expires_at': expiry})
            if not updated:
                raise HTTPException(409, 'Device was unpaired during upload')
        except Exception:
            await _remove_objects(c, [p for p, _, _ in objects])
            await store.delete(c, 'dev_cards', {'id': f'eq.{card_id}'})
            raise
        row['expires_at'] = expiry
        return {'ok': True, 'card': await shown(c, row)}


@router.get('/platform/dev-desk/cards/{id}')
async def card_get(id: str, _owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        rows = await store.get(c, 'dev_cards', {'id': f'eq.{store.uid(id)}',
                                              'expires_at': f'gt.{store.z(store.now())}', 'select': '*'})
        if not rows:
            raise HTTPException(404, 'Card expired or unavailable')
        return {'ok': True, 'card': await shown(c, rows[0])}


async def purge_cards(c, filters):
    rows = await store.all_rows(c, 'dev_cards', {**filters, 'select': 'id,object_path,thumb_path', 'order': 'id'})
    for row in rows:
        await _remove_objects(c, [row[k] for k in ('object_path', 'thumb_path') if row.get(k)])
        await store.delete(c, 'dev_cards', {'id': f"eq.{row['id']}"})
    return len(rows)

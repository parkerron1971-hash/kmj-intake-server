"""Solutionist's own approved marketing calendar, isolated from tenant publishing."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from PIL import Image

from buffer_client import BufferClient, BufferError
from lead_admin import require_owner
from auth_supabase import UserSession
import sb_clients

router = APIRouter(prefix='/platform/marketing', tags=['platform-marketing'], dependencies=[Depends(require_owner)])
logger = logging.getLogger(__name__)
SUPPORTED = {'facebook', 'instagram', 'twitter', 'linkedin'}
MAX_BYTES = 100 * 1024 * 1024


def now():
    return datetime.now(timezone.utc)


async def db(method, path, body=None):
    """Fail closed; never confuse missing schema or failed writes with empty data."""
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.request(method, sb_clients.sb_url() + '/rest/v1' + path,
                headers=sb_clients.sb_headers_service(), json=body)
        except httpx.HTTPError:
            raise HTTPException(503, 'Marketing storage is unavailable. Please retry.') from None
    if r.status_code >= 400:
        if r.status_code == 409 or (r.status_code == 400 and '/rpc/' in path):
            raise HTTPException(409, 'The post changed or its schedule passed. Refresh and review again.')
        raise HTTPException(503, 'Marketing storage is not ready. Apply the platform marketing migration and check server access.')
    return r.json() if r.content else []


async def config():
    rows = await db('GET', '/platform_marketing_config?id=eq.true')
    if not rows:
        raise HTTPException(503, 'Apply the platform marketing migration first.')
    return rows[0]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise HTTPException(422, 'Choose a date with a timezone.')
    return value.astimezone(timezone.utc)


def tracked_link(url, service, campaign, creative):
    try:
        parts = urlsplit(url)
        valid = parts.scheme == 'https' and parts.hostname in {'mysolutionist.app', 'www.mysolutionist.app'} and not parts.username and parts.port in (None,443)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(422, 'Use an https://mysolutionist.app landing page for Solutionist marketing.')
    tags = dict(parse_qsl(parts.query, keep_blank_values=True))
    tags.update(utm_source='x' if service == 'twitter' else service, utm_medium='organic_social',
                utm_campaign=campaign, utm_content=creative)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', urlencode(tags), parts.fragment))


def link_code(post_id):
    """The post's short-link code: 8 characters, derived from its id.

    Derived rather than random so a retried save, an edit or a rebuilt
    preview always lands on the same code \u2014 the link in an approved caption
    can never drift away from the post it names."""
    raw = hashlib.sha256(f'platform-marketing-go:{post_id}'.encode()).digest()[:5]
    return base64.b32encode(raw).decode().lower()


def short_link(code):
    return f'https://mysolutionist.app/go/{code}'


GO_CODE = re.compile(r'^[a-z2-7]{8}$')


def caption_with_landing_link(text, url, link):
    """Keep public captions clean; attribution metadata is not public copy.

    The public text carries the post's short link, never a tagged URL. The
    redirect behind the link adds the campaign tags, which is what lets a
    visit be followed back to this post \u2014 the clean destination on its own
    arrived untracked. A caption that already names the landing page has
    that mention swapped for the short link; otherwise the link is appended
    once. The caller validates the destination through tracked_link first.
    """
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not k.lower().startswith('utm_')])
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path or '/', query, parts.fragment))

    def destination(value):
        try:
            parsed = urlsplit(value if '://' in value else 'https://' + value)
            return (parsed.hostname.removeprefix('www.'), parsed.path or '/',
                    tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True))), parsed.fragment)
        except ValueError:
            return None

    # Match entire URLs, not substrings of another host, path or email address.
    pattern = re.compile(r'(?<![\w@./-])(?:https?://)?(?:www\.)?mysolutionist\.app\b[^\s<>"\u201c\u201d]*', re.I)
    if link in text:
        return text
    target = destination(clean)
    found = False

    def swap(match):
        nonlocal found
        value = match.group(0)
        bare = value.rstrip('.,!;:)]}')
        if destination(bare) != target:
            return value
        found = True
        return link + value[len(bare):]

    swapped = pattern.sub(swap, text)
    return swapped if found else text + '\n\n' + link


class Connection(BaseModel):
    organization_id: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    channel_ids: list[str] = Field(min_length=1, max_length=10)


class Pause(BaseModel):
    paused: bool


class Draft(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    revision: int | None = None
    campaign: str = Field(min_length=1, max_length=100)
    campaign_id: UUID | None = None
    text: str = Field(min_length=1, max_length=5000)
    channel_id: str = Field(min_length=1, max_length=100)
    landing_url: str = Field(default='https://mysolutionist.app/', max_length=1500)
    asset_id: UUID | None = None
    run_at: datetime
    expires_at: datetime | None = None
    ai_assisted: bool = False


class ReviewItem(BaseModel):
    id: UUID
    revision: int
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class Review(BaseModel):
    items: list[ReviewItem] = Field(min_length=1, max_length=50)


class Revision(BaseModel):
    revision: int


class Reconcile(BaseModel):
    provider_id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$', max_length=150)


def post_payload(row):
    p = row['payload']
    assets = [{p['asset']['kind']: {'url': p['asset']['url']}}] if p.get('asset') else []
    metadata = {}
    if p['service'] in {'instagram', 'facebook'}:
        kind = 'reel' if (p.get('asset') or {}).get('kind') == 'video' else 'post'
        metadata[p['service']] = {'type': kind}
        if p['service'] == 'instagram':
            metadata['instagram']['shouldShareToFeed'] = True
    return {'channelId': p['channel_id'], 'text': p['publish_text'], 'assets': assets,
            'schedulingType': 'automatic', 'mode': 'shareNow', 'needsApproval': False,
            'saveToDraft': False, 'aiAssisted': p.get('ai_assisted', False), 'metadata': metadata}


@router.get('/status')
async def status():
    cfg = await config()
    return {'configured': bool(os.environ.get('BUFFER_API_KEY', '').strip()),
            'worker_enabled': os.environ.get('BUFFER_PUBLISHING', 'off').lower() == 'on',
            'config': cfg, 'supported_services': sorted(SUPPORTED)}


@router.get('/connection')
async def connection():
    try:
        async with httpx.AsyncClient() as client:
            api = BufferClient(client)
            account = await api.account()
            organizations = []
            for org in account.get('organizations', []):
                channels = await api.channels(org['id'])
                organizations.append({**org, 'channels': channels})
            return {'organizations': organizations}
    except BufferError as e:
        raise HTTPException(502, str(e)) from None


@router.put('/connection')
async def save_connection(req: Connection):
    try:
        async with httpx.AsyncClient() as client:
            channels = await BufferClient(client).channels(req.organization_id)
    except BufferError as e:
        raise HTTPException(502, str(e)) from None
    selected = [c for c in channels if c['id'] in req.channel_ids]
    if len(selected) != len(set(req.channel_ids)) or any(c['service'] not in SUPPORTED for c in selected):
        raise HTTPException(422, 'Choose supported channels from this Buffer organization.')
    if any(c['isDisconnected'] or c['isLocked'] for c in selected):
        raise HTTPException(422, 'Reconnect or unlock the selected channels in Buffer first.')
    # Saving different destinations pauses delivery. Old approvals are bound to
    # their original organization/channel and cannot be silently redirected.
    return (await db('PATCH', '/platform_marketing_config?id=eq.true',
        {'organization_id': req.organization_id, 'channels': selected, 'paused': True,
         'updated_at': now().isoformat()}))[0]


@router.put('/pause')
async def pause(req: Pause):
    cfg = await config()
    if not req.paused and (not cfg['channels'] or not os.environ.get('BUFFER_API_KEY')):
        raise HTTPException(409, 'Connect Buffer and select Solutionist channels first.')
    return (await db('PATCH', '/platform_marketing_config?id=eq.true',
        {'paused': req.paused, 'updated_at': now().isoformat()}))[0]


@router.get('/posts')
async def posts():
    rows = await db('GET', '/platform_marketing_posts?order=run_at.desc&limit=500')
    return {'posts': rows, 'truncated': len(rows) == 500}


@router.get('/assets')
async def assets():
    return await db('GET', '/platform_marketing_assets?order=created_at.desc&limit=100')


@router.post('/assets')
async def upload_asset(file: UploadFile = File(...)):
    return await save_asset(file)


class ChiefArtwork(BaseModel):
    image_id: UUID


@router.post('/assets/from-chief')
async def import_chief_artwork(req: ChiefArtwork, owner=Depends(require_owner),
                               session: UserSession = Depends(sb_clients.authed_request)):
    from platform_chief_creative import platform_business
    import image_studio
    from starlette.datastructures import Headers
    biz = await platform_business(owner)
    # Resolve original bytes with the real user JWT and platform business ID;
    # never accept a client URL or a selected tenant ID for a public copy.
    async with httpx.AsyncClient(timeout=60) as client:
        row = await image_studio.artwork(client, biz['id'], req.image_id)
        raw = image_studio.normalize_image(await image_studio.original(client, row))
    aid = uuid5(NAMESPACE_URL, f"platform-marketing:{biz['id']}:{req.image_id}")
    return await save_asset(UploadFile(filename=f'Chief artwork {str(req.image_id)[:8]}.png',
        file=io.BytesIO(raw), headers=Headers({'content-type': 'image/png'})), asset_id=aid)


async def save_asset(file: UploadFile, *, asset_id=None):
    if asset_id is not None:
        existing = await db('GET', f'/platform_marketing_assets?id=eq.{asset_id}&limit=1')
        if existing:
            return existing[0]
    # Streaming read bounds memory even when Content-Length is absent/false.
    blob = bytearray()
    while chunk := await file.read(1024 * 1024):
        blob.extend(chunk)
        if len(blob) > MAX_BYTES:
            raise HTTPException(413, 'Marketing exports must be 100 MB or smaller.')
    mime = file.content_type
    if mime in ('image/png', 'image/jpeg'):
        try:
            with Image.open(io.BytesIO(blob)) as im:
                expected = 'PNG' if mime == 'image/png' else 'JPEG'
                if im.format != expected:
                    raise ValueError()
                im.verify()
        except Exception:
            raise HTTPException(422, 'Upload a valid PNG or JPEG export.') from None
        ext, kind = ('png' if mime == 'image/png' else 'jpg'), 'image'
    elif mime == 'video/mp4' and len(blob) >= 12 and blob[4:8] == b'ftyp':
        ext, kind = 'mp4', 'video'
    else:
        raise HTTPException(422, 'Upload a PNG, JPEG or MP4 marketing export.')
    aid = str(asset_id or uuid4())
    sha = hashlib.sha256(blob).hexdigest()
    path = f'platform-marketing/{aid}/{sha}.{ext}'
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(sb_clients.sb_url() + '/storage/v1/object/' + path,
                headers={**sb_clients.sb_headers_service(), 'Content-Type': mime,
                         'x-upsert': 'true' if asset_id else 'false'}, content=bytes(blob))
    except httpx.HTTPError:
        raise HTTPException(503, 'The upload connection was interrupted. Check Marketing assets before retrying.') from None
    if r.status_code >= 400:
        raise storage_upload_error(r, len(blob), mime)
    row = {'id': aid, 'sha256': sha, 'url': sb_clients.sb_url() + '/storage/v1/object/public/' + path,
           'kind': kind, 'mime_type': mime, 'name': (file.filename or 'Marketing export')[:180]}
    try:
        return (await db('POST', '/platform_marketing_assets', row))[0]
    except HTTPException:
        if asset_id is not None:
            existing = await db('GET', f'/platform_marketing_assets?id=eq.{aid}&limit=1')
            if existing:
                return existing[0]
        raise


def storage_upload_error(response, size, mime):
    # Supabase can wrap a 413 in HTTP 400. Never expose raw provider details,
    # file names, auth headers or payloads in browser errors/logs.
    try:
        detail = response.json()
        if not isinstance(detail, dict): detail = {}
    except ValueError:
        detail = {}
    code = str(detail.get('code') or detail.get('error') or '')
    message = str(detail.get('message') or '').lower()
    logger.warning('Marketing upload rejected: status=%s code=%s bytes=%s mime=%s',
        response.status_code, ''.join(c for c in code if c.isalnum())[:80], size, mime)
    if response.status_code == 413 or str(detail.get('statusCode')) == '413' or code.lower() in ('entitytoolarge', 'payloadtoolarge') or 'maximum allowed size' in message:
        return HTTPException(413, 'Storage rejected this file as too large. Marketing supports up to 100 MB; the project and bucket storage limits must both allow 100 MB.')
    if code.lower() == 'invalidmimetype' or response.status_code == 415 or 'mime type' in message:
        return HTTPException(415, 'Storage rejected this file format. Marketing accepts PNG, JPEG and MP4; check the marketing bucket allows this format.')
    if response.status_code in (401, 403):
        return HTTPException(503, 'Marketing storage denied the upload. The server storage connection needs attention.')
    return HTTPException(503, 'Marketing storage could not save this file. Please retry later; the upload failure has been logged.')


async def build_draft(req):
    if req.campaign_id:
        from platform_marketing_campaigns import get_campaign
        campaign_record = await get_campaign(req.campaign_id)
        if campaign_record['stage'] == 'archived':
            raise HTTPException(409, 'This campaign is archived. Reopen it before preparing posts.')
        if req.campaign != campaign_record['tracking_key']:
            raise HTTPException(422, 'Use the campaign’s permanent tracking key.')
    cfg = await config()
    channel = next((c for c in cfg['channels'] if c['id'] == req.channel_id), None)
    if not channel:
        raise HTTPException(422, 'Select one of the connected Solutionist channels.')
    run_at = aware(req.run_at)
    expires = aware(req.expires_at) if req.expires_at else run_at + timedelta(hours=6)
    if not now() < run_at <= now() + timedelta(days=90) or expires <= run_at:
        raise HTTPException(422, 'Schedule within the next 90 days and expire after the publishing time.')
    asset = None
    if req.asset_id:
        rows = await db('GET', f'/platform_marketing_assets?id=eq.{req.asset_id}&limit=1')
        if not rows:
            raise HTTPException(422, 'Choose a saved marketing export.')
        asset = rows[0]
    if channel['service'] == 'instagram' and not asset:
        raise HTTPException(422, 'Instagram requires an image or video.')
    campaign = req.campaign.strip()
    if not campaign:
        raise HTTPException(422, 'Enter a campaign name.')
    link = tracked_link(req.landing_url, channel['service'], campaign, str(req.id))
    text = req.text.strip()
    if not text:
        raise HTTPException(422, 'Write a caption before saving.')
    code = link_code(req.id)
    publish_text = caption_with_landing_link(text, req.landing_url, short_link(code))
    # Buffer performs final platform/media validation; local length catches
    # accidental long captions early. URLs count as 23 characters on X.
    if channel['service'] == 'twitter' and len(text) + 25 > 280:
        raise HTTPException(422, 'Keep the X caption at 255 characters or fewer, leaving room for its link.')
    limits = {'instagram':2200, 'linkedin':3000, 'facebook':5000}
    if len(publish_text) > limits.get(channel['service'], 10000):
        raise HTTPException(422, 'Caption and website link exceed this channel’s limit.')
    payload = {'organization_id': cfg['organization_id'], 'channel_id': channel['id'],
        'channel_name': channel.get('displayName') or channel['name'], 'service': channel['service'],
        'text': text, 'publish_text': publish_text, 'landing_url': req.landing_url,
        'tracked_url': link, 'asset': asset, 'ai_assisted': req.ai_assisted}
    row = {'id': str(req.id), 'campaign': campaign, 'payload': payload,
           'run_at': run_at.isoformat(), 'expires_at': expires.isoformat()}
    row['content_hash'] = digest(row)
    # Relationship metadata stays outside the public-content hash so migration
    # does not invalidate already reviewed legacy posts. The link code is
    # already inside the hash through publish_text; the column is its index.
    row['link_code'] = code
    if req.campaign_id:
        row['campaign_id'] = str(req.campaign_id)
    return row


async def follow(code, *, count_click):
    """The tagged destination behind a short link, or None for an unknown code."""
    if not GO_CODE.match(code or ''):
        return None
    try:
        url = await db('POST', '/rpc/platform_marketing_follow', {'code': code, 'count_click': count_click})
    except HTTPException:
        return None
    # Never an open redirect: only a destination tracked_link would build.
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
    except ValueError:
        parts = None
    if not parts or parts.scheme != 'https' or parts.hostname not in {'mysolutionist.app', 'www.mysolutionist.app'}:
        return None
    return url


@router.post('/posts')
async def save_draft(req: Draft):
    if req.revision is not None:
        # Preserve the campaign when legacy clients/Chief omit its ID on edit.
        current = await db('GET', f'/platform_marketing_posts?id=eq.{req.id}&limit=1')
        linked = current[0].get('campaign_id') if current else None
        if linked:
            if req.campaign_id and str(req.campaign_id) != linked:
                raise HTTPException(409, 'A saved post cannot move between campaigns.')
            req = req.model_copy(update={'campaign_id':UUID(linked)})
    row = await build_draft(req)
    if req.revision is None:
        # Caller-chosen UUID makes a retried save detectable, not a new post.
        return (await db('POST', '/platform_marketing_posts', row))[0]
    row.update(revision=req.revision + 1, status='draft', approved_hash=None, approved_by=None,
               approved_at=None, error=None)
    saved = await db('PATCH', f'/platform_marketing_posts?id=eq.{req.id}&revision=eq.{req.revision}&status=in.(draft,approved,failed)&provider_id=is.null', row)
    if not saved:
        raise HTTPException(409, 'Post changed or delivery has started. Refresh before editing.')
    return saved[0]


@router.post('/approve')
async def approve(req: Review, owner=Depends(require_owner)):
    # Refresh channel health once per batch before approving exact snapshots.
    cfg = await config()
    try:
        async with httpx.AsyncClient() as client:
            channels = await BufferClient(client).channels(cfg['organization_id'])
    except BufferError as e:
        raise HTTPException(502, str(e)) from None
    allowed = {c['id'] for c in channels if not (c['isDisconnected'] or c['isLocked'] or c['isQueuePaused'])}
    selected = {c['id'] for c in cfg['channels']}
    for item in req.items:
        rows = await db('GET', f'/platform_marketing_posts?id=eq.{item.id}&limit=1')
        if not rows or rows[0]['payload']['organization_id'] != cfg['organization_id'] or rows[0]['payload']['channel_id'] not in allowed & selected:
            raise HTTPException(409, 'A destination is unavailable or changed. Reconnect and review.')
    count = await db('POST', '/rpc/platform_marketing_approve',
                    {'items': [i.model_dump(mode='json') for i in req.items], 'actor': str(owner.id)})
    return {'approved': count}


@router.post('/posts/{post_id}/cancel')
async def cancel(post_id: UUID, req: Revision):
    rows = await db('PATCH', f'/platform_marketing_posts?id=eq.{post_id}&revision=eq.{req.revision}&status=in.(draft,approved,failed)&provider_id=is.null',
                    {'status': 'cancelled', 'revision': req.revision + 1})
    if not rows:
        raise HTTPException(409, 'Delivery may already be in progress. Check Buffer before cancelling there.')
    return rows[0]


class SlotItem(BaseModel):
    id: UUID
    revision: int


class SlotEdit(BaseModel):
    """One idea's posts — the same caption on each channel — changed together."""
    items: list[SlotItem] = Field(min_length=1, max_length=10)
    text: str | None = Field(default=None, min_length=1, max_length=5000)
    run_at: datetime | None = None


class SlotCancel(BaseModel):
    items: list[SlotItem] = Field(min_length=1, max_length=30)


async def edit_slot(req: SlotEdit, *, ai_assisted=None):
    """Rewrite and/or move every channel post of one idea. Each goes back to
    draft for review, exactly like a single edit. Every post is rebuilt and
    checked before any is saved, so a caption too long for X fails the whole
    idea instead of leaving its channels saying different things."""
    if req.text is None and req.run_at is None:
        raise HTTPException(422, 'Change the caption or the time.')
    drafts = []
    for item in req.items:
        rows = await db('GET', f'/platform_marketing_posts?id=eq.{item.id}&limit=1')
        if not rows:
            raise HTTPException(409, 'A post in this idea no longer exists. Refresh the desk.')
        row = rows[0]
        p = row['payload']
        moved = req.run_at is not None
        drafts.append(Draft(id=item.id, revision=item.revision, campaign=row['campaign'],
                            campaign_id=row.get('campaign_id'),
                            text=req.text if req.text is not None else p['text'],
                            channel_id=p['channel_id'], landing_url=p['landing_url'],
                            asset_id=(p.get('asset') or {}).get('id'),
                            run_at=req.run_at if moved else row['run_at'],
                            # A new time gets a fresh delivery window; the old one would end before it.
                            expires_at=None if moved else row['expires_at'],
                            ai_assisted=p.get('ai_assisted', False) if ai_assisted is None else ai_assisted))
    for draft in drafts:
        await build_draft(draft)
    return {'posts': [await save_draft(d) for d in drafts]}


@router.post('/slot/edit')
async def edit_slot_route(req: SlotEdit):
    return await edit_slot(req)


@router.post('/slot/cancel')
async def cancel_slot(req: SlotCancel):
    """Skip one idea, or let missed drafts go: cancels each channel post."""
    done = [await cancel(item.id, Revision(revision=item.revision)) for item in req.items]
    return {'cancelled': len(done), 'posts': done}


@router.post('/posts/{post_id}/not-sent')
async def mark_not_sent(post_id: UUID, req: Revision):
    """The owner checked Buffer and the post is not there: an unconfirmed
    delivery becomes a plain failure, which can be edited and approved again."""
    rows = await db('PATCH', f'/platform_marketing_posts?id=eq.{post_id}&revision=eq.{req.revision}'
                             '&status=eq.uncertain&provider_id=is.null',
                    {'status': 'failed', 'revision': req.revision + 1, 'checked_at': now().isoformat(),
                     'error': 'Checked in Buffer and marked not sent. Edit or approve it again to reschedule.'})
    if not rows:
        raise HTTPException(409, 'Only an unconfirmed delivery can be marked not sent. Refresh the desk.')
    return rows[0]


def delivery_result(post):
    status = str(post.get('status', '')).lower()
    if status == 'sent':
        return {'status': 'published', 'external_url': post.get('externalLink'), 'error': None}
    if status in {'error', 'failed', 'not_sent'}:
        return {'status': 'failed', 'error': 'Buffer reported a publishing failure. Review this post in Buffer.'}
    if status == 'draft':
        return {'status': 'failed', 'error': 'Buffer retained this post as a draft. Review its approval settings in Buffer.'}
    return {'status': 'submitted', 'error': None}


@router.post('/posts/{post_id}/reconcile')
async def reconcile(post_id: UUID, req: Reconcile):
    rows = await db('GET', f'/platform_marketing_posts?id=eq.{post_id}&status=eq.uncertain&limit=1')
    if not rows:
        raise HTTPException(409, 'Only uncertain deliveries can be reconciled.')
    row = rows[0]
    try:
        async with httpx.AsyncClient() as client:
            post = await BufferClient(client).post(req.provider_id)
    except BufferError as e:
        raise HTTPException(502, str(e)) from None
    if post['channelId'] != row['payload']['channel_id'] or post['text'] != row['payload']['publish_text']:
        raise HTTPException(422, 'That Buffer post does not match this destination and exact caption.')
    return await db('PATCH', f'/platform_marketing_posts?id=eq.{post_id}&status=eq.uncertain',
                    {**delivery_result(post), 'provider_id': post['id'], 'checked_at': now().isoformat()})


async def dispatch(row, api):
    """Hand one claimed post to Buffer and record what happened; returns the patch.

    Only a failure AFTER the create call was attempted can mean "maybe sent".
    Anything before it (storage blip, config read, channel check) means
    nothing left this server, so the post fails plainly and can be edited and
    approved again. Until 2026-10-02 such an error escaped, the row sat in
    dispatching, the recovery sweep made it "uncertain", and an uncertain post
    with no Buffer id had no way out."""
    attempted = False
    try:
        cfg = await config()
        p = row['payload']
        approved = {'id':row['id'], 'campaign':row['campaign'], 'payload':p,
                    'run_at':aware(row['run_at']).isoformat(), 'expires_at':aware(row['expires_at']).isoformat()}
        if row['approved_hash'] != digest(approved):
            raise BufferError('Approved content changed. Review it again.')
        if cfg['paused'] or p['organization_id'] != cfg['organization_id'] or p['channel_id'] not in {c['id'] for c in cfg['channels']}:
            raise BufferError('Publishing paused or destination changed. Review a new schedule.')
        live = await api.channels(cfg['organization_id'])
        channel = next((c for c in live if c['id'] == p['channel_id']), None)
        if not channel or any(channel[k] for k in ('isDisconnected','isLocked','isQueuePaused')):
            raise BufferError('Destination is disconnected, locked or paused in Buffer.')
        if aware(row['expires_at']) <= now():
            raise BufferError('The delivery window expired. Review a new schedule.')
        attempted = True
        post = await api.create(post_payload(row))
        patch = {**delivery_result(post), 'provider_id':post['id'], 'checked_at':now().isoformat()}
    except BufferError as e:
        patch = {'status': 'uncertain' if e.uncertain else 'failed', 'error': str(e)}
    except Exception:
        logger.warning('Marketing delivery stopped %s Buffer was reached.', 'after' if attempted else 'before',
                       exc_info=True)
        patch = ({'status': 'uncertain', 'error': 'Delivery was interrupted. Check Buffer, then mark it sent or not sent.'}
                 if attempted else
                 {'status': 'failed', 'error': 'This post could not be checked before sending, so it was not sent. '
                                               'Edit or approve it again to reschedule.'})
    # If persistence fails after create, leave dispatching; the stale-claim
    # recovery moves it to uncertain and will NEVER automatically create again.
    await db('PATCH', f"/platform_marketing_posts?id=eq.{row['id']}&status=eq.dispatching", patch)
    return patch


async def due_tick():
    if os.environ.get('BUFFER_PUBLISHING', 'off').lower() != 'on' or not os.environ.get('BUFFER_API_KEY'):
        return
    trouble = []
    try:
        async with httpx.AsyncClient() as client:
            api = BufferClient(client)
            for _ in range(5):
                rows = await db('POST', '/rpc/platform_marketing_claim', {})
                if not rows:
                    break
                patch = await dispatch(rows[0], api)
                if patch.get('status') in ('failed', 'uncertain'):
                    trouble.append({**rows[0], **patch})
    except Exception:
        logger.warning('Marketing delivery tick failed; durable claims retained for reconciliation.', exc_info=True)
    if trouble:
        try:
            import marketing_desk
            await marketing_desk.tell_owner_about_delivery(trouble)
        except Exception:
            logger.warning('Marketing delivery: could not tell the owner.', exc_info=True)


async def reconcile_tick():
    if not os.environ.get('BUFFER_API_KEY'):
        return
    try:
        # Recover interrupted attempts even while paused.
        cutoff = (now()-timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
        await db('PATCH', f'/platform_marketing_posts?status=eq.dispatching&claimed_at=lt.{cutoff}',
                 {'status':'uncertain','error':'Delivery interrupted. Reconcile with Buffer before retrying.'})
        rows = await db('GET', '/platform_marketing_posts?status=eq.submitted&provider_id=not.is.null&order=checked_at.asc.nullsfirst&limit=30')
        if not rows:
            return
        async with httpx.AsyncClient() as client:
            data = await BufferClient(client).posts([r['provider_id'] for r in rows])
        for i, row in enumerate(rows):
            post = data.get(f'p{i}')
            if post and post['id'] == row['provider_id']:
                await db('PATCH', f"/platform_marketing_posts?id=eq.{row['id']}&status=eq.submitted",
                    {**delivery_result(post), 'checked_at':now().isoformat()})
            else:
                # A removed/inaccessible provider post must not prevent the
                # rest of the batch from advancing or monopolize the first page.
                await db('PATCH', f"/platform_marketing_posts?id=eq.{row['id']}&status=eq.submitted",
                    {'error':'Buffer status could not be read. Check this post in Buffer.', 'checked_at':now().isoformat()})
    except Exception:
        logger.warning('Marketing status check failed; delivery state unchanged.', exc_info=True)

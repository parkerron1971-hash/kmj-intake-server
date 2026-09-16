"""Mission Control's creative tools use the owner's platform business only."""
import asyncio
from uuid import UUID, NAMESPACE_URL, uuid5

import httpx
from fastapi import HTTPException

import image_studio as images
import sb_clients

PROMPT = '''
CREATIVE TOOLS: You can actually create flyers, social graphics and video projects for
The Solutionist System. When asked to create artwork, execute generate_image; do not
merely describe a design or send a build request. If essential details are missing,
ask one focused question. Use only owner-approved claims, offers, prices and dates.
Brand: The Solutionist System; confident, clear, useful; audience solo operators and
small businesses; blue/navy with restrained violet, no green; destination mysolutionist.app.
Do not use historical pricing or beta availability from the strategic context in ads
unless the owner confirms it. Write the intended caption in your reply for review.
[ACTION:{"type":"generate_image","prompt":"complete creative brief and exact visible copy","size":"1024x1536","quality":"high"}]
Sizes: 1024x1536 flyer/story, 1024x1024 square, 1536x1024 landscape.
To revise saved artwork, include reference_ids:["artwork UUID from the conversation"].
Never invent IDs. Use [ACTION:{"type":"find_images"}] to retrieve saved artwork.
[ACTION:{"type":"create_video","brief":"complete approved brief","title":"short title","format":"portrait"}]
Video formats: landscape, portrait, square. This saves a project and queues its scene
plan. The owner opens Video Studio to review, revise and explicitly render it.
Generate at most one new image or video per turn. Jobs are asynchronous: say you are
requesting creation, never claim the file is finished. The result card is authoritative.
The image card offers Save to marketing and Prepare post. Those make a delivery copy
and a reviewable composer, never publish. You cannot approve or publish through these
creative actions. Creating an asset does not authorize distribution.
'''


async def platform_business(owner):
    # Shared resolver: ignores model/client business IDs, even another business
    # owned by the same operator. The creative job remains in platform books.
    from platform_console import _find_platform_business, _service_headers
    async with httpx.AsyncClient(timeout=20) as client:
        biz = await _find_platform_business(client, _service_headers(), str(owner.id))
    if not biz:
        raise HTTPException(409, 'Set up The Solutionist System in Mission Control → Money & Website first.')
    return biz


async def create_video(biz, owner, action, request_id):
    import video_studio as studio
    from video_studio_models import CreateProject, Message
    body = CreateProject(brief=action.get('brief', ''),
                         title=action.get('title') or 'Solutionist marketing video',
                         format=action.get('format') or 'portrait')
    if not studio.configuration()['planning_available']:
        raise HTTPException(503, 'Video planning is not enabled. Your image tools are still available.')
    pid = uuid5(NAMESPACE_URL, f"{biz['id']}:{request_id}:platform-video")
    plan = Message(message=body.brief, expected_revision=0, request_id=uuid5(pid, 'plan'))
    row = await asyncio.to_thread(studio.create, biz['id'], body, owner, project_id=pid)
    # Do not start a second job after a lost response or a later project edit.
    detail = await asyncio.to_thread(studio.detail, biz['id'], row['id'], owner)
    if not detail['jobs'] and not row.get('revision'):
        await asyncio.to_thread(studio.enqueue, biz['id'], row['id'],
            plan, owner, 'plan')
    return {'result': 'Video project saved. Open Video Studio to check the scene plan, revise it and review before rendering.',
            'label': 'Your video project', 'project_id': row['id'], 'business_id': str(biz['id'])}


def handlers(owner, request_id):
    """Request-local closures, never a global owner/tenant or actor override."""
    generated = False

    async def execute(action):
        nonlocal generated
        kind = action['type']
        if kind != 'find_images':
            if generated:
                raise HTTPException(422, 'Create one asset at a time. Ask Chief for the next variation when ready.')
            generated = True
            import spend_guard
            import rate_limit
            if not rate_limit.allow('platform_chief_creative', str(owner.id)):
                raise HTTPException(429, 'Please wait before starting another creative job.')
            if await asyncio.to_thread(spend_guard.over_budget):
                raise HTTPException(429, spend_guard.block_message())
        biz = await platform_business(owner)
        if not sb_clients.get_current_user_jwt():
            raise HTTPException(401, 'Sign in again to create artwork.')
        if kind == 'create_video':
            result = await create_video(biz, owner, action, request_id)
        else:
            identity = images.turn_id.set(str(request_id))
            index = images.turn_image_index.set(0)
            references = images.turn_references.set(())
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    handler = images.handle_generate_image if kind == 'generate_image' else images.handle_find_images
                    # No model-selected tenant, endpoint, model or website fetch.
                    safe = {k: action[k] for k in ('prompt', 'size', 'quality', 'reference_ids') if k in action}
                    result = await handler(client, biz, safe)
            finally:
                images.turn_id.reset(identity)
                images.turn_image_index.reset(index)
                images.turn_references.reset(references)
        return {**result, 'ok': not result.get('failed', False) and (result.get('image') or {}).get('status') != 'failed',
                'business_id': str(biz['id'])}

    return {kind: execute for kind in ('generate_image', 'find_images', 'create_video')}

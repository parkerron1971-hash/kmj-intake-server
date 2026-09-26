"""Structured creative dispatch and evidence-backed image status for Mission Control."""
import re
from uuid import UUID

import httpx
from fastapi import HTTPException

import image_studio as images
from chief_flyer_direction import FlyerBrief
from chief_flyer_composer import Layout

CREATIVE = {'generate_image', 'compose_flyer', 'create_video', 'find_images'}
PROMPT = '''
CREATIVE EXECUTION CONTRACT (takes precedence over creative ACTION-tag examples):
Use the native generate_image, compose_flyer, create_video and find_images tools for creative
work, not prose or ACTION tags. "Create it" after a visual brief means submit that brief now.
If essential copy/assets are missing or offer terms conflict with verified billing, call
creative_clarification with one precise question instead. Do not ask permission already given.
The server displays actual action status. Never claim a request was sent, an image exists,
a card is visible, a job is rendering, or a design has been visually reviewed without evidence.
You cannot see the user's UI. Prior assistant promises are not execution records. Descriptions
of an intended design are not observations of the generated pixels. For status use find_images;
for visual critique inspect the owned artwork pixels supplied by the server.
Creating a private asset does not schedule or publish it. Keep draft copy factual and distinguish
verified billing terms from ambiguous owner wording and earlier assistant inventions.
'''


def tool_specs():
    image = FlyerBrief.model_json_schema()
    image['properties'].update(size={'type': 'string', 'enum': ['1024x1024', '1024x1536', '1536x1024']},
                               quality={'type': 'string', 'enum': ['low', 'medium', 'high']})
    layout = Layout.model_json_schema()
    # Composition resolves chat:N to an owned UUID before normal validation.
    layout['$defs']['ImageLayer']['properties']['image_id'] = {'type': 'string', 'description': 'Owned artwork UUID or chat:N'}
    compose = {'type': 'object', 'properties': {'layout': {k: v for k,v in layout.items() if k != '$defs'}},
               'required': ['layout'], '$defs': layout['$defs']}
    return [
        {'name': 'generate_image', 'description': 'Submit one original image using the approved brief, exact copy, art direction and reference roles. Existing approval and budget rules apply.', 'input_schema': image},
        {'name': 'compose_flyer', 'description': 'Create a PNG and editable SVG from a complete owned-image, text and shape layout. Existing approval rules apply.', 'input_schema': compose},
        {'name': 'create_video', 'description': 'Create one video project and queue its scene plan for later owner review; does not render or publish.',
         'input_schema': {'type': 'object', 'properties': {'brief': {'type': 'string'}, 'title': {'type': 'string'}, 'format': {'type': 'string', 'enum': ['portrait','landscape','square']}}, 'required': ['brief']}},
        {'name': 'find_images', 'description': 'Read current owned artwork status and return real result cards. Does not create or retry an image.',
         'input_schema': {'type': 'object', 'properties': {'image_id': {'type': 'string', 'format': 'uuid', 'description': 'Use the actual artwork ID from this conversation when known.'}}}},
        {'name': 'creative_clarification', 'description': 'Ask one essential factual question when the requested creative cannot safely be produced from the brief. Do not invent offers or assets.',
         'input_schema': {'type': 'object', 'properties': {'question': {'type': 'string', 'minLength': 3, 'maxLength': 1000}}, 'required': ['question']}},
    ]


def create_requested(body):
    text = body.message.strip().lower().rstrip('.!')
    if len(text) > 500 or re.search(r"\b(don't|do not|not yet|before|if|suggest|ideas|concepts)\b", text):
        return False
    short = re.fullmatch(r'(?:please )?(?:create|generate|make|design|render) (?:it|that|this)(?: now)?', text)
    if short:
        return any(re.search(r'\b(flyer|image|visual|artwork|poster|graphic|video)\b', t.text, re.I) for t in body.history[-2:])
    return bool(re.match(r'(?:please )?(?:create|generate|make|design|render)\b', text)
                and re.search(r'\b(flyer|image|visual|artwork|poster|graphic|video)\b', text))


def status_requested(body):
    text = body.message.strip().lower().rstrip('?.!')
    return bool(re.fullmatch(r"(?:got (?:the|my) image|(?:is |where is |where's )(?:the |my )?(?:image|flyer|artwork)(?: ready| yet)?|i (?:don't|do not|can't|cannot) (?:see|find) (?:it|the image|the flyer)|(?:check|show)(?: me)? (?:the |my )?(?:image|flyer)(?: status)?)", text))


def selected_actions(blocks, legacy):
    native = [b for b in blocks if isinstance(b, dict) and b.get('type') == 'tool_use']
    if len(native) > 1:
        raise HTTPException(422, 'Chief requested multiple creative tools. No creative work was submitted; choose one asset.')
    selected, question = [], None
    for block in native:
        name, args = block.get('name'), block.get('input')
        if name not in CREATIVE | {'creative_clarification'} or not isinstance(args, dict):
            raise HTTPException(422, 'Chief returned an invalid creative command. No work was submitted.')
        if name == 'creative_clarification':
            question = str(args.get('question') or '').strip()[:1000]
            if not question:
                raise HTTPException(422, 'Chief returned an empty clarification. No work was submitted.')
        else:
            selected.append({**args, 'type': name})
    # Native calls own creative dispatch; duplicated legacy tags must not execute twice.
    if native:
        return ([] if question else selected + [a for a in legacy if a.get('type') not in CREATIVE]), question
    return legacy, None


def result_reply(results):
    lines = []
    for result in results:
        approval = result.get('approval') or {}
        status = approval.get('status')
        if status == 'pending':
            lines.append('Your creative request is awaiting approval in the review card. Generation has not started.')
        elif status in ('uncertain', 'executing'):
            lines.append('The creative request has an unresolved execution status. Check its action card before retrying; I cannot confirm a finished image.')
        elif not result.get('ok', True):
            lines.append(result.get('label') or 'The creative request failed. No completed image is confirmed.')
        elif result.get('image'):
            image = result['image']; state = image.get('status')
            lines.append({'ready': 'The saved image is ready; its result card is attached.',
                          'queued': 'The image request is queued. It is not ready yet.',
                          'working': 'The image is generating. It is not ready yet.',
                          'failed': 'The image job failed. Check the error on its result card.'}.get(state, 'The image status is not confirmed. Check its result card.'))
        elif result.get('type') == 'find_images':
            lines.append(result.get('result') or 'These are the saved image records I could verify.')
        elif result.get('project_id'):
            lines.append('The video project was saved. Open Video Studio to check its scene plan; no finished video is confirmed.')
        else:
            lines.append('No image job or completed file was returned. Check the action result before retrying.')
    return '\n\n'.join(lines)


async def status_result(body, owner):
    """Read only. Never turn assistant prose or a style benchmark into a job receipt."""
    from platform_chief_creative import platform_business
    import platform_chief_authority as authority
    explicit = re.search(r'\b(?:image|flyer|artwork)\s+([0-9a-fA-F-]{36})\b', body.message)
    iid = str(UUID(explicit.group(1))) if explicit else None
    if not iid:
        for index in range(len(body.history) - 1, -1, -1):
            turn = body.history[index]
            if turn.role == 'you':
                from platform_chief_marketing import ChiefMessageBody
                if create_requested(ChiefMessageBody(message=turn.text, history=body.history[:index])):
                    break  # A newer creation request must not inherit an older image receipt.
            if turn.role == 'chief':
                match = re.search(r'\[Image references:\s*([0-9a-fA-F-]{36})', turn.text)
                if match:
                    iid = str(UUID(match.group(1))); break
    try:
        biz = await platform_business(owner)
        async with httpx.AsyncClient(timeout=30) as client:
            await images.business(client, biz['id'])
            if iid:
                rows = [await images.artwork(client, biz['id'], iid)]
            else:
                rows = await images.db(client, 'GET', f"/image_artworks?business_id=eq.{UUID(str(biz['id']))}"
                    + '&or=(model.not.is.null,prompt.like.EDITABLE_FLYER_V1*)&order=created_at.desc&limit=4')
            cards = [await images.present(client, row) for row in rows]
        if iid:
            state = cards[0].get('status')
            detail = {'ready': 'The saved image is ready.', 'queued': 'The image is queued, not ready yet.',
                      'working': 'The image is still generating.', 'failed': 'The image job failed.'}.get(state, 'The image has an unknown status.')
        else:
            detail = ('This conversation has no confirmed image-job ID, so I cannot claim the requested flyer was generated. '
                      + ('These are the latest saved/generated image records, which may belong to earlier requests.' if cards else 'No generated image records were found.'))
        try:
            approvals = await authority.db('GET', f'/platform_chief_authorizations?owner_id=eq.{UUID(str(owner.id))}'
                + '&status=in.(pending,executing,uncertain)&order=created_at.desc&limit=10')
            pending = [a for a in approvals if (a.get('action') or {}).get('type') in ('generate_image','compose_flyer')]
            if pending:
                detail += ' There are unresolved image requests in Action History; check their approval/status before starting another.'
        except HTTPException:
            detail += ' Approval status could not be loaded.'
        return {'type':'find_images', 'ok':True, 'label':'Verified image status', 'result':detail, 'images':cards, 'business_id':str(biz['id'])}
    except (HTTPException, httpx.HTTPError):
        return {'type':'find_images', 'ok':False, 'label':'Image status could not be verified. No new generation was started.', 'images':[]}


def display_reply(text, results, body, question=None):
    creative = [r for r in results if r.get('type') in CREATIVE or r.get('image') or r.get('project_id') or (r.get('approval') or {}).get('action', {}).get('type') in CREATIVE]
    if creative:
        return result_reply(creative)
    if question:
        return question
    # Fail visibly if an explicit creation turn still yielded only narration.
    if create_requested(body):
        return 'Chief did not return a valid creative command, so no image was submitted. Please retry the creation request.'
    if not results and re.search(r'(?:\b(?:image|flyer|visual|artwork)\s+(?:is|was)\s+(?:ready|generated|generating|queued)|\b(?:requesting|generating|rendering) (?:the|your) (?:image|flyer|visual)|\b(?:you should see|card (?:is|appeared))\b)', text, re.I):
        return 'I cannot verify that an image was submitted or completed from this reply. Ask me to check the image status; no new generation was started.'
    return text

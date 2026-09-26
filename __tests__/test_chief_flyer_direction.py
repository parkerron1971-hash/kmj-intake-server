import asyncio
import base64
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chief_flyer_direction as direction
import chief_flyer_composer as composer
import platform_chief_creative as creative
import image_studio as images
from platform_chief_marketing import ChiefMessageBody, conversation_messages

OWNER = SimpleNamespace(id=str(uuid4()))
BIZ = {'id': str(uuid4()), 'owner_id': OWNER.id}


def run(coro): return asyncio.run(coro)


def raw_image():
    out = io.BytesIO()
    Image.new('RGB', (24, 18), 'red').save(out, 'PNG')
    return out.getvalue()


def attachment(name='reference.png'):
    return {'name': name, 'data_url': 'data:image/png;base64,' + base64.b64encode(raw_image()).decode()}


@pytest.fixture
def owned(monkeypatch):
    monkeypatch.setattr(creative, 'platform_business', AsyncMock(return_value=BIZ))
    monkeypatch.setattr(images, 'business', AsyncMock(return_value=BIZ))
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[]))
    monkeypatch.setattr(images, 'store', AsyncMock())
    monkeypatch.setattr(images, 'artwork', AsyncMock(return_value={'status': 'ready', 'prompt': 'Original brief'}))
    monkeypatch.setattr(images, 'original', AsyncMock(return_value=raw_image()))


def test_chat_labels_match_history_and_current_catalog():
    body = ChiefMessageBody(message='Use the second photo', images=[attachment('new.png')],
        history=[{'role': 'you', 'text': 'Earlier reference', 'images': [attachment('old.png')]}])
    messages = conversation_messages(body)
    assert 'chat:1' in messages[0]['content'][0]['text']
    assert 'chat:2' in messages[1]['content'][0]['text']
    assert [r.name for r in direction.chat_references(body)] == ['old.png', 'new.png']


def test_reference_roles_are_frozen_for_later_approval(owned):
    body = ChiefMessageBody(message='Use this photo', images=[attachment()])
    result = run(direction.prepare_actions([{'type': 'generate_image', 'prompt': 'An editorial flyer',
        'style_key': 'editorial_story', 'reference_inputs': [{'source': 'chat:1', 'role': 'subject', 'use': 'preserve supplied portrait'}]}], body, OWNER))[0]
    assert len(result['reference_ids']) == 1
    assert '"role": "subject"' in result['prompt']
    assert 'preserve supplied portrait' in result['prompt']
    assert 'data:image' not in json.dumps(result)
    assert 'reference_inputs' not in result
    assert images.store.await_count == 1
    metadata = next(call.args[3] for call in images.db.await_args_list if call.args[1] == 'POST')
    assert metadata['owner_id'] == OWNER.id and metadata['business_id'] == BIZ['id']
    assert metadata['cost_usd'] == 0


def test_reference_upload_replay_reuses_private_asset(owned, monkeypatch):
    image = ChiefMessageBody(message='x', images=[attachment()]).images[0]
    first = run(direction.save_chat_reference(None, BIZ, image))
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[{'id': first, 'status': 'ready'}]))
    assert run(direction.save_chat_reference(None, BIZ, image)) == first
    assert images.store.await_count == 1


@pytest.mark.parametrize('source', ['https://localhost/private', 'chat:0', 'chat:2', 'chat:bad', 'artwork:bad'])
def test_invalid_reference_never_uploads(owned, source):
    body = ChiefMessageBody(message='Create', images=[attachment()])
    with pytest.raises(HTTPException):
        run(direction.prepare_actions([{'type': 'generate_image', 'prompt': 'A poster',
            'reference_inputs': [{'source': source}]}], body, OWNER))
    images.store.assert_not_called()


def test_foreign_saved_reference_blocks_before_upload(owned, monkeypatch):
    monkeypatch.setattr(images, 'artwork', AsyncMock(side_effect=HTTPException(404, 'Not found')))
    body = ChiefMessageBody(message='Create', images=[attachment()])
    with pytest.raises(HTTPException):
        run(direction.prepare_actions([{'type': 'generate_image', 'prompt': 'A poster', 'reference_inputs': [
            {'source': 'chat:1'}, {'source': 'artwork:' + str(uuid4())}]}], body, OWNER))
    images.store.assert_not_called()


def test_benchmark_is_style_only_and_never_added_to_an_edit(owned, monkeypatch):
    benchmark = str(uuid4()); target = str(uuid4())
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[{'id': benchmark}]))
    body = ChiefMessageBody(message='Create')
    action = {'type': 'generate_image', 'prompt': 'An original product flyer', 'style_key': 'product_hero'}
    result = run(direction.prepare_actions([action], body, OWNER))[0]
    assert result['reference_ids'] == [benchmark]
    assert '"role": "style"' in result['prompt']
    assert 'do not copy their people, logos, offers, names or text' in result['prompt']
    action['reference_ids'] = [target]
    result = run(direction.prepare_actions([action], body, OWNER))[0]
    assert result['reference_ids'] == [target]
    assert '"role": "edit_target"' in result['prompt']


def test_visual_review_loads_owned_pixels_and_complete_layout(owned, monkeypatch):
    iid = str(uuid4())
    stored = composer.PREFIX + json.dumps({'layers': [], 'note': 'x' * 2200})
    monkeypatch.setattr(images, 'artwork', AsyncMock(return_value={'prompt': stored, 'status': 'ready'}))
    body = ChiefMessageBody(message=f'Review artwork {iid}: do not generate')
    messages = conversation_messages(body)
    run(direction.attach_review(body, OWNER, messages))
    assert messages[-1]['content'][1]['type'] == 'image'
    assert stored in messages[-1]['content'][0]['text']
    images.artwork.assert_awaited_once()
    assert images.artwork.call_args.args[1:] == (BIZ['id'], iid)


def test_review_failure_is_explicit_and_contains_no_pixels(owned, monkeypatch):
    monkeypatch.setattr(images, 'artwork', AsyncMock(side_effect=HTTPException(404, 'Not found')))
    body = ChiefMessageBody(message=f'Review artwork {uuid4()}')
    messages = conversation_messages(body)
    run(direction.attach_review(body, OWNER, messages))
    assert all(block['type'] == 'text' for block in messages[-1]['content'])
    assert 'could not be loaded' in messages[-1]['content'][0]['text']


def test_review_last_flyer_uses_latest_assistant_image_metadata():
    iid = str(uuid4())
    body = ChiefMessageBody(message='Critique the last flyer', history=[{'role': 'chief', 'text': f'Created. [Image references: {iid}: Brief]'}])
    assert direction.review_target(body) == iid
    assert direction.review_target(ChiefMessageBody(message='Create a new flyer', history=body.history)) is None


def layout(**kwargs):
    return composer.Layout.model_validate({'width': 1080, 'height': 1350, 'title': 'Editable test', 'layers': [
        {'kind': 'text', 'x': 50, 'y': 50, 'width': 950, 'font_size': 80, 'text': 'HELLO\nWORLD'}], **kwargs})


def test_composition_escapes_text_and_keeps_images_embedded(owned):
    spec = layout(layers=[{'kind': 'image', 'image_id': str(uuid4()), 'x': 0, 'y': 0, 'width': 1080, 'height': 1350},
        {'kind': 'text', 'x': 40, 'y': 60, 'width': 900, 'font_size': 40, 'text': '<script>alert(1)</script> & "quote"'}])
    svg = run(composer.svg_document(None, BIZ['id'], spec))
    assert '<script>' not in svg and '&lt;script&gt;' in svg
    assert 'href="data:image/png;base64,' in svg
    assert 'id="layer-0"' in svg and 'id="layer-1"' in svg
    assert run(composer.svg_document(None, BIZ['id'], composer.decode_layout({'prompt': composer.encode_layout(spec)}))) == svg


@pytest.mark.parametrize('mutation', [
    {'background': 'url(https://example.com)'}, {'width': 10000},
    {'layers': [{'kind': 'image', 'image_id': 'https://example.com', 'x': 0, 'y': 0, 'width': 100, 'height': 100}]},
    {'layers': [{'kind': 'text', 'text': 'bad', 'x': 0, 'y': 0, 'width': 100, 'font_size': 40, 'font': 'url(remote)'}]},
    {'layers': [{'kind': 'text', 'text': 'bad', 'x': float('nan'), 'y': 0, 'width': 100, 'font_size': 40}]},
])
def test_composition_rejects_remote_content_unbounded_and_nonfinite_values(mutation):
    with pytest.raises(ValidationError): layout(**mutation)


def test_composition_never_reads_foreign_pixels(owned, monkeypatch):
    monkeypatch.setattr(images, 'artwork', AsyncMock(side_effect=HTTPException(404, 'Not found')))
    spec = layout(layers=[{'kind': 'image', 'image_id': str(uuid4()), 'x': 0, 'y': 0, 'width': 100, 'height': 100}])
    with pytest.raises(HTTPException): run(composer.svg_document(None, BIZ['id'], spec))
    images.original.assert_not_called()


def test_composition_chat_source_becomes_owned_reference(owned):
    body = ChiefMessageBody(message='Place this photo', images=[attachment()])
    result = run(composer.prepare_action({'layout': {'width': 1080, 'height': 1350, 'layers': [
        {'kind': 'image', 'image_id': 'chat:1', 'x': 0, 'y': 0, 'width': 1080, 'height': 1350}]}}, body, OWNER))
    assert result['type'] == 'compose_flyer'
    assert not result['layout']['layers'][0]['image_id'].startswith('chat:')


def test_composition_replay_does_not_render_again(owned, monkeypatch):
    spec = layout(); iid = str(uuid4())
    existing = {'id': iid, 'prompt': composer.encode_layout(spec), 'status': 'ready'}
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[existing]))
    monkeypatch.setattr(images, 'present', AsyncMock(side_effect=lambda c, row: row))
    render = AsyncMock(); monkeypatch.setattr(composer, 'render_svg', render)
    result = run(composer.compose(None, BIZ, {'layout': spec.model_dump()}, uuid4()))
    assert result['image']['editable_master'] is True
    render.assert_not_called()
    changed = layout(title='Different')
    with pytest.raises(HTTPException): run(composer.compose(None, BIZ, {'layout': changed.model_dump()}, uuid4()))


def test_master_download_is_owner_gated():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import platform_console
    from auth_supabase import require_user
    app = FastAPI(); app.include_router(platform_console.router)
    client = TestClient(app)
    path = f'/platform/chief/flyers/{uuid4()}/master'
    assert client.get(path).status_code in (401, 403)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=str(uuid4()), email='someone@example.com')
    assert client.get(path).status_code == 403


def test_suggestions_do_not_upload_chat_references(owned):
    body = ChiefMessageBody(message='Compare these only', images=[attachment()])
    assert run(direction.prepare_actions([], body, OWNER)) == []
    images.store.assert_not_called()
    images.db.assert_not_called()


def test_compose_saves_owned_preview_and_download_reconstructs_master(owned, monkeypatch):
    spec = layout()
    saved = []
    async def db(client, method, path, body=None, **kwargs):
        if method == 'GET': return []
        saved.append(body)
        return [body]
    monkeypatch.setattr(images, 'db', db)
    monkeypatch.setattr(images, 'present', AsyncMock(side_effect=lambda c, row: row))
    monkeypatch.setattr(composer, 'render_svg', AsyncMock(return_value=raw_image()))
    result = run(composer.compose(None, BIZ, {'layout': spec.model_dump()}, uuid4()))
    assert result['image']['status'] == 'ready' and result['image']['editable_master']
    assert saved[0]['owner_id'] == OWNER.id
    assert saved[0]['prompt'].startswith(composer.PREFIX)
    monkeypatch.setattr(images, 'artwork', AsyncMock(return_value=saved[0]))
    response = run(composer.export_master(BIZ['id'], result['image']['id']))
    assert response.media_type == 'image/svg+xml'
    assert response.headers['content-disposition'].startswith('attachment;')
    assert 'sandbox' in response.headers['content-security-policy']
    assert b'<text ' in response.body and b'HELLO' in response.body


def test_multiple_asset_proposals_fail_before_private_uploads(owned):
    body = ChiefMessageBody(message='Create', images=[attachment()])
    action = {'type': 'generate_image', 'prompt': 'A flyer', 'reference_inputs': [{'source': 'chat:1'}]}
    with pytest.raises(HTTPException): run(direction.prepare_actions([action, action], body, OWNER))
    images.store.assert_not_called()

import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

import image_studio as studio


def test_business_owner_is_checked_even_if_rls_returns_another_owner():
    biz = uuid4()
    with patch.object(studio, 'db', new_callable=AsyncMock, return_value=[{'id': str(biz), 'owner_id': 'another-owner'}]), \
         patch.object(studio, 'token', return_value='user-jwt'), \
         patch.object(studio, 'require_user', return_value=SimpleNamespace(id='current-user')):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(studio.business(None, biz))
        assert exc.value.status_code == 403


def test_missing_signed_url_returns_recoverable_error():
    client = AsyncMock()
    client.post.return_value.is_success = True
    client.post.return_value.json = lambda: {}
    with patch.object(studio, 'token', return_value='user-jwt'), patch.dict(studio.os.environ, {'SUPABASE_URL': 'https://example.supabase.co'}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(studio.present(client, {'status': 'ready', 'storage_path': 'business/original.png'}))
        assert exc.value.status_code == 502


def test_publishing_partial_success_is_not_reported_as_complete():
    assert studio.publication_status({'ok': True, 'facebook_url': 'https://example.test/post'}) == 'published'
    assert studio.publication_status({'ok': False, 'facebook_url': 'https://example.test/post', 'result': 'IG failed'}) == 'partial'
    assert studio.publication_status({'ok': False, 'result': 'Connection failed'}) == 'failed'
    assert studio.publication_status({'failed': True}) == 'failed'


def test_invalid_models_and_references_are_rejected():
    base = dict(business_id=uuid4(), request_id=uuid4(), prompt='A business flyer')
    for invalid in ({'model': 'unreviewed'}, {'quality': 'free'}, {'size': '99999x99999'}, {'reference_ids': [uuid4() for _ in range(5)]}):
        with pytest.raises(ValidationError):
            studio.CreateImage(**base, **invalid)


def test_image_file_contents_are_validated_not_extension():
    with pytest.raises(HTTPException) as exc:
        studio.normalize_image(b'<script>not an image</script>')
    assert exc.value.status_code == 422
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), 'blue').save(buffer, 'JPEG')
    assert studio.normalize_image(buffer.getvalue()).startswith(b'\x89PNG')


def test_cost_uses_image_and_text_modalities_and_cache():
    usage = {'input_tokens_details': {'text_tokens': 1000, 'image_tokens': 2000,
        'cached_tokens_details': {'text_tokens': 400, 'image_tokens': 500}}, 'output_tokens': 3000}
    assert studio.image_cost(usage) == pytest.approx(.1065)
    assert studio.image_cost({'input_tokens': 3000}) is None


def test_no_service_role_fallback():
    with patch.object(studio.sb_clients, 'get_current_user_jwt', return_value=None):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(studio.db(None, 'GET', '/image_artworks'))
        assert exc.value.status_code == 401


def test_reference_is_always_scoped_to_business():
    biz, asset = uuid4(), uuid4()
    with patch.object(studio, 'db', new_callable=AsyncMock, return_value=[]) as db:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(studio.artwork(None, biz, asset))
        assert exc.value.status_code == 404
        assert f'business_id=eq.{biz}' in db.call_args.args[2]


def test_unready_reference_never_hits_provider():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(studio.original(None, {'status': 'working'}))
    assert exc.value.status_code == 409


def test_worker_does_not_repeat_claimed_generation():
    with patch.object(studio, 'db', new_callable=AsyncMock, return_value=[]) as db:
        asyncio.run(studio.generate_worker({'id': str(uuid4())}))
        assert db.await_count == 1
        assert '&status=eq.queued' in db.call_args.args[2]


def test_private_preview_signs_url_and_hides_storage_path():
    row = {'id': str(uuid4()), 'status': 'ready', 'owner_id': 'private-owner', 'storage_path': 'business/original.png'}
    client = AsyncMock()
    client.post.return_value.is_success = True
    client.post.return_value.json = lambda: {'signedURL': '/object/sign/image-originals/business/original.png?token=temporary'}
    with patch.object(studio, 'token', return_value='user-jwt'), patch.dict(studio.os.environ, {'SUPABASE_URL': 'https://example.supabase.co'}):
        result = asyncio.run(studio.present(client, row))
    assert result['url'].startswith('https://example.supabase.co/storage/v1/object/sign/')
    assert '/public/' not in result['url']
    assert 'owner_id' not in result and 'storage_path' not in result


def test_completed_request_is_not_regenerated():
    req = studio.CreateImage(business_id=uuid4(), request_id=uuid4(), prompt='A blue flyer')
    row = {'id': str(req.request_id), 'business_id': str(req.business_id), 'prompt': req.prompt,
        'model': req.model, 'quality': req.quality, 'size': req.size, 'reference_ids': [], 'status': 'ready'}
    with patch.object(studio, 'business', new_callable=AsyncMock, return_value={'id': str(req.business_id)}), \
         patch.object(studio, 'db', new_callable=AsyncMock, return_value=[row]), \
         patch.object(studio, 'present', new_callable=AsyncMock, return_value=row), \
         patch('billing_limits.require_units'), patch.dict(studio.os.environ, {'OPENAI_API_KEY': 'test-only-placeholder'}), \
         patch.object(studio.asyncio, 'create_task') as create_task:
        assert asyncio.run(studio.create(req, None)) == row
        create_task.assert_not_called()


def test_retry_id_cannot_be_repurposed_for_another_prompt():
    req = studio.CreateImage(business_id=uuid4(), request_id=uuid4(), prompt='A blue flyer')
    with patch.object(studio, 'business', new_callable=AsyncMock), \
         patch.object(studio, 'db', new_callable=AsyncMock, return_value=[{'business_id': str(req.business_id), 'prompt': 'different'}]), \
         patch('billing_limits.require_units'), patch.dict(studio.os.environ, {'OPENAI_API_KEY': 'test-only-placeholder'}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(studio.create(req, None))
        assert exc.value.status_code == 409


def test_stream_fallback_reuses_image_even_if_llm_rewords_prompt():
    biz = {'id': str(uuid4())}
    row = {'id': str(uuid4()), 'status': 'working'}
    paths = []
    async def run(prompt):
        t = studio.turn_id.set('same-transport-request')
        index = studio.turn_image_index.set(0)
        try:
            with patch.object(studio, 'db', new_callable=AsyncMock, return_value=[row]) as db, \
                 patch.object(studio, 'present', new_callable=AsyncMock, return_value=row), \
                 patch.object(studio, 'create', new_callable=AsyncMock) as create:
                result = await studio.handle_generate_image(None, biz, {'prompt': prompt})
                paths.append(db.call_args.args[2])
                create.assert_not_called()
                assert result['image'] == row
        finally:
            studio.turn_id.reset(t); studio.turn_image_index.reset(index)
    asyncio.run(run('A navy salon flyer'))
    asyncio.run(run('An editorial salon promotion in navy blue'))
    assert paths[0] == paths[1]

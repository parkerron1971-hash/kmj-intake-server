import asyncio
import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import httpx
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

import image_studio as studio


def test_configured_model_controls_new_requests_and_quality_choices():
    with patch.dict(studio.os.environ, {'OPENAI_IMAGE_MODEL': 'gpt-image-2'}):
        req = studio.CreateImage(business_id=uuid4(), request_id=uuid4(), prompt='A promotional image')
        assert req.model == 'gpt-image-2'
        config = asyncio.run(studio.config())
        assert config['model'] == 'gpt-image-2'
        assert tuple(config['credits']) == ('low', 'medium', 'high')
        assert 'max' not in config['qualities']
    with patch.dict(studio.os.environ, {'OPENAI_IMAGE_MODEL': 'unreviewed'}):
        with pytest.raises(HTTPException):
            studio.configured_model()


@pytest.mark.parametrize('model', studio.MODELS)
@pytest.mark.parametrize('editing', [False, True])
def test_catalog_404_does_not_block_generation_or_reference_edit(model, editing):
    req = studio.CreateImage(business_id=uuid4(), request_id=uuid4(),
        prompt='Add 90-Day Intensive beneath 50% OFF. Keep the same layout.',
        model=model, size='1536x1024', reference_ids=[uuid4()] if editing else [])
    row = {'id': str(req.request_id), 'business_id': str(req.business_id),
        'prompt': req.prompt, 'model': model, 'quality': req.quality, 'size': req.size,
        'reference_ids': [str(ref) for ref in req.reference_ids], 'status': 'queued'}
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), 'blue').save(buffer, 'PNG')
    raw = buffer.getvalue()
    requests = []

    def provider(request):
        requests.append(request)
        if request.method == 'GET':
            return httpx.Response(404, json={'error': {'code': 'model_not_found'}})
        return httpx.Response(200, headers={'x-request-id': 'test-generation-receipt'},
            json={'data': [{'b64_json': base64.b64encode(raw).decode()}],
                  'usage': {'input_tokens': 15, 'output_tokens': 196,
                            'input_tokens_details': {'text_tokens': 15, 'image_tokens': 0}}})

    async def database(client, method, path, payload=None, **kwargs):
        if method == 'GET':
            return []
        if method == 'PATCH':
            row.update(payload)
        return [dict(row)]

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
        with patch.object(studio.httpx, 'AsyncClient', return_value=client), \
             patch.object(studio, 'business', new_callable=AsyncMock), \
             patch.object(studio, 'db', side_effect=database), \
             patch.object(studio, 'artwork', new_callable=AsyncMock, return_value={'status': 'ready'}), \
             patch.object(studio, 'original', new_callable=AsyncMock, return_value=raw) as original, \
             patch.object(studio, 'store', new_callable=AsyncMock) as store, \
             patch.object(studio, 'present', new_callable=AsyncMock, side_effect=lambda c, r: r), \
             patch.object(studio, 'log_api_usage', new_callable=AsyncMock) as meter, \
             patch('billing_limits.require_units') as budget, \
             patch.dict(studio.os.environ, {'OPENAI_API_KEY': 'test-only-placeholder'}):
            await studio.create(req, client)
            await asyncio.gather(*list(studio._tasks))
            budget.assert_called_once_with(str(req.business_id))
            store.assert_awaited_once()
            assert original.await_count == int(editing)
            meter.assert_awaited_once()
            assert meter.call_args.kwargs['units'] == studio.image_units('high')
            assert meter.call_args.kwargs['cost_cents_override'] == pytest.approx(.5955)
            assert meter.call_args.kwargs['ok'] is True

    asyncio.run(run())
    assert row['status'] == 'ready'
    assert row['size'] == '1536x1024'
    assert len(requests) == 1
    assert requests[0].url.path == ('/v1/images/edits' if editing else '/v1/images/generations')
    assert b'1536x1024' in requests[0].content
    assert model.encode() in requests[0].content
    if editing:
        assert b'name="image[]"' in requests[0].content


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
def test_actual_provider_denial_fails_job_without_credits_or_retry(status, caplog):
    row = {'id': str(uuid4()), 'business_id': str(uuid4()), 'model': studio.MODELS[0],
           'prompt': 'A business flyer', 'quality': 'high', 'size': '1536x1024', 'reference_ids': []}
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(status, headers={'x-request-id': 'test-denial-receipt'},
            json={'error': {'code': 'model_not_found' if status == 404 else 'provider_error'}})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
        with patch.object(studio.httpx, 'AsyncClient', return_value=client), \
             patch.object(studio, 'db', new_callable=AsyncMock, return_value=[row]) as db, \
             patch.object(studio, 'store', new_callable=AsyncMock) as store, \
             patch.object(studio, 'log_api_usage', new_callable=AsyncMock) as meter:
            await studio.generate_worker(row)
            store.assert_not_called()
            meter.assert_not_called()
            failure = db.call_args.args[3]
            assert failure['status'] == 'failed'
            if status in (403, 404):
                assert 'GPT Image 2.5 Sunburst' in failure['error']
            elif status == 401:
                assert 'API key' in failure['error']
    asyncio.run(run())
    assert len(calls) == 1
    assert 'test-denial-receipt' in caplog.text


@pytest.mark.parametrize('failure_at', ['usage_save', 'storage', 'ready_save'])
def test_paid_generation_save_failure_records_cost_without_customer_credits(failure_at):
    row = {'id': str(uuid4()), 'business_id': str(uuid4()), 'model': studio.MODELS[0],
           'prompt': 'A business flyer', 'quality': 'high', 'size': '1536x1024', 'reference_ids': []}
    writes = []

    async def database(client, method, path, payload, **kwargs):
        writes.append(payload)
        if (failure_at == 'usage_save' and 'usage' in payload or
                failure_at == 'ready_save' and payload.get('status') == 'ready'):
            raise HTTPException(502, 'Save unavailable')
        return [row]

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json={'data': [{'b64_json': base64.b64encode(b'normalized-test-image').decode()}],
                  'usage': {'input_tokens': 15, 'output_tokens': 196,
                            'input_tokens_details': {'text_tokens': 15, 'image_tokens': 0}}})))
        with patch.object(studio.httpx, 'AsyncClient', return_value=client), \
             patch.object(studio, 'db', side_effect=database), \
             patch.object(studio, 'normalize_image', side_effect=lambda raw: raw), \
             patch.object(studio, 'store', new_callable=AsyncMock,
                          side_effect=HTTPException(502, 'Save unavailable') if failure_at == 'storage' else None), \
             patch.object(studio, 'log_api_usage', new_callable=AsyncMock) as meter:
            await studio.generate_worker(row)
            meter.assert_awaited_once()
            assert meter.call_args.kwargs['cost_cents_override'] == pytest.approx(.5955)
            assert meter.call_args.kwargs['units'] == 0
            assert meter.call_args.kwargs['ok'] is False
    asyncio.run(run())
    assert writes[-1]['status'] == 'failed'


def test_unsupported_quality_does_not_silently_downgrade_or_reserve():
    req = studio.CreateImage(business_id=uuid4(), request_id=uuid4(), prompt='A promotional image', model='gpt-image-2', quality='max')
    with patch.object(studio, 'business', new_callable=AsyncMock), \
         patch.object(studio, 'db', new_callable=AsyncMock) as db, \
         patch.dict(studio.os.environ, {'OPENAI_API_KEY': 'test-only-placeholder'}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(studio.create(req, None))
        assert exc.value.status_code == 422
        db.assert_not_called()


def test_invalid_credentials_are_distinct_from_model_access():
    error = studio.provider_error(httpx.Response(401, json={'error': {'code': 'invalid_api_key'}}), 'gpt-image-2')
    assert 'API key' in error.detail
    assert 'not available' not in error.detail


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

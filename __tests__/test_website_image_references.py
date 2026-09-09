import asyncio
import io
import socket
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image

import image_studio as studio
import website_image_references as capture


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://localhost', 'http://127.0.0.1',
    'http://169.254.169.254', 'http://[::1]', 'https://test.internal', 'https://u:p@example.com',
    'https://example.com:8000', 'https://example.com:bad', 'https://example.com\\@localhost', ''])
def test_public_url_rejects_local_credentials_and_bad_ports(url):
    with pytest.raises(ValueError):
        capture.public_url(url)


def test_public_url_retains_target_section_and_normalizes_domain():
    assert capture.public_url('EXAMPLE.com/services#coaching') == 'https://example.com/services#coaching'


@pytest.mark.parametrize('blocked', ['10.0.0.1', '169.254.169.254', '224.0.0.1', '::1', 'ff02::1'])
def test_dns_rejects_mixed_public_private_results(blocked):
    async def run():
        loop = asyncio.get_running_loop()
        values = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
                  (socket.AF_INET, socket.SOCK_STREAM, 6, '', (blocked, 443))]
        with patch.object(loop, 'getaddrinfo', new_callable=AsyncMock, return_value=values):
            with pytest.raises(ValueError):
                await capture.public_addresses('example.com', 443)
    asyncio.run(run())


def test_fetch_pins_checked_address_and_does_not_send_cookies():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={'content-type': 'image/png', 'set-cookie': 'private=secret'}, content=b'image')
    async def run():
        fetcher = capture.PublicFetcher()
        await fetcher.client.aclose()
        fetcher.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(capture, 'public_addresses', new_callable=AsyncMock, return_value=['8.8.8.8']):
            await fetcher.one('https://example.com/logo.png')
            await fetcher.one('https://different.example/logo.png')
        await fetcher.close()
    asyncio.run(run())
    assert all(str(r.url).startswith('https://8.8.8.8/') for r in requests)
    assert requests[0].headers['host'] == 'example.com'
    assert requests[0].extensions['sni_hostname'] == 'example.com'
    assert requests[1].headers['cookie'] == ''


def test_logo_redirect_is_checked_and_size_budget_enforced():
    async def run():
        fetcher = capture.PublicFetcher()
        await fetcher.client.aclose()
        fetcher.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r:
            httpx.Response(302, headers={'location': 'http://127.0.0.1/admin'})))
        with patch.object(capture, 'public_addresses', new_callable=AsyncMock, return_value=['8.8.8.8']):
            with pytest.raises(ValueError):
                await fetcher.image('https://example.com/logo')
        await fetcher.client.aclose()
        fetcher.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'123456')))
        with patch.object(capture, 'MAX_RESOURCE', 4), patch.object(capture, 'public_addresses', new_callable=AsyncMock, return_value=['8.8.8.8']):
            with pytest.raises(ValueError):
                await fetcher.one('https://example.com/large')
        await fetcher.close()
    asyncio.run(run())


def test_capture_checks_owner_before_network_or_storage():
    with patch.object(studio, 'business', new_callable=AsyncMock, side_effect=HTTPException(403)), \
         patch.object(capture, 'capture_website', new_callable=AsyncMock) as browser, \
         patch.object(studio, 'store', new_callable=AsyncMock) as store:
        with pytest.raises(HTTPException):
            asyncio.run(studio.handle_capture_website_references(None, {'id': str(uuid4())}, {'url': 'https://example.com'}))
        browser.assert_not_called()
        store.assert_not_called()


def test_capture_saves_private_assets_and_reuses_same_turn():
    biz = {'id': str(uuid4()), 'owner_id': str(uuid4())}
    out = io.BytesIO()
    Image.new('RGBA', (100, 50), 'gold').save(out, 'PNG')
    rows = {}
    async def db(client, method, path, body=None, **kwargs):
        if method == 'POST':
            rows[body['id']] = body
            return [body]
        return [row for key, row in rows.items() if f'id=eq.{key}&' in path]
    async def run():
        token = studio.turn_id.set('same-turn')
        refs = studio.turn_references.set(())
        try:
            with patch.object(studio, 'business', new_callable=AsyncMock, return_value=biz), \
                 patch.object(studio, 'db', side_effect=db), \
                 patch.object(studio, 'store', new_callable=AsyncMock) as store, \
                 patch.object(studio, 'present', new_callable=AsyncMock, side_effect=lambda c, r: r), \
                 patch.object(capture, 'capture_website', new_callable=AsyncMock, return_value={
                     'assets': [{'role': role, 'raw': out.getvalue()} for role in ('website screenshot', 'website logo')], 'warning': ''}) as browser:
                first = await studio.handle_capture_website_references(None, biz, {'url': 'https://example.com'})
                second = await studio.handle_capture_website_references(None, biz, {'url': 'https://example.com'})
                assert [i['id'] for i in first['images']] == [i['id'] for i in second['images']]
                assert len(studio.turn_references.get()) == 2
                assert all(row['owner_id'] == biz['owner_id'] and row['cost_usd'] == 0 for row in rows.values())
                assert all(call.args[1].startswith(biz['id'] + '/') for call in store.call_args_list)
                assert store.await_count == 2
                browser.assert_awaited_once()
        finally:
            studio.turn_id.reset(token)
            studio.turn_references.reset(refs)
    asyncio.run(run())


def test_generation_combines_attached_inspiration_and_website_assets():
    biz = {'id': str(uuid4())}
    inspiration, screenshot, logo = [str(uuid4()) for _ in range(3)]
    async def run():
        refs = studio.turn_references.set((inspiration,))
        index = studio.turn_image_index.set(0)
        try:
            with patch.object(studio, 'db', new_callable=AsyncMock, return_value=[]), \
                 patch.object(studio, 'handle_capture_website_references', new_callable=AsyncMock, return_value={
                     'images': [{'id': screenshot, 'prompt': 'Website screenshot'}, {'id': logo, 'prompt': 'Website logo'}]}) as browser, \
                 patch.object(studio, 'create', new_callable=AsyncMock, return_value={'status': 'queued'}) as create:
                await studio.handle_generate_image(None, biz, {'prompt': 'Make this ad', 'website_url': 'https://example.com', 'size': '1536x1024'})
                req = create.call_args.args[0]
                assert [str(i) for i in req.reference_ids] == [inspiration, screenshot, logo]
                assert req.size == '1536x1024'
                assert 'Website screenshot' in req.prompt
                browser.assert_awaited_once()
        finally:
            studio.turn_references.reset(refs)
            studio.turn_image_index.reset(index)
    asyncio.run(run())


def test_missing_logo_blocks_paid_generation_with_clear_error():
    with patch.object(studio, 'db', new_callable=AsyncMock, return_value=[]), \
         patch.object(studio, 'handle_capture_website_references', new_callable=AsyncMock, return_value={'images': [], 'warning': 'No logo found.'}), \
         patch.object(studio, 'create', new_callable=AsyncMock) as create:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(studio.handle_generate_image(None, {'id': str(uuid4())}, {'prompt': 'Make an ad', 'website_url': 'https://example.com'}))
        assert 'No logo' in exc.value.detail
        create.assert_not_called()

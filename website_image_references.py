"""Capture public website references in an isolated browser, without account cookies.

All browser HTTP traffic is fulfilled by a size-limited, DNS-pinned fetcher.
Neither page scripts nor redirects can connect to private services or read server keys.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

MAX_RESOURCE = 8 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_REQUESTS = 100
VIEWPORT = {'width': 1600, 'height': 1100}


def public_url(value: str) -> str:
    value = str(value or '').strip()
    if '://' not in value:
        value = 'https://' + value
    try:
        p = urlsplit(value)
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
                or p.port not in (None, 80, 443) or len(value) > 2048
                or any(ord(c) < 33 for c in value) or '\\' in value):
            raise ValueError()
        host = p.hostname.encode('idna').decode('ascii').lower()
        if '.' not in host or host.endswith(('.local', '.internal', '.localhost')):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        return urlunsplit((p.scheme, host + (f':{p.port}' if p.port else ''), p.path or '/', p.query, p.fragment))
    except (ValueError, UnicodeError):
        raise ValueError('Use a public http or https website address, without login details.') from None


async def public_addresses(host, port):
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses or any(not ipaddress.ip_address(addr).is_global
            or ipaddress.ip_address(addr).is_multicast or ipaddress.ip_address(addr).is_reserved
            for addr in addresses):
        raise ValueError('Private or reserved network addresses cannot be captured.')
    return addresses


class PublicFetcher:
    def __init__(self):
        self.requests = 0
        self.total = 0
        self.slots = asyncio.Semaphore(8)
        self.client = httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False)

    async def close(self):
        await self.client.aclose()

    async def one(self, value):
        url = public_url(value)
        self.requests += 1
        if self.requests > MAX_REQUESTS or self.total >= MAX_TOTAL:
            raise ValueError('Website capture exceeded its resource budget.')
        p = urlsplit(url)
        async with self.slots:
            addresses = await asyncio.wait_for(public_addresses(p.hostname, p.port or (443 if p.scheme == 'https' else 80)), 5)
            address = addresses[0]
            authority = f'[{address}]' if ':' in address else address
            pinned = urlunsplit((p.scheme, authority + (f':{p.port}' if p.port else ''), p.path, p.query, ''))
            # Connect to the checked IP, retaining hostname TLS verification and HTTP routing.
            async with self.client.stream('GET', pinned,
                    # Do not reuse an IP-keyed TLS connection for a different hostname.
                    headers={'Host': p.netloc, 'Cookie': '', 'Connection': 'close',
                             'User-Agent': 'Mozilla/5.0 SolutionistWebsiteCapture/1.0'},
                    extensions={'sni_hostname': p.hostname}) as response:
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    self.total += len(chunk)
                    if len(data) + len(chunk) > MAX_RESOURCE or self.total > MAX_TOTAL:
                        raise ValueError('Website resource is too large.')
                    data.extend(chunk)
                headers = {'content-type': response.headers.get('content-type', 'application/octet-stream')}
                if response.is_redirect:
                    headers['location'] = public_url(urljoin(url, response.headers.get('location', '')))
                return response.status_code, headers, bytes(data)

    async def image(self, url):
        for _ in range(5):
            status, headers, raw = await self.one(url)
            if 300 <= status < 400 and headers.get('location'):
                url = headers['location']
                continue
            if status != 200 or not headers['content-type'].startswith('image/'):
                raise ValueError('Website logo could not be downloaded.')
            return raw
        raise ValueError('Too many logo redirects.')


async def capture_website(url: str, *, include_logo=True):
    """One desktop viewport and the best visible logo; no AI/provider generation."""
    from playwright.async_api import async_playwright
    from image_studio import normalize_image

    url = public_url(url)
    fetcher = PublicFetcher()
    try:
        async with asyncio.timeout(45), async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                context = await browser.new_context(viewport=VIEWPORT, device_scale_factor=1,
                    accept_downloads=False, service_workers='block')
                # Keep page code on the intercepted HTTP surface; no peer/UDP transports
                # or worker globals that could open a second, unguarded network path.
                await context.add_init_script('''for (const name of [
                    'RTCPeerConnection', 'webkitRTCPeerConnection', 'WebTransport',
                    'Worker', 'SharedWorker', 'WebSocket']) {
                    Object.defineProperty(globalThis, name, {value: undefined, configurable: false, writable: false});
                }''')
                async def route_request(route):
                    request = route.request
                    if request.method != 'GET' or request.resource_type not in ('document', 'stylesheet', 'image', 'font', 'script'):
                        return await route.abort()
                    try:
                        status, headers, raw = await fetcher.one(request.url)
                        await route.fulfill(status=status, headers=headers, body=raw)
                    except (ValueError, OSError, httpx.HTTPError, TimeoutError):
                        await route.abort()
                await context.route('**/*', route_request)
                await context.route_web_socket('**/*', lambda ws: ws.close())
                page = await context.new_page()
                context.on('page', lambda other: asyncio.create_task(other.close()) if other != page else None)
                response = await page.goto(url, wait_until='domcontentloaded', timeout=25000)
                if not response or response.status >= 400:
                    raise ValueError('The public website could not be opened.')
                # Fonts and entrance animations settle before the viewport is photographed.
                await page.evaluate('() => Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 2500))])')
                await page.wait_for_timeout(1800)
                if await page.locator('input[type=password]').count():
                    raise ValueError('This page requires a login. Use a public page instead.')
                if not (await page.locator('body').inner_text()).strip():
                    raise ValueError('This page did not expose visible content for a screenshot.')
                screenshot = await page.screenshot(type='png', animations='disabled')
                assets = [{'role': 'website screenshot', 'raw': screenshot}]
                if include_logo:
                    candidates = await page.locator('img').evaluate_all('''images => images.map((img, index) => {
                        const box = img.getBoundingClientRect();
                        const hint = [img.alt, img.currentSrc, img.className, img.parentElement?.className].join(' ');
                        const branded = /logo|brand|wordmark/i.test(hint);
                        const nav = !!img.closest('header, nav, [role=banner], .nav-logo');
                        return {index, url: img.currentSrc, score: (branded ? 10 : 0) + (nav ? 5 : 0),
                            visible: box.width > 20 && box.height > 10 && img.complete && img.naturalWidth > 0};
                    }).filter(x => x.visible && x.score >= 5).sort((a,b) => b.score-a.score).slice(0,3)''')
                    for candidate in candidates:
                        try:
                            raw = normalize_image(await fetcher.image(candidate['url']))
                        except Exception:
                            # A rendered SVG/data logo is still the real site mark, not an invented replacement.
                            try:
                                raw = await page.locator('img').nth(candidate['index']).screenshot(type='png', animations='disabled', timeout=3000)
                            except Exception:
                                continue
                        assets.append({'role': 'website logo', 'raw': raw})
                        break
                return {'url': page.url, 'assets': assets,
                    'warning': 'No identifiable website logo was found. Supply a logo or choose a page that displays it.' if include_logo and len(assets) == 1 else ''}
            finally:
                await browser.close()
    finally:
        await fetcher.close()

"""Server executor for Anthropic's browser_toolset_20260801 (arc PR2).

One controller belongs to one job thread. HTTP handlers must send a mailbox
command to that thread; Playwright objects must never cross event loops.
No routes or model calls are enabled by this module. The caller supplies a
per-action authority check and a Secure Entry hold callback.
"""
from __future__ import annotations

import base64
import io
import ipaddress
import json
import os
import re
import socket
import time
from typing import Callable, Protocol
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID, uuid4

from PIL import Image

from browser_hand import forbidden_field, VIEWPORT, JPEG_QUALITY
from secret_vault import normalize_host

TOOLSET = 'browser_toolset_20260801'
OPTIONAL = {'javascript_exec', 'file_upload', 'read_console', 'read_network'}
TAB_TOOLS = {'new_tab', 'list_tabs', 'switch_tab', 'close_tab'}
TOOLS = TAB_TOOLS | {
    'navigate', 'screenshot', 'zoom', 'left_click', 'right_click', 'middle_click',
    'double_click', 'triple_click', 'hover', 'left_click_drag', 'left_mouse_down',
    'left_mouse_up', 'mouse_move', 'scroll', 'scroll_to', 'type', 'key', 'hold_key',
    'wait', 'read_page', 'find', 'get_page_text', 'form_input',
}
NOT_EXECUTED = 'Not executed: an earlier action in this turn failed.'
NAVY = '#10243A'


class BrowserStopped(Exception):
    """A fixed message only: never include a page, model argument or secret."""


def tool_config() -> dict:
    return {'type': TOOLSET, 'configs': {
        name: {'enabled': False} for name in sorted(OPTIONAL)}}


def host_allowed(url: str, hosts: list[str], deny_hosts: list[str] = ()) -> bool:
    """Exact HTTPS origins on standard port; deny descendants cannot be waived."""
    try:
        u = urlsplit(url)
        h = normalize_host(u.hostname or '')
        denied = ['amazon.com', *deny_hosts]
        return (u.scheme == 'https' and not u.username and not u.password
                and u.port in (None, 443) and h in hosts
                and not any(h == d or h.endswith('.' + d) for d in denied)
                and not re.search(r'[\x00-\x20\\]', url))
    except Exception:
        return False


class SecretScrubber:
    """Per-run known values. Never serialize, log or include this object in events."""
    def __init__(self):
        self._values: set[str] = set()
        self._digit_patterns: set[str] = set()

    def remember(self, fields: dict[str, str]):
        for value in fields.values():
            if not isinstance(value, str) or not value:
                continue
            self._values.update((value, quote(value, safe=''), json.dumps(value)[1:-1]))
        number = fields.get('number')
        if number:
            digits = re.sub(r'\D', '', number)
            self._values.update((digits, digits[-4:]))
            self._digit_patterns.update(r'[\s-]*'.join(re.escape(d) for d in value)
                                        for value in (digits, digits[-4:]) if value)

    def text(self, text: str) -> str:
        out = str(text)
        for value in sorted(self._values, key=len, reverse=True):
            out = out.replace(value, '[redacted]')
        for pattern in self._digit_patterns:
            out = re.sub(pattern, '[redacted]', out)
        return re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', out)

    def url(self, url: str) -> str:
        if url == 'about:blank':
            return url
        try:
            u = urlsplit(url)
            # No query, fragment or userinfo in any browser-state/event surface.
            return self.text(urlunsplit((u.scheme, u.hostname or '', unquote(u.path), '', '')))[:4096]
        except Exception:
            return ''


class BrowserBackend(Protocol):
    def open(self): ...
    def page(self): ...
    def live_view_url(self) -> str | None: ...
    def close(self): ...


class ChromiumBackend:
    """Fresh, restricted context. DNS pinned at launch; every request checked.

    Third-party payment/CDN hosts must be explicitly included in the approved
    host set. A newly encountered origin requires a new plan, not automatic trust.
    Browser child processes receive only OS/locale variables, never server keys.
    """
    def __init__(self, hosts: list[str], deny_hosts: list[str] = ()):
        self.hosts = [normalize_host(h) for h in hosts]
        self.deny_hosts = [normalize_host(h) for h in deny_hosts]
        self.context = self.browser = self.runtime = None
        self.blocked = False

    def _rules(self) -> str:
        rules = []
        for h in self.hosts:
            if not host_allowed('https://' + h, self.hosts, self.deny_hosts):
                raise BrowserStopped('The supplier host is blocked.')
            ips = {item[4][0] for item in socket.getaddrinfo(h, 443, type=socket.SOCK_STREAM)}
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise BrowserStopped('The supplier address is not public.')
            # Prefer IPv4; Chromium resolver MAP accepts bracketed IPv6 literals.
            ip = sorted(ips, key=lambda x: ':' in x)[0]
            rules.append(f'MAP {h} {"[" + ip + "]" if ":" in ip else ip}')
        return ', '.join([*rules, 'MAP * ~NOTFOUND'])

    def open(self):
        from playwright.sync_api import sync_playwright
        rules = self._rules()
        self.runtime = sync_playwright().start()
        try:
            env = {k: v for k, v in os.environ.items() if k.upper() in {
                'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME', 'LANG', 'LC_ALL'}}
            self.browser = self.runtime.chromium.launch(headless=True, env=env, args=[
                '--host-resolver-rules=' + rules, '--disable-quic', '--no-proxy-server',
                '--disable-background-networking', '--disable-features=DnsOverHttps',
                '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
            ])
            self.context = self.browser.new_context(
                viewport=VIEWPORT, accept_downloads=False, service_workers='block')
            self.context.set_default_timeout(5000)
            self.context.set_default_navigation_timeout(15000)
            self.context.route('**/*', self._route)
            self.context.route_web_socket('**/*', lambda ws: ws.close())
            self.context.on('page', self._page_created)
            return self.context
        except Exception:
            self.close()
            raise BrowserStopped('The browser could not start.') from None

    def _route(self, route):
        if not host_allowed(route.request.url, self.hosts, self.deny_hosts):
            self.blocked = True
            route.abort('blockedbyclient')
        else:
            route.continue_()

    def _page_created(self, page):
        page.on('download', lambda download: download.cancel())
        page.on('filechooser', lambda chooser: chooser.set_files([]))
        page.on('dialog', lambda dialog: dialog.dismiss())
        # Model new_tab is the only supported way to create a tab. Popups are
        # closed before they can become another model-controlled surface.
        if page.opener() is not None or len(self.context.pages) > 3:
            page.close()

    def page(self):
        return self.context.new_page()

    def live_view_url(self):
        return None

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.runtime:
                self.runtime.stop()
            self.context = self.browser = self.runtime = None


def store_frame(business_id: str, errand_id: str, n: int, jpeg: bytes) -> str:
    """Upload already-masked pixels. Storage errors contain no response body."""
    import httpx
    from storage_links import service_headers
    bid, eid = str(UUID(business_id)), str(UUID(errand_id))
    if type(n) is not int or n < 1:
        raise ValueError('Invalid frame sequence.')
    path = f'{bid}/errand/{eid}/{n:03d}.jpg'
    try:
        response = httpx.post(
            os.environ['SUPABASE_URL'].rstrip('/') + '/storage/v1/object/proposals/' + path,
            headers={**service_headers(), 'Content-Type': 'image/jpeg', 'x-upsert': 'false'},
            content=jpeg, timeout=20)
        if response.status_code not in (200, 201):
            raise BrowserStopped('The private frame could not be recorded.')
    except BrowserStopped:
        raise
    except Exception:
        raise BrowserStopped('The private frame could not be recorded.') from None
    return path


# Page content is untrusted data. This script reads rendered text only, never
# source, input values, scripts, hidden text, form actions, URLs or arbitrary attrs.
VISIBLE_TEXT = r'''(root) => {
 const parts = []; const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
 while (walker.nextNode() && parts.join('').length < 50000) {
  const node = walker.currentNode, el = node.parentElement;
  if (!el || el.closest('script,style,noscript,textarea,input,select,[hidden],[aria-hidden="true"]')) continue;
  if (!el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) continue;
  parts.push(node.textContent);
 }
 return parts.join(' ').replace(/\s+/g, ' ').slice(0,50000);
}'''
FIELD = r'''el => ({tag:el.tagName.toLowerCase(),type:(el.type||'').toLowerCase(),
 autocomplete:(el.autocomplete||'').toLowerCase(),name:el.name||'',id:el.id||'',
 label:el.getAttribute('aria-label')||'',placeholder:el.getAttribute('placeholder')||'',
 editable:el.isContentEditable,
 login:!!(el.form && el.form.querySelector('input[type="password"]'))})'''


class BrowserController:
    def __init__(self, backend: BrowserBackend, hosts: list[str], *,
                 check_action: Callable[[str, dict], None],
                 on_secret: Callable[[dict], None],
                 record_frame: Callable[[bytes, str, str], None],
                 deny_hosts: list[str] = (), clock=time.monotonic):
        self.backend = backend
        self.hosts = [normalize_host(h) for h in hosts]
        self.deny_hosts = [normalize_host(h) for h in deny_hosts]
        self.check_action, self.on_secret, self.record_frame = check_action, on_secret, record_frame
        self.clock = clock
        self.scrubber = SecretScrubber()
        self.tabs, self.refs = {}, {}
        self.active = None
        self.hold = None
        self._hold_element = None
        self._private_pixels = False
        self._closed = False

    def open(self):
        self.backend.open()
        self._new_tab()
        return self

    def close(self):
        self._closed = True
        self.hold = self._hold_element = None
        self.refs.clear()
        self.scrubber = SecretScrubber()
        self.backend.close()

    def _new_tab(self):
        if len(self.tabs) >= 3:
            raise BrowserStopped('The three-tab limit was reached.')
        tid = str(uuid4())
        page = self.backend.page()
        self.tabs[tid] = page
        self.active = tid
        page.on('framenavigated', lambda frame: self.refs.clear())
        return tid

    def _page(self, args):
        tid = args.get('tab_id', self.active)
        if tid not in self.tabs or self.tabs[tid].is_closed():
            raise BrowserStopped('The requested tab is unavailable.')
        return tid, self.tabs[tid]

    def _check_hosts(self):
        if getattr(self.backend, 'blocked', False):
            raise BrowserStopped('A request left the approved sites. The run must stop.')
        for page in self.tabs.values():
            if page.is_closed():
                continue
            if page.url != 'about:blank' and not host_allowed(page.url, self.hosts, self.deny_hosts):
                raise BrowserStopped('The page left the approved sites. The run must stop.')
            for frame in page.frames:
                if frame == page.main_frame:
                    continue  # Its URL was checked above; inspect child frames here.
                if frame.url not in ('about:blank', 'about:srcdoc', '') and not host_allowed(frame.url, self.hosts, self.deny_hosts):
                    raise BrowserStopped('A frame left the approved sites. The run must stop.')

    def _state(self, changes=None):
        block = {'type': 'browser_state', 'tabs': [
            {'tab_id': tid, 'title': self.scrubber.text(p.title())[:4096],
             'url': self.scrubber.url(p.url), 'active': tid == self.active}
            for tid, p in self.tabs.items() if not p.is_closed()]}
        if changes:
            block['state_changes'] = changes
        return block

    def _pixels(self, page, region=None):
        # After a fill the site can echo a secret in canvas, CSS, QR codes or a
        # remote image. Field masks alone cannot make that safe. Keep a privacy
        # curtain for the rest of this run; sanitized DOM navigation still works.
        if self._private_pixels:
            img = Image.new('RGB', (VIEWPORT['width'], VIEWPORT['height']), NAVY)
        else:
            masks = [f.locator('input,textarea,select,[contenteditable="true"]') for f in page.frames]
            png = page.screenshot(type='png', mask=masks, mask_color=NAVY,
                                  animations='disabled', timeout=5000)
            img = Image.open(io.BytesIO(png)).convert('RGB')
        if region is not None:
            if (not isinstance(region, list) or len(region) != 4
                    or any(type(n) is not int for n in region)
                    or not 0 <= region[0] < region[2] <= VIEWPORT['width']
                    or not 0 <= region[1] < region[3] <= VIEWPORT['height']):
                raise BrowserStopped('Invalid zoom region.')
            img = img.crop(region)
        out = io.BytesIO()
        img.save(out, format='PNG')
        return out.getvalue()

    def _capture(self, page, tool):
        self._check_hosts()
        png = self._pixels(page)
        jpeg = io.BytesIO()
        Image.open(io.BytesIO(png)).convert('RGB').save(jpeg, format='JPEG', quality=JPEG_QUALITY)
        self.record_frame(jpeg.getvalue(), urlsplit(page.url).hostname or '', tool)
        return png

    def _element(self, tid, target):
        if not isinstance(target, dict) or target.get('type') != 'ref':
            raise BrowserStopped('This action requires an element reference.')
        entry = self.refs.get(target.get('ref'))
        if (not entry or entry[0] != tid or not entry[1].evaluate('el => el.isConnected')
                or self._signature(entry[1]) != entry[2]):
            raise BrowserStopped('The element changed. Read the page again.')
        return entry[1]

    @staticmethod
    def _signature(el):
        # Store internal snapshots without exposing attributes to the model.
        # Reusing a node for another action invalidates its prior authority.
        return el.evaluate('''el => [el.tagName, el.type, el.name, el.id,
          el.getAttribute('href'), el.getAttribute('formaction'),
          el.form && el.form.action, el.textContent,
          el.getAttribute('aria-label'), el.getAttribute('autocomplete')]''')

    @staticmethod
    def _point(target):
        if (not isinstance(target, dict) or target.get('type') != 'coordinate'
                or type(target.get('x')) is not int or type(target.get('y')) is not int
                or not 0 <= target['x'] < VIEWPORT['width']
                or not 0 <= target['y'] < VIEWPORT['height']):
            raise BrowserStopped('A point inside the viewport is required.')
        return target['x'], target['y']

    def _focused(self, page):
        frame = page.main_frame
        for _ in range(10):
            el = frame.query_selector(':focus')
            if el is None:
                raise BrowserStopped('Focus could not be inspected.')
            if el.evaluate('el => el.tagName') not in ('IFRAME', 'FRAME'):
                return el
            frame = el.content_frame()
            if frame is None:
                break
        raise BrowserStopped('Focus could not be inspected.')

    def _inspect(self, tid, page, el):
        attrs = el.evaluate(FIELD)
        if attrs['type'] == 'file':
            raise BrowserStopped('File uploads are disabled.')
        # Usernames must go through Secure Entry too, even when the legacy
        # hand's narrower password/card matcher would allow ordinary text.
        sensitive = (attrs['login'] and attrs['tag']=='input' and attrs['type'] not in ('checkbox','radio')) or forbidden_field(attrs) or re.search(
            r'user.?name|login|cc-name', ' '.join(str(attrs.get(k, '')) for k in
                                               ('name','id','autocomplete','label')),
            re.I)
        if sensitive:
            host = urlsplit(el.owner_frame().url).hostname
            if not host or not host_allowed('https://' + host, self.hosts, self.deny_hosts):
                raise BrowserStopped('Secure Entry requires an approved HTTPS frame.')
            haystack = ' '.join(str(v) for v in attrs.values()).lower()
            kind = 'otp' if re.search(r'one-time|otp|passcode', haystack) else (
                'card' if re.search(r'cc-|card|cvc|cvv|expir', haystack) else 'login')
            self.hold = {'id': str(uuid4()), 'kind': 'secret', 'field_kind': kind,
                         'host': host, 'tab_id': tid, 'expires': self.clock() + 600}
            self._hold_element = el
            self.on_secret({k:v for k,v in self.hold.items() if k != 'expires'})
            return False
        if attrs['tag'] not in ('input','textarea','select') and not attrs['editable']:
            raise BrowserStopped('The target is not an editable field.')
        return True

    def fill_secret(self, hold_id: str, fields: dict[str, str]):
        """Internal thread-only primitive. Caller authenticates/step-ups first.

        Revalidates the live hold and target frame immediately before filling.
        No plaintext return value, event, exception or model argument is emitted.
        Multiple-field mapping is deliberately server owned (HTML autocomplete,
        types and names); ambiguous or missing fields fail closed.
        """
        hold, el = self.hold, self._hold_element
        if (not hold or hold['id'] != hold_id or self.clock() >= hold['expires']
                or el is None or not el.evaluate('el => el.isConnected')):
            raise BrowserStopped('Secure Entry expired. Start a new hold.')
        self._check_hosts()
        self.check_action('secure_fill', {'hold_id': hold_id})
        frame = el.owner_frame()
        if urlsplit(frame.url).hostname != hold['host']:
            raise BrowserStopped('The Secure Entry host changed.')
        selectors = {
            'login': {'username':'input[autocomplete="username"],input[type="email"],input[name="username"]',
                      'password':'input[type="password"]'},
            'otp': {'code':'input[autocomplete="one-time-code"],input[name="otp"],input[name="code"]'},
            'card': {'number':'input[autocomplete="cc-number"]',
                     'exp':'input[autocomplete="cc-exp"]', 'cvc':'input[autocomplete="cc-csc"]',
                     'name':'input[autocomplete="cc-name"]'},
        }[hold['field_kind']]
        if (not isinstance(fields, dict) or set(fields) != set(selectors)
                or any(not isinstance(v, str) or not v or len(v)>4096 for v in fields.values())):
            raise BrowserStopped('Secure Entry fields do not match this hold.')
        targets = {}
        for key, selector in selectors.items():
            candidates = [x for x in frame.query_selector_all(selector) if x.is_visible() and x.is_editable()]
            if len(candidates) != 1:
                raise BrowserStopped('Secure Entry cannot identify each field safely.')
            targets[key] = candidates[0]
        self.scrubber.remember(fields)
        self._private_pixels = True
        try:
            for key, target in targets.items():
                self._check_hosts()
                if urlsplit(frame.url).hostname != hold['host']:
                    raise BrowserStopped('The Secure Entry host changed.')
                target.fill(fields[key])
        except Exception:
            raise BrowserStopped('Secure Entry could not fill the current form.') from None
        self._check_hosts()
        self.hold = self._hold_element = None
        return 'filled'

    def _read(self, tid, page, args, query=None):
        # New references never reuse IDs; discard stale refs on each read.
        root = self._element(tid, {'type':'ref','ref':args['ref']}) if args.get('ref') else None
        self.refs.clear()
        frames = [root.owner_frame()] if root else page.frames
        lines = []
        for frame in frames:
            scope = root or frame.query_selector('body')
            if not scope:
                continue
            if args.get('filter') != 'interactive' and query is None:
                lines.append(scope.evaluate(VISIBLE_TEXT))
            for el in scope.query_selector_all('a,button,input,textarea,select,[role="button"],[contenteditable="true"]'):
                if not el.is_visible():
                    continue
                attrs = el.evaluate(FIELD)
                label = self.scrubber.text(el.evaluate(VISIBLE_TEXT) or attrs['label'] or attrs['placeholder'])[:500]
                if attrs['tag']=='select':
                    label += ' options: ' + self.scrubber.text(', '.join(
                        option.inner_text() for option in el.query_selector_all('option')))[:1000]
                if query and not all(word in label.lower() for word in query.lower().split()):
                    continue
                ref = 'ref_' + uuid4().hex
                self.refs[ref] = (tid, el, self._signature(el))
                lines.append(f'{ref} {attrs["tag"]} {attrs["type"]} {label}')
                if query and len(self.refs) >= 20:
                    break
        return self.scrubber.text('\n'.join(lines))[:50000]

    @staticmethod
    def _keys(text):
        if not isinstance(text, str) or not 1 <= len(text) <= 160:
            raise BrowserStopped('Invalid key sequence.')
        aliases = {'ctrl':'Control', 'alt':'Alt', 'shift':'Shift', 'cmd':'Meta',
                   'super':'Meta', 'enter':'Enter', 'return':'Enter', 'esc':'Escape',
                   'escape':'Escape', 'tab':'Tab', 'backspace':'Backspace',
                   'delete':'Delete', 'space':'Space', 'up':'ArrowUp', 'down':'ArrowDown',
                   'left':'ArrowLeft', 'right':'ArrowRight', 'home':'Home', 'end':'End',
                   'pageup':'PageUp','pagedown':'PageDown'}
        sequences = []
        for chord in text.split():
            parts = [aliases.get(p.lower(), p) for p in chord.split('+')]
            # No clipboard, address bar, browser dialogs/devtools, downloads or
            # platform hotkeys. Ordinary editing/navigation stays supported.
            if any(p in {'Control','Meta','Alt'} or re.fullmatch(r'F\d+',p) for p in parts):
                raise BrowserStopped('That browser shortcut is disabled.')
            if any(len(p) != 1 and p not in set(aliases.values()) for p in parts):
                raise BrowserStopped('Invalid key sequence.')
            sequences.append('+'.join(parts))
        return sequences

    def _dispatch(self, name, args):
        if name == 'new_tab':
            tid = self._new_tab()
            return [self._state([{'type':'tab_opened','tab_id':tid}])]
        if name == 'list_tabs':
            return [self._state()]
        tid, page = self._page(args)
        if name == 'switch_tab':
            self.active = tid
            page.bring_to_front()
            return [self._state()]
        if name == 'close_tab':
            if len(self.tabs) == 1:
                raise BrowserStopped('Keep at least one tab open.')
            page.close()
            del self.tabs[tid]
            if self.active == tid:
                self.active = next(iter(self.tabs))
            self.refs.clear()
            return [self._state()]
        if name == 'navigate':
            url = args.get('url')
            if url in ('back', 'forward', 'reload'):
                getattr(page, {'back':'go_back','forward':'go_forward','reload':'reload'}[url])(wait_until='domcontentloaded')
            else:
                if not isinstance(url,str) or not host_allowed(url, self.hosts, self.deny_hosts):
                    raise BrowserStopped('Navigation requires an approved HTTPS site.')
                page.goto(url, wait_until='domcontentloaded')
            self.refs.clear()
        elif name in ('read_page','find'):
            return [{'type':'text','text':self._read(tid,page,args,args.get('query') if name=='find' else None)}]
        elif name == 'get_page_text':
            return [{'type':'text','text':self.scrubber.text(page.locator('body').evaluate(VISIBLE_TEXT))}]
        elif name in ('screenshot','zoom'):
            return [{'type':'image','source':{'type':'base64','media_type':'image/png',
                'data':base64.b64encode(self._pixels(page,args.get('region') if name=='zoom' else None)).decode()}}]
        elif name in ('type','form_input'):
            el = self._element(tid,args.get('target')) if name=='form_input' else self._focused(page)
            if not self._inspect(tid,page,el):
                return [{'type':'text','text':'Secure Entry is required. The run is paused.'}]
            value = args.get('value') if name=='form_input' else args.get('text')
            attrs = el.evaluate(FIELD)
            if attrs['type'] in ('checkbox','radio') and type(value) is bool:
                el.set_checked(value)
            elif attrs['tag']=='select':
                options=el.query_selector_all('option')
                matches=[o.get_attribute('value') or o.inner_text() for o in options
                         if o.get_attribute('value')==str(value) or o.inner_text()==str(value)]
                if len(matches)!=1:
                    raise BrowserStopped('The selected option is unavailable or ambiguous.')
                el.select_option(matches[0])
            elif isinstance(value,(str,int,float)) and not isinstance(value,bool) and len(str(value))<=4096:
                el.fill(str(value)) if name=='form_input' else el.type(str(value))
            else:
                raise BrowserStopped('Invalid form value.')
        elif name in ('key','hold_key'):
            keys = self._keys(args.get('text'))
            # Inspect focus even for Enter: a sensitive form may submit on it.
            el = self._focused(page)
            attrs = el.evaluate(FIELD)
            if attrs['tag'] in ('input','textarea','select') or attrs['editable']:
                if not self._inspect(tid,page,el):
                    return [{'type':'text','text':'Secure Entry is required. The run is paused.'}]
            if name=='hold_key':
                duration = self._duration(args)
                if len(keys)!=1:
                    raise BrowserStopped('Hold one key at a time.')
                try:
                    page.keyboard.down(keys[0])
                    page.wait_for_timeout(duration*1000)
                finally:
                    page.keyboard.up(keys[0])
            else:
                repeat = args.get('repeat',1)
                if type(repeat) is not int or not 1<=repeat<=100:
                    raise BrowserStopped('Invalid key repeat.')
                for _ in range(repeat):
                    for key in keys:
                        page.keyboard.press(key)
        elif name=='wait':
            page.wait_for_timeout(self._duration(args)*1000)
        elif name=='scroll_to':
            self._element(tid,args.get('target')).scroll_into_view_if_needed()
        elif name=='scroll':
            page.mouse.move(*self._point(args.get('target')))
            amount=args.get('scroll_amount',3)
            direction=args.get('scroll_direction')
            if type(amount) is not int or not 1<=amount<=10 or direction not in ('up','down','left','right'):
                raise BrowserStopped('Invalid scroll.')
            page.mouse.wheel((1 if direction=='right' else -1)*amount*100 if direction in ('left','right') else 0,
                             (1 if direction=='down' else -1)*amount*100 if direction in ('up','down') else 0)
        elif name=='left_click_drag':
            page.mouse.move(*self._point(args.get('from')))
            try:
                page.mouse.down()
                page.mouse.move(*self._point(args.get('target')), steps=8)
            finally:
                page.mouse.up()
        elif name in ('mouse_move','left_mouse_down','left_mouse_up'):
            page.mouse.move(*self._point(args.get('target')))
            if name!='mouse_move':
                getattr(page.mouse,'down' if name=='left_mouse_down' else 'up')()
        else:
            modifiers=args.get('modifiers',[])
            if not isinstance(modifiers,list) or any(m!='Shift' for m in modifiers):
                raise BrowserStopped('That click modifier is disabled.')
            target=args.get('target')
            clicks={'double_click':2,'triple_click':3}.get(name,1)
            button={'right_click':'right','middle_click':'middle'}.get(name,'left')
            if isinstance(target,dict) and target.get('type')=='ref':
                el=self._element(tid,target)
                if name=='hover':
                    el.hover()
                else:
                    el.click(button=button,click_count=clicks,modifiers=modifiers)
            elif name=='hover':
                page.mouse.move(*self._point(target))
            else:
                page.mouse.click(*self._point(target),button=button,click_count=clicks)
        return [{'type':'text','text':'Action completed.'}]

    @staticmethod
    def _duration(args):
        duration=args.get('duration',0)
        if type(duration) not in (int,float) or not 0<=duration<=30:
            raise BrowserStopped('Invalid duration.')
        return duration

    def execute(self, use: dict) -> dict:
        result={'type':'tool_result','tool_use_id':use.get('id',''), 'toolset_name':'browser'}
        try:
            name, args=use.get('name'),use.get('input',{})
            if self._closed or self.hold:
                raise BrowserStopped('The run is paused or closed.')
            if name not in TOOLS or use.get('toolset_name','browser')!='browser' or not isinstance(args,dict):
                raise BrowserStopped('This browser tool is disabled.')
            self._check_hosts()
            self.check_action(name,args)
            content=self._dispatch(name,args)
            self._check_hosts()
            # Every executed member records sanitized pixels, including reads.
            self._capture(self.tabs.get(args.get('tab_id'), self.tabs[self.active]),name)
            result['content']=content
        except BrowserStopped as exc:
            result.update(is_error=True,content=[{'type':'text','text':str(exc)}])
        except Exception:
            # Playwright errors may quote a selector or typed value.
            result.update(is_error=True,content=[{'type':'text','text':'The browser action could not complete.'}])
        return result

    def execute_batch(self, uses: list[dict]) -> list[dict]:
        results=[]
        halted=False
        for use in uses:
            if halted:
                result={'type':'tool_result','tool_use_id':use.get('id',''), 'toolset_name':'browser',
                        'is_error':True,'content':[{'type':'text','text':NOT_EXECUTED}]}
            else:
                result=self.execute(use)
            results.append(result)
            halted=halted or bool(result.get('is_error')) or self.hold is not None
        return results

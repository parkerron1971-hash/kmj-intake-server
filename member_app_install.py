"""
member_app_install.py — the member page installs like an app.

Subsplash's LCC app is in the app stores. Ours is the member page at
<church site>/my, and until now a phone could only bookmark it. This makes
it installable (a home-screen icon that opens in its own window, no
browser bar):

    /my/manifest.webmanifest   name, colours, icons, start /my, scope /my
    /my/icon-<size>.png        the church's initials on its own colour
    /my/sw.js                  a small service worker scoped to /my: pages
                               always come from the network; with no
                               connection, a plain "you're offline" page

and an "Install the app" card on Home: one tap where the browser offers
an install prompt (Android, desktop Chrome/Edge), the three steps on an
iPhone (Share, then Add to Home Screen). Hidden once installed or
dismissed.

Notifications: Kevin said yes to open decision 1 (2026-10-14). The
service worker shows a push and opens its /my link on a tap; who gets
what, and the church's and member's switches, live in member_push.py.
Store apps (Capacitor) are wave 3.
"""
from __future__ import annotations

import io
import json
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

from fastapi.responses import Response

ICON_SIZES = (180, 192, 512)
ASSETS = ("/my/manifest.webmanifest", "/my/sw.js") + tuple(f"/my/icon-{s}.png" for s in ICON_SIZES)

_CACHE_A_DAY = {"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"}


def _colours(biz: Dict[str, Any], site: Optional[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, Any]]:
    import member_app_ui as ui
    from public_form_theme import resolve_theme
    theme = resolve_theme(biz, site)
    return ui.palette(biz, theme), theme


def short_name(name: str) -> str:
    """What fits under a home-screen icon (about 12 characters): the
    name if it fits, else as many of its first words as fit, else its
    initials ("Love City Church" -> "Love City")."""
    name = " ".join((name or "").split()) or "Church"
    if len(name) <= 12:
        return name
    out = ""
    for word in name.split(" "):
        if len(out) + len(word) + (1 if out else 0) > 12:
            break
        out = f"{out} {word}".strip()
    if out and out.lower() not in ("the", "st.", "st"):
        return out
    import member_app_ui as ui
    return ui.initials(name)


def manifest(biz: Dict[str, Any], site: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    pal, _ = _colours(biz, site)
    name = " ".join((biz.get("name") or "").split()) or "Your church"
    return {
        "name": name,
        "short_name": short_name(name),
        "description": f"Your page at {name}: messages, groups, sermons, giving and what's coming up.",
        "id": "/my",
        "start_url": "/my",
        "scope": "/my",
        "display": "standalone",
        "background_color": pal["ground"],
        "theme_color": pal["ground"],
        "icons": [{"src": f"/my/icon-{s}.png", "sizes": f"{s}x{s}", "type": "image/png",
                   "purpose": "any maskable" if s == 512 else "any"} for s in (192, 512)],
    }


@lru_cache(maxsize=256)
def _icon(size: int, initials: str, ground: str, accent: str, on_accent: str) -> bytes:
    """A square icon: the church's initials on its accent colour, inside
    the maskable safe zone (the middle 80%), so a round launcher mask
    never cuts a letter."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (size, size), accent)
    draw = ImageDraw.Draw(img)
    text = (initials or "C")[:3]
    font = ImageFont.load_default(size=int(size * (0.40 if len(text) < 3 else 0.30)))
    box = draw.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), text, font=font, fill=on_accent)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def icon_png(biz: Dict[str, Any], site: Optional[Dict[str, Any]], size: int) -> bytes:
    import member_app_ui as ui
    pal, _ = _colours(biz, site)
    return _icon(int(size), ui.initials(biz.get("name") or "Church"),
                 pal["ground"], pal["accent"], pal["on_accent"])


# Network-first for every request it handles; the only thing it keeps is
# the offline page. Member pages are personal and change by the minute, so
# nothing else is cached. A push shows title + body and opens its /my link
# (member_push.py chooses the words; nothing private reaches a lock screen).
SW_JS = """// The member app's service worker (member_app_install.py).
const OFFLINE = '/my/offline';
const CACHE = 'member-offline-v1';
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.add(new Request(OFFLINE, {cache: 'reload'}))));
  self.skipWaiting();
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(fetch(e.request).catch(() => caches.match(OFFLINE)));
});
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {}; }
  // Only this app's own pages: /my, /my/..., /my?..., /my#...
  const ok = typeof d.url === 'string' && d.url.indexOf('/my') === 0 &&
    (d.url.length === 3 || '/?#'.indexOf(d.url.charAt(3)) !== -1);
  const url = ok ? d.url : '/my';
  e.waitUntil(self.registration.showNotification(d.title || 'Your church', {
    body: d.body || '', icon: '/my/icon-192.png', badge: '/my/icon-192.png',
    tag: d.tag || 'church', data: {url}}));
});
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/my';
  e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then((wins) => {
    for (const w of wins) {
      if (new URL(w.url).pathname.startsWith('/my') && 'focus' in w) { w.navigate(url); return w.focus(); }
    }
    return self.clients.openWindow(url);
  }));
});
"""


def serve_asset(biz: Dict[str, Any], site: Optional[Dict[str, Any]], path: str) -> Optional[Response]:
    """The response for one of ASSETS, or None if `path` isn't one."""
    if path == "/my/manifest.webmanifest":
        return Response(json.dumps(manifest(biz, site)), media_type="application/manifest+json",
                        headers=_CACHE_A_DAY)
    if path == "/my/sw.js":
        # Scope /my (not just /my/), and always re-checked so a fix ships.
        return Response(SW_JS, media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/my",
                                 "X-Content-Type-Options": "nosniff"})
    for s in ICON_SIZES:
        if path == f"/my/icon-{s}.png":
            return Response(icon_png(biz, site, s), media_type="image/png", headers=_CACHE_A_DAY)
    return None


def head_tags(biz: Dict[str, Any]) -> str:
    """What every member page's <head> adds so the browser can install it."""
    from html import escape
    short = escape(short_name(biz.get("name") or ""), quote=True)
    return ('<link rel="manifest" href="/my/manifest.webmanifest">'
            '<link rel="apple-touch-icon" href="/my/icon-180.png">'
            '<meta name="mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
            f'<meta name="apple-mobile-web-app-title" content="{short}">')


REGISTER_JS = ("<script>if('serviceWorker' in navigator){window.addEventListener('load',function(){"
               "navigator.serviceWorker.register('/my/sw.js',{scope:'/my'}).catch(function(){});});}</script>")


def install_card(church_name: str) -> str:
    """Home's "Install the app" card. Starts hidden; the script shows it
    only where it can help: the browser offered an install prompt, or it's
    an iPhone/iPad in Safari not already opened from the home screen."""
    from html import escape
    name = escape(church_name or "the church", quote=True)
    return f"""
<section class="mp-card mb-install" id="mb-install" hidden aria-labelledby="mb-install-h">
  <h2 id="mb-install-h" class="mp-sect" style="margin-top:0">Put {name} on your home screen</h2>
  <p class="mp-muted">Open it like an app, one tap from your home screen.</p>
  <button class="mp-go" type="button" id="mb-install-go" hidden>Install the app</button>
  <ol class="mp-muted" id="mb-install-ios" hidden style="margin:8px 0 0 18px;line-height:1.6">
    <li>Tap the Share button at the bottom of Safari.</li>
    <li>Scroll down and tap <strong>Add to Home Screen</strong>.</li>
    <li>Tap <strong>Add</strong>.</li>
  </ol>
  <button class="mp-link" type="button" id="mb-install-no">Not now</button>
</section>
<script>(function(){{
  var card=document.getElementById('mb-install'); if(!card) return;
  var standalone=window.matchMedia('(display-mode: standalone)').matches||window.navigator.standalone===true;
  var dismissed=false; try{{dismissed=localStorage.getItem('mb-install-dismissed')==='1';}}catch(e){{}}
  if(standalone||dismissed) return;
  var ios=/iphone|ipad|ipod/i.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  var go=document.getElementById('mb-install-go'), steps=document.getElementById('mb-install-ios');
  document.getElementById('mb-install-no').addEventListener('click',function(){{
    card.hidden=true; try{{localStorage.setItem('mb-install-dismissed','1');}}catch(e){{}}
  }});
  if(ios){{ steps.hidden=false; card.hidden=false; return; }}
  var prompt=null;
  window.addEventListener('beforeinstallprompt',function(e){{
    e.preventDefault(); prompt=e; go.hidden=false; card.hidden=false;
  }});
  go.addEventListener('click',function(){{
    if(!prompt) return; prompt.prompt();
    prompt.userChoice.then(function(){{ card.hidden=true; prompt=null; }});
  }});
  window.addEventListener('appinstalled',function(){{ card.hidden=true; }});
}})();</script>"""


def render_offline(biz: Dict[str, Any], site: Optional[Dict[str, Any]]) -> str:
    from member_portal import _shell
    return _shell(biz, site, "Offline", """
<div class="mp-card"><h1>You're offline</h1>
<p class="mp-muted">This page needs a connection. Check your signal or Wi-Fi, then try again.</p>
<button class="mp-go" type="button" onclick="location.reload()">Try again</button></div>""")

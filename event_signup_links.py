"""event_signup_links.py — one sign-up link per event (docs/EVENT_SIGNUP_LINKS.md).

Kevin, 2026-11-22: "when the event is made there is no way for someone to sign
up with a link if there don't have the church app. can we fix this issue?",
then "yes to both" on the mock (artifact HmdpXJJNgzKefxW5qoAF5e) with its picks.

Every Services & Events entry gets one link, https://<slug>.mysolutionist.app
/e/<code>. Whoever opens it sees that one event and signs up with a name and a
phone number or an email, no app, no sign-in. The sign-up lands on the event as
a normal signup with via "link", and earns serving hours only once the office
says who it is (church_serving.event_credits).

THE CODE (spec 3.1). Never stored. The entry's data holds a random nonce,
_link = {n, at}; the code is the first 26 base32 characters of
HMAC-SHA256(derive_key("event-signup-link", business), "<entry>|<n>"). Reading
the entry (every seat can) gives the nonce, never the code; writing a nonce
only makes a new link, which the server still hands only to office logins.
Make a new link writes a new nonce, and the old code matches nothing. A code is
checked against every live link of the church with hmac.compare_digest.

    GET    /church/event-links/status?business_id=                    {enabled, can_change}
    GET    /church/event-links/{entry_id}?business_id=                the link (made if missing), its sign-ups
    POST   /church/event-links/{entry_id}/new                         {business_id}: a new link, the old one stops
    POST   /church/event-links/{entry_id}/signups/{sid}/confirm       {business_id, contact_id}
    POST   /church/event-links/{entry_id}/signups/{sid}/add           {business_id}: add to Members, then confirm
    DELETE /church/event-links/{entry_id}/signups/{sid}?business_id=  take the sign-up off
    POST   /public/event-link/{slug}                                  {code, name, reach, role?, website?}
    (page) https://<church host>/e/<code>                             public_site -> serve_page()

WHO. The office routes: require_user, then event_volunteers._login (an office
login of a church whose teams have owners, the church checked independently
of RLS), then the switch, then the event is this church's. A Viewer reads a
link already made and nothing else. The public routes are unauthenticated by
design: the public RSVP's rate limit first, a honeypot, and every way of not
taking sign-ups is the same 404.

THE SWITCH. EVENT_SIGNUP_LINKS = off | owner | on, owner when unset (the
platform owner's own church, member_asks.platform_church, never by who is
signed in), and only where EVENT_VOLUNTEERS is open (event_volunteers.open_for).
Only print(..., flush=True) reaches the logs, prefixed [event-links].
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import html as _html
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

import sb_clients
from auth_supabase import AuthedUser, require_user

router = APIRouter(tags=["church"])

SWITCH = "EVENT_SIGNUP_LINKS"
PURPOSE = "event-signup-link"
CODE_LEN = 26
CODE_RE = re.compile(r"[a-z2-7]{26}")
NONCE_RE = re.compile(r"[0-9a-f]{32}")
SID_RE = re.compile(r"[0-9a-f]{16}")
PHONE_DIGITS = (7, 15)
NAME_MAX = 120
TRIES = 5
MAX_HINTS = 25          # Members lookups one read of the sign-ups makes at most

NOT_TAKING = "This event isn't taking sign-ups."
NOT_READY = "Sign-up links aren't ready here yet."
KIDS = "Ask the office about this one."
NO_NAME = "Please tell us your name."
NO_REACH = "Add a phone number or an email so the church can reach you."
BAD_EMAIL = "That email doesn't look right."
BAD_PHONE = "That phone number doesn't look right."
NO_ROLE = "Pick one of the ways to help on the page."
FULL = "This event is full."
TAKES_SIGNUPS = "This event takes sign-ups on the church's events page."
GONE_SIGNUP = "That sign-up isn't on this event any more."
NOT_MEMBER = "They aren't on this church's Members."
UNSAVED = "That didn't save. Try again."
BUSY = "Someone else was saving this event at the same moment. Try again."
ROLL_ONLY = "Adding people to Members is for People & care and the Office."


def _log(msg: str) -> None:
    print(f"[event-links] {msg}", flush=True)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _plain(v: Any, most: int = 200) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(v or ""))
    return re.sub(r"\s+", " ", s).strip()[:most]


def _rows(path: str) -> List[Dict[str, Any]]:
    got = sb_clients.sb_get_as_service(path)
    return got if isinstance(got, list) else []


# ─── the switch ──────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_here(business_id: Any) -> bool:
    """Links open for this church: the switch (owner = the platform owner's
    own church, read from the church), and EVENT_VOLUNTEERS open here."""
    m = mode()
    if m == "off":
        return False
    if m == "owner":
        try:
            import member_asks
            if not member_asks.platform_church(business_id):
                return False
        except Exception:  # noqa: BLE001 — a lookup that fails is a no
            return False
    try:
        import event_volunteers as evv
        return bool(evv.open_for(business_id))
    except Exception:  # noqa: BLE001
        return False


# ─── the code ────────────────────────────────────────────────────────

def _key(business_id: str) -> bytes:
    """The church's own key (HKDF from CUSTOMER_TOKEN_SECRET). RuntimeError
    when the root isn't set: no link can be made or checked."""
    from customer_token import derive_key
    return derive_key(PURPOSE, str(business_id))


def link_of(data: Any) -> Optional[Dict[str, str]]:
    """The entry's _link, held to its shape on every read: n exactly 32
    lowercase hex characters, at a string. Anything else is no link."""
    lk = data.get("_link") if isinstance(data, dict) else None
    if not isinstance(lk, dict):
        return None
    n, at = lk.get("n"), lk.get("at")
    if not isinstance(n, str) or not NONCE_RE.fullmatch(n) or not isinstance(at, str) or len(at) > 64:
        return None
    return {"n": n, "at": at}


def code_for(business_id: str, entry_id: str, nonce: str, key: Optional[bytes] = None) -> str:
    d = hmac.new(key or _key(business_id), f"{entry_id}|{nonce}".encode(), hashlib.sha256).digest()
    return base64.b32encode(d).decode().lower().rstrip("=")[:CODE_LEN]


def new_link() -> Dict[str, str]:
    return {"n": secrets.token_hex(16), "at": _now().isoformat()}


def clean_code(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().lower()
    return s if CODE_RE.fullmatch(s) else None


def link_url(slug: str, code: str) -> str:
    from business_sites_helpers import PUBLIC_DOMAIN
    return f"https://{slug}.{PUBLIC_DOMAIN}/e/{code}"


def _modules(biz: str) -> Dict[str, Dict[str, Any]]:
    return {str(m["id"]): m for m in _rows(
        f"/custom_modules?business_id=eq.{_q(biz)}&archetype=eq.event_roster&is_active=eq.true"
        "&select=id,archetype_params,is_active&limit=50")}


def find_by_code(biz: str, code: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """(entry, its room) whose live link is this code, or None. Every
    candidate is compared in constant time, with no early exit."""
    try:
        key = _key(biz)
    except RuntimeError:
        return None
    mods = _modules(biz)
    hit = None
    import events_rsvp_router as er
    for mid in mods:
        for e in _rows(f"/module_entries?business_id=eq.{_q(biz)}&module_id=eq.{_q(mid)}&status=eq.active"
                       f"&select=id,module_id,status,data,updated_at&limit={er.MAX_ENTRIES_PER_MODULE}"):
            lk = link_of(e.get("data"))
            if lk is None:
                continue
            if hmac.compare_digest(code_for(biz, str(e["id"]), lk["n"], key), code) and hit is None:
                hit = (e, mods[mid])
    return hit


# ─── reading and writing the event ───────────────────────────────────

def _signups_field(mod: Dict[str, Any]) -> str:
    import events_rsvp_router as er
    return er.resolve_fields(mod.get("archetype_params"))["signups_field"]


def _change(biz: str, eid: str, fn: Callable[[Dict[str, Any], Dict[str, Any]], Any]) -> Tuple[Dict[str, Any], Any, Any]:
    """A read-modify-write of the entry's data as the server, its revision
    (updated_at) as the guard, tried TRIES times. `fn(data, row)` changes data
    in place and returns what the caller wants back; it may raise. (data,
    what fn returned, updated_at)."""
    for _ in range(TRIES):
        rows = _rows(f"/module_entries?id=eq.{_q(eid)}&business_id=eq.{_q(biz)}"
                     "&select=id,module_id,status,data,updated_at&limit=1")
        if not rows:
            raise HTTPException(404, NOT_TAKING)
        row = rows[0]
        data = copy.deepcopy(row.get("data")) if isinstance(row.get("data"), dict) else {}
        out = fn(data, row)
        rev = row.get("updated_at")
        guard = f"&updated_at=eq.{_q(rev)}" if rev else ""
        got = sb_clients.sb_patch_as_service(
            f"/module_entries?id=eq.{_q(eid)}&business_id=eq.{_q(biz)}{guard}&select=id,data,updated_at",
            {"data": data})
        if not isinstance(got, list):
            raise HTTPException(503, UNSAVED)
        if got:
            saved = got[0].get("data") if isinstance(got[0].get("data"), dict) else data
            return saved, out, got[0].get("updated_at")
    raise HTTPException(409, BUSY)


# ─── what the page shows ─────────────────────────────────────────────

def _when_words(day, at) -> str:
    import event_volunteers as evv
    words = f"{day.strftime('%A, %B')} {day.day}"
    return f"{words} · {evv.clock_words(at)}" if at is not None else words


def event_view(biz: str, e: Dict[str, Any], mod: Dict[str, Any], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """What the link's page needs, or None when the event isn't taking
    sign-ups: archived, its room off, no date, or already past (a start time
    passed; a bare date, once that day is over)."""
    import event_volunteers as evv
    import events_rsvp_router as er
    import sunday_planning as sp
    zone = sp._zone(biz)
    ent = evv.entry_view(e, mod, zone)
    if not ent["active"] or ent["day"] is None:
        return None
    now = now or evv._now()
    local = now.astimezone(zone)
    if (ent["at"] is not None and ent["at"] <= now) or (ent["at"] is None and ent["day"] < local.date()):
        return None
    f = er.resolve_fields(mod.get("archetype_params"))
    data = ent["data"]
    signups = er.read_signups(data, f["signups_field"])
    capacity = er._capacity_of(data, f["capacity_field"])
    full = capacity is not None and er.attending_count(signups) >= capacity
    roles = []
    for r in ent["roles"]:
        if er.kids_role(r):
            roles.append({"id": str(r["id"]), "raw": r["id"], "label": _plain(r.get("label"), 80) or "A role",
                          "kids": True})
            continue
        fill = er.role_fill(r, signups)
        roles.append({"id": str(r["id"]), "raw": r["id"], "label": _plain(fill["label"], 80) or "A role", "kids": False,
                      "needed": fill["needed"], "left": max(0, fill["needed"] - fill["filled"]),
                      "full": fill["full"] or full})
    blocks = False
    try:
        import church_event_signups
        blocks = bool(church_event_signups.blocks_free_rsvp(biz, ent["entry_id"]))
    except Exception:  # noqa: BLE001 — a read that fails blocks nothing (the RSVP's own rule)
        blocks = False
    return {"entry_id": ent["entry_id"], "title": ent["title"], "when": _when_words(ent["day"], ent["at"]),
            "place": ent["place"], "flyer": evv.flyer_of(data, biz, ent["entry_id"]), "roles": roles,
            "full": full, "just_coming": not full and not blocks, "blocks": blocks,
            "visibility": er.occasion_visibility(data)}


def page_state(biz_id: Any, code_raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(the church, the event's view) for a link, the view None for every way
    of not taking sign-ups, alike."""
    try:
        import sunday_planning as sp
        biz = sp._uuid(biz_id)
    except HTTPException:
        return None, None
    rows = _rows(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,settings&limit=1")
    church = rows[0] if rows else None
    if church is None:
        return None, None
    code = clean_code(code_raw)
    if code is None:
        return church, None
    import sample_church
    if sample_church.is_sample(biz) or not open_here(biz):
        return church, None
    hit = find_by_code(biz, code)
    if hit is None:
        return church, None
    return church, event_view(biz, hit[0], hit[1])


# ─── the page (pure) ─────────────────────────────────────────────────

def _e(s: Any) -> str:
    return _html.escape(str(s or ""), quote=True)


HEAD_SAFETY = ('<meta name="robots" content="noindex,nofollow">'
               '<meta name="referrer" content="strict-origin">')
PAGE_HEADERS = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "strict-origin"}

CSS = """
html,body{margin:0;padding:0;font-family:var(--font-body);color:var(--text-primary);background:var(--surface);min-height:100vh}
*{box-sizing:border-box}
.sl-shell{max-width:480px;margin:0 auto;padding:24px 16px 48px}
.sl-church{display:flex;align-items:center;gap:10px;font-size:13px;font-weight:600;letter-spacing:.08em;
text-transform:uppercase;color:var(--text-secondary)}
.sl-church img{width:36px;height:36px;object-fit:contain;border-radius:8px}
.sl-title{font-family:var(--font-heading);font-size:26px;line-height:1.2;font-weight:700;margin:14px 0 4px}
.sl-when{font-size:15px;font-weight:600;color:var(--accent)}
.sl-place{font-size:15px;color:var(--text-secondary);margin-top:2px}
.sl-flyer{display:block;margin:16px 0 4px}
.sl-flyer img{display:block;width:100%;height:auto;border-radius:var(--radius)}
.sl-form{margin-top:20px;display:flex;flex-direction:column;gap:10px}
.sl-ask{font-family:var(--font-heading);font-size:17px;font-weight:700;margin:4px 0 2px;padding:0;border:0}
fieldset{border:0;margin:0;padding:0;display:flex;flex-direction:column;gap:8px;min-width:0}
.sl-role{display:flex;align-items:center;gap:12px;min-height:52px;padding:10px 14px;border:1.5px solid var(--border);
border-radius:var(--radius);cursor:pointer;font-size:16px}
.sl-role input{width:20px;height:20px;margin:0;accent-color:var(--accent);flex:none}
.sl-role .sl-label{flex:1;min-width:0}
.sl-role .sl-left{font-size:13px;color:var(--text-secondary);white-space:nowrap}
.sl-role:has(input:checked){border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.sl-role.sl-off{cursor:default;opacity:.7}
.sl-field{display:flex;flex-direction:column;gap:6px;font-size:14px;font-weight:600;margin-top:6px}
.sl-input{width:100%;padding:12px 14px;font-size:16px;border:1.5px solid var(--border);border-radius:var(--radius);
background:var(--input-surface);color:var(--text-primary);min-height:48px;font-family:var(--font-body)}
.sl-go{width:100%;margin-top:8px;padding:14px 0;font-size:16px;font-weight:700;border:0;border-radius:var(--radius);
background:var(--accent);color:var(--accent-text);cursor:pointer;min-height:50px;font-family:var(--font-body)}
.sl-go:disabled{opacity:.55;cursor:default}
.sl-input:focus-visible,.sl-go:focus-visible,.sl-role:focus-within{outline:2px solid var(--focus);outline-offset:3px}
.sl-hp{position:absolute;left:-10000px;width:1px;height:1px;overflow:hidden}
.sl-msg{font-size:14px;line-height:1.5;color:var(--error);min-height:1px}
.sl-done{margin-top:20px;border:1.5px solid var(--accent);border-radius:var(--radius);padding:16px}
.sl-done h2{font-family:var(--font-heading);font-size:20px;margin:0 0 6px}
.sl-done p{margin:4px 0;font-size:15px;line-height:1.5}
.sl-note{margin-top:18px;font-size:14px;line-height:1.5;color:var(--text-secondary)}
.sl-foot{text-align:center;font-size:11px;color:var(--text-muted);margin-top:32px;padding-top:14px;
border-top:1px solid var(--border)}
.sl-foot a{color:var(--text-muted);text-decoration:none}
"""


def _theme(church: Dict[str, Any], site: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], str, str]:
    from public_form_theme import css_vars, font_links, resolve_theme
    theme = resolve_theme(church, site)
    return theme, css_vars(theme), font_links(theme)


def _head(title: str, church: Dict[str, Any], site: Optional[Dict[str, Any]], extra: str = "") -> Tuple[str, Dict[str, Any]]:
    theme, vars_css, fonts = _theme(church, site)
    head = (f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0">{HEAD_SAFETY}'
            f"<title>{_e(title)}</title>{extra}{fonts}<style>{vars_css}</style><style>{CSS}</style></head>")
    return head, theme


def _church_line(church: Dict[str, Any], theme: Dict[str, Any]) -> str:
    name = _plain(church.get("name"), 120) or "Our church"
    logo = theme.get("logo_url") or ""
    img = f'<img src="{_e(logo)}" alt="">' if logo else ""
    return f'<div class="sl-church">{img}<span>{_e(name)}</span></div>'


FOOT = ('<footer class="sl-foot">Powered by <a href="https://mysolutionist.app/" target="_blank" '
        'rel="noopener">Solutionist</a></footer>')


def render_closed(church: Optional[Dict[str, Any]], site: Optional[Dict[str, Any]] = None) -> str:
    """Every way of not taking sign-ups: one page, the same for each."""
    church = church or {"name": ""}
    name = _plain(church.get("name"), 120) or "Sign up"
    head, theme = _head(name, church, site)
    return (f'{head}<body><main class="sl-shell">{_church_line(church, theme)}'
            f'<h1 class="sl-title">{_e(NOT_TAKING)}</h1>'
            '<p class="sl-note">The link may be old, or the event may have already happened. '
            'Ask the church for a new one.</p>'
            f"{FOOT}</main></body></html>")


def _role_rows(view: Dict[str, Any]) -> Tuple[str, int]:
    rows, open_n = [], 0
    for r in view["roles"]:
        if r["kids"]:
            rows.append(f'<div class="sl-role sl-off"><span class="sl-label">{_e(r["label"])}</span>'
                        f'<span class="sl-left">{_e(KIDS)}</span></div>')
            continue
        if r["full"]:
            rows.append(f'<div class="sl-role sl-off"><span class="sl-label">{_e(r["label"])}</span>'
                        '<span class="sl-left">Full</span></div>')
            continue
        open_n += 1
        rows.append(f'<label class="sl-role"><input type="radio" name="role" value="{_e(r["id"])}" '
                    f'data-label="{_e(r["label"])}"><span class="sl-label">{_e(r["label"])}</span>'
                    f'<span class="sl-left">{r["left"]} needed</span></label>')
    if view["just_coming"]:
        open_n += 1
        rows.append('<label class="sl-role"><input type="radio" name="role" value="" data-label="Coming">'
                    '<span class="sl-label">Just coming</span><span class="sl-left">No role</span></label>')
    return "".join(rows), open_n


SCRIPT = """
(function(){
  var API = %(api)s, SLUG = %(slug)s, CODE = %(code)s, WHEN = %(when)s, PLACE = %(place)s;
  var form = document.getElementById('sl-form');
  if (!form) return;
  var msg = form.querySelector('.sl-msg'), go = form.querySelector('.sl-go');
  function say(t){ msg.textContent = t; }
  form.addEventListener('submit', function(ev){
    ev.preventDefault();
    say('');
    var pick = form.querySelector('input[name=role]:checked');
    var name = form.querySelector('[name=name]').value.trim();
    var reach = form.querySelector('[name=reach]').value.trim();
    if (!pick) { say('Pick how you would like to help.'); return; }
    if (!name) { say(%(no_name)s); return; }
    if (!reach) { say(%(no_reach)s); return; }
    go.disabled = true;
    fetch(API + '/public/event-link/' + encodeURIComponent(SLUG), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code: CODE, name: name, reach: reach, role: pick.value || undefined,
                            website: form.querySelector('[name=website]').value})
    }).then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }, function(){ return {ok: false, j: {}}; }); })
      .then(function(res){
        if (res.ok && res.j && res.j.ok) {
          var done = document.createElement('div'); done.className = 'sl-done'; done.setAttribute('role', 'status');
          var h = document.createElement('h2'); h.textContent = "You're on the list."; done.appendChild(h);
          var p = document.createElement('p');
          p.textContent = [res.j.role || pick.getAttribute('data-label') || 'Coming', res.j.when || WHEN, res.j.place || PLACE]
            .filter(function(x){ return x; }).join(' · ');
          done.appendChild(p);
          if (res.j.emailed) { var m = document.createElement('p'); m.textContent = 'We sent the details to ' + reach + '.'; done.appendChild(m); }
          var n = document.createElement('p'); n.textContent = 'The church will be in touch if anything changes.'; done.appendChild(n);
          form.replaceWith(done); done.setAttribute('tabindex', '-1'); done.focus();
          return;
        }
        say((res.j && typeof res.j.detail === 'string' && res.j.detail) || 'That didn\\u2019t go through. Try again.');
        go.disabled = false;
      }).catch(function(){ say('That didn\\u2019t go through. Check your connection and try again.'); go.disabled = false; });
  });
})();
"""


def render_page(church: Dict[str, Any], site: Optional[Dict[str, Any]], view: Dict[str, Any], code: str,
                *, api_origin: str, slug: str) -> str:
    """The link's page: the one event, and the sign-up. Counts only, never
    anyone's name."""
    title = view["title"]
    f = view.get("flyer")
    og = (f'<meta property="og:title" content="{_e(title)}">'
          f'<meta property="og:description" content="{_e(" · ".join(x for x in (view["when"], view["place"]) if x))}">'
          '<meta property="og:type" content="website">')
    flyer = ""
    if isinstance(f, dict) and f.get("url") and f.get("thumb"):
        og += f'<meta property="og:image" content="{_e(f["url"])}">'
        try:
            h = max(1, round(480 * int(f["h"]) / int(f["w"])))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            h = 600
        flyer = (f'<a class="sl-flyer" href="{_e(f["url"])}" target="_blank" rel="noopener">'
                 f'<img src="{_e(f["thumb"])}" alt="Flyer for {_e(title)}" width="480" height="{h}" '
                 'decoding="async"></a>')
    head, theme = _head(f"{title} · {_plain(church.get('name'), 120)}", church, site, og)
    place = f'<div class="sl-place">{_e(view["place"])}</div>' if view["place"] else ""
    rows, open_n = _role_rows(view)
    if open_n:
        form = (f'<form class="sl-form" id="sl-form" novalidate>'
                f'<fieldset><legend class="sl-ask">How would you like to help?</legend>{rows}</fieldset>'
                '<label class="sl-field">Your name<input class="sl-input" name="name" autocomplete="name" '
                f'maxlength="{NAME_MAX}" required></label>'
                '<label class="sl-field">Phone or email<input class="sl-input" name="reach" '
                'autocomplete="email" maxlength="200" required></label>'
                '<div class="sl-hp" aria-hidden="true"><label>Leave this empty<input name="website" tabindex="-1" '
                'autocomplete="off"></label></div>'
                '<div class="sl-msg" role="alert"></div>'
                '<button class="sl-go" type="submit">Sign me up</button>'
                '<noscript><p class="sl-note">Turn on JavaScript to sign up, or ask the church.</p></noscript>'
                '</form>')
    else:
        form = (f'<div class="sl-form"><fieldset><legend class="sl-ask">How would you like to help?</legend>{rows}'
                '</fieldset><p class="sl-note">Everything is full just now. Ask the church if you would still '
                'like to help.</p></div>')
    script = SCRIPT % {"api": json.dumps(api_origin), "slug": json.dumps(slug), "code": json.dumps(code),
                       "when": json.dumps(view["when"]), "place": json.dumps(view["place"]),
                       "no_name": json.dumps(NO_NAME), "no_reach": json.dumps(NO_REACH)}
    script = script.replace("</", "<\\/")
    return (f'{head}<body><main class="sl-shell">{_church_line(church, theme)}'
            f'<h1 class="sl-title">{_e(title)}</h1><div class="sl-when">{_e(view["when"])}</div>{place}{flyer}'
            f"{form}{FOOT}</main><script>{script}</script></body></html>")


async def serve_page(biz_id: Any, slug: str, code_raw: Any, *, api_origin: str, headers: Dict[str, str]) -> HTMLResponse:
    """GET https://<church host>/e/<code> (public_site routes it here)."""
    church, view = await asyncio.to_thread(page_state, biz_id, code_raw)
    site = None
    if church is not None:
        from public_form_theme import SITE_SELECT
        got = await asyncio.to_thread(
            _rows, f"/business_sites?business_id=eq.{_q(church['id'])}&status=eq.published&select={SITE_SELECT}&limit=1")
        site = got[0] if got else None
    hdrs = {**headers, **PAGE_HEADERS}
    if view is None:
        return HTMLResponse(render_closed(church, site), status_code=404, media_type="text/html", headers=hdrs)
    return HTMLResponse(render_page(church, site, view, clean_code(code_raw) or "", api_origin=api_origin, slug=slug),
                        media_type="text/html", headers=hdrs)


# ─── signing up (public) ─────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_reach(raw: Any) -> Tuple[str, str]:
    """("email" | "phone", the normalized value), or a plain 400."""
    s = _plain(raw, 200)
    if not s:
        raise HTTPException(400, NO_REACH)
    if "@" in s:
        e = s.lower()
        if len(e) > 200 or not EMAIL_RE.match(e):
            raise HTTPException(400, BAD_EMAIL)
        return "email", e
    if re.search(r"[^0-9+()\-. ]", s):
        raise HTTPException(400, BAD_PHONE)
    digits = re.sub(r"\D", "", s)
    if s.startswith("+"):
        if not PHONE_DIGITS[0] + 1 <= len(digits) <= PHONE_DIGITS[1]:
            raise HTTPException(400, BAD_PHONE)
        return "phone", "+" + digits
    if len(digits) == 10:
        return "phone", "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "phone", "+" + digits
    raise HTTPException(400, BAD_PHONE)


def _public_key(biz: str, eid: str, email: str) -> str:
    """The public page's registration key for an email on an event
    (events_rsvp_router.public_event_rsvp)."""
    return hashlib.sha256(f"{biz}:{eid}:{email}".encode()).hexdigest()


def _church_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    sites = _rows(f"/business_sites?slug=eq.{_q(slug)}&order=updated_at.desc&limit=1&select=business_id,slug")
    if not sites:
        return None
    rows = _rows(f"/businesses?id=eq.{_q(sites[0]['business_id'])}&select=id,name,type,settings&limit=1")
    return rows[0] if rows else None


def signup(slug: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """The sign-up after the rate limit: checks, the write, and what the page
    and the email say. Raises the plain words."""
    name = _plain(body.get("name"), NAME_MAX)
    if not name:
        raise HTTPException(400, NO_NAME)
    kind, reach = clean_reach(body.get("reach"))
    role_id = _plain(body.get("role"), 80) or None
    code = clean_code(body.get("code"))
    if code is None:
        raise HTTPException(404, NOT_TAKING)
    church = _church_by_slug(_plain(slug, 120))
    if church is None:
        raise HTTPException(404, NOT_TAKING)
    biz = str(church["id"])
    import sample_church
    if sample_church.is_sample(biz) or not open_here(biz):
        raise HTTPException(404, NOT_TAKING)
    hit = find_by_code(biz, code)
    if hit is None:
        raise HTTPException(404, NOT_TAKING)
    entry, mod = hit
    eid = str(entry["id"])
    import events_rsvp_router as er
    sid = secrets.token_hex(8)
    key = _key(biz)

    def write(data: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
        # The event as it is now, through the same checks as the page.
        lk = link_of(data)
        if (lk is None or row.get("status") != "active"
                or not hmac.compare_digest(code_for(biz, eid, lk["n"], key), code)):
            raise HTTPException(404, NOT_TAKING)
        view = event_view(biz, {**row, "data": data}, mod)
        if view is None:
            raise HTTPException(404, NOT_TAKING)
        field = _signups_field(mod)
        signups = er.read_signups(data, field)
        label, role = "Coming", None
        if role_id:
            role = next((r for r in view["roles"] if r["id"] == role_id), None)
            if role is None:
                raise HTTPException(400, NO_ROLE)
            if role["kids"]:
                raise HTTPException(403, KIDS)
            if role["full"]:
                raise HTTPException(409, FULL if view["full"] else f"{role['label']} just filled up.")
            label = role["label"]
        elif view["blocks"]:
            raise HTTPException(409, TAKES_SIGNUPS)
        elif view["full"]:
            raise HTTPException(409, FULL)
        said = {"role": label, "when": view["when"], "place": view["place"], "title": view["title"]}
        keys = data.get("_registration_keys") if isinstance(data.get("_registration_keys"), dict) else {}
        if any(s.get("via") == "link" and s.get(kind) == reach and (s.get("status") or "yes") == "yes"
               for s in signups) or (kind == "email" and _public_key(biz, eid, reach) in keys):
            raise _Already(said)
        new = {"sid": sid, "name": name, "status": "yes", "via": "link", kind: reach, "at": _now().isoformat()}
        if role_id:
            new["role"] = role["raw"]
        data[field] = (data.get(field) if isinstance(data.get(field), list) else []) + [new]
        return said

    try:
        _, said, _ = _change(biz, eid, write)
    except _Already as a:
        return {"ok": True, **{k: a.said[k] for k in ("role", "when", "place")}, "emailed": False, "_mail": None}
    mail = None
    if kind == "email":
        mail = {"biz": biz, "church": _plain(church.get("name"), 120), "to": reach, "name": name, "said": said,
                "key": f"evlink-{eid}-{sid}"}
    _log(f"signed up biz={biz[:8]} entry={eid[:8]} via=link role={'yes' if role_id else 'no'}")
    return {"ok": True, **{k: said[k] for k in ("role", "when", "place")}, "emailed": mail is not None, "_mail": mail}


class _Already(Exception):
    """Already on the list: the same success, nothing written, no email."""

    def __init__(self, said: Dict[str, Any]):
        super().__init__("already")
        self.said = said


def email_words(m: Dict[str, Any]) -> Tuple[str, str]:
    s = m["said"]
    first = _plain(m.get("name"), NAME_MAX).split(" ")[0] or "Friend"
    line = " · ".join(x for x in (s["role"], s["when"], s["place"]) if x)
    church = m.get("church") or "The church"
    body = (f"<p>Hi {_e(first)},</p><p>You're on the list for <strong>{_e(s['title'])}</strong>.</p>"
            f"<p>{_e(line)}</p><p>If anything changes, {_e(church)} will be in touch.</p>")
    return f"You're on the list for {s['title']}", body


def _mail(m: Dict[str, Any]) -> None:
    """Through the church's own sender (church_event_signups._send_email:
    send_via_resend from the church's name, its suppression list, the sample
    church's refusal), once: the idempotency key is the sign-up's."""
    import church_event_signups as ces
    subject, body = email_words(m)
    ces._run(ces._send_email(m["biz"], m["to"], m["name"], subject, body, m["key"]))


@router.post("/public/event-link/{slug}")
async def public_signup(slug: str, body: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """Anonymous: one person signs up through an event's link."""
    # Rate limit FIRST, before any read or write: the public RSVP's own.
    import events_rsvp_router as er
    from rate_limit import trusted_client_ip
    if not er._check_rsvp_rate(trusted_client_ip(request)):
        raise HTTPException(429, "Too many tries. Please wait a minute and try again.")
    body = body if isinstance(body, dict) else {}
    if str(body.get("website") or "").strip():
        # The honeypot: the ordinary answer, nothing written or sent.
        return {"ok": True, "role": "", "when": "", "place": "", "emailed": False}
    out = await asyncio.to_thread(signup, slug, body)
    m = out.pop("_mail", None)
    if m:
        _mail(m)
    return out


# ─── the office ──────────────────────────────────────────────────────

def _office(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    import event_volunteers as evv
    me = evv._login(business_id, user)
    if not open_here(me["biz"]):
        raise HTTPException(404, "Not Found")
    return me


def _writer(me: Dict[str, Any]) -> None:
    import event_volunteers as evv
    evv._ask_gate(me)


def _entry(me: Dict[str, Any], entry_id: Any) -> Dict[str, Any]:
    import event_volunteers as evv
    import sunday_planning as sp
    eid = sp._uuid(entry_id, "event")
    return evv.event_entry(me["biz"], eid, sp._zone(me["biz"]))


def _sid(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if not SID_RE.fullmatch(s):
        raise HTTPException(404, GONE_SIGNUP)
    return s


def _slug(me: Dict[str, Any], make: bool) -> Optional[str]:
    rows = _rows(f"/business_sites?business_id=eq.{_q(me['biz'])}&order=updated_at.desc&select=slug&limit=1")
    if rows and rows[0].get("slug"):
        return str(rows[0]["slug"])
    if not make:
        return None
    church = _rows(f"/businesses?id=eq.{_q(me['biz'])}&select=id,name,type,settings&limit=1")
    if not church:
        return None
    from business_sites_helpers import ensure_business_site
    site, _ = ensure_business_site(church[0])
    return str(site.get("slug") or "") or None


def _module_of(me: Dict[str, Any], ent: Dict[str, Any]) -> Dict[str, Any]:
    rows = _rows(f"/custom_modules?id=eq.{_q(ent['module_id'])}&business_id=eq.{_q(me['biz'])}"
                 "&select=id,archetype_params,is_active&limit=1")
    if not rows:
        raise HTTPException(404, "That event isn't in Services & Events.")
    return rows[0]


def _maybe(biz: str, s: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Someone on Members with this phone or email: a hint for the office,
    never written."""
    try:
        import lead_identity
        c = lead_identity.find(biz, email=s.get("email"), phone=s.get("phone"), name=s.get("name"),
                               select="id,name,metadata")
    except Exception:  # noqa: BLE001 — a hint that can't be read is no hint
        return None
    if not c or (isinstance(c.get("metadata"), dict) and c["metadata"].get("merged_into")):
        return None
    return {"contact_id": str(c["id"]), "name": _plain(c.get("name"), 120) or "Someone"}


def link_signups(me: Dict[str, Any], ent: Dict[str, Any], mod: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The event's sign-ups by link, for the office. Phone and email only for
    a login that isn't a Viewer."""
    import events_rsvp_router as er
    labels = {str(r.get("id")): _plain(r.get("label"), 80) for r in ent["roles"]}
    reads = me["role"] != "viewer"
    hints = MAX_HINTS
    out = []
    for s in er.read_signups(ent["data"], _signups_field(mod)):
        if s.get("via") != "link" or not isinstance(s.get("sid"), str) or not SID_RE.fullmatch(s["sid"]):
            continue
        if (s.get("status") or "yes") != "yes":
            continue
        rid = str(s.get("role") or "")
        row: Dict[str, Any] = {"sid": s["sid"], "name": _plain(s.get("name"), NAME_MAX) or "Someone",
                               "role_id": rid or None, "role": labels.get(rid) or ("Coming" if not rid else "A role"),
                               "at": s.get("at") if isinstance(s.get("at"), str) else None,
                               "confirmed": s.get("confirmed") is True}
        if row["confirmed"] and s.get("contact_id"):
            row["contact_id"] = str(s["contact_id"])
        if reads:
            for k in ("phone", "email"):
                if isinstance(s.get(k), str):
                    row[k] = s[k]
            if not row["confirmed"] and hints > 0:
                hints -= 1
                hint = _maybe(me["biz"], s)
                if hint:
                    row["maybe"] = hint
        out.append(row)
    return out


def _link_out(me: Dict[str, Any], ent: Dict[str, Any], data: Dict[str, Any], slug: Optional[str],
              mod: Dict[str, Any]) -> Dict[str, Any]:
    import events_rsvp_router as er
    lk = link_of(data)
    url = None
    if lk and slug:
        try:
            url = link_url(slug, code_for(me["biz"], ent["entry_id"], lk["n"]))
        except RuntimeError:
            raise HTTPException(503, NOT_READY)
    vis = er.occasion_visibility(data)
    page = None
    if vis == "public" and slug:
        from business_sites_helpers import PUBLIC_DOMAIN
        page = f"https://{slug}.{PUBLIC_DOMAIN}/events?event={_q(ent['entry_id'])}"
    return {"enabled": True, "url": url, "made_at": lk["at"] if lk else None, "visibility": vis, "page_url": page,
            "can_change": me["role"] != "viewer",
            # Whether the link takes sign-ups now (the page's own rule).
            "taking": event_view(me["biz"], {"id": ent["entry_id"], "status": "active" if ent["active"] else "archived",
                                             "data": data}, mod) is not None}


def _ensure_key(biz: str) -> None:
    try:
        _key(biz)
    except RuntimeError:
        raise HTTPException(503, NOT_READY)


def _mint(me: Dict[str, Any], eid: str, *, renew: bool) -> Tuple[Dict[str, Any], Any]:
    def put(data: Dict[str, Any], row: Dict[str, Any]) -> bool:
        if not renew and link_of(data) is not None:
            return False                 # another office login made it first: keep theirs
        data["_link"] = new_link()
        return True
    data, _, rev = _change(me["biz"], eid, put)
    return data, rev


@router.get("/church/event-links/status")
def status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether the office shows sign-up links here, for this login."""
    import business_access
    import sunday_planning as sp
    biz = sp._uuid(business_id)
    business_access.assert_access(biz, user, "viewer")
    try:
        me = _office(biz, user)
    except HTTPException as e:
        if e.status_code in (403, 404):
            return {"enabled": False, "can_change": False}
        raise
    return {"enabled": True, "can_change": me["role"] != "viewer"}


@router.get("/church/event-links/{entry_id}")
def get_link(entry_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """The event's link (made the first time an office login that may change
    it asks), and its sign-ups by link."""
    me = _office(business_id, user)
    ent = _entry(me, entry_id)
    mod = _module_of(me, ent)
    _ensure_key(me["biz"])
    data, rev = ent["data"], None
    writer = me["role"] != "viewer"
    if link_of(data) is None and writer and ent["active"]:
        data, rev = _mint(me, ent["entry_id"], renew=False)
        ent = {**ent, "data": data}
    out = _link_out(me, ent, data, _slug(me, make=writer), mod)
    return {**out, "signups": link_signups(me, ent, mod), **({"updated_at": rev, "data": data} if rev else {})}


@router.post("/church/event-links/{entry_id}/new")
def renew(entry_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """A new link: the old one stops working at once."""
    body = body if isinstance(body, dict) else {}
    me = _office(body.get("business_id"), user)
    _writer(me)
    ent = _entry(me, entry_id)
    mod = _module_of(me, ent)
    _ensure_key(me["biz"])
    data, rev = _mint(me, ent["entry_id"], renew=True)
    _log(f"new link biz={me['biz'][:8]} entry={ent['entry_id'][:8]}")
    return {**_link_out(me, {**ent, "data": data}, data, _slug(me, make=True), mod), "data": data, "updated_at": rev}


def _contact(biz: str, cid: str) -> Dict[str, Any]:
    rows = _rows(f"/contacts?business_id=eq.{_q(biz)}&id=eq.{_q(cid)}&select=id,name,metadata,status&limit=1")
    if not rows:
        raise HTTPException(404, NOT_MEMBER)
    c = rows[0]
    if isinstance(c.get("metadata"), dict) and c["metadata"].get("merged_into"):
        raise HTTPException(409, "That record was merged into another. Pick them again from Members.")
    return c


def _confirm(me: Dict[str, Any], ent: Dict[str, Any], mod: Dict[str, Any], sid: str,
             contact: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    field = _signups_field(mod)

    def put(data: Dict[str, Any], row: Dict[str, Any]) -> None:
        signups = data.get(field) if isinstance(data.get(field), list) else []
        s = next((x for x in signups if isinstance(x, dict) and x.get("via") == "link" and x.get("sid") == sid), None)
        if s is None:
            raise HTTPException(404, GONE_SIGNUP)
        if s.get("confirmed") is True and str(s.get("contact_id") or "") != str(contact["id"]):
            raise HTTPException(409, f"That sign-up is already confirmed as {_plain(s.get('name'), 120) or 'someone'}.")
        if "typed_name" not in s:
            s["typed_name"] = _plain(s.get("name"), NAME_MAX)
        s.update({"contact_id": str(contact["id"]), "confirmed": True, "confirmed_by": me["uid"],
                  "confirmed_at": _now().isoformat(), "name": _plain(contact.get("name"), NAME_MAX) or s.get("name")})
    data, _, rev = _change(me["biz"], ent["entry_id"], put)
    return data, rev


def _office_answer(me: Dict[str, Any], ent: Dict[str, Any], mod: Dict[str, Any], data: Dict[str, Any], rev: Any):
    ent = {**ent, "data": data}
    return {"ok": True, "signups": link_signups(me, ent, mod), "data": data, "updated_at": rev}


@router.post("/church/event-links/{entry_id}/signups/{sid}/confirm")
def confirm(entry_id: str, sid: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """That's someone on Members: this church's person, and the sign-up's
    hours count from now on."""
    import sunday_planning as sp
    body = body if isinstance(body, dict) else {}
    me = _office(body.get("business_id"), user)
    _writer(me)
    ent = _entry(me, entry_id)
    mod = _module_of(me, ent)
    s = _sid(sid)
    contact = _contact(me["biz"], sp._uuid(body.get("contact_id"), "person"))
    data, rev = _confirm(me, ent, mod, s, contact)
    return _office_answer(me, ent, mod, data, rev)


@router.post("/church/event-links/{entry_id}/signups/{sid}/add")
def add_to_members(entry_id: str, sid: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Add them to Members (a guest who found the church at an event, through
    the roll's own add), then confirm the sign-up as them."""
    body = body if isinstance(body, dict) else {}
    me = _office(body.get("business_id"), user)
    _writer(me)
    import church_roll as cr
    import church_roll_edit as cre
    if (not cre.open_to(user) or me["role"] not in ("owner", "admin", "manager")
            or not cr._areas_ok(me["biz"], me["uid"], me["role"])):
        raise HTTPException(403, ROLL_ONLY)
    ent = _entry(me, entry_id)
    mod = _module_of(me, ent)
    s_id = _sid(sid)
    import events_rsvp_router as er
    s = next((x for x in er.read_signups(ent["data"], _signups_field(mod))
              if x.get("via") == "link" and x.get("sid") == s_id), None)
    if s is None:
        raise HTTPException(404, GONE_SIGNUP)
    if s.get("confirmed") is True:
        raise HTTPException(409, f"That sign-up is already confirmed as {_plain(s.get('name'), 120) or 'someone'}.")
    words = (_plain(s.get("name"), NAME_MAX) or "Guest").split(" ")
    person = {"first": words[0][:60], "last": " ".join(words[1:])[:60], "kind": "adult"}
    if isinstance(s.get("phone"), str):
        person["mobile"] = s["phone"]
    if isinstance(s.get("email"), str):
        person["email"] = s["email"]
    made = cre.add_people(me["biz"], {"people": [person], "status": "first_time", "found": "event"}, user)
    cre._forget(me["biz"])
    ids = made.get("ids") or []
    if not ids:
        raise HTTPException(503, "Nobody was added. Try again in a moment.")
    contact = _contact(me["biz"], str(ids[0]))
    data, rev = _confirm(me, ent, mod, s_id, contact)
    return {**_office_answer(me, ent, mod, data, rev), "contact_id": str(contact["id"])}


@router.delete("/church/event-links/{entry_id}/signups/{sid}")
def remove(entry_id: str, sid: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """Take a sign-up by link off the event."""
    me = _office(business_id, user)
    _writer(me)
    ent = _entry(me, entry_id)
    mod = _module_of(me, ent)
    s_id = _sid(sid)
    field = _signups_field(mod)

    def put(data: Dict[str, Any], row: Dict[str, Any]) -> None:
        signups = data.get(field) if isinstance(data.get(field), list) else []
        kept = [x for x in signups if not (isinstance(x, dict) and x.get("via") == "link" and x.get("sid") == s_id)]
        if len(kept) == len(signups):
            raise HTTPException(404, GONE_SIGNUP)
        data[field] = kept
    data, _, rev = _change(me["biz"], ent["entry_id"], put)
    return _office_answer(me, ent, mod, data, rev)

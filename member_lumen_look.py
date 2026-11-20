"""member_lumen_look.py — Light, Dark or Same as my phone, in the member app's new look.

Kevin, 2026-11-20: "the new look need to allow dark or light option ... in
settings giving the member option to have dark or light look." This reverses
the earlier rule that the new look (member_lumen, MEMBER_LUMEN) is always
white.

THE CHOICE. Me (the member's own page, opened from their picture at the top
right) has one control, Look: Light · Dark · Same as my phone.
  - The member's own choice wins.
  - Until they choose, the church's base decides (settings.member_portal.base,
    the base today's look already wears, black when the church never picked
    one): Black is Dark, any other base is Light (church_look).
  - Same as my phone follows the phone's own setting (prefers-color-scheme),
    in CSS: no script decides it, so nothing flashes.

WHERE IT'S KEPT. contacts.metadata.member_look = "light" | "dark" | "auto"
on the member's own record (no migration), written the way the member's
photo is (member_photos._set: the record's updated_at guards an office edit
made at the same moment; only the signed-in member's own row). Pages read it
from the record the session already reads (member_portal.contacts_for_email
and contacts_for_phone select look:metadata->member_look): no new read. That
record is kept 30 s per server copy (member_cache.PEOPLE_SECONDS), so saving
also sets a cookie on this phone, lm_look = "<look>.<unix time>.<whose>",
which wins for BRIDGE_SECONDS after the save; after that the record wins
again, so a change made on another phone reaches this one. The cookie names
whose choice it is (a short hash of their record's id), so someone else in
the household signing in on the same phone isn't handed it. The owner's
preview never writes as the member: there the cookie alone holds the choice,
on the owner's own browser.

ON THE PAGE. member_portal.serve decides once per request (decide(): no read,
the record and the cookies only) and keeps the answer for the page (CURRENT).
member_portal._shell puts it on <body>: lm-dark for Dark, lm-auto for Same
as my phone, nothing for Light, so the page arrives in its look; the phone's
bar (theme-color) matches it (two of them, by media, for Same as my phone).
The colours are member_lumen_ui's: one dark layer over the white page (the
near-black of the approved "Look 4: black base" board), written once and
used twice, under body.lm.lm-dark and, inside a prefers-color-scheme: dark
query, under body.lm.lm-auto (member_lumen_ui.dark). The one colour CSS
can't work out is the church's button colour on near-black: a church whose
colour is too deep for it gets a lifted one (dark_tokens), from the same
palette rules as today's black base. A member who chose Light, or who hasn't
chosen at a church whose base isn't Black, gets the page byte for byte as it
was (only Me changes: it carries the control).

THE READER'S MOON. The Bible reader and a devotional's day keep their moon
(night reading, member_lumen_bible.NIGHT_JS). The moon is the reader's own
switch on top of the look, kept on this phone in lm_night: "1" night, "0"
day, no cookie: the reader follows the look (Dark starts the reader dark,
Same as my phone follows the phone). Tapping the moon to what the look
would give anyway clears the cookie (the reader follows the look again);
anything else keeps it. Choosing a look on Me clears it: the newest choice
wins everywhere. The reader's dark stays its warm night (#100E0B), as on the
approved board; Watch and Live stay the cinema whatever the look.

Youth and Kids keep their own looks; the pages before sign-in keep today's.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from html import escape
from typing import Any, Dict, Mapping, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger("member_lumen_look")
router = APIRouter()

LOOKS = ("light", "dark", "auto")
LABELS = (("light", "Light"), ("dark", "Dark"), ("auto", "Same as my phone"))
KEY = "member_look"                 # contacts.metadata.member_look
COOKIE = "lm_look"
NIGHT_COOKIE = "lm_night"           # member_lumen_bible.NIGHT_COOKIE: the reader's moon
BRIDGE_SECONDS = 120                # the cookie wins this long after a save (the record is kept 30 s)
COOKIE_SECONDS = 31536000
# The phone's bar on a dark page: the new look's near-black, the reader's
# warm night (member_lumen_bible.NIGHT_BG), the cinema's black
# (member_lumen_motion.CINE_BG).
DARK_BG = "#0A0A0B"

# The page being drawn: {"look": light|dark|auto, "night": "1"|"0"|""} (the
# member's look, and the reader's moon on this phone). member_portal.serve
# sets it for a new-look page; anywhere else it reads Light.
CURRENT: contextvars.ContextVar[Optional[Dict[str, str]]] = contextvars.ContextVar("member_lumen_look", default=None)


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


# ─── which look ──────────────────────────────────────────────────────


def church_look(biz: Optional[Mapping[str, Any]]) -> str:
    """The look a member gets until they choose: the church's base (the one
    today's look wears; black when it never picked one) — Black is Dark,
    any other base is Light."""
    import member_app_ui as ui
    cfg = (((biz or {}).get("settings") or {}).get("member_portal") or {})
    base = cfg.get("base") if isinstance(cfg, dict) else None
    base = base if base in ui.BASES else ui.DEFAULT_BASE
    return "dark" if base == "black" else "light"


def stored(me: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The member's own choice from their record (the session's read selects
    it as `look`; a whole record carries it in metadata), or None."""
    if not me:
        return None
    v = me.get("look")
    if v is None and isinstance(me.get("metadata"), dict):
        v = me["metadata"].get(KEY)
    return v if v in LOOKS else None


def _whose(me: Optional[Mapping[str, Any]]) -> str:
    """Whose choice a cookie holds: a short hash of their record's id (not
    the id itself)."""
    import hashlib
    cid = str((me or {}).get("id") or "")
    return hashlib.sha256(cid.encode("utf-8")).hexdigest()[:12] if cid else ""


def cookie_value(look: str, me: Optional[Mapping[str, Any]], now: Optional[float] = None) -> str:
    return f"{look}.{int(now if now is not None else time.time())}.{_whose(me)}"


def from_cookie(raw: Any, me: Optional[Mapping[str, Any]]) -> Tuple[Optional[str], float]:
    """(look, when it was saved) from this phone's cookie, for this member
    only; (None, 0) for anything else."""
    parts = str(raw or "").split(".")
    if len(parts) != 3 or parts[0] not in LOOKS or not parts[1].isdigit():
        return None, 0.0
    if not parts[2] or parts[2] != _whose(me):
        return None, 0.0
    return parts[0], float(parts[1])


def resolve(biz: Optional[Mapping[str, Any]], me: Optional[Mapping[str, Any]], cookie: Any = "", *,
            preview: bool = False, now: Optional[float] = None) -> str:
    """The member's look: what they chose (the cookie for BRIDGE_SECONDS
    after saving on this phone, then their record), else the church's.
    The owner's preview keeps the choice in the cookie alone."""
    c_look, c_at = from_cookie(cookie, me)
    if preview:
        return c_look or stored(me) or church_look(biz)
    now = time.time() if now is None else now
    if c_look and 0 <= now - c_at <= BRIDGE_SECONDS:
        return c_look
    return stored(me) or c_look or church_look(biz)


def decide(request: Any, session: Optional[Mapping[str, Any]], biz: Optional[Mapping[str, Any]]) -> str:
    """resolve() for the page being drawn, kept for it (CURRENT), with the
    reader's moon on this phone. No read: the session's record and the
    request's cookies."""
    session = session or {}
    cookies = getattr(request, "cookies", None) or {}
    look = resolve(biz, session.get("me"), cookies.get(COOKIE) or "", preview=bool(session.get("preview")))
    night = str(cookies.get(NIGHT_COOKIE) or "")
    CURRENT.set({"look": look, "night": night if night in ("1", "0") else ""})
    return look


def here() -> str:
    """The member's look for the page being drawn (Light anywhere it wasn't
    decided)."""
    cur = CURRENT.get() or {}
    return cur.get("look") or "light"


def page_look(*, reader: bool = False, cine: bool = False) -> str:
    """How the page being drawn wears it: the cinema (Watch, Live) is always
    dark; the reader (the Bible's and a devotional's day) follows its moon
    when the member set it on this phone, else the look; every other page
    the look."""
    if cine:
        return "dark"
    cur = CURRENT.get() or {}
    if reader and cur.get("night") == "1":
        return "dark"
    if reader and cur.get("night") == "0":
        return "light"
    return cur.get("look") or "light"


def reader_night() -> Optional[bool]:
    """Whether the reader arrives at night (its moon pressed): True, False,
    or None for Same as my phone with no moon set (the phone decides, in
    CSS; the moon's script reads it)."""
    look = page_look(reader=True)
    return None if look == "auto" else look == "dark"


def body_class(look: str) -> str:
    return {"dark": "lm-dark", "auto": "lm-auto"}.get(look, "")


def theme_meta(look: str, day: str, night: str) -> str:
    """The phone's bar colour: the page's colour by day, `night` dark; both,
    by the phone's own setting, for Same as my phone."""
    if look == "auto":
        return (f'<meta name="theme-color" content="{_e(day)}" media="(prefers-color-scheme: light)">\n'
                f'<meta name="theme-color" content="{_e(night)}" media="(prefers-color-scheme: dark)">')
    return f'<meta name="theme-color" content="{_e(night if look == "dark" else day)}">'


def dark_tokens(biz: Mapping[str, Any], theme: Mapping[str, Any]) -> str:
    """The church's button colour on the dark page, when its own is too deep
    for near-black (the palette's rule for a dark base: lifted in its own
    hue to 2.2:1, with white or near-black words on it, whichever reads):
    a small <style> laid over the dark layer, for Dark and for Same as my
    phone at night (member_lumen_ui.dark). '' when the church's colour
    already works, which is most of them."""
    import member_app_ui as ui
    import member_lumen_ui as lm
    try:
        day = ui.palette(dict(biz), dict(theme))
        night = ui.palette(dict(biz), dict(theme), lumen_dark=True)
    except Exception:
        return ""
    fill, on = night["fill"], night["on_fill"]
    if (fill, on) == (day["fill"], day["on_fill"]):
        return ""
    rule = (f"body.lm.lm-dark{{--acc-fill:{fill};--mb-fill:{fill};--on-acc:{on};--mb-on-fill:{on};--accent-text:{on};"
            f"--acc-soft:{ui._rgba(fill, .18)};--mb-soft:{ui._rgba(fill, .18)};--mb-soft-line:{ui._rgba(fill, .4)};}}")
    return f"<style>{lm.dark(rule).strip()}</style>"


# ─── saving ──────────────────────────────────────────────────────────


def save(business_id: str, contact_id: str, look: str) -> bool:
    """The member's choice on their own record (contacts.metadata), guarded
    by updated_at so an office edit at the same moment isn't lost (as
    member_photos._set; a record with no updated_at is guarded by that).
    Whether it saved."""
    import sb_clients
    from urllib.parse import quote
    import member_portal_church as mpc
    if look not in LOOKS:
        return False
    q = lambda v: quote(str(v), safe="")  # noqa: E731
    for _ in range(3):
        me = mpc.load_me(business_id, contact_id)
        if not me:
            return False
        meta = dict(me.get("metadata") or {}) if isinstance(me.get("metadata"), dict) else {}
        if meta.get(KEY) == look:
            return True
        meta[KEY] = look
        guard = f"eq.{q(me['updated_at'])}" if me.get("updated_at") else "is.null"
        got = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{q(contact_id)}&business_id=eq.{q(business_id)}&updated_at={guard}",
            {"metadata": meta})
        if isinstance(got, list) and got:
            return True
    return False


def _cookies(resp, look: str, me: Optional[Mapping[str, Any]], secure: bool) -> None:
    resp.set_cookie(COOKIE, cookie_value(look, me), max_age=COOKIE_SECONDS, path="/my", httponly=True,
                    secure=secure, samesite="lax")
    # the newest choice wins everywhere: the reader's moon follows it again
    resp.delete_cookie(NIGHT_COOKIE, path="/my")


@router.post("/my/look", include_in_schema=False)
async def save_look(request: Request):
    """The member's Look (Me): `look` = light | dark | auto. Signed in and
    from the member's own page (member_portal_church._signed_in: the
    session and the same-origin check), the member's own record only. The
    owner's preview keeps it on their own browser. JSON for the page's
    script (Accept: application/json), else back to Me."""
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    wants = "application/json" in (request.headers.get("accept") or "")
    try:
        form = await request.form()
        look = str(form.get("look") or "")
    except Exception:
        look = ""

    def answer(ok: bool, err: str = "", status: int = 200):
        if wants:
            return JSONResponse({"ok": ok, **({"error": err} if err else {})}, status_code=status)
        if ok:
            # Me comes back in the look just chosen, at the control: that's the answer.
            from member_portal import _SECURE_HEADERS
            return RedirectResponse("/my/me#lm-look-h", status_code=303, headers=_SECURE_HEADERS)
        return mpc._back("/my" if err == "signed_out" else "/my/me", err=err)

    if look not in LOOKS:
        return answer(False, "error", 400)
    secure = request.url.scheme == "https" or (request.headers.get("x-forwarded-proto") or "") == "https"
    if unavailable == "preview":
        # The owner's preview never writes as the member: this browser only.
        import member_portal as mp
        sess = await asyncio.to_thread(mp._session_for, request, church)
        resp = answer(True)
        _cookies(resp, look, (sess or {}).get("me"), secure)
        return resp
    if unavailable:
        return answer(False, "error", 503)
    if not me:
        return answer(False, "signed_out", 401)
    if not mpc._allowed(church, me):
        return answer(False, "slow", 429)
    ok = await asyncio.to_thread(save, church["business"]["id"], str(me["id"]), look)
    resp = answer(ok, "" if ok else "error", 200 if ok else 503)
    if ok:
        _cookies(resp, look, me, secure)
    return resp


# ─── the control on Me ───────────────────────────────────────────────


# Picking a look turns the page at once (the body's class and the phone's
# bar) and saves it in the background; if it doesn't save, the page turns
# back and says so. Without script the form posts and Me comes back in the
# new look.
_JS = r"""<script>(function(){var f=document.getElementById('lm-lookf');if(!f)return;
var B=document.body,say=document.getElementById('lm-look-say'),day=f.getAttribute('data-day'),night=f.getAttribute('data-night');
function bar(v){document.querySelectorAll('meta[name="theme-color"]').forEach(function(m){m.remove();});
 function add(c,q){var m=document.createElement('meta');m.name='theme-color';m.content=c;if(q)m.media=q;document.head.appendChild(m);}
 if(v==='auto'){add(day,'(prefers-color-scheme: light)');add(night,'(prefers-color-scheme: dark)');}else{add(v==='dark'?night:day);}}
function turn(v){B.classList.toggle('lm-dark',v==='dark');B.classList.toggle('lm-auto',v==='auto');bar(v);}
var was=(f.querySelector('input:checked')||{}).value||'light';
f.addEventListener('change',function(e){var v=e.target&&e.target.value;if(!v||v===was)return;var back=was;was=v;turn(v);
 if(say)say.textContent='';
 var d=new FormData(f);fetch(f.action,{method:'POST',body:d,credentials:'same-origin',headers:{'Accept':'application/json'}})
 .then(function(r){return r.json().catch(function(){return{};});})
 .then(function(j){if(j&&j.ok){if(say)say.textContent='Saved';return;}throw 0;})
 .catch(function(){was=back;turn(back);var i=f.querySelector('input[value="'+back+'"]');if(i)i.checked=true;
  if(say)say.textContent='That didn’t save. Try again in a moment.';});});
})();</script>"""


def control(look: str, day: str) -> str:
    """Me's Look: Light · Dark · Same as my phone, `look` checked (the look
    the member has now: their choice, else the church's). `day` is the
    page's own colour (the phone's bar by day). Radios in one group (the
    arrow keys move between them), a Save button without script."""
    look = look if look in LOOKS else "light"
    opts = "".join(
        f'<label class="lm-segi"><input type="radio" name="look" value="{k}"{" checked" if k == look else ""}>'
        f'<span>{_e(label)}</span></label>' for k, label in LABELS)
    return (f'<section class="lm-look" aria-labelledby="lm-look-h">'
            f'<div class="lm-lookhd"><h2 class="lm-lookt" id="lm-look-h">Look</h2>'
            f'<span class="lm-looksay" id="lm-look-say" role="status" aria-live="polite"></span></div>'
            f'<form class="lm-lookf" id="lm-lookf" method="post" action="/my/look" data-day="{_e(day)}" '
            f'data-night="{DARK_BG}"><div class="lm-seg3" role="radiogroup" aria-labelledby="lm-look-h">{opts}</div>'
            f'<noscript><button class="lm-txtbtn" type="submit">Save</button></noscript></form></section>')


def script() -> str:
    return _JS

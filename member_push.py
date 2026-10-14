"""
member_push.py — notifications on members' phones (the installed member app).

Subsplash exit plan, open decision 1. Kevin, 2026-10-14: yes. The plan's
rule: "Members can turn each kind off, and nothing goes out on the
church's behalf without the church's switch."

Three layers decide whether a note reaches a phone:
  1. The church's switch, per kind:
     settings.member_portal.notifications = {kind: true}. Every kind is
     off until the church turns it on (Settings → Member page). Staff
     push keeps its own settings.notifications namespace.
  2. The member's own choice, per kind (member_push_prefs.off), on
     /my/notifications.
  3. A device the member turned on (member_push_subscriptions). Web
     Push needs a tap: requestPermission only runs from a button. On an
     iPhone it only works once the app is on the home screen.

Kept apart from the staff table push_subscriptions, so a staff send
(morning brief, send_to_business) can never reach a member. The VAPID
keys and the sending code are shared (push_notifications._send_one).

What goes on a lock screen is chosen here, never by the caller's raw
text. A message or a prayer note says that something happened, not
what was written: a teen's phone, a shared tablet.

Endpoints (member side; the session decides who, never the body):
  POST /my/push/subscribe     {subscription}   this device, on
  POST /my/push/unsubscribe   {endpoint}       this device, off
  POST /my/notifications      form             my kinds on/off
  GET  /my/notifications                       (member_portal.serve)
Staff side:
  POST /member-portal/{business_id}/announce {title, body, url?}
       manager+, needs the church's "announcements" switch, at most
       DAILY_ANNOUNCEMENTS a day, logged in member_push_sends.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("member_push")
router = APIRouter(tags=["member-portal"])

# (key, what the church switches on, what a member sees next to the box)
KINDS = (
    ("announcements", "News from the church", "Notes the church sends to everyone"),
    ("live", "Live now", "When the service starts streaming"),
    ("messages", "New messages", "When someone writes to you or a group you're in"),
    ("sermons", "New sermons", "When a new message is posted"),
    ("events", "Event reminders", "The day before something you said you'd come to"),
    ("prayer", "Prayer", "When the church has prayed for your request"),
)
KIND_KEYS = tuple(k for k, _, _ in KINDS)
DAILY_ANNOUNCEMENTS = 3
TITLE_MAX, BODY_MAX = 60, 180
_TABLE = "member_push_subscriptions"


# ─── the church's switch ─────────────────────────────────────────────

def church_kinds(settings: Optional[Dict[str, Any]]) -> Set[str]:
    cfg = ((settings or {}).get("member_portal") or {}).get("notifications") or {}
    if not isinstance(cfg, dict):
        return set()
    return {k for k in KIND_KEYS if cfg.get(k) is True}


def clean_switches(raw: Any) -> Dict[str, bool]:
    """The owner's PATCH: {kind: bool}, known kinds only."""
    if not isinstance(raw, dict):
        raise HTTPException(400, "notifications must be {kind: true/false}")
    out: Dict[str, bool] = {}
    for k, v in raw.items():
        if k not in KIND_KEYS:
            raise HTTPException(400, f"Unknown notification kind: {k}")
        if not isinstance(v, bool):
            raise HTTPException(400, f"{k} must be true or false")
        out[k] = v
    return out


def ready() -> bool:
    import push_notifications
    return push_notifications.push_enabled()


def vapid_public() -> str:
    import push_notifications
    return push_notifications.VAPID_PUBLIC_KEY if ready() else ""


# ─── a member's devices and choices ──────────────────────────────────

_ENDPOINT_RE = re.compile(r"^https://[^\s]{10,2000}$")


def valid_subscription(sub: Any) -> Optional[Dict[str, Any]]:
    """The PushSubscription JSON a browser hands over, or None."""
    if not isinstance(sub, dict):
        return None
    endpoint = sub.get("endpoint")
    keys = sub.get("keys")
    if not isinstance(endpoint, str) or not _ENDPOINT_RE.match(endpoint):
        return None
    if not isinstance(keys, dict) or not all(
            isinstance(keys.get(k), str) and 10 <= len(keys[k]) <= 200 for k in ("p256dh", "auth")):
        return None
    return {"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}


def subscribe(business_id: str, contact_id: str, sub: Dict[str, Any], user_agent: str = "") -> bool:
    rows = sb_clients.sb_post_as_service(
        f"/{_TABLE}?on_conflict=endpoint",
        {"business_id": business_id, "contact_id": contact_id, "endpoint": sub["endpoint"],
         "subscription": sub, "user_agent": (user_agent or "")[:300]},
        prefer="resolution=merge-duplicates,return=representation")
    return bool(rows)


def unsubscribe(business_id: str, endpoint: str) -> None:
    if endpoint:
        sb_clients.sb_delete_as_service(
            f"/{_TABLE}?business_id=eq.{business_id}&endpoint=eq.{quote(endpoint, safe='')}")


def turned_off(business_id: str, contact_id: str) -> Optional[Set[str]]:
    rows = sb_clients.sb_get_as_service(
        f"/member_push_prefs?business_id=eq.{business_id}&contact_id=eq.{contact_id}&select=off&limit=1")
    if rows is None:
        return None
    return set((rows[0].get("off") or []) if rows else [])


def save_turned_off(business_id: str, contact_id: str, off: Iterable[str]) -> bool:
    rows = sb_clients.sb_post_as_service(
        "/member_push_prefs?on_conflict=business_id,contact_id",
        {"business_id": business_id, "contact_id": contact_id,
         "off": sorted(k for k in set(off) if k in KIND_KEYS),
         "updated_at": datetime.now(timezone.utc).isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    return bool(rows)


def device_count(business_id: str, contact_id: Optional[str] = None) -> int:
    q = f"/{_TABLE}?business_id=eq.{business_id}&select=id&limit=5000"
    if contact_id:
        q += f"&contact_id=eq.{contact_id}"
    return len(sb_clients.sb_get_as_service(q) or [])


# ─── sending ─────────────────────────────────────────────────────────

def _safe_url(url: Optional[str]) -> str:
    u = str(url or "/my")
    return u if re.match(r"^/my(?:[/?#][^\s]*)?$", u) else "/my"


def send(business: Dict[str, Any], kind: str, *, title: str, body: str = "",
         url: str = "/my", contact_ids: Optional[Iterable[str]] = None,
         ref_id: Optional[str] = None, sent_by: Optional[str] = None) -> int:
    """Send one note of `kind` to the church's members (or to
    `contact_ids`). Returns how many phones it reached. Quietly 0 when
    push isn't set up, the church hasn't switched this kind on, or `ref_id`
    was already sent. Never raises: a notification is never worth failing
    the thing it's about."""
    try:
        return _send(business, kind, title=title, body=body, url=url,
                     contact_ids=contact_ids, ref_id=ref_id, sent_by=sent_by)
    except Exception:
        logger.warning("member push send failed", exc_info=True)
        return 0


def _send(business, kind, *, title, body, url, contact_ids, ref_id, sent_by) -> int:
    import push_notifications as pn
    biz_id = str(business.get("id") or "")
    if kind not in KIND_KEYS or not biz_id or not ready():
        return 0
    if kind not in church_kinds(business.get("settings")):
        return 0
    title = " ".join(str(title or "").split())[:TITLE_MAX] or (business.get("name") or "Your church")
    body = " ".join(str(body or "").split())[:BODY_MAX]
    url = _safe_url(url)
    log_id = None
    if ref_id:
        # Claim first: a second sweep or a double press sends nothing.
        claimed = sb_clients.sb_post_as_service(
            "/member_push_sends?on_conflict=business_id,kind,ref_id",
            {"business_id": biz_id, "kind": kind, "ref_id": str(ref_id)[:200], "title": title,
             "body": body, "url": url, "sent_by": sent_by},
            prefer="resolution=ignore-duplicates,return=representation")
        if not claimed:
            return 0
        log_id = claimed[0].get("id")
    q = f"/{_TABLE}?business_id=eq.{biz_id}&select=id,contact_id,endpoint,subscription&limit=5000"
    subs = sb_clients.sb_get_as_service(q) or []
    if contact_ids is not None:
        wanted = {str(c) for c in contact_ids}
        subs = [s for s in subs if str(s.get("contact_id")) in wanted]
    if not subs:
        return _logged(log_id, 0)
    people = sorted({str(s["contact_id"]) for s in subs})
    off_rows = []
    for i in range(0, len(people), 150):
        off_rows += sb_clients.sb_get_as_service(
            f"/member_push_prefs?business_id=eq.{biz_id}&contact_id=in.({','.join(people[i:i + 150])})"
            f"&select=contact_id,off") or []
    muted = {str(r["contact_id"]) for r in off_rows if kind in (r.get("off") or [])}
    payload = {"title": title, "body": body, "url": url, "tag": f"{kind}-{ref_id or ''}"[:60]}
    reached = 0
    for s in subs:
        if str(s["contact_id"]) in muted:
            continue
        if pn._send_one(s, payload, table=_TABLE):
            reached += 1
    return _logged(log_id, reached)


def _logged(log_id: Optional[str], reached: int) -> int:
    if log_id:
        sb_clients.sb_patch_as_service(f"/member_push_sends?id=eq.{log_id}", {"recipients": reached})
    return reached


# ─── member endpoints ────────────────────────────────────────────────

async def _member(request: Request):
    from member_portal_church import _signed_in, _allowed
    church, me, unavailable = await _signed_in(request)
    if unavailable == "preview":
        return church, None, JSONResponse({"ok": False, "error": "preview"}, status_code=403)
    if unavailable:
        return church, None, JSONResponse({"ok": False, "error": "unavailable"}, status_code=503)
    if not me:
        return church, None, JSONResponse({"ok": False, "error": "signed_out"}, status_code=401)
    if not _allowed(church, me):
        return church, None, JSONResponse({"ok": False, "error": "slow"}, status_code=429)
    return church, me, None


@router.post("/my/push/subscribe", include_in_schema=False)
async def my_push_subscribe(request: Request):
    import asyncio
    church, me, err = await _member(request)
    if err:
        return err
    if not ready() or not church_kinds(church["business"].get("settings")):
        return JSONResponse({"ok": False, "error": "off"}, status_code=409)
    try:
        body = await request.json()
    except Exception:
        body = {}
    sub = valid_subscription((body or {}).get("subscription"))
    if not sub:
        return JSONResponse({"ok": False, "error": "bad_subscription"}, status_code=400)
    ok = await asyncio.to_thread(subscribe, church["business"]["id"], me["id"], sub,
                                 request.headers.get("user-agent") or "")
    return JSONResponse({"ok": ok}, status_code=200 if ok else 503)


@router.post("/my/push/unsubscribe", include_in_schema=False)
async def my_push_unsubscribe(request: Request):
    import asyncio
    church, me, err = await _member(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    endpoint = str((body or {}).get("endpoint") or "")
    if not _ENDPOINT_RE.match(endpoint):
        return JSONResponse({"ok": False, "error": "bad_endpoint"}, status_code=400)
    await asyncio.to_thread(unsubscribe, church["business"]["id"], endpoint)
    return JSONResponse({"ok": True})


@router.post("/my/notifications", include_in_schema=False)
async def my_notifications_save(request: Request):
    import asyncio
    from member_portal_church import _back, _signed_in, _allowed
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _back("/my/notifications", err="preview" if unavailable == "preview" else "error")
    if not me:
        return _back("/my")
    if not _allowed(church, me):
        return _back("/my/notifications", err="slow")
    form = await request.form()
    offered = church_kinds(church["business"].get("settings"))
    off = {k for k in offered if str(form.get(f"k_{k}") or "") != "on"}
    ok = await asyncio.to_thread(save_turned_off, church["business"]["id"], me["id"], off)
    return _back("/my/notifications", **({"done": "notifications"} if ok else {"err": "error"}))


def render_page(biz: Dict[str, Any], site: Optional[Dict[str, Any]], request: Request,
                me: Dict[str, Any], off: Optional[Set[str]]) -> str:
    from html import escape
    from member_portal import _shell
    offered = [k for k in KINDS if k[0] in church_kinds(biz.get("settings"))]
    flash = ""
    q = request.query_params
    if q.get("done") == "notifications":
        flash = '<p class="mp-ok" role="status">Saved.</p>'
    elif q.get("err"):
        flash = '<p class="mp-err" role="alert">That didn&#x27;t save. Please try again.</p>'
    if not offered or not ready():
        body = ('<section class="mp-card"><p>Your church hasn&#x27;t turned on notifications yet.</p>'
                '<p><a href="/my/me">Back to Me</a></p></section>')
        return _shell(biz, site, "Notifications", body, tab="me", who=me)
    off = off or set()
    boxes = "".join(
        f'<label class="mp-check" style="display:flex;gap:10px;align-items:flex-start;min-height:44px;margin:8px 0">'
        f'<input type="checkbox" name="k_{k}" {"" if k in off else "checked"} style="width:22px;height:22px;margin-top:2px">'
        f'<span><strong>{escape(label)}</strong><br><span class="mp-muted">{escape(hint)}</span></span></label>'
        for k, label, hint in offered)
    key = escape(vapid_public(), quote=True)
    return _shell(biz, site, "Notifications", f"""
{flash}
<section class="mp-card" aria-labelledby="np-dev">
  <h2 id="np-dev" class="mp-sect" style="margin-top:0">This phone</h2>
  <p class="mp-muted" id="np-state">Checking…</p>
  <p class="mp-muted" id="np-ios" hidden>On an iPhone, first put the app on your home screen
  (Share, then Add to Home Screen), open it from there, then come back here.</p>
  <button class="mp-go" type="button" id="np-on" hidden>Turn on notifications</button>
  <button class="mp-link" type="button" id="np-off" hidden>Turn off on this phone</button>
</section>
<form class="mp-card" method="post" action="/my/notifications" aria-labelledby="np-kinds">
  <h2 id="np-kinds" class="mp-sect" style="margin-top:0">What to tell me about</h2>
  {boxes}
  <button class="mp-go" type="submit">Save</button>
</form>
<p><a href="/my/me">Back to Me</a></p>
<script>(function(){{
  var KEY='{key}', st=document.getElementById('np-state'), on=document.getElementById('np-on'),
      off=document.getElementById('np-off'), ios=document.getElementById('np-ios');
  var standalone=window.matchMedia('(display-mode: standalone)').matches||window.navigator.standalone===true;
  var iphone=/iphone|ipad|ipod/i.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  function b64(s){{s=s.replace(/-/g,'+').replace(/_/g,'/');while(s.length%4)s+='=';var r=atob(s),a=new Uint8Array(r.length);for(var i=0;i<r.length;i++)a[i]=r.charCodeAt(i);return a;}}
  function post(u,d){{return fetch(u,{{method:'POST',headers:{{'Content-Type':'application/json'}},credentials:'same-origin',body:JSON.stringify(d)}});}}
  if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window)){{
    if(iphone&&!standalone){{st.textContent='';ios.hidden=false;return;}}
    st.textContent='This browser can\\'t show notifications.'; return;
  }}
  navigator.serviceWorker.register('/my/sw.js',{{scope:'/my'}}).then(function(){{return navigator.serviceWorker.ready;}}).then(function(reg){{
    function show(sub){{
      if(sub){{st.textContent='Notifications are on for this phone.';on.hidden=true;off.hidden=false;}}
      else if(Notification.permission==='denied'){{st.textContent='Notifications are blocked for this site in your phone\\'s settings.';on.hidden=true;off.hidden=true;}}
      else{{st.textContent='Notifications are off on this phone.';on.hidden=false;off.hidden=true;}}
    }}
    reg.pushManager.getSubscription().then(show);
    on.addEventListener('click',function(){{
      on.disabled=true;
      Notification.requestPermission().then(function(p){{
        if(p!=='granted'){{on.disabled=false;return show(null);}}
        return reg.pushManager.subscribe({{userVisibleOnly:true,applicationServerKey:b64(KEY)}}).then(function(sub){{
          return post('/my/push/subscribe',{{subscription:sub.toJSON()}}).then(function(r){{
            on.disabled=false; if(!r.ok){{st.textContent='That didn\\'t work. Please try again.';return;}} show(sub);}});
        }});
      }}).catch(function(){{on.disabled=false;st.textContent='That didn\\'t work. Please try again.';}});
    }});
    off.addEventListener('click',function(){{
      reg.pushManager.getSubscription().then(function(sub){{
        if(!sub) return show(null);
        var ep=sub.endpoint; return sub.unsubscribe().then(function(){{return post('/my/push/unsubscribe',{{endpoint:ep}});}}).then(function(){{show(null);}});
      }});
    }});
  }}).catch(function(){{st.textContent='This browser can\\'t show notifications.';}});
}})();</script>""", tab="me", who=me)


def home_card(biz: Dict[str, Any]) -> str:
    """Home's nudge: shown only where it can work and isn't on yet."""
    if not ready() or not church_kinds(biz.get("settings")):
        return ""
    return """
<section class="mp-card" id="np-card" hidden>
  <h2 class="mp-sect" style="margin-top:0">Get notified</h2>
  <p class="mp-muted">Hear when the service goes live and when the church sends news.</p>
  <a class="mp-go" href="/my/notifications">Turn on notifications</a>
  <button class="mp-link" type="button" id="np-card-no">Not now</button>
</section>
<script>(function(){
  var c=document.getElementById('np-card'); if(!c) return;
  var no=false; try{no=localStorage.getItem('np-card-no')==='1';}catch(e){}
  if(no||!('Notification' in window)||!('PushManager' in window)||Notification.permission!=='default') return;
  c.hidden=false;
  document.getElementById('np-card-no').addEventListener('click',function(){
    c.hidden=true; try{localStorage.setItem('np-card-no','1');}catch(e){}
  });
})();</script>"""


# ─── staff: an announcement ──────────────────────────────────────────

@router.post("/member-portal/{business_id}/announce")
def announce(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Manager and up. Body: { title, body, url? }. Returns { ok, reached }."""
    import business_access
    business_access.assert_access(business_id, user, "manager")
    body = body or {}
    title = " ".join(str(body.get("title") or "").split())
    text = " ".join(str(body.get("body") or "").split())
    if not title:
        raise HTTPException(400, "Give the note a title.")
    if len(title) > TITLE_MAX or len(text) > BODY_MAX:
        raise HTTPException(400, f"Keep it short: a title up to {TITLE_MAX} characters, "
                                 f"a line up to {BODY_MAX}.")
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    biz = rows[0]
    if not ready():
        raise HTTPException(503, "Notifications aren't set up on this server yet.")
    if "announcements" not in church_kinds(biz.get("settings")):
        raise HTTPException(409, "Turn on News from the church in Settings, Member page, first.")
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = sb_clients.sb_get_as_service(
        f"/member_push_sends?business_id=eq.{business_id}&kind=eq.announcements"
        f"&created_at=gte.{quote(since, safe='')}&select=id&limit=10")
    if recent is None:
        raise HTTPException(503, "Couldn't check today's notes. Please try again.")
    if len(recent) >= DAILY_ANNOUNCEMENTS:
        raise HTTPException(429, f"That's {DAILY_ANNOUNCEMENTS} notes in a day. Try again tomorrow.")
    import uuid
    reached = send(biz, "announcements", title=title, body=text, url=_safe_url(body.get("url")),
                   ref_id=str(uuid.uuid4()), sent_by=str(user.id))
    return {"ok": True, "reached": reached}

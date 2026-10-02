"""
member_portal_group_live.py — live group meetings in the member app.

Kevin's decisions (2026-09-29): a group's leader starts a video meeting
for the group from the member app — Meeting (everyone can be on camera)
or Broadcast (only hosts are). The church decides who may host
(group_members.can_host_live, on leaders). A YOUTH group needs two
approved adults: the meeting waits until a second approved host joins,
and no one else can come in before that. Joining counts as group
attendance for the day (the church's own date). Nothing is recorded.
Video runs on the same LiveKit project as Academy classes
(academy_live_router.settings/provider).

  POST /my/groups/live/start        {group_id, mode}   — an approved host
  GET  /my/groups/live/<sid>        the meeting page   (through member_portal.serve)
  POST /my/groups/live/<sid>/token  a 60-second join token for this member
  POST /my/groups/live/<sid>/end    an approved host ends it for everyone

The owner's preview never starts, joins or ends anything.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import sb_clients

router = APIRouter(tags=["member-portal"])

LIVEKIT_JS = "https://cdn.jsdelivr.net/npm/livekit-client@2.22.3/dist/livekit-client.umd.js"
# The exact file the app itself ships (npm livekit-client 2.22.3), so a
# changed copy on the CDN is refused by the browser.
LIVEKIT_SRI = "sha384-G/xxtkVytOx/ia9Q8MXxM+V0ohsaY1fZAgVP3iSGTPz4wJ0s3+ulJNKXh/gnzEDZ"
MAX_PEOPLE = 50
TOKEN_TTL = 60


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── reads ───────────────────────────────────────────────────────────


def membership(business_id: str, group_id: str, contact_id: str):
    """This person's row in the group: a dict, False when they aren't in
    it, None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/group_members?group_id=eq.{_q(group_id)}&contact_id=eq.{_q(contact_id)}&business_id=eq.{_q(business_id)}"
        f"&select=role,can_host_live&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else False


def is_host(m: Any) -> bool:
    """An approved adult: a leader the church allowed to host."""
    return bool(m) and m.get("role") == "leader" and bool(m.get("can_host_live"))


def group(business_id: str, group_id: str):
    rows = sb_clients.sb_get_as_service(
        f"/groups?id=eq.{_q(group_id)}&business_id=eq.{_q(business_id)}&select=id,name,youth,active&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else False


def session(business_id: str, sid: str):
    rows = sb_clients.sb_get_as_service(
        f"/group_live_sessions?id=eq.{_q(sid)}&business_id=eq.{_q(business_id)}"
        f"&select=id,group_id,mode,status,room_name,started_by,second_adult,started_at&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else False


def open_sessions(business_id: str, group_ids) -> Optional[Dict[str, Dict[str, Any]]]:
    """{group_id: its open meeting} for these groups, or None on a failed read."""
    ids = [str(g) for g in group_ids]
    if not ids:
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/group_live_sessions?business_id=eq.{_q(business_id)}&group_id=in.({','.join(ids)})"
        f"&status=in.(waiting,live)&select=id,group_id,mode,status&limit=200")
    if not isinstance(rows, list):
        return None
    return {str(r["group_id"]): r for r in rows}


# ─── LiveKit ─────────────────────────────────────────────────────────


def video_ready() -> bool:
    import academy_live_router as alr
    url, key, secret = alr.settings()
    return url.startswith("wss://") and bool(key) and bool(secret)


def mint(room: str, identity: str, name: str, publish: bool, host: bool) -> Dict[str, Any]:
    """A 60-second join token. `identity` is "c_<contact id>" for a member,
    "staff_<user id>" for the church team (group_live_router)."""
    import academy_live_router as alr
    from livekit import api
    url, key, secret = alr.settings()
    sources = ["camera", "microphone"] + (["screen_share", "screen_share_audio"] if host else []) if publish else []
    token = (api.AccessToken(key, secret).with_identity(identity).with_name(name)
             .with_ttl(timedelta(seconds=TOKEN_TTL)).with_metadata(json.dumps({"host": host}))
             .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=publish, can_subscribe=True,
                                          can_publish_data=False, can_publish_sources=sources,
                                          can_update_own_metadata=False)).to_jwt())
    return {"server_url": url, "token": token}


async def create_room(room: str) -> None:
    import academy_live_router as alr
    from livekit import api
    async with alr.provider() as live:
        await live.room.create_room(api.CreateRoomRequest(
            name=room, max_participants=MAX_PEOPLE, empty_timeout=600, departure_timeout=120))


async def room_open(room: str) -> bool:
    import academy_live_router as alr
    from livekit import api
    async with alr.provider() as live:
        res = await live.room.list_rooms(api.ListRoomsRequest(names=[room]))
    return any(r.name == room for r in res.rooms)


async def close_room(room: str) -> None:
    import academy_live_router as alr
    async with alr.provider() as live:
        await alr.delete_room(live.room, room)


# ─── attendance ──────────────────────────────────────────────────────


def count_attendance(biz: Dict[str, Any], group_id: str, contact_id: str) -> bool:
    """Today's (the church's today) meeting row for the group, and this
    person on it — once."""
    from sms_alerts import _business_tz
    day = datetime.now(_business_tz(biz)).date().isoformat()
    b = str(biz["id"])
    rows = sb_clients.sb_post_as_service(
        "/group_meetings?on_conflict=group_id,met_on",
        {"business_id": b, "group_id": group_id, "met_on": day},
        prefer="return=representation,resolution=ignore-duplicates")
    if rows is None:
        return False
    meet = rows[0] if rows else None
    if not meet:
        found = sb_clients.sb_get_as_service(
            f"/group_meetings?group_id=eq.{_q(group_id)}&met_on=eq.{_q(day)}&business_id=eq.{_q(b)}&select=id&limit=1")
        if not isinstance(found, list) or not found:
            return False
        meet = found[0]
    done = sb_clients.sb_post_as_service(
        "/group_meeting_attendance?on_conflict=meeting_id,contact_id",
        {"meeting_id": meet["id"], "contact_id": contact_id, "business_id": b},
        prefer="return=representation,resolution=ignore-duplicates")
    return done is not None


# ─── the page ────────────────────────────────────────────────────────


def render_meeting(biz, site, me: Dict[str, Any], s, g, m) -> Tuple[str, int]:
    """(html, status) for /my/groups/live/<sid>."""
    import member_app_ui as ui
    from member_portal import _e, _shell
    back = f'<a class="mb-back" href="/my/groups">{ui.icon("back", 16)}Groups</a>'
    if s is None or g is None or m is None:
        return _shell(biz, site, "Group meeting", back + '<p class="mp-err" role="alert">The meeting couldn\'t load just now. '
                      'Please try again in a moment.</p>', tab="groups", who=me), 503
    if not s or not g or not m:
        return _shell(biz, site, "Group meeting", back + '<div class="mp-card"><h1>This meeting isn\'t for you</h1>'
                      '<p class="mp-muted">Group meetings are for the people in that group.</p></div>',
                      tab="groups", who=me), 404
    if s["status"] == "ended":
        return _shell(biz, site, "Group meeting", back + f'<div class="mp-card"><h1>{_e(g["name"])}</h1>'
                      '<p class="mp-muted">This meeting has ended.</p></div>', tab="groups", who=me), 200
    host = is_host(m)
    if s["status"] == "waiting" and not host:
        refresh = '<meta http-equiv="refresh" content="15">'
        return _shell(biz, site, "Group meeting", refresh + back + f"""<div class="mp-card mb-wait">
<span class="mb-live-badge" style="background:var(--mb-surface-2);color:var(--text-secondary)">Waiting</span>
<h1 style="margin:10px 0 6px">{_e(g['name'])}</h1>
<p class="mp-muted">This group's meetings start once two approved adult leaders are here. It opens on its own as soon as they are.</p></div>""",
                      tab="groups", who=me), 200
    note = ("You're the first leader here. Members can come in once a second approved adult leader joins."
            if s["status"] == "waiting" else
            ("Only leaders are on camera in this meeting." if s["mode"] == "broadcast" and not host else ""))
    end = (f'<form method="post" action="/my/groups/live/{_e(s["id"])}/end" class="mb-end">'
           '<button class="mp-go mp-go-2" type="submit">End meeting for everyone</button></form>' if host else "")
    body = f"""{back}
<div class="mb-live-head"><span class="mb-live-badge"><span class="mb-live-dot" aria-hidden="true"></span>{'Waiting' if s['status'] == 'waiting' else 'Live'}</span>
  <h1 style="margin:6px 0 0">{_e(g['name'])}</h1></div>
{f'<p class="mp-muted" style="margin-top:6px">{_e(note)}</p>' if note else ''}
<div class="mb-meet" id="mb-meet" data-sid="{_e(s['id'])}" aria-live="polite">
  <p class="mp-muted" id="mb-meet-msg">Connecting…</p>
  <div class="mb-tiles" id="mb-tiles"></div>
</div>
<div class="mb-meet-bar" id="mb-meet-bar" hidden>
  <button class="mp-go mp-go-2" type="button" id="mb-mic" aria-pressed="false"><span>Mic off</span></button>
  <button class="mp-go mp-go-2" type="button" id="mb-cam" aria-pressed="false"><span>Camera off</span></button>
  <button class="mp-go" type="button" id="mb-leave">Leave</button>
</div>
{end}
<p class="mp-muted" style="margin-top:14px;font-size:12px">Group meetings aren't recorded.</p>"""
    script = (f'<script src="{LIVEKIT_JS}" integrity="{LIVEKIT_SRI}" crossorigin="anonymous"></script>'
              + _meet_script())
    return _shell(biz, site, g["name"], body, tab="groups", who=me, script=script), 200


def _meet_script() -> str:
    """Join with a fresh token, show everyone's camera, mic/camera
    buttons when allowed. Names come from LiveKit and are set as text."""
    return r"""<script>(function(){var box=document.getElementById('mb-meet');if(!box||!window.LivekitClient)return;
var L=window.LivekitClient,sid=box.getAttribute('data-sid'),tiles=document.getElementById('mb-tiles'),
msg=document.getElementById('mb-meet-msg'),bar=document.getElementById('mb-meet-bar'),room;
function say(t){msg.textContent=t;msg.hidden=!t;}
function tile(p){var id='t-'+p.identity,el=document.getElementById(id);if(el)return el;el=document.createElement('div');el.className='mb-tile';el.id=id;
var n=document.createElement('span');n.className='mb-tile-name';n.textContent=p.name||'Someone';el.appendChild(n);tiles.appendChild(el);return el;}
function attach(track,p){if(track.kind==='video'){var el=tile(p),v=track.attach();v.setAttribute('playsinline','');el.insertBefore(v,el.firstChild);}
else if(track.kind==='audio'){var a=track.attach();a.hidden=true;document.body.appendChild(a);}}
function drop(p){var el=document.getElementById('t-'+p.identity);if(el)el.remove();}
fetch('/my/groups/live/'+sid+'/token',{method:'POST',credentials:'same-origin',headers:{'Accept':'application/json'}})
.then(function(r){return r.json().then(function(d){return {ok:r.ok,d:d};});}).then(function(x){
if(!x.ok){say(x.d.error||'You can\'t join right now.');if(x.d.reload)setTimeout(function(){location.reload();},15000);return;}
room=new L.Room({adaptiveStream:true,dynacast:true});
room.on(L.RoomEvent.TrackSubscribed,function(t,pub,p){attach(t,p);});
room.on(L.RoomEvent.LocalTrackPublished,function(pub){if(pub.track&&pub.track.kind==='video')attach(pub.track,room.localParticipant);});
room.on(L.RoomEvent.ParticipantConnected,function(p){tile(p);});
room.on(L.RoomEvent.ParticipantDisconnected,drop);
room.on(L.RoomEvent.Disconnected,function(){say('You left the meeting.');bar.hidden=true;tiles.textContent='';});
return room.connect(x.d.server_url,x.d.token).then(function(){say('');tile(room.localParticipant);
room.remoteParticipants.forEach(function(p){tile(p);});bar.hidden=false;
var can=x.d.publish,mic=document.getElementById('mb-mic'),cam=document.getElementById('mb-cam');
if(!can){mic.hidden=true;cam.hidden=true;}
mic.onclick=function(){var on=mic.getAttribute('aria-pressed')!=='true';room.localParticipant.setMicrophoneEnabled(on).then(function(){
mic.setAttribute('aria-pressed',String(on));mic.lastChild.textContent=on?'Mic on':'Mic off';}).catch(function(){say('Your microphone couldn\'t start. Check the browser\'s permission.');});};
cam.onclick=function(){var on=cam.getAttribute('aria-pressed')!=='true';room.localParticipant.setCameraEnabled(on).then(function(){
cam.setAttribute('aria-pressed',String(on));cam.lastChild.textContent=on?'Camera on':'Camera off';if(!on){var el=document.getElementById('t-'+room.localParticipant.identity);
if(el){el.querySelectorAll('video').forEach(function(v){v.remove();});}}}).catch(function(){say('Your camera couldn\'t start. Check the browser\'s permission.');});};
document.getElementById('mb-leave').onclick=function(){room.disconnect();};});
}).catch(function(){say('The meeting couldn\'t connect. Check your connection and try again.');});})();</script>"""


# ─── POST ─────────────────────────────────────────────────────────────


def _json(ok: bool, status: int = 200, **data):
    return JSONResponse({"ok": ok, **data}, status_code=status)


@router.post("/my/groups/live/start", include_in_schema=False)
async def start_meeting(request: Request):
    import asyncio
    import re
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return mpc._back("/my/groups", err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    form = await request.form()
    gid = str(form.get("group_id") or "")
    mode = "broadcast" if str(form.get("mode") or "") == "broadcast" else "meeting"
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", gid):
        return mpc._back("/my/groups", err="group_gone")
    if not mpc._allowed(church, me):
        return mpc._back("/my/groups", err="slow")
    if not video_ready():
        return mpc._back("/my/groups", err="video_off")
    biz = church["business"]
    g, m = await asyncio.gather(asyncio.to_thread(group, biz["id"], gid),
                                asyncio.to_thread(membership, biz["id"], gid, me["id"]))
    if g is None or m is None:
        return mpc._back("/my/groups", err="error")
    if not g or not g.get("active"):
        return mpc._back("/my/groups", err="group_gone")
    if not is_host(m):
        return mpc._back("/my/groups", err="not_host")
    sid = str(uuid4())
    room = f"grp-{sid}"
    rows = await asyncio.to_thread(sb_clients.sb_post_as_service, "/group_live_sessions", {
        "id": sid, "business_id": biz["id"], "group_id": gid, "mode": mode,
        "status": "waiting" if g.get("youth") else "live", "room_name": room, "started_by": str(me["id"])})
    if not isinstance(rows, list) or not rows:
        # One meeting at a time per group: someone already started it.
        existing = await asyncio.to_thread(open_sessions, biz["id"], [gid])
        if existing and gid in existing:
            return mpc._back(f"/my/groups/live/{existing[gid]['id']}")
        return mpc._back("/my/groups", err="error")
    try:
        await create_room(room)
    except Exception:
        await asyncio.to_thread(sb_clients.sb_patch_as_service,
                                f"/group_live_sessions?id=eq.{_q(sid)}&business_id=eq.{_q(biz['id'])}",
                                {"status": "ended", "ended_at": now_iso(), "updated_at": now_iso()})
        return mpc._back("/my/groups", err="video_off")
    return mpc._back(f"/my/groups/live/{sid}")


@router.post("/my/groups/live/{sid}/token", include_in_schema=False)
async def join_token(sid: str, request: Request):
    import asyncio
    import live_router as lr
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable == "preview":
        return _json(False, 403, error=mpc.ERRORS["preview"])
    if unavailable:
        return _json(False, 503, error=mpc.ERRORS["error"])
    if not me:
        return _json(False, 401, error=mpc.ERRORS["signed_out"])
    if not mpc._allowed(church, me):
        return _json(False, 429, error=mpc.ERRORS["slow"])
    biz = church["business"]
    s = await asyncio.to_thread(session, biz["id"], sid)
    if s is None:
        return _json(False, 503, error=mpc.ERRORS["error"])
    if not s or s["status"] == "ended":
        return _json(False, 410, error="This meeting has ended.")
    m = await asyncio.to_thread(membership, biz["id"], s["group_id"], me["id"])
    if m is None:
        return _json(False, 503, error=mpc.ERRORS["error"])
    if not m:
        return _json(False, 403, error="Group meetings are for the people in that group.")
    host = is_host(m)
    if s["status"] == "waiting":
        if not host:
            return _json(False, 409, error="Waiting for a second adult leader.", reload=True)
        if str(s.get("started_by") or "") != str(me["id"]):
            # The second approved adult is here: the meeting opens.
            await asyncio.to_thread(
                sb_clients.sb_patch_as_service,
                f"/group_live_sessions?id=eq.{_q(s['id'])}&business_id=eq.{_q(biz['id'])}&status=eq.waiting",
                {"status": "live", "second_adult": str(me["id"]), "updated_at": now_iso()})
    try:
        alive = await room_open(s["room_name"])
    except Exception:
        return _json(False, 503, error="Video isn't reachable just now. Please try again in a moment.")
    if not alive:
        await asyncio.to_thread(
            sb_clients.sb_patch_as_service,
            f"/group_live_sessions?id=eq.{_q(s['id'])}&business_id=eq.{_q(biz['id'])}&status=in.(waiting,live)",
            {"status": "ended", "ended_at": now_iso(), "updated_at": now_iso()})
        return _json(False, 410, error="This meeting has ended.")
    publish = host or s["mode"] == "meeting"
    await asyncio.to_thread(count_attendance, biz, s["group_id"], str(me["id"]))
    return _json(True, publish=publish, host=host,
                 **mint(s["room_name"], f"c_{me['id']}", lr.author_for(me.get("name")), publish, host))


@router.post("/my/groups/live/{sid}/end", include_in_schema=False)
async def end_meeting(sid: str, request: Request):
    import asyncio
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return mpc._back("/my/groups", err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    biz = church["business"]
    s = await asyncio.to_thread(session, biz["id"], sid)
    if s is None:
        return mpc._back("/my/groups", err="error")
    if not s:
        return mpc._back("/my/groups", err="group_gone")
    m = await asyncio.to_thread(membership, biz["id"], s["group_id"], me["id"])
    if m is None:
        return mpc._back("/my/groups", err="error")
    if not is_host(m):
        return mpc._back("/my/groups", err="not_host")
    if s["status"] != "ended":
        saved = await asyncio.to_thread(
            sb_clients.sb_patch_as_service,
            f"/group_live_sessions?id=eq.{_q(s['id'])}&business_id=eq.{_q(biz['id'])}",
            {"status": "ended", "ended_at": now_iso(), "updated_at": now_iso()})
        if not isinstance(saved, list):
            return mpc._back("/my/groups", err="error")
        try:
            await close_room(s["room_name"])
        except Exception:
            pass          # the room empties and closes on its own
    return mpc._back("/my/groups", done="meeting_ended")

"""
KAI on the phone (2026-10-14).

KAI is the orchestrator inside Solution Space, Kevin's desktop app: one
long-lived Claude Code conversation that opens, briefs and watches his coding
sessions. Until now it lived only on the desktop. This is its line to the
Dev Desk, so the conversation goes with him:

  • the desktop mirrors KAI's conversation here as it happens — what Kevin
    typed, what KAI said, the Space actions it took, what Solution Space told
    it — so the phone shows the same conversation, picked up where it was;
  • what Kevin sends from the phone, typed or spoken, waits here until the
    desktop types it into KAI and acks it. Spoken words reach KAI marked as
    spoken, so it answers the way it would out loud, and the phone reads the
    answer to him;
  • the approvals KAI's workers are stopped on ride along in the desktop's
    state, and his answer from the phone goes back the same way a message
    does. The desktop applies it once, never as a standing rule.

Storage is dev_kai_messages; the desktop's live read (busy, away, the
approvals) is dev_bridge_devices.kai_state. Both come from
supabase/APPLY-2026-10-14-dev-desk-kai.sql.

Auth: /platform/dev-desk/kai* is owner-only (require_owner) like the rest of
the Dev Desk; /dev-bridge/kai/* takes the paired device's token.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from dev_bridge import HTTP_TIMEOUT, _now, _push_owner, _require_device, _sb_get, _sb_patch
from lead_admin import SUPABASE_URL, _service_headers, require_owner

logger = logging.getLogger("dev_kai")

router = APIRouter(tags=["dev-bridge"])

MIGRATION = "supabase/APPLY-2026-10-14-dev-desk-kai.sql"
# The capability a build of Solution Space names on its queue poll when it
# carries KAI's line; the phone finds the desktop KAI lives on by it.
KAI_CAPABILITY = "kai-v1"
# Where a tap on a KAI notification opens.
NAV = "studio:platform-dev-desk:kai"

# What the desktop mirrors. 'decision' only ever comes from the phone.
_MIRRORED = {"you", "kai", "event", "tool", "error"}
_TEXT_MAX = 4000
_LINE_MAX = 60
_APPROVALS_MAX = 20
# A device polls every 15 seconds; three missed polls reads as offline.
_ONLINE_S = 45
# The phone renews its watch every minute while KAI's thread is open.
_WATCH_S = 180
# A short KAI line after it already answered ("Noted.") is not worth a buzz.
_WORTH_A_PUSH = 120
_COLUMNS = "id,at,updated_at,kind,via,text,spoken,delivered_at,meta"


# ─── Small helpers ────────────────────────────────────────────────────

def _parse(ts: Any) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _z(t: datetime) -> str:
    # Z form: '+00:00' reads as a space in a PostgREST query string.
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _missing(e: HTTPException) -> HTTPException:
    return HTTPException(e.status_code, f"KAI on the phone needs {MIGRATION} applied. {e.detail}")


async def _insert(c: httpx.AsyncClient, rows: List[Dict[str, Any]], *,
                  skip_known: bool = False) -> List[Dict[str, Any]]:
    """Insert messages and return the rows that are new. With skip_known, a
    row whose id is already stored is left alone and not returned — the
    desktop re-sends its recent line whenever it reconnects."""
    prefer = "return=representation"
    if skip_known:
        prefer += ",resolution=ignore-duplicates"
    r = await c.post(f"{SUPABASE_URL}/rest/v1/dev_kai_messages",
                     headers={**_service_headers(), "Prefer": prefer}, json=rows)
    if r.status_code >= 400:
        raise _missing(HTTPException(502, f"dev_kai write failed: {r.text[:200]}"))
    out = r.json() if r.text else []
    return out if isinstance(out, list) else []


async def _kai_device(c: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """The Solution Space KAI lives on: the paired device that most recently
    polled saying it carries KAI. None until a build that does has polled."""
    try:
        rows = await _sb_get(c, "dev_bridge_devices", {
            "select": "id,name,last_seen_at,agents,kai_state,kai_watch_until",
            "revoked": "eq.false",
            "agents": f"cs.{{{KAI_CAPABILITY}}}",
            "order": "last_seen_at.desc.nullslast",
            "limit": "1",
        })
    except HTTPException as e:
        raise _missing(e)
    return rows[0] if rows else None


def _desktop(device: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What the phone needs to know about the desktop: is it there, is KAI
    thinking, and what is waiting on Kevin. Approvals only show while the
    desktop is online — a restart expires every one of them."""
    if not device:
        return {"paired": False, "online": False, "busy": False, "approvals": []}
    seen = _parse(device.get("last_seen_at"))
    online = bool(seen and (datetime.now(timezone.utc) - seen).total_seconds() <= _ONLINE_S)
    state = device.get("kai_state") or {}
    return {
        "paired": True,
        "online": online,
        "name": device.get("name"),
        "last_seen_at": device.get("last_seen_at"),
        "running": bool(state.get("running")) and online,
        "busy": bool(state.get("busy")) and online,
        "away": bool(state.get("away")),
        "approvals": list(state.get("approvals") or []) if online else [],
    }


def _shown(m: Dict[str, Any]) -> Dict[str, Any]:
    return {k: m.get(k) for k in _COLUMNS.split(",")}


async def _watch(c: httpx.AsyncClient) -> str:
    until = _z(datetime.now(timezone.utc) + timedelta(seconds=_WATCH_S))
    try:
        await _sb_patch(c, "dev_bridge_devices",
                        {"revoked": "eq.false", "agents": f"cs.{{{KAI_CAPABILITY}}}"},
                        {"kai_watch_until": until})
    except HTTPException as e:
        raise _missing(e)
    return until


# ─── The phone: Kevin's side ──────────────────────────────────────────

class KaiSayBody(BaseModel):
    text: str
    spoken: bool = False


class KaiDecisionBody(BaseModel):
    verdict: str  # 'approve' | 'refuse'


@router.get("/platform/dev-desk/kai")
async def kai_thread(since: Optional[str] = None, _owner=Depends(require_owner)):
    """KAI's conversation and the desktop's state. With `since` (the newest
    updated_at the phone holds), only what changed — new lines, and phone
    messages the desktop has since delivered."""
    cursor = _parse(since) if since else None
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _kai_device(c)
        params: Dict[str, str] = {"select": _COLUMNS}
        if cursor:
            # A few seconds of overlap: the server's clock and the database's
            # differ a little, and the phone merges by id anyway.
            params.update({"updated_at": f"gt.{_z(cursor - timedelta(seconds=3))}",
                           "order": "updated_at.asc", "limit": "100"})
        else:
            params.update({"order": "at.desc", "limit": "60"})
        try:
            rows = await _sb_get(c, "dev_kai_messages", params)
        except HTTPException as e:
            raise _missing(e)
    if not cursor:
        rows.reverse()
    return {"ok": True, "messages": [_shown(m) for m in rows],
            "desktop": _desktop(device), "now": _now()}


@router.post("/platform/dev-desk/kai/say")
async def kai_say(body: KaiSayBody, _owner=Depends(require_owner)):
    """Kevin, from his phone. It waits here until the desktop types it into
    KAI; if Solution Space is closed, KAI gets it when it opens."""
    text = (body.text or "").strip()[:_TEXT_MAX]
    if not text:
        raise HTTPException(422, "Nothing to send.")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _kai_device(c)
        now = _now()
        rows = await _insert(c, [{
            "kind": "you", "via": "phone", "text": text, "spoken": bool(body.spoken),
            "device_id": device["id"] if device else None, "at": now, "updated_at": now,
        }])
        await _watch(c)
    return {"ok": True, "message": _shown(rows[0]) if rows else None,
            "desktop": _desktop(device)}


@router.post("/platform/dev-desk/kai/approvals/{request_id}")
async def kai_decide(request_id: int, body: KaiDecisionBody, _owner=Depends(require_owner)):
    """Kevin's answer to an approval a worker is stopped on. Only a request
    the desktop says is still waiting can be answered, and only while it is
    online to apply it; the desktop applies it once."""
    verdict = (body.verdict or "").strip().lower()
    if verdict not in ("approve", "refuse"):
        raise HTTPException(422, "verdict must be approve or refuse")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _kai_device(c)
        desk = _desktop(device)
        if not desk["online"]:
            raise HTTPException(409, "Solution Space is offline, so it can't take an answer right now.")
        request = next((a for a in desk["approvals"] if a.get("id") == request_id), None)
        if not request:
            raise HTTPException(409, "That request was already answered, or it has expired.")
        what = request.get("label") or request.get("what") or f"request #{request_id}"
        now = _now()
        rows = await _insert(c, [{
            "kind": "decision", "via": "phone", "device_id": device["id"], "at": now, "updated_at": now,
            "text": f"{'Approved' if verdict == 'approve' else 'Not approved'}: {what}"[:_TEXT_MAX],
            "meta": {"request": request_id, "verdict": verdict},
        }])
    return {"ok": True, "message": _shown(rows[0]) if rows else None}


@router.post("/platform/dev-desk/kai/watch")
async def kai_watch(_owner=Depends(require_owner)):
    """The phone has KAI's thread open. Until this lapses the desktop checks
    for his messages every few seconds, and KAI's answers don't buzz the
    phone he is already looking at."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        until = await _watch(c)
    return {"ok": True, "until": until}


# ─── The desktop: Solution Space's side ───────────────────────────────

class KaiAckBody(BaseModel):
    ids: List[str]


class KaiEntry(BaseModel):
    id: str
    kind: str
    text: Optional[str] = ""
    at: Optional[str] = None
    spoken: Optional[bool] = False
    meta: Optional[Dict[str, Any]] = None


class KaiLineBody(BaseModel):
    entries: List[KaiEntry] = []
    # { running, busy, away, approvals: [{id, label, what, worker, agent, createdAt}] }
    state: Optional[Dict[str, Any]] = None


@router.get("/dev-bridge/kai/inbox")
async def kai_inbox(authorization: Optional[str] = Header(None)):
    """Kevin's messages and answers from the phone that KAI hasn't had yet,
    oldest first, and whether the phone is watching (poll fast if so)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        try:
            rows = await _sb_get(c, "dev_kai_messages", {
                "via": "eq.phone", "delivered_at": "is.null",
                "select": "id,at,kind,text,spoken,meta",
                "order": "at.asc", "limit": "20",
            })
            me = await _sb_get(c, "dev_bridge_devices", {
                "id": f"eq.{device['id']}", "select": "kai_watch_until"})
        except HTTPException as e:
            raise _missing(e)
    until = _parse((me[0] if me else {}).get("kai_watch_until"))
    watching = bool(until and until > datetime.now(timezone.utc))
    return {"ok": True, "messages": rows, "watching": watching}


@router.post("/dev-bridge/kai/ack")
async def kai_ack(body: KaiAckBody, authorization: Optional[str] = Header(None)):
    """The desktop typed these into KAI (or applied the decision)."""
    ids = []
    for raw in (body.ids or [])[:50]:
        try:
            ids.append(str(UUID(str(raw))))
        except ValueError:
            continue
    if not ids:
        raise HTTPException(422, "ids required")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        now = _now()
        try:
            await _sb_patch(c, "dev_kai_messages",
                            {"id": f"in.({','.join(ids)})", "via": "eq.phone", "delivered_at": "is.null"},
                            {"delivered_at": now, "updated_at": now, "device_id": device["id"]})
        except HTTPException as e:
            raise _missing(e)
    return {"ok": True, "acked": len(ids)}


def _entry_row(e: KaiEntry, device_id: str) -> Optional[Dict[str, Any]]:
    try:
        eid = str(UUID(str(e.id)))
    except ValueError:
        return None
    if e.kind not in _MIRRORED:
        return None
    at = _parse(e.at) or datetime.now(timezone.utc)
    meta = {k: v for k, v in (e.meta or {}).items()
            if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 300}
    return {"id": eid, "device_id": device_id, "kind": e.kind, "via": "desktop",
            "text": (e.text or "")[:_TEXT_MAX], "spoken": bool(e.spoken),
            "at": _z(at), "updated_at": _now(), "meta": meta or None}


def _clean_state(state: Dict[str, Any]) -> Dict[str, Any]:
    approvals = []
    for a in (state.get("approvals") or [])[:_APPROVALS_MAX]:
        if not isinstance(a, dict):
            continue
        try:
            rid = int(a.get("id"))
        except (TypeError, ValueError):
            continue
        approvals.append({
            "id": rid,
            "label": str(a.get("label") or "")[:200],
            "what": str(a.get("what") or "")[:300],
            "worker": str(a.get("worker") or "")[:40],
            "agent": str(a.get("agent") or "")[:20],
            "createdAt": str(a.get("createdAt") or "")[:40],
        })
    return {"running": bool(state.get("running")), "busy": bool(state.get("busy")),
            "away": bool(state.get("away")), "approvals": approvals, "at": _now()}


@router.post("/dev-bridge/kai/line")
async def kai_mirror(body: KaiLineBody, authorization: Optional[str] = Header(None)):
    """The desktop's KAI line as it happens, and its live state. Entries are
    keyed by the desktop's own ids, so sending the recent line again after a
    reconnect stores nothing twice and tells Kevin nothing twice."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        rows = [r for r in (_entry_row(e, device["id"]) for e in body.entries[:_LINE_MAX]) if r]
        stored = await _insert(c, rows, skip_known=True) if rows else []
        try:
            me = await _sb_get(c, "dev_bridge_devices", {
                "id": f"eq.{device['id']}", "select": "kai_state,kai_watch_until"})
        except HTTPException as e:
            raise _missing(e)
        before = (me[0] if me else {})
        previous = before.get("kai_state") or {}
        state = _clean_state(body.state) if body.state is not None else dict(previous)
        pushed = await _tell(c, previous, state, stored, _parse(before.get("kai_watch_until")))
        if body.state is not None or pushed:
            await _sb_patch(c, "dev_bridge_devices", {"id": f"eq.{device['id']}"},
                            {"kai_state": state})
    return {"ok": True, "stored": len(stored), "pushed": pushed}


async def _tell(c: httpx.AsyncClient, previous: Dict[str, Any], state: Dict[str, Any],
                stored: List[Dict[str, Any]], watch_until: Optional[datetime]) -> int:
    """Whether Kevin's phone hears about this. Never while he has KAI's
    thread open. Otherwise: a new approval when he is away from the desk or
    talking to KAI from the phone, and KAI's answer when the last thing he
    said came from the phone — the first answer always, after that only
    when it says something substantial. Records what it told in `state`."""
    if watch_until and watch_until > datetime.now(timezone.utc):
        return 0
    known = {a.get("id") for a in previous.get("approvals") or []}
    fresh = [a for a in state.get("approvals") or [] if a.get("id") not in known]
    said = [m for m in stored if m.get("kind") == "kai" and (m.get("text") or "").strip()]
    if not fresh and not said:
        return 0
    last_you = await _sb_get(c, "dev_kai_messages", {
        "kind": "eq.you", "select": "id,via", "order": "at.desc", "limit": "1"})
    from_phone = bool(last_you and last_you[0].get("via") == "phone")
    if fresh and (state.get("away") or from_phone):
        a = fresh[-1]
        more = f" (+{len(fresh) - 1} more)" if len(fresh) > 1 else ""
        return await _push_owner(c, "KAI — needs your OK",
                                 f"{a.get('label') or a.get('what') or 'A worker is waiting'}{more}",
                                 nav=NAV, tag="kai-approval")
    if said and from_phone:
        answering = last_you[0]["id"]
        text = " ".join(said[-1]["text"].split())
        if previous.get("answered") == answering and len(text) < _WORTH_A_PUSH:
            return 0
        state["answered"] = answering
        return await _push_owner(c, "KAI", text, nav=NAV, tag="kai")
    return 0


@router.post("/dev-bridge/kai/handoff")
async def kai_handoff(authorization: Optional[str] = Header(None)):
    """Kevin pressed "Take KAI with me" in Solution Space. His phone hears
    about it at once, and a tap opens KAI's thread on the Dev Desk."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _require_device(c, authorization)
        pushed = await _push_owner(c, "KAI — on your phone",
                                   "Pick up where you left off. Tap the mic to talk.",
                                   nav=NAV, tag="kai")
    return {"ok": True, "pushed": pushed}

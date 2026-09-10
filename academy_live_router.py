"""Native Academy classes. Railway holds provider secrets; Supabase owns access.

Access RPCs deliberately run as the caller (or enrollment-link anon), NEVER as
service role. Only after that check may this module perform privileged writes.
No request payloads, tokens, provider errors, or credentials are logged here.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from aiohttp import ClientTimeout
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from livekit import api

import sb_clients

router = APIRouter(prefix="/academy-live", tags=["academy-live"])
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
ACTIONS = {"status", "start", "join", "end", "allow", "listen", "remove"}
CONTROLS = {"allow", "listen", "remove"}
NO_STORE = {"Cache-Control": "no-store"}


class LiveError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def settings():
    return tuple(os.environ.get(k, "").strip() for k in
                 ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))


def configured():
    url, key, secret = settings()
    return bool(url.startswith("wss://") and key and secret and sb_clients.sb_url()
                and sb_clients.sb_anon() and sb_clients.sb_service_role())


async def bounded_body(request, limit):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise LiveError(413, "Request too large.")
    return bytes(body)


def parse_input(raw):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise LiveError(400, "Invalid request.") from None
    if not isinstance(value, dict) or not isinstance(value.get("action"), str) or value["action"] not in ACTIONS:
        raise LiveError(400, "Unknown classroom action.")
    for field in ("session_id", "portal_token"):
        item = value.get(field)
        required = field == "session_id" and value["action"] != "status"
        if (required or item is not None) and (not isinstance(item, str) or not UUID_RE.fullmatch(item)):
            raise LiveError(400, "Choose a valid class and classroom link.")
    if value["action"] in CONTROLS:
        target = value.get("identity")
        if not isinstance(target, str) or not target.startswith("student_") or not UUID_RE.fullmatch(target[8:]):
            raise LiveError(400, "Choose a student in this class.")
    # Never trust client-supplied role, permission, room, or business fields.
    return {k: value.get(k) for k in ("action", "session_id", "portal_token", "identity")}


def authorize(action, access):
    if action != "join" and access.get("teacher") is not True:
        raise LiveError(403, "Only your teaching team can manage this class.")
    if action == "end" and access["status"] == "ended":
        return
    if access["status"] in ("ended", "cancelled"):
        raise LiveError(409, "This class has ended or was cancelled.")
    if action == "join" and access["status"] != "live":
        raise LiveError(409, "Your teacher has not started this class yet.")
    if action in CONTROLS and access["status"] != "live":
        raise LiveError(409, "Start the class first.")


async def db(client, method, path, body=None, *, caller=None, prefer="return=representation"):
    headers = sb_clients.sb_headers_user(caller, prefer) if caller else sb_clients.sb_headers_service(prefer)
    res = await client.request(method, sb_clients.sb_url() + "/rest/v1" + path,
                               headers=headers, json=body, timeout=10)
    if res.status_code >= 400:
        if caller:
            raise LiveError(403, "This classroom is unavailable for your account or class link.")
        # Postgres P0001 is the explicit block/throttle exception, not an outage.
        if path == "/rpc/academy_live_token_claim" and res.json().get("code") == "P0001":
            raise LiveError(429, "Please wait a few seconds and try joining again.")
        raise LiveError(503, "Class data is unavailable. Please retry or contact your school.")
    return res.json() if res.content else None


async def access_for(client, input, authorization):
    # A portal link always stays a student, even in a signed-in teacher's browser.
    # PostgREST verifies the forwarded JWT; academy_live_access checks ownership,
    # confirmed teaching-team membership, enrollment, and course/business scope.
    if input["portal_token"]:
        caller = sb_clients.sb_anon()
    else:
        scheme, _, caller = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not caller.strip() or caller == sb_clients.sb_service_role():
            raise LiveError(401, "Sign in or use your classroom link.")
    access = await db(client, "POST", "/rpc/academy_live_access",
                      {"p_session": input["session_id"], "p_token": input["portal_token"]}, caller=caller)
    if not isinstance(access, dict) or not access.get("identity"):
        raise LiveError(403, "This classroom is unavailable.")
    return access


def mint_token(access):
    url, key, secret = settings()
    sources = []
    if access["can_publish"]:
        sources = ["camera", "microphone"]
        if access["teacher"]:
            sources += ["screen_share", "screen_share_audio"]
    token = (api.AccessToken(key, secret).with_identity(access["identity"])
             .with_name(access["name"]).with_ttl(timedelta(seconds=60))
             .with_metadata(json.dumps({"teacher": access["teacher"]}))
             .with_grants(api.VideoGrants(room_join=True, room=access["room_name"],
                 can_publish=access["can_publish"], can_subscribe=True, can_publish_data=True,
                 can_publish_sources=sources, can_update_own_metadata=True)).to_jwt())
    return {"server_url": url, "participant_token": token, **{k: access[k] for k in
            ("teacher", "session_id", "title", "mode")}}


def provider():
    url, key, secret = settings()
    return api.LiveKitAPI(url, key, secret, timeout=ClientTimeout(total=10))


async def delete_room(rooms, name):
    try:
        await rooms.delete_room(api.DeleteRoomRequest(room=name))
    except api.TwirpError as exc:
        if exc.code != "not_found":
            raise


async def run_action(client, input, authorization):
    action = input["action"]
    if action == "status":
        ready = configured()
        if ready:
            try:
                await db(client, "GET", "/academy_live_sessions?select=id&limit=0")
            except Exception:
                ready = False
        return {"configured": ready}
    if not configured():
        raise LiveError(503, "Live classes are being connected. Please try again later.")
    access = await access_for(client, input, authorization)
    authorize(action, access)
    if action == "join":
        await db(client, "POST", "/rpc/academy_live_token_claim",
                 {"p_session": access["session_id"], "p_identity": access["identity"]})
        # Recheck persisted permissions after claiming, so a concurrent block or
        # listen-only change observed here is reflected in the signed token.
        access = await access_for(client, input, authorization)
        authorize(action, access)
        return mint_token(access)
    async with provider() as live:
        rooms = live.room
        session_path = "/academy_live_sessions?id=eq." + access["session_id"]
        if action == "start":
            await rooms.create_room(api.CreateRoomRequest(name=access["room_name"],
                max_participants=access["max_participants"], empty_timeout=120, departure_timeout=60,
                metadata=json.dumps({"title": access["title"], "mode": access["mode"]})))
            await db(client, "PATCH", session_path + "&status=eq.scheduled",
                     {"status": "live", "started_at": datetime.now(timezone.utc).isoformat()})
            try:
                access = await access_for(client, input, authorization)
                authorize("join", access)
            except LiveError:
                await delete_room(rooms, access["room_name"])
                raise
            await db(client, "POST", "/rpc/academy_live_token_claim",
                     {"p_session": access["session_id"], "p_identity": access["identity"]})
            return mint_token(access)
        if action == "end":
            await db(client, "PATCH", session_path + "&status=in.(live,scheduled)",
                     {"status": "ended", "ended_at": datetime.now(timezone.utc).isoformat()})
            await delete_room(rooms, access["room_name"])
            return {"ok": True}
        target = input["identity"]
        enrolled = await db(client, "GET", "/academy_enrollments?select=id&id=eq." + target[8:]
                            + "&course_id=eq." + access["course_id"] + "&business_id=eq." + access["business_id"] + "&limit=1")
        if not enrolled:
            raise LiveError(403, "That student does not belong to this class.")
        publish = action == "allow"
        await db(client, "POST", "/academy_live_members?on_conflict=session_id,identity",
                 {"session_id": access["session_id"], "identity": target,
                  "can_publish": publish, "blocked": action == "remove"},
                 prefer="resolution=merge-duplicates,return=representation")
        if action == "remove":
            try:
                await rooms.remove_participant(api.RoomParticipantIdentity(room=access["room_name"], identity=target))
            except api.TwirpError as exc:
                if exc.code != "not_found":
                    raise
        else:
            try:
                await rooms.update_participant(api.UpdateParticipantRequest(room=access["room_name"], identity=target,
                    permission=api.ParticipantPermission(can_publish=publish, can_subscribe=True, can_publish_data=True,
                        can_publish_sources=[api.TrackSource.CAMERA, api.TrackSource.MICROPHONE] if publish else [])))
            except api.TwirpError as exc:
                # The persisted permission also applies when the student rejoins.
                if exc.code != "not_found":
                    raise
        return {"ok": True}


@router.post("")
async def live_action(request: Request):
    try:
        input = parse_input(await bounded_body(request, 4096))
        async with httpx.AsyncClient() as client:
            result = await asyncio.wait_for(run_action(client, input, request.headers.get("authorization")), timeout=22)
        return JSONResponse(result, headers=NO_STORE)
    except LiveError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status, headers=NO_STORE)
    except Exception:
        return JSONResponse({"error": "The live service could not complete this action. Please retry."},
                            status_code=502, headers=NO_STORE)


async def record_event(client, event):
    room = event.room.name
    if not room.startswith("class_") or not UUID_RE.fullmatch(room[6:]):
        return
    if event.event in ("participant_joined", "participant_left"):
        person = event.participant
        if not re.fullmatch(r"(?:student|teacher)_[0-9a-f-]{36}", person.identity, re.I) or not person.sid:
            return
        at = datetime.fromtimestamp(event.created_at, timezone.utc).isoformat()
        await db(client, "POST", "/rpc/academy_live_attendance_event", {
            "p_room": room, "p_sid": person.sid, "p_identity": person.identity, "p_name": person.name,
            "p_joined": at if event.event == "participant_joined" else None,
            "p_left": at if event.event == "participant_left" else None})
    if event.event == "room_finished":
        at = datetime.fromtimestamp(event.created_at, timezone.utc).isoformat()
        rows = await db(client, "PATCH", "/academy_live_sessions?room_name=eq." + room + "&status=in.(live,ended)&select=id",
                        {"status": "ended", "ended_at": at})
        for session in rows or []:
            await db(client, "PATCH", "/academy_live_attendance?session_id=eq." + session["id"] + "&left_at=is.null", {"left_at": at})


@router.post("/webhook")
async def webhook(request: Request):
    try:
        body = await bounded_body(request, 262144)
    except LiveError as exc:
        return Response(exc.message, status_code=exc.status, headers=NO_STORE)
    _, key, secret = settings()
    if not key or not secret:
        return Response("Webhook not configured", status_code=503, headers=NO_STORE)
    try:
        event = api.WebhookReceiver(api.TokenVerifier(key, secret)).receive(
            body.decode("utf-8"), request.headers.get("authorization", ""))
    except Exception:
        return Response("Invalid signature", status_code=401, headers=NO_STORE)
    try:
        async with httpx.AsyncClient() as client:
            await record_event(client, event)
        return Response("OK", headers=NO_STORE)
    except Exception:
        return Response("Retry delivery", status_code=500, headers=NO_STORE)

"""Native Academy classes. Railway holds provider secrets; Supabase owns access.

Access RPCs deliberately run as the caller (or enrollment-link anon), NEVER as
service role. Only after that check may this module perform privileged writes.
No request payloads, tokens, provider errors, or credentials are logged here.

The room (2026-10-17): the lobby opens 15 minutes before a class starts; the
class's chat, questions and answers to a question slide are kept
(academy_live_messages) and reach the room from here, never from a
participant, so a message a student sends can be held for the teacher and an
answer is only ever seen by the teaching team until a teacher puts it on
screen without a name.
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
ACTIONS = {"status", "start", "join", "end", "allow", "listen", "remove", "lower",
           "post", "history", "moderate", "roster", "here", "mark", "missed", "sum", "record", "watch"}
CONTROLS = {"allow", "listen", "remove", "lower"}
TEACHER_ACTIONS = {"start", "end", "allow", "listen", "remove", "lower", "moderate", "roster", "mark", "missed", "sum",
                   "record"}
# Things a student may do while the class is live or its lobby is open.
ROOM_ACTIONS = {"join", "post", "history", "here"}
KINDS = {"chat", "question", "answer"}
MODERATION = {"hide", "show", "pin", "unpin", "answered", "onscreen", "offscreen"}
SLIDE_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# A student's message carrying a link waits for the teacher.
LINK_RE = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|co|app|ly|me|xyz|info|biz|gg|tv|link|site)\b", re.I)
LOBBY = timedelta(minutes=15)
MAX_BODY = 1000
TOPIC_MESSAGE, TOPIC_UPDATE = "class.msg", "class.upd"
NO_STORE = {"Cache-Control": "no-store"}
MESSAGE_FIELDS = "id,identity,display_name,teacher,kind,body,slide_id,status,pinned,answered_at,onscreen_at,created_at"


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
    action = value["action"]
    for field in ("session_id", "portal_token"):
        item = value.get(field)
        required = field == "session_id" and action != "status"
        if (required or item is not None) and (not isinstance(item, str) or not UUID_RE.fullmatch(item)):
            raise LiveError(400, "Choose a valid class and classroom link.")
    if action in CONTROLS or action == "mark":
        target = value.get("identity")
        if not isinstance(target, str) or not target.startswith("student_") or not UUID_RE.fullmatch(target[8:]):
            raise LiveError(400, "Choose a student in this class.")
    out = {k: value.get(k) for k in ("action", "session_id", "portal_token", "identity")}
    if action == "post":
        kind, body, slide = value.get("kind"), value.get("body"), value.get("slide_id")
        if kind not in KINDS:
            raise LiveError(400, "Choose chat, a question or an answer.")
        if not isinstance(body, str) or not body.strip():
            raise LiveError(400, "Write something first.")
        if len(body.strip()) > MAX_BODY:
            raise LiveError(400, f"Keep it under {MAX_BODY} characters.")
        if kind == "answer" and (not isinstance(slide, str) or not SLIDE_RE.fullmatch(slide)):
            raise LiveError(400, "Answer the question on the screen.")
        out.update(kind=kind, body=body.strip(), slide_id=slide if kind == "answer" else None)
    if action == "moderate":
        message, op = value.get("message_id"), value.get("op")
        if not isinstance(message, str) or not UUID_RE.fullmatch(message) or op not in MODERATION:
            raise LiveError(400, "Choose a message and what to do with it.")
        out.update(message_id=message, op=op)
    if action in ("mark", "missed", "record"):
        on = value.get("on")
        if not isinstance(on, bool):
            raise LiveError(400, "Say yes or no.")
        out.update(on=on)
    if action == "sum":
        slide, question = value.get("slide_id"), value.get("question")
        if not isinstance(slide, str) or not SLIDE_RE.fullmatch(slide):
            raise LiveError(400, "Choose the question on the screen.")
        if question is not None and (not isinstance(question, str) or len(question) > 1000):
            raise LiveError(400, "Choose the question on the screen.")
        out.update(slide_id=slide, question=(question or "").strip())
    # Never trust client-supplied role, permission, room, or business fields.
    return out


def when(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def lobby_open(access, now=None):
    """A scheduled class's room opens 15 minutes early and stays open through its planned time."""
    starts = when(access.get("starts_at"))
    if access.get("status") != "scheduled" or starts is None:
        return False
    now = now or datetime.now(timezone.utc)
    return starts - LOBBY <= now <= starts + timedelta(minutes=access.get("duration_minutes") or 60)


def authorize(action, access):
    if action in TEACHER_ACTIONS and access.get("teacher") is not True:
        raise LiveError(403, "Only your teaching team can manage this class.")
    # A recording is watched once the class is over, by its students and
    # its teaching team alike.
    if action == "watch":
        if access["status"] != "ended":
            raise LiveError(409, "The recording is ready after the class ends.")
        return
    # Ending again closes leftover connections; the slides can be sent to
    # who missed a class after it is over.
    if action in ("end", "missed") and access["status"] == "ended":
        return
    if access["status"] in ("ended", "cancelled"):
        raise LiveError(409, "This class has ended or was cancelled.")
    if action in ROOM_ACTIONS and access["status"] != "live" and not lobby_open(access):
        raise LiveError(409, "Your teacher has not started this class yet.")
    if action == "mark" and access["status"] != "live" and not lobby_open(access):
        raise LiveError(409, "Open the room first.")
    if action == "record" and access["status"] != "live":
        raise LiveError(409, "Start the class first.")
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
        if path in ("/rpc/academy_live_token_claim", "/rpc/academy_live_post"):
            detail = res.json() if res.content else {}
            if detail.get("code") == "P0001":
                raise LiveError(429, detail.get("message") if path.endswith("_post") and detail.get("message")
                                else "Please wait a few seconds and try joining again.")
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
            ("teacher", "session_id", "title", "mode")},
            # What the room shows: the lobby's clock, the lesson, who is teaching.
            **{k: access.get(k) for k in ("identity", "name", "status", "starts_at", "duration_minutes",
                                           "lesson_id", "teacher_name", "business_type", "course_id")}}


def provider():
    url, key, secret = settings()
    return api.LiveKitAPI(url, key, secret, timeout=ClientTimeout(total=10))


async def delete_room(rooms, name):
    try:
        await rooms.delete_room(api.DeleteRoomRequest(room=name))
    except api.TwirpError as exc:
        if exc.code != "not_found":
            raise


def room_metadata(access):
    return json.dumps({"title": access["title"], "mode": access["mode"], "status": "live"})


async def open_room(rooms, access, live=False):
    """Create the class's room (or find it open). Metadata is set only once the class is live,
    so a lobby join can never put a started class back into its lobby."""
    await rooms.create_room(api.CreateRoomRequest(name=access["room_name"],
        max_participants=access["max_participants"], empty_timeout=120, departure_timeout=60,
        **({"metadata": room_metadata(access)} if live else {})))
    if live:
        await rooms.update_room_metadata(api.UpdateRoomMetadataRequest(
            room=access["room_name"], metadata=room_metadata(access)))


async def send(rooms, access, topic, payload, to=None):
    await rooms.send_data(api.SendDataRequest(room=access["room_name"],
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        kind=api.DataPacket.Kind.RELIABLE, destination_identities=list(to or []), topic=topic))


async def teachers_in_room(rooms, access):
    try:
        found = await rooms.list_participants(api.ListParticipantsRequest(room=access["room_name"]))
    except api.TwirpError as exc:
        if exc.code == "not_found":
            return []
        raise
    return [p.identity for p in found.participants if p.identity.startswith("teacher_")]


# ─── What each person may see of a message ───────────────────────────
def full_view(row):
    return {k: row.get(k) for k in MESSAGE_FIELDS.split(",")}


def anonymous_answer(row):
    return {"id": row["id"], "kind": "answer", "body": row["body"], "slide_id": row.get("slide_id"),
            "onscreen_at": row.get("onscreen_at"), "created_at": row.get("created_at")}


def visible_to(row, access):
    """The message as this person may see it, or None."""
    if access.get("teacher") is True:
        return full_view(row)
    mine = row.get("identity") == access["identity"]
    if row.get("kind") == "answer":
        if mine:
            return full_view(row)
        return anonymous_answer(row) if row.get("onscreen_at") else None
    if row.get("status") == "shown" or (mine and row.get("status") == "held"):
        return full_view(row)
    return None


async def deliver(access, row):
    """Send a new message to whoever may see it. A failed delivery keeps the message
    (it is already saved and arrives with the history on the next join)."""
    public = row.get("kind") != "answer" and row.get("status") == "shown"
    try:
        async with provider() as live:
            if public:
                await send(live.room, access, TOPIC_MESSAGE, {"type": "msg", "message": full_view(row)})
            else:
                teachers = await teachers_in_room(live.room, access)
                if teachers:
                    await send(live.room, access, TOPIC_MESSAGE, {"type": "msg", "message": full_view(row)}, teachers)
        return True
    except Exception:
        return False


async def post_message(client, input, access):
    teacher = access.get("teacher") is True
    held = not teacher and input["kind"] != "answer" and bool(LINK_RE.search(input["body"]))
    row = await db(client, "POST", "/rpc/academy_live_post", {
        "p_session": access["session_id"], "p_identity": access["identity"], "p_name": access.get("name"),
        "p_teacher": teacher, "p_kind": input["kind"], "p_body": input["body"],
        "p_slide": input.get("slide_id"), "p_held": held})
    delivered = await deliver(access, row)
    return {"message": full_view(row), "held": row.get("status") == "held", "delivered": delivered}


async def history(client, access):
    rows = await db(client, "GET", "/academy_live_messages?session_id=eq." + access["session_id"]
                    + "&select=" + MESSAGE_FIELDS + "&order=created_at.desc&limit=400")
    seen = [v for v in (visible_to(r, access) for r in reversed(rows or [])) if v]
    return {"messages": seen}


async def moderate(client, input, access):
    path = "/academy_live_messages?id=eq." + input["message_id"] + "&session_id=eq." + access["session_id"]
    found = await db(client, "GET", path + "&select=" + MESSAGE_FIELDS)
    if not found:
        raise LiveError(404, "That message is no longer in this class.")
    row, op = found[0], input["op"]
    if op == "answered" and row["kind"] != "question":
        raise LiveError(400, "Only a question can be marked answered.")
    if op in ("onscreen", "offscreen") and row["kind"] != "answer":
        raise LiveError(400, "Only an answer goes on the screen.")
    if op in ("pin", "show") and row["kind"] == "answer":
        raise LiveError(400, "Put an answer on the screen instead.")
    now = datetime.now(timezone.utc).isoformat()
    change = {"hide": {"status": "hidden", "pinned": False}, "show": {"status": "shown"},
              "pin": {"status": "shown", "pinned": True}, "unpin": {"pinned": False},
              "answered": {"answered_at": now}, "onscreen": {"onscreen_at": now},
              "offscreen": {"onscreen_at": None}}[op]
    if op == "pin":
        await db(client, "PATCH", "/academy_live_messages?session_id=eq." + access["session_id"] + "&pinned=is.true",
                 {"pinned": False}, prefer="return=minimal")
    updated = await db(client, "PATCH", path + "&select=" + MESSAGE_FIELDS, change)
    row = updated[0] if updated else {**row, **change}
    event = {"hide": {"type": "hide", "id": row["id"]},
             "show": {"type": "msg", "message": full_view(row)},
             "pin": {"type": "pin", "message": full_view(row)},
             "unpin": {"type": "pin", "message": None, "id": row["id"]},
             "answered": {"type": "answered", "id": row["id"], "at": row.get("answered_at")},
             "onscreen": {"type": "onscreen", "message": anonymous_answer(row)},
             "offscreen": {"type": "offscreen", "id": row["id"]}}[op]
    try:
        async with provider() as live:
            await send(live.room, access, TOPIC_UPDATE, event)
    except Exception:
        pass  # saved; the room reads it with the history on reconnect
    return {"message": full_view(row)}


async def roster(client, access):
    enrolled = await db(client, "GET", "/academy_enrollments?select=id,contact_id&course_id=eq." + access["course_id"]
                        + "&business_id=eq." + access["business_id"] + "&status=in.(active,completed)"
                        + "&order=enrolled_at.asc&limit=500") or []
    names = {}
    contacts = sorted({e["contact_id"] for e in enrolled if e.get("contact_id")})
    for i in range(0, len(contacts), 80):
        chunk = contacts[i:i + 80]
        for c in await db(client, "GET", "/contacts?select=id,name&business_id=eq." + access["business_id"]
                          + "&id=in.(" + ",".join(chunk) + ")") or []:
            names[c["id"]] = (c.get("name") or "").strip()
    # Who is in the room (they tapped "I'm in the room", or a teacher
    # marked them), and whether the slides go to who isn't here.
    here = await db(client, "GET", "/academy_live_here?select=enrollment_id,marked_by&session_id=eq." + access["session_id"]) or []
    room = {h["enrollment_id"]: h["marked_by"] for h in here}
    night = await db(client, "GET", "/academy_live_sessions?select=send_missed,missed_sent_at,recording_status&id=eq."
                     + access["session_id"]) or [{}]
    import academy_recordings
    return {"students": [{"identity": "student_" + e["id"], "name": names.get(e.get("contact_id")) or "Student",
                          "room": room.get(e["id"])} for e in enrolled],
            "send_missed": bool(night[0].get("send_missed")), "missed_sent_at": night[0].get("missed_sent_at"),
            "recording": night[0].get("recording_status"), "can_record": academy_recordings.configured()}


async def mark_here(client, input, access):
    """A student says they're in the room ("here"), or a teacher marks or
    unmarks one ("mark"). Counted when the class ends (academy_class_nights)."""
    sid = access["session_id"]
    if input["action"] == "here":
        if access["teacher"]:
            raise LiveError(400, "Mark people in the room from People.")
        enrollment, by, on = access["identity"][8:], "self", True
    else:
        enrollment, by, on = input["identity"][8:], "teacher", input["on"]
        enrolled = await db(client, "GET", "/academy_enrollments?select=id&id=eq." + enrollment
                            + "&course_id=eq." + access["course_id"] + "&business_id=eq." + access["business_id"] + "&limit=1")
        if not enrolled:
            raise LiveError(403, "That student does not belong to this class.")
    if on:
        await db(client, "POST", "/academy_live_here?on_conflict=session_id,enrollment_id",
                 {"session_id": sid, "enrollment_id": enrollment, "marked_by": by},
                 prefer="resolution=ignore-duplicates,return=minimal")
    else:
        await db(client, "DELETE", "/academy_live_here?session_id=eq." + sid + "&enrollment_id=eq." + enrollment,
                 prefer="return=minimal")
    return {"ok": True, "room": on}


async def ask_missed(client, input, access):
    """The teacher's "Send tonight's slides to who wasn't here": sent once,
    after the class ends (academy_class_nights). Once sent, it stays sent."""
    rows = await db(client, "PATCH", "/academy_live_sessions?id=eq." + access["session_id"]
                    + "&missed_sent_at=is.null&select=send_missed,missed_sent_at", {"send_missed": input["on"]})
    if not rows:
        rows = await db(client, "GET", "/academy_live_sessions?select=send_missed,missed_sent_at&id=eq." + access["session_id"]) or [{}]
    return {"ok": True, "send_missed": bool(rows[0].get("send_missed")), "missed_sent_at": rows[0].get("missed_sent_at")}


async def sum_answers(client, input, access):
    """Chief sums up the answers to the question on the screen, for the
    teacher alone (academy_class_sum): only answers showing in the room
    (never one hidden, or held for the teacher), and only their words, never
    who wrote them. Only an ask that reaches the model counts against the
    night's limit."""
    import academy_class_sum
    import rate_limit
    rows = await db(client, "GET", "/academy_live_messages?select=body&session_id=eq." + access["session_id"]
                    + "&kind=eq.answer&status=eq.shown&slide_id=eq." + input["slide_id"]
                    + "&order=created_at.desc&limit=" + str(academy_class_sum.MAX_ANSWERS)) or []
    answers = [r.get("body") or "" for r in rows]
    if len([a for a in answers if a.strip()]) < academy_class_sum.MIN_ANSWERS:
        raise LiveError(409, "Wait for a few more answers first.")
    if not await asyncio.to_thread(rate_limit.allow_strict, "class_sum", access["session_id"]):
        raise LiveError(429, "Give it a few minutes, then ask Chief again.")
    try:
        return await academy_class_sum.summarize(client, access["business_id"], input["question"], answers)
    except academy_class_sum.SumError as e:
        raise LiveError(e.status, e.message) from None


async def start_recording(client, live, access, *, asked=False):
    """Record the night from its start (academy_recordings): once, when the
    business's storage is connected and the class's owner left recording on
    (or the teacher asked for it tonight). The night is claimed before
    LiveKit is asked, so two starts never make two files. Never raises: a
    recording that won't start never stops the class."""
    import academy_recordings
    cfg = academy_recordings.settings()
    if not cfg:
        return None
    sid = access["session_id"]
    key = academy_recordings.object_key(access["business_id"], access["course_id"], sid)
    claimed, egress_id = False, None
    try:
        if not asked:
            course = await db(client, "GET", "/academy_courses?select=record_live&id=eq." + access["course_id"]) or [{}]
            if course[0].get("record_live") is False:
                return None
        # Claim the night: only a night with no recording yet (or one that
        # didn't start) becomes "recording", and only one caller gets it.
        rows = await db(client, "PATCH", "/academy_live_sessions?id=eq." + sid
                        + "&or=(recording_status.is.null,recording_status.eq.failed)&select=id", {
                            "recording_status": "recording", "recording_egress_id": None, "recording_path": key,
                            "recording_started_at": datetime.now(timezone.utc).isoformat(), "recording_ended_at": None,
                            "recording_seconds": None, "recording_bytes": None})
        if not rows:
            now = await db(client, "GET", "/academy_live_sessions?select=recording_status&id=eq." + sid) or [{}]
            return now[0].get("recording_status")  # already recording, or ready: one a night
        claimed = True
        info = await live.egress.start_room_composite_egress(academy_recordings.egress_request(access["room_name"], key, cfg))
        egress_id = info.egress_id
        await db(client, "PATCH", "/academy_live_sessions?id=eq." + sid + "&recording_egress_id=is.null",
                 {"recording_egress_id": egress_id}, prefer="return=minimal")
        return "recording"
    except Exception:
        if not claimed:
            return None  # nothing started: the teacher can press Record
        if egress_id:
            # Started but not written down: stop it rather than leave a file
            # nobody can find.
            try:
                await live.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))
            except Exception:
                pass
        try:
            await db(client, "PATCH", "/academy_live_sessions?id=eq." + sid + "&recording_status=eq.recording",
                     {"recording_status": "failed"}, prefer="return=minimal")
        except Exception:
            pass
        return "failed"


async def stop_recording(client, live, access):
    """The teacher's Stop recording: the file so far is kept and is ready
    once LiveKit finishes it (egress_ended). It doesn't start again tonight.
    When LiveKit says the recording is already over, the night is set from
    what LiveKit knows of it, so it never stays "recording"."""
    import academy_recordings
    rows = await db(client, "GET", "/academy_live_sessions?select=recording_egress_id,recording_status&id=eq."
                    + access["session_id"]) or [{}]
    egress, status = rows[0].get("recording_egress_id"), rows[0].get("recording_status")
    if status != "recording" or not egress:
        return {"ok": True, "recording": status}
    try:
        await live.egress.stop_egress(api.StopEgressRequest(egress_id=egress))
        return {"ok": True, "recording": "stopping"}
    except api.TwirpError as exc:
        if exc.code not in ("not_found", "failed_precondition"):
            raise
    found = await live.egress.list_egress(api.ListEgressRequest(egress_id=egress))
    items = list(getattr(found, "items", []) or [])
    ended = items and items[0].status not in (api.EgressStatus.EGRESS_STARTING, api.EgressStatus.EGRESS_ACTIVE,
                                              api.EgressStatus.EGRESS_ENDING)
    fields = academy_recordings.ended_fields(items[0]) if ended else {"recording_status": "failed"}
    if not items or ended:
        await db(client, "PATCH", "/academy_live_sessions?recording_egress_id=eq." + egress + "&recording_status=eq.recording",
                 fields, prefer="return=minimal")
        return {"ok": True, "recording": fields["recording_status"]}
    return {"ok": True, "recording": "stopping"}  # still finishing: egress_ended will say


async def watch(client, access):
    """A link to an ended night's recording, signed for an hour: for a
    student of the class (their link) or its teaching team, nobody else."""
    import academy_recordings
    cfg = academy_recordings.settings()
    rows = await db(client, "GET", "/academy_live_sessions?select=recording_status,recording_path&id=eq."
                    + access["session_id"]) or [{}]
    if not cfg or rows[0].get("recording_status") != "ready" or not rows[0].get("recording_path"):
        raise LiveError(404, "This class wasn't recorded.")
    return {"url": academy_recordings.presign_get(rows[0]["recording_path"], cfg),
            "expires_in": academy_recordings.LINK_TTL}


async def run_action(client, input, authorization):
    action = input["action"]
    if action == "status":
        ready = configured()
        if ready:
            try:
                await db(client, "GET", "/academy_live_sessions?select=id&limit=0")
            except Exception:
                ready = False
        import academy_recordings
        return {"configured": ready, "recording": ready and academy_recordings.configured()}
    if not configured():
        raise LiveError(503, "Live classes are being connected. Please try again later.")
    access = await access_for(client, input, authorization)
    authorize(action, access)
    if action == "post":
        return await post_message(client, input, access)
    if action == "history":
        return await history(client, access)
    if action == "moderate":
        return await moderate(client, input, access)
    if action == "roster":
        return await roster(client, access)
    if action in ("here", "mark"):
        return await mark_here(client, input, access)
    if action == "missed":
        return await ask_missed(client, input, access)
    if action == "sum":
        return await sum_answers(client, input, access)
    if action == "watch":
        return await watch(client, access)
    if action == "join":
        await db(client, "POST", "/rpc/academy_live_token_claim",
                 {"p_session": access["session_id"], "p_identity": access["identity"]})
        # Recheck persisted permissions after claiming, so a concurrent block or
        # listen-only change observed here is reflected in the signed token.
        access = await access_for(client, input, authorization)
        authorize(action, access)
        if access["status"] != "live":
            async with provider() as live:
                await open_room(live.room, access)
        return mint_token(access)
    async with provider() as live:
        rooms = live.room
        session_path = "/academy_live_sessions?id=eq." + access["session_id"]
        if action == "start":
            await open_room(rooms, access, live=True)
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
            # Recorded from the start (Kevin 2026-10-17), once storage is in.
            recording = await start_recording(client, live, access)
            return {**mint_token(access), "recording": recording}
        if action == "record":
            if not input["on"]:
                return await stop_recording(client, live, access)
            import academy_recordings
            if not academy_recordings.configured():
                raise LiveError(503, "Recording isn't set up for this business yet.")
            recording = await start_recording(client, live, access, asked=True)
            if recording is None:
                raise LiveError(503, "The recording didn't start. Try again.")
            return {"ok": True, "recording": recording}
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
        if action == "lower":
            try:
                await rooms.update_participant(api.UpdateParticipantRequest(room=access["room_name"], identity=target,
                    attributes={"hand_raised": "false"}))
            except api.TwirpError as exc:
                if exc.code != "not_found":
                    raise
            return {"ok": True}
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
                # Inviting someone to speak also lowers their hand.
                await rooms.update_participant(api.UpdateParticipantRequest(room=access["room_name"], identity=target,
                    permission=api.ParticipantPermission(can_publish=publish, can_subscribe=True, can_publish_data=True,
                        can_publish_sources=[api.TrackSource.CAMERA, api.TrackSource.MICROPHONE] if publish else []),
                    **({"attributes": {"hand_raised": "false"}} if publish else {})))
            except api.TwirpError as exc:
                # The persisted permission also applies when the student rejoins.
                if exc.code != "not_found":
                    raise
        return {"ok": True}


@router.post("")
async def live_action(request: Request):
    try:
        input = parse_input(await bounded_body(request, 8192))
        async with httpx.AsyncClient() as client:
            result = await asyncio.wait_for(run_action(client, input, request.headers.get("authorization")), timeout=22)
        return JSONResponse(result, headers=NO_STORE)
    except LiveError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status, headers=NO_STORE)
    except Exception:
        return JSONResponse({"error": "The live service could not complete this action. Please retry."},
                            status_code=502, headers=NO_STORE)


async def record_event(client, event):
    if event.event == "egress_ended":
        # A class recording finished (academy_recordings): ready with its
        # length and size, or failed.
        info = event.egress_info
        egress = getattr(info, "egress_id", "") or ""
        if re.fullmatch(r"EG_[A-Za-z0-9]{1,64}", egress):
            import academy_recordings
            await db(client, "PATCH", "/academy_live_sessions?recording_egress_id=eq." + egress + "&recording_status=eq.recording",
                     academy_recordings.ended_fields(info), prefer="return=minimal")
        return
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

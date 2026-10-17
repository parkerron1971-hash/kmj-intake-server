"""Provider/DB boundaries are faked; JWTs and webhook signatures use the real SDK."""
import asyncio
import base64
import hashlib
import json
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from livekit import api

import academy_live_router as live

SID = "10000000-0000-4000-8000-000000000001"
COURSE = "20000000-0000-4000-8000-000000000002"
BIZ = "30000000-0000-4000-8000-000000000003"
STUDENT = "student_40000000-0000-4000-8000-000000000004"
PORTAL = "50000000-0000-4000-8000-000000000005"
KEY, SECRET = "test-key", "unit-test-secret-with-at-least-32-characters"


@pytest.fixture
def env(monkeypatch):
    for name, value in {"LIVEKIT_URL": "wss://live.example.test", "LIVEKIT_API_KEY": KEY,
                        "LIVEKIT_API_SECRET": SECRET, "SUPABASE_URL": "https://db.example.test",
                        "SUPABASE_ANON": "test-anon", "SUPABASE_SERVICE_ROLE_KEY": "test-service"}.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def client(env):
    app = FastAPI()
    app.include_router(live.router)
    with TestClient(app) as client:
        yield client


def access(**changes):
    return {"session_id": SID, "course_id": COURSE, "business_id": BIZ,
            "room_name": "class_" + SID, "identity": STUDENT, "name": "Student",
            "teacher": False, "can_publish": False, "status": "live",
            "mode": "broadcast", "max_participants": 30, "title": "Test class", **changes}


def input(action="join", **changes):
    return {"action": action, "session_id": SID, "portal_token": PORTAL, "identity": STUDENT, **changes}


@pytest.mark.parametrize("body", [{}, [], {"action": []}, {"action": "bad"},
    {"action": "join", "session_id": "bad"}, input(portal_token="bad"),
    input("remove", identity="teacher_" + SID)])
def test_invalid_request_rejected_before_db(client, monkeypatch, body):
    db = AsyncMock()
    monkeypatch.setattr(live, "db", db)
    response = client.post("/academy-live", json=body)
    assert response.status_code == 400
    db.assert_not_called()


def test_oversized_body(client):
    assert client.post("/academy-live", content="x" * 8193).status_code == 413
    assert client.post("/academy-live/webhook", content="x" * 262145).status_code == 413


def test_status_requires_schema_and_configuration(client, monkeypatch):
    monkeypatch.setattr(live, "db", AsyncMock(return_value=[]))
    response = client.post("/academy-live", json={"action": "status"})
    assert response.json() == {"configured": True}
    assert response.headers["cache-control"] == "no-store"
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=live.LiveError(503, "Missing migration")))
    assert client.post("/academy-live", json={"action": "status"}).json() == {"configured": False}
    monkeypatch.delenv("LIVEKIT_API_SECRET")
    assert client.post("/academy-live", json={"action": "status"}).json() == {"configured": False}
    assert client.post("/academy-live/webhook", content="{}").status_code == 503


@pytest.mark.parametrize("header", [None, "Bearer test-service", "Basic abc", "Bearer "])
def test_no_caller_cannot_use_service_role(env, header):
    with pytest.raises(live.LiveError) as error:
        asyncio.run(live.access_for(None, input(portal_token=None), header))
    assert error.value.status == 401


@pytest.mark.parametrize("portal,header,expected", [(PORTAL, "Bearer owner-jwt", "test-anon"),
                                                  (None, "Bearer owner-jwt", "owner-jwt")])
def test_access_rpc_uses_caller_not_service(env, monkeypatch, portal, header, expected):
    seen = []
    def transport(request):
        seen.append(request)
        return httpx.Response(200, json=access())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as db:
            await live.access_for(db, input(portal_token=portal), header)
    asyncio.run(run())
    assert seen[0].headers["authorization"] == "Bearer " + expected
    assert seen[0].headers["apikey"] == "test-anon"
    assert json.loads(seen[0].content) == {"p_session": SID, "p_token": portal}


@pytest.mark.parametrize("action", ["start", "end", "allow", "listen", "remove"])
def test_students_cannot_control_classes(client, monkeypatch, action):
    monkeypatch.setattr(live, "db", AsyncMock(return_value=access()))
    provider = AsyncMock()
    monkeypatch.setattr(live, "provider", provider)
    response = client.post("/academy-live", json=input(action, teacher=True, room_name="spoofed"))
    assert response.status_code == 403
    provider.assert_not_called()


@pytest.mark.parametrize("state", ["scheduled", "ended", "cancelled"])
def test_students_cannot_join_inactive_classes(client, monkeypatch, state):
    monkeypatch.setattr(live, "db", AsyncMock(return_value=access(status=state)))
    assert client.post("/academy-live", json=input()).status_code == 409


@pytest.mark.parametrize("teacher,publish,sources", [(False, False, []),
    (False, True, ["camera", "microphone"]),
    (True, True, ["camera", "microphone", "screen_share", "screen_share_audio"])])
def test_real_signed_token_has_only_room_specific_permissions(env, teacher, publish, sources):
    response = live.mint_token(access(teacher=teacher, can_publish=publish))
    token = response["participant_token"]
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], issuer=KEY)
    assert claims["exp"] - claims["nbf"] == 60
    assert claims["sub"] == STUDENT
    assert claims["video"]["room"] == "class_" + SID
    assert claims["video"]["canPublish"] is publish
    assert claims["video"]["canPublishSources"] == sources
    assert claims["video"]["canUpdateOwnMetadata"] is True
    for forbidden in ("roomAdmin", "roomCreate", "roomRecord", "roomList"):
        assert not claims["video"].get(forbidden)
    assert SECRET not in json.dumps(response)


def test_join_refreshes_permissions_after_throttle(client, monkeypatch):
    db = AsyncMock(side_effect=[access(can_publish=True), None, access(can_publish=False)])
    monkeypatch.setattr(live, "db", db)
    response = client.post("/academy-live", json=input())
    assert response.status_code == 200
    claims = jwt.decode(response.json()["participant_token"], SECRET, algorithms=["HS256"])
    assert claims["video"]["canPublish"] is False
    assert db.call_args_list[1].args[2] == "/rpc/academy_live_token_claim"


def test_throttle_failure_does_not_mint(client, monkeypatch):
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(), live.LiveError(429, "Wait")]))
    assert client.post("/academy-live", json=input()).status_code == 429


@pytest.fixture
def rooms(monkeypatch):
    rooms = SimpleNamespace(create_room=AsyncMock(), delete_room=AsyncMock(),
                            update_participant=AsyncMock(), remove_participant=AsyncMock(),
                            update_room_metadata=AsyncMock(), send_data=AsyncMock(),
                            list_participants=AsyncMock(return_value=SimpleNamespace(participants=[
                                SimpleNamespace(identity="teacher_" + SID), SimpleNamespace(identity=STUDENT)])))
    context = AsyncMock()
    context.__aenter__.return_value = SimpleNamespace(room=rooms)
    monkeypatch.setattr(live, "provider", lambda: context)
    return rooms


def test_start_creates_bounded_room_and_rechecks_access(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(teacher=True, status="scheduled"), [], access(teacher=True), None])
    monkeypatch.setattr(live, "db", db)
    response = client.post("/academy-live", json=input("start", portal_token=None), headers={"Authorization": "Bearer owner-jwt"})
    assert response.status_code == 200
    request = rooms.create_room.call_args.args[0]
    assert request.name == "class_" + SID
    assert request.max_participants == 30 and request.empty_timeout == 120
    assert "status=eq.scheduled" in db.call_args_list[1].args[2]
    # A room opened as a lobby is told the class is live.
    meta = rooms.update_room_metadata.call_args.args[0]
    assert meta.room == "class_" + SID and json.loads(meta.metadata)["status"] == "live"


def test_concurrent_cancellation_prevents_start_token(client, monkeypatch, rooms):
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(teacher=True), [], access(teacher=True, status="cancelled")]))
    response = client.post("/academy-live", json=input("start"))
    assert response.status_code == 409
    rooms.delete_room.assert_awaited_once()


@pytest.mark.parametrize("action", ["allow", "listen", "remove"])
def test_foreign_student_target_is_rejected(client, monkeypatch, rooms, action):
    db = AsyncMock(side_effect=[access(teacher=True), []])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input(action)).status_code == 403
    path = db.call_args_list[1].args[2]
    assert "course_id=eq." + COURSE in path and "business_id=eq." + BIZ in path
    rooms.update_participant.assert_not_called()
    rooms.remove_participant.assert_not_called()


@pytest.mark.parametrize("action", ["allow", "listen", "remove"])
def test_moderation_is_persisted_before_provider(client, monkeypatch, rooms, action):
    db = AsyncMock(side_effect=[access(teacher=True), [{"id": STUDENT[8:]}], []])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input(action)).status_code == 200
    saved = db.call_args_list[2].args[3]
    assert saved["blocked"] is (action == "remove")
    assert saved["can_publish"] is (action == "allow")
    if action != "remove":
        permission = rooms.update_participant.call_args.args[0].permission
        assert permission.can_publish is (action == "allow")
        assert list(permission.can_publish_sources) == ([api.TrackSource.CAMERA, api.TrackSource.MICROPHONE] if action == "allow" else [])


def test_end_closes_database_before_provider_and_supports_retry(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(teacher=True), [], access(teacher=True, status="ended"), []])
    monkeypatch.setattr(live, "db", db)
    rooms.delete_room.side_effect = [RuntimeError("private provider detail"), None]
    first = client.post("/academy-live", json=input("end"))
    assert first.status_code == 502 and "private" not in first.text
    assert db.call_args_list[1].args[3]["status"] == "ended"
    assert client.post("/academy-live", json=input("end")).status_code == 200


def signed_body(event="participant_joined"):
    body = json.dumps({"event": event, "createdAt": int(time.time()), "room": {"name": "class_" + SID},
                       "participant": {"sid": "PA_test", "identity": STUDENT, "name": "Student"}})
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    token = api.AccessToken(KEY, SECRET).with_sha256(digest).with_ttl(timedelta(minutes=1)).to_jwt()
    return body, token


def test_webhook_requires_valid_signature_and_original_body(client, monkeypatch):
    db = AsyncMock(return_value=[])
    monkeypatch.setattr(live, "db", db)
    body, token = signed_body()
    assert client.post("/academy-live/webhook", content=body).status_code == 401
    assert client.post("/academy-live/webhook", content=body + " ", headers={"Authorization": token}).status_code == 401
    db.assert_not_called()
    assert client.post("/academy-live/webhook", content=body, headers={"Authorization": token}).status_code == 200
    call = db.call_args.args
    assert call[2] == "/rpc/academy_live_attendance_event"
    assert call[3]["p_sid"] == "PA_test" and call[3]["p_joined"] and call[3]["p_left"] is None


def test_webhook_failure_requests_retry(client, monkeypatch):
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=RuntimeError("private DB error")))
    body, token = signed_body()
    response = client.post("/academy-live/webhook", content=body, headers={"Authorization": token})
    assert response.status_code == 500 and "private" not in response.text


def test_room_finished_closes_session_and_open_attendance(client, monkeypatch):
    db = AsyncMock(side_effect=[[{"id": SID}], []])
    monkeypatch.setattr(live, "db", db)
    body, token = signed_body("room_finished")
    assert client.post("/academy-live/webhook", content=body, headers={"Authorization": token}).status_code == 200
    assert db.call_args_list[0].args[3]["status"] == "ended"
    assert "left_at=is.null" in db.call_args_list[1].args[2]


def test_real_provider_client_can_be_constructed(env):
    async def run():
        async with live.provider() as client:
            assert client.room is not None  # no network request
    asyncio.run(run())


def test_router_registered_before_public_catchall():
    source = (Path(__file__).resolve().parents[1] / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert source.index("app.include_router(academy_live_router)") < source.index("app.include_router(public_site_router)")


def test_classroom_credentials_are_excluded_from_error_reports():
    from access_log_redaction import scrub_sentry_event
    event = {"request": {"url": "https://api.example.test/academy-live", "data": {"portal_token": PORTAL},
                         "headers": {"Authorization": "Bearer private"}, "query_string": "unused"}}
    result = scrub_sentry_event(event)
    assert result["request"] == {"url": "https://api.example.test/academy-live"}


# ─── The room: lobby, kept messages, hands, roster (2026-10-17) ──────
TEACHER = "teacher_60000000-0000-4000-8000-000000000006"
MSG = "70000000-0000-4000-8000-000000000007"


def soon(minutes):
    return (live.datetime.now(live.timezone.utc) + timedelta(minutes=minutes)).isoformat()


def message(**changes):
    return {"id": MSG, "identity": STUDENT, "display_name": "Dana", "teacher": False, "kind": "chat",
            "body": "Amen", "slide_id": None, "status": "shown", "pinned": False, "answered_at": None,
            "onscreen_at": None, "created_at": "2026-10-17T18:00:00Z", **changes}


def sent(rooms):
    """Every send_data the room got: (topic, payload, to)."""
    out = []
    for call in rooms.send_data.call_args_list:
        req = call.args[0]
        out.append((req.topic, json.loads(req.data.decode()), list(req.destination_identities)))
    return out


@pytest.mark.parametrize("body", [
    input("post", kind="shout", body="hi"), input("post", kind="chat", body="   "),
    input("post", kind="chat", body="x" * 1001), input("post", kind="answer", body="Yes"),
    input("post", kind="answer", body="Yes", slide_id="bad id!"),
    input("moderate", message_id="nope", op="hide"), input("moderate", message_id=MSG, op="delete"),
    input("lower", identity="teacher_" + SID)])
def test_room_requests_are_checked_before_db(client, monkeypatch, body):
    db = AsyncMock()
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=body).status_code == 400
    db.assert_not_called()


@pytest.mark.parametrize("minutes,ok", [(10, True), (-30, True), (20, False), (-70, False)])
def test_lobby_opens_fifteen_minutes_early_and_closes_after_the_planned_time(minutes, ok):
    assert live.lobby_open(access(status="scheduled", starts_at=soon(minutes), duration_minutes=60)) is ok
    assert live.lobby_open(access(status="live", starts_at=soon(minutes))) is False


def test_a_student_waits_in_the_lobby_without_making_the_class_live(client, monkeypatch, rooms):
    early = access(status="scheduled", starts_at=soon(10), duration_minutes=60)
    db = AsyncMock(side_effect=[early, None, early])
    monkeypatch.setattr(live, "db", db)
    response = client.post("/academy-live", json=input())
    assert response.status_code == 200
    assert response.json()["status"] == "scheduled" and response.json()["starts_at"]
    request = rooms.create_room.call_args.args[0]
    assert request.name == "class_" + SID and request.metadata == ""
    rooms.update_room_metadata.assert_not_called()
    assert not any("academy_live_sessions" in str(c.args[2]) for c in db.call_args_list)


def test_too_early_for_the_lobby(client, monkeypatch, rooms):
    monkeypatch.setattr(live, "db", AsyncMock(return_value=access(status="scheduled", starts_at=soon(40))))
    assert client.post("/academy-live", json=input()).status_code == 409
    assert client.post("/academy-live", json=input("post", kind="chat", body="hi")).status_code == 409
    rooms.create_room.assert_not_called()


def test_chat_is_kept_then_sent_to_everyone(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(name="Dana"), message()])
    monkeypatch.setattr(live, "db", db)
    response = client.post("/academy-live", json=input("post", kind="chat", body="  Amen  "))
    assert response.status_code == 200 and response.json()["held"] is False
    rpc = db.call_args_list[1].args
    assert rpc[2] == "/rpc/academy_live_post"
    assert rpc[3]["p_body"] == "Amen" and rpc[3]["p_held"] is False and rpc[3]["p_teacher"] is False
    assert rpc[3]["p_identity"] == STUDENT and rpc[3]["p_session"] == SID
    [(topic, payload, to)] = sent(rooms)
    assert topic == "class.msg" and payload["message"]["body"] == "Amen" and to == []


def test_a_students_link_waits_for_the_teacher(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(), message(status="held", body="see www.example.com")])
    monkeypatch.setattr(live, "db", db)
    response = client.post("/academy-live", json=input("post", kind="chat", body="see www.example.com"))
    assert response.json()["held"] is True
    assert db.call_args_list[1].args[3]["p_held"] is True
    [(_, _, to)] = sent(rooms)
    assert to == ["teacher_" + SID]  # only the teaching team in the room


def test_a_teachers_link_is_not_held(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(teacher=True, identity=TEACHER), message(identity=TEACHER, teacher=True)])
    monkeypatch.setattr(live, "db", db)
    client.post("/academy-live", json=input("post", portal_token=None, kind="chat", body="https://example.com/notes"),
                headers={"Authorization": "Bearer owner-jwt"})
    assert db.call_args_list[1].args[3]["p_held"] is False


def test_an_answer_goes_only_to_the_teaching_team(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(), message(kind="answer", slide_id="q3", body="Secure")])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("post", kind="answer", body="Secure", slide_id="q3")).status_code == 200
    assert db.call_args_list[1].args[3]["p_slide"] == "q3"
    [(_, _, to)] = sent(rooms)
    assert to == ["teacher_" + SID]


def test_a_saved_message_survives_a_failed_delivery(client, monkeypatch, rooms):
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(), message()]))
    rooms.send_data.side_effect = RuntimeError("provider detail")
    response = client.post("/academy-live", json=input("post", kind="chat", body="Amen"))
    assert response.status_code == 200 and response.json()["delivered"] is False
    assert "provider" not in response.text


def test_the_pace_limit_reads_as_plain_words(env):
    async def run():
        def transport(request):
            return httpx.Response(400, json={"code": "P0001", "message": "Give it a second before sending again."})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            await live.db(client, "POST", "/rpc/academy_live_post", {})
    with pytest.raises(live.LiveError) as error:
        asyncio.run(run())
    assert error.value.status == 429 and error.value.message == "Give it a second before sending again."


def test_history_shows_a_student_only_what_they_may_see(client, monkeypatch):
    other = "student_80000000-0000-4000-8000-000000000008"
    rows = [message(id="m6", identity=other, kind="answer", slide_id="q3", body="Loved", onscreen_at="2026-10-17T18:06:00Z"),
            message(id="m5", identity=other, kind="answer", slide_id="q3", body="Not shown"),
            message(id="m4", kind="answer", slide_id="q3", body="Mine"),
            message(id="m3", identity=other, status="hidden", body="Taken down"),
            message(id="m2", identity=other, status="held", body="Someone else's link"),
            message(id="m1b", status="held", body="My own link"),
            message(id="m1", identity=other, body="Amen")]
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(), rows]))
    seen = client.post("/academy-live", json=input("history")).json()["messages"]
    assert [m["id"] for m in seen] == ["m1", "m1b", "m4", "m6"]
    shown_answer = seen[-1]
    assert shown_answer["body"] == "Loved" and "identity" not in shown_answer and "display_name" not in shown_answer
    # The teaching team sees everything, with names.
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(teacher=True, identity=TEACHER), rows]))
    everything = client.post("/academy-live", json=input("history", portal_token=None),
                             headers={"Authorization": "Bearer owner-jwt"}).json()["messages"]
    assert len(everything) == len(rows) and all("display_name" in m for m in everything)


@pytest.mark.parametrize("action", ["moderate", "roster", "lower"])
def test_students_cannot_moderate_lower_or_read_the_roster(client, monkeypatch, rooms, action):
    db = AsyncMock(return_value=access())
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input(action, message_id=MSG, op="hide")).status_code == 403
    assert db.call_count == 1  # only the access check
    rooms.send_data.assert_not_called()
    rooms.update_participant.assert_not_called()


def test_pinning_one_message_unpins_the_last(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(teacher=True, identity=TEACHER), [message()], None, [message(pinned=True)]])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("moderate", message_id=MSG, op="pin")).status_code == 200
    unpin_all = db.call_args_list[2].args
    assert unpin_all[1] == "PATCH" and "pinned=is.true" in unpin_all[2] and unpin_all[3] == {"pinned": False}
    assert db.call_args_list[3].args[3] == {"status": "shown", "pinned": True}
    [(topic, payload, to)] = sent(rooms)
    assert topic == "class.upd" and payload["type"] == "pin" and to == []


def test_an_answer_goes_on_screen_without_a_name(client, monkeypatch, rooms):
    answer = message(kind="answer", slide_id="q3", body="Secure", display_name="Dana")
    db = AsyncMock(side_effect=[access(teacher=True, identity=TEACHER), [answer], [{**answer, "onscreen_at": "now"}]])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("moderate", message_id=MSG, op="onscreen")).status_code == 200
    [(_, payload, _)] = sent(rooms)
    assert payload["type"] == "onscreen" and payload["message"]["body"] == "Secure"
    assert "Dana" not in json.dumps(payload) and STUDENT not in json.dumps(payload)


@pytest.mark.parametrize("op,kind", [("onscreen", "chat"), ("answered", "chat"), ("pin", "answer")])
def test_moderation_fits_the_kind_of_message(client, monkeypatch, rooms, op, kind):
    db = AsyncMock(side_effect=[access(teacher=True, identity=TEACHER), [message(kind=kind, slide_id="q3")]])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("moderate", message_id=MSG, op=op)).status_code == 400
    assert db.call_count == 2
    rooms.send_data.assert_not_called()


def test_moderating_a_message_from_another_class_is_refused(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(teacher=True, identity=TEACHER), []])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("moderate", message_id=MSG, op="hide")).status_code == 404
    assert "session_id=eq." + SID in db.call_args_list[1].args[2]


def test_lowering_a_hand_changes_only_the_hand(client, monkeypatch, rooms):
    db = AsyncMock(side_effect=[access(teacher=True, identity=TEACHER), [{"id": STUDENT[8:]}]])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("lower")).status_code == 200
    request = rooms.update_participant.call_args.args[0]
    assert dict(request.attributes) == {"hand_raised": "false"} and not request.HasField("permission")
    assert db.call_count == 2  # nothing persisted for a hand


def test_inviting_someone_to_speak_lowers_their_hand(client, monkeypatch, rooms):
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(teacher=True), [{"id": STUDENT[8:]}], []]))
    assert client.post("/academy-live", json=input("allow")).status_code == 200
    assert dict(rooms.update_participant.call_args.args[0].attributes) == {"hand_raised": "false"}


def test_roster_names_every_enrolled_student(client, monkeypatch):
    enrolled = [{"id": f"9{i:07d}-0000-4000-8000-000000000000", "contact_id": f"c{i}"} for i in range(85)]
    contacts_a = [{"id": f"c{i}", "name": f" Person {i} "} for i in range(80)]
    contacts_b = [{"id": f"c{i}", "name": ""} for i in range(80, 85)]
    db = AsyncMock(side_effect=[access(teacher=True, identity=TEACHER), enrolled, contacts_a, contacts_b])
    monkeypatch.setattr(live, "db", db)
    students = client.post("/academy-live", json=input("roster")).json()["students"]
    assert len(students) == 85
    assert students[0] == {"identity": "student_" + enrolled[0]["id"], "name": "Person 0"}
    assert students[-1]["name"] == "Student"
    assert "business_id=eq." + BIZ in db.call_args_list[1].args[2] and "course_id=eq." + COURSE in db.call_args_list[1].args[2]
    assert all("business_id=eq." + BIZ in c.args[2] for c in db.call_args_list[2:])


def test_the_token_carries_what_the_room_shows(env):
    response = live.mint_token(access(starts_at="2026-10-17T18:00:00Z", lesson_id="L", teacher_name="Pastor Kevin",
                                      business_type="ministry"))
    assert response["starts_at"] == "2026-10-17T18:00:00Z" and response["teacher_name"] == "Pastor Kevin"
    assert response["business_type"] == "ministry" and response["lesson_id"] == "L"
    assert response["identity"] == STUDENT and "room_name" not in response and "business_id" not in response

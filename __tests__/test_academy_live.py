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
    assert client.post("/academy-live", content="x" * 4097).status_code == 413
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
                            update_participant=AsyncMock(), remove_participant=AsyncMock())
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

"""Class recordings (academy_recordings.py; the live room's start, "record"
and "watch", and LiveKit's egress_ended in academy_live_router.py).

Kevin, 2026-10-17, settled: recording on from the start. Pins: nothing is
recorded, or said to be, until the four storage settings are in; a class is
recorded from its start unless its owner turned recording off, once a
night, through our own page into the private bucket; a failed start never
stops the class; the teacher can stop it; a finished file is ready with its
length and size, a failed one failed; only a student of that class (their
link) or its teaching team gets a link, signed for an hour, and only to an
ended night's ready recording. The signing matches AWS's published example.
"""
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from livekit import api

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import academy_recordings as rec  # noqa: E402
import academy_live_router as live  # noqa: E402
from test_academy_live import BIZ, COURSE, SID, access, client, env, input, rooms  # noqa: E402,F401

STORAGE = {"CLASS_RECORDING_BUCKET": "lcc-classes", "CLASS_RECORDING_ACCESS_KEY_ID": "AKIDTEST",
           "CLASS_RECORDING_SECRET_ACCESS_KEY": "s3cr3t-test", "CLASS_RECORDING_ENDPOINT": "https://acct.r2.cloudflarestorage.com"}


@pytest.fixture
def storage(monkeypatch):
    for k, v in STORAGE.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def no_storage(monkeypatch):
    for k in STORAGE:
        monkeypatch.delenv(k, raising=False)


# ─── Settings, the request, the link ─────────────────────────────────

def test_nothing_is_recorded_until_all_four_settings_are_in(monkeypatch, storage):
    assert rec.configured()
    monkeypatch.setenv("CLASS_RECORDING_ENDPOINT", "http://acct.r2.cloudflarestorage.com")
    assert not rec.configured(), "an address that isn't https is no storage"
    monkeypatch.setenv("CLASS_RECORDING_ENDPOINT", STORAGE["CLASS_RECORDING_ENDPOINT"])
    monkeypatch.delenv("CLASS_RECORDING_SECRET_ACCESS_KEY")
    assert not rec.configured()


def test_the_class_is_recorded_through_our_page_into_the_private_bucket(storage):
    req = rec.egress_request("class_" + SID, rec.object_key(BIZ, COURSE, SID), rec.settings())
    assert req.room_name == "class_" + SID and req.custom_base_url == "https://system.mysolutionist.app/class-recorder"
    out = req.file_outputs[0]
    assert out.filepath == f"classes/{BIZ}/{COURSE}/{SID}.mp4" and out.file_type == api.EncodedFileType.MP4
    assert (out.s3.bucket, out.s3.endpoint, out.s3.region, out.s3.force_path_style) == (
        "lcc-classes", "https://acct.r2.cloudflarestorage.com", "auto", True)
    assert req.preset == api.EncodingOptionsPreset.H264_720P_30


def test_the_signing_matches_aws_published_example():
    # docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
    cfg = {"access_key": "AKIAIOSFODNN7EXAMPLE", "secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
           "endpoint": "https://examplebucket.s3.amazonaws.com", "bucket": "examplebucket"}
    url = rec.presign_get("test.txt", cfg, expires=86400, now=datetime(2013, 5, 24, tzinfo=timezone.utc), region="us-east-1",
                          host="examplebucket.s3.amazonaws.com", path="/test.txt")
    assert url.endswith("&X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404")


def test_a_link_is_the_bucket_path_for_an_hour(storage):
    url = rec.presign_get(rec.object_key(BIZ, COURSE, SID), rec.settings(), now=datetime(2026, 10, 22, 23, tzinfo=timezone.utc))
    u = urlparse(url)
    assert u.netloc == "acct.r2.cloudflarestorage.com" and u.path == f"/lcc-classes/classes/{BIZ}/{COURSE}/{SID}.mp4"
    q = parse_qs(u.query)
    assert q["X-Amz-Expires"] == ["3600"] and q["X-Amz-Credential"][0].startswith("AKIDTEST/20261022/auto/s3/")
    assert "s3cr3t" not in url


def test_a_finished_file_is_ready_and_anything_else_failed():
    done = SimpleNamespace(status=api.EgressStatus.EGRESS_COMPLETE,
                           file_results=[SimpleNamespace(size=52_000_000, duration=3_120 * 1_000_000_000)])
    got = rec.ended_fields(done)
    assert got["recording_status"] == "ready" and got["recording_seconds"] == 3120 and got["recording_bytes"] == 52_000_000
    assert rec.ended_fields(SimpleNamespace(status=api.EgressStatus.EGRESS_FAILED, file_results=[]))["recording_status"] == "failed"
    empty = SimpleNamespace(status=api.EgressStatus.EGRESS_COMPLETE, file_results=[SimpleNamespace(size=0, duration=0)])
    assert rec.ended_fields(empty)["recording_status"] == "failed", "an empty file is no recording"


# ─── The live room: start, stop, watch, LiveKit's word ───────────────

@pytest.fixture
def egress(monkeypatch):
    """LiveKit, faked: the room calls the start test already uses, and egress."""
    rooms = SimpleNamespace(create_room=AsyncMock(), delete_room=AsyncMock(), update_room_metadata=AsyncMock(),
                            list_participants=AsyncMock(return_value=SimpleNamespace(participants=[])))
    eg = SimpleNamespace(start_room_composite_egress=AsyncMock(return_value=SimpleNamespace(egress_id="EG_abc123")),
                         stop_egress=AsyncMock())
    context = AsyncMock()
    context.__aenter__.return_value = SimpleNamespace(room=rooms, egress=eg)
    monkeypatch.setattr(live, "provider", lambda: context)
    return eg


def _start_db(*after):
    """access, the PATCH live, access again, the token claim, then the recording's own calls."""
    return AsyncMock(side_effect=[access(teacher=True, status="scheduled"), [], access(teacher=True), None, *after])


def test_a_class_is_recorded_from_its_start_into_the_bucket(client, monkeypatch, egress, storage):
    db = _start_db([{"record_live": True}], [{"id": SID}], None)
    monkeypatch.setattr(live, "db", db)
    r = client.post("/academy-live", json=input("start"))
    assert r.status_code == 200 and r.json()["recording"] == "recording" and r.json()["participant_token"]
    req = egress.start_room_composite_egress.call_args.args[0]
    assert req.room_name == "class_" + SID and req.file_outputs[0].filepath == f"classes/{BIZ}/{COURSE}/{SID}.mp4"
    claim_path, claim = db.call_args_list[5].args[2], db.call_args_list[5].args[3]
    assert "or=(recording_status.is.null,recording_status.eq.failed)" in claim_path, "the night is claimed before LiveKit is asked"
    assert claim["recording_status"] == "recording" and claim["recording_path"] == f"classes/{BIZ}/{COURSE}/{SID}.mp4"
    assert db.call_args_list[6].args[3] == {"recording_egress_id": "EG_abc123"}
    assert "recording_egress_id=is.null" in db.call_args_list[6].args[2]


def test_without_storage_nothing_is_recorded(client, monkeypatch, egress, no_storage):
    db = _start_db()
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("start")).json()["recording"] is None
    egress.start_room_composite_egress.assert_not_called()


def test_the_owners_off_switch_holds(client, monkeypatch, egress, storage):
    db = _start_db([{"record_live": False}])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("start")).json()["recording"] is None
    egress.start_room_composite_egress.assert_not_called()


def test_two_starts_never_make_two_files(client, monkeypatch, egress, storage):
    # Someone else claimed the night first: no second egress, their status.
    db = _start_db([{"record_live": True}], [], [{"recording_status": "recording"}])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("start")).json()["recording"] == "recording"
    egress.start_room_composite_egress.assert_not_called()


def test_a_recording_that_wont_start_never_stops_the_class(client, monkeypatch, egress, storage):
    egress.start_room_composite_egress.side_effect = RuntimeError("egress unavailable")
    db = _start_db([{"record_live": True}], [{"id": SID}], None)
    monkeypatch.setattr(live, "db", db)
    r = client.post("/academy-live", json=input("start"))
    assert r.status_code == 200 and r.json()["participant_token"] and r.json()["recording"] == "failed"
    assert db.call_args_list[6].args[3] == {"recording_status": "failed"}
    assert "recording_status=eq.recording" in db.call_args_list[6].args[2]


def test_a_database_blip_before_the_claim_marks_nothing_failed(client, monkeypatch, egress, storage):
    db = _start_db(live.LiveError(503, "Class data is unavailable."))
    monkeypatch.setattr(live, "db", db)
    r = client.post("/academy-live", json=input("start"))
    assert r.status_code == 200 and r.json()["recording"] is None, "nothing started: the teacher can press Record"
    assert db.await_count == 5, "no failed written over a night that may be recording"
    egress.start_room_composite_egress.assert_not_called()


def test_the_teacher_stops_it_and_it_never_starts_a_second_file(client, monkeypatch, egress, storage):
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(teacher=True), [{"recording_egress_id": "EG_abc123", "recording_status": "recording"}]]))
    r = client.post("/academy-live", json=input("record", on=False))
    assert r.json() == {"ok": True, "recording": "stopping"}
    assert egress.stop_egress.call_args.args[0].egress_id == "EG_abc123"
    egress.stop_egress.reset_mock()
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(teacher=True), [{"recording_egress_id": "EG_abc123", "recording_status": "ready"}]]))
    assert client.post("/academy-live", json=input("record", on=False)).json() == {"ok": True, "recording": "ready"}
    egress.stop_egress.assert_not_called()
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(teacher=True), [], [{"recording_status": "ready"}]]))
    assert client.post("/academy-live", json=input("record", on=True)).json()["recording"] == "ready"
    egress.start_room_composite_egress.assert_not_called()


def test_a_stop_livekit_says_is_over_never_leaves_the_night_recording(client, monkeypatch, egress, storage):
    egress.stop_egress.side_effect = api.TwirpError("not_found", "egress not found", status=404)
    done = SimpleNamespace(status=api.EgressStatus.EGRESS_COMPLETE, file_results=[SimpleNamespace(size=9_000_000, duration=600 * 1_000_000_000)])
    egress.list_egress = AsyncMock(return_value=SimpleNamespace(items=[done]))
    db = AsyncMock(side_effect=[access(teacher=True), [{"recording_egress_id": "EG_abc123", "recording_status": "recording"}], None])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("record", on=False)).json()["recording"] == "ready"
    assert db.call_args_list[2].args[3]["recording_seconds"] == 600
    egress.list_egress = AsyncMock(return_value=SimpleNamespace(items=[]))
    db = AsyncMock(side_effect=[access(teacher=True), [{"recording_egress_id": "EG_abc123", "recording_status": "recording"}], None])
    monkeypatch.setattr(live, "db", db)
    assert client.post("/academy-live", json=input("record", on=False)).json()["recording"] == "failed"
    assert db.call_args_list[2].args[3] == {"recording_status": "failed"}


def test_a_student_cannot_stop_a_recording(client, monkeypatch, egress, storage):
    monkeypatch.setattr(live, "db", AsyncMock(return_value=access()))
    assert client.post("/academy-live", json=input("record", on=False)).status_code == 403
    egress.stop_egress.assert_not_called()


def test_a_student_watches_an_ended_nights_recording_by_a_signed_link(client, monkeypatch, storage):
    db = AsyncMock(side_effect=[access(status="ended"), [{"recording_status": "ready", "recording_path": f"classes/{BIZ}/{COURSE}/{SID}.mp4"}]])
    monkeypatch.setattr(live, "db", db)
    r = client.post("/academy-live", json=input("watch"))
    assert r.status_code == 200 and r.json()["expires_in"] == 3600
    u = urlparse(r.json()["url"])
    assert u.path == f"/lcc-classes/classes/{BIZ}/{COURSE}/{SID}.mp4" and "X-Amz-Signature=" in u.query
    assert "id=eq." + SID in db.call_args_list[1].args[2], "this night only"


@pytest.mark.parametrize("state, night, code", [
    ("live", {"recording_status": "recording", "recording_path": "k"}, 409),
    ("ended", {"recording_status": "failed", "recording_path": "k"}, 404),
    ("ended", {"recording_status": None, "recording_path": None}, 404),
])
def test_no_link_before_the_end_or_without_a_ready_file(client, monkeypatch, storage, state, night, code):
    monkeypatch.setattr(live, "db", AsyncMock(side_effect=[access(status=state), [night]]))
    assert client.post("/academy-live", json=input("watch")).status_code == code


def test_livekits_word_that_a_recording_finished_marks_it_ready(monkeypatch):
    db = AsyncMock()
    monkeypatch.setattr(live, "db", db)
    info = SimpleNamespace(egress_id="EG_abc123", status=api.EgressStatus.EGRESS_COMPLETE,
                           file_results=[SimpleNamespace(size=52_000_000, duration=3_120 * 1_000_000_000)])
    import asyncio
    asyncio.run(live.record_event(None, SimpleNamespace(event="egress_ended", egress_info=info, room=SimpleNamespace(name=""))))
    path, body = db.call_args.args[2], db.call_args.args[3]
    assert path == "/academy_live_sessions?recording_egress_id=eq.EG_abc123&recording_status=eq.recording"
    assert body["recording_status"] == "ready" and body["recording_seconds"] == 3120
    db.reset_mock()
    asyncio.run(live.record_event(None, SimpleNamespace(event="egress_ended", egress_info=SimpleNamespace(egress_id="x&y=1"), room=SimpleNamespace(name=""))))
    db.assert_not_called()


def test_the_room_says_whether_it_can_record(client, monkeypatch, storage):
    monkeypatch.setattr(live, "db", AsyncMock(return_value=[]))
    assert client.post("/academy-live", json={"action": "status"}).json() == {"configured": True, "recording": True}

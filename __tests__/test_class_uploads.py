"""Homework answered with a file (the last part of the Class Schedule design).

The database half (the private bucket, academy_item_file_target /
academy_item_attach / academy_item_my_file, the path guard) was rehearsed on
production in a rolled-back transaction; see docs/MIGRATIONS.md. These cover
what a file is judged to be from its bytes, where it is filed, and the three
routes: a student's upload and their own file by the class link, and the
teacher's file read as the teacher.
"""
import asyncio
import io
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import academy_work as aw
import account_lifecycle as al
import auth_supabase

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "3f2c9a10-1b2c-4d5e-8f90-1a2b3c4d5e6f"
ITEM = "7d1e2f30-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
TARGET = {"business_id": "009e9a2c-3e81-4bfc-a92a-205a8806aa99", "course_id": "c480f7f0-740d-4c78-9578-12f7e0150102",
          "enrollment_id": "11111111-2222-4333-8444-555555555555", "item_id": ITEM, "photo_only": False, "file_path": None}


def _jpeg(size=(40, 20), orientation=None, gps=False) -> bytes:
    img = Image.new("RGB", size, (200, 30, 90))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    if gps:
        exif[0x8825] = {1: "N", 2: (32.0, 45.0, 1.0), 3: "W", 4: (97.0, 19.0, 1.0)}
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


# ─── What a file is ──────────────────────────────────────────────────

def test_a_phone_photo_is_kept_upright_and_without_where_it_was_taken():
    raw = _jpeg((40, 20), orientation=6, gps=True)
    assert Image.open(io.BytesIO(raw)).getexif().get(0x8825), "the sample really carries a location"
    (data, mime, ext), words = aw.classify(raw)
    assert (mime, ext, words) == ("image/jpeg", "jpg", "")
    kept = Image.open(io.BytesIO(data))
    assert kept.size == (20, 40), "turned upright"
    assert not kept.getexif(), "no EXIF at all: no location, camera or time"
    assert "exif" not in kept.info


def test_a_big_photo_is_kept_no_bigger_than_it_is_shown():
    (data, _, _), _ = aw.classify(_jpeg((5000, 3000)))
    assert max(Image.open(io.BytesIO(data)).size) == aw.PHOTO_EDGE


def test_a_see_through_picture_stays_a_png():
    out = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(out, "PNG")
    (_, mime, ext), _ = aw.classify(out.getvalue())
    assert (mime, ext) == ("image/png", "png")


def test_a_broken_photo_or_an_iphone_heic_says_what_to_do():
    assert aw.classify(_jpeg()[:300]) == (None, aw.WORDS["unreadable"])
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64
    assert aw.classify(heic) == (None, aw.WORDS["heic"])
    assert aw.classify(b"") == (None, aw.WORDS["empty"])


@pytest.mark.parametrize("head, declared, want", [
    (b"%PDF-1.7\n", "", ("application/pdf", "pdf")),
    (b"\x00\x00\x00\x20ftypM4A \x00\x00", "", ("audio/mp4", "m4a")),
    (b"\x00\x00\x00\x20ftypisom\x00\x00", "audio/mp4", ("audio/mp4", "m4a")),
    (b"\x00\x00\x00\x20ftypisom\x00\x00", "video/mp4", ("video/mp4", "mp4")),
    (b"\x00\x00\x00\x14ftypqt  \x00\x00", "", ("video/quicktime", "mov")),
    (b"\x1a\x45\xdf\xa3\x01\x00", "audio/webm;codecs=opus", ("audio/webm", "webm")),
    (b"\x1a\x45\xdf\xa3\x01\x00", "", ("video/webm", "webm")),
    (b"ID3\x04\x00\x00", "", ("audio/mpeg", "mp3")),
    (b"OggS\x00\x02", "", ("audio/ogg", "ogg")),
    (b"RIFF\x24\x00\x00\x00WAVEfmt ", "", ("audio/wav", "wav")),
])
def test_files_are_named_by_their_bytes(head, declared, want):
    (data, mime, ext), words = aw.classify(head + b"\x00" * 64, declared)
    assert (mime, ext) == want and words == ""


def test_the_browsers_word_never_makes_a_file_acceptable():
    for blob, declared in ((b"<html><script>alert(1)</script>", "audio/mpeg"),
                           (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/png"),
                           (b"MZ\x90\x00 an exe", "video/mp4")):
        assert aw.classify(blob, declared) == (None, aw.WORDS["unknown"])


def test_a_photo_homework_takes_only_a_photo_and_sizes_are_capped():
    assert aw.classify(b"%PDF-1.7\n" + b"0" * 64, photo_only=True) == (None, aw.WORDS["photo_only"])
    assert aw.classify(b"%PDF-1.7\n" + b"0" * (20 * aw.MB)) == (None, aw.WORDS["too_big"])
    assert aw.classify(b"\x00\x00\x00\x20ftypisom" + b"0" * (49 * aw.MB))[1] == ""
    assert aw.classify(b"ID3\x04" + b"0" * (25 * aw.MB)) == (None, aw.WORDS["too_big"])


def test_where_a_file_is_filed_and_what_the_teacher_reads_it_as():
    path = aw.object_path(TARGET, "jpg")
    assert path.startswith(f"{TARGET['business_id']}/{TARGET['course_id']}/{TARGET['enrollment_id']}-{ITEM}-")
    assert aw._PATH.fullmatch(path)
    with pytest.raises(ValueError):
        aw.object_path({**TARGET, "item_id": "../../other"}, "jpg")
    assert aw.display_name("../../etc/My Verse Card.HEIC", "jpg") == "My Verse Card.jpg"
    assert aw.display_name("<script>.png", "png") == "script_.png"
    assert aw.display_name("", "pdf") == "file.pdf"


def test_the_database_and_this_module_agree_on_the_path_and_who_may_call():
    sql = (ROOT / "supabase/APPLY-2026-10-18-academy-uploads.sql").read_text(encoding="utf-8")
    assert aw._PATH.pattern in sql, "the column's check and the module's pattern are the same pattern"
    for fn in ("academy_item_file_target(uuid, uuid)", "academy_item_attach(uuid, uuid, text, text, text, bigint)",
               "academy_item_my_file(uuid, uuid)"):
        assert f"revoke all on function public.{fn} from public, anon, authenticated;" in sql
        assert f"grant execute on function public.{fn} to service_role;" in sql
    assert "values ('academy-work', 'academy-work', false" in sql and "public = false" in sql
    assert "create policy" not in sql.lower(), "the bucket has no storage policies: only the service role"
    assert "academy-work" in al.STORAGE_BUCKETS, "a deleted account's homework files go with it"


# ─── The routes ──────────────────────────────────────────────────────

class _Calls:
    def __init__(self, target=TARGET, attach=None, mine=None):
        self.rpc, self.stored, self.removed = [], [], []
        self.answers = {"academy_item_file_target": target, "academy_item_my_file": mine,
                        "academy_item_attach": attach or {"old_path": None, "file_name": "x", "file_type": "image/jpeg", "file_size": 1}}


@pytest.fixture
def app(monkeypatch):
    calls = _Calls()

    async def rpc(client, name, body):
        calls.rpc.append((name, body))
        ans = calls.answers[name]
        return (None, ans) if isinstance(ans, str) else (ans, "")

    async def store(client, path, blob, mime):
        calls.stored.append((path, mime, len(blob)))
        return ""

    async def remove(client, path):
        calls.removed.append(path)

    monkeypatch.setattr(aw, "_rpc", rpc)
    monkeypatch.setattr(aw, "_store", store)
    monkeypatch.setattr(aw, "_remove", remove)
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key, **k: True)
    a = FastAPI()
    a.include_router(aw.router)
    a.dependency_overrides[auth_supabase.require_user_session] = lambda: auth_supabase.UserSession(
        user=auth_supabase.AuthedUser(id="u1", email=None, role="authenticated"), token="teacher-jwt")
    return TestClient(a), calls


def _post(client, blob, name="IMG_0042.jpg", ctype="image/jpeg", token=TOKEN, item=ITEM):
    return client.post(f"/academy-work/{token}/{item}", files={"file": (name, blob, ctype)})


def test_a_student_hands_in_a_photo(app):
    client, calls = app
    calls.answers["academy_item_attach"] = {"old_path": f"{TARGET['business_id']}/{TARGET['course_id']}/old.jpg",
                                            "file_name": "IMG_0042.jpg", "file_type": "image/jpeg", "file_size": 900}
    r = _post(client, _jpeg(gps=True))
    assert r.status_code == 200, r.text
    assert r.json()["file_name"] == "IMG_0042.jpg"
    (path, mime, size), = calls.stored
    assert mime == "image/jpeg" and aw._PATH.fullmatch(path)
    attach = dict(calls.rpc)["academy_item_attach"]
    assert attach["p_path"] == path and attach["p_type"] == "image/jpeg" and attach["p_size"] == size
    assert attach["p_name"] == "IMG_0042.jpg" and attach["p_token"] == TOKEN
    assert calls.removed == [f"{TARGET['business_id']}/{TARGET['course_id']}/old.jpg"], "the file it replaced is deleted"


def test_a_file_the_database_refuses_is_not_left_behind(app):
    client, calls = app
    calls.answers["academy_item_attach"] = "That file isn't filed under this student"
    r = _post(client, b"%PDF-1.7\n" + b"0" * 100, "notes.pdf", "application/pdf")
    assert r.status_code == 502
    assert calls.removed == [calls.stored[0][0]], "stored, refused, deleted again"


@pytest.mark.parametrize("said, status, words", [
    ("Classroom unavailable", 404, "Classroom unavailable"),
    ("Not open yet", 400, "This week isn't open yet."),
    ("This one doesn't take a file", 400, "This homework doesn't take a file."),
])
def test_the_link_and_the_item_are_checked_before_a_byte_is_stored(app, said, status, words):
    client, calls = app
    calls.answers["academy_item_file_target"] = said
    r = _post(client, _jpeg())
    assert (r.status_code, r.json()["detail"]) == (status, words)
    assert not calls.stored


def test_a_photo_homework_turns_a_pdf_away(app):
    client, calls = app
    calls.answers["academy_item_file_target"] = {**TARGET, "photo_only": True}
    r = _post(client, b"%PDF-1.7\n" + b"0" * 100, "x.pdf", "application/pdf")
    assert (r.status_code, r.json()["detail"]) == (400, aw.WORDS["photo_only"]) and not calls.stored


def test_a_link_that_isnt_a_link_never_reaches_the_database(app):
    client, calls = app
    assert _post(client, _jpeg(), token="not-a-link").status_code == 404
    assert _post(client, _jpeg(), item="../../x").status_code == 404
    assert not calls.rpc


def test_too_many_uploads_wait(app, monkeypatch):
    client, calls = app
    import rate_limit
    keys = []
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key, **k: keys.append((bucket, key)) or False)
    assert _post(client, _jpeg()).status_code == 429 and not calls.rpc
    assert keys[0][0] == "academy_work_upload" and TOKEN not in keys[0][1], "the limiter keeps a hash, never the link"
    for bucket in ("academy_work_upload", "academy_work_upload_ip", "academy_work_file"):
        assert bucket in rate_limit._LIMITS


def test_the_student_opens_their_own_file_by_their_link(app, monkeypatch):
    client, calls = app
    monkeypatch.setattr(aw.storage_links, "signed_url", _signed)
    assert client.get(f"/academy-work/{TOKEN}/{ITEM}").status_code == 404, "no file yet"
    calls.answers["academy_item_my_file"] = {"file_path": aw.object_path(TARGET, "jpg"), "file_name": "a.jpg", "file_type": "image/jpeg"}
    r = client.get(f"/academy-work/{TOKEN}/{ITEM}")
    assert r.status_code == 200 and r.json()["url"].startswith("https://signed/") and r.json()["file_type"] == "image/jpeg"


def test_the_teacher_reads_the_file_as_themselves(app, monkeypatch):
    client, _ = app
    import sb_clients
    seen = []
    row = {"file_path": aw.object_path(TARGET, "m4a"), "file_name": "voice.m4a", "file_type": "audio/mp4"}
    monkeypatch.setattr(sb_clients, "sb_get_as_user", lambda path, jwt: seen.append((path, jwt)) or ([row] if jwt == "teacher-jwt" else []))
    monkeypatch.setattr(aw.storage_links, "signed_url", _signed)
    work = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    r = client.get(f"/academy-work-file/{work}")
    assert r.status_code == 200 and r.json()["file_name"] == "voice.m4a"
    assert seen == [(f"/academy_item_work?id=eq.{work}&select=file_path,file_name,file_type&limit=1", "teacher-jwt")]
    monkeypatch.setattr(sb_clients, "sb_get_as_user", lambda path, jwt: [])
    assert client.get(f"/academy-work-file/{work}").status_code == 404, "not their class: the policy shows nothing"


async def _signed(client, bucket, path, ttl=0, download_as=None):
    assert bucket == aw.BUCKET and ttl == aw.SIGNED_TTL
    return f"https://signed/{path}"

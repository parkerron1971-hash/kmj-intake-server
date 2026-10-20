# __tests__/test_worship_media_router.py
#
# The church's pictures and videos for Sunday's screens
# (worship_media_router.py). Pins:
#   * the switch and seats: owner/admin/manager upload and take out; any
#     seat lists; a stranger gets 404
#   * an upload slot names one object under the church's own prefix in the
#     public bucket; types and sizes outside the rules are refused before a
#     slot is made; the library has a 3 GB allowance
#   * nothing is ready until the stored file is read back: the size has to
#     match, a picture has to open, a video has to start like one; a file
#     that lies about itself is deleted
#   * a list never shows an upload that hasn't been checked
#   * taking one out removes its file

import io
import pathlib
import sys
import uuid as uuidlib
from urllib.parse import parse_qsl

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import sb_clients
import worship_team
import worship_media_router as wm
from auth_supabase import AuthedUser, require_user

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER_EMAIL = "kmjcreativesolution@gmail.com"
PEOPLE = {
    "owner": AuthedUser(id="u-owner", email=OWNER_EMAIL, role="authenticated"),
    "member": AuthedUser(id="u-member", email="jas@lovecity.org", role="authenticated"),
    "stranger": AuthedUser(id="u-stranger", email="who@else.org", role="authenticated"),
}
SEATS = {("u-owner", BIZ): "owner", ("u-member", BIZ): "member"}


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (40, 10, 50)).save(buf, "PNG")
    return buf.getvalue()


class FakeDb:
    def __init__(self):
        self.rows = []

    @staticmethod
    def _f(path):
        return [(k, v) for k, v in parse_qsl(path.partition("?")[2]) if k not in ("select", "order", "limit")]

    def _match(self, r, f):
        for k, v in f:
            if v == "is.null" and r.get(k) is not None:
                return False
            if v.startswith("eq.") and str(r.get(k)) != v[3:]:
                return False
        return True

    def get(self, path, **_):
        return [dict(r) for r in self.rows if self._match(r, self._f(path))]

    def post(self, path, body, prefer=None, **_):
        row = {"archived_at": None, "url": None, **body}
        self.rows.append(row)
        return [dict(row)]

    def patch(self, path, body):
        hit = [r for r in self.rows if self._match(r, self._f(path))]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]


@pytest.fixture
def api(monkeypatch):
    db = FakeDb()
    store = {"files": {}, "removed": []}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("SUPABASE_URL", "https://abcd.supabase.co")
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setattr(wm, "upload_token", lambda name: "tok-" + name[-8:])
    monkeypatch.setattr(wm, "stored_size", lambda name: len(store["files"][name]) if name in store["files"] else None)
    monkeypatch.setattr(wm, "read_start", lambda name, limit: (store["files"].get(name) or b"")[:limit] if limit else store["files"].get(name))
    monkeypatch.setattr(wm, "remove_object", lambda name: store["removed"].append(name))

    # Seats; nobody here is on a church's ChurchSavvy team (test_worship_team.py is).
    monkeypatch.setattr(worship_team, "role_of", lambda biz, uid: SEATS.get((uid, biz)))
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    app.include_router(wm.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    return db, store, as_


def start(as_, who="owner", **body):
    return as_(who).post("/worship/media/start", json={"business_id": BIZ, **body})


def test_a_picture_goes_up_and_is_checked(api):
    db, store, as_ = api
    data = png_bytes()
    r = start(as_, name="Stage photo", mime="image/png", bytes=len(data))
    assert r.status_code == 200, r.text
    slot = r.json()["upload"]
    media = r.json()["media"]
    assert slot["bucket"] == "business-assets" and slot["chunk_size"] == 6 * 1024 * 1024
    assert slot["object_name"].startswith(BIZ + "/worship-") and slot["object_name"].endswith(".png")
    assert slot["endpoint"] == "https://abcd.storage.supabase.co/storage/v1/upload/resumable/sign"
    # Not uploaded yet: not finished, and not in the list.
    assert as_("owner").post(f"/worship/media/{media['id']}/finish", json={"business_id": BIZ}).status_code == 409
    assert as_("member").get(f"/worship/media?business_id={BIZ}").json()["media"] == []
    store["files"][slot["object_name"]] = data
    done = as_("owner").post(f"/worship/media/{media['id']}/finish", json={"business_id": BIZ})
    assert done.status_code == 200 and done.json()["media"]["status"] == "ready"
    assert done.json()["media"]["url"] == f"https://abcd.supabase.co/storage/v1/object/public/business-assets/{slot['object_name']}"
    listed = as_("member").get(f"/worship/media?business_id={BIZ}").json()
    assert [m["name"] for m in listed["media"]] == ["Stage photo"] and listed["can_write"] is False


def test_a_video_starts_like_one(api):
    db, store, as_ = api
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200
    r = start(as_, name="The Making promo", mime="video/mp4", bytes=len(mp4))
    slot, media = r.json()["upload"], r.json()["media"]
    store["files"][slot["object_name"]] = mp4
    assert as_("owner").post(f"/worship/media/{media['id']}/finish", json={"business_id": BIZ}).json()["media"]["kind"] == "video"


def test_a_file_that_lies_is_removed(api):
    db, store, as_ = api
    html = b"<html><script>alert(1)</script></html>"
    r = start(as_, name="not a video", mime="video/mp4", bytes=len(html))
    slot, media = r.json()["upload"], r.json()["media"]
    store["files"][slot["object_name"]] = html
    bad = as_("owner").post(f"/worship/media/{media['id']}/finish", json={"business_id": BIZ})
    assert bad.status_code == 400 and "removed" in bad.json()["detail"]
    assert store["removed"] == [slot["object_name"]]
    # A "PNG" that starts right but doesn't open is refused too.
    fake = b"\x89PNG\r\n\x1a\n" + b"garbage" * 10
    r2 = start(as_, name="broken", mime="image/png", bytes=len(fake))
    store["files"][r2.json()["upload"]["object_name"]] = fake
    assert as_("owner").post(f"/worship/media/{r2.json()['media']['id']}/finish", json={"business_id": BIZ}).status_code == 400


@pytest.mark.parametrize("body, status, words", [
    ({"mime": "text/html", "bytes": 10}, 400, "PNG, JPG or WebP"),
    ({"mime": "image/png", "bytes": 21 * 1024 * 1024}, 400, "at most 20 MB"),
    ({"mime": "video/mp4", "bytes": 101 * 1024 * 1024}, 400, "at most 100 MB"),
    ({"mime": "video/mp4", "bytes": 0}, 400, "at most 100 MB"),
])
def test_refused_before_a_slot(api, body, status, words):
    db, store, as_ = api
    r = start(as_, **body)
    assert r.status_code == status and words in r.json()["detail"]
    assert db.rows == []


def test_the_library_allowance(api, monkeypatch):
    db, store, as_ = api
    monkeypatch.setattr(wm, "LIBRARY_BYTES", 100)
    db.rows.append({"id": "x", "business_id": BIZ, "status": "ready", "bytes": 90, "archived_at": None})
    r = start(as_, mime="image/png", bytes=20)
    assert r.status_code == 409 and "full" in r.json()["detail"]


def test_seats(api, monkeypatch):
    db, store, as_ = api
    assert start(as_, "member", mime="image/png", bytes=10).status_code == 403
    assert as_("stranger").get(f"/worship/media?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("WORSHIP_SONGS", "owner")
    assert as_("member").get(f"/worship/media?business_id={BIZ}").status_code == 404


def test_taking_one_out_removes_its_file(api):
    db, store, as_ = api
    data = png_bytes()
    r = start(as_, name="Old flyer", mime="image/png", bytes=len(data))
    slot, media = r.json()["upload"], r.json()["media"]
    store["files"][slot["object_name"]] = data
    as_("owner").post(f"/worship/media/{media['id']}/finish", json={"business_id": BIZ})
    assert as_("member").delete(f"/worship/media/{media['id']}?business_id={BIZ}").status_code == 403
    assert as_("owner").delete(f"/worship/media/{media['id']}?business_id={BIZ}").json() == {"ok": True}
    assert store["removed"] == [slot["object_name"]]
    assert as_("owner").get(f"/worship/media?business_id={BIZ}").json()["media"] == []

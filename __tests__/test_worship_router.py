# __tests__/test_worship_router.py
#
# The song library and Scripture on the spot over HTTP (worship_router.py).
# Pins:
#   * the switch: WORSHIP_SONGS=owner opens it to the platform owner only,
#     everyone else gets a 404; on opens it; off closes it for everyone
#   * seats: anyone with a seat reads, only owner/admin/manager write, a
#     stranger gets the same 404 as a church that doesn't exist
#   * words become sections and the sung order; a SongSelect footer fills
#     the CCLI number; orders keep only parts the song still has
#   * a failed read is a 503, never an empty library
#   * a church's own Proclaim files come over once; running it again adds
#     nothing; files that aren't Proclaim's are refused
#   * the router is mounted before the public site's catch-all

import io
import json
import pathlib
import sys
import uuid as uuidlib
from urllib.parse import parse_qsl

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import sb_clients
import worship_router as wr
from auth_supabase import AuthedUser, require_user
from test_worship_proclaim import build as build_proclaim

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER_BIZ = "22222222-2222-4222-8222-222222222222"
OWNER_EMAIL = "kmjcreativesolution@gmail.com"
PEOPLE = {
    "owner": AuthedUser(id="u-owner", email=OWNER_EMAIL, role="authenticated"),
    "manager": AuthedUser(id="u-manager", email="pat@lovecity.org", role="authenticated"),
    "member": AuthedUser(id="u-member", email="jas@lovecity.org", role="authenticated"),
    "stranger": AuthedUser(id="u-stranger", email="who@else.org", role="authenticated"),
}
SEATS = {("u-owner", BIZ): "owner", ("u-manager", BIZ): "manager", ("u-member", BIZ): "member"}

WORDS = """Verse 1
When peace like a river attendeth my way,
When sorrows like sea billows roll;

Refrain
It is well with my soul,
It is well, it is well with my soul.

Verse 2
Though Satan should buffet, though trials should come,
Let this blest assurance control,

Refrain
"""


class FakeSongs:
    """sb_*_as_service for /worship_songs with eq./is.null filters. fail=True: every call fails."""

    def __init__(self):
        self.rows = []
        self.fail = False

    @staticmethod
    def _filters(path):
        q = path.split("?", 1)[1] if "?" in path else ""
        out = []
        for k, v in parse_qsl(q, keep_blank_values=True):
            if k in ("select", "order", "limit"):
                continue
            out.append((k, v))
        return out

    def _match(self, row, filters):
        for k, v in filters:
            if v == "is.null":
                if row.get(k) is not None:
                    return False
            elif v.startswith("eq."):
                if str(row.get(k)) != v[3:]:
                    return False
        return True

    def get(self, path, **_):
        if self.fail or not path.startswith("/worship_songs"):
            return None if self.fail else []
        return [dict(r) for r in self.rows if self._match(r, self._filters(path))]

    def post(self, path, body, prefer=None, **_):
        """Like sb_clients._sync_request: a refused insert is None, and so is a
        successful one sent with return=minimal (PostgREST answers 201 with an
        empty body, which the helper reads as None)."""
        if self.fail:
            return None
        items = body if isinstance(body, list) else [body]
        made = []
        for item in items:
            row = {"id": str(uuidlib.uuid4()), "archived_at": None, "needs_title": False, "authors": "", "copyright": "",
                   "public_domain": False, "song_key": None, "tempo": None, "ccli_number": None, "lines_per_slide": 2,
                   "source": "typed", "source_ref": "", "times_sung": {}, "last_sung": None, **item}
            if row["source_ref"] and any(r["source_ref"] == row["source_ref"] and r["business_id"] == row["business_id"]
                                         and r["source"] == row["source"] for r in self.rows + made):
                return None  # the unique index refuses the whole batch
            made.append(row)
        self.rows.extend(made)
        return [dict(r) for r in made] if prefer == "return=representation" else None

    def patch(self, path, body):
        if self.fail:
            return None
        hit = [r for r in self.rows if self._match(r, self._filters(path))]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]


@pytest.fixture
def api(monkeypatch):
    db = FakeSongs()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.delenv("WORSHIP_SONGS", raising=False)

    def fake_access(biz, user, min_role="viewer"):
        role = SEATS.get((user.id, biz))
        if not role:
            raise HTTPException(404, "Not Found")
        return role

    monkeypatch.setattr(wr, "assert_access", fake_access)
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    app.include_router(wr.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    return db, as_


def add(as_, who="owner", **body):
    return as_(who).post("/worship/songs", json={"business_id": BIZ, **body})


def test_the_switch_opens_it_to_the_owner_first(api, monkeypatch):
    db, as_ = api
    assert as_("owner").get(f"/worship/songs?business_id={BIZ}").status_code == 200
    assert as_("manager").get(f"/worship/songs?business_id={BIZ}").status_code == 404
    assert as_("manager").get(f"/worship/status?business_id={BIZ}").json() == {"enabled": False, "can_write": False}
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    assert as_("manager").get(f"/worship/status?business_id={BIZ}").json() == {"enabled": True, "can_write": True}
    assert as_("member").get(f"/worship/status?business_id={BIZ}").json() == {"enabled": True, "can_write": False}
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert as_("owner").get(f"/worship/songs?business_id={BIZ}").status_code == 404
    assert as_("owner").get("/worship/scripture?q=rom 8 28").status_code == 404


def test_seats_read_and_staff_write(api, monkeypatch):
    db, as_ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    assert add(as_, "manager", title="It Is Well With My Soul", words=WORDS).status_code == 200
    assert as_("member").get(f"/worship/songs?business_id={BIZ}").json()["can_write"] is False
    assert add(as_, "member", title="Mine", words=WORDS).status_code == 403
    assert as_("stranger").get(f"/worship/songs?business_id={BIZ}").status_code == 404
    assert as_("owner").get(f"/worship/songs?business_id={OTHER_BIZ}").status_code == 404


def test_pasted_words_become_sections_and_the_sung_order(api):
    db, as_ = api
    r = add(as_, title="It Is Well With My Soul", words=WORDS, public_domain=True, song_key="D")
    song = r.json()["song"]
    assert [s["label"] for s in song["sections"]] == ["Verse 1", "Refrain", "Verse 2"]
    labels = {s["id"]: s["label"] for s in song["sections"]}
    assert [labels[i] for i in song["arrangements"][0]["order"]] == ["Verse 1", "Refrain", "Verse 2", "Refrain"]
    assert song["has_words"] and song["public_domain"] and song["song_key"] == "D"
    listed = as_("owner").get(f"/worship/songs?business_id={BIZ}").json()["songs"]
    assert listed[0]["title"] == "It Is Well With My Soul" and "sections" not in listed[0]


def test_a_songselect_file_fills_title_and_ccli(api):
    db, as_ = api
    text = "Holy, Holy, Holy\n\nVerse 1\nHoly, holy, holy! Lord God Almighty!\n\nCCLI Song # 1234567\nReginald Heber | John Bacchus Dykes\n© Public Domain\nCCLI License # 7654321\n"
    song = add(as_, words=text, source="songselect").json()["song"]
    assert song["title"] == "Holy, Holy, Holy" and song["ccli_number"] == "1234567"
    assert song["authors"] == "Reginald Heber | John Bacchus Dykes" and song["source"] == "songselect"


@pytest.mark.parametrize("body, message", [
    ({"words": "just some words\nwith no name"}, "Give the song a name"),
    ({"title": "x", "song_key": "H"}, "A key looks like"),
    ({"title": "x", "tempo": 900}, "Tempo"),
    ({"title": "x", "ccli_number": "12"}, "3 to 9 digits"),
    ({"title": "x", "words": "a" * 20001}, "too long"),
])
def test_what_a_song_cant_be(api, body, message):
    db, as_ = api
    r = add(as_, **body)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_new_words_keep_the_order_parts_that_still_exist(api):
    db, as_ = api
    song = add(as_, title="It Is Well", words=WORDS).json()["song"]
    v1, refrain, v2 = [s["id"] for s in song["sections"]]
    short = {"id": "short", "name": "Short", "order": [v1, refrain, "zz9", v2]}
    r = as_("owner").put(f"/worship/songs/{song['id']}", json={"business_id": BIZ, "arrangements": song["arrangements"] + [short]})
    assert r.json()["song"]["arrangements"][1] == {"id": "short", "name": "Short", "order": [v1, refrain, v2]}
    # Verse 2 goes away: both orders drop it, nothing else changes.
    fewer = WORDS.split("Verse 2")[0]
    r = as_("owner").put(f"/worship/songs/{song['id']}", json={"business_id": BIZ, "words": fewer})
    orders = [a["order"] for a in r.json()["song"]["arrangements"]]
    assert orders == [[v1, refrain, refrain], [v1, refrain]]


def test_removing_a_song_takes_it_out_of_the_library(api):
    db, as_ = api
    song = add(as_, title="Old one", words=WORDS).json()["song"]
    assert as_("owner").delete(f"/worship/songs/{song['id']}?business_id={BIZ}").json() == {"ok": True}
    assert as_("owner").get(f"/worship/songs/{song['id']}?business_id={BIZ}").status_code == 404
    assert as_("owner").get(f"/worship/songs?business_id={BIZ}").json()["songs"] == []


def test_a_failed_read_is_never_an_empty_library(api):
    db, as_ = api
    db.fail = True
    r = as_("owner").get(f"/worship/songs?business_id={BIZ}")
    assert r.status_code == 503 and "Try again" in r.json()["detail"]
    assert add(as_, title="x", words=WORDS).status_code == 503


def test_parse_previews_without_saving(api):
    db, as_ = api
    r = as_("owner").post("/worship/parse", json={"words": WORDS})
    assert [s["label"] for s in r.json()["sections"]] == ["Verse 1", "Refrain", "Verse 2"] and db.rows == []


def _upload(paths):
    return [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]


def test_proclaim_songs_come_over_once(api, tmp_path):
    db, as_ = api
    files = build_proclaim(tmp_path)
    r = as_("owner").post("/worship/import/proclaim", data={"business_id": BIZ}, files=_upload(files))
    body = r.json()
    assert r.status_code == 200 and body["added"] == 4 and body["with_words"] == 4 and body["untitled"] == 1
    assert body["need_words"] == [] and body["services"] == 1
    holy = next(s for s in db.rows if s["title"] == "Holy, Holy, Holy")
    assert holy["source"] == "proclaim" and holy["song_key"] == "D" and holy["has_words"] and holy["times_sung"] == {"2026": 2}
    again = as_("owner").post("/worship/import/proclaim", data={"business_id": BIZ}, files=_upload(files)).json()
    assert again["added"] == 0 and again["already_here"] == 4 and len(db.rows) == 4


def test_files_that_arent_proclaims_are_refused(api, tmp_path, monkeypatch):
    db, as_ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    junk = tmp_path / "notes.db"
    junk.write_bytes(b"hello")
    r = as_("owner").post("/worship/import/proclaim", data={"business_id": BIZ}, files=_upload([junk]))
    assert r.status_code == 400 and "aren't Proclaim's" in r.json()["detail"]
    r = as_("member").post("/worship/import/proclaim", data={"business_id": BIZ}, files=_upload([junk]))
    assert r.status_code == 403


def test_scripture_on_the_spot(api):
    db, as_ = api
    r = as_("owner").get("/worship/scripture?q=rom 8 28")
    assert [c["label"] for c in r.json()["choices"]] == ["Romans 8:28", "Romans 8:28-29", "Romans 8"]
    assert as_("owner").get("/worship/scripture?q=%20").status_code == 400


def test_mounted_before_the_public_site_catch_all():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "include_router(worship_router)" in src
    assert src.index("include_router(worship_router)") < src.index("include_router(public_site_router)")

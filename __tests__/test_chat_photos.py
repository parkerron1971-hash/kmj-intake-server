# __tests__/test_chat_photos.py
#
# Photos in a group's chat (chat_photos + member_portal_messaging send and
# GET .../photo/<id> + member_portal_groups + member_portal_safety; the
# approved canvas "Church Groups, Together", boards Chat and Settings). Pins:
#   1. anyone who writes in a group's chat shares a photo, a caption if they
#      like; it's made upright, at most 1600px, WebP, and checked before
#      it's kept; one the check turns down is never kept, and if the check
#      can't run nothing is posted; a harmful caption holds the whole photo
#   2. never in a private chat, never in a chat with a teen in it, and the
#      group's leaders turn photos and polls off together
#   3. who sees it: the chat's own members (the sender alone while it's
#      held); the safety officers a held or reported one, or after their
#      logged look; nobody else, ever
#   4. the file goes when the message does; a caption that lost its picture
#      is taken back down

import io
import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import chat_photos as cph
import member_photos
import member_portal as mp
import member_portal_messaging as mpm
import member_portal_safety as mps
from test_chat_polls import polls  # noqa: F401
from test_member_group_chat import _msg, _page, _post, church  # noqa: F401
from test_member_messaging import (ANA, BEN, BIZ, CARL, GRP, HOST, JSON, ORIGIN, TEEN, YOUTH, _group_tid,  # noqa: F401
                                   _send, env)


def _png(w=200, h=100, fmt="PNG"):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), (40, 120, 160)).save(out, fmt)
    return out.getvalue()


@pytest.fixture
def pics(polls, monkeypatch):
    polls.t.setdefault("msg_photos", [])
    polls.files, polls.dropped, polls.seen = {}, [], []
    polls.look, polls.officer, polls.recent = "ok", False, False

    async def screen(b, webp):
        polls.seen.append(webp)
        if polls.look == "down":
            raise member_photos.ScreenUnavailable("down")
        return polls.look
    monkeypatch.setattr(cph, "screen", screen)

    def store(b, tid, webp):
        path = f"{b}/chat-photos/{tid}/{len(polls.files):04d}.webp"
        polls.files[path] = webp
        return path
    monkeypatch.setattr(cph, "store", store)
    monkeypatch.setattr(cph, "drop", lambda path: polls.dropped.append(path))
    import storage_links
    monkeypatch.setattr(storage_links, "signed_url_sync", lambda bucket, path, ttl=0, **kw: f"https://files.test/{bucket}/{path}")
    monkeypatch.setattr(mps, "is_officer", lambda b, c: polls.officer)
    monkeypatch.setattr(mps, "recent_look", lambda b, t, c: polls.recent)
    return polls


def _share(env, who, tid, data=None, raw=None, name="p.png"):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpm.router)
    return TestClient(app, base_url=f"https://{HOST}").post(
        f"/my/messages/{tid}/send", data=data or {}, files={"photo": (name, raw if raw is not None else _png(), "image/png")},
        headers=JSON, follow_redirects=False)


def _see(env, who, tid, mid):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpm.router)
    return TestClient(app, base_url=f"https://{HOST}").get(f"/my/messages/{tid}/photo/{mid}", follow_redirects=False)


# ── 1. sharing one ───────────────────────────────────────────────────

def test_a_member_shares_a_photo_with_a_caption(pics):
    tid = _group_tid(pics, ANA, GRP)
    assert _share(pics, ANA, tid, {"body": "From Saturday's pantry"}).json()["ok"]
    m = _msg(pics, "From Saturday's pantry")
    p = pics.t["msg_photos"][0]
    assert m["status"] == "delivered" and p["message_id"] == m["id"] and p["captioned"] is True
    assert p["path"].startswith(f"{BIZ}/chat-photos/{tid}/") and (p["width"], p["height"]) == (200, 100)
    assert pics.files[p["path"]][:4] == b"RIFF" and pics.seen == [pics.files[p["path"]]]          # WebP, checked before kept


def test_no_caption_reads_photo(pics):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, BEN, tid)
    m = _msg(pics, "Photo")
    assert pics.t["msg_photos"][0]["captioned"] is False
    page = _page(pics, ANA, f"/my/groups/{GRP}/chat").text
    assert f'src="/my/messages/{tid}/photo/{m["id"]}" alt="Photo from Ben Cole"' in page
    assert '<span class="gc-b">Photo</span>' not in page                                         # no caption bubble
    assert f'class="gc-act" href="/my/messages/{tid}/photo/{m["id"]}" target="_blank"' in page   # Open, full size


def test_a_caption_is_500_at_most(pics):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, ANA, tid, {"body": "a" * 900})
    assert [len(m["body"]) for m in pics.t["msg_messages"]] == [500]


def test_a_big_photo_is_made_smaller(pics):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, ANA, tid, raw=_png(3200, 1000, "JPEG"), name="big.jpg")
    assert (pics.t["msg_photos"][0]["width"], pics.t["msg_photos"][0]["height"]) == (1600, 500)


@pytest.mark.parametrize("raw", [b"not a picture", _png(40, 40)])
def test_a_file_that_isnt_a_photo(pics, raw):
    tid = _group_tid(pics, ANA, GRP)
    r = _share(pics, ANA, tid, raw=raw)
    assert r.status_code == 400 and not pics.files and not pics.t["msg_messages"] and not pics.seen


def test_one_the_check_turns_down_is_never_kept(pics):
    tid = _group_tid(pics, ANA, GRP)
    pics.look = "no"
    r = _share(pics, ANA, tid, {"body": "look"})
    assert r.status_code == 422 and "can't be shared" in r.json()["error"]
    assert not pics.files and not pics.t["msg_messages"] and not pics.t["msg_photos"]


def test_if_the_check_cant_run_nothing_is_posted(pics):
    tid = _group_tid(pics, ANA, GRP)
    pics.look = "down"
    r = _share(pics, ANA, tid)
    assert r.status_code == 503 and not pics.files and not pics.t["msg_messages"]


def test_a_harmful_caption_holds_the_whole_photo(pics):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, ANA, tid, {"body": "something harmful"})
    m = _msg(pics, "something harmful")
    assert m["status"] == "held" and pics.t["msg_photos"][0]["message_id"] == m["id"]
    assert "something harmful" in _page(pics, ANA, f"/my/groups/{GRP}/chat").text
    assert f"/photo/{m['id']}" not in _page(pics, BEN, f"/my/groups/{GRP}/chat").text


def test_a_caption_that_lost_its_picture_comes_down(pics, monkeypatch):
    tid = _group_tid(pics, ANA, GRP)
    real = mpm.sb_clients.sb_post_as_service
    monkeypatch.setattr(mpm.sb_clients, "sb_post_as_service",
                        lambda path, *a, **k: None if path.startswith("/msg_photos") else real(path, *a, **k))
    r = _share(pics, ANA, tid, {"body": "pantry"})
    assert r.status_code == 503 and _msg(pics, "pantry")["status"] == "removed" and pics.dropped == list(pics.files)


def test_no_message_no_file(pics, monkeypatch):
    tid = _group_tid(pics, ANA, GRP)
    real = mpm.sb_clients.sb_post_as_service
    monkeypatch.setattr(mpm.sb_clients, "sb_post_as_service",
                        lambda path, *a, **k: None if path.startswith("/msg_messages") else real(path, *a, **k))
    assert _share(pics, ANA, tid).status_code == 503 and pics.dropped == list(pics.files) and pics.files


def test_a_few_an_hour(pics, monkeypatch):
    import rate_limit
    tid = _group_tid(pics, ANA, GRP)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k, **kw: b != "chat_photos")
    assert _share(pics, ANA, tid).status_code == 429 and not pics.seen


# ── 2. where ─────────────────────────────────────────────────────────

def test_never_in_a_private_chat(pics):
    from test_member_messaging import _start, _tid
    tid = _tid(_start(pics, ANA, BEN))
    assert _share(pics, ANA, tid).status_code == 403 and not pics.files and not pics.seen


def test_never_in_a_chat_with_a_teen(pics):
    tid = _group_tid(pics, TEEN, YOUTH)
    pics.t["group_members"].append({"group_id": YOUTH, "contact_id": BEN, "business_id": BIZ, "role": "leader"})
    r = _share(pics, CARL, tid)                                                     # an adult leader of the youth group
    assert r.status_code == 403 and "teens" in r.json()["error"] and not pics.seen
    assert _share(pics, TEEN, tid).status_code == 403                               # nor a teen
    page = _page(pics, CARL, f"/my/groups/{YOUTH}/chat?make=photo").text
    assert "?make=photo" not in page and 'id="gc-photoform"' not in page


def test_off_with_polls(pics):
    tid = _group_tid(pics, ANA, GRP)
    pics.t["groups"][0]["chat_extras"] = False
    assert _share(pics, ANA, tid).status_code == 403 and not pics.seen
    assert "?make=photo" not in _page(pics, ANA, f"/my/groups/{GRP}/chat").text


def test_the_plus_offers_a_photo(pics):
    _group_tid(pics, ANA, GRP)
    page = _page(pics, ANA, f"/my/groups/{GRP}/chat").text
    assert f'href="/my/groups/{GRP}/chat?make=photo#gc-photoform"' in page and 'aria-label="Add a photo, poll or prayer"' in page
    form = _page(pics, ANA, f"/my/groups/{GRP}/chat?make=photo").text
    assert 'id="gc-photoform"' in form and 'enctype="multipart/form-data"' in form and 'type="file" name="photo"' in form


# ── 3. who sees it ───────────────────────────────────────────────────

def test_the_chat_sees_it_and_nobody_else(pics):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, BEN, tid)
    m = _msg(pics, "Photo")
    r = _see(pics, ANA, tid, m["id"])
    assert r.status_code == 302 and r.headers["location"].endswith(pics.t["msg_photos"][0]["path"])
    assert "private" in r.headers["cache-control"]
    assert _see(pics, CARL, tid, m["id"]).status_code == 404                          # not in the group
    other = _group_tid(pics, TEEN, YOUTH)
    assert _see(pics, ANA, other, m["id"]).status_code == 404                         # not through another chat


def test_only_from_its_own_chats_folder(pics):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, BEN, tid)
    m = _msg(pics, "Photo")
    pics.t["msg_photos"][0]["path"] = f"{BIZ}/chat-photos/00000000-0000-4000-9000-0000000000ff/x.webp"   # never, but if
    assert _see(pics, ANA, tid, m["id"]).status_code == 404


def test_a_held_one_is_the_senders_and_the_officers(pics):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, ANA, tid, {"body": "something harmful"})
    mid = _msg(pics, "something harmful")["id"]
    assert _see(pics, ANA, tid, mid).status_code == 302
    assert _see(pics, BEN, tid, mid).status_code == 404
    pics.officer = True
    assert _see(pics, CARL, tid, mid).status_code == 302                              # a safety officer, outside the group


def test_an_officer_sees_a_reported_one_or_after_a_look(pics):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, ANA, tid)
    mid = _msg(pics, "Photo")["id"]
    pics.officer = True
    assert _see(pics, CARL, tid, mid).status_code == 404                              # nothing to review, no look
    pics.recent = True
    assert _see(pics, CARL, tid, mid).status_code == 302                              # after the logged look
    pics.recent = False
    assert _post(pics, BEN, f"/my/messages/{tid}/hide", {"message_id": mid}).json()["ok"]    # the leader takes it down
    for r in pics.t["msg_reports"]:
        r.setdefault("status", "open")                                                # the table's default
    pics.officer = False
    assert _see(pics, ANA, tid, mid).status_code == 404                               # gone for the group
    pics.officer = True
    assert _see(pics, CARL, tid, mid).status_code == 302                              # the report is the officer's


def test_the_safety_room_shows_a_reported_photo(pics, monkeypatch):
    tid = _group_tid(pics, ANA, GRP)
    _share(pics, ANA, tid, {"body": "pantry"})
    mid = _msg(pics, "pantry")["id"]
    pics.t.setdefault("msg_reports", []).append({"id": "r1", "business_id": BIZ, "message_id": mid, "reporter_contact_id": BEN,
                                                 "reason": "", "status": "open", "created_at": "2026-10-20T00:00:00+00:00"})
    import messaging_router as mr
    items = mr.safety_items(BIZ)
    photos = mps._photos(BIZ, items["held"] + [r.get("message") or {} for r in items["reports"]])
    html = mps.render_room({"id": BIZ, "name": "First Light Church", "settings": {}}, None,
                           type("R", (), {"query_params": {}})(), {"id": CARL, "name": "Carl Moss"}, items, photos)
    assert f'<img class="sf-photo" src="/my/messages/{tid}/photo/{mid}"' in html


# ── 4. the file goes with the message ────────────────────────────────

def test_retention_drops_the_file_with_its_message(pics, monkeypatch):
    old = "2025-01-01T00:00:00+00:00"
    pics.t["msg_messages"] = [
        {"id": "m1", "business_id": BIZ, "thread_id": "t", "status": "delivered", "created_at": old},
        {"id": "m2", "business_id": BIZ, "thread_id": "t", "status": "held", "created_at": old},
    ]
    pics.t["msg_photos"] = [{"message_id": "m1", "business_id": BIZ, "path": f"{BIZ}/chat-photos/t/a.webp", "created_at": old},
                            {"message_id": "m2", "business_id": BIZ, "path": f"{BIZ}/chat-photos/t/b.webp", "created_at": old}]
    pics.t["msg_reports"] = []
    pics.t["businesses"][0]["settings"] = {"messaging": {"enabled": True}}
    import sb_clients
    real_get, real_delete = sb_clients.sb_get_as_service, sb_clients.sb_delete_as_service

    def delete(path):                       # the photo row goes with its message (on delete cascade)
        ok = real_delete(path)
        ids = {m["id"] for m in pics.t["msg_messages"]}
        pics.t["msg_photos"] = [p for p in pics.t["msg_photos"] if p["message_id"] in ids]
        return ok
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: pics.t["businesses"] if p.startswith("/businesses") else real_get(p))
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    mpm.retention_tick()
    assert [m["id"] for m in pics.t["msg_messages"]] == ["m2"] and pics.dropped == [f"{BIZ}/chat-photos/t/a.webp"]


def test_words():
    import member_portal_church as mpc
    assert {"photo_where", "photo_teen", "chat_photo_no", "photo_bad", "photo_busy"} <= set(mpc.ERRORS)

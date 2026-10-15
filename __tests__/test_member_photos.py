"""Members' profile photos (Kevin, 2026-10-15: "people should be able to put
profile pictures. this is a easy way to identify people as well"), under his
9/29 rule: profiles for fellow members, a minor's for parents and staff."""
import asyncio
import io
from datetime import date

import pytest
from PIL import Image

import member_photos as ph

TODAY = date(2026, 10, 15)
ADULT = {"id": "a1", "name": "Ana Rivers", "birthdate": "1990-05-01",
         "photo": {"path": "b1/member-photos/a1/abc.webp", "v": "abc"}}
TEEN = {"id": "t1", "name": "Tia Rivers", "birthdate": "2011-03-02",
        "photo": {"path": "b1/member-photos/t1/def.webp", "v": "def"}}
UNKNOWN = {"id": "u1", "name": "Unknown Age", "birthdate": None,
           "photo": {"path": "b1/member-photos/u1/ghi.webp", "v": "ghi"}}


def _jpeg(w=800, h=1200, exif=True):
    im = Image.new("RGB", (w, h), (200, 30, 90))
    out = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x0112] = 6                       # rotated: the camera held sideways
        ex[0x010F] = "PhoneMaker"            # a camera make, which must not survive
        im.save(out, "JPEG", exif=ex.tobytes())
    else:
        im.save(out, "JPEG")
    return out.getvalue()


def test_a_photo_is_made_upright_square_small_and_without_camera_data():
    webp = ph.prepare(_jpeg())
    with Image.open(io.BytesIO(webp)) as im:
        assert im.format == "WEBP" and im.size == (ph.SIZE, ph.SIZE)
        assert not im.getexif()                                        # no camera or location data kept
    for bad, words in ((b"", "Choose a photo"), (b"not an image", "isn't a photo"),
                       (b"x" * (ph.MAX_BYTES + 1), "too large")):
        with pytest.raises(ph.PhotoError) as e:
            ph.prepare(bad)
        assert words in str(e.value)
    with pytest.raises(ph.PhotoError):
        ph.prepare(_jpeg(40, 40, exif=False))                          # too small to be a face


def test_who_sees_a_photo_follows_the_rule_for_profiles():
    assert ph.may_see(ADULT, "anyone", set(), TODAY)                   # a fellow member
    assert ph.may_see(TEEN, "t1", set(), TODAY)                        # themselves
    assert ph.may_see(TEEN, "p1", {"p1"}, TODAY)                       # their linked parent
    assert not ph.may_see(TEEN, "a1", {"p1"}, TODAY)                   # not another adult
    assert not ph.may_see(UNKNOWN, "a1", set(), TODAY)                 # no birthdate: could be a child
    assert ph.shown_to_members(ADULT, TODAY) and not ph.shown_to_members(TEEN, TODAY)
    assert not ph.shown_to_members(UNKNOWN, TODAY)


def test_the_avatar_is_the_photo_only_where_it_may_show():
    assert ph.src(ADULT) == "/my/photo/a1?v=abc" and ph.src({"id": "x", "name": "No Photo"}) == ""
    assert "<img" in ph.avatar(ADULT, show=True) and "has-photo" in ph.avatar(ADULT, show=True)
    hidden = ph.avatar(TEEN, show=False)
    assert "<img" not in hidden and ">TR<" in hidden
    assert ph.of({"metadata": {"member_photo": {"path": "p", "v": "1"}}}) == {"path": "p", "v": "1"}
    assert ph.of({"metadata": {"member_photo": "junk"}}) == {}


def test_the_link_rechecks_who_is_asking(monkeypatch):
    import storage_links
    monkeypatch.setattr(storage_links, "signed_url_sync", lambda b, p, ttl: f"https://signed/{p}")
    records = {"t1": {**TEEN, "photo": {"path": "b1/member-photos/t1/def.webp", "v": "def"}},
               "x1": {"id": "x1", "birthdate": "1980-01-01", "photo": {"path": "b2/member-photos/x1/v.webp", "v": "v"}}}
    monkeypatch.setattr(ph, "owner_record", lambda b, c: records.get(c, {}))
    monkeypatch.setattr(ph, "parents_of", lambda b, c: {"p1"})
    assert ph.link_for("b1", "t1", "p1") == "https://signed/b1/member-photos/t1/def.webp"
    assert ph.link_for("b1", "t1", "a9") == ""                         # not their parent
    assert ph.link_for("b1", "x1", "a9") == ""                         # a path outside this church
    assert ph.link_for("b1", "nobody", "a9") == ""
    monkeypatch.setattr(ph, "owner_record", lambda b, c: None)
    assert ph.link_for("b1", "t1", "p1") is None                       # a failed read is not "no photo"


def test_the_screen_turns_down_a_picture_and_never_saves_unchecked(monkeypatch):
    import llm_call

    class R:
        def __init__(self, body, code=200):
            self._b, self.status_code = body, code

        def json(self):
            return self._b

    async def fake(client, payload, **kw):
        content = payload["messages"][0]["content"]
        assert content[0]["type"] == "image" and kw["task"] == "member_photo_screen"
        return reply

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(llm_call, "apost", fake)
    for body, want in (({"content": [{"type": "text", "text": '{"verdict": "ok"}'}]}, "ok"),
                       ({"content": [{"type": "text", "text": '{"verdict": "no"}'}]}, "no"),
                       ({"stop_reason": "refusal", "content": []}, "no")):
        reply = R(body)
        assert asyncio.run(ph.screen("b1", b"webp")) == want
    reply = R({"content": [{"type": "text", "text": "maybe"}]})
    with pytest.raises(ph.ScreenUnavailable):
        asyncio.run(ph.screen("b1", b"webp"))
    reply = R({}, 529)
    with pytest.raises(ph.ScreenUnavailable):
        asyncio.run(ph.screen("b1", b"webp"))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(ph.ScreenUnavailable):
        asyncio.run(ph.screen("b1", b"webp"))


def test_saving_keeps_the_record_and_clears_the_old_file(monkeypatch):
    put, dropped = [], []
    monkeypatch.setattr(ph, "_put", lambda path, data: put.append(path) or True)
    monkeypatch.setattr(ph, "_drop", lambda path: dropped.append(path))
    monkeypatch.setattr(ph, "_set", lambda b, c, rec: "b1/member-photos/a1/old.webp")
    assert ph.save("b1", "a1", b"webp") is True
    assert put[0].startswith("b1/member-photos/a1/") and dropped == ["b1/member-photos/a1/old.webp"]
    monkeypatch.setattr(ph, "_set", lambda b, c, rec: None)            # the record didn't save
    assert ph.save("b1", "a1", b"webp") is False and dropped[-1] == put[-1]   # the new file goes too


def _req(path, body=b"", ctype="multipart/form-data; boundary=X"):
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": path, "query_string": b"",
                    "headers": [(b"content-type", ctype.encode())]}, receive)


def _multipart(data: bytes) -> bytes:
    return (b"--X\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"me.jpg\"\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + data + b"\r\n--X--\r\n")


@pytest.fixture
def route(monkeypatch):
    import member_portal_church as mpc
    state = {"session": ({"business": {"id": "b1"}}, {"id": "a1", "name": "Ana"}, False), "saved": []}

    async def signed_in(request):
        return state["session"]
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, me: True)
    monkeypatch.setattr(ph, "save", lambda b, c, w: state["saved"].append(c) or True)
    return state


def _go(req):
    return asyncio.run(ph.upload_photo(req)).headers["location"]


def test_the_upload_saves_only_a_checked_photo(route, monkeypatch):
    async def ok(b, w):
        return "ok"

    async def no(b, w):
        return "no"

    async def down(b, w):
        raise ph.ScreenUnavailable("x")
    monkeypatch.setattr(ph, "screen", ok)
    assert _go(_req("/my/photo", _multipart(_jpeg()))) == "/my/me?done=photo" and route["saved"] == ["a1"]
    monkeypatch.setattr(ph, "screen", no)
    assert _go(_req("/my/photo", _multipart(_jpeg()))) == "/my/me?err=photo_no"
    monkeypatch.setattr(ph, "screen", down)
    assert _go(_req("/my/photo", _multipart(_jpeg()))) == "/my/me?err=photo_busy"
    assert _go(_req("/my/photo", _multipart(b"not a photo"))) == "/my/me?err=photo_bad"
    assert route["saved"] == ["a1"]
    route["session"] = ({"business": {"id": "b1"}}, None, "preview")   # the owner's preview never saves
    assert _go(_req("/my/photo", _multipart(_jpeg()))) == "/my/me?err=preview"


def test_the_photo_routes_are_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    paths = [getattr(r, "path", "") for r in app_mod.app.routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    for p in ("/my/photo", "/my/photo/remove", "/member-portal/{business_id}/photo/{contact_id}"):
        assert p in paths and paths.index(p) < catch


def test_me_offers_a_photo_and_says_who_sees_it():
    import member_portal as mp
    biz = {"id": "b1", "name": "First Light", "settings": {}}
    adult = mp.render_me(biz, None, me={**ADULT, "email": "ana@example.com"}, people=[ADULT], year=2026, gifts=[],
                         give_url="", this_year=2026)
    assert 'action="/my/photo"' in adult and 'enctype="multipart/form-data"' in adult and 'name="photo"' in adult
    assert "Members you message and the church staff see it." in adult and 'action="/my/photo/remove"' in adult
    assert 'class="mb-avatar has-photo mp-noprint" href="/my/me"' in adult            # top right too
    teen = mp.render_me(biz, None, me={**TEEN, "photo": None}, people=[TEEN], year=2026, gifts=[], give_url="",
                        this_year=2026)
    assert "Only your parents and the church staff see it." in teen and "/my/photo/remove" not in teen

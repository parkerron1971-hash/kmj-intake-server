# __tests__/test_member_yt_pictures.py
#
# A message with no art of its own shows its own YouTube picture in the new
# look (member_yt_pictures). Pins:
#   - the id is read from the link the way the player reads it
#     (sermons_public.youtube_id), and the player's embed is unchanged;
#   - the address is pure (no read), signed, on our own address; '' for a
#     link that isn't YouTube or with nothing to sign with;
#   - the picture: hqdefault's bars cut off (16:9 at the centre), the wide one
#     maxres, else sd, else hq; kept, a miss kept briefly, a failed fetch never;
#   - the route: only a name we signed, a day by the phone, 304, 503, 404,
#     no database read;
#   - the order: series art, the church's named photo, the video picture,
#     the colour wash; only where the new look asks (today's look unchanged);
#   - where it draws: Watch's latest (wide) and rows (small), a message's
#     page (and the mini player's picture), Home's message card, the share
#     sheet's card, the story picture; no read added.

import io
import json
import pathlib
import re
import sys

import pytest
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_yt_pictures as myp
import sermons_public as sp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_give import church  # noqa: F401  (the fixture)
from test_member_lumen_watch import LIB, M, _app, _s, watch  # noqa: F401  (the fixture)

VID = "AjrqJXkVIcQ"
LINK = f"https://www.youtube.com/watch?v={VID}"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    myp._KEPT.clear()
    yield
    myp._KEPT.clear()


def _jpeg(w, h, bars=0, colour=(200, 40, 90)):
    im = Image.new("RGB", (w, h), colour)
    if bars:
        im.paste((0, 0, 0), (0, 0, w, bars))
        im.paste((0, 0, 0), (0, h - bars, w, h))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=95)
    return out.getvalue()


# ─── the id and the address ──────────────────────────────────────────


@pytest.mark.parametrize("url,want", [
    (LINK, VID),
    (f"https://youtube.com/watch?feature=share&v={VID}&t=95", VID),
    (f"https://m.youtube.com/watch?v={VID}", VID),
    (f"https://youtu.be/{VID}?si=abc", VID),
    (f"https://www.youtube.com/live/{VID}?si=x", VID),
    (f"https://www.youtube.com/shorts/{VID}", VID),
    (f"https://www.youtube-nocookie.com/embed/{VID}", VID),
    (f"http://www.youtube.com/watch?v={VID}", ""),
    ("https://vimeo.com/123456", ""),
    ("https://example.com/watch?v=abc", ""),
    ("not a link", ""),
    ("", ""),
])
def test_youtube_id(url, want):
    assert sp.youtube_id(url) == want


@pytest.mark.parametrize("url,want", [
    (LINK, f"https://www.youtube-nocookie.com/embed/{VID}"),
    (f"https://youtu.be/{VID}", f"https://www.youtube-nocookie.com/embed/{VID}"),
    ("https://www.youtube.com/watch?list=x", ""),
    ("https://youtu.be/", ""),
    ("https://vimeo.com/123456", "https://player.vimeo.com/video/123456"),
])
def test_the_players_embed_is_unchanged(url, want):
    assert sp.video_embed_src(url) == want


def test_the_address_is_signed_and_ours(fake):  # noqa: F811
    fake.gets.clear()
    small, wide = myp.picture_url(LINK), myp.picture_url(LINK, wide=True)
    assert re.fullmatch(rf"/my/yt/{VID}\.jpg\?k=[A-Za-z0-9_-]{{16}}", small)
    assert re.fullmatch(rf"/my/yt/{VID}-w\.jpg\?k=[A-Za-z0-9_-]{{16}}", wide)
    assert not fake.gets                                         # pure: no read
    assert myp.parse(small) == (VID, False) and myp.parse(wide) == (VID, True)
    k = small.split("k=")[1]
    assert myp.parse(f"/my/yt/{VID[:-1]}x.jpg?k={k}") is None     # another video, the same signature
    assert myp.parse(small[:-2] + ("AA" if not small.endswith("AA") else "BB")) is None
    assert myp.parse(f"https://evil.test/my/yt/{VID}.jpg?k={k}") is None


@pytest.mark.parametrize("url", ["https://vimeo.com/123456", "https://www.youtube.com/watch?v=abc123", "", None,
                                 "https://www.youtube.com/watch?v=Ajrq%22onload"])
def test_no_address_for_anything_else(url):
    assert myp.picture_url(url) == ""


def test_no_secret_no_picture(monkeypatch):
    monkeypatch.delenv("CUSTOMER_TOKEN_SECRET", raising=False)
    assert myp.picture_url(LINK) == ""


# ─── the picture ─────────────────────────────────────────────────────


def test_the_bars_come_off():
    out = Image.open(io.BytesIO(myp.cut(_jpeg(480, 360, bars=45), myp.SMALL_W)))
    assert out.size == (480, 270)
    for xy in ((2, 2), (240, 2), (477, 267), (2, 267)):          # no black left at the edges
        assert min(out.getpixel(xy)) > 20 or max(out.getpixel(xy)) > 120
    assert Image.open(io.BytesIO(myp.cut(_jpeg(1280, 720), myp.WIDE_W))).size == (1280, 720)
    assert Image.open(io.BytesIO(myp.cut(_jpeg(1920, 1080), myp.WIDE_W))).size == (1280, 720)
    assert myp.cut(b"not a picture", 480) is None


def test_wide_is_maxres_then_sd_then_hq(monkeypatch):
    asked = []
    files = {"maxresdefault": b"", "sddefault": b"", "hqdefault": _jpeg(480, 360, bars=45)}
    monkeypatch.setattr(myp, "_fetch", lambda u: asked.append(u.rsplit("/", 1)[1][:-4]) or files[u.rsplit("/", 1)[1][:-4]])
    got = myp.get(VID, True)
    assert asked == ["maxresdefault", "sddefault", "hqdefault"]
    assert Image.open(io.BytesIO(got)).size == (480, 270)
    assert myp.get(VID, True) == got and len(asked) == 3          # kept
    files["maxresdefault"] = _jpeg(1280, 720)
    myp._KEPT.clear()
    asked.clear()
    assert Image.open(io.BytesIO(myp.get(VID, True))).size == (1280, 720) and asked == ["maxresdefault"]
    asked.clear()
    myp.get(VID, False)
    assert asked == ["hqdefault"]                                # the small one is always hq


def test_a_failed_fetch_is_never_kept_a_miss_is(monkeypatch):
    asked = []
    monkeypatch.setattr(myp, "_fetch", lambda u: asked.append(u) or None)
    assert myp.get(VID, False) is None and myp.get(VID, False) is None and len(asked) == 2
    monkeypatch.setattr(myp, "_fetch", lambda u: asked.append(u) or b"")
    assert myp.get(VID, False) == b"" and myp.get(VID, False) == b"" and len(asked) == 3


def test_the_fetch_asks_youtubes_picture_host_only(monkeypatch):
    asked = []
    monkeypatch.setattr(myp, "_fetch", lambda u: asked.append(u) or b"")
    myp.get(VID, True)
    assert asked and all(u.startswith(f"https://i.ytimg.com/vi/{VID}/") for u in asked)


# ─── the route ───────────────────────────────────────────────────────


def _route_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(myp.router)
    return TestClient(app)


def test_the_route(monkeypatch, fake):  # noqa: F811
    monkeypatch.setattr(myp, "_fetch", lambda u: _jpeg(480, 360, bars=45))
    c = _route_client()
    url = myp.picture_url(LINK)
    fake.gets.clear()
    r = c.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=86400" and r.headers["x-content-type-options"] == "nosniff"
    assert Image.open(io.BytesIO(r.content)).size == (480, 270)
    assert c.get(url, headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert not fake.gets                                         # no database read
    k = url.split("k=")[1]
    for bad in (f"/my/yt/{VID}.jpg", f"/my/yt/{VID}-w.jpg?k={k}", f"/my/yt/{VID}.png?k={k}",
                f"/my/yt/{VID[:-1]}x.jpg?k={k}", f"/my/yt/..%2F{VID}.jpg?k={k}"):
        assert c.get(bad).status_code == 404, bad


def test_the_route_says_try_again_or_not_found(monkeypatch):
    c = _route_client()
    monkeypatch.setattr(myp, "_fetch", lambda u: None)
    r = c.get(myp.picture_url(LINK))
    assert r.status_code == 503 and r.headers["cache-control"] == "no-store"
    monkeypatch.setattr(myp, "_fetch", lambda u: b"")
    assert c.get(myp.picture_url(LINK, wide=True)).status_code == 404


def test_the_route_is_mounted_before_the_catch_all():
    import kmj_intake_automation as k
    from fastapi.routing import APIRoute
    paths = [r.path for r in k.app.router.routes if isinstance(r, APIRoute)]
    assert "/my/yt/{name}" in paths
    assert paths.index("/my/yt/{name}") < paths.index("/{path:path}")


# ─── the order, and only in the new look ─────────────────────────────


def _lib(**kw):
    return {"series": [{"id": "s1", "title": "Light Has Come"}],
            "sermons": [dict({"id": M[20], "series_id": None, "title": "Love Out Loud", "video_url": LINK}, **kw)]}


def test_the_order(monkeypatch):
    import member_app_photos as photos
    import member_portal_sermons as mps
    pal = {"tint": "#D6246E"}
    s = _lib()["sermons"][0]
    assert "/my/yt/" not in mps._art(_lib(), s, pal)                     # today's look: the wash
    assert 'class="mb-art' in mps._art(_lib(), s, pal)
    got = mps._art(_lib(), s, pal, yt="small")
    assert f"/my/yt/{VID}.jpg?k=" in got and "lm-yt" in got and "background:" in got   # over its wash
    assert f"/my/yt/{VID}-w.jpg?k=" in mps._art(_lib(), s, pal, yt="wide")
    pool = ["https://cdn.test/love-loud.jpg"]
    assert "love-loud.jpg" in mps._art(_lib(), s, pal, None, pool, yt="small")       # the named photo first
    ss = dict(s, series_id="s1")
    monkeypatch.setattr(photos, "series_art", lambda site, t: "/public/site-assets/x/series-light.webp")
    assert "series-light.webp" in mps._art({"series": _lib()["series"], "sermons": [ss]}, ss, pal, yt="wide")
    assert "/my/yt/" not in mps._art(_lib(video_url="https://vimeo.com/1"), dict(s, video_url="https://vimeo.com/1"),
                                     pal, yt="wide")


def _yt_lib():
    lib = json.loads(json.dumps(LIB))
    lib["sermons"].insert(0, _s(20, None, "Love Out Loud", 1, "1 John 4:7", video_url=LINK))
    return lib


def test_watch_draws_it(watch, fake, monkeypatch):  # noqa: F811
    watch["lib"] = _yt_lib()
    html = _app(fake, monkeypatch).get("/my/sermons").text
    hero = html[html.index('class="lw-hero"'):html.index("</a>", html.index('class="lw-hero"'))]
    assert f"/my/yt/{VID}-w.jpg?k=" in hero
    rows = html[html.index('id="lw-every"'):]
    assert f"/my/yt/{VID}.jpg?k=" in rows
    assert html.count("/my/yt/") == 3        # the hero, its row, the share sheet's card (small)


def test_a_message_page_and_its_mini_player_picture(watch, fake, monkeypatch):  # noqa: F811
    watch["lib"] = _yt_lib()
    lib = watch["lib"]
    lib["sermons"][0]["audio_url"] = "https://example.test/a.mp3"
    html = _app(fake, monkeypatch).get(f"/my/sermons/{M[20]}?listen=1").text
    assert re.search(rf'data-thumb="/my/yt/{VID}-w\.jpg\?k=[^"]+"', html)
    assert f'<span class="lw-aart"><span class="mb-ph is-colour lm-yt"' in html


@pytest.mark.parametrize("path", ["/my/sermons", f"/my/sermons/{M[20]}", "/my"])
def test_todays_look_never_shows_it(watch, fake, monkeypatch, path):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    watch["lib"] = _yt_lib()
    html = _app(fake, monkeypatch).get(path).text
    assert "/my/yt/" not in html and "lm-yt" not in html


def test_no_read_added(watch, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    seen = []
    for lib in (json.loads(json.dumps(LIB)), _yt_lib()):
        watch["lib"] = lib
        c.get("/my/sermons")
        fake.gets.clear()
        c.get("/my/sermons")
        seen.append(sorted(g.split("?")[0] for g in fake.gets))
    assert seen[0] == seen[1]


def test_homes_message_card(watch):  # noqa: F811
    import member_lumen_feed as mlf
    from datetime import date
    lib = _yt_lib()
    html = mlf.message_card({"name": "Grace Fellowship", "id": tct.BIZ}, None, lib, lib["sermons"][0],
                            {"tint": "#D6246E"}, [], set(), date.today())
    assert f'<a class="lf-vid" href="/my/sermons/{M[20]}"' in html
    assert f"/my/yt/{VID}-w.jpg?k=" in html                         # the picture, wide
    assert re.search(rf'data-share-img="/my/yt/{VID}\.jpg\?k=[^"]+"', html)   # the sheet's card, small


def test_the_share_sheet_and_the_story_picture(fake, monkeypatch):  # noqa: F811
    import member_lumen_share as mls
    lib = _yt_lib()
    assert mls.message_art(lib, lib["sermons"][0], None, []) == myp.picture_url(LINK)
    fake.biz[tct.BIZ]["name"] = "Grace Fellowship"
    fake.t["sermons"] = [dict(lib["sermons"][0], business_id=tct.BIZ)]
    spec = mls._message(fake.biz[tct.BIZ], None, M[20])
    assert spec["pic"] == myp.picture_url(LINK, wide=True) and spec["look"] == "colour"
    monkeypatch.setattr(myp, "get", lambda vid, wide: b"JPEG" if (vid, wide) == (VID, True) else b"")
    monkeypatch.setattr(mls, "_fetch", lambda u: pytest.fail("no other host is asked"))
    assert mls.picture_bytes(spec["pic"], tct.BIZ) == b"JPEG"
    assert mls.picture_bytes(f"/my/yt/{VID}-w.jpg?k=forged", tct.BIZ) is None


def test_a_smaller_picture_after_a_blip_is_kept_only_briefly(monkeypatch):
    import time
    files = {"maxresdefault": None, "sddefault": _jpeg(640, 480, bars=60), "hqdefault": _jpeg(480, 360, bars=45)}
    monkeypatch.setattr(myp, "_fetch", lambda u: files[u.rsplit("/", 1)[1][:-4]])
    assert Image.open(io.BytesIO(myp.get(VID, True))).size == (640, 360)
    assert myp._KEPT[(VID, True)][0] - time.monotonic() <= myp.MISS_S        # not the six hours
    myp._KEPT.clear()
    files["maxresdefault"] = b""                                              # no maxres at all: sd is the picture
    myp.get(VID, True)
    assert myp._KEPT[(VID, True)][0] - time.monotonic() > myp.MISS_S


def test_a_story_picture_drawn_without_its_video_picture_is_never_kept(monkeypatch):
    import member_lumen_share as mls
    monkeypatch.setattr(mls, "render", lambda spec, marks, photo, logo: b"PNG+" if photo else b"PNG-")
    spec = {"kind": "message", "title": "Love Out Loud", "pic": myp.picture_url(LINK, wide=True), "look": "colour"}
    marks = {"name": "Grace Fellowship", "logo": ""}
    mls._PNG.clear()
    monkeypatch.setattr(myp, "get", lambda vid, wide: None)                  # YouTube didn't answer
    assert mls.picture(spec, marks, tct.BIZ) == ("", b"PNG-") and not mls._PNG
    monkeypatch.setattr(myp, "get", lambda vid, wide: _jpeg(1280, 720))
    tag, png = mls.picture(spec, marks, tct.BIZ)
    assert tag == mls.tag_of(spec, marks) and png == b"PNG+" and mls._PNG[tag] == b"PNG+"
    mls._PNG.clear()

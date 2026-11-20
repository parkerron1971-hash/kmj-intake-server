# __tests__/test_member_lumen_share.py
#
# Share in the member app's new look (member_lumen_share), Look 5.1. Kevin,
# 2026-11-20: a member shares the church's own content (messages, series,
# events, verses, moments) with its public link and a "Your story" picture;
# members' posts, prayer requests and photos of members' families never.
# Pins:
#   - the markup: contract 1, escaped; only the church's kinds;
#   - the story picture: a 1080 x 1920 PNG of this church's published or
#     public thing; another church's id, a draft, a private event, an event
#     while the public events page is off, a series with nothing published,
#     a member's post, anything not a church kind: 404; signed out or the
#     switch off: 404; past the limit: 429; a failed read: 503 and never kept;
#     kept (memory, ETag, 304); verses from the public-domain texts only;
#   - pictures are read only from the church's own site files and its own
#     storage folder, capped; never another host;
#   - wired in: the message page and Watch (the sheet, not today's button),
#     Coming up (public events only, the page on), the reader's Share (the
#     tapped verse); today's look keeps today's button and script;
#   - the script only on a page with a share control, from its own file,
#     no page-wide key listener; the CSS in the Lumen file before the type
#     block, tokens only, motion only without reduced motion;
#   - no page reads more.

import io
import pathlib
import re
import sys
from collections import Counter
from datetime import date, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_lumen_share as mls
import member_portal_church as mpc
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_home import _client, church  # noqa: F401  (the fixture)

SERMON = "00000000-0000-4000-8000-000000000a01"
SERMON2 = "00000000-0000-4000-8000-000000000a03"
DRAFT = "00000000-0000-4000-8000-000000000a04"
THEIRS = "00000000-0000-4000-8000-000000000a05"
SERIES = "00000000-0000-4000-8000-000000000a02"
EMPTY_SERIES = "00000000-0000-4000-8000-000000000a06"
THEIR_SERIES = "00000000-0000-4000-8000-000000000a07"
MOD = "00000000-0000-4000-8000-000000000a10"
EVENT = "00000000-0000-4000-8000-000000000a11"
PRIVATE = "00000000-0000-4000-8000-000000000a12"
THEIR_EVENT = "00000000-0000-4000-8000-000000000a13"
THEIR_MOD = "00000000-0000-4000-8000-000000000a14"
POST = "00000000-0000-4000-8000-000000000a20"
SOON = (date.today() + timedelta(days=5)).isoformat()


def _sermon(i, biz=tct.BIZ, series=SERIES, published=True, title="Hope Has a Name"):
    return {"id": i, "business_id": biz, "series_id": series, "title": title, "preached_on": "2026-11-15",
            "speaker": "Pastor James", "scripture": "Isaiah 9:6", "summary": "", "questions": "", "video_url": "",
            "audio_url": "", "published": published, "created_at": "2026-11-15T12:00:00+00:00"}


@pytest.fixture
def share(church, fake, monkeypatch):  # noqa: F811
    """Grace Fellowship's messages, a series, its public events page on with
    a public and a private occasion; another church's of each."""
    fake.t["sermons"] = [_sermon(SERMON), _sermon(SERMON2, title="Light in the Dark"), _sermon(DRAFT, published=False),
                         _sermon(THEIRS, biz=tct.OTHER, series=THEIR_SERIES)]
    fake.t["sermon_series"] = [{"id": SERIES, "business_id": tct.BIZ, "title": "Light Has Come", "description": ""},
                               {"id": EMPTY_SERIES, "business_id": tct.BIZ, "title": "Coming Soon", "description": ""},
                               {"id": THEIR_SERIES, "business_id": tct.OTHER, "title": "Theirs", "description": ""}]
    fake.t["custom_modules"] = [{"id": MOD, "business_id": tct.BIZ, "archetype": "event_roster", "is_active": True,
                                 "name": "Events", "archetype_params": {}},
                                {"id": THEIR_MOD, "business_id": tct.OTHER, "archetype": "event_roster",
                                 "is_active": True, "name": "Events", "archetype_params": {}}]
    fake.t["module_entries"] = [
        {"id": EVENT, "module_id": MOD, "business_id": tct.BIZ, "status": "active", "created_at": "2026-11-01",
         "data": {"title": "Serve Day at Riverside Park", "date": SOON + "T09:00", "location": "Riverside Park"}},
        {"id": PRIVATE, "module_id": MOD, "business_id": tct.BIZ, "status": "active", "created_at": "2026-11-01",
         "data": {"title": "Elders' retreat", "date": SOON, "_visibility": "private"}},
        {"id": THEIR_EVENT, "module_id": THEIR_MOD, "business_id": tct.OTHER, "status": "active",
         "created_at": "2026-11-01", "data": {"title": "Their picnic", "date": SOON}}]
    fake.biz[tct.BIZ]["settings"]["events_public"] = {"enabled": True}
    fake.biz[tct.OTHER]["settings"]["events_public"] = {"enabled": True}
    import member_portal_sermons as mps
    lib = {"sermons": [s for s in fake.t["sermons"] if s["business_id"] == tct.BIZ and s["published"]],
           "series": [x for x in fake.t["sermon_series"] if x["business_id"] == tct.BIZ]}
    monkeypatch.setattr(mps, "load_library", lambda b: lib)
    for kept in (mls._FOUND, mls._PNG):
        kept.clear()
    import rate_limit
    rate_limit._buckets.clear()
    return church


def _app(fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.app.include_router(mls.router)
    for _ in range(2):                       # both routes before the catch-all
        c.app.router.routes.insert(0, c.app.router.routes.pop())
    return c


def _png(r):
    from PIL import Image
    assert r.status_code == 200, r.status_code
    assert r.headers["content-type"] == "image/png"
    im = Image.open(io.BytesIO(r.content))
    return im.format, im.size


# ─── the markup ──────────────────────────────────────────────────────


def test_the_markup_is_contract_one_and_only_for_the_churchs_kinds():
    a = mls.link("message", "/sermons/x", 'Hope "Has" <a> Name', "<svg></svg>Share", sub="Pastor James",
                 img="/public/site-assets/grace/series-light.webp", sid=SERMON, cls="lm-btn ghost", label="Share")
    assert a.startswith('<a class="lm-share lm-btn ghost" href="/sermons/x" data-share-kind="message" ')
    assert 'data-share-title="Hope &quot;Has&quot; &lt;a&gt; Name"' in a and 'data-share-sub="Pastor James"' in a
    assert f'data-share-id="{SERMON}"' in a and 'aria-label="Share"' in a and a.endswith("<svg></svg>Share</a>")
    assert mls.message_href(SERMON) == f"/sermons/{SERMON}" and mls.series_href(SERIES) == f"/sermons#sm-s-{SERIES}"
    assert mls.EVENTS_HREF == "/events" and mls.VERSE_HREF == "/"
    v = mls.attrs("verse", "/", "John 1:5 · WEB", sid="JOH.1.5", text="“The light shines…” John 1:5 (WEB)", tr="web")
    assert 'data-share-id="JOH.1.5"' in v and 'data-share-tr="web"' in v and "data-share-text=" in v
    assert "g('tr')" in mls.JS_TEXT
    # A member's post, a prayer request, a photo: there is no such kind.
    assert mls.KINDS == ("message", "series", "event", "verse", "moment")
    for kind in ("post", "news", "prayer", "photo", "comment", "celebration", ""):
        with pytest.raises(ValueError):
            mls.attrs(kind, "/", "x")


# ─── the story picture ───────────────────────────────────────────────


def test_a_message_picture_is_a_story_sized_png_kept_and_cached(share, fake, monkeypatch):
    c = _app(fake, monkeypatch)
    r = c.get(f"/my/story/message/{SERMON}.png")
    assert _png(r) == ("PNG", (1080, 1920))
    assert r.headers["cache-control"] == "private, max-age=600" and r.headers["etag"].startswith('"')
    # Asked again: nothing read (kept), nothing drawn (kept), and the phone's copy is still good.
    fake.gets.clear()
    drawn = []
    monkeypatch.setattr(mls, "render", lambda *a, **k: drawn.append(1) or b"x")
    again = c.get(f"/my/story/message/{SERMON}.png")
    assert again.content == r.content and not drawn
    assert not [g for g in fake.gets if g.startswith(("/sermons", "/sermon_series"))]
    assert c.get(f"/my/story/message/{SERMON}.png", headers={"if-none-match": r.headers["etag"]}).status_code == 304
    spec = mls.lookup(fake.business(), None, "message", SERMON)
    assert spec["kicker"] == "Light Has Come" and spec["title"] == "Hope Has a Name"
    assert spec["sub"] == "Pastor James · Isaiah 9:6" and spec["href"] == f"/sermons/{SERMON}"


def test_series_event_verse_and_moment_pictures(share, fake, monkeypatch):
    c = _app(fake, monkeypatch)
    for path in (f"/my/story/series/{SERIES}.png", f"/my/story/event/{EVENT}.png", "/my/story/verse/JOH.1.5.png?t=web",
                 "/my/story/verse/JER.17.7-8.png", f"/my/story/moment/message:{SERMON}.png",
                 f"/my/story/moment/event:{EVENT}.png"):
        assert _png(c.get(path)) == ("PNG", (1080, 1920)), path
    b = fake.business()
    s = mls.lookup(b, None, "series", SERIES)
    assert s["kicker"] == "A series · 2 messages" and s["href"] == f"/sermons#sm-s-{SERIES}"
    e = mls.lookup(b, None, "event", EVENT)
    d = date.fromisoformat(SOON)
    assert e["title"] == "Serve Day at Riverside Park" and e["href"] == "/events" and e["sub"] == "Riverside Park"
    assert e["kicker"] == f"{d.strftime('%A, %B')} {d.day} · 9 AM"
    m = mls.lookup(b, None, "moment", f"message:{SERMON}")
    assert m["kind"] == "moment" and m["title"] == "Hope Has a Name"


def test_another_churchs_id_is_404(share, fake, monkeypatch):
    c = _app(fake, monkeypatch)
    for path in (f"/my/story/message/{THEIRS}.png", f"/my/story/series/{THEIR_SERIES}.png",
                 f"/my/story/event/{THEIR_EVENT}.png", f"/my/story/moment/message:{THEIRS}.png"):
        assert c.get(path).status_code == 404, path


def test_only_published_and_public_things(share, fake, monkeypatch):
    c = _app(fake, monkeypatch)
    assert c.get(f"/my/story/message/{DRAFT}.png").status_code == 404               # a draft
    assert c.get(f"/my/story/series/{EMPTY_SERIES}.png").status_code == 404         # nothing published in it
    assert c.get(f"/my/story/event/{PRIVATE}.png").status_code == 404               # private
    fake.biz[tct.BIZ]["settings"]["events_public"] = {"enabled": False}
    mls._FOUND.clear()
    assert c.get(f"/my/story/event/{EVENT}.png").status_code == 404                 # the public page is off
    assert c.get("/my/story/message/not-a-uuid.png").status_code == 404
    assert c.get(f"/my/story/message/{SERMON}.jpg").status_code == 404


def test_a_members_post_can_never_be_shared(share, fake, monkeypatch):
    fake.t["church_posts"] = [{"id": POST, "business_id": tct.BIZ, "kind": "celebration", "title": "Our baby",
                               "body": "Born today", "source": "member", "posted_by": tct.BEN, "status": "posted",
                               "attach": {"photos": ["https://example.org/baby.jpg"]}}]
    c = _app(fake, monkeypatch)
    for kind in ("post", "news", "prayer", "photo", "celebration", "comment", "group"):
        assert c.get(f"/my/story/{kind}/{POST}.png").status_code == 404, kind
    for inner in ("news", "post", "prayer", "photo", "verse"):
        assert c.get(f"/my/story/moment/{inner}:{POST}.png").status_code == 404, inner
    assert mls.lookup(fake.business(), None, "moment", f"news:{POST}") is None
    assert not [g for g in fake.gets if g.startswith("/church_posts")]               # never even looked up


def test_signed_out_switched_off_limited_and_failed(share, fake, monkeypatch):
    c = _app(fake, monkeypatch)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert c.get(f"/my/story/message/{SERMON}.png").status_code == 404
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    import member_portal as mp
    real = mp._session_for
    monkeypatch.setattr(mp, "_session_for", lambda request, church: None)
    assert c.get(f"/my/story/message/{SERMON}.png").status_code == 404
    monkeypatch.setattr(mp, "_session_for", lambda request, church: {"unavailable": True})
    assert c.get(f"/my/story/message/{SERMON}.png").status_code == 404
    monkeypatch.setattr(mp, "_session_for", real)
    # A failed read says try again, and isn't kept.
    fake.down.add("sermons")
    assert c.get(f"/my/story/message/{SERMON}.png").status_code == 503
    assert not mls._FOUND
    fake.down.clear()
    assert c.get(f"/my/story/message/{SERMON}.png").status_code == 200
    # Past the member's limit.
    import rate_limit
    seen = []
    monkeypatch.setattr(rate_limit, "allow", lambda b, k: seen.append((b, k)) or False)
    r = c.get(f"/my/story/message/{SERMON}.png")
    assert r.status_code == 429 and r.headers["retry-after"] == "600"
    assert seen == [("member_story", f"{tct.BIZ}|{tct.ANA}")]
    assert rate_limit._LIMITS["member_story"] == (40, 600)


def test_verses_come_from_the_public_domain_texts(share, fake, monkeypatch):
    b = fake.business()
    v = mls.lookup(b, None, "verse", "JOH.1.5", "kjv")
    assert v["title"] == "And the light shineth in darkness; and the darkness comprehended it not."
    assert v["kicker"] == "John 1:5 · KJV" and v["href"] == "/"
    # The supplied words lose their brackets; a range reads as one.
    jer = mls.lookup(b, None, "verse", "JER.17.7-8", "kjv")
    assert jer["kicker"] == "Jeremiah 17:7-8 · KJV" and "[" not in jer["title"] and jer["title"].startswith("Blessed is the man")
    for tr, short in (("web", "WEB"), ("bsb", "BSB"), ("asv", "ASV")):
        assert mls.lookup(b, None, "verse", "PSA.23.1", tr)["kicker"] == f"Psalm 23:1 · {short}"
    # A licensed version isn't ours to print: the reader's default instead.
    assert mls.lookup(b, None, "verse", "JOH.3.16", "niv")["kicker"].endswith("· KJV")
    for bad in ("JOH.99.1", "XYZ.1.1", "JOH.1.5-20", "JOH.1.9-5", "JOH.1.900", "john.1.5", "JOH.1"):
        assert mls.lookup(b, None, "verse", bad, "kjv") is None, bad


# ─── pictures: only the church's own ─────────────────────────────────


def test_pictures_come_only_from_the_churchs_own_files(monkeypatch):
    import sb_clients
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    assert sb_clients.sb_url() == "https://abc.supabase.co"
    ok = f"https://abc.supabase.co/storage/v1/object/public/business-assets/brand/{tct.BIZ}/member-app-1.webp"
    assert mls._storage_ok(ok, tct.BIZ)
    for bad in (ok.replace(tct.BIZ, tct.OTHER),                                     # another church's folder
                ok.replace("https://abc.supabase.co", "https://evil.example"),        # another host
                ok.replace("https://", "http://"),
                ok.replace("abc.supabase.co", "abc.supabase.co:8443"),
                ok + "?download=1",
                ok.replace("/object/public/", "/object/sign/"),                        # a private file
                f"https://abc.supabase.co/storage/v1/object/public/x/../{tct.BIZ}/a.webp",
                f"https://user@abc.supabase.co/storage/v1/object/public/{tct.BIZ}/a.webp",
                "https://169.254.169.254/latest/meta-data", "file:///etc/passwd", ""):
        assert not mls._storage_ok(bad, tct.BIZ), bad
    fetched = []
    monkeypatch.setattr(mls, "_fetch", lambda url: fetched.append(url) or b"")
    assert mls.picture_bytes("https://evil.example/x.jpg", tct.BIZ) is None and not fetched
    assert mls.picture_bytes("/public/site-assets/../../etc/passwd", tct.BIZ) is None
    assert mls.picture_bytes("/public/site-assets/nope/x.webp", tct.BIZ) is None
    mls.picture_bytes(ok, tct.BIZ)
    assert fetched == [ok]


def test_a_picture_too_big_or_not_a_photo_is_left_out():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 10, 10)).save(buf, "GIF")
    assert mls.open_picture(buf.getvalue()) is None                                     # not a photo kind
    assert mls.open_picture(b"not a picture") is None and mls.open_picture(b"") is None
    buf = io.BytesIO()
    Image.new("RGB", (9000, 5000), (1, 2, 3)).save(buf, "PNG")                           # 45 megapixels
    assert mls.open_picture(buf.getvalue()) is None
    buf = io.BytesIO()
    Image.new("RGBA", (3000, 2000), (10, 20, 30, 128)).save(buf, "PNG")
    im = mls.open_picture(buf.getvalue())
    assert im.mode == "RGB" and max(im.size) == 2200


def test_an_events_picture_must_already_be_on_the_churchs_website(share, fake, monkeypatch):
    import member_app_photos as photos
    site_photo = "/public/site-assets/grace/serve-day.webp"
    monkeypatch.setattr(photos, "photos", lambda b, site, limit=80: [site_photo])
    b = fake.business()
    assert mls.event_picture(b, None, "Serve Day at Riverside Park") == site_photo          # named for it, on the site
    # The media team's own upload for the event, only in the app: it stays in the app.
    upload = f"https://abc.supabase.co/storage/v1/object/public/business-assets/brand/{tct.BIZ}/member-app-1.webp"
    b["settings"]["member_portal"]["pictures"] = {"event:serve-day-at-riverside-park": {"url": upload, "look": "colour"}}
    assert mls.event_picture(b, None, "Serve Day at Riverside Park") == ""
    b["settings"]["member_portal"]["pictures"] = {"event:serve-day-at-riverside-park": {"url": site_photo, "look": "bw"}}
    assert mls.event_picture(b, None, "Serve Day at Riverside Park") == site_photo


def test_the_drawing_with_a_photo_a_logo_and_every_pairing():
    from PIL import Image
    import member_app_ui as ui
    pal = ui.palette({"settings": {"brand_kit": {"accent": "#0F7A55"}}}, {"accent": "#0F7A55"})
    photo = Image.new("RGB", (1600, 1000), (240, 240, 235))
    logo = Image.new("RGB", (300, 300), (20, 90, 60))
    for pair in ("a", "b", "c"):
        marks = {"name": "Grace Fellowship", "mark": "GF", "logo": "", "fill": pal["fill"], "on_fill": pal["on_fill"],
                 "night": pal["night"], "lit": pal["lit"], "pair": pair, "host": "grace.example"}
        for spec, ph, lg in (({"kind": "message", "kicker": "Light Has Come", "title": "Hope Has a Name " * 4,
                               "sub": "Pastor James · Isaiah 9:6 " * 4, "href": f"/sermons/{SERMON}", "pic": "x",
                               "look": "bw"}, photo, logo),
                             ({"kind": "verse", "kicker": "Jeremiah 17:7-8 · KJV", "title": "Blessed is the man " * 30,
                               "sub": "", "href": "/", "pic": "", "look": ""}, None, None),
                             ({"kind": "event", "kicker": "Saturday, December 5 · 9 AM", "title": "Zoë's Café Night",
                               "sub": "Fellowship Hall", "href": "/events", "pic": "", "look": ""}, None, None)):
            png = mls.render(spec, marks, ph, lg)
            im = Image.open(io.BytesIO(png))
            assert im.size == (1080, 1920) and im.format == "PNG", (pair, spec["kind"])


def test_the_faces_open_here():
    """Pillow reads the self-hosted woff2 faces (it needs FreeType with
    Brotli): every face the pictures draw with, at its axes."""
    for disp, axes, ital, uist in mls.FACES.values():
        for stem in (disp, ital, uist):
            f = mls.font(stem, 40, axes if stem == disp else {"wght": 600})
            assert f.getlength("Hope Has a Name") > 100
    assert mls._font_file("literata-normal", "Zoë").endswith("literata-normal-latin.woff2")
    assert mls._font_file("literata-normal", "Łódź").endswith("literata-normal-latin-ext.woff2")


# ─── wired into today's pages ────────────────────────────────────────


def _reads(fake, c, path):  # noqa: F811
    c.get(path)
    fake.gets.clear()
    html = c.get(path).text
    return html, Counter(r.split("?")[0] for r in fake.gets)


def test_the_message_page_opens_the_sheet_and_reads_nothing_more(share, fake, monkeypatch):
    import member_portal_sermons as mps
    c = _app(fake, monkeypatch)
    on, reads_on = _reads(fake, c, f"/my/sermons/{SERMON}")
    a = on[on.index('<a class="lm-share'):]
    a = a[:a.index("</a>")]
    # The message page is Watch's (Look 5.1, member_lumen_watch): Share in its row of four.
    assert a.startswith(f'<a class="lm-share lw-pa" href="/sermons/{SERMON}" data-share-kind="message" ')
    assert 'data-share-title="Hope Has a Name"' in a and 'data-share-sub="Pastor James · Light Has Come"' in a
    assert f'data-share-id="{SERMON}"' in a and "<span>Share</span>" in a
    assert 'data-share="/sermons/' not in on and mps.SHARE_SCRIPT not in on
    assert on.count(f'<script src="{mls.js_url()}" defer></script>') == 1
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    off, reads_off = _reads(fake, c, f"/my/sermons/{SERMON}")
    assert reads_on == reads_off
    # Today's look: today's button and script, nothing of the sheet.
    assert f'data-share="/sermons/{SERMON}"' in off and mps.SHARE_SCRIPT in off
    assert "lm-share" not in off and mls.js_url() not in off


def test_watch_shares_the_latest_message(share, fake, monkeypatch):
    import member_portal_sermons as mps
    c = _app(fake, monkeypatch)
    on, reads_on = _reads(fake, c, "/my/sermons")
    # Watch is Look 5.1's (member_lumen_watch): Share under the latest message.
    feat = on[on.index('<div class="lw-btns">'):]
    assert f'<a class="lm-share lw-pill" href="/sermons/{SERMON}" data-share-kind="message"' in feat[:4000]
    assert ">Share</a>" in feat[:4000] and mps.SHARE_SCRIPT not in on and mls.js_url() in on
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    off, reads_off = _reads(fake, c, "/my/sermons")
    assert reads_on == reads_off and mps.SHARE_SCRIPT in off and "lm-share" not in off


def test_coming_up_shares_public_events_only(share, fake, monkeypatch):
    church = share
    church["occ"][0]["public"] = True
    church["occ"][1]["public"] = False
    c = _app(fake, monkeypatch)
    on, reads_on = _reads(fake, c, "/my/events")
    first = church["occ"][0]
    assert on.count('class="lm-share lm-evshare"') == 1 and on.count('<div class="lm-evt has-share">') == 1
    a = on[on.index('<a class="lm-share lm-evshare"'):]
    a = a[:a.index("</a>")]
    assert 'href="/events" data-share-kind="event"' in a and f'data-share-title="{first["title"]}"' in a
    assert f'data-share-id="{first["entry_id"]}"' in a and f'aria-label="Share {first["title"]}"' in a
    # The church's public events page off: nothing to share.
    fake.biz[tct.BIZ]["settings"]["events_public"] = {"enabled": False}
    none = c.get("/my/events").text
    assert "lm-share" not in none and mls.js_url() not in none
    fake.biz[tct.BIZ]["settings"]["events_public"] = {"enabled": True}
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    off, reads_off = _reads(fake, c, "/my/events")
    assert reads_on == reads_off and "lm-share" not in off


def test_upcoming_for_marks_the_public_occasions(fake, monkeypatch):  # noqa: F811
    fake.t["custom_modules"] = [{"id": MOD, "business_id": tct.BIZ, "archetype": "event_roster", "is_active": True,
                                 "name": "Events", "archetype_params": {}}]
    fake.t["module_entries"] = [
        {"id": EVENT, "module_id": MOD, "business_id": tct.BIZ, "status": "active", "created_at": "2026-11-02",
         "data": {"title": "Serve Day", "date": SOON}},
        {"id": PRIVATE, "module_id": MOD, "business_id": tct.BIZ, "status": "active", "created_at": "2026-11-01",
         "data": {"title": "Invite only", "date": SOON, "_visibility": "invite",
                  "signups": [{"contact_id": tct.ANA, "status": "yes"}]}}]
    me = next(dict(p) for p in fake.t["contacts"] if p["id"] == tct.ANA)
    got = {o["entry_id"]: o["public"] for o in mpc.upcoming_for(tct.BIZ, me)}
    assert got == {EVENT: True, PRIVATE: False}


def test_the_readers_share_is_the_tapped_verse():
    js = mls.JS_TEXT
    assert "data-share-from')==='reader'" in js and ".bb-v.is-sel" in js
    assert "'/my/story/verse/'" in js and "data-book" in js and "data-tr" in js
    import member_lumen_bible
    src = pathlib.Path(member_lumen_bible.__file__).read_text(encoding="utf-8")
    assert 'class="lm-share" data-share-kind="verse" data-share-from="reader"' in src
    assert 'data-act="share"' not in src
    import member_portal_bible
    assert 'data-act="share"' in pathlib.Path(member_portal_bible.__file__).read_text(encoding="utf-8")   # today's reader keeps its own


# ─── the script and the sheet ────────────────────────────────────────


def test_the_script_rides_only_where_theres_a_share(share, fake, monkeypatch):
    c = _app(fake, monkeypatch)
    for path in ("/my", "/my/connect", "/my/me", "/my/give"):
        html = c.get(path).text
        assert "lm-share" not in html and mls.js_url() not in html, path
    # the Bible tab (Look 5.1) opens on the reader, whose verse bar has Share: the script rides there
    html = c.get("/my/bible").text
    assert 'data-share-from="reader"' in html and html.count(mls.js_url()) == 1
    assert mls.page_js("<p>nothing</p>") == "" and mls.js_url() in mls.page_js('<a class="lm-share" href="/">')
    r = c.get(mls.js_url())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable" and r.content == mls.js_file()[0]
    stale = c.get("/my/share.000000000000.js")
    assert stale.status_code == 200 and stale.headers["cache-control"] == "no-store"


def test_the_sheet_does_what_the_mock_shows():
    js = mls.JS_TEXT
    for target in ("Your story", "Text a friend", "Copy link", "More apps"):
        assert f"<b>{target}</b>" in mls.SHEET
    assert "Send to someone at church" not in js                                         # no compose with a picked person
    assert "'sms:?&body='" in js and "navigator.share" in js and "navigator.canShare" in js
    assert "navigator.clipboard" in js and "'Link copied'" in js and "image/png" in js
    assert 'role=\\"dialog\\"' in js and 'aria-modal=\\"true\\"' in js and 'aria-labelledby=\\"lm-shs-h\\"' in js
    assert "Saved to your phone" in js
    # Escape on the sheet only: no listener on the whole page's keys.
    assert "S.addEventListener('keydown'" in js
    assert "document.addEventListener('keydown'" not in js and "window.addEventListener('keydown'" not in js
    # Focus goes in and comes back.
    assert "S.focus(" in js and "back.focus(" in js
    for kind, note in mls.NOTES.items():
        assert "%h" in note or kind == "verse", kind
    assert "photos members post never leave the app" in mls.NOTES["event"]


def test_the_css_is_in_the_lumen_file_with_tokens_only():
    import member_lumen_fonts
    import member_lumen_ui as lm
    parts = lm.templates()
    assert mls.CSS in parts and parts.index(mls.CSS) < len(parts) - 1
    assert parts[-1].template == member_lumen_fonts.template().template
    css = mls.CSS.template
    assert "$" not in css and not re.search(r"#[0-9a-fA-F]{3,6}\b", css)
    # The only literal colours are the dim behind the sheet, as one token.
    assert re.findall(r"rgba?\([^)]*\)", css) == ["rgba(0,0,0,.42)", "rgba(0,0,0,.62)", "rgba(0,0,0,.62)"]
    for tok in ("var(--bg)", "var(--fg)", "var(--s1)", "var(--lm-line)", "var(--acc-fill)", "var(--on-acc)"):
        assert tok in css
    # Motion only without reduced motion; dark and Same as my phone both turn it.
    head, _, motion = css.partition("@media (prefers-reduced-motion:no-preference){")
    assert "animation:" not in head and "transition:" not in head
    assert "body.lm.lm-dark .lm-shs-sheet" in css and "body.lm.lm-auto .lm-shs-sheet" in css


def test_the_routes_are_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    paths = [getattr(r, "path", "") for r in app_mod.app.routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    assert paths.index("/my/story/{kind}/{name}") < catch and paths.index("/my/share.{tag}.js") < catch

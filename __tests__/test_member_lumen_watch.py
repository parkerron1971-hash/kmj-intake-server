# __tests__/test_member_lumen_watch.py
#
# Watch in the member app's new look, Look 5.1 (member_lumen_watch), behind
# MEMBER_LUMEN. Pins:
#   - off: none of it (no lw- class, no service read, today's pages);
#   - Watch: the title, Messages | Series as links, the latest on a card
#     (kicker "Latest · <series>, part n", serif title, speaker · scripture,
#     how long only once her phone has played it), Watch / Listen (only with
#     audio) / Share (the shared contract) / Save; Pick up where you left off
#     from her own record (started, not finished, newest first); Saved;
#     Every message (twelve, then See all); Watch live with the office's
#     weekly time and Add to calendar, else the next gathering; Live now on
#     top while live; Series two across with when it ran and how many;
#   - a message: the player (video with start= where she left off, or our
#     audio player), the media element marked for the mini-player, Part n of
#     m, Listen | Video, Share, Save, Give; About (the summary, Read <passage>
#     into the reader), Discuss (numbered; Talk about it in <group> only for
#     a group whose chat is open to her), In this series (Playing, watched);
#   - a series: the poster, Keep watching part n / Watch part n / Play part 1,
#     Share (the public page's series), the parts;
#   - POST /my/sermons/progress and /my/sermons/save: same origin, signed in,
#     never in the owner's preview, its own rate limit, her own row only,
#     guarded by updated_at, bounded, a no-op not written;
#   - GET /my/sermons/live.ics: the weekly rule on the church's clock, kept;
#   - the same reads as off (the service time and her groups are kept), the
#     household read carries her places, the sheet's block before the type.

import json
import pathlib
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_lumen_ui as lm
import member_lumen_watch as mlw
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_give import LIVE, church  # noqa: F401  (the fixture)
from test_member_lumen_pages import _body_class, _client

TODAY = date.today()
S1, S2 = "00000000-0000-4000-8000-000000000501", "00000000-0000-4000-8000-000000000502"
M = [f"00000000-0000-4000-8000-0000000006{i:02d}" for i in range(1, 30)]
YT = "https://www.youtube.com/watch?v=abc123"
MP3 = "https://example.test/a.mp3"


def _s(i, series, title, days, scripture="", **kw):
    row = {"id": M[i], "series_id": series, "title": title, "speaker": "Pastor James",
           "preached_on": (TODAY - timedelta(days=days)).isoformat(), "scripture": scripture, "summary": "",
           "questions": "", "video_url": "", "audio_url": "", "published": True}
    row.update(kw)
    return row


LIB = {"series": [{"id": S1, "title": "Light Has Come", "description": "Four weeks with the prophets."},
                  {"id": S2, "title": "Rooted", "description": ""}],
       "sermons": [_s(0, S1, "Hope Has a Name", 3, "Isaiah 9:6", video_url=YT, audio_url=MP3,
                      summary="God gave them a name to hold.",
                      questions="1. Which name do you need?\n2. Where have you seen light?\n3. Who could you invite?"),
                   _s(1, S1, "A Light in the Dark", 10, "John 1:5", video_url=YT),
                   _s(2, S1, "The Light Is Coming", 17, "Isaiah 60:1", video_url=YT),
                   _s(3, None, "When We Pray", 24, "Matthew 6:9", speaker="Pastor Dana", audio_url=MP3),
                   _s(4, S2, "Deep Water", 60, "Psalm 1:3"), _s(5, S2, "Good Soil", 67, "Mark 4:8")]}


@pytest.fixture
def watch(church, fake, monkeypatch):  # noqa: F811
    """church (test_member_lumen_give) with a real-shaped library, nothing
    kept from another test, and the office's service time unsaved."""
    church["lib"] = json.loads(json.dumps(LIB))
    for k in (mlw._SLOTS, mlw._GROUPS):
        if k is not None:
            k.clear()
    import member_cache
    member_cache.forget_all()
    fake.t["church_checkin_settings"] = []
    return church


def _places(fake, p=None, s=None):
    now = int(datetime.now(timezone.utc).timestamp())
    for c in fake.t["contacts"]:
        if c["id"] == tct.ANA:
            meta = dict(c.get("metadata") or {})
            meta["member_watch"] = {"p": {k: [v[0], v[1], now - v[2], v[3]] for k, v in (p or {}).items()},
                                    "s": {k: now - v for k, v in (s or {}).items()}}
            c["metadata"] = meta
            c["updated_at"] = "2026-11-20T10:00:00+00:00"
    return now


def _service(fake, weekday=6, at="10:30:00", tz="America/New_York", title="Sunday Worship"):
    fake.t["church_checkin_settings"] = [{"business_id": tct.BIZ, "weekday": weekday, "start_time": at,
                                          "timezone": tz, "title": title, "enabled": True}]


def _app(fake, monkeypatch, **kw):  # noqa: F811
    """The pages' client, with member_lumen_watch's routes before the catch-all."""
    c = _client(fake, monkeypatch, **kw)
    from fastapi.routing import APIRoute
    c.app.include_router(mlw.router)
    tail = [r for r in c.app.router.routes if isinstance(r, APIRoute) and r.path == "/my/{rest:path}"]
    c.app.router.routes = [r for r in c.app.router.routes if r not in tail] + tail
    return c


def _get(fake, monkeypatch, path):  # noqa: F811
    return _app(fake, monkeypatch).get(path).text


def _cut(html, start, end="</section>"):
    i = html.index(start)
    return html[i:html.index(end, i)]


# ─── off ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/my/sermons", "/my/sermons?view=series", f"/my/sermons?series={S1}",
                                  f"/my/sermons/{M[0]}", f"/my/sermons/{M[0]}?listen=1"])
def test_off_none_of_it(watch, fake, monkeypatch, path):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    _service(fake)
    c = _app(fake, monkeypatch)
    fake.gets.clear()
    html = c.get(path).text
    assert 'class="lw' not in html and "lm-share" not in html and "data-lm-media" not in html
    assert not any("church_checkin_settings" in g for g in fake.gets)


# ─── Watch ───────────────────────────────────────────────────────────


def test_watch_messages(watch, fake, monkeypatch):  # noqa: F811
    _service(fake)
    html = _get(fake, monkeypatch, "/my/sermons")
    assert _body_class(html).split()[:3] == ["lm", "lm-tab", "pg-watch"] and "lm-dark" not in _body_class(html)
    assert '<h1 class="lw-t1">Watch</h1>' in html
    seg = _cut(html, '<nav class="lw-seg"', "</nav>")
    assert '<a href="/my/sermons" aria-current="page">Messages</a>' in seg and 'href="/my/sermons?view=series">Series' in seg
    hero = _cut(html, 'class="lw-hero"', "</a>")
    assert "Latest · Light Has Come, part 3" in hero and "<h2>Hope Has a Name</h2>" in hero
    assert "Pastor James · Isaiah 9:6</span>" in hero                     # no length: never played here
    btns = _cut(html, '<div class="lw-btns">', "</form></div>")
    assert f'href="/my/sermons/{M[0]}"' in btns and "Watch</a>" in btns
    assert f'href="/my/sermons/{M[0]}?listen=1"' in btns                    # Listen: it has audio
    share = re.search(r'<a class="lm-share[^"]*"[^>]*>', btns).group(0)
    assert f'href="/sermons/{M[0]}"' in share and 'data-share-kind="message"' in share
    assert 'data-share-title="Hope Has a Name"' in share and 'data-share-sub="Pastor James · Light Has Come, part 3"' in share
    assert f'data-share-id="{M[0]}"' in share
    assert 'action="/my/sermons/save"' in btns and 'aria-pressed="false"' in btns and 'aria-label="Save for later"' in btns
    rows = html.count('class="lw-mrow"')
    assert rows == 6 and "lw-all" not in html                              # six messages: no See all
    assert 'data-lw-rail="go"' in html and re.search(r'data-lw-rail="go"[^>]* hidden', html)  # nothing started
    card = _cut(html, '<div class="lw-card">', "</div>")
    assert "Watch live" in card and "Sundays at 10:30 AM" in card and 'href="/my/sermons/live.ics"' in card
    assert html.count(f'<script src="{mlw.js_url()}" defer></script>') == 1 and 'id="lw-state"' in html
    assert mlw.JS not in html                                              # its own file, kept by the phone


def test_watch_listen_only_with_audio_and_the_next_gathering_without_a_service_time(watch, fake, monkeypatch):  # noqa: F811
    watch["lib"]["sermons"][0]["audio_url"] = ""
    html = _get(fake, monkeypatch, "/my/sermons")
    btns = _cut(html, '<div class="lw-btns">', "</form></div>")
    assert "?listen=1" not in btns and "Listen" not in btns
    card = _cut(html, '<div class="lw-card">', "</div>")
    assert "live.ics" not in card and "Sunday Worship" in card and 'href="/my/live"' in card


def test_watch_while_live_and_with_nothing_posted(watch, fake, monkeypatch):  # noqa: F811
    watch["live"] = dict(LIVE)
    _service(fake)
    html = _get(fake, monkeypatch, "/my/sermons")
    live = _cut(html, 'class="lw-live is-live"', "</a>")
    assert 'href="/my/live"' in live and "Live now" in live and "Sunday Worship" in live
    assert html.index('class="lw-live') < html.index('class="lw-hero"') and 'class="lw-card"' not in html
    watch["live"], watch["lib"] = {}, {"sermons": [], "series": []}
    html = _get(fake, monkeypatch, "/my/sermons")
    assert "Messages are on the way" in html and 'class="lw-hero"' not in html and "Watch live" in html


def test_pick_up_where_you_left_off_and_saved(watch, fake, monkeypatch):  # noqa: F811
    _places(fake, p={M[1]: [1188, 2200, 3600, "v"], M[3]: [598, 2658, 86400, "a"], M[2]: [2465, 2465, 7200, "v"],
                     M[0]: [5, 2292, 60, "v"], "00000000-0000-4000-8000-0000000009ff": [900, 2000, 10, "v"]},
            s={M[5]: 100})
    html = _get(fake, monkeypatch, "/my/sermons")
    rail = _cut(html, 'data-lw-rail="go"')
    ids = re.findall(r'class="lw-cw" href="[^"]*" data-lw-sid="([^"]+)"', rail)
    assert ids == [M[1], M[3]]                                             # started, newest first; done and unknown out
    assert "Part 2 · 17 min left" in rail and "35 min left" in rail
    assert f'href="/my/sermons/{M[3]}?listen=1"' in rail                   # she was listening
    assert 'style="width:54%"' in rail
    saved = _cut(html, 'data-lw-rail="saved"')
    assert f'data-lw-sid="{M[5]}"' in saved and "Rooted, part 1" in saved
    assert 'data-lw-rail="saved" aria-labelledby="lw-sv-h">' in html          # not hidden
    hero = _cut(html, 'class="lw-hero"', "</a>")
    assert "38 min" in hero                                                # her phone played it: its length is known
    row = _cut(html, f'class="lw-mrow" href="/my/sermons/{M[1]}"', "</a>")
    assert '<i class="lw-dur">36:40</i>' in row
    row = _cut(html, f'class="lw-mrow" href="/my/sermons/{M[4]}"', "</a>")
    assert '<i class="lw-dur" hidden></i>' in row                          # never played: no length
    assert f'"{M[1]}":[1188,2200,' in html                                  # the page's state for its script


def test_every_message_shows_twelve_then_see_all(watch, fake, monkeypatch):  # noqa: F811
    watch["lib"]["sermons"] += [_s(6 + i, None, f"Message {i}", 80 + 7 * i) for i in range(10)]
    html = _get(fake, monkeypatch, "/my/sermons")
    assert html.count('class="lw-mrow"') == 12 and 'href="/my/sermons?all=1#lw-every">See all 16 messages' in html
    html = _get(fake, monkeypatch, "/my/sermons?all=1")
    assert html.count('class="lw-mrow"') == 16 and "lw-all" not in html


def test_series_two_across(watch, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/sermons?view=series")
    seg = _cut(html, '<nav class="lw-seg"', "</nav>")
    assert 'href="/my/sermons?view=series" aria-current="page">Series' in seg
    grid = _cut(html, '<div class="lw-grid">', '</div></div>')
    tiles = re.findall(r'<a class="lw-ser[^"]*" href="/my/sermons\?series=([^"]+)"', grid)
    assert tiles == [S1, S2]                                               # newest message first
    one, two = (TODAY - timedelta(days=17)), (TODAY - timedelta(days=3))
    when = mlw.span([{"preached_on": one.isoformat()}, {"preached_on": two.isoformat()}])
    assert f"{when} · 3 messages" in grid and "2 messages" in grid
    assert "<b>Light Has Come</b>" in grid                                 # generated art: the serif title on it
    assert 'class="lw-hero"' not in html and 'class="lw-card"' not in html


# ─── a message ───────────────────────────────────────────────────────


def test_a_message(watch, fake, monkeypatch):  # noqa: F811
    _places(fake, p={M[0]: [700, 2292, 30, "v"], M[2]: [2465, 2465, 900, "v"]})
    html = _get(fake, monkeypatch, f"/my/sermons/{M[0]}")
    assert _body_class(html).split()[:2] == ["lm", "lm-push"]
    pv = _cut(html, '<div class="lw-pv', '<div class="lw-pinfo">')
    frame = re.search(r"<iframe[^>]*>", pv).group(0)
    assert "youtube-nocookie.com/embed/abc123?enablejsapi=1" in frame and "start=697" in frame   # a few seconds back
    for attr in ("data-lm-media", 'data-title="Hope Has a Name"', 'data-sub="Pastor James · Light Has Come, part 3"',
                 f'data-href="/my/sermons/{M[0]}"', 'data-lw-kind="yt"', "data-thumb="):
        assert attr in frame, attr
    assert f'class="lw-fab" href="/my/sermons?series={S1}" data-lw-back aria-label="Back to Light Has Come"' in pv
    info = _cut(html, '<div class="lw-pinfo">', "</div>")
    assert "Light Has Come · Part 3 of 3" in info and "<h1>Hope Has a Name</h1>" in info
    assert "Pastor James · Isaiah 9:6 · " in info
    acts = _cut(html, '<div class="lw-pacts"', '<div class="lw-tabs">')
    assert "--n:4" in acts and 'class="lw-pa" href="/my/give"' in acts     # the church's own Give
    assert f'href="/my/sermons/{M[0]}?listen=1"' in acts and "<span>Listen</span>" in acts
    assert 'class="lm-share lw-pa"' in acts and 'data-share-kind="message"' in acts and "<span>Save</span>" in acts
    tabs = html[html.index('<div class="lw-tabs">'):]
    assert ['about', 'discuss', 'series'] == re.findall(r'id="lw-t-(\w+)"', tabs)
    about = _cut(tabs, 'class="lw-panel lw-p-about"')
    assert "God gave them a name to hold." in about
    assert 'href="/my/bible/isaiah/9#v6"' in about and "Read Isaiah 9" in about and "King James Version" in about
    disc = _cut(tabs, 'class="lw-panel lw-p-discuss"')
    assert re.findall(r"<li>([^<]+)</li>", disc) == ["Which name do you need?", "Where have you seen light?",
                                                    "Who could you invite?"]
    assert "Talk about it" not in disc                                     # messaging is off at this church
    ser = _cut(tabs, 'class="lw-panel lw-p-series"')
    assert re.findall(r'data-lw-sid="([^"]+)"', ser) == [M[2], M[1], M[0]]  # part 1 first
    assert "Part 3 · Playing" in ser and 'aria-current="true"' in ser
    assert 'aria-label="Watched"' in ser                                   # part 1 is watched


def test_a_message_listen_audio_only_give_and_one_tab(watch, fake, monkeypatch):  # noqa: F811
    _places(fake, p={M[0]: [700, 2292, 30, "v"], M[3]: [600, 2658, 30, "a"]})
    html = _get(fake, monkeypatch, f"/my/sermons/{M[0]}?listen=1")
    pv = _cut(html, '<div class="lw-pv', '<div class="lw-pinfo">')
    assert "iframe" not in pv and 'class="lw-pv is-aud"' in html
    audio = re.search(r"<audio[^>]*>", pv).group(0)
    assert f'src="{MP3}"' in audio and "data-lm-media" in audio and 'data-lw-at="0"' in audio   # the video's place isn't audio's
    assert f'data-href="/my/sermons/{M[0]}?listen=1"' in audio and " controls " in audio
    assert 'class="lw-actl" hidden' in pv and 'data-lw-skip="-15"' in pv and 'data-lw-seek' in pv
    acts = _cut(html, '<div class="lw-pacts"', "</div>")
    assert f'class="lw-pa on" href="/my/sermons/{M[0]}"' in acts and "<span>Video</span>" in acts
    # Audio only: our player, no Listen | Video, resumed; a loose message has one tab's worth.
    watch["give"] = False
    html = _get(fake, monkeypatch, f"/my/sermons/{M[3]}")
    assert "/my/give" not in _cut(html, '<div class="lw-pacts"', "</div>")      # no online giving: no Give
    assert 'data-lw-at="597"' in html and "<span>Video</span>" not in html and "<span>Listen</span>" not in html
    assert '<div class="lw-panel lw-one">' in html and 'class="lw-tabs"' not in html and "Read Matthew 6" in html
    assert "<p class=\"lw-kick\">Message</p>" in html


def test_a_message_with_nothing_posted_and_a_link_we_cant_play(watch, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, f"/my/sermons/{M[4]}")
    assert "The recording for this message isn&#x27;t posted yet." in html or \
        "The recording for this message isn't posted yet." in html
    assert not re.search(r"<(iframe|audio)[^>]*data-lm-media", html)
    watch["lib"]["sermons"][4]["video_url"] = "https://example.test/video.mp4"
    html = _get(fake, monkeypatch, f"/my/sermons/{M[4]}")
    assert 'href="https://example.test/video.mp4" target="_blank" rel="noopener"' in html
    assert _app(fake, monkeypatch).get("/my/sermons/00000000-0000-4000-8000-0000000009ff",
                                       follow_redirects=False).headers["location"] == "/my/sermons"


def test_talk_about_it_only_in_a_group_whose_chat_is_open(watch, fake, monkeypatch):  # noqa: F811
    fake.biz[tct.BIZ]["settings"]["messaging"] = {"enabled": True}
    fake.add("group_members", group_id=tct.GROUP, business_id=tct.BIZ, contact_id=tct.ANA, role="member")
    c = _app(fake, monkeypatch)
    html = c.get(f"/my/sermons/{M[0]}").text
    talk = _cut(html, "<div class=lw-talk>", "</div>")
    name = next(g["name"] for g in fake.t["groups"] if g["id"] == tct.GROUP)
    assert f'href="/my/groups/{tct.GROUP}/chat"' in talk and f"Talk about it in {name}" in talk
    fake.gets.clear()
    c.get(f"/my/sermons/{M[0]}")
    assert not any(g.startswith(("/group_members", "/groups")) for g in fake.gets)   # kept a minute
    # Only leaders write in that group: not for her.
    mlw._GROUPS.clear()
    for g in fake.t["groups"]:
        if g["id"] == tct.GROUP:
            g["chat_writers"] = "leaders"
    assert "Talk about it" not in c.get(f"/my/sermons/{M[0]}").text
    # A message with no questions never reads her groups.
    mlw._GROUPS.clear()
    fake.gets.clear()
    c.get(f"/my/sermons/{M[1]}")
    assert not any(g.startswith(("/group_members", "/groups")) for g in fake.gets)


# ─── a series ────────────────────────────────────────────────────────


def test_a_series(watch, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, f"/my/sermons?series={S1}")
    hero = _cut(html, '<header class="lw-shero">', "</header>")
    assert "<h1>Light Has Come</h1>" in hero and "Series · " in hero
    assert 'class="lw-fab" href="/my/sermons?view=series" data-lw-back' in hero
    assert '<p class=lw-about>Four weeks with the prophets.</p>' in html
    btns = _cut(html, '<div class="lw-btns lw-sbtns">', "</a></div>")
    assert f'href="/my/sermons/{M[2]}">' in btns and "Play part 1" in btns
    share = re.search(r'<a class="lm-share[^"]*"[^>]*>', btns).group(0)
    assert f'href="/sermons#sm-s-{S1}"' in share and 'data-share-kind="series"' in share and f'data-share-id="{S1}"' in share
    assert re.findall(r'class="lw-prow[^"]*" href="/my/sermons/([^"?]+)', html) == [M[2], M[1], M[0]]
    assert "Part 3 · New" in html                                          # three days old, not started
    _places(fake, p={M[2]: [2465, 2465, 90, "v"], M[1]: [400, 2200, 30, "v"]})
    html = _get(fake, monkeypatch, f"/my/sermons?series={S1}")
    assert f'href="/my/sermons/{M[1]}">' in html and "Keep watching part 2" in html
    _places(fake, p={M[2]: [2465, 2465, 90, "v"]})
    html = _get(fake, monkeypatch, f"/my/sermons?series={S1}")
    assert "Watch part 2" in html and "Keep watching" not in html


# ─── saving where she is, and Save ───────────────────────────────────


def _post(c, path, body, origin=None, json_=True):
    h = {"Origin": origin} if origin else {}
    if json_:
        h["Content-Type"] = "application/json"
        h["Accept"] = "application/json"
        return c.post(path, content=json.dumps(body), headers=h)
    return c.post(path, data=body, headers=h, follow_redirects=False)


def _mine(fake):
    return next(c for c in fake.t["contacts"] if c["id"] == tct.ANA).get("metadata", {}).get("member_watch")


def test_progress_saves_on_her_own_record(watch, fake, monkeypatch):  # noqa: F811
    _places(fake)
    c = _app(fake, monkeypatch)
    r = _post(c, "/my/sermons/progress", {"id": M[0], "pos": 612.4, "dur": 2292, "m": "v"}, origin=f"https://{tct.HOST}")
    assert r.status_code == 200 and r.json()["ok"] and isinstance(r.json()["at"], int)
    assert _mine(fake)["p"][M[0]][:2] == [612, 2292] and _mine(fake)["p"][M[0]][3] == "v"
    patch = [w for w in fake.written("contacts") if w[0] == "patch"][-1]
    assert patch[2] and all(row["id"] == tct.ANA for row in patch[2])
    # Near the end counts as watched.
    _post(c, "/my/sermons/progress", {"id": M[0], "pos": 2270, "dur": 2292, "m": "v"})
    assert _mine(fake)["p"][M[0]][0] == 2292
    # A place that hasn't moved isn't written again.
    n = len(fake.written("contacts"))
    _post(c, "/my/sermons/progress", {"id": M[0], "pos": 2292, "dur": 2292, "m": "v"})
    assert len(fake.written("contacts")) == n
    # Bounded: the newest twenty.
    for i in range(25):
        _post(c, "/my/sermons/progress", {"id": f"00000000-0000-4000-8000-0000000007{i:02d}", "pos": 100, "dur": 900, "m": "a"})
    assert len(_mine(fake)["p"]) == mlw.MAX_PROGRESS


@pytest.mark.parametrize("body", [{"id": "nope", "pos": 1, "dur": 2, "m": "v"}, {"id": M[0], "pos": -1, "dur": 2, "m": "v"},
                                  {"id": M[0], "pos": 1, "dur": 2, "m": "x"}, {"id": M[0], "pos": "a", "m": "v"}, ["x"]])
def test_progress_refuses_what_isnt_a_place(watch, fake, monkeypatch, body):  # noqa: F811
    r = _post(_app(fake, monkeypatch), "/my/sermons/progress", body)
    assert r.status_code == 400 and not fake.written("contacts")


def test_progress_needs_the_same_origin_a_session_and_isnt_the_preview(watch, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    body = {"id": M[0], "pos": 100, "dur": 2292, "m": "v"}
    assert _post(c, "/my/sermons/progress", body, origin="https://evil.test").status_code == 403
    c2 = tct._app(fake, monkeypatch, None)
    c2.app.include_router(mlw.router)
    assert _post(c2, "/my/sermons/progress", body).status_code == 401
    import member_portal as mp
    monkeypatch.setattr(mp, "_session_for", lambda req, ch: {"preview": True, "me": {"id": tct.ANA}, "people": []})
    r = _post(c, "/my/sermons/progress", body)
    assert r.json() == {"ok": False, "error": "preview"} and not fake.written("contacts")


def test_progress_has_its_own_rate_limit(watch, fake, monkeypatch):  # noqa: F811
    import rate_limit
    seen = []
    monkeypatch.setattr(rate_limit, "allow", lambda bucket, key, **kw: seen.append((bucket, key)) or False)
    r = _post(_app(fake, monkeypatch), "/my/sermons/progress", {"id": M[0], "pos": 100, "dur": 2292, "m": "v"})
    assert r.status_code == 429 and seen == [("member_watch", f"{tct.BIZ}|{tct.ANA}")]
    assert rate_limit._LIMITS["member_watch"][1] == 600


def test_progress_is_guarded_by_updated_at(watch, fake, monkeypatch):  # noqa: F811
    _places(fake)
    calls = []
    real = fake.patch

    def patch(path, body, **kw):
        calls.append(path)
        return [] if len(calls) == 1 else real(path, body, **kw)               # an office edit landed first
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    r = _post(_app(fake, monkeypatch), "/my/sermons/progress", {"id": M[1], "pos": 300, "dur": 2200, "m": "v"})
    assert r.json()["ok"] and len(calls) == 2 and all("updated_at=eq." in c for c in calls)
    assert all(f"id=eq.{tct.ANA}" in c and f"business_id=eq.{tct.BIZ}" in c for c in calls)


def test_save_with_a_script_and_without(watch, fake, monkeypatch):  # noqa: F811
    _places(fake)
    c = _app(fake, monkeypatch)
    r = _post(c, "/my/sermons/save", {"id": M[2], "on": 1})
    assert r.json()["ok"] and r.json()["on"] is True and M[2] in _mine(fake)["s"]
    r = _post(c, "/my/sermons/save", {"id": M[2], "on": "0", "back": f"/my/sermons/{M[2]}"}, json_=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/sermons/{M[2]}" and M[2] not in _mine(fake)["s"]
    r = _post(c, "/my/sermons/save", {"id": M[2], "on": "1", "back": "https://evil.test/"}, json_=False)
    assert r.headers["location"] == "/my/sermons"
    html = _get(fake, monkeypatch, f"/my/sermons/{M[2]}")
    assert f'data-lw-save="{M[2]}" aria-pressed="true"' in html and "<span>Saved</span>" in html
    assert _post(c, "/my/sermons/save", {"id": M[2], "on": 1}, origin="https://evil.test").status_code == 403


# ─── Add to calendar ─────────────────────────────────────────────────


def test_the_service_for_the_calendar(watch, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    assert c.get("/my/sermons/live.ics").status_code == 404                 # the office never saved a time
    mlw._SLOTS.clear()
    _service(fake, weekday=6, at="10:30:00", tz="America/Chicago")
    r = c.get("/my/sermons/live.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert r.headers["cache-control"] == "public, max-age=3600"
    body = r.text
    assert "\r\n" in body and "RRULE:FREQ=WEEKLY;BYDAY=SU" in body and "DTSTART;TZID=America/Chicago:" in body
    assert "T103000" in body and "BEGIN:VTIMEZONE" in body and "TZID:America/Chicago" in body
    assert "SUMMARY:Sunday Worship · Grace Fellowship" in body and f"URL:https://{tct.HOST}/my/live" in body
    assert "DTEND" not in body and "DURATION" not in body                    # we don't know how long it runs
    first = re.search(r"DTSTART;TZID=America/Chicago:(\d{8})", body).group(1)
    assert datetime.strptime(first, "%Y%m%d").weekday() == 6
    fake.gets.clear()
    c.get("/my/sermons/live.ics")
    assert not any("church_checkin_settings" in g for g in fake.gets)         # kept


def test_ics_pieces():
    tz = mlw.vtimezone("America/New_York", 2026)
    assert "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU" in tz and "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU" in tz
    assert "TZOFFSETFROM:-0500" in tz and "TZOFFSETTO:-0400" in tz
    assert "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU" in mlw.vtimezone("Europe/London", 2026)
    assert [x for x in mlw.vtimezone("America/Phoenix", 2026) if x.startswith("TZOFFSET")] == \
        ["TZOFFSETFROM:-0700", "TZOFFSETTO:-0700"]
    long = mlw._fold("DESCRIPTION:" + "x" * 200)
    assert all(len(line.encode()) <= 75 for line in long.split("\r\n")) and "\r\n " in long
    assert mlw._ics_text("a, b; c\\d\ne") == "a\\, b\\; c\\\\d\\ne"


# ─── reads, the record, the sheet, the words ─────────────────────────


@pytest.mark.parametrize("path", ["/my/sermons", "/my/sermons?view=series", f"/my/sermons?series={S1}",
                                  f"/my/sermons/{M[1]}", f"/my/sermons/{M[0]}?listen=1"])
def test_the_same_reads_as_off(watch, fake, monkeypatch, path):  # noqa: F811
    _service(fake)
    got = {}
    for mode in ("off", "on"):
        monkeypatch.setenv("MEMBER_LUMEN", mode)
        c = _app(fake, monkeypatch)
        c.get(path)                                                         # warm what's kept
        fake.gets.clear()
        c.get(path)
        got[mode] = Counter(r.split("?")[0] for r in fake.gets)
    assert got["on"] == got["off"], (got["on"] - got["off"], got["off"] - got["on"])


def test_the_household_read_carries_her_places():
    import inspect
    import member_portal as mp
    for fn in (mp.contacts_for_email, mp.contacts_for_phone):
        assert "watch:metadata->member_watch" in inspect.getsource(fn)
    assert mlw.state({"watch": {"p": {M[0]: [10, 20, 30, "a"]}}})["p"][M[0]] == [10, 20, 30, "a"]
    assert mlw.state({"metadata": {"member_watch": {"s": [M[1]]}}})["s"] == {M[1]: 0}


def test_clean_keeps_only_what_is_safe():
    raw = {"p": {M[0]: [99999999, 50, 1, "v"], "bad": [1, 2, 3, "v"], M[1]: ["x"], M[2]: [5, 0, 9, "zz"],
                 **{f"00000000-0000-4000-8000-0000000007{i:02d}": [1, 2, i, "a"] for i in range(30)}},
           "s": {M[3]: "x", "nope": 1}}
    st = mlw.clean(raw)
    assert len(st["p"]) == mlw.MAX_PROGRESS and "bad" not in st["p"] and M[1] not in st["p"]
    assert st["s"] == {M[3]: 0}
    assert mlw.clean({"p": {M[0]: [99999999, 50, 1, "v"]}})["p"][M[0]][:2] == [50, 50]
    assert mlw.clean({"p": {M[2]: [5, 0, 9, "zz"]}})["p"][M[2]][3] == "v"


def test_words():
    assert mlw.clock(2292) == "38:12" and mlw.clock(3723) == "1:02:03"
    assert mlw.minutes(2292) == "38 min" and mlw.minutes(3900) == "1 hr 5 min" and mlw.minutes(3600) == "1 hr"
    assert mlw.left(1188, 2200) == "17 min left" and mlw.left(2190, 2200) == "1 min left"
    assert mlw.span([{"preached_on": "2026-11-01"}, {"preached_on": "2026-11-15"}]) == "November 2026"
    assert mlw.span([{"preached_on": "2026-10-04"}, {"preached_on": "2026-11-15"}]) == "Oct – Nov 2026"
    assert mlw.span([{"preached_on": "2025-12-28"}, {"preached_on": "2026-01-04"}]) == "Dec 2025 – Jan 2026"
    assert mlw.span([{}]) == ""
    assert mlw.questions("1. One?\n2) Two?\n- Three?") == ["One?", "Two?", "Three?"]
    assert mlw.questions("1. One? 2. Two? 3. Three?") == ["One?", "Two?", "Three?"]
    assert mlw.questions("Just one question here?") == ["Just one question here?"]
    assert mlw.passages("Isaiah 9:6; Isaiah 9:2, John 1:5", "kjv") == [
        ("Isaiah 9", "/my/bible/isaiah/9#v6"), ("John 1", "/my/bible/john/1#v5")]
    assert mlw.passages("Psalm 23", "kjv") == [("Psalms 23", "/my/bible/psalms/23")]
    assert mlw.done(2250, 2292) and mlw.done(950, 1000) and not mlw.done(100, 2292) and not mlw.done(100, 0)
    assert mlw.started(25, 2292) and not mlw.started(10, 2292) and not mlw.started(2290, 2292)


def test_the_sheet_carries_the_watch_block_before_the_type():
    import member_lumen_fonts
    parts = lm.templates()
    assert mlw.CSS in parts and parts[-1].template == member_lumen_fonts.template().template   # the type last
    assert "$" not in mlw.CSS.template
    text = re.sub(r"/\*.*?\*/", "", mlw.CSS.template, flags=re.S)
    for sel in re.findall(r"(?:^|\})\s*([^{}@]+)\{", re.sub(r"@media[^{]*\{|@supports[^{]*\{", "", text)):
        for one in sel.split(","):
            assert one.strip().startswith(".lm"), one
    # Moves only for a phone that wants them.
    assert "transition:transform" in text and "@media (prefers-reduced-motion:no-preference){" in mlw.CSS.template
    assert "#1F1F22" not in mlw.CSS.template and "#0A0A0B" not in mlw.CSS.template   # tokens, not the dark's colours


def test_the_script_keeps_the_contracts():
    for bit in ("lm:progress", "'lw:'+S.who", "/my/sermons/progress", "/my/sermons/save", "sendBeacon", "keepalive",
                "visibilitychange", "pagehide", "60000", "mediaSession", "event:'listening'",
                "method:'addEventListener'", "e.defaultPrevented", "navigator.share", "pageshow"):
        assert bit in mlw.JS, bit
    assert "</script" not in mlw.JS and "<script" not in mlw.JS


def test_the_script_is_its_own_kept_file(watch, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    r = c.get(mlw.js_url())
    assert r.status_code == 200 and r.content == mlw.js_file()[0] and r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    stale = c.get("/my/watch.000000000000.js")
    assert stale.content == mlw.js_file()[0] and stale.headers["cache-control"] == "no-store"
    assert re.fullmatch(r"/my/watch\.[0-9a-f]{12}\.js", mlw.js_url())

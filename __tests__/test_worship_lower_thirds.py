# __tests__/test_worship_lower_thirds.py
#
# Lower thirds (ChurchSavvy, 2026-11-15; Kevin: "could we also have a way to
# place lower thirds if we need to do lower thirds by itself"; worship_show.py,
# worship_show_router.py, worship_count_auto.py). Pins:
#   * the lower third item: its name line (needed) and the line under it, one
#     line each and capped, who sees it, its own background; it compiles to one
#     `third` slide every screen draws its own way
#   * "show as a lower third": songs, passages and slides only, written only
#     when on (so an old item comes back key for key), on every slide it makes
#   * the look: its saved lower thirds (capped, each with its own id), the six
#     designs; bar and shadow at the top or bottom come back exactly as they were
#     and an old look comes back key for key (plus an empty list of saved ones)
#   * the booth's lower third over anything: put up, taken down, who sees it,
#     going down by itself, refused when it isn't one; it never moves the slide
#     under it, rides through every press, a press that says nothing of it keeps
#     it, a restart brings it back, and the countdown that starts by itself
#     keeps it
#   * a room screen's words as lower thirds: saved and read by its link, an old
#     screen draws full slides, only the three ways; before the column is there
#     (PostgREST's 42703) screens read exactly as before, and the setting waits
#   * a look too full to save says what to take out

import pathlib
import sys
import time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import sb_clients  # noqa: E402
import worship_show as wsh  # noqa: E402
import worship_show_router as wsr  # noqa: E402
import test_worship_show_router as base  # noqa: E402
from test_worship_show_router import BIZ, api, plan  # noqa: E402,F401  (api is the fixture)

AT = "2026-11-15T15:20:00+00:00"


def item(kind, **kw):
    return wsh.clean_item({"id": kw.pop("id", kind), "kind": kind, **kw})


# ─── the lower third item ─────────────────────────────────────────────


def test_a_lower_third_item_is_its_two_lines():
    it = item("third", name="  Pastor Kevin   McClain ", sub="Senior\nPastor", show="online")
    assert (it["name"], it["sub"], it["show"]) == ("Pastor Kevin McClain", "Senior Pastor", "online")
    assert item("third", name="Give at lovecity.church/give")["sub"] == ""
    # Its own background, behind it in the room.
    own = item("third", name="Guest speaker", bg={"kind": "color", "color": "#2E1A47"})
    assert own["bg"] == {"kind": "color", "color": "#2E1A47", "url": None, "dim": 0.55}
    for bad, words in [({}, "needs its name line"), ({"name": "   "}, "needs its name line"),
                       ({"name": "x" * (wsh.THIRD_NAME + 1)}, f"at most {wsh.THIRD_NAME}"),
                       ({"name": "Pastor", "sub": "x" * (wsh.THIRD_SUB + 1)}, f"at most {wsh.THIRD_SUB}"),
                       ({"name": 7}, "should be text"),
                       ({"name": "Pastor", "show": "lobby"}, "everyone, the room only, or online only")]:
        with pytest.raises(ValueError, match=words):
            item("third", **bad)
    # The longest of each passes.
    assert len(item("third", name="n" * wsh.THIRD_NAME, sub="s" * wsh.THIRD_SUB)["sub"]) == wsh.THIRD_SUB


def test_a_lower_third_item_is_one_third_slide():
    it = item("third", name="Pastor Kevin McClain", sub="Senior Pastor", minutes=1, who="Media",
              bg={"kind": "design", "design": "glass"})
    out = wsh.compile_item(it, {})
    assert out["title"] == "Pastor Kevin McClain" and (out["kind"], out["show"], out["minutes"]) == ("third", "all", 1.0)
    assert out["slides"] == [{"kind": "third", "name": "Pastor Kevin McClain", "sub": "Senior Pastor",
                              "bg": {"kind": "design", "color": None, "url": None, "dim": 0.55, "design": "glass"}}]
    plain = wsh.compile_item(item("third", name="Give online"), {})
    assert plain["slides"] == [{"kind": "third", "name": "Give online", "sub": ""}]
    show = wsh.compile_show({"items": [it, item("text", id="pts", slides=[{"text": "Stones"}])]}, {})
    assert show["slide_count"] == 2 and show["missing"] == []


def test_sunday_plannings_order_names_a_lower_third():
    import sunday_order
    it = item("third", name="Pastor Kevin McClain", sub="Senior Pastor")
    assert sunday_order._name(it, {}) == {"title": "Pastor Kevin McClain", "sub": "Lower third · Senior Pastor"}
    assert sunday_order._name(item("third", name="Give online"), {}) == {"title": "Give online", "sub": "Lower third"}


# ─── show as a lower third ────────────────────────────────────────────


def test_songs_passages_and_slides_can_run_as_lower_thirds():
    song = item("song", song_id=base.SONG_ID, as_third=True)
    verse = item("scripture", ref="John 3:16", as_third=True)
    text = item("text", slides=[{"kicker": "Point 1", "text": "Stop and pick up stones"}], as_third=True)
    assert song["as_third"] is verse["as_third"] is text["as_third"] is True
    for it, songs in ((song, {base.SONG_ID: base.SONG}), (verse, {}), (text, {})):
        slides = wsh.compile_item(it, songs)["slides"]
        assert slides and all(s["as_third"] is True for s in slides)
    # Only those three; anything but true is off, and off isn't written at all.
    assert "as_third" not in item("announcement", title="Lunch", as_third=True)
    assert "as_third" not in item("third", name="Pastor", as_third=True)
    assert "as_third" not in item("song", song_id=base.SONG_ID, as_third="yes")
    old = {"id": "well", "kind": "song", "song_id": base.SONG_ID, "arrangement_id": None, "show": "all", "notes": "",
           "who": "", "stage": "", "minutes": 5.0}
    assert wsh.clean_item(old) == old                                  # an item saved before comes back key for key
    assert all("as_third" not in s for s in wsh.compile_item(old, {base.SONG_ID: base.SONG})["slides"])


# ─── the look ─────────────────────────────────────────────────────────


OLD_LOOK = {
    "background": {"kind": "image", "color": None, "url": "https://x.example/stage.jpg", "dim": 0.55},
    "size": "std", "caps": False, "align": "center", "font": None, "shadow": True, "translation": "kjv",
    "lower_third": {"style": "shadow", "position": "top"},
    "brand": {"primary": None, "accent": None, "background": None, "logo_url": None},
    "quick": [], "workspace": "dark", "crawls": ["The overflow lot is open on 5th Street."],
    "countdown": {"design": "glass", "title": "We start soon", "welcome": "", "big_last": True, "times": []},
    "fonts": None, "series": [],
}


def test_an_old_look_comes_back_as_it_was():
    look = wsh.clean_look(OLD_LOOK)
    assert look == {**OLD_LOOK, "thirds": []}
    for style in ("bar", "shadow"):
        for position in ("bottom", "top"):
            got = wsh.clean_look({"lower_third": {"style": style, "position": position}})["lower_third"]
            assert got == {"style": style, "position": position}
    assert wsh.clean_look({})["lower_third"] == {"style": "bar", "position": "bottom"} == wsh.DEFAULT_LOOK["lower_third"]
    assert wsh.clean_look({})["thirds"] == [] == wsh.DEFAULT_LOOK["thirds"]


def test_the_lower_third_designs():
    assert wsh.LT_STYLES == ("bar", "shadow", "glass", "stripe", "tag", "band")
    for style in wsh.LT_STYLES:
        assert wsh.clean_look({"lower_third": {"style": style}})["lower_third"] == {"style": style, "position": "bottom"}
    for bad in ({"style": "neon"}, {"style": "glass", "position": "middle"}):
        with pytest.raises(ValueError, match="one of the designs, at the bottom or the top"):
            wsh.clean_look({"lower_third": bad})


def test_saved_lower_thirds_in_the_look():
    thirds = [{"id": "kevin", "name": " Pastor Kevin McClain ", "sub": "Senior Pastor"},
              {"id": "give", "name": "Give at lovecity.church/give"}]
    assert wsh.clean_look({"thirds": thirds})["thirds"] == [
        {"id": "kevin", "name": "Pastor Kevin McClain", "sub": "Senior Pastor"},
        {"id": "give", "name": "Give at lovecity.church/give", "sub": ""}]
    many = [{"id": f"t-{k}", "name": f"Guest {k}"} for k in range(wsh.MAX_THIRDS)]
    assert len(wsh.clean_look({"thirds": many})["thirds"]) == wsh.MAX_THIRDS
    for bad, words in [(many + [{"id": "t-x", "name": "One more"}], f"up to {wsh.MAX_THIRDS}"),
                       ([{"id": "a", "name": "A"}, {"id": "a", "name": "B"}], "its own id"),
                       ([{"id": "Not An Id!", "name": "A"}], "its own id"),
                       ([{"id": "a", "name": ""}], "needs its name line"),
                       ([{"id": "a", "name": "A", "sub": "s" * (wsh.THIRD_SUB + 1)}], f"at most {wsh.THIRD_SUB}"),
                       (["Pastor Kevin"], "isn't a lower third"),
                       ("Pastor Kevin", f"up to {wsh.MAX_THIRDS}")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_look({"thirds": bad})


# ─── the booth's lower third, over anything ───────────────────────────


def booth(**kw):
    return {"name": "Pastor Kevin McClain", "sub": "Senior Pastor", "show": "all", "at": AT, **kw}


def test_the_booth_puts_a_lower_third_up_over_anything():
    live = wsh.clean_live({"service_id": None, "item_id": "well", "slide": 2, "third": booth(seconds=15, id="kevin")})
    assert live["third"] == {"name": "Pastor Kevin McClain", "sub": "Senior Pastor", "show": "all", "at": AT,
                             "seconds": 15, "id": "kevin"}
    assert (live["item_id"], live["slide"]) == ("well", 2)            # the slide under it stays where it was
    typed = wsh.clean_live({"third": {"name": " Welcome,   guests ", "at": AT, "show": "room"}})["third"]
    assert typed == {"name": "Welcome, guests", "sub": "", "show": "room", "at": AT, "seconds": None, "id": None}
    assert wsh.clean_live({"third": booth(seconds=0)})["third"]["seconds"] is None   # 0: until it's taken down
    assert wsh.clean_live({"third": booth(seconds=30.0)})["third"]["seconds"] == 30
    assert "third" not in wsh.clean_live({"third": None})              # taken down
    for bad, words in [("Pastor", "needs its name line"), (booth(name=""), "needs its name line"),
                       (booth(show="stage"), "everyone, the room only, or online only"),
                       (booth(at="soon"), "isn't a time"), (booth(at=None), "isn't a time"),
                       (booth(seconds=2), "3 to 600 seconds"), (booth(seconds=601), "3 to 600 seconds"),
                       (booth(seconds=True), "3 to 600 seconds"), (booth(seconds="15"), "3 to 600 seconds"),
                       (booth(id="Not An Id!"), "saved lower thirds"),
                       (booth(name="x" * (wsh.THIRD_NAME + 1)), f"at most {wsh.THIRD_NAME}")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_live({"third": bad})


def test_a_press_that_says_nothing_of_it_keeps_it():
    up = {"third": wsh.clean_live_third(booth())}
    assert wsh.carry_third(up, {"slide": 3})["third"] == up["third"]
    assert "third" not in wsh.carry_third({}, {"slide": 3})
    assert "third" not in wsh.carry_third(None, {"slide": 3})
    newer = wsh.clean_live_third(booth(name="Guest speaker"))
    assert wsh.carry_third(up, {"third": newer})["third"] == newer     # what's sent wins


def test_over_http_it_rides_on_top_and_comes_back_after_a_restart(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    sid = plan(as_).json()["service"]["id"]
    token = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector"}).json()["screen"]["token"]
    press = lambda state: as_("owner").post("/worship/live", json={"business_id": BIZ, "state": state})  # noqa: E731
    live = lambda: as_("member").get(f"/worship/live?business_id={BIZ}").json()["state"]  # noqa: E731

    assert press({"service_id": sid, "item_id": "well", "slide": 1}).status_code == 200
    r = press({"service_id": sid, "item_id": "well", "slide": 1, "third": booth(show="online", seconds=20)})
    assert r.status_code == 200, r.text
    now = live()
    assert (now["item_id"], now["slide"]) == ("well", 1) and now["third"]["show"] == "online"
    # The booth's every press sends it again (useBooth's base); one that says nothing of it keeps it.
    press({"service_id": sid, "item_id": "word", "slide": 0, "third": now["third"]})
    press({"service_id": sid, "item_id": "word", "slide": 1})
    assert live()["third"]["name"] == "Pastor Kevin McClain" and live()["slide"] == 1
    # A restarted server brings it back from the saved row, and a screen's link hears it.
    wsr.HUB = wsr.LiveHub()
    assert live()["third"]["seconds"] == 20
    assert wsr._current(BIZ)[1]["third"]["name"] == "Pastor Kevin McClain"
    assert as_("stranger").get(f"/worship/screen/{token}/show").status_code == 200
    # Taken down: a press that sends none.
    press({"service_id": sid, "item_id": "word", "slide": 1, "third": None})
    assert "third" not in live() and live()["item_id"] == "word"
    # Only the booth puts one up, and only a real one.
    assert as_("member").post("/worship/live", json={"business_id": BIZ, "state": {"third": booth()}}).status_code == 403
    bad = press({"service_id": sid, "item_id": "word", "third": booth(seconds=9000)})
    assert bad.status_code == 400 and "seconds" in bad.json()["detail"]


def test_the_countdown_that_starts_by_itself_keeps_it(monkeypatch):
    import worship_count_auto as wca

    up = {"service_id": None, "item_id": None, "slide": 0, "mode": "logo", "at": "2026-11-15T14:00:00+00:00",
          "third": wsh.clean_live_third(booth())}
    wrote = {}
    monkeypatch.setattr(wca, "_live", lambda biz: (True, (5, dict(up))))
    monkeypatch.setattr(wca, "_service_near", lambda biz, ends: (True, None))
    monkeypatch.setattr(wca, "_claim", lambda *a, **k: True)
    monkeypatch.setattr(wca, "_put_live", lambda biz, new, live, now: wrote.update(new) or 6)
    now = datetime(2026, 11, 15, 15, 15, tzinfo=timezone.utc)
    t = {"id": "sun", "on": True, "days": [0], "at": "10:15", "minutes": 15, "where": "all"}
    got = wca.start_one(BIZ, t, now, wsh.clean_look({})["countdown"], [t], now)
    assert got == "up" and wrote["adhoc"]["kind"] == "countdown" and wrote["third"] == up["third"]


# ─── a room screen's words as lower thirds ────────────────────────────


def test_a_screens_words_setting():
    assert wsh.clean_words(None) == wsh.clean_words({}) == {"as": "slides"}
    for how in wsh.WORDS_AS:
        assert wsh.clean_words({"as": how}) == {"as": how}
    with pytest.raises(ValueError, match="full slides or as lower thirds"):
        wsh.clean_words({"as": "captions"})


def test_a_room_screen_shows_words_as_lower_thirds(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    screen = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Side screen", "role": "room",
                                                          "words": {"as": "see_through"}}).json()["screen"]
    assert screen["words"] == {"as": "see_through"}
    info = as_("stranger").get(f"/worship/screen/{screen['token']}").json()
    assert info["screen"]["words"] == {"as": "see_through"}
    saved = as_("owner").put(f"/worship/screens/{screen['id']}", json={"business_id": BIZ, "words": {"as": "thirds"}})
    assert saved.status_code == 200 and saved.json()["screen"]["words"] == {"as": "thirds"}
    bad = as_("owner").put(f"/worship/screens/{screen['id']}", json={"business_id": BIZ, "words": {"as": "captions"}})
    assert bad.status_code == 400
    # A screen made before the setting has the column's default ({}, the migration's): full slides.
    db.t["worship_screens"].append({**db.t["worship_screens"][0], "id": "old-screen", "token": "O" * 43, "name": "Projector",
                                    "words": {}})
    listed = {s["name"]: s for s in as_("owner").get(f"/worship/screens?business_id={BIZ}").json()["screens"]}
    assert listed["Projector"]["words"] == {"as": "slides"} and listed["Side screen"]["words"] == {"as": "thirds"}


def test_before_the_column_is_there_screens_read_as_before(api, monkeypatch):
    """PostgREST refuses a read that asks for a column that isn't there (42703); the screens
    are read without it, draw full slides, and the setting waits. Any other failure is a 503."""
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setattr(wsr, "_NO_WORDS", {"at": 0.0})
    token = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector"}).json()["screen"]["token"]
    for r in db.t["worship_screens"]:
        r.pop("words", None)
    err = {"now": None}
    real_get, real_patch = db.get, db.patch

    def refuse(call):
        def run(path, *a, **k):
            if "worship_screens" in path and "words" in path:
                err["now"] = {"status": 400, "code": "42703", "message": "column worship_screens.words does not exist"}
                return None
            err["now"] = None
            return call(path, *a, **k)
        return run

    monkeypatch.setattr(sb_clients, "sb_get_as_service", refuse(real_get))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", refuse(real_patch))
    monkeypatch.setattr(sb_clients, "last_error", lambda: err["now"])

    info = as_("stranger").get(f"/worship/screen/{token}")
    assert info.status_code == 200 and "words" not in info.json()["screen"]
    listed = as_("owner").get(f"/worship/screens?business_id={BIZ}").json()["screens"]
    assert listed and "words" not in listed[0]
    sid = listed[0]["id"]
    renamed = as_("owner").put(f"/worship/screens/{sid}", json={"business_id": BIZ, "name": "Main projector"})
    assert renamed.status_code == 200 and renamed.json()["screen"]["name"] == "Main projector"
    wait = as_("owner").put(f"/worship/screens/{sid}", json={"business_id": BIZ, "words": {"as": "thirds"}})
    assert wait.status_code == 400 and "aren't ready yet" in wait.json()["detail"]
    # A minute later it's asked again: the migration ran, and every screen has the column's default.
    for r in db.t["worship_screens"]:
        r["words"] = {}
    monkeypatch.setattr(wsr, "_NO_WORDS", {"at": time.monotonic() - wsr.NO_WORDS_SECONDS - 1})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real_get)
    assert "words" in as_("stranger").get(f"/worship/screen/{token}").json()["screen"]

    # Any other failed read is a 503, never a guess.
    def down(path, *a, **k):
        err["now"] = {"status": 503, "code": "", "message": "upstream"}
        return None
    monkeypatch.setattr(wsr, "_NO_WORDS", {"at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", down)
    assert as_("stranger").get(f"/worship/screen/{token}").status_code == 503
    assert as_("owner").get(f"/worship/screens?business_id={BIZ}").status_code == 503
    assert wsr._NO_WORDS["at"] == 0.0


# ─── saving the look ──────────────────────────────────────────────────


def test_saved_lower_thirds_save_and_a_full_look_says_what_to_take_out(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    look = as_("owner").get(f"/worship/look?business_id={BIZ}").json()["look"]
    thirds = [{"id": "kevin", "name": "Pastor Kevin McClain", "sub": "Senior Pastor"}]
    r = as_("owner").put("/worship/look", json={"business_id": BIZ, "look": {**look, "thirds": thirds,
                                                                             "lower_third": {"style": "tag", "position": "top"}}})
    assert r.status_code == 200, r.text
    got = as_("member").get(f"/worship/look?business_id={BIZ}").json()["look"]
    assert got["thirds"] == thirds and got["lower_third"] == {"style": "tag", "position": "top"}
    # Every list full and every line as long as it may be: past the row's own size, say what to take out.
    full = {**look,
            "thirds": [{"id": f"t-{k}", "name": "n" * wsh.THIRD_NAME, "sub": "s" * wsh.THIRD_SUB} for k in range(wsh.MAX_THIRDS)],
            "crawls": ["c" * wsh.CRAWL_TEXT] * wsh.MAX_CRAWLS,
            "quick": [{"id": f"q-{k}", "kind": "text", "label": "l" * 24, "text": "w" * 120} for k in range(wsh.MAX_QUICK)],
            "series": [{"id": f"s-{k}", "name": "x" * 60, "from": f"2026-{k + 1:02d}-01", "to": f"2026-{k + 1:02d}-02",
                        "fonts": "warm", "background": {"kind": "image", "url": "https://x.example/" + "p" * 300 + ".jpg"}}
                       for k in range(wsh.MAX_SERIES)]}
    r = as_("owner").put("/worship/look", json={"business_id": BIZ, "look": full})
    assert r.status_code == 400 and "too full to save" in r.json()["detail"]
    assert as_("member").get(f"/worship/look?business_id={BIZ}").json()["look"]["thirds"] == thirds   # nothing changed

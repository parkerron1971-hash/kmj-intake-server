"""The Bible, rebuilt (member app round three, Kevin approved 2026-10-19):
highlights, private notes and saved verses (member_bible_marks), the reader,
search, recent chapters, and Highlights & notes."""
import asyncio
import json

import pytest
from starlette.requests import Request

import member_bible_marks as mbm
import member_portal_bible as mpb

BIZ = {"id": "11111111-1111-4111-8111-111111111111", "name": "Love City Church", "type": "church", "settings": {}}
ME = {"id": "22222222-2222-4222-8222-222222222222", "name": "Jasmine Carter"}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    import giving_router
    import reading_plans as rp
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(rp, "current", lambda biz: None)


def req(path="/my/bible", query="", cookie=""):
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": path, "query_string": query.encode(), "headers": headers})


def go(path, query="", cookie="", preview=False):
    return asyncio.run(mpb.serve(req(path, query, cookie), BIZ, None, ME, path, preview=preview))


# ─── a change, checked ───────────────────────────────────────────────


def test_a_change_is_a_real_verse_and_a_known_colour_note_or_bookmark():
    ok = mbm.clean({"book": "PRO", "chapter": 4, "verse": 25, "colour": "gold"})
    assert ok == {"book": "PRO", "chapter": 4, "verse": 25, "colour": "gold"}
    assert mbm.clean({"book": "PRO", "chapter": 4, "verse": 25, "colour": ""})["colour"] is None    # take it off
    assert mbm.clean({"book": "PRO", "chapter": 4, "verse": 25, "note": "  Guard it  "})["note"] == "Guard it"
    assert mbm.clean({"book": "PRO", "chapter": 4, "verse": 25, "bookmark": True})["bookmarked"] is True
    for bad in ({"book": "XYZ", "chapter": 1, "verse": 1, "colour": "gold"},
                {"book": "PRO", "chapter": 4, "verse": 28, "colour": "gold"},       # Proverbs 4 has 27
                {"book": "PRO", "chapter": 40, "verse": 1, "colour": "gold"},
                {"book": "PRO", "chapter": 4, "verse": 25, "colour": "neon"},
                {"book": "PRO", "chapter": 4, "verse": 25, "note": "x" * 2001},
                {"book": "PRO", "chapter": 4, "verse": 25, "bookmark": "yes"},
                {"book": "PRO", "chapter": 4, "verse": 25},                           # nothing to change
                {"book": "PRO", "chapter": "four", "verse": 25, "colour": "gold"}):
        assert mbm.clean(bad) is None, bad


def test_saving_upserts_merges_and_drops_an_empty_mark(monkeypatch):
    import sb_clients
    rows = {}
    calls = []

    def get(path):
        return [dict(rows["m"])] if "m" in rows else []

    def post(path, body, prefer=None):
        calls.append(("post", body))
        rows["m"] = {k: body[k] for k in ("book", "chapter", "verse", "colour", "note", "bookmarked")}
        return [dict(rows["m"])]

    def delete(path):
        calls.append(("delete", path))
        rows.pop("m", None)
        return True
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    v = {"book": "PRO", "chapter": 4, "verse": 23}
    assert mbm.save("b", "c", {**v, "colour": "gold"})["mark"]["colour"] == "gold"
    out = mbm.save("b", "c", {**v, "note": "Guard what I let in first"})["mark"]
    assert out["colour"] == "gold" and out["note"] == "Guard what I let in first"     # a note keeps the highlight
    assert mbm.save("b", "c", {**v, "colour": None})["mark"]["note"]                   # the note stays
    assert mbm.save("b", "c", {**v, "note": None}) == {"mark": None}                    # nothing left: gone
    assert calls[-1][0] == "delete"
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: None)
    assert mbm.save("b", "c", {**v, "colour": "teal"}) is None                         # a failed read saves nothing


def _post(body, *, session=(BIZ, ME, False)):
    import member_portal as mp
    import member_portal_church as mpc
    from unittest import mock

    async def signed_in(request):
        return {"business": session[0]}, session[1], session[2]
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    request = Request({"type": "http", "method": "POST", "path": "/my/bible/mark", "query_string": b"",
                       "headers": [(b"content-type", b"application/json")]}, receive)
    with mock.patch.object(mpc, "_signed_in", signed_in), mock.patch.object(mpc, "_allowed", lambda c, m: True), \
            mock.patch.object(mp, "_same_origin", lambda r: True), \
            mock.patch.object(mbm, "save", lambda b, c, ch: {"mark": {**ch, "note": None, "bookmarked": False}}):
        resp = asyncio.run(mbm.mark(request))
    return resp.status_code, json.loads(resp.body)


def test_the_route_saves_only_for_the_member_themselves():
    assert _post({"book": "PRO", "chapter": 4, "verse": 25, "colour": "pink"}) == \
        (200, {"ok": True, "mark": {"book": "PRO", "chapter": 4, "verse": 25, "colour": "pink", "note": None, "bookmarked": False}})
    assert _post({"book": "PRO", "chapter": 4, "verse": 25, "colour": "pink"}, session=(BIZ, None, "preview"))[0] == 403
    assert _post({"book": "PRO", "chapter": 4, "verse": 25, "colour": "pink"}, session=(BIZ, None, False))[0] == 401
    assert _post({"book": "PRO", "chapter": 4, "verse": 99, "colour": "pink"})[0] == 400


def test_the_route_is_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    routes = [(getattr(r, "path", ""), getattr(r, "methods", set()) or set()) for r in app_mod.app.routes]
    paths = [p for p, _ in routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    assert next(i for i, (p, m) in enumerate(routes) if p == "/my/bible/mark" and "POST" in m) < catch


# ─── the reader ──────────────────────────────────────────────────────


def test_the_reader_shows_a_members_marks_and_lets_them_change_them(monkeypatch):
    monkeypatch.setattr(mbm, "chapter_marks", lambda b, c, book, ch: {
        23: {"colour": "gold", "note": "Guard it </script><b>", "bookmarked": False},
        18: {"colour": "teal", "note": None, "bookmarked": True}})
    page = go("/my/bible/proverbs/4").body.decode()
    assert '<span class="bb-v hl-gold" data-v="23">' in page and '<span class="bb-v hl-teal" data-v="18">' in page
    assert 'class="bb-nm"' in page and 'class="bb-bm"' in page and 'id="bb-dock"' in page
    marks = page[page.index('id="bb-marks">') + len('id="bb-marks">'):]
    assert "</script><b>" not in marks.split("</script>")[0] and "<\\/script>" in marks           # can't break out
    assert 'href="/my/bible/proverbs"' in page                                         # the name opens the picker


def test_a_preview_never_shows_or_changes_a_members_marks(monkeypatch):
    seen = []
    monkeypatch.setattr(mbm, "chapter_marks", lambda *a: seen.append(a) or {25: {"colour": "gold"}})
    monkeypatch.setattr(mbm, "all_marks", lambda *a: seen.append(a) or [{"colour": "gold"}])
    page = go("/my/bible/proverbs/4", preview=True).body.decode()
    assert 'class="bb-v hl-gold"' not in page and 'id="bb-dock"' not in page and "private" in page
    notes = go("/my/bible/notes", preview=True).body.decode()
    assert "private to each member" in notes
    go("/my/bible", preview=True)
    assert seen == []                                                                  # never even read


def test_marks_that_cant_load_leave_reading_working(monkeypatch):
    monkeypatch.setattr(mbm, "chapter_marks", lambda *a: None)
    page = go("/my/bible/proverbs/4").body.decode()
    assert "couldn&#x27;t load" in page or "couldn't load" in page
    assert "Let thine eyes look right on" in page and 'id="bb-dock"' not in page


# ─── search, recent chapters, the notes page ─────────────────────────


def test_a_word_finds_its_verses_and_a_reference_still_opens_it(monkeypatch):
    monkeypatch.setattr(mbm, "all_marks", lambda b, c: [])
    page = go("/my/bible", "q=look right on").body.decode()
    assert 'href="/my/bible/proverbs/4?v=25#v25"' in page and '<b class="bb-q">look</b>' in page
    assert go("/my/bible", "q=Proverbs 4:25").headers["location"] == "/my/bible/proverbs/4?v=25#v25"
    assert "couldn" in go("/my/bible", "q=zzzzqq").body.decode()


def test_the_last_chapters_read_come_back_as_chips(monkeypatch):
    monkeypatch.setattr(mbm, "chapter_marks", lambda *a: {})
    monkeypatch.setattr(mbm, "all_marks", lambda b, c: [])
    cookie = go("/my/bible/proverbs/4", cookie="sol_bible=kjv|john/3~psalms/23").headers["set-cookie"]
    assert "kjv|proverbs/4~john/3~psalms/23" in cookie                                # newest first, no escapes
    home = go("/my/bible", cookie="sol_bible=kjv|proverbs/4~john/3").body.decode()
    assert 'class="bb-recent"' in home and 'href="/my/bible/john/3">John 3</a>' in home
    assert "Keep reading Proverbs 4" in home


def test_highlights_and_notes_list_filter_and_say_theyre_private(monkeypatch):
    rows = [{"book": "PRO", "chapter": 4, "verse": 23, "colour": "gold", "note": "Guard it", "bookmarked": False,
             "updated_at": "2026-10-19T12:00:00+00:00"},
            {"book": "COL", "chapter": 3, "verse": 2, "colour": "violet", "note": None, "bookmarked": True,
             "updated_at": "2026-10-10T12:00:00+00:00"}]
    from datetime import date
    page = mpb.render_notes(BIZ, None, ME, "kjv", rows, today=date(2026, 10, 19))
    assert "Proverbs 4:23" in page and "Guard it" in page and "Colossians 3:2" in page
    assert page.index("Today") < page.index("Proverbs 4:23") < page.index("Earlier") < page.index("Colossians 3:2")
    assert "staff can" in page
    only_notes = mpb.render_notes(BIZ, None, ME, "kjv", rows, show="notes", today=date(2026, 10, 19))
    assert "Proverbs 4:23" in only_notes and "Colossians 3:2" not in only_notes
    violet = mpb.render_notes(BIZ, None, ME, "kjv", rows, colour="violet", today=date(2026, 10, 19))
    assert "Colossians 3:2" in violet and "Proverbs 4:23" not in violet
    assert "couldn" in mpb.render_notes(BIZ, None, ME, "kjv", None)


def test_the_home_shows_the_members_highlights_and_notes(monkeypatch):
    monkeypatch.setattr(mbm, "all_marks", lambda b, c: [
        {"book": "PRO", "chapter": 4, "verse": 23, "colour": "gold", "note": "Guard it", "bookmarked": True,
         "updated_at": "2026-10-19T12:00:00+00:00"}])
    page = go("/my/bible").body.decode()
    assert 'href="/my/bible/notes"' in page and "<b>1</b> highlight" in page and "Keep thy heart" in page

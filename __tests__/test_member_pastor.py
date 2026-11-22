# __tests__/test_member_pastor.py
#
# Meet the pastor (member_pastor), in the member app's new look. Kevin,
# 2026-11-20, on a pastor profile for the Look 4.1 tile: "yes add one." Pins:
#   - who: whoever holds the church's senior role (its own title: Lead
#     Pastor, Pastor, Rector…), the first by name when several share it, the
#     first version's "pastor" key too; no one in it, no pastor; kept five
#     minutes, a failed read never kept;
#   - the picture: the church's Pastor spot, else their own profile photo
#     (only when members may see it), else their initials;
#   - Home: someone new sees YOUR PASTOR in Also for you (the prayer tile
#     moves below); no pastor, the tiles are today's; everyone else reads
#     nothing more (the pastor is read only for someone new, and kept);
#   - Connect: one quiet row for everyone; none without a pastor;
#   - the page: the picture, YOUR PASTOR, the name, the title, the note,
#     Send a message only when member messages let this member write to
#     them; no pastor, back to Home; switch off, it isn't there;
#   - the note: edit mode for the owner's preview and the people the owner
#     named; the write takes the picture route's checks (same site, signed
#     in, may_edit, the limit), screens a named member's words, cleans and
#     caps them, writes this church's row only, and forgets the kept church;
#   - the Pastor spot is listed only where the new look shows;
#   - the CSS is in the Lumen file before the type block, tokens only.

import pathlib
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_im_new as mim
import member_pastor as mpa
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_home import EVENING, _client, _main, church  # noqa: F401  (the fixture)

PASTOR, ELDER2 = tct.cid(1650), tct.cid(1651)
NOTE = "Welcome. We're glad you're here.\n\nCome say hello after the service."


def _roles(f, *holders, title="Lead Pastor", key="pastor", defs=True):
    if defs:
        f.t["church_role_defs"] = [{"id": "d1", "business_id": tct.BIZ, "key": key, "title": title, "job": "senior",
                                    "status": "active", "sort": 0, "created_at": "2026-01-01T00:00:00+00:00",
                                    "reports_to": None},
                                   {"id": "d2", "business_id": tct.BIZ, "key": "deacons", "title": "Deacons", "job": "care",
                                    "status": "active", "sort": 1, "created_at": "2026-01-01T00:00:00+00:00",
                                    "reports_to": None}]
    else:
        f.t["church_role_defs"] = []
    f.t["church_leader_roles"] = [{"id": f"r{i}", "business_id": tct.BIZ, "contact_id": c, "role": key, "status": "active"}
                                  for i, c in enumerate(holders)]


@pytest.fixture
def pastor(church, fake, monkeypatch):  # noqa: F811
    fake.person(PASTOR, "James Carter")
    fake.person(ELDER2, "Aaron Bell")
    _roles(fake, PASTOR)
    mpa._KEPT.clear()
    fake.biz[tct.BIZ]["settings"]["member_portal"]["pastor_note"] = {"text": NOTE, "at": "2026-11-20T00:00:00+00:00",
                                                                     "by": "owner:x"}
    fake.biz[tct.BIZ]["settings"]["member_portal"]["enabled"] = True          # the member app is on (POSTs need it)
    return church


def _new(church):
    church["told"] = {"at": (EVENING - timedelta(days=1)).isoformat(), "first_time": True}
    for kept in (mim._TOLD, mim._NOT_YET):
        kept.clear()


def _app(fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.app.include_router(mpa.router)
    c.app.router.routes.insert(0, c.app.router.routes.pop())
    return c


def _also(html):
    i = html.index('<section class="lm-also"')
    return html[i:html.index("</section>", i)]


# ─── who ─────────────────────────────────────────────────────────────


def test_who_is_the_senior_role_holder_with_its_title(pastor, fake):  # noqa: F811
    p = mpa.find(tct.BIZ)
    assert p["id"] == PASTOR and p["name"] == "James Carter" and p["title"] == "Lead Pastor"
    # The church's own word for it.
    _roles(fake, PASTOR, title="Rector")
    assert mpa.find(tct.BIZ)["title"] == "Rector"
    # Elders share it: the first by name, as church_follow_up picks.
    _roles(fake, PASTOR, ELDER2, title="Elders (Shepherds)")
    assert mpa.find(tct.BIZ)["id"] == ELDER2
    # The first version's key, with no library yet.
    _roles(fake, PASTOR, defs=False)
    assert mpa.find(tct.BIZ)["title"] == "Lead Pastor"
    # Someone holding a role that isn't the senior one isn't the pastor.
    _roles(fake, PASTOR, key="deacons", title="Deacons")
    fake.t["church_role_defs"][0]["key"] = "pastor"
    assert mpa.find(tct.BIZ) == {}
    # Invited but not yet active: not yet.
    _roles(fake, PASTOR)
    fake.t["church_leader_roles"][0]["status"] = "invited"
    assert mpa.find(tct.BIZ) == {}


def test_who_is_kept_and_a_failed_read_never_is(pastor, fake):  # noqa: F811
    b = fake.business()
    assert mpa.who(b)["id"] == PASTOR
    fake.gets.clear()
    assert mpa.who(b)["id"] == PASTOR and fake.gets == []                   # kept
    mpa._KEPT.clear()
    fake.down.add("church_leader_roles")
    assert mpa.who(b) is None and mpa.who(b) is None
    fake.down.clear()
    assert mpa.who(b)["id"] == PASTOR


def test_the_picture_spot_then_their_photo_then_initials(pastor, fake):  # noqa: F811
    b = fake.business()
    p = mpa.find(tct.BIZ)
    assert mpa.picture(b, p) == ("", "", "")
    assert '<span class="lm-pini' in mpa._art(b, p) and "<b>JC</b>" in mpa._art(b, p)
    rec = next(c for c in fake.t["contacts"] if c["id"] == PASTOR)
    rec["metadata"] = {"member_photo": {"path": "x.webp", "v": "7"}}
    p = mpa.find(tct.BIZ)
    assert mpa.picture(b, p) == (f"/my/photo/{PASTOR}?v=7", "colour", "own")
    rec["birthdate"] = None                                               # members may not see it
    assert mpa.picture(b, mpa.find(tct.BIZ)) == ("", "", "")
    b["settings"]["member_portal"]["pictures"] = {"pastor": {"url": "https://example.org/james.jpg", "look": "bw"}}
    assert mpa.picture(b, p) == ("https://example.org/james.jpg", "bw", "chosen")


# ─── Home ────────────────────────────────────────────────────────────


def test_someone_new_meets_the_pastor_on_home(pastor, fake, monkeypatch):  # noqa: F811
    _new(pastor)
    fake.add("groups", id=tct.cid(33), business_id=tct.BIZ, name="Women of Grace", active=True, kind="small_group",
             join_mode="open", meets="Tuesdays")
    html = _app(fake, monkeypatch).get("/my").text
    # Kevin's Home plan (2026-11-21) took Also for you off Home: Meet the
    # pastor is a row among the church's own cards, for someone new.
    assert 'class="lm-also"' not in html
    row = re.search(r'<a class="lf-crow" href="/my/pastor">.*?</a>', html, re.S).group(0)
    assert "<b>Meet James Carter</b>" in row and "<small>Your pastor · Lead Pastor</small>" in row and "<b>JC</b>" in row


def test_no_pastor_keeps_todays_tiles(pastor, fake, monkeypatch):  # noqa: F811
    _new(pastor)
    fake.t["church_leader_roles"].clear()
    mpa._KEPT.clear()
    html = _app(fake, monkeypatch).get("/my").text
    assert 'href="/my/pastor"' not in html and 'class="lm-also"' not in html


def test_everyone_else_sees_no_tile_and_reads_nothing_more(pastor, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    c.get("/my")
    fake.gets.clear()
    html = c.get("/my").text
    assert "Your pastor" not in html
    # (Home's own "may I post?" asks about Ana's roles when there's no news; the pastor read asks by role.)
    assert not [g for g in fake.gets if g.startswith(("/church_role_defs", "/church_leader_roles")) and "role=in." in g
                or g.startswith("/church_role_defs")]


def test_someone_new_reads_the_pastor_once_then_it_is_kept(pastor, fake, monkeypatch):  # noqa: F811
    _new(pastor)
    c = _app(fake, monkeypatch)
    mine = lambda: [g for g in fake.gets if g.startswith("/church_role_defs") or "role=in." in g]   # noqa: E731
    fake.gets.clear()
    c.get("/my")
    assert [g.split("?")[0] for g in mine()] == ["/church_role_defs", "/church_leader_roles"]
    fake.gets.clear()
    c.get("/my")
    assert mine() == []


def test_edit_mode_changes_the_pastors_picture_on_their_page(pastor, fake, monkeypatch):  # noqa: F811
    # Home's row has no Change of its own now; the Pastor spot is still in
    # the pictures list (member_app_pictures).
    _new(pastor)
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    html = _app(fake, monkeypatch).get("/my?edit=pictures").text
    assert 'href="/my/pastor"' in html and "Changing pictures" in html


# ─── Connect ─────────────────────────────────────────────────────────


def test_connect_has_one_quiet_row(pastor, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    html = c.get("/my/connect").text
    # Look 5.1's More list (member_lumen_connect.more_rows): "Your pastor", the name and the title.
    rooms = html[html.index('aria-labelledby="lm-more-h"'):]
    assert '<a class="lm-mrow" href="/my/pastor">' in rooms and "<b>Your pastor</b>" in rooms
    assert "James Carter · Lead Pastor" in rooms
    fake.t["church_leader_roles"].clear()
    mpa._KEPT.clear()
    assert 'href="/my/pastor"' not in c.get("/my/connect").text


# ─── the page ────────────────────────────────────────────────────────


def test_the_page(pastor, fake, monkeypatch):  # noqa: F811
    html = _app(fake, monkeypatch).get("/my/pastor").text
    main = _main(html)
    assert '<p class="lm-eyebrow">Your pastor</p><h1 class="lm-disp">James Carter</h1>' in main
    assert '<p class="lm-pptitle">Lead Pastor</p>' in main
    assert "<p>Welcome. We&#x27;re glad you&#x27;re here.</p><p>Come say hello after the service.</p>" in main
    assert "Send a message" not in main                                      # messages aren't on for them
    assert "lm-ppedit" not in main and "<textarea" not in main               # not an editor
    assert "<title>Meet the pastor" in html


def test_send_a_message_only_when_messages_let_them(pastor, fake, monkeypatch):  # noqa: F811
    import member_portal_messaging as mpm
    monkeypatch.setattr(mpm, "turned_on", lambda b: True)
    for c in (tct.ANA, PASTOR):
        fake.t.setdefault("msg_members", []).append({"business_id": tct.BIZ, "contact_id": c, "enabled": True,
                                                     "guidelines_at": "2026-01-01T00:00:00+00:00"})
    c = _app(fake, monkeypatch)
    assert f'<a class="lm-btn" href="/my/messages/to/{PASTOR}">Send a message</a>' in c.get("/my/pastor").text
    # A block (either way) says nothing and shows nothing.
    fake.t.setdefault("msg_blocks", []).append({"business_id": tct.BIZ, "blocker_contact_id": PASTOR,
                                                "blocked_contact_id": tct.ANA})
    assert "Send a message" not in c.get("/my/pastor").text
    fake.t["msg_blocks"].clear()
    monkeypatch.setattr(mpm, "turned_on", lambda b: False)
    assert "Send a message" not in c.get("/my/pastor").text


def test_no_pastor_goes_home_and_switch_off_has_no_page(pastor, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    fake.t["church_leader_roles"].clear()
    mpa._KEPT.clear()
    r = c.get("/my/pastor", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    _roles(fake, PASTOR)
    mpa._KEPT.clear()
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    r = c.get("/my/pastor", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    assert "Your pastor" not in c.get("/my/connect", follow_redirects=True).text


# ─── the note ────────────────────────────────────────────────────────


def test_edit_mode_for_editors_only(pastor, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    assert "<textarea" not in c.get("/my/pastor?edit=pictures").text          # not an editor: the page as is
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    page = c.get("/my/pastor").text
    assert '<a href="/my/pastor?edit=pictures">' in page
    html = c.get("/my/pastor?edit=pictures").text
    assert '<form class="lm-ppform" method="post" action="/my/pastor/note">' in html
    assert f'maxlength="{mpa.NOTE_MAX}"' in html and "Welcome. We&#x27;re glad you&#x27;re here." in html
    assert 'href="/my/pictures/spot?key=pastor&amp;back=pastor"' in html and "Changing this page" in html


def _businesses_patch(fake, monkeypatch):  # noqa: F811
    """The fake keeps churches apart from its tables: a PATCH of /businesses
    writes the church's row (and says which one)."""
    import sb_clients
    wrote = []
    plain = sb_clients.sb_patch_as_service

    def patch(path, body, **kw):
        if not path.startswith("/businesses?"):
            return plain(path, body, **kw)
        bid = path.split("id=eq.", 1)[1].split("&", 1)[0]
        wrote.append(bid)
        if bid not in fake.biz:
            return []
        fake.biz[bid].update(body)
        return [fake.biz[bid]]
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    return wrote


def _post(c, note, **h):

    return c.post("/my/pastor/note", data={"note": note}, headers={"origin": f"https://{tct.HOST}", **h},
                  follow_redirects=False)


def test_the_note_saves_with_the_picture_routes_checks(pastor, fake, monkeypatch):  # noqa: F811
    import member_cache
    import msg_screen
    said = []

    async def screen(b, text):
        said.append(text)
        return "harm" if "HOLD" in text else "ok"
    monkeypatch.setattr(msg_screen, "screen", screen)
    wrote = _businesses_patch(fake, monkeypatch)
    c = _app(fake, monkeypatch)
    # Not an editor: nothing saves.
    r = _post(c, "Hello")
    assert r.status_code == 303 and r.headers["location"] == "/my"
    assert fake.biz[tct.BIZ]["settings"]["member_portal"]["pastor_note"]["text"] == NOTE
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    # Another site: refused.
    assert _post(c, "Hello", origin="https://evil.example").status_code == 403
    forgot = []
    monkeypatch.setattr(member_cache, "forget_church", lambda b: forgot.append(str(b)) or 1)
    r = _post(c, "  Glad you came.\r\n\r\n\r\n\r\nSee you Sunday.  ")
    assert r.headers["location"] == "/my/pastor?edit=pictures&done=note"
    kept = fake.biz[tct.BIZ]["settings"]["member_portal"]["pastor_note"]
    assert kept["text"] == "Glad you came.\n\nSee you Sunday." and kept["by"] == f"member:{tct.ANA}"
    assert said == ["Glad you came.\n\nSee you Sunday."] and forgot == [tct.BIZ]
    assert wrote == [tct.BIZ]                                                # this church's row only
    # The other settings are untouched.
    assert fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] == [tct.ANA]
    # A named member's words that the check holds: not saved.
    assert _post(c, "HOLD this").headers["location"] == "/my/pastor?edit=pictures&err=no"
    assert fake.biz[tct.BIZ]["settings"]["member_portal"]["pastor_note"]["text"] == "Glad you came.\n\nSee you Sunday."
    # Too long.
    assert _post(c, "x" * (mpa.NOTE_MAX + 1)).headers["location"].endswith("err=long")
    # Empty takes it away.
    _post(c, "   ")
    assert "pastor_note" not in fake.biz[tct.BIZ]["settings"]["member_portal"]


def test_the_check_down_saves_nothing(pastor, fake, monkeypatch):  # noqa: F811
    import msg_screen

    async def down(b, text):
        raise msg_screen.ScreenUnavailable("down")
    monkeypatch.setattr(msg_screen, "screen", down)
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    assert _post(_app(fake, monkeypatch), "Hello").headers["location"].endswith("err=busy")
    assert fake.biz[tct.BIZ]["settings"]["member_portal"]["pastor_note"]["text"] == NOTE


def test_a_saved_picture_shows_at_once_on_this_copy(pastor, fake, monkeypatch):  # noqa: F811
    import member_app_pictures as mapic
    import member_cache
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    monkeypatch.setattr(mapic, "library", lambda b, site: ["https://example.org/james.jpg"])
    monkeypatch.setattr(mapic, "save_spot", lambda *a, **k: True)
    forgot = []
    monkeypatch.setattr(member_cache, "forget_church", lambda b: forgot.append(str(b)) or 1)
    c = _app(fake, monkeypatch)
    c.app.include_router(mapic.router)
    c.app.router.routes.insert(0, c.app.router.routes.pop())
    r = c.post("/my/pictures", data={"key": "pastor", "look": "colour", "pick": "https://example.org/james.jpg",
                                     "back": "/my/pastor?edit=pictures"},
               headers={"origin": f"https://{tct.HOST}"}, follow_redirects=False)
    assert r.headers["location"] == "/my/pastor?edit=pictures&done=picture" and forgot == [tct.BIZ]


def test_clean():
    assert mpa.clean("a\r\n\r\n\r\nb\x07 \t\nc") == "a\n\nb\nc"


# ─── the spot and the sheet ──────────────────────────────────────────


def test_the_pastor_spot_only_where_the_new_look_shows(pastor, fake, monkeypatch):  # noqa: F811
    import member_app_pictures as mapic
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    c = _app(fake, monkeypatch)
    assert "Meet the pastor" in c.get("/my/pictures").text
    spot = c.get("/my/pictures/spot?key=pastor&back=pastor").text
    assert 'name="back" value="/my/pastor?edit=pictures"' in spot and ">Meet the pastor</a>" in spot
    # With nothing chosen, the spot shows what the app shows: their initials here (no photo of their own).
    assert '<span class="pc-prev-def lm-pown" aria-hidden="true"><b>JC</b></span>' in spot
    assert "<strong>Use their initials</strong>" in spot and "Use the default picture" not in spot
    # Another spot keeps its default picture and words.
    other = c.get("/my/pictures/spot?key=prayer&back=home").text
    assert "<strong>Use the default picture</strong>" in other and "lm-pown" not in other
    assert mapic.KEY_RE.fullmatch("pastor")
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert "Meet the pastor" not in c.get("/my/pictures").text


def test_the_css_is_in_the_lumen_file_with_tokens_only():
    import member_lumen_fonts
    import member_lumen_ui as lm
    parts = lm.templates()
    assert mpa.CSS in parts and parts.index(mpa.CSS) < len(parts) - 1
    assert parts[-1].template == member_lumen_fonts.template().template
    css = mpa.CSS.template
    assert "$" not in css and not re.search(r"#[0-9a-fA-F]{3,6}\b|rgba?\(", css)
    assert "transition:" not in css and "animation:" not in css


def test_the_note_route_is_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    routes = [(getattr(r, "path", ""), getattr(r, "methods", set()) or set()) for r in app_mod.app.routes]
    paths = [p for p, _ in routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    assert next(i for i, (p, m) in enumerate(routes) if p == "/my/pastor/note" and "POST" in m) < catch


def test_switch_off_writes_no_note(pastor, fake, monkeypatch):  # noqa: F811
    """Where the new look doesn't show, the note isn't there to write: the
    route goes Home and the church's row is untouched."""
    wrote = _businesses_patch(fake, monkeypatch)
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    c = _app(fake, monkeypatch)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    r = _post(c, "Written while it's off")
    assert r.status_code == 303 and r.headers["location"] == "/my" and wrote == []
    assert fake.biz[tct.BIZ]["settings"]["member_portal"]["pastor_note"]["text"] == NOTE
    # Preview: only for the platform owner, at their own church (an editor here isn't).
    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    assert _post(c, "Written in preview").headers["location"] == "/my" and wrote == []

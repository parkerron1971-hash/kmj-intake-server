# __tests__/test_member_lumen_dark.py
#
# Light, Dark or Same as my phone in the member app's new look
# (member_lumen_look, behind MEMBER_LUMEN). Pins:
#   - which look: the member's own choice wins; until they choose, the
#     church's base (Black, the default, is Dark; any other base is Light);
#     a save on this phone wins for a short while over the session's kept
#     record, then the record wins; someone else's cookie is ignored; the
#     owner's preview keeps it in the cookie alone;
#   - every page wears it from the server (lm-dark, lm-auto, nothing for
#     Light), the phone's bar with it (two bars for Same as my phone); Watch
#     stays the cinema; Youth keeps its own look;
#   - off: a member's choice changes nothing, byte for byte; no new reads;
#   - Me carries the control (three radios, the current look checked),
#     POST /my/look saves only the member's own record (contacts.metadata),
#     signed in and same-origin, sets the cookie and clears the reader's
#     moon; a preview never writes;
#   - the reader's moon on top of the look: Dark starts the reader at night,
#     lm_night=0 keeps it by day, Same as my phone leaves it to the phone;
#   - the sheet: one dark layer, twinned for Same as my phone, the reader's
#     warm night scoped to the reader, contrast at least 4.5:1 for body text
#     and 3:1 for the quietest, the church's button colour lifted only when
#     it's too deep for near-black.

import pathlib
import re
import sys
import time
from collections import Counter

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_app_ui as ui
import member_cache
import member_lumen_look as mll
import member_portal as mp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import church, _client, _body_class  # noqa: F401  (church is a fixture)


def _look(fake, look=None, base=None):  # noqa: F811
    """Ana's own choice (None: she hasn't chosen) and the church's base."""
    for row in fake.t["contacts"]:
        if row["id"] == tct.ANA:
            row["metadata"] = {"member_look": look} if look else {}
            row["updated_at"] = "2026-11-20T10:00:00+00:00"
    mpcfg = fake.biz[tct.BIZ]["settings"]["member_portal"]
    if base is None:
        mpcfg.pop("base", None)
    else:
        mpcfg["base"] = base


def _metas(html):
    return re.findall(r'<meta name="theme-color"[^>]*>', html)


def _reads(fake, c, path):  # noqa: F811
    c.get(path)
    fake.gets.clear()
    html = c.get(path).text
    return html, Counter(r.split("?")[0] for r in fake.gets)


# ─── which look ──────────────────────────────────────────────────────


def test_the_churchs_base_decides_until_the_member_chooses():
    def biz(base):
        return {"settings": {"member_portal": {"base": base} if base else {}}}
    assert mll.church_look(biz("black")) == "dark"
    assert mll.church_look(biz(None)) == "dark"                      # no base picked: today's black
    assert mll.church_look(biz("nonsense")) == "dark"                # an unknown base reads as the default
    for base in ("white", "gray", "charcoal"):
        assert mll.church_look(biz(base)) == "light"                 # "anything else means light"
    assert mll.church_look(None) == "dark"


def test_the_members_choice_is_read_from_the_record_the_session_has():
    assert mll.stored({"look": "dark"}) == "dark"                     # the session's select alias
    assert mll.stored({"metadata": {"member_look": "auto"}}) == "auto"  # a whole record
    assert mll.stored({"look": "purple"}) is None and mll.stored({"metadata": "x"}) is None
    assert mll.stored(None) is None and mll.stored({}) is None


def test_a_save_on_this_phone_wins_briefly_then_the_record_wins():
    me = {"id": tct.ANA, "look": "light"}
    black = {"settings": {"member_portal": {"base": "black"}}}
    now = 1_800_000_000.0
    fresh = mll.cookie_value("dark", me, now - 30)
    stale = mll.cookie_value("dark", me, now - mll.BRIDGE_SECONDS - 5)
    assert mll.resolve(black, me, fresh, now=now) == "dark"          # just saved here; the kept record is behind
    assert mll.resolve(black, me, stale, now=now) == "light"         # the record wins again (a change elsewhere reaches here)
    assert mll.resolve(black, {"id": tct.ANA}, stale, now=now) == "dark"   # no record choice: this phone's
    assert mll.resolve(black, {"id": tct.ANA}, "", now=now) == "dark"      # the church's black
    other = {"id": tct.BEN}
    assert mll.from_cookie(fresh, other) == (None, 0.0)              # someone else in the household
    assert mll.resolve(black, other, fresh, now=now) == "dark"       # ...gets the church's, not Ana's
    assert mll.resolve({"settings": {"member_portal": {"base": "white"}}}, other, fresh, now=now) == "light"
    assert mll.from_cookie("dark.123", me) == (None, 0.0) and mll.from_cookie("x.1.y", me) == (None, 0.0)
    # the owner's preview: the cookie alone, however old
    assert mll.resolve(black, me, stale, preview=True, now=now) == "dark"
    assert mll.resolve(black, me, "", preview=True, now=now) == "light"


# ─── every page wears it ─────────────────────────────────────────────


def test_no_choice_at_a_black_church_is_dark(church, fake, monkeypatch):  # noqa: F811
    _look(fake, None, "black")
    html = _client(fake, monkeypatch).get("/my").text
    assert _body_class(html).split()[:2] == ["lm", "lm-tab"] and "lm-dark" in _body_class(html).split()
    assert _metas(html) == [f'<meta name="theme-color" content="{mll.DARK_BG}">']


def test_no_choice_at_a_white_church_is_light_and_unchanged(church, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    _look(fake, None, "white")
    unset = c.get("/my").text
    assert "lm-dark" not in _body_class(unset) and "lm-auto" not in _body_class(unset)
    assert _metas(unset) == ['<meta name="theme-color" content="#ffffff">']
    _look(fake, "light", "black")
    assert c.get("/my").text == unset                                  # chose Light anywhere: the same page


def test_her_choice_wins_over_the_base(church, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    _look(fake, "dark", "white")
    assert "lm-dark" in _body_class(c.get("/my/connect").text).split()
    _look(fake, "light", "black")
    assert "lm-dark" not in _body_class(c.get("/my/connect").text).split()


def test_same_as_my_phone_is_css_with_two_bars(church, fake, monkeypatch):  # noqa: F811
    _look(fake, "auto", "black")
    html = _client(fake, monkeypatch).get("/my/give").text
    cls = _body_class(html).split()
    assert "lm-auto" in cls and "lm-dark" not in cls
    assert _metas(html) == ['<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">',
                            f'<meta name="theme-color" content="{mll.DARK_BG}" media="(prefers-color-scheme: dark)">']
    sheet = ui.sheet("lumen")[0]
    at = sheet.index("@media (prefers-color-scheme:dark){body.lm.lm-auto{--bg:#0A0A0B;")
    assert at > sheet.index("body.lm.lm-dark{--bg:#0A0A0B;")          # the same layer, twice


def test_live_stays_the_cinema_in_every_look_and_watch_follows_hers(church, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    for look in ("light", "dark", "auto"):
        _look(fake, look, "black")
        member_cache.forget_all()
        html = c.get("/my/live").text
        assert "lm-dark" in _body_class(html).split() and "pg-watch" in _body_class(html).split()
        assert _metas(html) == ['<meta name="theme-color" content="#050506">']
        # Watch (Look 5.1, member_lumen_watch) wears her own look.
        watch = _body_class(c.get("/my/sermons").text).split()
        assert ("lm-dark" in watch) == (look == "dark") and ("lm-auto" in watch) == (look == "auto")


def test_youth_keeps_its_own_look(church, fake, monkeypatch):  # noqa: F811
    _look(fake, "dark", "white")
    html = _client(fake, monkeypatch, space="youth").get("/my").text
    assert "lm-dark" not in _body_class(html) and "lm" not in _body_class(html).split()


def test_off_her_choice_changes_nothing(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _client(fake, monkeypatch)
    pages = ("/my", "/my/me", "/my/bible", "/my/bible/john/1", "/my/give", "/my/sermons")
    _look(fake, None, "black")
    for p in pages:
        c.get(p)                     # the reader notes where she is: once, before comparing
    before = {p: c.get(p).text for p in pages}
    for look in ("dark", "auto", "light"):
        _look(fake, look, "black")
        c.cookies.set(mll.COOKIE, mll.cookie_value(look, {"id": tct.ANA}))
        c.cookies.set(mll.NIGHT_COOKIE, "0")
        for p in pages:
            assert c.get(p).text == before[p], (look, p)               # byte for byte
        c.cookies.delete(mll.COOKIE)
        c.cookies.delete(mll.NIGHT_COOKIE)
    assert "lm-look" not in before["/my/me"] and 'action="/my/look"' not in before["/my/me"]


def test_the_look_reads_nothing_new(church, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    for p in ("/my", "/my/me", "/my/connect", "/my/bible/john/1"):
        _look(fake, "light", "black")
        _, light = _reads(fake, c, p)
        _look(fake, "dark", "black")
        _, dark = _reads(fake, c, p)
        _look(fake, "auto", "black")
        _, auto = _reads(fake, c, p)
        assert light == dark == auto, p


def test_a_deep_church_colour_is_lifted_for_the_dark_page(church, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    _look(fake, "dark", "black")
    assert "--lm-dk" not in c.get("/my").text and "body.lm.lm-dark{--acc-fill" not in c.get("/my").text
    fake.biz[tct.BIZ]["settings"]["brand_kit"] = {"accent": "#1B2A57"}           # a deep navy
    html = c.get("/my").text
    m = re.search(r"body\.lm\.lm-dark\{--acc-fill:(#[0-9a-f]{6});--mb-fill:#[0-9a-f]{6};--on-acc:(#[0-9A-Fa-f]{6});", html)
    assert m, "the lifted button colour"
    fill, on = m.group(1), m.group(2)
    assert ui.contrast(fill, "#0a0a0b") >= 2.2 and ui.contrast(on, fill) >= 4.5
    assert "@media (prefers-color-scheme:dark){body.lm.lm-auto{--acc-fill:" in html     # Same as my phone too
    _look(fake, "light", "black")
    assert "--acc-fill:" not in c.get("/my").text                    # Light never carries it
    assert "body.lm.lm-dark{--acc-fill" in c.get("/my/me").text     # Me does: its control turns the page


# ─── Me: the control, and saving it ──────────────────────────────────


def _me_app(fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.app.include_router(mll.router)
    return c


def test_me_has_the_look_with_her_look_checked(church, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    _look(fake, None, "black")
    html = c.get("/my/me").text
    box = html[html.index('<section class="lm-look"'):html.index("</section>", html.index('<section class="lm-look"'))]
    assert '<h2 class="lm-lookt" id="lm-look-h">Look</h2>' in box
    assert '<form class="lm-lookf" id="lm-lookf" method="post" action="/my/look"' in box
    assert re.findall(r'<input type="radio" name="look" value="(\w+)"( checked)?>', box) == [
        ("light", ""), ("dark", " checked"), ("auto", "")]                       # the church's black, until she picks
    assert [m for m in re.findall(r"<span>([^<]+)</span>", box)] == ["Light", "Dark", "Same as my phone"]
    assert 'role="radiogroup" aria-labelledby="lm-look-h"' in box and "<noscript>" in box
    assert mll.script() in html and "fetch(f.action" in mll.script()
    assert html.index('class="lm-megive"') < html.index('class="lm-look"') < html.index('class="lm-lst"')
    _look(fake, "auto", "black")
    assert '<input type="radio" name="look" value="auto" checked>' in c.get("/my/me").text


def test_saving_the_look_writes_only_her_own_record(church, fake, monkeypatch):  # noqa: F811
    c = _me_app(fake, monkeypatch)
    _look(fake, None, "black")
    for row in fake.t["contacts"]:
        if row["id"] == tct.BEN:
            row["metadata"] = {"keep": 1}
    fake.writes.clear()
    c.cookies.set(mll.NIGHT_COOKIE, "1")
    r = c.post("/my/look", data={"look": "light", "id": tct.BEN, "contact_id": tct.BEN},
               headers={"accept": "application/json"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    patches = fake.written("contacts")
    assert patches and all(w[0] == "patch" for w in patches)
    touched = {row["id"] for w in patches for row in w[2]}
    assert touched == {tct.ANA}                                                  # her own row only
    ana = next(r for r in fake.t["contacts"] if r["id"] == tct.ANA)
    assert ana["metadata"]["member_look"] == "light"
    assert next(r for r in fake.t["contacts"] if r["id"] == tct.BEN)["metadata"] == {"keep": 1}
    cookies = r.headers.get_list("set-cookie")
    look = next(x for x in cookies if x.startswith(mll.COOKIE + "="))
    assert re.match(rf"{mll.COOKIE}=light\.\d+\.{mll._whose({'id': tct.ANA})};", look)
    assert "Path=/my" in look and "HttpOnly" in look and tct.ANA not in look
    assert "SameSite=lax" in look and "Secure" in look
    assert any(x.startswith(mll.NIGHT_COOKIE + "=") and "Max-Age=0" in x for x in cookies)   # the moon follows again
    # the next page is in it at once, though the kept record would say otherwise
    assert "lm-dark" not in _body_class(c.get("/my").text).split()


def test_saving_without_script_comes_back_to_me(church, fake, monkeypatch):  # noqa: F811
    c = _me_app(fake, monkeypatch)
    _look(fake, None, "white")
    r = c.post("/my/look", data={"look": "dark"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/me#lm-look-h"
    assert "lm-dark" in _body_class(c.get("/my/me").text).split()


def test_a_bad_look_or_a_stranger_saves_nothing(church, fake, monkeypatch):  # noqa: F811
    c = _me_app(fake, monkeypatch)
    _look(fake, None, "black")
    fake.writes.clear()
    assert c.post("/my/look", data={"look": "purple"}, headers={"accept": "application/json"}).status_code == 400
    r = c.post("/my/look", data={"look": "dark"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert not fake.written("contacts") and mll.COOKIE not in r.headers.get("set-cookie", "")
    monkeypatch.setattr(mp, "_session_for", lambda request, church: None)
    r = c.post("/my/look", data={"look": "dark"}, headers={"accept": "application/json"})
    assert r.status_code == 401 and not fake.written("contacts")


def test_a_failed_save_turns_nothing(church, fake, monkeypatch):  # noqa: F811
    c = _me_app(fake, monkeypatch)
    _look(fake, None, "black")
    fake.down.add("contacts")
    r = c.post("/my/look", data={"look": "light"}, headers={"accept": "application/json"})
    assert r.status_code == 503 and r.json()["ok"] is False
    assert mll.COOKIE not in r.headers.get("set-cookie", "")


def test_save_keeps_the_rest_of_her_record_and_waits_for_an_office_edit(fake, monkeypatch):  # noqa: F811
    fake.person(tct.ANA, "Ana Rivera")
    row = next(r for r in fake.t["contacts"] if r["id"] == tct.ANA)
    row.update(metadata={"member_photo": {"path": "p"}}, updated_at="t1")
    calls = []
    import member_portal_church as mpc
    real = mpc.load_me

    def load(b, c):
        calls.append(1)
        got = real(b, c)
        if len(calls) == 1:          # the office saves between this read and our write
            row["updated_at"] = "t2"
        return got
    monkeypatch.setattr(mpc, "load_me", load)
    assert mll.save(tct.BIZ, tct.ANA, "dark") is True and len(calls) == 2
    assert row["metadata"] == {"member_photo": {"path": "p"}, "member_look": "dark"}
    assert mll.save(tct.BIZ, tct.ANA, "neon") is False


def test_the_owners_preview_keeps_it_on_their_own_browser(church, fake, monkeypatch):  # noqa: F811
    c = _me_app(fake, monkeypatch)
    _look(fake, None, "black")
    ana = next(dict(r) for r in fake.t["contacts"] if r["id"] == tct.ANA)
    monkeypatch.setattr(mp, "_session_for",
                        lambda request, church: {"claims": {"cid": tct.ANA}, "people": [ana], "me": ana, "preview": True})
    fake.writes.clear()
    r = c.post("/my/look", data={"look": "light"}, headers={"accept": "application/json"})
    assert r.json() == {"ok": True} and not fake.written("contacts")          # never writes as the member
    assert any(x.startswith(mll.COOKIE + "=light.") for x in r.headers.get_list("set-cookie"))
    assert "lm-dark" not in _body_class(c.get("/my").text).split()


# ─── the reader's moon on top of the look ────────────────────────────


def test_dark_starts_the_reader_at_night_and_the_moon_can_say_day(church, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    _look(fake, "dark", "black")
    night = c.get("/my/bible/john/1").text
    assert "lm-dark" in _body_class(night).split()
    assert _metas(night) == [f'<meta name="theme-color" content="{mlb.NIGHT_BG}">']   # the reader's warm night
    assert 'id="lm-moon" aria-pressed="true"' in night and 'data-look="dark"' in night
    c.cookies.set(mll.NIGHT_COOKIE, "0")
    day = c.get("/my/bible/john/1").text
    assert "lm-dark" not in _body_class(day).split() and 'aria-pressed="false"' in day
    assert _metas(day) == ['<meta name="theme-color" content="#ffffff">']
    assert "lm-dark" in _body_class(c.get("/my/bible?tab=devotional").text).split()   # the moon is the reader's alone


def test_light_keeps_the_moon_as_it_was(church, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    _look(fake, "light", "black")
    day = c.get("/my/bible/john/1").text
    moon = re.search(r'<button[^>]*id="lm-moon"[^>]*>', day).group(0)
    assert "lm-dark" not in _body_class(day).split() and "data-look=" not in moon         # the moon as it was
    c.cookies.set(mll.NIGHT_COOKIE, "1")
    night = c.get("/my/bible/john/1").text
    assert "lm-dark" in _body_class(night).split() and 'aria-pressed="true"' in night
    assert _metas(night) == [f'<meta name="theme-color" content="{mlb.NIGHT_BG}">']


def test_same_as_my_phone_leaves_the_reader_to_the_phone(church, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    _look(fake, "auto", "black")
    html = c.get("/my/bible/john/1").text
    assert "lm-auto" in _body_class(html).split() and 'aria-pressed="false"' in html and 'data-look="auto"' in html
    assert _metas(html)[1] == f'<meta name="theme-color" content="{mlb.NIGHT_BG}" media="(prefers-color-scheme: dark)">'
    # the moon's script: back to following the look when it lands where the look would
    js = mlb._NIGHT
    assert "on===nLook()?'':(on?'1':'0')" in js and "B.classList.remove('lm-auto')" in js
    # one scope with the card's script (READER_MORE_JS): the moon's names are its own
    for name in ("nQ", "nPhone", "nLook", "nDark", "night", "moon"):
        assert not re.search(rf"(?:var |function |,){name}", mlb._CARD), name
    assert "prefers-color-scheme: dark" in js and "querySelectorAll('meta[name=\"theme-color\"]')" in js


def test_a_devotionals_day_follows_the_same_moon(church, fake, monkeypatch):  # noqa: F811
    import member_lumen_devotional as mld
    mll.CURRENT.set({"look": "dark", "night": ""})
    assert mll.reader_night() is True and mll.page_look(reader=True) == "dark"
    mll.CURRENT.set({"look": "dark", "night": "0"})
    assert mll.reader_night() is False and mll.page_look() == "dark"        # only the reader takes the moon
    mll.CURRENT.set({"look": "auto", "night": ""})
    assert mll.reader_night() is None
    mll.CURRENT.set({"look": "light", "night": "1"})
    assert mll.page_look(reader=True) == "dark" and mll.page_look(cine=True) == "dark"
    mll.CURRENT.set(None)
    assert mll.here() == "light"
    assert "lumen_reader=True" in pathlib.Path(mld.__file__).read_text(encoding="utf-8")


# ─── the sheet ───────────────────────────────────────────────────────


def _hex_of(tokens, name):
    return re.search(rf"--{name}:(#[0-9A-Fa-f]{{6}})", tokens).group(1)


def test_the_dark_layer_reads_well():
    import member_lumen_ui as lm
    t = lm.DARK_TOKENS
    bg, s1, s2 = _hex_of(t, "bg"), _hex_of(t, "s1"), _hex_of(t, "s2")
    for surface in (bg, s1, s2):
        assert ui.contrast(_hex_of(t, "fg"), surface) >= 7
        assert ui.contrast(_hex_of(t, "fg2"), surface) >= 4.5       # body text
        assert ui.contrast(_hex_of(t, "fg3"), surface) >= 3          # the quietest words
    assert bg.upper() == "#0A0A0B"                                   # near-black, not navy, not grey
    # the church's colour as words: its lit shade (4.5:1 on black), lightened like the reader's
    assert "--acc:var(--acc-lit)" in t and "--acc:color-mix(in oklab,var(--acc-lit) 62%,#fff)" in lm.DARK_MIX
    for brand in ("#D6246E", "#1B2A57", "#0A7566", "#F5C518", "#6B21A8", "#8B0000"):
        lit = ui.palette({"settings": {"brand_kit": {"accent": brand}}}, {}, lumen_dark=True)["lit"]
        assert ui.contrast(lit, "#000000") >= 4.5
    # the family inks their dark shades, the hairlines light
    assert "--gold-ink:var(--gold-lit)" in t and "--lm-line:rgba(255,255,255,.1)" in t


def test_the_reader_keeps_its_warm_night_and_the_type_block_stays_last():
    import member_lumen_fonts
    import member_lumen_ui as lm
    sheet = ui.sheet("lumen")[0]
    assert "body.lm.lm-dark:has(.lm-read),body.lm.lm-dark:has(.lm-dd){overscroll-behavior-y:none;--bg:#100E0B;" in sheet
    assert "body.lm.lm-auto:has(.lm-read),body.lm.lm-auto:has(.lm-dd){overscroll-behavior-y:none;--bg:#100E0B;" in sheet
    assert "body.lm.lm-dark{overscroll" not in sheet                 # the warm night isn't every dark page's
    assert "html:has(>body.lm.lm-dark){background:#0A0A0B;" in sheet
    twin = sheet[sheet.index("@media (prefers-color-scheme:dark){body.lm.lm-auto{--bg:#0A0A0B;"):]
    assert "html:has(>body.lm.lm-auto){background:#0A0A0B;" in twin[:twin.index("}}") + 400]
    assert lm.templates()[-1].template == member_lumen_fonts.template().template
    assert "body.lm.lm-dark:has(.lm-brief)" not in sheet              # Home's own dark is the look's now


def test_dark_twins_every_rule_for_same_as_my_phone():
    import member_lumen_ui as lm
    css = "body.lm.lm-dark .x{color:red;}html:has(>body.lm.lm-dark){background:#000;}"
    out = lm.dark(css)
    assert out.startswith(css)
    assert ("@media (prefers-color-scheme:dark){body.lm.lm-auto .x{color:red;}"
            "html:has(>body.lm.lm-auto){background:#000;}}") in out


def test_cookie_value_names_whose_it_is():
    v = mll.cookie_value("auto", {"id": tct.ANA}, 1_700_000_000)
    assert re.fullmatch(r"auto\.1700000000\.[0-9a-f]{12}", v) and tct.ANA not in v
    assert mll.from_cookie(v, {"id": tct.ANA}) == ("auto", 1_700_000_000.0)
    assert mll.from_cookie(v, {"id": tct.BEN}) == (None, 0.0) and mll.from_cookie(v, {}) == (None, 0.0)
    assert abs(float(mll.cookie_value("dark", {"id": "x"}).split(".")[1]) - time.time()) < 5


def test_a_record_with_no_updated_at_still_saves(fake, monkeypatch):  # noqa: F811
    import sb_clients
    fake.person(tct.ANA, "Ana Rivera")
    for row in fake.t["contacts"]:
        if row["id"] == tct.ANA:
            row.pop("updated_at", None)
    paths = []

    def patch(path, body, **kw):
        paths.append(path)
        return fake.patch(path, body, **kw)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    assert mll.save(tct.BIZ, tct.ANA, "auto") is True
    assert next(r for r in fake.t["contacts"] if r["id"] == tct.ANA)["metadata"]["member_look"] == "auto"
    # guarded by "still no updated_at", her own row only
    assert len(paths) == 1 and paths[0].endswith("&updated_at=is.null")
    assert f"id=eq.{tct.ANA}" in paths[0] and f"business_id=eq.{tct.BIZ}" in paths[0]


def test_a_busy_member_saves_nothing(church, fake, monkeypatch):  # noqa: F811
    c = _me_app(fake, monkeypatch)
    _look(fake, None, "black")
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: False)
    fake.writes.clear()
    r = c.post("/my/look", data={"look": "light"}, headers={"accept": "application/json"})
    assert r.status_code == 429 and not fake.written("contacts") and mll.COOKIE not in r.headers.get("set-cookie", "")


def test_give_draws_its_own_page_in_the_look_too(church, fake, monkeypatch):  # noqa: F811
    import giving_router
    biz = fake.biz[tct.BIZ]
    biz["stripe_account_id"] = "acct_test123"
    biz["settings"]["giving"] = {"enabled": True, "funds": ["Tithes", "Missions"]}
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: True)
    c = _client(fake, monkeypatch)
    _look(fake, "light", "black")
    light = c.get("/my/give").text
    assert "lm-dark" not in _body_class(light) and not _metas(light)          # as it was: no bar colour of its own
    _look(fake, "dark", "black")
    dark = c.get("/my/give").text
    assert "lm-dark" in _body_class(dark).split() and _metas(dark) == [f'<meta name="theme-color" content="{mll.DARK_BG}">']
    _look(fake, "auto", "black")
    auto = c.get("/my/give").text
    assert "lm-auto" in _body_class(auto).split() and len(_metas(auto)) == 2


def test_the_look_route_is_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    routes = [(getattr(r, "path", ""), getattr(r, "methods", set()) or set()) for r in app_mod.app.routes]
    paths = [p for p, _ in routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    assert next(i for i, (p, m) in enumerate(routes) if p == "/my/look" and "POST" in m) < catch

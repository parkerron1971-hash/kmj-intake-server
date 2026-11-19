# __tests__/test_member_lumen_fonts.py
#
# The new look's type (member_lumen_fonts, Lumen Next 2026-11-19): three
# pairings, A (Literata + Figtree) the default, picked per church in
# Settings → Member page. Pins:
#   - the pick: A unless the owner picked B or C; read from the church's row;
#   - the files: every face is here with its licence, served from our own
#     address as a hashed, immutable file any site may use, passed through on
#     a custom domain like the stylesheets;
#   - the sheet: every face and fallback, each pairing's variables, last in
#     the Lumen sheet; no Google Fonts anywhere in it;
#   - a Lumen page preloads its pairing's faces and drops the Google Fonts
#     link; its body carries the pairing's class; today's look is untouched;
#   - the owner's pick: owner-only, a, b or c, kept beside the other
#     member-page settings; the picker shows only where the new look can be
#     seen.

import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_app_ui as ui
import member_lumen_fonts as lmf
import member_portal as mp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import _body_class, _client, church  # noqa: F401  (the fixture)

BIZ = tct.BIZ


def _biz(fonts=None):
    cfg = {"enabled": True}
    if fonts is not None:
        cfg["fonts"] = fonts
    return {"id": BIZ, "settings": {"member_portal": cfg}}


def test_the_pick_is_a_unless_the_owner_picked_another():
    assert lmf.pick({}) == "a" and lmf.pick(None) == "a" and lmf.pick(_biz()) == "a"
    assert lmf.pick(_biz("b")) == "b" and lmf.pick(_biz("C")) == "c"
    for bad in ("d", "", 3, None, ["b"]):
        assert lmf.pick(_biz(bad)) == "a"
    assert lmf.pick({"settings": {"member_portal": "x"}}) == "a"
    assert lmf.body_class(_biz()) == [] and lmf.body_class(_biz("b")) == ["lm-fb"]
    assert lmf.body_class(_biz("c")) == ["lm-fc"]


def test_every_face_is_here_with_its_licence():
    names = set(lmf.files())
    assert len(names) == 2 * len(lmf.FACES) == 20
    for name, (data, digest) in lmf.files().items():
        assert data[:4] == b"wOF2", name
        assert re.fullmatch(r"[0-9a-f]{12}", digest)
    for p in lmf.PAIRS.values():
        for fam in (p["display"], p["ui"], p["read"], p["num"]):
            assert any(f[1] == fam for f in lmf.FACES), fam
        assert all(n in names for n in p["preload"])
    for slug in ("literata", "figtree", "fraunces", "onest", "mona-sans", "source-serif-4"):
        lic = (lmf.FONT_DIR / f"OFL-{slug}.txt").read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE" in lic.upper() and "Copyright" in lic, slug


def test_a_font_is_a_hashed_immutable_file_any_site_may_use():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(mp.router)
    c = TestClient(app, base_url=f"https://{tct.HOST}")
    path = lmf.url("literata-normal-latin")
    assert re.fullmatch(r"/my/fonts/literata-normal-latin\.[0-9a-f]{12}\.woff2", path)
    r = c.get(path)
    assert r.status_code == 200 and r.headers["content-type"] == "font/woff2"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.headers["access-control-allow-origin"] == "*" and r.content == lmf.files()["literata-normal-latin"][0]
    # Another hash (a page from the other side of a deploy): today's file, kept by nobody.
    r = c.get("/my/fonts/literata-normal-latin.000000000000.woff2")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    for bad in ("/my/fonts/nope-latin.000000000000.woff2", "/my/fonts/literata-normal-latin.woff2",
                "/my/fonts/..%2fmember_portal.py"):
        assert c.get(bad).status_code == 404, bad


def test_a_custom_domain_passes_the_font_through_like_the_sheets():
    import custom_domain_cache as cdc
    path = lmf.url("figtree-normal-latin")
    assert cdc.SHARED_FONT_RE.match(path) and lmf.FONT_PATH_RE.match(path)
    for p in ("/my/fonts/figtree-normal-latin.woff2", "/my/fonts/a.b.woff2", "/my/x.0123456789ab.woff2"):
        assert bool(cdc.SHARED_FONT_RE.match(p)) == bool(lmf.FONT_PATH_RE.match(p)), p
    forever = [(b"cache-control", b"public, max-age=31536000, immutable")]
    assert cdc._shared_sheet({"path": path}, forever)
    assert not cdc._shared_sheet({"path": path}, [(b"cache-control", b"no-store")])


def test_the_sheet_carries_every_face_and_each_pairing_last():
    css = lmf.css()
    for stem, fam, style, *_ in lmf.FACES:
        for sub in ("latin", "latin-ext"):
            assert lmf.url(f"{stem}-{sub}") in css
    for fam in lmf.FALLBACKS:
        assert f'font-family:"{fam} Fallback";src:local(' in css
    assert "body.lm{" in css and "body.lm.lm-fb{" in css and "body.lm.lm-fc{" in css
    assert '--mb-ui:"Figtree","Figtree Fallback"' in css and '--mb-serif:"Literata","Literata Fallback"' in css
    assert '--lm-read:"Source Serif 4"' in css and "--lm-nvn:lining-nums" in css
    sheet = ui.sheet("lumen")[0]
    assert sheet.rstrip().endswith(css.rstrip()), "the type comes last, so it sets every block's fonts"
    assert "fonts.googleapis" not in sheet and "fonts.gstatic" not in sheet
    assert "$" not in css


def test_a_lumen_page_preloads_its_pairing_and_drops_google(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    head = html[:html.index("</head>")]
    assert "fonts.googleapis.com" not in head
    for n in lmf.PAIRS["a"]["preload"]:
        assert f'<link rel="preload" href="{lmf.url(n)}" as="font" type="font/woff2" crossorigin>' in head
    assert not ({"lm-fb", "lm-fc"} & set(_body_class(html).split()))
    fake.biz[BIZ]["settings"]["member_portal"]["fonts"] = "c"
    html = _client(fake, monkeypatch).get("/my/bible").text
    head = html[:html.index("</head>")]
    assert lmf.url("mona-sans-normal-latin") in head and lmf.url("figtree-normal-latin") not in head
    assert "lm-fc" in _body_class(html).split()


def test_todays_look_keeps_its_fonts(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    fake.biz[BIZ]["settings"]["member_portal"]["fonts"] = "b"
    html = _client(fake, monkeypatch).get("/my").text
    assert ui.FONTS in html and "/my/fonts/" not in html
    assert not ({"lm-fb", "lm-fc"} & set(_body_class(html).split()))


def _settings(monkeypatch, owner="owner"):
    stored = {"settings": {"member_portal": {"enabled": True, "epoch": 7}, "giving": {"enabled": True}}}

    def _owner(b, u):
        if str(u.id) != owner:
            raise mp.HTTPException(403, "not authorized")
        return {"id": BIZ, "type": "church", "settings": dict(stored["settings"])}
    monkeypatch.setattr(mp, "_require_owner", _owner)
    import business_sites_helpers
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site",
                        lambda biz: ({"slug": "grace", "site_config": {}}, False))
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", lambda p: [{"settings": dict(stored["settings"])}])
    writes = []

    def _patch(path, body):
        writes.append(body)
        stored["settings"] = body["settings"]
        return [{"id": BIZ}]
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", _patch)
    return stored, writes


def test_the_owner_picks_the_pairing(monkeypatch):
    stored, writes = _settings(monkeypatch)
    user = SimpleNamespace(id="owner", email="pastor@example.test")
    for bad in ({"fonts": "d"}, {"fonts": None}, {"fonts": ""}, {"fonts": 2}):
        with pytest.raises(mp.HTTPException) as e:
            mp.patch_member_portal_config(BIZ, bad, user)
        assert e.value.status_code == 400
    assert not writes
    out = mp.patch_member_portal_config(BIZ, {"fonts": "B"}, user)
    assert out["fonts"] == "b" and stored["settings"]["member_portal"] == {"enabled": True, "epoch": 7, "fonts": "b"}
    assert stored["settings"]["giving"] == {"enabled": True}
    assert [c["key"] for c in out["font_choices"]] == ["a", "b", "c"] and out["fonts_default"] == "a"
    assert out["font_choices"][0]["label"] == "A · Literata + Figtree (recommended)"
    assert {f["family"] for f in out["font_faces"]} == {"Literata", "Figtree", "Fraunces", "Onest", "Mona Sans",
                                                         "Source Serif 4"}
    out = mp.patch_member_portal_config(BIZ, {"fonts": "a"}, user)
    assert out["fonts"] == "a" and stored["settings"]["member_portal"]["fonts"] == "a"


def test_only_the_owner_picks(monkeypatch):
    stored, writes = _settings(monkeypatch)
    with pytest.raises(mp.HTTPException) as e:
        mp.patch_member_portal_config(BIZ, {"fonts": "c"}, SimpleNamespace(id="someone-else", email=""))
    assert e.value.status_code == 403 and not writes and "fonts" not in stored["settings"]["member_portal"]


def test_the_picker_shows_only_where_the_new_look_can_be_seen(monkeypatch):
    import member_lumen
    owner = SimpleNamespace(id="o", email="Kevin@Example.test")
    other = SimpleNamespace(id="x", email="pastor@example.test")
    looked = []

    def _platform(bid):
        looked.append(bid)
        return bid == BIZ
    monkeypatch.setattr(member_lumen, "_platform_church", _platform)
    monkeypatch.setattr(member_lumen, "_platform_email", lambda: "kevin@example.test")
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert not lmf.picker_open({"id": BIZ}, owner)
    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    assert lmf.picker_open({"id": BIZ}, owner) and not lmf.picker_open({"id": "other"}, owner)
    looked.clear()
    assert not lmf.picker_open({"id": BIZ}, other) and not looked      # no read for anyone else
    monkeypatch.setenv("MEMBER_LUMEN", "owner")
    assert lmf.picker_open({"id": BIZ}, other) and not lmf.picker_open({"id": "other"}, other)
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    assert lmf.picker_open({"id": "other"}, other)

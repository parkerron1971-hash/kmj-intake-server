# __tests__/test_member_lumen.py
#
# The member app's new look ("Lumen") behind one switch (member_lumen.py):
# MEMBER_LUMEN = off | preview | owner | on, preview by default.
# Pins: off shows nobody; preview shows only the platform owner (their
# preview session or their own sign-in) at a church they own; owner shows
# every member at that church; on shows every church; an unknown value is
# off; an ordinary member under preview costs no read; serve() decides once
# per page and the page reads it through here().

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_asks
import member_lumen as ml

PLATFORM = "owner@platform.test"
HOME = "11111111-1111-1111-1111-111111111111"     # the platform owner's church
OTHER = "22222222-2222-2222-2222-222222222222"    # anyone else's church


@pytest.fixture
def owned(monkeypatch):
    """platform_church answers from a list, and counts its calls."""
    calls = []

    def fake(bid):
        calls.append(str(bid))
        return str(bid) == HOME
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", PLATFORM)
    monkeypatch.setattr(member_asks, "platform_church", fake)
    return calls


def _member(email="ana@example.test", em=None, preview=False):
    me = {"id": "c1", "name": "Ana Rivers", "email": email}
    sess = {"claims": {"em": em if em is not None else email, "cid": "c1"}, "people": [me], "me": me}
    if preview:
        sess["preview"] = True
    return sess


def _ctx(bid, sess):
    return {"business": {"id": bid, "name": "A church"}, "session": sess}


def test_default_is_preview(monkeypatch):
    monkeypatch.delenv("MEMBER_LUMEN", raising=False)
    assert ml.mode() == "preview"


@pytest.mark.parametrize("raw,want", [("off", "off"), ("PREVIEW", "preview"), (" owner ", "owner"),
                                      ("on", "on"), ("yes", "off"), ("", "preview")])
def test_mode_reads_the_env(monkeypatch, raw, want):
    monkeypatch.setenv("MEMBER_LUMEN", raw)
    assert ml.mode() == want


def test_off_shows_nobody(monkeypatch, owned):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert not ml.visible(None, _ctx(HOME, _member(PLATFORM)))
    assert not ml.visible(None, _ctx(HOME, _member(preview=True)))
    assert owned == []


def test_on_shows_every_church(monkeypatch, owned):
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    assert ml.visible(None, _ctx(OTHER, _member()))
    assert ml.visible(None, _ctx(OTHER, None))
    assert owned == []


def test_owner_shows_every_member_at_the_platform_church(monkeypatch, owned):
    monkeypatch.setenv("MEMBER_LUMEN", "owner")
    assert ml.visible(None, _ctx(HOME, _member()))
    assert not ml.visible(None, _ctx(OTHER, _member()))
    assert not ml.visible(None, _ctx(OTHER, _member(PLATFORM)))


def test_preview_shows_the_platform_owners_preview_at_their_church(monkeypatch, owned):
    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    assert ml.visible(None, _ctx(HOME, _member(preview=True)))
    # Another church's owner previewing their own app keeps today's look.
    assert not ml.visible(None, _ctx(OTHER, _member(preview=True)))


def test_preview_shows_the_platform_owners_own_sign_in(monkeypatch, owned):
    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    assert ml.visible(None, _ctx(HOME, _member(PLATFORM)))
    # Signed in by text: the record's email still says who it is.
    assert ml.visible(None, _ctx(HOME, _member(PLATFORM, em="+15550102030")))
    # Signed in with the address, the record's email blank.
    assert ml.visible(None, _ctx(HOME, _member("", em=PLATFORM.upper())))
    # Not at a church someone else owns.
    assert not ml.visible(None, _ctx(OTHER, _member(PLATFORM)))


def test_preview_hides_from_everyone_else(monkeypatch, owned):
    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    assert not ml.visible(None, _ctx(HOME, _member()))
    assert not ml.visible(None, _ctx(HOME, None))
    assert not ml.visible(None, _ctx(HOME, {"unavailable": True}))
    assert not ml.visible(None, _ctx(HOME, {"claims": {"em": PLATFORM}, "people": [], "me": None}))
    # An ordinary member is decided without asking who owns the church.
    assert owned == []


def test_no_church_is_a_no(monkeypatch, owned):
    for m in ("preview", "owner"):
        monkeypatch.setenv("MEMBER_LUMEN", m)
        assert not ml.visible(None, {"business": {}, "session": _member(preview=True)})
        assert not ml.visible(None, None)


def test_a_failed_owner_lookup_is_a_no(monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "owner")

    def boom(bid):
        raise RuntimeError("down")
    monkeypatch.setattr(member_asks, "platform_church", boom)
    assert not ml.visible(None, _ctx(HOME, _member()))


def test_decide_keeps_the_answer_for_the_page(monkeypatch, owned):
    monkeypatch.setenv("MEMBER_LUMEN", "preview")

    async def run(ctx):
        yes = await ml.decide(None, ctx)
        return yes, ml.here()
    assert asyncio.run(run(_ctx(HOME, _member(PLATFORM)))) == (True, True)
    assert asyncio.run(run(_ctx(HOME, _member()))) == (False, False)


def test_here_defaults_to_todays_look():
    import contextvars
    assert contextvars.Context().run(ml.here) is False


def test_platform_church_is_member_asks(monkeypatch):
    """The owner lookup is member_asks.platform_church (kept ten minutes)."""
    seen = []
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: seen.append(bid) or True)
    monkeypatch.setenv("MEMBER_LUMEN", "owner")
    assert ml.visible(None, _ctx(HOME, _member()))
    assert seen == [HOME]


# ── serve() decides once per page ──────────────────────────────────


def test_serve_decides_for_the_page(monkeypatch, owned):
    """A page drawn by serve() reads the answer through here()."""
    import member_portal as mp
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    biz = {"id": HOME, "name": "First Light Church", "type": "church",
           "settings": {"member_portal": {"enabled": True}}, "stripe_account_id": None}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": dict(biz), "site": {"slug": "fl"}})
    sess = _member(PLATFORM)
    monkeypatch.setattr(mp, "_session_for", lambda req, church: sess)
    seen = []

    async def page(request, church, s, sub):
        seen.append(ml.here())
        return mp._page("<p>ok</p>")
    monkeypatch.setattr(mp, "_serve_page", page)

    async def nothing(*a, **k):
        return None
    import member_spaces as msp
    import member_portal_threads as mpt
    monkeypatch.setattr(msp, "resolve_async", lambda *a, **k: asyncio.sleep(0, {"space": "church"}))
    monkeypatch.setattr(mpt, "counts", nothing)
    monkeypatch.setattr(mp, "_leads", nothing)
    import member_portal_board as mpb
    monkeypatch.setattr(mpb, "on_board", nothing)
    import church_follow_up as cfu
    monkeypatch.setattr(cfu, "is_church", lambda b: False)

    app = FastAPI()

    @app.get("/my")
    async def _my(request: mp.Request):
        return await mp.serve(request, "/my")
    c = TestClient(app, base_url="https://first-light.mysolutionist.app")

    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    assert c.get("/my").status_code == 200
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert c.get("/my").status_code == 200
    sess.update(_member())
    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    assert c.get("/my").status_code == 200
    assert seen == [True, False, False]

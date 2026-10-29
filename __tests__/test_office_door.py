"""A church's own office door (Kevin, 2026-10-28: "yes build the
church-branded office door").

An office login used to sign in on Solutionist's own page, the one that sells
a business owner a trial. A church's office now opens at its own door: its
address + /office, the app's /office/<slug> in its colours, and every invite
to its office."""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import business_users_router as bu  # noqa: E402
import office_door  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-step-up")
import ledger_unlock as lu  # noqa: E402

OWNER = type("U", (), {"id": "owner1", "email": "pastor@x.com"})()
SENT: list = []


def _stepup(user_id):
    return type("R", (), {"headers": {lu.UNLOCK_HEADER: lu.mint(str(user_id), lu.SCOPE_ACCESS)["token"]}})()


@pytest.fixture
def fb(monkeypatch):
    fb = FakeSB()
    import sb_clients
    import email_sender

    def get(path):
        # The fake doesn't embed: a site's business rides along as PostgREST would.
        rows = fb.get(path)
        if path.startswith("/business_sites") and "business:businesses" in path:
            for r in rows:
                b = next((x for x in fb.rows("businesses") if x["id"] == r.get("business_id")), None)
                r["business"] = dict(b) if b else None
        return rows

    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)

    async def send(**kw):
        SENT.append(kw)
    SENT.clear()
    monkeypatch.setattr(email_sender, "send_via_resend", send)
    for k in ("BILLING_ENFORCE", "CHURCH_AREAS"):
        monkeypatch.delenv(k, raising=False)
    fb.rows("businesses").extend([
        {"id": "church1", "owner_id": "owner1", "name": "Love City Church", "type": "ministry",
         "settings": {"brand_kit": {"colors": {"primary": "#B0146A"}, "logo_url": "https://cdn.example/lc.png"}}},
        {"id": "shop1", "owner_id": "owner1", "name": "Fade Lab", "type": "barber", "settings": {}},
        {"id": "church2", "owner_id": "owner1", "name": "Closed Church", "type": "ministry", "settings": {}},
    ])
    fb.rows("business_sites").extend([
        {"slug": "love-city", "business_id": "church1", "site_config": {}, "updated_at": "2026-10-01"},
        {"slug": "fade-lab", "business_id": "shop1", "site_config": {}, "updated_at": "2026-10-01"},
        {"slug": "closed", "business_id": "church2", "site_config": {"offline": True}, "updated_at": "2026-10-01"},
    ])
    return fb


def _invite(biz, email, **kw):
    out = asyncio.run(bu.invite(biz, bu.InviteBody(email=email, **kw), _stepup(OWNER.id), OWNER))
    row = next(r for r in FB["fb"].rows("business_users") if r["id"] == out["member"]["id"])
    row["token"] = "tok-" + row["id"]
    return out, row


FB: dict = {}


@pytest.fixture(autouse=True)
def _keep(fb):
    FB["fb"] = fb


def test_a_church_has_a_door_in_its_own_colours(fb):
    look = bu.office_door_look("love-city")
    assert look["ok"] is True
    door = look["door"]
    assert (door["name"], door["slug"], door["logo_url"]) == ("Love City Church", "love-city", "https://cdn.example/lc.png")
    # The member app's look: its base (black by default) and the church's colour.
    assert door["dark"] is True and door["bg"] == "#000000"
    assert door["fill"].lower() == "#b0146a"
    # Only a church's live site has one: a barber, a site taken offline, nonsense.
    for slug in ("fade-lab", "closed", "no-such", "../x", ""):
        assert bu.office_door_look(slug) == {"ok": False}


def test_a_church_invite_opens_at_its_door_and_comes_from_the_church(fb):
    out, row = _invite("church1", "dana@x.com", lane="people_care")
    from app_base import app_base_url
    assert out["accept_url"].startswith(f"{app_base_url()}/office/love-city?team_invite=")
    assert row["lane"] == "people_care"
    mail = SENT[-1]
    assert mail["from_name"] == "Love City Church"
    assert mail["subject"] == "Your Love City Church office login"
    assert "Solutionist" not in mail["body"] and "People & Care" in mail["body"]
    # Any other business keeps the plain sign-in and Solutionist's own email.
    out2, _ = _invite("shop1", "kim@x.com", role="member")
    assert out2["accept_url"].startswith(f"{app_base_url()}/?team_invite=")
    assert SENT[-1]["from_name"] == "Solutionist System"


def test_an_invite_link_brands_its_page_even_one_sent_before_the_door(fb):
    _, row = _invite("church1", "dana@x.com", lane="sunday_serving")
    v = bu.validate_invite(row["token"])
    assert v["door"]["slug"] == "love-city" and v["lane"] == "Sunday & Serving"
    _, row2 = _invite("shop1", "kim@x.com", role="member")
    assert bu.validate_invite(row2["token"])["door"] is None


def test_the_office_header_names_the_lane_even_the_treasurers(fb, monkeypatch):
    import church_areas
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {
        "areas": None if role == "admin" else ["people_care", "kids_youth", "groups_classes"], "by": "picked"})
    fb.rows("business_users").extend([
        {"id": "s1", "business_id": "church1", "user_id": "u-min", "role": "admin", "status": "active",
         "invited_email": "m@x.com", "lane": "treasurer"},
        {"id": "s2", "business_id": "church1", "user_id": "u-dana", "role": "manager", "status": "active",
         "invited_email": "d@x.com"},
        {"id": "s3", "business_id": "church1", "user_id": "u-adm", "role": "admin", "status": "active",
         "invited_email": "a@x.com"},
    ])
    role = lambda uid: bu.my_role("church1", type("U", (), {"id": uid, "email": None})())  # noqa: E731
    # Stored: an admin can only be the Treasurer by the lane it was given.
    assert role("u-min")["lane"] == "Treasurer"
    # Not stored: the lane its areas are exactly.
    assert role("u-dana")["lane"] == "People & Care"
    # An admin given no lane has none to show.
    assert role("u-adm")["lane"] is None
    # The owner's answer has no lane.
    assert "lane" not in role("owner1")


def test_the_churchs_address_slash_office_goes_to_its_door(fb):
    import member_portal
    import public_site
    app = FastAPI()
    app.include_router(public_site.router)
    from app_base import app_base_url
    r = TestClient(app, base_url="https://love-city.mysolutionist.app").get("/office", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{app_base_url()}/office/love-city"
    assert member_portal  # the church is found from the address, as the member app finds it

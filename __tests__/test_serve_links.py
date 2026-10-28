# __tests__/test_serve_links.py
#
# ChurchSavvy Planning by email (serve_links.py; canvas UZu4VsoY9KemkUGorz234j
# boards 12-15). Pins:
#   * a link is signed for one church and one person: an edited church, an
#     expired link or another purpose's signature opens nothing
#   * opening an ask changes nothing; Yes puts them on, Can't keeps why, and
#     "I can do …" offers only a Sunday they're actually free for
#   * a link only ever answers its own ask: another person's link, or a
#     "Stop these emails" link, can't answer it
#   * "Stop these emails" stops this church's serving emails for this one
#     person (the page, and the mail client's one-click), and the email
#     copy turned back on undoes it
#   * the office adds someone new by name and email, never twice for one
#     address; a reader can't
#   * "Email asks and reminders" is an admin's switch and keeps the church's
#     other settings

import pathlib
import sys
import types
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_sunday_planning import (ANA, BIZ, JO, KENDRA, NOW, OTHER, PRODUCTION, TY, api, ask, make_team, place,  # noqa: F401
                                  services, sundays, train)

import serve_links as sl
import sunday_serving as ss


@pytest.fixture
def linked(api, monkeypatch):
    """Production on four Sundays (10/25, 11/1, 11/8, 11/15): Sound (Kendra
    and Jo trained) and Slides (Ana). Kendra and Jo have email addresses.
    The links read the planning tests' clock (NOW, Wed 10/21), not today's:
    an ask's link lapses three days after its Sunday, so on the real clock
    these tests started failing on 10/28."""
    db, as_ = api
    monkeypatch.setattr(sl, "time", types.SimpleNamespace(time=lambda: NOW.timestamp()))
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.setenv("APP_BASE_URL", "https://system.mysolutionist.app")
    monkeypatch.delenv("CHURCHSAVVY_APP_URL", raising=False)
    for c in db.t["contacts"]:
        if c["id"] in (KENDRA, JO):
            c["email"] = c["name"].split(" ")[0].lower() + "@example.com"
    sundays(as_, 4)
    team = make_team(as_)
    sound, slides = place(team, "Sound"), place(team, "Slides")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained")])
    train(as_, slides, [(ANA, "trained")])
    s = [x["id"] for x in services(db)]
    app = FastAPI()
    app.include_router(sl.router)
    return db, as_, TestClient(app), s, sound


def token_for(db, cid, aid, svc_id):
    at = next(x for x in db.t["worship_services"] if x["id"] == svc_id)["starts_at"]
    from datetime import datetime
    return sl.answer_token(BIZ, cid, aid, datetime.fromisoformat(str(at).replace("Z", "+00:00")))


def row(db, aid):
    return next(r for r in db.t["serve_assignments"] if r["id"] == aid)


# ─── the link itself ─────────────────────────────────────────────────


def test_a_link_is_signed_for_one_church_and_one_person(linked, monkeypatch):
    db, *_ = linked
    t = sl.sign(BIZ, KENDRA, "a-1", int(sl.time.time()) + 600)
    claims = sl.verify(t)
    assert claims["biz"] == BIZ and claims["cid"] == KENDRA and claims["a"] == "a-1"
    # Name another church inside: its own signature fails.
    payload, sig = t.split(".")
    import base64
    import json
    raw = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    raw["biz"] = OTHER
    forged = base64.urlsafe_b64encode(json.dumps(raw, separators=(",", ":")).encode()).decode().rstrip("=")
    assert sl.verify(f"{forged}.{sig}") is None
    # Expired, garbage, and a link signed for another purpose open nothing.
    assert sl.verify(sl.sign(BIZ, KENDRA, "a-1", int(sl.time.time()) - 1)) is None
    assert sl.verify("not-a-link") is None and sl.verify("") is None
    import member_portal_preview as mpp
    other_purpose = mpp._sign("member-preview-link", BIZ, {"v": 1, "biz": BIZ, "cid": KENDRA, "exp": int(sl.time.time()) + 600})
    assert sl.verify(other_purpose) is None


def test_the_pages_links(linked):
    t = sl.sign(BIZ, KENDRA, "a-1", int(sl.time.time()) + 600)
    assert sl.page_url(t, ans="yes") == f"https://system.mysolutionist.app/churchsavvy/a/{t}?ans=yes"
    assert sl.page_url(t) == f"https://system.mysolutionist.app/churchsavvy/a/{t}"
    assert sl.one_click_url(t).startswith("https://mysolutionist.app/serve-link/stop?t=")


# ─── answering ───────────────────────────────────────────────────────


def test_opening_changes_nothing_and_yes_puts_them_on(linked):
    db, as_, link, s, sound = linked
    aid = ask(as_, s[0], sound, KENDRA).json()["assignment"]["id"]
    t = token_for(db, KENDRA, aid, s[0])
    v = link.get(f"/serve-link/view?t={t}")
    assert v.status_code == 200, v.text
    body = v.json()
    assert body["church"]["name"] == "Love City Church" and body["church"]["initials"] == "LC"
    assert body["first"] == "Kendra" and body["email_on"] is True
    assert body["ask"]["place"] == "Sound" and body["ask"]["status"] == "asked" and body["ask"]["short"] == "Oct 25"
    assert [f["short"] for f in body["ask"]["free"]] == ["Nov 1", "Nov 8"]
    assert body["ask"]["starts_at"].startswith("2026-10-25T") and body["ask"]["arrive_at"] <= body["ask"]["starts_at"]
    assert row(db, aid)["status"] == "asked", "opening a link never answers it"
    r = link.post("/serve-link/answer", json={"t": t, "ans": "yes"})
    assert r.status_code == 200, r.text
    assert row(db, aid)["status"] == "yes" and r.json()["ask"]["status"] == "yes"


def test_cant_keeps_why_and_offers_only_a_free_sunday(linked):
    db, as_, link, s, sound = linked
    aid = ask(as_, s[0], sound, KENDRA).json()["assignment"]["id"]
    ask(as_, s[1], sound, KENDRA)                         # already asked for Nov 1
    t = token_for(db, KENDRA, aid, s[0])
    free = link.get(f"/serve-link/view?t={t}").json()["ask"]["free"]
    assert [f["short"] for f in free] == ["Nov 8", "Nov 15"]
    taken = link.post("/serve-link/answer", json={"t": t, "ans": "other", "offer": s[1], "why": "Away"})
    assert taken.status_code == 409, "a Sunday they're already asked for isn't free"
    r = link.post("/serve-link/answer", json={"t": t, "ans": "other", "offer": free[1]["id"], "why": "Away"})
    assert r.status_code == 200, r.text
    assert row(db, aid)["status"] == "no" and row(db, aid)["note"] == "Can do Nov 15 · Away"
    # Just can't, with a reason said afterwards.
    b = ask(as_, s[2], sound, JO).json()["assignment"]["id"]
    tj = token_for(db, JO, b, s[2])
    assert link.post("/serve-link/answer", json={"t": tj, "ans": "no"}).status_code == 200
    assert link.post("/serve-link/why", json={"t": tj, "why": "Working"}).status_code == 200
    assert row(db, b)["status"] == "no" and row(db, b)["note"] == "Working"


def test_a_link_answers_only_its_own_ask(linked):
    db, as_, link, s, sound = linked
    aid = ask(as_, s[0], sound, KENDRA).json()["assignment"]["id"]
    # Jo's link, pointed at Kendra's ask.
    jo = token_for(db, JO, aid, s[0])
    assert link.post("/serve-link/answer", json={"t": jo, "ans": "yes"}).status_code == 404
    assert link.get(f"/serve-link/view?t={jo}").json().get("gone") is True
    # Kendra's "Stop these emails" link names no ask.
    stop = sl.stop_token(BIZ, KENDRA)
    assert link.post("/serve-link/answer", json={"t": stop, "ans": "yes"}).status_code == 404
    assert link.post("/serve-link/answer", json={"t": "garbage", "ans": "yes"}).status_code == 410
    assert row(db, aid)["status"] == "asked"


def test_an_answer_link_lapses_after_its_sunday(linked, monkeypatch):
    db, as_, link, s, sound = linked
    aid = ask(as_, s[0], sound, KENDRA).json()["assignment"]["id"]
    t = token_for(db, KENDRA, aid, s[0])
    later = sl.verify(t)["exp"] + 1
    monkeypatch.setattr(sl.time, "time", lambda: later)
    assert link.get(f"/serve-link/view?t={t}").status_code == 410


# ─── stop these emails ───────────────────────────────────────────────


def test_stop_these_emails_is_this_church_and_this_person(linked):
    db, as_, link, s, sound = linked
    stop = sl.stop_token(BIZ, KENDRA)
    # The page names the church first; reading it changes nothing.
    w = link.get(f"/serve-link/who?t={stop}").json()
    assert w == {"church": w["church"], "first": "Kendra", "email_on": True}
    assert w["church"]["name"] == "Love City Church" and ss.emails_on(BIZ, KENDRA) is True
    assert link.get("/serve-link/who?t=garbage").status_code == 410
    r = link.post("/serve-link/email", json={"t": stop, "on": False})
    assert r.status_code == 200 and r.json()["email_on"] is False
    assert ss.emails_on(BIZ, KENDRA) is False and ss.emails_on(BIZ, JO) is True
    pref = next(p for p in db.t["serve_prefs"] if p["contact_id"] == KENDRA)
    assert pref["email"] is False and pref["email_stopped_at"]
    # Start them again from the same page.
    assert link.post("/serve-link/email", json={"t": stop, "on": True}).json()["email_on"] is True
    assert ss.emails_on(BIZ, KENDRA) is True
    # The mail client's one-click unsubscribe does the same, for Jo alone.
    one = link.post(f"/serve-link/stop?t={sl.stop_token(BIZ, JO)}", data={"List-Unsubscribe": "One-Click"})
    assert one.status_code == 200 and "Love City Church" in one.text
    assert ss.emails_on(BIZ, JO) is False and ss.emails_on(BIZ, KENDRA) is True
    assert link.post("/serve-link/stop?t=garbage").status_code == 410
    # The email copy turned back on in the app undoes it too.
    ss.set_hearing({"id": BIZ}, JO, "email", True)
    assert ss.emails_on(BIZ, JO) is True


# ─── the office: someone new, and the switch ─────────────────────────


def test_add_someone_new_by_name_and_email(linked):
    db, as_, *_ = linked
    r = as_("planner").post("/planning/people", json={"business_id": BIZ, "name": "Grace Lee", "email": "Grace.Lee@Example.com"})
    assert r.status_code == 200, r.text
    made = r.json()["person"]
    assert r.json()["existing"] is False and made["has_email"] is True
    row_ = next(c for c in db.t["contacts"] if c["id"] == made["contact_id"])
    assert row_["email"] == "grace.lee@example.com" and row_["business_id"] == BIZ
    again = as_("owner").post("/planning/people", json={"business_id": BIZ, "name": "Gracie", "email": "grace.lee@example.com"})
    assert again.json()["existing"] is True and again.json()["person"]["contact_id"] == made["contact_id"]
    assert again.json()["person"]["name"] == "Grace Lee"
    assert sum(1 for c in db.t["contacts"] if (c.get("email") or "") == "grace.lee@example.com") == 1
    assert as_("owner").post("/planning/people", json={"business_id": BIZ, "name": "X", "email": "nope"}).status_code == 400
    assert as_("booth").post("/planning/people", json={"business_id": BIZ, "name": "X", "email": "x@example.com"}).status_code == 403
    # The team shows who an email can reach, never the address.
    teams = as_("owner").get(f"/planning/teams?business_id={BIZ}").json()["teams"]
    sound = next(p for p in teams[0]["places"] if p["name"] == "Sound")
    kendra = next(p for p in sound["people"] if p["contact_id"] == KENDRA)
    assert kendra["has_email"] is True and "email" not in kendra


def test_email_asks_is_an_admins_switch(linked):
    db, as_, *_ = linked
    assert as_("planner").put("/planning/email", json={"business_id": BIZ, "on": True}).status_code == 403
    r = as_("owner").put("/planning/email", json={"business_id": BIZ, "on": True})
    assert r.status_code == 200 and r.json() == {"email_asks": True}
    settings = db.t["businesses"][0]["settings"]
    assert settings["churchsavvy"]["planning_email"] is True
    assert settings["practitioner_name"] == "Pastor Kevin", "the church's other settings stay"
    st = as_("owner").get(f"/planning/status?business_id={BIZ}").json()
    assert st["email_asks"] is True and st["can_setup"] is True and st["member_app"] is False
    assert as_("planner").get(f"/planning/status?business_id={BIZ}").json()["can_setup"] is False
    as_("owner").put("/planning/email", json={"business_id": BIZ, "on": False})
    assert db.t["businesses"][0]["settings"]["churchsavvy"]["planning_email"] is False

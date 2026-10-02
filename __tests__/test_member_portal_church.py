# __tests__/test_member_portal_church.py
#
# The member page, part 2 (member_portal_church.py). Pins:
#   1. RSVP as the signed-in person: one answer per person per occasion
#      (a new answer replaces the old), capacity and the occasion's own
#      roles honoured, a past or foreign occasion refused, and a
#      concurrent change re-read rather than overwritten
#   2. a prayer request goes to the private care table, linked to the
#      member, marked as from the member page
#   3. details: phone validated; the address lands in metadata without
#      dropping other keys; the write is guarded by updated_at
#   4. routes: no session → back to sign-in; cross-site refused; the
#      redirect carries a code, never a name or an address

import pathlib
import sys
import urllib.parse
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal as mp
import member_portal_church as mpc

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
MOD = "33333333-3333-3333-3333-333333333333"
HOST = "first-light.mysolutionist.app"
ME = {"id": "c1", "name": "Ana Rivers", "email": "ana@example.com", "phone": ""}
SOON = (date.today() + timedelta(days=5)).isoformat()


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")


def _q(path, name):
    return urllib.parse.parse_qs(path.split("?", 1)[1]).get(name, [""])[0]


class Fake:
    def __init__(self):
        self.module = {"id": MOD, "name": "Services", "archetype_params": {
            "roles": [{"id": "greeter", "label": "Greeter", "needed": 1}]}}
        self.entries = {"e1": {"id": "e1", "module_id": MOD, "business_id": BIZ, "updated_at": "r1",
                               "data": {"title": "Sunday", "date": SOON, "capacity": 3, "signups": [
                                   {"name": "Ben", "status": "yes", "contact_id": "c2"}]}}}
        self.contact = {"id": "c1", "business_id": BIZ, "name": "Ana Rivers", "email": "ana@example.com",
                        "phone": "", "metadata": {"source_note": "keep me"}, "updated_at": "u1"}
        self.care = []
        self.conflicts = 0
        self.patches = []

    def get(self, path):
        biz = _q(path, "business_id").removeprefix("eq.")
        if path.startswith("/custom_modules"):
            return [dict(self.module)] if biz == BIZ else []
        if path.startswith("/module_entries"):
            if path.split("?", 1)[1].startswith("id=eq."):
                eid = _q(path, "id").removeprefix("eq.")
                e = self.entries.get(eid)
                return [dict(e, data=dict(e["data"]))] if e and e["business_id"] == biz else []
            return [dict(e, data=dict(e["data"])) for e in self.entries.values() if e["business_id"] == biz]
        if path.startswith("/contacts"):
            if path.split("?", 1)[1].startswith("id=eq."):
                c = self.contact
                return [dict(c, metadata=dict(c["metadata"]))] if biz == BIZ else []
            em = _q(path, "email").removeprefix("ilike.").replace("\\", "")
            return [dict(self.contact)] if em == self.contact["email"] and biz == BIZ else []
        return []

    def patch(self, path, body):
        self.patches.append((path, body))
        if self.conflicts:
            self.conflicts -= 1
            return []
        rev = _q(path, "updated_at").removeprefix("eq.")
        if path.startswith("/module_entries"):
            e = self.entries[_q(path, "id").removeprefix("eq.")]
            if rev != e["updated_at"]:
                return []
            e["data"] = body["data"]; e["updated_at"] = rev + "x"
            return [e]
        if path.startswith("/contacts"):
            if rev != self.contact["updated_at"]:
                return []
            self.contact.update(body); self.contact["updated_at"] = rev + "x"
            return [self.contact]
        return []

    def post(self, path, body, prefer=None):
        if path.startswith("/ministry_care_requests"):
            self.care.append(body)
            return [body]
        return None


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(mpc.sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(mpc.sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(mpc.sb_clients, "sb_post_as_service", f.post)
    import events_rsvp_router
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for",
                        lambda b: [dict(f.module)] if b == BIZ else [])
    return f


# ─── 1. RSVP ──────────────────────────────────────────────────────────


def _mine(fake):
    return [s for s in fake.entries["e1"]["data"]["signups"] if s.get("contact_id") == "c1"]


def test_coming_then_cant_replaces_rather_than_duplicates(fake):
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (True, "coming")
    assert _mine(fake) == [{"name": "Ana Rivers", "status": "yes", "contact_id": "c1"}]
    assert mpc.member_rsvp(BIZ, ME, "e1", "cant") == (True, "cant")
    assert _mine(fake) == [{"name": "Ana Rivers", "status": "no", "contact_id": "c1"}]
    # Someone else's signup is untouched.
    assert {"name": "Ben", "status": "yes", "contact_id": "c2"} in fake.entries["e1"]["data"]["signups"]


def test_capacity_counts_others_not_me(fake):
    fake.entries["e1"]["data"]["capacity"] = 2
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (True, "coming")
    # Full now — but my own answer can still change.
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (True, "coming")
    other = dict(ME, id="c9", name="Cy")
    assert mpc.member_rsvp(BIZ, other, "e1", "coming") == (False, "full")


def test_serving_follows_the_occasions_own_roles(fake):
    assert mpc.member_rsvp(BIZ, ME, "e1", "serve", "greeter") == (True, "serving")
    assert _mine(fake)[0]["role"] == "greeter"
    other = dict(ME, id="c9")
    assert mpc.member_rsvp(BIZ, other, "e1", "serve", "greeter") == (False, "role")   # filled
    fake.entries["e1"]["data"]["_roles"] = [{"id": "ushers", "label": "Ushers", "needed": 2}]
    assert mpc.member_rsvp(BIZ, other, "e1", "serve", "greeter") == (False, "role")   # not on this one
    assert mpc.member_rsvp(BIZ, other, "e1", "serve", "ushers") == (True, "serving")


def test_past_foreign_and_unknown_occasions_are_refused(fake):
    fake.entries["e1"]["data"]["date"] = (date.today() - timedelta(days=1)).isoformat()
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (False, "past")
    assert mpc.member_rsvp(OTHER, ME, "e1", "coming") == (False, "gone")
    assert mpc.member_rsvp(BIZ, ME, "nope", "coming") == (False, "gone")
    assert mpc.member_rsvp(BIZ, ME, "e1", "delete") == (False, "error")


def test_concurrent_change_is_reread_not_overwritten(fake):
    fake.conflicts = 1
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (True, "coming")
    assert len(fake.patches) == 2 and "updated_at=eq.r1" in fake.patches[0][0]


def test_upcoming_marks_my_answer(fake):
    mpc.member_rsvp(BIZ, ME, "e1", "serve", "greeter")
    (o,) = mpc.upcoming_for(BIZ, ME)
    assert o["mine"] == {"status": "yes", "role": "greeter"}
    html = mpc.occasion_card(o, "/my")
    assert "You're serving" in html and "Greeter" in html


def test_failed_read_is_not_nothing(monkeypatch):
    monkeypatch.setattr(mpc.sb_clients, "sb_get_as_service", lambda p: None)
    assert mpc.upcoming_for(BIZ, ME) is None
    assert "couldn't load" in mpc.coming_up(None)


# ─── 2. prayer ────────────────────────────────────────────────────────


def test_prayer_goes_to_private_care_linked_to_the_member(fake):
    assert mpc.save_prayer(BIZ, ME, "  Please pray for my mother.  ", True)
    (row,) = fake.care
    assert row["business_id"] == BIZ and row["contact_id"] == "c1" and row["status"] == "new"
    sub = row["submission"]
    assert sub["prayer_request"] == "Please pray for my mother."
    assert sub["confidential"] == "yes" and sub["source"] == "Member page" and sub["name"] == "Ana Rivers"


# ─── 3. details ──────────────────────────────────────────────────────


def test_details_validate_and_keep_other_metadata(fake):
    assert mpc.clean_details({"phone": "call me"}) == (None, "phone")
    cleaned, err = mpc.clean_details({"phone": "(555) 123-4567", "line1": "1 Main St", "city": "Dayton",
                                      "state": "OH", "postal": "45402"})
    assert not err
    assert mpc.update_details(BIZ, "c1", cleaned)
    c = fake.contact
    assert c["phone"] == "(555) 123-4567"
    assert c["metadata"]["mailing_address"]["city"] == "Dayton"
    assert c["metadata"]["source_note"] == "keep me"
    assert "updated_at=eq.u1" in fake.patches[-1][0]


# ─── 4. routes ───────────────────────────────────────────────────────


def _client(fake, monkeypatch, signed_in=True):
    biz = {"id": BIZ, "name": "First Light", "type": "church",
           "settings": {"member_portal": {"enabled": True}}}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": biz, "site": {}})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", fake.get)
    app = FastAPI()
    app.include_router(mpc.router)
    c = TestClient(app, base_url=f"https://{HOST}")
    if signed_in:
        c.cookies.set(mp.SESSION_COOKIE, mp.mint_session(BIZ, "ana@example.com", "c1"))
    return c


ORIGIN = {"origin": f"https://{HOST}"}


def test_rsvp_route_redirects_with_a_code_only(fake, monkeypatch):
    c = _client(fake, monkeypatch)
    r = c.post("/my/rsvp", data={"entry_id": "e1", "action": "coming", "back": "/my/events"},
               headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/events?done=coming"
    assert _mine(fake)
    # An open redirect is not possible through `back`.
    r = c.post("/my/rsvp", data={"entry_id": "e1", "action": "cant", "back": "https://evil.example"},
               headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my?done=cant"


def test_routes_need_a_session_and_same_origin(fake, monkeypatch):
    c = _client(fake, monkeypatch, signed_in=False)
    r = c.post("/my/prayer", data={"request": "hi"}, headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my" and not fake.care
    c = _client(fake, monkeypatch)
    r = c.post("/my/prayer", data={"request": "hi"}, headers={"origin": "https://evil.example"},
               follow_redirects=False)
    assert r.status_code == 403 and not fake.care


def test_prayer_and_details_routes(fake, monkeypatch):
    c = _client(fake, monkeypatch)
    r = c.post("/my/prayer", data={"request": "Pray for rain"}, headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my?done=prayer" and fake.care[0]["contact_id"] == "c1"
    r = c.post("/my/details", data={"phone": "bad!"}, headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my/details?err=phone"
    r = c.post("/my/details", data={"phone": "555 123 4567", "city": "Dayton"}, headers=ORIGIN,
               follow_redirects=False)
    assert r.headers["location"] == "/my/details?done=details"
    assert "Dayton" not in r.headers["location"]


# ─── review fixes ────────────────────────────────────────────────────


def test_office_typed_name_is_hers_and_keeps_its_note(fake):
    fake.entries["e1"]["data"]["signups"].append({"name": "  ana  RIVERS ", "status": "maybe", "note": "needs a ride"})
    (o,) = mpc.upcoming_for(BIZ, ME)
    assert o["mine"]["status"] == "maybe"
    html = mpc.occasion_card(o, "/my")
    assert "You said maybe" in html and "I'm coming" in html
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (True, "coming")
    (mine,) = _mine(fake)
    assert mine == {"name": "Ana Rivers", "status": "yes", "note": "needs a ride", "contact_id": "c1"}
    assert len(fake.entries["e1"]["data"]["signups"]) == 2      # Ben + Ana, no duplicate


def test_full_occasion_offers_nothing_that_can_only_fail(fake):
    fake.entries["e1"]["data"]["capacity"] = 1                   # Ben fills it
    (o,) = mpc.upcoming_for(BIZ, ME)
    html = mpc.occasion_card(o, "/my")
    assert "I'm coming" not in html and "Serve</button>" not in html
    assert "make it" in html                                    # "Can't make it" is still offered


def test_cant_clears_the_public_pages_registration(fake):
    key = mpc._registration_key(BIZ, "e1", "ANA@example.com")
    fake.entries["e1"]["data"]["_registration_keys"] = {key: True, "other": True}
    assert mpc.member_rsvp(BIZ, ME, "e1", "cant") == (True, "cant")
    assert fake.entries["e1"]["data"]["_registration_keys"] == {"other": True}


def test_stored_phone_is_not_rejudged():
    assert mpc.clean_details({"phone": "(555) 123-4567 x2"}, "(555) 123-4567 x2")[1] == ""
    assert mpc.clean_details({"phone": "555 123 4567 ext 12"})[1] == ""
    assert mpc.clean_details({"phone": "call the office"}, "(555) 123-4567")[1] == "phone"


def test_cards_name_their_occasion_for_screen_readers(fake):
    (o,) = mpc.upcoming_for(BIZ, ME)
    html = mpc.occasion_card(o, "/my", level=3)
    assert '<h3 id="mp-occ-e1">' in html and 'aria-describedby="mp-occ-e1"' in html


def test_a_failed_read_says_try_again_not_sign_in(fake, monkeypatch):
    c = _client(fake, monkeypatch)
    monkeypatch.setattr(mp, "_session_for", lambda req, church: {"unavailable": True})
    r = c.post("/my/prayer", data={"request": "hi"}, headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my/prayer?err=error" and not fake.care
    r = c.post("/my/rsvp", data={"entry_id": "e1", "action": "coming", "back": "/my/events"},
               headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my/events?err=error"


# ─── visibility ──────────────────────────────────────────────────────


def test_private_is_never_on_a_members_page_even_on_its_roster(fake):
    fake.entries["e1"]["data"]["_visibility"] = "private"
    fake.entries["e1"]["data"]["signups"].append({"name": "Ana Rivers", "status": "yes"})
    assert mpc.upcoming_for(BIZ, ME) == []
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (False, "gone")


def test_invite_only_shows_to_the_invited_and_the_rostered(fake):
    fake.entries["e1"]["data"]["_visibility"] = "invite"
    assert mpc.upcoming_for(BIZ, ME) == []
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (False, "gone")
    fake.entries["e1"]["data"]["_invited"] = ["c1"]
    assert len(mpc.upcoming_for(BIZ, ME)) == 1
    assert mpc.member_rsvp(BIZ, ME, "e1", "coming") == (True, "coming")
    # Ben is on its roster, so he sees it without an invitation.
    ben = dict(ME, id="c2", name="Ben")
    assert len(mpc.upcoming_for(BIZ, ben)) == 1


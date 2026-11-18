"""The church's guest card (guest_card.py): which card a guest lands on when
they scan the bulletin's "New here?" code.

Kevin, 2026-11-17, "build that": a printed connect card and guest QR that
Tiara (People & Care, the first-time guests) makes herself. The cards print
in the app; the server keeps only her choice of card, in
settings.new_here.guest_form, and says which cards a guest can be sent to.

Who picks it: whoever holds church_duties first_guests (Tiara by default;
the owner and the admins always), never the Office's login or a member, and
a duty that can't be read is a 503, never a yes. A switched-off, private or
another church's card is refused. New here's own PUT keeps the choice.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

CHURCH = "7c0de000-0000-4000-8000-0000000000d1"
SHOP = "7c0de000-0000-4000-8000-0000000000d2"
OTHER = "7c0de000-0000-4000-8000-0000000000d3"
OWNER_ID, ADMIN_ID, NAIYA_ID, TIARA_ID, MEMBER_ID, STRANGER_ID = (
    f"0f0f0f0f-0000-4000-8000-00000000001{i}" for i in range(1, 7))
VISIT = "f1000000-0000-4000-8000-000000000001"     # "Plan your visit"
BAPTISM = "f1000000-0000-4000-8000-000000000002"
PRAYER = "f1000000-0000-4000-8000-000000000003"    # private
OFF = "f1000000-0000-4000-8000-000000000004"       # switched off
THEIRS = "f1000000-0000-4000-8000-000000000005"    # another church's
HELP = "f1000000-0000-4000-8000-000000000006"      # private by its setting


def _who(uid):
    from auth_supabase import AuthedUser
    return AuthedUser(id=uid, email=None, role="authenticated")


@pytest.fixture
def church(monkeypatch):
    """Love City's office (the owner, an admin, Naiya in Office & Leadership,
    Tiara in People & Care, a member login), its cards and its own number, in
    the role tests' in-memory PostgREST; settings writes through the merge
    model."""
    import church_duties
    import new_here
    import sb_clients
    from settings_merge_fake import install
    from test_church_roles import FakeDB

    def seats(biz):
        return [{"business_id": biz, "user_id": u, "role": r, "status": "active", "lane": ln,
                 "invited_email": f"{n}@lovecity.org"}
                for u, r, ln, n in ((ADMIN_ID, "admin", None, "admin"), (NAIYA_ID, "manager", "office_leadership", "naiya"),
                                    (TIARA_ID, "manager", "people_care", "tiara"), (MEMBER_ID, "member", None, "web"))]

    def form(fid, name, biz=CHURCH, active=True, settings=None, form_type="general"):
        return {"id": fid, "business_id": biz, "name": name, "is_active": active, "form_type": form_type,
                "settings": settings or {}, "created_at": "2026-10-01T00:00:00Z",
                "fields": [{"name": "name", "label": "Your name", "type": "text"},
                           {"name": "first", "label": "Is this your first time?", "type": "radio", "options": ["Yes", "No"]}]}

    fake = FakeDB(
        businesses=[{"id": CHURCH, "name": "Love City Church", "type": "ministry", "owner_id": OWNER_ID,
                     "settings": {"new_here": {"on": True, "word": "HELLO"}, "brand_kit": {"colors": {"primary": "#3b1f5c"}}}},
                    {"id": SHOP, "name": "Fade Shop", "type": "barber", "owner_id": OWNER_ID, "settings": {}},
                    {"id": OTHER, "name": "Another Church", "type": "ministry", "owner_id": STRANGER_ID, "settings": {}}],
        business_users=seats(CHURCH) + seats(SHOP), church_duty_holders=[],
        intake_forms=[form(VISIT, "Plan your visit", form_type="connect_card"), form(BAPTISM, "Baptism"),
                      form(PRAYER, "Prayer request"), form(OFF, "Youth trip", active=False),
                      form(THEIRS, "Their card", biz=OTHER), form(HELP, "Help", settings={"private_care": True})],
        sms_numbers=[{"business_id": CHURCH, "status": "active", "phone_number": "+12315550199"}],
        business_sites=[{"business_id": CHURCH, "slug": "lovecity", "site_config": {"custom_domain": "lovecity.church"}}],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(new_here, "switched_on", lambda bid: True)
    monkeypatch.delenv("CHURCH_AREAS", raising=False)
    church_duties._CACHE.clear()
    fake.merges = install(monkeypatch, lambda bid: next((b for b in fake.t["businesses"] if b["id"] == bid), None))
    return fake


def _client(uid):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import guest_card
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(guest_card.router)
    app.dependency_overrides[require_user] = lambda: _who(uid)
    return TestClient(app)


def _get(uid, biz=CHURCH):
    return _client(uid).get(f"/church/guest-card/{biz}")


def _put(uid, form_id, biz=CHURCH):
    return _client(uid).put(f"/church/guest-card/{biz}", json={"form_id": form_id})


# ─── what the print sheet reads ───────────────────────────────────────

def test_the_sheet_reads_the_cards_a_guest_can_be_sent_to(church):
    r = _get(TIARA_ID)
    assert r.status_code == 200
    got = r.json()
    assert [f["name"] for f in got["forms"]] == ["Plan your visit", "Baptism"]
    visit = got["forms"][0]
    assert visit["url"] == f"https://lovecity.church/public/widget/form/{VISIT}" and visit["connect"] is True
    assert visit["questions"][1] == {"label": "Is this your first time?", "type": "radio", "options": ["Yes", "No"]}
    assert got["chosen"] is None and got["chosen_gone"] is False and got["can_choose"] is True
    assert got["text"] == {"word": "HELLO", "number": "+12315550199", "number_pretty": "(231) 555-0199",
                           "sms_link": "sms:+12315550199?&body=HELLO"}


def test_no_own_address_opens_on_the_api_host(church):
    church.t["business_sites"] = []
    from chief_host import FALLBACK_BASE
    assert _get(TIARA_ID).json()["forms"][0]["url"] == f"{FALLBACK_BASE.rstrip('/')}/public/widget/form/{VISIT}"


def test_the_text_is_offered_only_when_new_here_is_on_with_its_own_number(church, monkeypatch):
    import new_here
    church.t["businesses"][0]["settings"]["new_here"]["on"] = False
    assert _get(TIARA_ID).json()["text"] is None
    church.t["businesses"][0]["settings"]["new_here"]["on"] = True
    church.t["sms_numbers"] = []
    assert _get(TIARA_ID).json()["text"] is None
    church.t["sms_numbers"] = [{"business_id": CHURCH, "status": "active", "phone_number": "+12315550199"}]
    monkeypatch.setattr(new_here, "switched_on", lambda bid: False)
    assert _get(TIARA_ID).json()["text"] is None


def test_every_login_of_the_church_reads_it_and_only_the_guests_login_may_choose(church):
    can = {uid: _get(uid).json()["can_choose"] for uid in (OWNER_ID, ADMIN_ID, NAIYA_ID, TIARA_ID, MEMBER_ID)}
    assert can == {OWNER_ID: True, ADMIN_ID: True, NAIYA_ID: False, TIARA_ID: True, MEMBER_ID: False}
    assert _get(STRANGER_ID).status_code == 404
    assert _get(OWNER_ID, SHOP).status_code == 404            # not a church
    assert _client(OWNER_ID).get("/church/guest-card/not-a-uuid").status_code == 404


def test_a_cards_read_that_fails_is_a_503_never_no_cards(church, monkeypatch):
    import sb_clients
    real = church.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith("/intake_forms") else real(p, **k))
    assert _get(TIARA_ID).status_code == 503


# ─── who chooses, and what ────────────────────────────────────────────

def test_tiara_makes_plan_your_visit_the_guest_card(church):
    r = _put(TIARA_ID, VISIT)
    assert r.status_code == 200 and r.json()["chosen"] == VISIT
    assert church.merges == [{"id": CHURCH, "set": {"guest_form": VISIT}, "drop": [], "under": ["new_here"]}]
    nh = church.t["businesses"][0]["settings"]["new_here"]
    assert nh == {"on": True, "word": "HELLO", "guest_form": VISIT}        # New here itself untouched
    assert _get(NAIYA_ID).json()["chosen"] == VISIT                      # everyone reads it


def test_back_to_the_links_page_drops_only_the_choice(church):
    assert _put(TIARA_ID, VISIT).status_code == 200
    r = _put(TIARA_ID, None)
    assert r.status_code == 200 and r.json()["chosen"] is None
    assert church.merges[-1] == {"id": CHURCH, "set": {}, "drop": ["guest_form"], "under": ["new_here"]}
    assert church.t["businesses"][0]["settings"]["new_here"] == {"on": True, "word": "HELLO"}


def test_the_office_a_member_and_a_stranger_cannot_choose(church):
    import church_duties
    r = _put(NAIYA_ID, VISIT)
    assert r.status_code == 403 and r.json()["detail"] == church_duties.refusal(CHURCH, "first_guests")
    assert "People & Care" in r.json()["detail"]
    assert _put(MEMBER_ID, VISIT).status_code == 403
    assert _put(STRANGER_ID, VISIT).status_code == 404
    assert _put(OWNER_ID, VISIT, SHOP).status_code == 404
    assert church.merges == []
    assert _put(OWNER_ID, BAPTISM).status_code == 200 and _put(ADMIN_ID, VISIT).status_code == 200


def test_the_choice_follows_the_first_time_guests_when_they_move(church):
    import church_duties
    church.t["church_duty_holders"] = [{"business_id": CHURCH, "duty": "first_guests", "user_id": NAIYA_ID}]
    church_duties._CACHE.clear()
    assert _put(TIARA_ID, VISIT).status_code == 403
    assert _put(NAIYA_ID, VISIT).status_code == 200


def test_a_duty_that_cant_be_read_is_a_503_never_a_yes(church, monkeypatch):
    import sb_clients
    real = church.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith("/church_duty_holders") else real(p, **k))
    assert _put(TIARA_ID, VISIT).status_code == 503
    assert church.merges == []
    got = _get(TIARA_ID)
    assert got.status_code == 200 and got.json()["can_choose"] is False   # reads, no choosing
    assert _put(ADMIN_ID, VISIT).status_code == 200


@pytest.mark.parametrize("form_id, status", [
    (OFF, 400),          # switched off
    (PRAYER, 400),       # private by its name
    (HELP, 400),         # private by its setting
    (THEIRS, 404),       # another church's card
    ("not-a-uuid", 400),
])
def test_a_card_a_guest_cant_land_on_is_refused(church, form_id, status):
    r = _put(TIARA_ID, form_id)
    assert r.status_code == status, r.json()
    assert church.merges == []


def test_a_failed_write_is_a_503(church, monkeypatch):
    import business_settings
    monkeypatch.setattr(business_settings, "merge", lambda *a, **k: None)
    assert _put(TIARA_ID, VISIT).status_code == 503


def test_a_chosen_card_switched_off_later_is_gone_and_the_bulletin_falls_back(church):
    assert _put(TIARA_ID, VISIT).status_code == 200
    next(f for f in church.t["intake_forms"] if f["id"] == VISIT)["is_active"] = False
    got = _get(MEMBER_ID).json()
    assert got["chosen"] is None and got["chosen_gone"] is True


# ─── New here's own PUT keeps it ──────────────────────────────────────

def test_saving_new_here_keeps_the_guest_card(church, monkeypatch):
    import new_here
    import sb_clients
    church.t["businesses"][0]["settings"]["new_here"]["guest_form"] = VISIT
    written = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **k: written.append(body) or [body])
    monkeypatch.setattr(new_here, "own_number", lambda biz: "+12315550199")
    body = new_here.NewHereIn(on=True, word="HELLO", welcome="", thanks=new_here.StepIn(), monday=new_here.StepIn(),
                              invite=new_here.StepIn())
    new_here.put_new_here(CHURCH, body, user=_who(TIARA_ID))
    (row,) = written
    assert row["settings"]["new_here"]["guest_form"] == VISIT and row["settings"]["new_here"]["word"] == "HELLO"
    assert new_here.KEPT == ("guest_form",)


def test_the_choice_lives_inside_a_server_key():
    import business_settings
    import guest_card
    assert guest_card.UNDER == ["new_here"] and business_settings.server_owned("new_here")
    assert not business_settings.server_owned(guest_card.KEY)    # not a key of its own: inside new_here

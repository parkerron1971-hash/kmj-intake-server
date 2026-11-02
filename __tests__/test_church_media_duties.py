"""Media's job gates and ChurchSavvy's parts read church duties
(docs/CHURCH_DUTIES.md step 2b). Kevin, 2026-11-01: "church savvy should be
connected with shapretta mcclain right from the list since she over media".

Pins, for a church (the owner, an Admin, or a login that holds the duty):
  * posts: the marketing desk's writes (business_marketing), Chief's desk
    verbs and picture posts; offers stay the owner's
  * clips: posting a clip (clip_posting, Chief's post_clip) and covers
    (clip_finder, clip_covers: made as the owner's, on the church's credits)
  * website: the site builder (public_site) and the events page
    (events_rsvp_router); a site_config domain key stays the owner's and the
    admins'
  * a Manager whose duty was moved away is refused with church_duties.refusal
  * a business that isn't a church keeps its gate exactly
  * a duties read that fails is a 503, never a yes
  * ChurchSavvy parts by duty: churchsavvy_team admin; sunday_plan and
    production_schedule planner; serve_schedule scheduler (who serves when,
    never the plan); stream media and booth. A Manager with none reads only
    (Tiara, Naiya); volunteers are unchanged
  * the team list names each office login, with its lane and its parts
  * "clips are ready" reaches everyone who does the clips duty, once each

The tables are the duties tests' in-memory PostgREST (test_church_duties.DutyDB)."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_marketing as bm  # noqa: E402
import chief_clip_actions as cca  # noqa: E402
import chief_marketing_actions as cma  # noqa: E402
import chief_social_actions as csa  # noqa: E402
import church_areas as ca  # noqa: E402
import church_duties as cd  # noqa: E402
import clip_covers as cc  # noqa: E402
import clip_finder  # noqa: E402
import clip_posting  # noqa: E402
import events_rsvp_router as ev  # noqa: E402
import image_posting  # noqa: E402
import image_studio as images  # noqa: E402
import public_site as ps  # noqa: E402
import sb_clients  # noqa: E402
import worship_team as wt  # noqa: E402
from test_church_duties import (ADMIN, C_JESS, C_NAIYA, JESS, LAQ, MEM, NAIYA, SHAP, STRANGER, TIARA,  # noqa: E402
                                DutyDB, _seat)
from test_church_follow_up import BIZ, OTHER_BIZ, OWNER  # noqa: E402

OTHER_OWNER = "b1000000-0000-4000-8000-000000000001"
OTHER_MGR = "b2000000-0000-4000-8000-000000000002"   # a manager at a business that isn't a church
OTHER_ADM = "b3000000-0000-4000-8000-000000000003"
VOL = "b4000000-0000-4000-8000-000000000004"         # a ChurchSavvy volunteer: a team row, no seat
CLIP = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def db(monkeypatch):
    seats = [
        _seat(ADMIN, "admin", "minnie@lovecity.org", lane="treasurer", name="Minnie Tatum"),
        _seat(NAIYA, "manager", "naiya@lovecity.org", lane="office_leadership", contact_id=C_NAIYA),
        _seat(TIARA, "manager", "tiara@lovecity.org", areas=["kids_youth", "people_care", "groups_classes"],
              name="Tiara Adams"),
        _seat(LAQ, "manager", "laquesha@lovecity.org", lane="sunday_serving", name="Laquesha Bailey-Smith"),
        _seat(JESS, "manager", "jessica@lovecity.org"),
        _seat(SHAP, "manager", "shapretta@lovecity.org", lane="media_comms", name="Shapretta McClain"),
        _seat(MEM, "member", "web@lovecity.org"),
    ]
    other = [{**_seat(OTHER_MGR, "manager", "pat@fade.example"), "business_id": OTHER_BIZ},
             {**_seat(OTHER_ADM, "admin", "sam@fade.example"), "business_id": OTHER_BIZ}]
    fake = DutyDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Kevin"}},
                    {"id": OTHER_BIZ, "name": "Fade Street", "type": "barber", "owner_id": OTHER_OWNER,
                     "settings": {}}],
        business_users=seats + other,
        contacts=[{"id": C_NAIYA, "business_id": BIZ, "name": "Naiya  Clark", "email": "naiya@lovecity.org"},
                  {"id": C_JESS, "business_id": BIZ, "name": "Jessica McCloud", "email": "Jessica@LoveCity.org"}],
        church_role_defs=[{"business_id": BIZ, "key": "executive_pastor", "catalog_key": "executive_pastor",
                           "title": "Executive Pastor", "job": "pastoral", "status": "active"}],
        church_leader_roles=[{"business_id": BIZ, "contact_id": C_JESS, "role": "executive_pastor",
                              "status": "active"}],
        church_duty_holders=[], church_duty_changes=[],
        worship_team=[{"business_id": BIZ, "user_id": VOL, "name": "Vic", "roles": ["booth"], "status": "active"}],
        chief_notifications=[],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.delenv("CHURCH_AREAS", raising=False)
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    cd._CACHE.clear()
    cd._FAILED.clear()
    ca._MY_CACHE.clear()
    yield fake
    cd._CACHE.clear()
    cd._FAILED.clear()


def _u(uid):
    return SimpleNamespace(id=uid, email=None)


def _move(db, duty, *uids):
    for u in uids:
        db.t["church_duty_holders"].append({"business_id": BIZ, "duty": duty, "user_id": u})
    cd._CACHE.clear()


def _break_duties(db, monkeypatch):
    """The duties table can't be read: every Manager's answer is a 503."""
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("church_duty_holders") else real(path, **kw))
    cd._CACHE.clear()


def _status(fn, *args, **kw):
    with pytest.raises(HTTPException) as e:
        fn(*args, **kw)
    return e.value.status_code, e.value.detail


LANE_TEXT = " is the Media & Communications lane's job here. The owner or an admin can give it to you in Logins & areas."


# ─── posts ────────────────────────────────────────────────────────────

def test_the_desk_opens_to_the_owner_an_admin_and_the_logins_that_do_posts(db):
    for uid in (OWNER, ADMIN, SHAP, JESS):
        assert bm._poster_row(BIZ, uid)["id"] == BIZ, uid
    assert _status(bm._poster_row, BIZ, NAIYA) == (403, "“Posts”" + LANE_TEXT)
    assert _status(bm._poster_row, BIZ, TIARA) == (403, "“Posts”" + LANE_TEXT)
    # A Member and a stranger: the desk's own words, never whose job it is.
    for uid in (MEM, STRANGER):
        assert _status(bm._poster_row, BIZ, uid) == (403, bm.OWNER_ONLY), uid
    # What customers pay stays the owner's.
    assert _status(bm._owner_row, BIZ, SHAP) == (403, bm.OWNER_ONLY)


def test_a_manager_whose_posts_moved_away_hears_whose_job_it_is(db):
    _move(db, "posts", LAQ)
    assert _status(bm._poster_row, BIZ, SHAP) == (
        403, "“Posts” is Laquesha's job here. The owner or an admin can give it to you in Logins & areas.")
    assert bm._poster_row(BIZ, LAQ)["id"] == BIZ
    assert bm._poster_row(BIZ, ADMIN)["id"] == BIZ, "nothing takes a duty from an admin"


def test_the_desk_says_who_can_change_it(db):
    church = db.get(f"/businesses?id=eq.{BIZ}")[0]
    assert bm._may_post(BIZ, SHAP, church) and bm._may_post(BIZ, OWNER, church)
    assert not bm._may_post(BIZ, NAIYA, church) and not bm._may_post(BIZ, MEM, church)
    assert not bm._may_post(BIZ, None, church)


def test_chief_works_the_desk_and_posts_pictures_for_the_logins_that_do_posts(db):
    assert asyncio.run(cma._owner(BIZ, SHAP, "nothing was changed"))["id"] == BIZ
    with pytest.raises(cca.Refusal) as no:
        asyncio.run(cma._owner(BIZ, NAIYA, "nothing was changed"))
    assert no.value.result.startswith("“Posts”" + LANE_TEXT) and no.value.result.endswith("Nothing was changed.")
    with pytest.raises(cca.Refusal) as member:
        asyncio.run(cma._owner(BIZ, MEM, "nothing was changed"))
    assert member.value.label == "Only the owner can change the desk"
    assert image_posting._require_owner(BIZ, SHAP) is None
    with pytest.raises(cca.Refusal) as pic:
        asyncio.run(csa._require_owner(BIZ, NAIYA))
    assert pic.value.result == "“Posts”" + LANE_TEXT + " So nothing was posted."
    assert _status(image_posting._require_owner, BIZ, MEM) == (403, image_posting.OWNER_ONLY)


# ─── clips ────────────────────────────────────────────────────────────

def test_clips_post_for_the_owner_an_admin_and_the_logins_that_do_clips(db):
    for uid in (OWNER, ADMIN, SHAP, JESS):
        assert clip_posting._require_owner(BIZ, _u(uid)) is None, uid
    assert _status(clip_posting._require_owner, BIZ, _u(NAIYA)) == (403, "“Clips and covers”" + LANE_TEXT)
    assert _status(clip_posting._require_owner, BIZ, _u(MEM)) == (403, clip_posting.OWNER_ONLY)
    with pytest.raises(cca.Refusal) as chief:
        asyncio.run(cca._require_owner(BIZ, LAQ))
    assert chief.value.result == "“Clips and covers”" + LANE_TEXT + " So nothing was posted."
    _move(db, "clips", JESS)
    assert _status(clip_posting._require_owner, BIZ, _u(SHAP))[0] == 403
    assert clip_posting._require_owner(BIZ, _u(JESS)) is None


def test_covers_are_made_as_the_owners_for_a_login_that_does_clips(db):
    assert clip_finder.church_cover_owner(BIZ, SHAP) == OWNER
    assert clip_finder.church_cover_owner(BIZ, ADMIN) == OWNER
    assert clip_finder.church_cover_owner(BIZ, OWNER) is None, "the owner goes the way they always did"
    assert clip_finder.church_cover_owner(BIZ, MEM) is None
    assert clip_finder.church_cover_owner(BIZ, STRANGER) is None
    assert _status(clip_finder.church_cover_owner, BIZ, NAIYA) == (403, "“Clips and covers”" + LANE_TEXT)


def test_make_cover_binds_the_build_actor_to_the_owner_for_a_clips_login(db, monkeypatch):
    seen = []

    async def made(business_id, asset_id, body, sizes, user_id):
        seen.append((images.build_actor.get(), user_id))
        return {"ok": True}
    monkeypatch.setattr(cc, "_make_cover", made)
    body = cc.Cover(request_id=uuid4())
    for who in (SHAP, OWNER):
        asyncio.run(cc.make_cover(UUID(BIZ), UUID(CLIP), body, SimpleNamespace(user=_u(who))))
    assert seen == [({"business_id": BIZ, "user_id": OWNER}, OWNER), (None, OWNER)]
    assert images.build_actor.get() is None, "the actor never outlives the request"
    with pytest.raises(HTTPException) as no:
        asyncio.run(cc.make_cover(UUID(BIZ), UUID(CLIP), body, SimpleNamespace(user=_u(NAIYA))))
    assert no.value.status_code == 403 and len(seen) == 2


def test_the_cover_worker_makes_a_clips_logins_covers_as_the_owners(db, monkeypatch):
    seen = {}

    async def business(client, business_id):
        seen["actor"] = images.build_actor.get()
        return {"id": BIZ, "owner_id": OWNER}
    monkeypatch.setattr(images, "business", business)
    monkeypatch.setattr(cc, "run_clips", lambda run: [{"id": CLIP, "name": "Feelings Lie", "configuration": {}}])
    monkeypatch.setattr(cc, "shaped_covers", lambda biz, rows: {})
    monkeypatch.setattr(cc, "_tries", {})

    async def refs(client, biz, row, user_id):
        seen["refs_for"] = user_id
        return []

    async def design(client, biz, action, turn):
        return {}
    monkeypatch.setattr(cc, "subject_references", refs)
    monkeypatch.setattr(cc, "design", design)
    run = {"id": str(uuid4()), "business_id": BIZ, "created_by": SHAP, "options": {"covers": {"sizes": ["story"]}}}
    assert asyncio.run(cc.cover_run(None, run)) == (1, None)
    assert seen == {"actor": {"business_id": BIZ, "user_id": OWNER}, "refs_for": OWNER}
    # Someone whose job clips no longer are: paused, nothing designed.
    _move(db, "clips", JESS)
    with pytest.raises(HTTPException) as no:
        asyncio.run(cc.cover_run(None, {**run, "id": str(uuid4())}))
    assert no.value.status_code == 403


# ─── website ──────────────────────────────────────────────────────────

def test_the_site_builder_and_events_page_open_to_the_logins_that_do_the_website(db):
    assert ps._require_business_owner(BIZ, _u(OWNER)) == "owner"
    assert ps._require_business_owner(BIZ, _u(ADMIN)) == "admin"
    assert ps._require_business_owner(BIZ, _u(SHAP)) == "manager"
    assert _status(ps._require_business_owner, BIZ, _u(NAIYA)) == (403, "“The website”" + LANE_TEXT)
    assert _status(ps._require_business_owner, BIZ, _u(MEM)) == (403, "not authorized for this business")
    for uid in (OWNER, ADMIN, SHAP, JESS):
        assert ev._require_owner(BIZ, _u(uid))["id"] == BIZ, uid
    assert _status(ev._require_owner, BIZ, _u(LAQ)) == (403, "“The website”" + LANE_TEXT)
    assert _status(ev._require_owner, BIZ, _u(STRANGER)) == (403, "not authorized")


def test_the_admin_site_routes_open_to_a_website_manager_in_a_church(db):
    church = {**db.get(f"/businesses?id=eq.{BIZ}")[0]}
    assert ps._site_admin(BIZ, {**church, "_caller_role": "admin"}, ADMIN) is None
    assert ps._site_admin(BIZ, {**church, "_caller_role": "manager"}, SHAP) is None
    assert _status(ps._site_admin, BIZ, {**church, "_caller_role": "manager"}, TIARA)[0] == 403
    assert _status(ps._site_admin, BIZ, {**church, "_caller_role": "member"}, MEM) == (404, "business not found")


def test_the_domain_stays_with_the_owner_and_the_admins(db, monkeypatch):
    import smart_sites
    saved = []
    monkeypatch.setattr(smart_sites, "save_smart_config", lambda biz, body: saved.append(body) or {"ok": True})
    call = lambda who, body: asyncio.run(ps.save_smart_config_endpoint(BIZ, body, _u(who)))  # noqa: E731
    with pytest.raises(HTTPException) as no:
        call(SHAP, {"custom_domain": "lovecity.org"})
    assert no.value.status_code == 403 and no.value.detail == ps.DOMAIN_KEYS_REFUSED and saved == []
    assert call(SHAP, {"offline": False}) == {"ok": True}
    assert call(ADMIN, {"custom_domain": "lovecity.org"}) == {"ok": True}
    assert call(OWNER, {"custom_domain_status": "pending"}) == {"ok": True}
    assert saved == [{"offline": False}, {"custom_domain": "lovecity.org"}, {"custom_domain_status": "pending"}]


# ─── a business that isn't a church, and a failed read ───────────────

def test_a_business_that_isnt_a_church_keeps_every_gate_exactly(db):
    for uid in (OTHER_MGR, OTHER_ADM):
        assert _status(bm._poster_row, OTHER_BIZ, uid) == (403, bm.OWNER_ONLY)
        assert _status(image_posting._require_owner, OTHER_BIZ, uid) == (403, image_posting.OWNER_ONLY)
        assert _status(clip_posting._require_owner, OTHER_BIZ, _u(uid)) == (403, clip_posting.OWNER_ONLY)
        assert _status(ps._require_business_owner, OTHER_BIZ, _u(uid)) == (403, "not authorized for this business")
        assert _status(ev._require_owner, OTHER_BIZ, _u(uid)) == (403, "not authorized")
        assert clip_finder.church_cover_owner(OTHER_BIZ, uid) is None
    biz = db.get(f"/businesses?id=eq.{OTHER_BIZ}")[0]
    assert _status(ps._site_admin, OTHER_BIZ, {**biz, "_caller_role": "manager"}, OTHER_MGR) == (404, "business not found")
    assert ps._site_admin(OTHER_BIZ, {**biz, "_caller_role": "admin"}, OTHER_ADM) is None
    assert bm._poster_row(OTHER_BIZ, OTHER_OWNER)["id"] == OTHER_BIZ
    # A manager is every ChurchSavvy part outside a church, as before.
    assert wt.roles_of(OTHER_BIZ, _u(OTHER_MGR), part=None) == set(wt.ROLES)
    assert cd.holders_of(OTHER_BIZ, "clips") == []
    assert not cd._CACHE, "nothing about duties was read for it"


def test_a_failed_duties_read_is_a_503_never_a_yes(db, monkeypatch):
    _break_duties(db, monkeypatch)
    assert _status(bm._poster_row, BIZ, SHAP)[0] == 503
    assert _status(image_posting._require_owner, BIZ, SHAP)[0] == 503
    assert _status(clip_posting._require_owner, BIZ, _u(SHAP))[0] == 503
    assert _status(clip_finder.church_cover_owner, BIZ, SHAP)[0] == 503
    assert _status(ps._require_business_owner, BIZ, _u(SHAP))[0] == 503
    assert _status(ev._require_owner, BIZ, _u(SHAP))[0] == 503
    assert _status(wt.roles_of, BIZ, _u(SHAP), part=None)[0] == 503
    # The owner and an admin read no duties table.
    assert bm._poster_row(BIZ, OWNER)["id"] == BIZ and bm._poster_row(BIZ, ADMIN)["id"] == BIZ
    assert wt.roles_of(BIZ, _u(ADMIN), part=None) == set(wt.ROLES)


# ─── ChurchSavvy parts ────────────────────────────────────────────────

def test_each_churchsavvy_duty_gives_its_parts():
    assert wt.duty_parts(["churchsavvy_team"]) == {"admin"}
    assert wt.duty_parts(["sunday_plan"]) == {"planner"}
    assert wt.duty_parts(["serve_schedule"]) == {"scheduler"}
    assert wt.duty_parts(["stream"]) == {"media", "booth"}
    assert wt.duty_parts(["production_schedule"]) == {"planner"}
    assert wt.duty_parts(["posts", "clips", "website", "weekly_text", "care_visits", "kids", "sermons",
                          "announcements", "serve_teams", "background_checks"]) == set()
    assert set(wt.PARTS_FROM_DUTIES) <= set(cd.CATALOG)
    assert {p for ps_ in wt.PARTS_FROM_DUTIES.values() for p in ps_} <= set(wt.PARTS)


def test_each_office_login_gets_its_churchsavvy_parts_from_its_duties(db):
    parts = lambda uid: wt.roles_of(BIZ, _u(uid), part=None)  # noqa: E731
    assert parts(OWNER) == set(wt.ROLES) and parts(ADMIN) == set(wt.ROLES)
    # Shapretta (Media & Communications) is ChurchSavvy's admin (Kevin, 2026-11-02: "churchsavvy is
    # shapretta"). Laquesha (Sunday & Serving, the volunteers) schedules who serves when by
    # serve_schedule, and nothing else of ChurchSavvy's: never the order of service.
    assert parts(SHAP) == {"admin", "planner", "media", "booth"}
    assert parts(LAQ) == {"scheduler"}
    assert parts(JESS) == {"admin", "planner", "scheduler", "media", "booth"}, "the Executive Pastor covers every lane"
    assert all(wt.can(parts(SHAP), k) for k in wt.CAN)
    assert wt.can(parts(LAQ), "serve") and not wt.can(parts(LAQ), "setup") and not wt.can(parts(LAQ), "plan")
    # Tiara and Naiya read ChurchSavvy only: no plan, no schedule, no setup.
    for uid in (TIARA, NAIYA):
        assert parts(uid) == set(), uid
        assert not any(wt.can(parts(uid), k) for k in wt.CAN), uid
        assert _status(wt.require, BIZ, _u(uid), "plan") == (403, wt.REFUSED["plan"])
        assert _status(wt.require, BIZ, _u(uid), "serve") == (403, wt.REFUSED["serve"])
    # A Member seat and a volunteer are as before; a stranger isn't there.
    assert parts(MEM) == set() and parts(VOL) == {"booth"}
    assert _status(wt.roles_of, BIZ, _u(STRANGER), part=None) == (404, "business not found")


def test_a_moved_duty_moves_the_part(db):
    _move(db, "churchsavvy_team", LAQ)
    assert wt.roles_of(BIZ, _u(SHAP), part=None) == {"planner", "media", "booth"}
    assert wt.roles_of(BIZ, _u(LAQ), part=None) == {"admin", "scheduler"}
    assert _status(wt.require, BIZ, _u(SHAP), "setup") == (403, wt.REFUSED["setup"])
    _move(db, "stream", NAIYA)
    assert wt.roles_of(BIZ, _u(NAIYA), part=None) == {"media", "booth"}
    assert wt.roles_of(BIZ, _u(SHAP), part=None) == {"planner"}


def test_a_manager_keeps_the_parts_the_team_gave_it(db):
    db.t["worship_team"].append({"business_id": BIZ, "user_id": NAIYA, "name": "Naiya", "roles": ["worship"],
                                 "status": "active"})
    assert wt.roles_of(BIZ, _u(NAIYA), part=None) == {"worship"}


# ─── the team list ────────────────────────────────────────────────────

def test_the_team_list_names_each_office_login_with_its_lane_and_parts(db):
    staff = wt._staff(BIZ, _u(OWNER))
    got = [(s["name"], s["role"], s["lane"], s["parts"]) for s in staff]
    assert got == [
        ("Pastor Kevin", "owner", None, list(wt.ROLES)),
        ("Minnie Tatum", "admin", "Treasurer", list(wt.ROLES)),
        ("Naiya Clark", "manager", "Office & Leadership", []),
        ("Tiara Adams", "manager", "People & Care", []),
        ("Laquesha Bailey-Smith", "manager", "Sunday & Serving", ["scheduler"]),
        ("Jessica McCloud", "manager", "Executive Pastor", ["planner", "booth", "media", "admin", "scheduler"]),
        ("Shapretta McClain", "manager", "Media & Communications", ["planner", "booth", "media", "admin"]),
    ]
    assert "scheduler" in got[4][3], "Laquesha's list says she schedules"
    assert not any("@" in s["name"] for s in staff), "never a bare email"
    shap = next(s for s in staff if s["name"] == "Shapretta McClain")
    assert shap["kind"] == "seat" and shap["email"] == "shapretta@lovecity.org" and shap["lanes"] == ["media_comms"]
    assert staff[0]["you"] and not any(s["you"] for s in staff[1:])
    # The keys the app already reads are all still there.
    assert all({"name", "kind", "you"} <= set(s) for s in staff)


def test_the_team_list_of_a_business_that_isnt_a_church_reads_no_duties(db):
    staff = wt._staff(OTHER_BIZ, _u(OTHER_OWNER))
    assert [(s["role"], s["lane"], s["parts"]) for s in staff] == [
        ("owner", None, list(wt.ROLES)), ("manager", None, list(wt.ROLES)), ("admin", None, list(wt.ROLES))]
    assert not cd._CACHE


# ─── "clips are ready" ────────────────────────────────────────────────

@pytest.fixture
def pushed(db, monkeypatch):
    import push_notifications
    out = []
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: out.append(uid) or 1)
    return out


def _ready(biz, who):
    clip_finder.notify({"id": f"run-{who}", "business_id": biz, "created_by": who},
                       {"id": "s1", "name": "Sunday"}, 8, 0)


def test_clips_ready_reaches_the_media_team_once_each_never_the_owner_or_admins(db, pushed):
    _ready(BIZ, SHAP)
    assert pushed == [SHAP, JESS], "the starter first, then the other Managers who do clips; not the owner or the treasurer"
    pushed.clear()
    _ready(BIZ, OWNER)
    assert pushed == [OWNER, JESS, SHAP], "the owner's own run tells the owner, then the media team"
    pushed.clear()
    _move(db, "clips", SHAP)
    _ready(BIZ, SHAP)
    assert pushed == [SHAP], "moved to Shapretta alone: Jessica no longer hears"


def test_clips_ready_outside_a_church_reaches_only_the_starter(db, pushed):
    _ready(OTHER_BIZ, OTHER_MGR)
    assert pushed == [OTHER_MGR]


def test_clips_ready_still_reaches_the_starter_when_who_does_clips_cant_be_read(db, pushed, monkeypatch):
    _break_duties(db, monkeypatch)
    _ready(BIZ, SHAP)
    assert pushed == [SHAP]

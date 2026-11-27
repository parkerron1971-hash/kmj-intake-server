"""A made-up church for the one Sunday hub's tests (M-7, sunday_hub.py).

Three Sunday teams: Worship and Production (ChurchSavvy's), Welcome
(Volunteers'). One login for each way a church gives out Sunday work, the
way the split lanes give it (church_duties.standing is the test's):

  owner      the church's owner                      -> pastor (every role)
  admin      an Admin seat                           -> pastor (every role)
  planner    a Manager with sunday_plan              -> planner
  csadmin    a Manager with churchsavvy_team         -> planner (ChurchSavvy's Admin part)
  worship    the team's Worship part, no seat        -> team leader of Worship
  booth      the team's Booth part, no seat          -> media & tech
  streamer   a Manager with the stream duty          -> media & tech
  ministry   a Manager with the Sunday & Serving lane (ministry_ops) -> ministry operations
  volsched   a Manager with serve_schedule alone     -> no role, reads Sunday
  leader     a Manager whose person leads Welcome    -> team leader of Welcome
  carer      a Manager with care duties only         -> no Sunday at all
  viewer     a viewer seat                           -> no Sunday at all
  stranger   nobody to the church

Every name is invented."""
from __future__ import annotations

import os
import sys
import uuid as uuidlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_marketing  # noqa: E402
import church_duties as cd  # noqa: E402
import sb_clients  # noqa: E402
import sunday_hub as hub  # noqa: E402
import sunday_planning as sp  # noqa: E402
import worship_team as wt  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_sunday_planning import (ANA, BIZ, JO, KENDRA, LEE, MARCUS, NOW, OWNER_EMAIL, PRODUCTION, WELCOME,  # noqa: E402
                                  ZONE, FakeDb)

WORSHIP = "55555555-5555-4555-8555-555555555555"
WHO = ("owner", "admin", "planner", "csadmin", "worship", "booth", "streamer", "ministry", "volsched", "leader",
       "carer", "viewer", "stranger")
PEOPLE = {name: AuthedUser(id=f"u-{name}", email=f"{name}@gracegrove.org", role="authenticated") for name in WHO}
PEOPLE["owner"] = AuthedUser(id="u-owner", email=OWNER_EMAIL, role="authenticated")
SEATS = {"u-owner": "owner", "u-admin": "admin", "u-planner": "manager", "u-csadmin": "manager",
         "u-streamer": "manager", "u-ministry": "manager", "u-volsched": "manager", "u-leader": "manager",
         "u-carer": "manager", "u-viewer": "viewer"}
LANE = ("ministry_ops", "serve_schedule", "serve_teams", "new_volunteers", "background_checks", "serving_thanks",
        "events", "outreach_nights", "attendance")
DUTIES = {
    "u-planner": {"sunday_plan"},
    "u-csadmin": {"churchsavvy_team"},
    "u-streamer": {"stream"},
    "u-ministry": set(LANE),
    "u-volsched": {"serve_schedule"},
    "u-leader": {"rooms"},
    "u-carer": {"care_visits", "prayer", "shepherding"},
}


@pytest.fixture
def church(monkeypatch):
    db = FakeDb()
    db.t["businesses"][0]["type"] = "ministry"
    db.t["worship_team"] = [
        {"id": str(uuidlib.uuid4()), "business_id": BIZ, "user_id": "u-worship", "name": "Renee",
         "roles": ["worship"], "status": "active"},
        {"id": str(uuidlib.uuid4()), "business_id": BIZ, "user_id": "u-booth", "name": "Sam",
         "roles": ["booth"], "status": "active"},
    ]
    db.t["groups"].append({"id": WORSHIP, "business_id": BIZ, "name": "Worship", "kind": "team", "active": True})
    db.t["serve_teams"] = [
        {"group_id": WORSHIP, "business_id": BIZ, "owner": "churchsavvy", "sort": 0},
        {"group_id": PRODUCTION, "business_id": BIZ, "owner": "churchsavvy", "sort": 1},
        {"group_id": WELCOME, "business_id": BIZ, "owner": "volunteers", "sort": 2},
    ]
    # Lee leads Welcome; the leader login's seat is tied to Lee.
    db.t["group_members"] = [{"group_id": WELCOME, "business_id": BIZ, "contact_id": LEE, "role": "leader"},
                             {"group_id": WELCOME, "business_id": BIZ, "contact_id": ANA, "role": "member"}]
    db.t["business_users"] = [{"business_id": BIZ, "user_id": "u-leader", "role": "manager", "status": "active",
                               "contact_id": LEE, "invited_email": "leader@gracegrove.org", "name": "Lee"}]
    db.t["worship_settings"] = []
    db.KEYS = {**FakeDb.KEYS, "worship_settings": ("business_id",)}
    for c in db.t["contacts"]:
        c.setdefault("email", None)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", db.delete)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setenv("SUNDAY_HUB", "on")
    monkeypatch.delenv("CHURCHSAVVY_BILLING", raising=False)
    monkeypatch.setattr(wt, "role_of", lambda biz, uid: SEATS.get(str(uid)) if biz == BIZ else None)
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZONE)
    monkeypatch.setattr(sp, "_now", lambda: NOW)
    monkeypatch.setitem(sp._no_column, "at", 0.0)
    state = {"duties": {k: set(v) for k, v in DUTIES.items()}, "giving": {"u-owner", "u-admin"}}

    def fake_standing(biz, uid):
        role = SEATS.get(str(uid))
        if role in ("owner", "admin"):
            return {"church": True, "role": role, "lanes": [], "duties": cd.ALL}
        held = state["duties"].get(str(uid), set()) if role == "manager" else set()
        return {"church": True, "role": role, "lanes": [], "duties": frozenset(held)}
    monkeypatch.setattr(cd, "standing", fake_standing)

    def fake_giving(biz, user):
        if str(user.id) not in state["giving"]:
            raise HTTPException(403, "Giving is the finance team's.")
        return {"id": biz}
    import giving_services
    monkeypatch.setattr(giving_services, "_gate", fake_giving)

    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    import worship_router
    import worship_show_router
    app.include_router(worship_router.router)
    app.include_router(worship_show_router.router)
    app.include_router(hub.router)
    app.include_router(sp.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    yield SimpleNamespace(db=db, as_=as_, app=app, state=state, who=who)


__all__ = ["ANA", "BIZ", "JO", "KENDRA", "LEE", "LANE", "MARCUS", "NOW", "PEOPLE", "PRODUCTION", "SEATS", "WELCOME",
           "WORSHIP", "ZONE", "church"]

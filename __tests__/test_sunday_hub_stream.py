"""The one Sunday hub: media & tech set up the stream (stream_relay_router;
M-7, Kevin's decisions church-office-1, 2026-11-27).

Pins:
  * a manager seat or the owner reaches the stream's setup, as always
  * with SUNDAY_HUB on, so does a login whose ChurchSavvy team part runs the
    livestream (worship_team.team_can "live": Media, Booth, Admin); a part
    that doesn't (Worship alone) and a seat below manager still don't
  * with the switch off, only a manager or the owner, as before
  * all three of the stream's team routes ask the same question"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stream_relay_router as srr  # noqa: E402
import worship_team  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER_EMAIL = "kmjcreativesolution@gmail.com"
SEATS = {"u-manager": "manager", "u-viewer": "viewer"}
LIVE = {"u-media", "u-booth"}           # team parts that run the livestream
PEOPLE = {n: AuthedUser(id=f"u-{n}", email=f"{n}@gracegrove.org", role="authenticated")
          for n in ("manager", "viewer", "media", "booth", "worship")}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("SUNDAY_HUB", "on")

    def fake_require(biz, user, minimum):
        if SEATS.get(str(user.id)) != "manager":
            raise HTTPException(403, "Only a manager or the owner can do that.")
        return "manager"
    monkeypatch.setattr(srr, "require", fake_require)
    monkeypatch.setattr(worship_team, "team_can", lambda biz, user, what: what == "live" and str(user.id) in LIVE)
    monkeypatch.setattr(srr, "is_ready", lambda: False)    # past the gate, every route stops here
    who = {"user": PEOPLE["manager"]}
    app = FastAPI()
    app.include_router(srr.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    c = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return c
    return as_


def _calls(as_, name):
    c = as_(name)
    return [c.get("/stream-relay", params={"business_id": BIZ}).status_code,
            c.post("/stream-relay/key", json={"business_id": BIZ}).status_code,
            c.patch("/stream-relay/settings", json={"business_id": BIZ}).status_code]


def test_a_manager_as_always(client):
    assert _calls(client, "manager")[0] == 200
    assert 403 not in _calls(client, "manager")


@pytest.mark.parametrize("who", ["media", "booth"])
def test_media_and_tech_with_the_hub_on(client, who):
    got = _calls(client, who)
    assert got[0] == 200 and 403 not in got, got


@pytest.mark.parametrize("who", ["worship", "viewer"])
def test_no_live_part_no_stream(client, who):
    assert _calls(client, who) == [403, 403, 403]


def test_off_only_a_manager(client, monkeypatch):
    monkeypatch.setenv("SUNDAY_HUB", "off")
    assert _calls(client, "media") == [403, 403, 403]
    assert _calls(client, "manager")[0] == 200

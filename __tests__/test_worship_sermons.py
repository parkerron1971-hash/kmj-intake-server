"""Sermons from ChurchSavvy (worship_sermons.py), for the team's Media part.
Kevin, 2026-10-23: a Media team gets the media part already set up.

Pins:
  * Media and Admin parts, and the church's owner, admins and managers,
    write sermons and series; the booth, the planner and a member seat read
  * a stranger, or someone taken off the team, gets 404, as for every
    worship route; ChurchSavvy's switch closes it
  * the tables' limits are said in words: a title, a real day, https links,
    lengths; a series must be the church's own
  * one church never reaches another's sermon or series
  * deleting a series leaves its sermons
  * a failed read is a 503, never an empty library
"""
from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import sb_clients  # noqa: E402
import worship_sermons as ws  # noqa: E402
from auth_supabase import require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
IDS = {n: f"00000000-0000-4000-8000-{i:012d}" for i, n in
       enumerate(("owner", "manager", "member", "mo", "sam", "gone", "stranger", "other_owner"), start=1)}
THEIRS = "99999999-9999-4999-8999-999999999999"


@pytest.fixture
def api(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "owner_id": IDS["owner"], "is_active": True},
                    {"id": OTHER, "name": "Other Church", "owner_id": IDS["other_owner"], "is_active": True}],
        business_users=[{"business_id": BIZ, "user_id": IDS["manager"], "role": "manager", "status": "active"},
                        {"business_id": BIZ, "user_id": IDS["member"], "role": "member", "status": "active"}],
        worship_team=[{"business_id": BIZ, "user_id": IDS["mo"], "roles": ["media"], "status": "active"},
                      {"business_id": BIZ, "user_id": IDS["sam"], "roles": ["booth"], "status": "active"},
                      {"business_id": BIZ, "user_id": IDS["gone"], "roles": ["media"], "status": "removed"}],
        sermons=[{"id": THEIRS, "business_id": OTHER, "title": "Theirs", "preached_on": "2026-10-18",
                  "series_id": None, "published": True}],
        sermon_series=[{"id": "88888888-8888-4888-8888-888888888888", "business_id": OTHER, "title": "Their series"}],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "site_config": {"custom_domain": "lovecityc.com"}}],
    )
    for verb in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{verb}_as_service", getattr(fake, verb))
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    app = FastAPI()
    app.include_router(ws.router)
    who = {"id": IDS["owner"]}
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=who["id"], email="someone@lovecity.org")
    client = TestClient(app)

    def as_(name):
        who["id"] = IDS[name]
        return client
    return fake, as_


SERMON = {"business_id": BIZ, "title": "Grace Upon Grace", "preached_on": "2026-10-25", "speaker": "Pastor Kevin",
          "scripture": "John 1:16", "video_url": "https://youtu.be/abc"}


def test_the_media_part_writes_sermons_and_series(api):
    db, as_ = api
    s = as_("mo").post("/worship/sermon-series", json={"business_id": BIZ, "title": "John"})
    assert s.status_code == 200
    sid = s.json()["series"]["id"]
    r = as_("mo").post("/worship/sermons", json={**SERMON, "series_id": sid})
    assert r.status_code == 200
    sermon = r.json()["sermon"]
    assert sermon["series_id"] == sid and sermon["published"] is True and sermon["speaker"] == "Pastor Kevin"
    r = as_("mo").patch(f"/worship/sermons/{sermon['id']}", json={"business_id": BIZ, "published": False, "summary": "  Grace.  "})
    assert r.status_code == 200 and r.json()["sermon"]["published"] is False and r.json()["sermon"]["summary"] == "Grace."
    listed = as_("mo").get(f"/worship/sermons?business_id={BIZ}").json()
    assert listed["can_write"] is True and [x["title"] for x in listed["sermons"]] == ["Grace Upon Grace"]
    assert listed["public_base"] == "https://lovecityc.com/sermons"
    assert "Theirs" not in [x["title"] for x in listed["sermons"]]


@pytest.mark.parametrize("name", ["owner", "manager"])
def test_the_churchs_staff_write_as_admins(api, name):
    db, as_ = api
    assert as_(name).post("/worship/sermons", json=SERMON).status_code == 200


@pytest.mark.parametrize("name", ["sam", "member"])
def test_other_parts_and_a_member_seat_read_and_change_nothing(api, name):
    db, as_ = api
    assert as_(name).get(f"/worship/sermons?business_id={BIZ}").json()["can_write"] is False
    refused = as_(name).post("/worship/sermons", json=SERMON)
    assert refused.status_code == 403 and "Media does" in refused.json()["detail"]
    assert as_(name).post("/worship/sermon-series", json={"business_id": BIZ, "title": "Mine"}).status_code == 403
    assert db.t.get("sermons")[0]["title"] == "Theirs" and len(db.t["sermons"]) == 1


@pytest.mark.parametrize("name", ["stranger", "gone"])
def test_a_stranger_or_someone_taken_off_the_team_gets_404(api, name):
    db, as_ = api
    assert as_(name).get(f"/worship/sermons?business_id={BIZ}").status_code == 404
    assert as_(name).post("/worship/sermons", json=SERMON).status_code == 404


def test_the_switch_closes_it(api, monkeypatch):
    db, as_ = api
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert as_("owner").get(f"/worship/sermons?business_id={BIZ}").status_code == 404
    assert as_("mo").post("/worship/sermons", json=SERMON).status_code == 404


@pytest.mark.parametrize("change,words", [
    ({"title": "   "}, "The title can't be empty"),
    ({"title": "x" * 161}, "The title is at most 160 characters"),
    ({"preached_on": "last Sunday"}, "like 2026-10-25"),
    ({"video_url": "http://youtu.be/abc"}, "https://"),
    ({"audio_url": "https://a b"}, "https://"),
    ({"summary": "x" * 2001}, "The summary is at most 2000 characters"),
    ({"published": "yes"}, "Published is yes or no"),
    ({"speaker": 7}, "The speaker should be words"),
])
def test_the_tables_limits_are_said_in_words(api, change, words):
    db, as_ = api
    r = as_("mo").post("/worship/sermons", json={**SERMON, **change})
    assert r.status_code == 400 and words in r.json()["detail"]
    assert len(db.t["sermons"]) == 1


def test_one_church_never_reaches_anothers_sermon_or_series(api):
    db, as_ = api
    their_series = db.t["sermon_series"][0]["id"]
    assert as_("mo").post("/worship/sermons", json={**SERMON, "series_id": their_series}).status_code == 404
    assert as_("mo").patch(f"/worship/sermons/{THEIRS}", json={"business_id": BIZ, "title": "Mine"}).status_code == 404
    assert as_("mo").delete(f"/worship/sermons/{THEIRS}?business_id={BIZ}").status_code == 404
    assert as_("mo").patch(f"/worship/sermon-series/{their_series}", json={"business_id": BIZ, "title": "Mine"}).status_code == 404
    assert as_("mo").delete(f"/worship/sermon-series/{their_series}?business_id={BIZ}").status_code == 404
    assert db.t["sermons"][0]["title"] == "Theirs" and db.t["sermon_series"][0]["title"] == "Their series"
    # Naming the other church as the business is the other church's team question, and Mo isn't on it.
    assert as_("mo").patch(f"/worship/sermons/{THEIRS}", json={"business_id": OTHER, "title": "Mine"}).status_code == 404


def test_a_sermon_comes_down_and_a_series_goes_without_its_sermons(api):
    db, as_ = api
    sid = as_("mo").post("/worship/sermon-series", json={"business_id": BIZ, "title": "John"}).json()["series"]["id"]
    one = as_("mo").post("/worship/sermons", json={**SERMON, "series_id": sid}).json()["sermon"]["id"]
    two = as_("mo").post("/worship/sermons", json={**SERMON, "title": "Second"}).json()["sermon"]["id"]
    assert as_("mo").delete(f"/worship/sermons/{two}?business_id={BIZ}").status_code == 200
    assert as_("mo").delete(f"/worship/sermon-series/{sid}?business_id={BIZ}").status_code == 200
    assert [r["id"] for r in db.t["sermons"] if r["business_id"] == BIZ] == [one]
    assert as_("mo").patch(f"/worship/sermons/{one}", json={"business_id": BIZ}).status_code == 400


def test_a_failed_read_is_a_503_never_an_empty_library(api, monkeypatch):
    db, as_ = api
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("sermons?") else real(path, **kw))
    assert as_("mo").get(f"/worship/sermons?business_id={BIZ}").status_code == 503

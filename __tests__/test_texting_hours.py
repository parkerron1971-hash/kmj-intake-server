"""A church's own texting hours (2026-11-14).

Kevin, on the Church Texting Playbook: "make sure that people know they can
adjust the window when automatic texts can go out. and any other rule we have
as default that they can make the changes", then "yes build the texting hours
panel". Pinned here:
  1. The defaults are what everyone had; a saved choice outside what's
     allowed reads as the default; New here's times stay inside the hours.
  2. What saving refuses (federal calling hours, ranges, a time outside the
     church's hours) and who may save.
  3. The choices reach what they govern: quiet hours for app alerts (and so
     serving asks and Important posts), the alerts-a-day cap, New here's
     thank-you, note, invite and send window.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import texting_hours as th  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
ET = ZoneInfo("America/New_York")
MINE = {"auto_from": 10, "auto_until": 19, "quiet_from": 22, "quiet_until": 8, "alerts_per_day": 5,
        "note": {"day": 1, "hour": 11}, "invite": {"day": 4, "hour": 17}}


def church(hours=None, **more):
    return {"id": BIZ, "name": "Grace Grove", "type": "church", "owner_id": "o1",
            "settings": {"texting_hours": hours or {}, **more}}


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# ── 1. the defaults and what a saved choice can be ────────────────────

def test_the_defaults_are_what_everyone_had():
    assert th.of(church()) == th.DEFAULTS
    assert th.of(None) == th.DEFAULTS and th.of({"settings": {"texting_hours": "nope"}}) == th.DEFAULTS
    assert [h for h in range(24) if th.is_quiet(church(), h)] == [0, 1, 2, 3, 4, 5, 6, 21, 22, 23]
    assert th.alerts_per_day(church()) == 3
    assert th.in_auto_window(church(), at(2026, 11, 15, 9)) and not th.in_auto_window(church(), at(2026, 11, 15, 20))


def test_a_churchs_own_choices_and_what_isnt_allowed():
    mine = th.of(church(MINE))
    assert mine == MINE
    assert [h for h in range(24) if th.is_quiet(church(MINE), h)] == [0, 1, 2, 3, 4, 5, 6, 7, 22, 23]
    bad = th.of(church({"auto_from": 6, "auto_until": 23, "alerts_per_day": 9, "quiet_from": 3,
                        "note": {"day": 6, "hour": 10}}))
    assert bad["auto_from"] == 9 and bad["auto_until"] == 20                 # never before 8 or after 9 PM
    assert bad["alerts_per_day"] == 3 and bad["quiet_from"] == 21 and bad["note"]["day"] == 0   # no Sundays
    late = th.of(church({"auto_from": 12, "auto_until": 17, "invite": {"day": 3, "hour": 18}}))
    assert late["invite"]["hour"] == 16 and late["note"]["hour"] == 12       # held inside the church's hours
    assert [th.hour_words(h) for h in (0, 9, 12, 20)] == ["midnight", "9 AM", "noon", "8 PM"]


# ── 2. saving ─────────────────────────────────────────────────────────

def _body(**over):
    return th.HoursIn(**{**MINE, **over})


def test_what_saving_refuses():
    assert th.clean(_body()) == MINE
    for bad, why in ((_body(auto_from=7), "8 AM"), (_body(auto_until=22), "after 9 PM"),
                     (_body(quiet_from=18), "Quiet hours start"), (_body(quiet_until=11), "Quiet hours end"),
                     (_body(alerts_per_day=0), "1 to 5"), (_body(note={"day": 6, "hour": 11}), "Monday to Saturday"),
                     (_body(invite={"day": 3, "hour": 19}), "inside your automatic-text hours")):
        with pytest.raises(HTTPException) as e:
            th.clean(bad)
        assert e.value.status_code == 400 and why in e.value.detail, why


@pytest.fixture
def api(monkeypatch):
    import business_access
    state = {"biz": church(), "patches": [], "edit": True, "read": True}

    def assert_access(biz, user, role):
        if not state["read"]:
            raise HTTPException(404, "Not found")
        return "admin"

    def patch(path, row, **kw):
        state["patches"].append((path, row))
        return [row]

    monkeypatch.setattr(business_access, "assert_access", assert_access)
    monkeypatch.setattr(th, "_business", lambda bid: state["biz"])
    monkeypatch.setattr(th, "_may_edit", lambda bid, user: state["edit"])
    monkeypatch.setattr(th.sb_clients, "sb_patch_as_service", patch)
    from auth_supabase import AuthedUser, require_user
    app = FastAPI()
    app.include_router(th.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id="u1", email="o@x.test", role="authenticated")
    return TestClient(app), state


def test_reading_and_saving(api):
    c, state = api
    got = c.get(f"/texting-hours/{BIZ}").json()
    assert got["hours"] == th.DEFAULTS and got["can_edit"] is True
    assert got["limits"]["auto_until"] == [17, 21] and got["limits"]["alerts_per_day"] == [1, 5]
    state["biz"] = church(other={"keep": 1})
    r = c.put(f"/texting-hours/{BIZ}", json=_body().model_dump())
    assert r.status_code == 200 and r.json()["hours"] == MINE
    (path, row), = state["patches"]
    assert row["settings"]["texting_hours"] == MINE and row["settings"]["other"] == {"keep": 1}
    assert c.put(f"/texting-hours/{BIZ}", json=_body(auto_until=23).model_dump()).status_code == 400
    state["edit"] = False
    assert c.put(f"/texting-hours/{BIZ}", json=_body().model_dump()).status_code == 403
    state["read"] = False
    assert c.get(f"/texting-hours/{BIZ}").status_code == 404


# ── 3. the choices reach what they govern ─────────────────────────────

def test_quiet_hours_follow_the_church(monkeypatch):
    import business_marketing
    import member_push as mp
    monkeypatch.setenv("MEMBER_QUIET_HOURS", "on")
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ET)
    ten_pm_utc = at(2026, 11, 15, 21, 30).astimezone(timezone.utc)          # 9:30 PM at the church
    assert mp.quiet_hour(church(), ten_pm_utc) is True                       # the default starts at 9
    assert mp.quiet_hour(church(MINE), ten_pm_utc) is False                  # this church starts at 10
    seven_am = at(2026, 11, 16, 7, 30).astimezone(timezone.utc)
    assert mp.quiet_hour(church(), seven_am) is False and mp.quiet_hour(church(MINE), seven_am) is True
    assert mp.is_quiet_hour(21) is True                                      # no church: as before


def test_the_alerts_a_day_follow_the_church():
    import news_alerts as na
    assert na.daily_max() == 3 and na.daily_max(church()) == 3 and na.daily_max(church(MINE)) == 5
    src = (pathlib.Path(th.__file__).parent / "member_push.py").read_text(encoding="utf-8")
    assert "cap = texting_hours.alerts_per_day(biz)" in src


def test_new_here_follows_the_church(monkeypatch):
    import new_here as nh
    monkeypatch.setattr(nh, "tz_of", lambda business: ET)
    s = nh.settings_of({"settings": {"new_here": {"on": True, "thanks": {"hours": 6}}}})
    got = {k: v.astimezone(ET) for k, v in nh.plan_times(church(MINE), at(2026, 11, 15, 14), s).items()}
    assert got["thanks"] == at(2026, 11, 15, 18, 45)                          # held 15 minutes before 7 PM
    assert got["monday"] == at(2026, 11, 17, 11)                              # this church's Tuesday 11 AM
    assert got["invite"] == at(2026, 11, 20, 17)                              # this church's Friday 5 PM
    assert nh._hours(church(MINE))["words"] == {"window": "10 AM to 7 PM", "latest": "6:45 PM",
                                                "note": "Tuesday at 11 AM", "invite": "Friday at 5 PM"}
    src = pathlib.Path(nh.__file__).read_text(encoding="utf-8")
    assert "texting_hours.in_auto_window(fresh, local)" in src               # the send checks the church's window


def test_the_router_is_mounted():
    src = (pathlib.Path(th.__file__).parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "from texting_hours import router as texting_hours_router" in src

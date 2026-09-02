"""A business is born whole, and the plug-in filter speaks every alias.

Two Wave-A fixes from the 2026-09-02 onboarding audit:

1. The profile defaults, blueprint modules and vertical autopilot used to
   hang off a second, client-initiated request that answered 404 for four
   months. create_business now schedules them itself, after the response.
2. plugins_for_vertical compared the raw `businesses.type` against a
   list of canonical keys, so "barber" never got the availability step a
   "personal_services" business got.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import business_track_actions as bta  # noqa: E402
import launch_access as la  # noqa: E402
import vertical_registry  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _BG:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append((fn, a, kw))


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.delenv("LAUNCH_INVITE_ONLY", raising=False)
    import usage_metering
    monkeypatch.setattr(usage_metering, "is_grandfathered_user", lambda uid: True)
    return fb


def _user():
    return type("U", (), {"id": "own1", "email": "kim@example.com"})()


class TestCreateBusinessSeeds:
    def test_the_seed_is_scheduled_with_the_row_type_and_voice(self, fake):
        body = la.CreateBusinessBody(name="Northside Cuts", type="barber",
                                     voice_profile={"tone": "warm"},
                                     settings={"practitioner_name": "Kim"})
        bg = _BG()
        out = la.create_business(body, _user(), bg)
        assert out["ok"]
        seeds = [t for t in bg.tasks if t[0] is la._seed_new_business]
        assert len(seeds) == 1
        _, args, _ = seeds[0]
        row, btype, voice, owner = args
        assert row["name"] == "Northside Cuts"
        assert btype == "barber"
        assert voice == {"tone": "warm"}
        assert owner == "own1"

    def test_no_background_tasks_still_creates_the_business(self, fake):
        body = la.CreateBusinessBody(name="Northside Cuts", type="barber")
        out = la.create_business(body, _user(), None)
        assert out["ok"] and out["business"]["name"] == "Northside Cuts"


class TestSeedNewBusiness:
    def _spies(self, monkeypatch, *, fail=()):
        calls = {}
        import business_profile_agent as bp
        import module_blueprint_agent as mba
        import vertical_autopilot as va

        def _profile(**kw):
            calls["profile"] = kw
            if "profile" in fail:
                raise RuntimeError("profile down")
            return {"business_id": kw["business_id"]}

        def _modules(biz_id, btype):
            calls["modules"] = (biz_id, btype)
            if "modules" in fail:
                raise RuntimeError("blueprint down")
            return []

        def _autopilot(**kw):
            calls["autopilot"] = kw
            if "autopilot" in fail:
                raise RuntimeError("autopilot down")
            return {"queued": 1}

        monkeypatch.setattr(bp, "seed_from_onboarding", _profile)
        monkeypatch.setattr(mba, "provision_modules", _modules)
        monkeypatch.setattr(va, "seed_defaults", _autopilot)
        return calls

    def test_all_three_run_with_the_business_and_type(self, monkeypatch):
        calls = self._spies(monkeypatch)
        out = la._seed_new_business({"id": "b1"}, "barber", {"tone": "warm"}, "own1")
        assert out == {"profile": True, "modules": True, "autopilot": True}
        assert calls["profile"] == {"business_id": "b1", "business_type": "barber",
                                    "tones": None, "voice_profile": {"tone": "warm"}}
        assert calls["modules"] == ("b1", "barber")
        assert calls["autopilot"] == {"business_id": "b1", "business_type": "barber",
                                      "owner_id": "own1"}

    def test_one_failure_does_not_stop_the_others_and_nothing_raises(self, monkeypatch):
        calls = self._spies(monkeypatch, fail=("profile", "autopilot"))
        out = la._seed_new_business({"id": "b1"}, "barber", None, "own1")
        assert out == {"profile": False, "modules": True, "autopilot": False}
        assert set(calls) == {"profile", "modules", "autopilot"}

    def test_a_row_without_an_id_does_nothing(self, monkeypatch):
        calls = self._spies(monkeypatch)
        assert la._seed_new_business({}, "barber", None, "own1") == {
            "profile": False, "modules": False, "autopilot": False}
        assert calls == {}


class TestPluginsForVerticalAliases:
    def test_every_alias_gets_its_canonical_verticals_list(self):
        table = vertical_registry.alias_to_canonical()
        assert table, "the alias table is empty"
        for alias, canonical in table.items():
            assert bta.plugins_for_vertical(alias) == bta.plugins_for_vertical(canonical), alias

    def test_a_counselor_gets_the_hours_step_like_a_therapist_does(self):
        # "counselor" and "law" are registry aliases; before the fix only
        # the canonical spellings were offered the availability step.
        assert vertical_registry.resolve("counselor") == "therapist"
        assert "availability" in bta.plugins_for_vertical("therapist")
        assert "availability" in bta.plugins_for_vertical("counselor")
        assert "availability" in bta.plugins_for_vertical(" Law ")

    def test_an_unknown_type_still_gets_the_universal_list(self):
        keys = bta.plugins_for_vertical("unknown_vertical")
        assert keys[0] == "import_contacts"
        assert "availability" not in keys

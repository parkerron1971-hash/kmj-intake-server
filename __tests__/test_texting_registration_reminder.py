"""The week-one texting reminder (Kevin, 2026-11-22: "yes add the reminder
after a week"). A church that got its number a week ago and hasn't sent its
registration: the owner is told once. Pinned here:
  1. who is told: a church, open to register, not sent, not a sample, not
     reminded already, not in quiet hours;
  2. the stamp is written BEFORE the tell, and no stamp means no tell;
  3. the words are a church's, and a business has none;
  4. the switch turns it off.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import texting_registration as tr  # noqa: E402

NOW = datetime(2026, 11, 30, 16, 0, tzinfo=timezone.utc)
CHURCH = {"id": "c0000000-0000-4000-8000-000000000001", "name": "Grace Hill Church", "type": "church",
          "settings": {}, "owner_id": "u1"}
SHOP = {"id": "b0000000-0000-4000-8000-000000000002", "name": "Northside Cuts", "type": "barber",
        "settings": {}, "owner_id": "u2"}


def run(x):
    return asyncio.run(x)


@pytest.fixture
def world(monkeypatch):
    import business_settings
    import member_push
    import sample_church

    monkeypatch.setenv("TEXTING_REGISTRATION_OPEN", "churches")
    monkeypatch.delenv("TEXTING_REGISTRATION_REMINDER", raising=False)
    w = {"lines": [{"business_id": CHURCH["id"]}], "biz": {CHURCH["id"]: dict(CHURCH), SHOP["id"]: dict(SHOP)},
         "reg": {}, "merged": [], "told": [], "order": [], "queries": [], "merge_ok": True,
         "quiet": False, "sample": False}

    def read(path):
        w["queries"].append(path)
        if path.startswith("/sms_numbers"):
            return w["lines"]
        if path.startswith("/businesses"):
            bid = path.split("id=eq.")[1].split("&")[0]
            return [w["biz"][bid]] if bid in w["biz"] else []
        raise AssertionError(path)

    def merge(bid, put):
        w["order"].append("stamp")
        w["merged"].append((bid, put))
        return {"ok": True} if w["merge_ok"] else None

    async def tell(business, status, reasons=None, number=None):
        w["order"].append("tell")
        w["told"].append((business["id"], status))
        return {"in_app": True, "push": False, "email": True}

    monkeypatch.setattr(tr, "_read", read)
    monkeypatch.setattr(tr, "registration", lambda bid: w["reg"].get(bid))
    monkeypatch.setattr(tr, "_tell_owner", tell)
    monkeypatch.setattr(business_settings, "merge", merge)
    monkeypatch.setattr(member_push, "quiet_hour", lambda b, now=None: w["quiet"])
    monkeypatch.setattr(sample_church, "skip", lambda b: w["sample"])
    return w


def test_a_church_a_week_on_with_no_registration_is_told_once(world):
    out = run(tr.remind_tick(NOW))
    assert out == {"checked": 1, "told": 1, "failed": 0}
    assert world["told"] == [(CHURCH["id"], "reminder")]
    assert world["order"] == ["stamp", "tell"], "stamped before telling"
    assert world["merged"][0][1] == {tr.REMINDED_KEY: NOW.isoformat()}
    q = world["queries"][0]
    assert "status=eq.active" in q and "account_sid=is.null" in q
    assert "purchased_at=lt.2026-11-23T16%3A00%3A00%2B00%3A00" in q, "a week before now, quoted"


def test_a_church_already_reminded_is_not_told_again(world):
    world["biz"][CHURCH["id"]]["settings"] = {tr.REMINDED_KEY: "2026-11-29T16:00:00+00:00"}
    assert run(tr.remind_tick(NOW))["told"] == 0
    assert world["told"] == [] and world["merged"] == []


@pytest.mark.parametrize("status", ["submitted", "brand_pending", "campaign_pending", "approved"])
def test_a_sent_registration_is_never_reminded(world, status):
    world["reg"][CHURCH["id"]] = {"status": status, "twilio": {}}
    assert run(tr.remind_tick(NOW))["told"] == 0


@pytest.mark.parametrize("status", ["draft", "failed"])
def test_a_started_but_unsent_registration_is_reminded(world, status):
    world["reg"][CHURCH["id"]] = {"status": status, "twilio": {}}
    assert run(tr.remind_tick(NOW))["told"] == 1


def test_a_business_is_never_reminded(world):
    world["lines"] = [{"business_id": SHOP["id"]}]
    assert run(tr.remind_tick(NOW))["told"] == 0
    assert tr.update_words(SHOP, "reminder") is None, "a business has no reminder words"


def test_quiet_hours_a_sample_church_and_a_closed_switch_hold_it(world, monkeypatch):
    world["quiet"] = True
    assert run(tr.remind_tick(NOW))["told"] == 0
    world["quiet"], world["sample"] = False, True
    assert run(tr.remind_tick(NOW))["told"] == 0
    world["sample"] = False
    monkeypatch.setenv("TEXTING_REGISTRATION_OPEN", "")
    assert run(tr.remind_tick(NOW))["told"] == 0
    assert world["merged"] == [], "nothing stamped while held: told later"


def test_no_stamp_means_no_tell(world):
    world["merge_ok"] = False
    out = run(tr.remind_tick(NOW))
    assert out["told"] == 0 and out["failed"] == 1 and world["told"] == []


def test_the_switch_turns_it_off(world, monkeypatch):
    monkeypatch.setenv("TEXTING_REGISTRATION_REMINDER", "off")
    assert run(tr.remind_tick(NOW))["off"] is True
    assert world["queries"] == []


def test_the_words_are_a_churchs():
    title, body = tr.update_words(CHURCH, "reminder")
    assert title == "Put Grace Hill Church's name on its texts"
    assert "Your name on texts" in body and "number stays the same" in body
    assert "client" not in body.lower() and "business" not in body.lower()

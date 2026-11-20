"""Two fixes on a church's Members page (Kevin, 2026-11-20: "the ability to
edited names and enter new people is off"):

  · a number nobody knows that texts a CHURCH is filed as a guest ("lead"),
    never "active" (which a church's roll reads as Member); every other
    business keeps "active", and an unreadable business is a guest;
  · a stored first or last name (an import's metadata) counts only while it
    is still in the full name, so a person renamed anywhere else sorts and
    greets by the new name."""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_roll as cr  # noqa: E402
import sms_routing  # noqa: E402
import sms_service  # noqa: E402
from test_church_roll import BIZ, CALVIN, _p, _roll, clock, db  # noqa: E402,F401


# ─── a stored part of a name ──────────────────────────────────────────

def test_a_stored_last_name_counts_only_while_it_is_still_in_the_name():
    assert cr.last_name("Angela M Tatum", "Tatum") == "Tatum"
    assert cr.last_name("Troy Hunter Jr", "Hunter Jr") == "Hunter Jr"        # the import's split stands
    assert cr.last_name("Diane trigge", "trigge") == "trigge"
    # Renamed elsewhere: the stored part is stale and the name decides.
    assert cr.last_name("Mary Jones", "Smith") == "Jones"
    assert cr.last_name("Mary Smith-Jones", "Smith") == "Smith-Jones"
    assert cr.last_name("Mary Jones Jr", "") == "Jones"
    assert cr.last_name("Prince", "") == "Prince"


def test_a_stored_first_name_counts_only_while_it_is_still_in_the_name():
    assert cr.first_of("Mary Ann Jones", "Mary Ann") == "Mary Ann"
    assert cr.first_of("Maria Jones", "Mary") == "Maria"
    assert cr.first_of("Maria Jones", "") == "Maria"
    assert cr.first_of("", "") == ""


def test_the_roll_files_a_renamed_person_by_the_new_name(db):
    calvin = next(c for c in db.t["contacts"] if c["id"] == CALVIN)
    assert calvin["metadata"]["first_name"] == "Calvin" and calvin["metadata"]["last_name"] == "Carter"
    calvin["name"] = "Cal Whitfield"                     # renamed on the Members page; metadata untouched
    v = _roll(db)
    assert _p(v, CALVIN)["last"] == "Whitfield" and _p(v, CALVIN)["first"] == "Cal"


# ─── a new texter's status ────────────────────────────────────────────

def _biz(monkeypatch, row):
    async def fake_get(client, path):
        assert path.startswith(f"/businesses?id=eq.{BIZ}")
        return [row] if row else None
    monkeypatch.setattr(sms_service, "_sb_get", fake_get)


def test_a_church_files_a_new_texter_as_a_guest(monkeypatch):
    _biz(monkeypatch, {"id": BIZ, "type": "church"})
    assert asyncio.run(sms_service.new_texter_status(None, BIZ)) == "lead"
    _biz(monkeypatch, {"id": BIZ, "type": "ministry"})
    assert asyncio.run(sms_service.new_texter_status(None, BIZ)) == "lead"


def test_every_other_business_keeps_active_and_an_unreadable_one_is_a_guest(monkeypatch):
    _biz(monkeypatch, {"id": BIZ, "type": "barber"})
    assert asyncio.run(sms_service.new_texter_status(None, BIZ)) == "active"
    _biz(monkeypatch, None)
    assert asyncio.run(sms_service.new_texter_status(None, BIZ)) == "lead"


def test_a_bound_texters_contact_at_a_church_is_a_guest(monkeypatch):
    _biz(monkeypatch, {"id": BIZ, "type": "church"})
    posted = []

    async def none(client, business_id, phone):
        return None

    async def post(client, path, body):
        posted.append((path, body))
        return [body]

    monkeypatch.setattr(sms_routing, "_find_contact_by_phone", none)
    monkeypatch.setattr(sms_routing, "_sb_post", post)
    asyncio.run(sms_routing._ensure_contact(None, BIZ, "+15550142290"))
    assert posted == [("/contacts", {"business_id": BIZ, "name": "+15550142290", "phone": "+15550142290", "status": "lead"})]

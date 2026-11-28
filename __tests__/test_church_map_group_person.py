"""Who a group answers to reaches the chain and the map (M-8, part 2; Kevin
2026-11-28: a leader answers to a specific person, "which elder", with the
role as the fallback; the leaders map on for every church).

  1. a group's item climbs to the person the group answers to first, while
     they hold an active role; then on up from them
  2. someone who no longer holds a role is passed over: the department and
     the role chain, as before
  3. that person is over the group's leaders (church_over)
  4. a group leader with no role: their late tasks go to that person
  5. before the file, nothing changes (no group links, no read)
  6. Leaders & roles carries each holder's own person
  7. the map is on for every church by default; owner still means Love City
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import church_leader_tasks as clt  # noqa: E402
import church_map as cm  # noqa: E402
import church_over as co  # noqa: E402
import church_roles as cr  # noqa: E402
import sb_clients  # noqa: E402
import church_three as c3  # noqa: E402
from church_three import GRACE, LOVE_CITY as LC, build, church  # noqa: E402


def _group(db, name):
    return next(g for g in db.t["groups"] if g["business_id"] == LC and g["name"] == name)


@pytest.fixture
def lc(monkeypatch):
    db = build(monkeypatch)
    cm._READY.pop("groups", None)
    for g in db.t["groups"]:
        g.setdefault("answers_to_contact_id", None)
    return db


def _chain(db, person, group_id):
    m = cm.load(LC)
    defs = cr.defs(LC)
    held = cr.active_holders(cfu.roles(LC))
    return m, cm.chain_for(m, defs, held, person, None, group_id=group_id, skip={person})


def test_a_groups_item_goes_to_the_person_it_answers_to_first(lc):
    w = lc.who[LC]
    sisters = _group(lc, "Sisters in the City")
    sisters["answers_to_contact_id"] = w["marcus"]               # an elder
    m, chain = _chain(lc, w["gloria"], sisters["id"])
    assert m.group_answers_to(sisters["id"]) == w["marcus"]
    step, rows = chain[0]
    assert step["answers_to"] == w["marcus"] and step["for_group"] == sisters["id"]
    assert [str(r["contact_id"]) for r in rows] == [w["marcus"]]
    # Then on up from Marcus: he answers to Jessica on Love City's map.
    assert any(w["jessica"] in [str(r["contact_id"]) for r in rs] for _s, rs in chain[1:])


def test_someone_without_a_role_is_passed_over(lc):
    w = lc.who[LC]
    youth = _group(lc, "Youth")
    _m, before = _chain(lc, w["yolanda"], youth["id"])
    youth["answers_to_contact_id"] = w["calvin"]                # holds no role
    _m, after = _chain(lc, w["yolanda"], youth["id"])
    assert [s.get("title") for s, _ in after] == [s.get("title") for s, _ in before]


def test_the_person_is_over_the_groups_leaders(lc):
    w = lc.who[LC]
    sisters = _group(lc, "Sisters in the City")
    ch = co.Church(church(lc, LC))
    assert w["gloria"] not in {r["id"] for r in co.under(ch, co.who(co.PERSON, w["marcus"]))}
    sisters["answers_to_contact_id"] = w["marcus"]
    ch = co.Church(church(lc, LC))
    under = {r["id"]: r for r in co.under(ch, co.who(co.PERSON, w["marcus"]))}
    assert w["gloria"] in under


def test_a_group_leader_with_no_role_goes_to_that_person(lc):
    w = lc.who[LC]
    sisters = _group(lc, "Sisters in the City")
    sisters["answers_to_contact_id"] = w["tanya"]                # the other elder
    m = cm.load(LC)
    step, rows = clt.group_department(m, LC, w["gloria"], cfu.roles(LC), cr.defs(LC))
    assert step["answers_to"] == w["tanya"] and [str(r["contact_id"]) for r in rows] == [w["tanya"]]


def test_before_the_file_nothing_changes(lc, monkeypatch):
    w = lc.who[LC]
    sisters = _group(lc, "Sisters in the City")
    sisters["answers_to_contact_id"] = w["marcus"]
    real = sb_clients.sb_get_as_service
    asked = []

    def get(path, *a, **k):
        if "answers_to_contact_id" in path and path.startswith("/groups"):
            asked.append(path)
            return None                                          # PostgREST: no such column
        return real(path, *a, **k)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    m = cm.load(LC)
    assert m is not None and m.group_links == {}
    assert len(asked) == 1                                       # the probe only, never the read
    _m, chain = _chain(lc, w["gloria"], sisters["id"])
    assert not any(s.get("for_group") for s, _ in chain)


def test_leaders_and_roles_carries_each_holders_person(lc):
    w = lc.who[LC]
    lib = cr.library(church(lc, LC))
    elders = next(r for r in lib["roles"] if r["key"] == "elders")
    marcus = next(h for h in elders["holders"] if h["contact_id"] == w["marcus"])
    assert marcus["answers_to_contact_id"] == w["jessica"] and marcus["answers_to_name"] == "Jessica McCloud"
    tanya = next(h for h in elders["holders"] if h["contact_id"] == w["tanya"])
    assert tanya["answers_to_contact_id"] is None and tanya["answers_to_name"] == ""


def test_the_map_is_on_for_every_church_by_default(monkeypatch):
    build(monkeypatch, filled=False)
    monkeypatch.delenv("CHURCH_MAP", raising=False)
    assert cm.mode() == "on" and cm.church_open(GRACE)
    monkeypatch.setenv("CHURCH_MAP", "owner")
    assert cm.church_open(LC) and not cm.church_open(GRACE)


def test_a_failed_groups_read_never_takes_the_map_down(lc, monkeypatch):
    w = lc.who[LC]
    sisters = _group(lc, "Sisters in the City")
    sisters["answers_to_contact_id"] = w["marcus"]
    assert cm.load(LC).group_links == {sisters["id"]: w["marcus"]}          # the file is in (the probe said yes)
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/groups?") else real(path, *a, **k))
    m = cm.load(LC)
    assert m is not None and m.group_links == {} and m.departments

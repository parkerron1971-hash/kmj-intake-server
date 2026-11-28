"""A ministry's leader is one of the church's people (worship_ministries.py;
mission M-8, Kevin 2026-11-28: "worship ministries' typed leaders become real
people from the members list. Match by email and name, and list any that
don't match").

  1. picking a person fills the name and email the link and emails read;
     someone from another church is refused; null lets go of the person
  2. the match list: by email (one person has it), else by the whole name;
     two people with the same email or name are never guessed; the rest are
     listed with why
  3. applying links every match and nothing else
  4. before the file: nothing asked of the new column; matching says not ready
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import sb_clients  # noqa: E402
import worship_ministries as wm  # noqa: E402
from test_worship_ministries import add, church  # noqa: E402,F401
from test_worship_show_router import BIZ, OTHER_BIZ, api  # noqa: E402,F401

DANA = "00000000-0000-4000-8000-00000000da01"
GLORIA = "00000000-0000-4000-8000-00000000da02"
SAM1 = "00000000-0000-4000-8000-00000000da03"
SAM2 = "00000000-0000-4000-8000-00000000da04"
ELSEWHERE = "00000000-0000-4000-8000-00000000da05"


@pytest.fixture
def people(church):
    db = church[0]
    db.t["contacts"] = [
        {"id": DANA, "business_id": BIZ, "name": "Dana Owens", "email": "dana@lovecity.org"},
        {"id": GLORIA, "business_id": BIZ, "name": "Gloria Hayes", "email": "Gloria@LoveCity.org"},
        {"id": SAM1, "business_id": BIZ, "name": "Sam Lee", "email": ""},
        {"id": SAM2, "business_id": BIZ, "name": "Sam  Lee", "email": "sam2@x.test"},
        {"id": ELSEWHERE, "business_id": OTHER_BIZ, "name": "Other Person", "email": "other@x.test"}]
    return church


def test_picking_a_person_fills_the_name_and_email(people):
    db, as_, _, _ = people
    r = as_("owner").post("/worship/ministries", json={"business_id": BIZ, "name": "Youth", "leader_contact_id": DANA})
    assert r.status_code == 200, r.text
    m = r.json()["ministry"]
    assert (m["leader_name"], m["leader_email"], m["leader_contact_id"]) == ("Dana Owens", "dana@lovecity.org", DANA)
    r = as_("owner").put(f"/worship/ministries/{m['id']}", json={"business_id": BIZ, "leader_contact_id": ELSEWHERE})
    assert r.status_code == 400 and "this church" in r.json()["detail"]
    r = as_("owner").put(f"/worship/ministries/{m['id']}", json={"business_id": BIZ, "leader_contact_id": None})
    assert r.status_code == 200 and r.json()["ministry"]["leader_contact_id"] is None
    assert r.json()["ministry"]["leader_name"] == "Dana Owens"           # the typed words stay


def test_the_match_list(people):
    db, as_, _, _ = people
    add(as_)                                                              # Gloria Hayes, gloria@lovecity.org
    add(as_, name="Men's ministry", leader_name="Dana Owens", leader_email="")
    add(as_, name="Choir", leader_name="Sam Lee", leader_email="")
    add(as_, name="Ushers", leader_name="Nobody Here", leader_email="nobody@x.test")
    r = as_("owner").get(f"/worship/ministries/leader-matches?business_id={BIZ}")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["ready"] is True
    assert {m["name"]: (m["contact"]["id"], m["by"]) for m in got["matched"]} == {
        "Women's ministry": (GLORIA, "email"), "Men's ministry": (DANA, "name")}
    why = {m["name"]: m["why"] for m in got["unmatched"]}
    assert why == {"Choir": "More than one of your people has that name.",
                   "Ushers": "No one in your members has that email or name."}
    assert as_("member").get(f"/worship/ministries/leader-matches?business_id={BIZ}").status_code == 403


def test_applying_links_every_match_and_nothing_else(people):
    db, as_, _, _ = people
    add(as_)
    add(as_, name="Ushers", leader_name="Nobody Here", leader_email="")
    r = as_("owner").post("/worship/ministries/leader-matches/apply", json={"business_id": BIZ})
    assert r.status_code == 200, r.text
    assert [m["name"] for m in r.json()["linked_now"]] == ["Women's ministry"]
    rows = {m["name"]: m.get("leader_contact_id") for m in db.t["worship_ministries"]}
    assert rows == {"Women's ministry": GLORIA, "Ushers": None}
    assert [m["name"] for m in r.json()["linked"]] == ["Women's ministry"] and r.json()["matched"] == []


def test_before_the_file(people, monkeypatch):
    db, as_, _, _ = people
    real = sb_clients.sb_get_as_service
    asked = []

    def get(path, *a, **k):
        if "leader_contact_id" in path:
            asked.append(path)
            return None
        return real(path, *a, **k)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    assert add(as_).status_code == 200
    listed = as_("owner").get(f"/worship/ministries?business_id={BIZ}").json()["ministries"]
    assert "leader_contact_id" not in listed[0]
    assert all(p.endswith("&limit=1") for p in asked)                    # the probe only
    assert as_("owner").get(f"/worship/ministries/leader-matches?business_id={BIZ}").json()["ready"] is False
    r = as_("owner").post("/worship/ministries", json={"business_id": BIZ, "name": "Youth", "leader_contact_id": DANA})
    assert r.status_code == 503

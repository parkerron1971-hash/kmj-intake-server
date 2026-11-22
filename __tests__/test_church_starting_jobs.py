"""The five starting jobs show only at a church that uses them
(church_job_defs.uses_presets).

Kevin, 2026-11-21: "I am with Elevation of grace and they are looking at the
same roles that we have made for our church. this is a problem". The five
(Office & Leadership, People & Care, Sunday & Serving, Media & Communications,
Treasurer) were written from Love City's own office and showed at every
church, with no way to change or remove them. Now:

  * a church with a login invited in one of them, or the platform owner's
    own church, keeps all five exactly as before
  * every other church sees only its own jobs: the invite's list, the jobs
    list, a person's sheet, and a login whose areas happen to match one
  * a hidden one can't be picked by key (invite, Logins & areas, a sheet),
    and a church may make its own job by the same title
  * Chief's setup questions propose jobs the church would make instead
  * a read that fails shows them (the list as it always was)
  * CHURCH_STARTING_JOBS=on shows them at every church again

People and churches here are made up."""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_duties as cd  # noqa: E402
import church_job_defs as cj  # noqa: E402
import sb_clients  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_church_follow_up import BIZ, OWNER  # noqa: E402
from test_church_structure import _biz, _draft, _fresh, _p, _seat, db  # noqa: E402,F401

PRESET_LABELS = {v["label"] for v in ca.LANES.values()}
CALEB = "c3000000-0000-4000-8000-000000000003"
PEOPLE_CARE_AREAS = ["people_care", "kids_youth", "groups_classes"]


@pytest.fixture(autouse=True)
def _used(monkeypatch):
    monkeypatch.setenv("CHURCH_STARTING_JOBS", "used")
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: False)
    cj._USES_CACHE.clear()
    yield
    cj._USES_CACHE.clear()


def test_a_church_that_never_used_the_five_sees_only_its_own_jobs(db):
    assert cj.uses_presets(BIZ) is False
    assert cj.presets_for(BIZ) == [] and cj.jobs(BIZ) == []
    assert ca.lanes_view(BIZ) == []
    # A login whose picked areas are exactly People & Care isn't labelled with it.
    assert ca.lane_of("manager", PEOPLE_CARE_AREAS, BIZ) is None
    assert ca.lane_of("manager", PEOPLE_CARE_AREAS) == "people_care"     # without a church, as always
    # A hidden one can't be picked by its key, here or on a sheet.
    with pytest.raises(HTTPException) as e:
        ca.lane("treasurer", BIZ)
    assert e.value.status_code == 400
    assert cj.find(BIZ, "treasurer") is None
    # A login that once held one keeps its title.
    assert cj.label_of(BIZ, "treasurer") == "Treasurer"


def test_a_church_may_make_its_own_job_by_a_starting_jobs_title(db):
    made = cj.create(_biz(db), {"label": "Treasurer", "does": "Keeps the books", "role": "admin"}, OWNER, "owner")
    job = made["job"]
    assert job["custom"] and job["label"] == "Treasurer" and job["key"] not in ca.LANES
    assert [j["label"] for j in cj.jobs(BIZ)] == ["Treasurer"]
    assert [lv["label"] for lv in ca.lanes_view(BIZ)] == ["Treasurer"]
    assert ca.lane(job["key"], BIZ)["custom"] is True
    renamed = cj.update(_biz(db), job["key"], {"label": "Financial Secretary", "role": "admin"}, OWNER, "owner")
    assert renamed["job"]["label"] == "Financial Secretary"


@pytest.mark.parametrize("status, keeps", [("active", True), ("invited", True), ("revoked", False)])
def test_a_church_with_a_login_in_one_keeps_all_five(db, status, keeps):
    db.t["business_users"].append(_seat(CALEB, "manager", "caleb@hopechapel.example", "Caleb Stone",
                                        lane="people_care", areas=PEOPLE_CARE_AREAS, status=status))
    assert cj.uses_presets(BIZ) is keeps
    if keeps:
        assert [j["key"] for j in cj.jobs(BIZ)] == list(ca.LANES)
        assert [lv["key"] for lv in ca.lanes_view(BIZ)] == list(ca.LANES)
        assert ca.lane("treasurer", BIZ)["label"] == "Treasurer"
        assert ca.lane_of("manager", PEOPLE_CARE_AREAS, BIZ) == "people_care"
        with pytest.raises(HTTPException) as e:          # the title stays the starting job's
            cj.create(_biz(db), {"label": "Treasurer", "role": "admin"}, OWNER, "owner")
        assert e.value.status_code == 409
    else:
        assert cj.jobs(BIZ) == []


def test_the_platform_owners_church_keeps_them(db, monkeypatch):
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: True)
    assert cj.uses_presets(BIZ) is True and len(cj.jobs(BIZ)) == 5


def test_a_read_that_fails_shows_them_and_is_not_kept(db, monkeypatch):
    real = sb_clients.sb_get_as_service

    def broken(path, *a, **kw):
        if path.startswith("/business_users") and "lane=in." in path:
            return None
        return real(path, *a, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", broken)
    assert cj.uses_presets(BIZ) is True
    assert BIZ not in cj._USES_CACHE
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    assert cj.uses_presets(BIZ) is False


def test_the_switch_on_shows_them_at_every_church(db, monkeypatch):
    monkeypatch.setenv("CHURCH_STARTING_JOBS", "on")
    assert cj.uses_presets(BIZ) is True and len(ca.lanes_view(BIZ)) == 5


SMALL = {
    "leads": "pastor",
    "money": {"counts": ["Dana Reed"], "deposits": None, "books": "Alma Price"},
    "bodies": [], "staff": "volunteers", "guests": "Maria Lopez",
    "people": [
        {"name": "Alma Price", "title": "Financial Secretary", "does": "keeps the books and pays the bills",
         "email": "alma@hopechapel.example"},
        {"name": "Ruth Hale", "title": "Church Administrator", "does": "runs the office"},
        {"name": "Maria Lopez", "does": "calls every guest and runs the prayer chain"},
    ],
}


@pytest.mark.parametrize("leads", ["pastor", "pastor_board", "elders", "staff"])
def test_setup_questions_propose_only_jobs_the_church_would_make(db, leads):
    d = _draft(db, {**SMALL, "leads": leads})
    for j in d["jobs"]:
        assert j["custom"] and not j["exists"] and j["key"] is None, j
        kept = cj.clean(j, "owner")                      # the church's own job save takes it as it is
        # An Admin job is saved with no areas and read as None: it sees the whole church either way.
        assert kept["role"] == j["role"] and (kept["areas"] or None) == (j["areas"] or None)
        assert kept["duties"] == j["duties"]
    labels = [j["label"] for j in d["jobs"]]
    assert not {"Office & Leadership", "People & Care", "Sunday & Serving", "Media & Communications"} & set(labels)
    alma = _p(d, "Alma Price")
    assert alma["role"] == "admin" and alma["job_label"] == "Financial Secretary" and alma["job_key"] is None
    assert alma["duties"] == cd.STARTER["treasurer"]
    ruth = _p(d, "Ruth Hale")
    assert ruth["job_label"] == "Church Administrator" and ruth["role"] == "manager"
    assert set(ruth["areas"]) == set(ca.LANES["office_leadership"]["areas"])


def test_setup_questions_still_use_the_five_where_the_church_does(db):
    db.t["business_users"].append(_seat(CALEB, "manager", "caleb@hopechapel.example", "Caleb Stone",
                                        lane="people_care", areas=PEOPLE_CARE_AREAS))
    d = _draft(db, SMALL)
    assert {"Treasurer", "Office & Leadership", "People & Care"} <= {j["label"] for j in d["jobs"]}
    assert _p(d, "Alma Price")["job_key"] == "treasurer"
    assert _p(d, "Ruth Hale")["job_label"] == "Office & Leadership"

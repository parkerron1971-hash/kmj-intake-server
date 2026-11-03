"""The ready-made directory (docs/CHURCH_LEADERS_STEP2.md §1.1, §2.1-§2.3, §2.5; §7 B4a).

Role ready-mades are built at import from church_roles.TYPES, so every row
is one and carries the backfill's switches; six more roles, fourteen
departments and six shapes sit beside them. Each is pinned by version and
content hash. Search folds case, punctuation and a plural, ranks an exact
title, then a word of the name, then a word like one, then what it says, the
church's own tradition first, and decides nothing. The two GET routes are
behind CHURCH_MAP for a manager seat and up, and only read."""
from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_duties as cd  # noqa: E402
import church_map as cm  # noqa: E402
import church_roles as cr  # noqa: E402
import church_templates as ct  # noqa: E402
import sb_clients  # noqa: E402
from church_three import GRACE, LOVE_CITY as LC, NEW_HOPE as NH, RIVERSIDE as RV, build  # noqa: E402
from test_church_map_vectors import VECTORS  # noqa: E402
from test_church_map_writes import Office  # noqa: E402

K = (*cr.SWITCHES, "made_for")


def _with(key, flips=None):
    return {**ct.ROLES[key], **(flips or {})}


# ─── The catalog ──────────────────────────────────────────────────────

def test_every_tradition_row_is_a_ready_made_with_the_backfills_switches():
    with open(VECTORS, encoding="utf-8") as f:
        v = {c["church"]: c for c in json.load(f)["churches"]}
    n = 0
    for t in cr.TYPE_ORDER:
        for r in v[f"type:{t}"]["roles"]:
            got = ct.ROLES[f"{t}.{r['key']}"]
            assert ({k: got[k] for k in K}, got["handles"], got["title"], got["job"]) == \
                ({k: r[k] for k in K}, r["handles"], r["title"], r["job"]), (t, r["key"])
            n += 1
    assert n == 101 == sum(len(cr.TYPES[t]["rows"]) for t in cr.TYPE_ORDER)
    assert len({x["title"].casefold() for x in ct.ROLES.values() if x["tradition"] != ct.ANY}) == 69


def test_the_six_roles_no_tradition_names_are_on_their_jobs_switches():
    jobs = {k[4:]: t["job"] for k, t in ct.ROLES.items() if k.startswith("any.")}
    assert jobs == {"media_lead": "team", "facilities_lead": "team", "outreach_lead": "welcome",
                    "mens_lead": "ministry", "womens_lead": "ministry", "missions_lead": "ministry"}
    for k, job in jobs.items():
        t = ct.ROLES[f"any.{k}"]
        assert {s: t[s] for s in cr.SWITCHES} == cr.JOBS[job]["switches"] and t["made_for"] == [] and t["words"]
    assert (len(ct.ROLES), len(ct.DEPARTMENTS), len(ct.SHAPES)) == (107, 14, 6)


def test_each_department_has_an_area_an_office_helper_and_a_leader_who_leads_everywhere():
    assert [d["name"] for d in ct.DEPARTMENTS.values()] == [
        "Worship & Arts", "Media & Production", "Youth", "Children", "Prayer", "Care & Visitation",
        "Welcome & Guest Services", "Ushers & Greeters", "Outreach & Evangelism", "Classes & Groups",
        "Men’s Ministry", "Women’s Ministry", "Missions", "Facilities & Safety"]
    for d in ct.DEPARTMENTS.values():
        assert d["area"] in ca.AREAS and d["support_duty"] in cd.CATALOG and d["rhythm"] and d["words"]
        assert d["units"]["space"] in (None, "youth", "kids") and (d["units"]["serve"] or d["units"]["group"])
        for t in cr.TYPE_ORDER:
            assert _with(d["leader"][t], d["lead_can"])["can_lead"] is True, (d["key"], t)
            assert ct.ROLES[d["overseer"][t]]["can_oversee"] is True
    assert {d["key"]: d["support_duty"] for d in ct.DEPARTMENTS.values()}["youth"] == "youth"
    assert ct.DEPARTMENTS["youth"]["leader"] == {
        "nondenom": "nondenom.youth_pastor", "baptist": "baptist.youth_minister", "cogic": "cogic.ypww_president",
        "ame": "ame.ypd_director", "presby": "presby.christian_ed", "coc": "coc.youth_minister",
        "liturgical": "liturgical.religious_ed", "other": "nondenom.youth_pastor"}


def test_in_every_shape_each_overseer_oversees_each_leader_leads_and_no_money_level_is_set():
    for s in ct.SHAPES.values():
        assert s["traditions"] and set(s["traditions"]) <= set(cr.TYPE_ORDER) and s["families"] > 0
        assert not any(k in json.dumps(s) for k in cm.LEVELS)
        for t in cr.TYPE_ORDER:
            flips = dict(ct.seats_of(s, t))
            for d in s["departments"]:
                ov, ld = ct.SEATS[d["overseer"]][t], ct.DEPARTMENTS[d["department"]]["leader"][t]
                assert _with(ov, flips[ov])["can_oversee"] is True, (s["key"], t, d)
                assert _with(ld, flips[ld])["can_lead"] is True, (s["key"], t, d)
            assert all(ct.SEATS[x][t] in flips for x in (*s["pastor_yes"], *s["office_overseer"]))
    deacons = next(r for r in ct.SHAPES["pastor_deacons"]["roles"] if r["seat"] == "deacons")
    assert deacons["flips"] == {"can_shepherd": True, "can_oversee": True}, "as Grace's fixture flips them"
    elders = next(r for r in ct.SHAPES["multi_staff"]["roles"] if r["seat"] == "elders")
    assert elders["flips"] == {"can_board_yes": True}, "the board's yes, a switch: never a level"
    grace = ct.card(ct.SHAPES["pastor_deacons"], "baptist")
    assert grace["fits_you"] and grace["shepherds"] == ["Pastor", "Deacon Board"]
    assert next(r for r in grace["roles"] if r["title"] == "Deacon Board")["can"] == \
        "shepherds families, can oversee a department"


def test_elder_led_at_a_church_of_christ_names_no_pastor_and_the_elders_are_its_top():
    titles = [ct.ROLES[k]["title"] for k, _f in ct.seats_of(ct.SHAPES["elder_led"], "coc")]
    assert not [x for x in titles if "pastor" in x.casefold()] and len(titles) == len(set(titles))
    c = ct.card(ct.SHAPES["elder_led"], "coc")
    assert (c["pastor_yes"], c["office_overseer"], c["fits_you"]) == (["Elders (Shepherds)"], ["Elders (Shepherds)"],
                                                                      True)
    assert {d["overseer"] for d in c["departments"]} == {"Elders (Shepherds)"}


def test_every_ready_made_carries_its_pinned_version_and_new_content_needs_a_new_pin(monkeypatch):
    assert set(ct.VERSIONS) == set(ct.ALL) and ct.stale() == []
    assert all(t["version"] == ct.VERSIONS[k][0] for k, t in ct.ALL.items())
    monkeypatch.setitem(ct.ROLES["baptist.usher_board"], "title", "Head usher")
    monkeypatch.setitem(ct.DEPARTMENTS["youth"], "rhythm", "Whenever.")
    assert ct.stale() == ["youth", "baptist.usher_board"], "content moved and the pin didn't"


# ─── Search (§2.3) ────────────────────────────────────────────────────

def test_a_query_is_folded_its_punctuation_out_and_a_plural_dropped():
    assert ct.words("Greeters!") == ["greeter"] and ct.words("CHILDREN’S Director") == ["children", "director"]
    assert ct.words("Classes & Ministries of the Church") == ["class", "ministry"]
    assert [c["key"] for c in ct.search("usher board PRESIDENT.", "role")] == ["baptist.usher_board"]
    assert ct.search("usher board president", "role")[0]["match"] == "title"


def test_greeter_finds_the_four_welcome_titles_the_churchs_own_tradition_first():
    lc = ct.search("greeter", "role", "nondenom")
    assert [c["title"] for c in lc] == ["Welcome Team lead", "Usher Board president", "Hospitality ministry lead",
                                        "Hospitality lead"]
    assert {c["match"] for c in lc} == {"like"}
    assert (lc[0]["key"], lc[0]["also"]) == ("nondenom.welcome_lead", ["Presbyterian", "Church of Christ",
                                                                      "Something else"])
    grace = ct.search("Greeters", "role", "baptist")
    assert [c["title"] for c in grace][:2] == ["Usher Board president", "Hospitality ministry lead"]
    assert sorted(c["title"] for c in grace) == sorted(c["title"] for c in lc)
    # Each says what it does, who it answers to, what it sees and what it can do.
    u = grace[0]
    assert u["does"] == cr.JOBS["team"]["definition"].format(title="Usher Board president")
    assert (u["answers_to"], u["sees"], u["never"]) == ("Pastor", cr.JOBS["team"]["sees"], cr.JOBS["team"]["never"])
    assert u["can"] == "leads (the leaders room)" and u["switches"]["can_lead"] is True
    every = ct.search("greeter", "", "nondenom")
    assert [(c["kind"], c["match"]) for c in every[:2]] == [("department", "name"), ("department", "like")]
    assert every[0]["name"] == "Ushers & Greeters" and every[0]["office_help"]["key"] == "serve_schedule"


def test_a_title_comes_before_its_words_before_a_word_like_one_before_what_it_says():
    got = [(c["match"], c["title"], c["tradition"]["key"]) for c in ct.search("deacons", "role", "nondenom")]
    assert got == [("title", "Deacons", "nondenom"), ("title", "Deacons", "coc"), ("name", "Deacon Board", "baptist"),
                   ("name", "Deacon (ordained)", "liturgical")], "two jobs, two cards"
    kids = ct.search("kids", "role", "nondenom")
    assert kids[0]["title"] == "Children’s Director" and {c["match"] for c in kids} == {"like"}
    meals = ct.search("meals", "", "nondenom")
    assert (meals[0]["name"], meals[0]["match"]) == ("Care & Visitation", "name")
    assert {c["match"] for c in meals[1:]} == {"says"} and "Care team" in [c.get("title") for c in meals]


def test_the_churchs_own_tradition_comes_first_and_an_empty_query_lists_a_kind():
    ame = ct.search("prayer leader", "role", "ame")
    assert (ame[0]["tradition"]["key"], ame[0]["also"]) == ("ame", ["Presbyterian", "Church of Christ",
                                                                   "Something else"])
    shapes = ct.search("", "shape", "coc")
    assert [c["key"] for c in shapes][0] == "elder_led" and len(shapes) == 6 and shapes[0]["match"] == ""
    assert len(ct.search("", "department")) == 14
    assert len(ct.search("", "role")) == 70 + 6, "one card a title and job: 69 titles, Deacons on two jobs"
    assert ct.search("money", "role", "baptist")[0]["title"] == "Trustees"


def test_search_reads_and_writes_nothing(monkeypatch):
    def no(*a, **k):
        raise AssertionError("search touched the database")
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", no)
    assert ct.search("youth", "", "baptist") and ct.card(ct.SHAPES["multi_staff"], "presby")


# ─── The routes (§2.5) ────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    return build(monkeypatch)


def _get(o, biz, path="", **q):
    qs = "".join(f"&{k}={v}" for k, v in q.items())
    return o.c.get(f"/church/map/templates{path}?business_id={biz}{qs}")


def test_the_directory_is_the_maps_for_a_manager_seat_and_up(db, monkeypatch):
    o = Office(db)
    r = _get(o.as_(LC, "naiya"), LC, q="greeter", kind="role")
    assert r.status_code == 200, "a manager reads it"
    assert r.json()["tradition"] == {"key": "nondenom", "label": "Non-denominational"}
    assert r.json()["results"][0]["title"] == "Welcome Team lead"
    assert _get(o, LC, kind="units").status_code == 400
    assert _get(o, LC, "/role/nondenom.nobody").status_code == 404 and _get(o, LC, "/team/youth").status_code == 404
    assert _get(o.as_(GRACE), LC).status_code == 404, "no seat here: the stranger's 404"
    monkeypatch.setenv("CHURCH_MAP", "owner")
    assert _get(o.as_(GRACE), GRACE).status_code == 404, "closed for this login"
    assert _get(o.as_(LC), LC).status_code == 200, "open for the platform owner's"


def test_before_step_2s_file_the_directory_is_a_503(monkeypatch):
    db = build(monkeypatch, migrated2=False)
    r = _get(Office(db).as_(LC), LC, q="youth")
    assert (r.status_code, r.json()["detail"]) == (503, "The ready-made list isn’t set up yet. Try again later.")


def _here(o, biz, kind, key):
    r = _get(o.as_(biz), biz, f"/{kind}/{key}")
    assert r.status_code == 200, r.json()
    return r.json()


def _names(h, side):
    return [(x["kind"], x["name"]) + ((x["yours"],) if side == "yours" else ()) for x in h[side]]


def test_what_adopting_would_add_says_what_is_already_the_churchs_own(db):
    o = Office(db)
    h = _here(o, LC, "role", "nondenom.youth_pastor")["here"]
    assert (_names(h, "yours"), h["new"], h["waits"]) == ([("role", "Youth Pastor", "Youth Pastor")], [], [])
    h = _here(o, NH, "role", "nondenom.youth_pastor")["here"]
    assert _names(h, "yours") == [("role", "Youth Pastor", "Youth Director")], "seeded from the row, retitled"
    h = _here(o, LC, "role", "baptist.usher_board")["here"]
    assert (_names(h, "new"), h["yours"]) == ([("role", "Usher Board president")], [])
    got = _here(o, NH, "department", "prayer")
    assert got["ready_made"]["leader"]["title"] == "Intercessor leader"
    h = got["here"]
    assert (_names(h, "new"), _names(h, "yours")) == ([("department", "Prayer")],
                                                     [("role", "Intercessor leader", "Intercessor leader")])
    assert [w["line"] for w in h["waits"]] == ["Intercessor leader: leads off → on"]
    h = _here(o, LC, "department", "prayer")["here"]
    assert h["new"] == [] and h["waits"] == [], "Love City's Prayer and its leader's switch are already there"


def test_a_shape_here_lists_each_role_and_department_and_what_would_wait(db):
    h = _here(Office(db), GRACE, "shape", "pastor_deacons")["here"]
    assert ("role", "Deacon Board", "Deacon Board") in _names(h, "yours") and ("role", "Children’s Director") in \
        _names(h, "new")
    assert ("department", "Youth", "Youth") in _names(h, "yours") and ("department", "Care & Visitation") in \
        _names(h, "new")
    assert [w["line"] for w in h["waits"]] == [
        "Prayer ministry leader: leads off → on",
        "Your church: who gives the pastor’s yes the usual → Pastor",
        "Your church: who oversees the office the usual → Pastor"], "Grace's deacons already shepherd and oversee"
    lc = [(w["line"], w["money"]) for w in _here(Office(db), LC, "shape", "multi_staff")["here"]["waits"]]
    assert ("Elders: gives the board’s yes on money off → on", True) in lc, "the owner's yes, in B4b"
    nh = _here(Office(db), NH, "shape", "multi_staff")["here"]["waits"]
    assert not [w for w in nh if w["money"]], "New Hope's elders already give the board's yes"


def test_at_riverside_the_directory_reads_and_seeds_nothing(db, monkeypatch):
    calls = []
    for n in ("post", "patch", "delete"):
        fn = getattr(sb_clients, f"sb_{n}_as_service")
        monkeypatch.setattr(sb_clients, f"sb_{n}_as_service", lambda *a, _fn=fn, **k: calls.append(a[0]) or _fn(*a, **k))
    o = Office(db)
    s = _get(o.as_(RV), RV, q="", kind="shape").json()
    h = _here(o, RV, "shape", "bishop_led")
    assert s["tradition"]["key"] == "ame" and s["results"][0]["fits_you"], "its name's tradition, AME"
    assert h["here"]["yours"] == [] and ("role", "Stewards") in _names(h["here"], "new")
    assert calls == [], "a read only"
    assert not [r for t in ("church_role_settings", "church_role_defs") for r in db.t[t] if r["business_id"] == RV]

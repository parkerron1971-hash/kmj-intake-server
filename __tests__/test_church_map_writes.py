"""The leaders map's writes and routes (church_map.py, church_map_router.py),
docs/CHURCH_LEADERS_MAP.md §3 and §5 PR 5.

Each write's rules, and that a refusal writes nothing; a conflict the
database catches is the same plain 400, and a failed write is a 503, never a
success; archiving lets go of what hung from a department; who a holder
answers to; the settings (only the owner changes money, and a change is
stamped and logged); the map read back with its gaps; propose() writes
nothing; the routes' switch, seats and 503s; and each church's map entered
through the routes lands in the same tables as church_three's direct write,
so step 4 can enter Love City's real map this way."""
from __future__ import annotations

import copy
import os
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_duties as cd  # noqa: E402
import church_map as cm  # noqa: E402
import church_map_router  # noqa: E402
import church_roles as cr  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from church_three import CHURCHES, GRACE, LOVE_CITY as LC, NAMES, OWNER_EMAIL, build, church  # noqa: E402

K = (*cr.SWITCHES, "made_for")


def _role(db, biz, key):
    return next(d for d in db.t["church_role_defs"] if d["business_id"] == biz and d["key"] == key)


def _dept(db, biz, name):
    return next(d for d in db.t["church_departments"] if d["business_id"] == biz and d["name"] == name)


def _owner(db, biz):
    return church(db, biz)["owner_id"]


@pytest.fixture
def lc(monkeypatch):
    return build(monkeypatch)


def _refused(fn, *a, code=400):
    with pytest.raises(HTTPException) as e:
        fn(*a)
    assert e.value.status_code == code, e.value.detail
    return str(e.value.detail)


def _save(db, body, biz=LC):
    return cm.save_department(church(db, biz), body, _owner(db, biz))


# ─── A department's rules ─────────────────────────────────────────────

RULES = [
    (lambda w, g: {"leader_contact_id": w["gloria"]}, "Gloria Hunt doesn’t hold a role that leads"),
    (lambda w, g: {"leader_contact_id": w["iris"]}, "Iris Bell doesn’t hold a role that leads"),
    (lambda w, g: {"overseer_contact_id": w["tasha"]}, "doesn’t hold a role that can oversee a department"),
    (lambda w, g: {"leader_contact_id": w["andre"], "overseer_contact_id": w["andre"]}, "are two people"),
    (lambda w, g: {"support_duty": "bake_sale"}, "one of the office’s duties"),
    (lambda w, g: {"area": "garden"}, "one of the eight areas"),
    (lambda w, g: {"status": "paused"}, "a draft, active or archived"),
    (lambda w, g: {"sort": 1000}, "0 to 999"),
    (lambda w, g: {"units": [{"kind": "serve_option", "label": "Choir"}]}, "“Choir” isn’t a team on your Serve card"),
    (lambda w, g: {"units": [{"kind": "check_line", "label": "Roof Fund"}]}, "isn’t one of your budget lines"),
    (lambda w, g: {"units": [{"kind": "space", "label": "adults"}]}, "A space is youth or kids"),
    (lambda w, g: {"units": [{"kind": "closet", "label": "x"}]}, "isn’t something a department can hold"),
    (lambda w, g: {"units": [{"kind": "group", "ref": "nope"}]}, "That group isn’t valid"),
    (lambda w, g: {"units": [{"kind": "space", "label": "Youth"}]}, "youth already hangs from Youth"),
    (lambda w, g: {"units": [{"kind": "serve_option", "label": "hospitality team"}]},
     "Hospitality Team already hangs from Outreach & Welcome"),
    (lambda w, g: {"name": "  youth "}, "There’s already a department called Youth"),
    (lambda w, g: {"name": ""}, "Name the department"),
    # Another church's person, group and role.
    (lambda w, g: {"leader_contact_id": g["yvette"]}, "That leader isn’t one of this church’s people"),
    (lambda w, g: {"units": [{"kind": "group", "ref": g["group"]}]}, "That group isn’t one of this church’s"),
    (lambda w, g: {"units": [{"kind": "role", "ref": g["deacons"]}]}, "That role isn’t one of this church’s"),
]


@pytest.mark.parametrize("make,says", RULES, ids=[s[:40] for _m, s in RULES])
def test_each_rule_refuses_with_a_plain_400_and_writes_nothing(lc, make, says):
    g = dict(lc.who[GRACE], group=next(x["id"] for x in lc.t["groups"] if x["business_id"] == GRACE),
             deacons=_role(lc, GRACE, "deacons")["id"])
    body = {"name": "Kitchen", **make(lc.who[LC], g)}
    before = copy.deepcopy((lc.t["church_departments"], lc.t["church_department_units"]))
    assert says in _refused(_save, lc, body)
    assert (lc.t["church_departments"], lc.t["church_department_units"]) == before


def test_a_department_saves_and_changes_only_what_it_names(lc):
    w = lc.who[LC]
    youth_line = {"kind": "check_line", "label": "youth"}          # Love City's budget lines are its ministries
    made = _save(lc, {"name": "Care", "leader_contact_id": w["andre"], "status": "draft", "source": "chief",
                      "units": [youth_line, {"kind": "space", "label": "kids"}]})
    assert (made["status"], made["source"], made["leader_contact_id"]) == ("draft", "chief", w["andre"])
    assert sorted(u["label"] for u in made["units"]) == ["Youth", "kids"], "the church's own spelling"
    youth = _dept(lc, LC, "Youth")
    group = next(g["id"] for g in lc.t["groups"] if g["business_id"] == LC and g["name"] == "Youth")
    saved = _save(lc, {"id": youth["id"], "leader_contact_id": None, "units": [
        {"kind": "serve_option", "label": "Youth Ministry (YWD)"}, {"kind": "group", "ref": group}]})
    assert saved["leader_contact_id"] is None and saved["overseer_contact_id"] == w["andre"], "the rest is kept"
    assert sorted(u["kind"] for u in saved["units"]) == ["group", "serve_option"]
    assert sorted(u["kind"] for u in lc.t["church_department_units"] if u["department_id"] == youth["id"]) == \
        ["group", "serve_option"], "the youth space came off"
    assert _save(lc, {"name": "Teens", "units": [{"kind": "space", "label": "youth"}]})["units"][0]["label"] == "youth"


def test_a_conflict_the_database_catches_is_the_same_400_and_a_failed_write_a_503(lc, monkeypatch):
    real = sb_clients.sb_post_as_service
    youth = _dept(lc, LC, "Youth")

    def racing(path, body, prefer=None, **k):
        if path.startswith("/church_department_units"):     # someone hung it meanwhile; the index refuses
            lc.t["church_department_units"].append({
                "id": "u-race", "business_id": LC, "department_id": youth["id"], "kind": "space", "group_id": None,
                "role_id": None, "board_id": None, "worship_ministry_id": None, "label": "kids"})
            return None
        return real(path, body, prefer, **k)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", racing)
    n = len(lc.t["church_departments"])
    assert _refused(_save, lc, {"name": "Kids", "units": [{"kind": "space", "label": "kids"}]}) == \
        "kids already hangs from Youth"
    assert len(lc.t["church_departments"]) == n, "a new department never stays half made"
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda *a, **k: None)
    assert _refused(_save, lc, {"id": youth["id"], "sort": 5}, code=503) == "That didn’t save. Try again."


def test_archiving_lets_go_of_what_hung_from_it(lc):
    youth = _dept(lc, LC, "Youth")
    out = cm.archive_department(church(lc, LC), youth["id"], _owner(lc, LC))
    assert (out["status"], out["units"]) == ("archived", [])
    assert not [u for u in lc.t["church_department_units"] if u["department_id"] == youth["id"]]
    assert [d["name"] for d in cm.load(LC).departments] == ["Prayer", "Outreach & Welcome"]
    again = _save(lc, {"name": "Youth", "units": [{"kind": "space", "label": "youth"}]})
    assert again["id"] != youth["id"], "its name and its things are free"
    assert cm.archive_department(church(lc, LC), youth["id"], _owner(lc, LC))["status"] == "archived", "again is fine"
    for other in (_dept(lc, GRACE, "Youth")["id"], "5d000000-0000-4000-8000-000000000000"):
        assert _refused(cm.archive_department, church(lc, LC), other, None, code=404) == "That department isn’t here"


# ─── Who a holder answers to ──────────────────────────────────────────

def test_who_a_holder_answers_to(lc):
    w = lc.who[LC]
    holder = {h["contact_id"]: h for h in lc.t["church_leader_roles"] if h["business_id"] == LC}
    biz = church(lc, LC)
    assert cm.set_answers_to(biz, holder[w["tanya"]]["id"], w["jessica"])["answers_to_contact_id"] == w["jessica"]
    assert cm.set_answers_to(biz, holder[w["marcus"]]["id"], None)["answers_to_contact_id"] is None
    assert "themselves" in _refused(cm.set_answers_to, biz, holder[w["tanya"]]["id"], w["tanya"])
    assert "Give them a role first" in _refused(cm.set_answers_to, biz, holder[w["tanya"]]["id"], w["gloria"])
    assert "Give them a role first" in _refused(cm.set_answers_to, biz, holder[w["tanya"]]["id"],
                                                lc.who[GRACE]["samuel"]), "another church's person"
    grace_holder = next(h["id"] for h in lc.t["church_leader_roles"] if h["business_id"] == GRACE)
    assert _refused(cm.set_answers_to, biz, grace_holder, w["kevin"], code=404) == "That person doesn’t hold that role here"


# ─── The settings ─────────────────────────────────────────────────────

def test_only_the_owner_changes_money_and_a_change_is_stamped_and_logged(lc, capsys):
    biz, owner = church(lc, GRACE), _owner(lc, GRACE)
    st = next(s for s in lc.t["church_role_settings"] if s["business_id"] == GRACE)
    st["map_by"] = None
    assert _refused(cm.save_settings, biz, {"pastor_from_cents": 30_000}, "u-admin", "admin", code=403) == \
        "Only the owner changes the church’s money levels."
    assert cm.save_settings(biz, {"pastor_from_cents": 20_000}, "u-admin", "admin")["changed"] is False, \
        "the same level again is no change"
    for body, says in (({"board_over_cents": 10_000}, "at or above the pastor’s"),
                       ({"pastor_from_cents": 10_000_001}, "$0 to $100,000"), ({"board_over_cents": -1}, "$0"),
                       ({"pastor_yes_roles": [_role(lc, LC, "pastor")["id"]]}, "this church’s own roles"),
                       ({"office_overseer_roles": ["x"]}, "That role isn’t valid")):
        assert says in _refused(cm.save_settings, biz, body, owner, "owner")
    assert capsys.readouterr().out == "" and st["map_by"] is None, "nothing changed, nothing logged"
    out = cm.save_settings(biz, {"pastor_from_cents": 30_000, "board_over_cents": None,
                                 "office_overseer_roles": []}, owner, "owner")
    assert out["changed"] and out["settings"]["pastor_from_cents"] == 30_000
    assert (st["board_over_cents"], st["office_overseer_roles"], st["map_by"]) == (None, [], owner) and st["map_at"]
    line = capsys.readouterr().out
    assert line.startswith(f"[church_map] settings {GRACE} by {owner}: pastor_from_cents 20000 -> 30000; "
                           "board_over_cents 100000 -> None; office_overseer_roles None -> []")
    pick = _role(lc, GRACE, "pastor")["id"]
    assert cm.save_settings(biz, {"pastor_yes_roles": [pick, pick]}, "u-admin", "admin")["settings"][
        "pastor_yes_roles"] == [pick], "an admin picks the roles"


# ─── The map read back, and its gaps ──────────────────────────────────

def test_the_map_reads_back_by_name_and_each_gap_shows(lc):
    w, biz = lc.who[LC], church(lc, LC)
    v = cm.view(biz)
    assert v["gaps"] == [], "the fixture's map is whole"
    youth = next(d for d in v["departments"] if d["name"] == "Youth")
    assert (youth["leader"]["name"], youth["overseer"]["name"]) == ("Yolanda Reed", "Andre Wallace")
    assert youth["support_duty"]["label"] == cd.CATALOG["youth"]["label"]
    assert youth["support_duty"]["holders"][:2] == [{"user_id": _owner(lc, LC), "name": "Pastor Kevin"},
                                                   {"user_id": lc.who[LC]["minnie@"], "name": "Minnie Tatum"}]
    assert sorted((u["kind"], u["name"]) for u in youth["units"]) == [
        ("group", "Youth"), ("serve_option", "Youth Ministry (YWD)"), ("space", "youth")]
    assert [(x["name"], x["answers_to"]["name"]) for x in v["answers_to"]] == [("Marcus Taylor", "Jessica McCloud")]
    assert next(r for r in v["roles"] if r["key"] == "evangelists")["switches"]["oversee"] is True
    assert v["settings"]["platform"] == {"pastor_from_cents": 50_000, "board_over_cents": 250_000}
    # Now each gap.
    next(h for h in lc.t["church_leader_roles"] if h["contact_id"] == w["paul"])["status"] = "declined"
    cr.update_role(LC, _role(lc, LC, "evangelists")["id"], {"can_oversee": False})
    _dept(lc, LC, "Youth")["leader_contact_id"] = None
    _dept(lc, LC, "Prayer")["support_duty"] = None
    team = next(f for f in next(x for x in lc.t["intake_forms"] if x["business_id"] == LC)["fields"]
                if f["name"] == "team")
    team["options"] = [o for o in team["options"] if o != "Hospitality Team"]
    next(g for g in lc.t["groups"] if g["business_id"] == LC and g["name"] == "Youth")["active"] = False
    _save(lc, {"id": _dept(lc, LC, "Prayer")["id"], "units": [{"kind": "check_line", "label": "Sisters in the City"}]})
    next(g for g in lc.t["groups"] if g["name"] == "Sisters in the City")["active"] = False   # the line goes with it
    got = {(next(d["name"] for d in v["departments"] if d["id"] == x["department_id"]), x["kind"], x["text"])
           for x in cm.view(biz)["gaps"]}
    assert got == {
        ("Prayer", "overseer_off", "Paul Mensah no longer holds a role that can oversee."),
        ("Prayer", "no_duty", "No office duty is named to help Prayer."),
        ("Prayer", "unit_gone", "“Sisters in the City” is no longer one of the budget lines."),
        ("Outreach & Welcome", "overseer_off", "Eve Hall no longer holds a role that can oversee."),
        ("Outreach & Welcome", "unit_gone", "“Hospitality Team” is no longer on the Serve card."),
        ("Youth", "no_leader", "Youth has no leader."),
        ("Youth", "unit_gone", "A group that hung from Youth is gone.")}


def test_propose_writes_nothing(lc, monkeypatch):
    def write(*a, **k):
        raise AssertionError("propose wrote")
    for name in ("post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", write)
    before = copy.deepcopy(lc.t)
    assert cm.propose(LC) == {} and lc.t == before


# ─── The routes ───────────────────────────────────────────────────────

class Office:
    """The routes, signed in as one of a church's logins."""

    def __init__(self, db):
        app = FastAPI()
        app.include_router(church_map_router.router)
        app.dependency_overrides[require_user] = lambda: self.user
        self.c, self.db, self.user = TestClient(app), db, None

    def as_(self, biz, handle="owner"):
        if handle == "owner":
            uid = _owner(self.db, biz)
            email = OWNER_EMAIL[uid]
        else:
            uid = self.db.who[biz][handle + "@"]
            email = next(s["invited_email"] for s in self.db.t["business_users"] if s["user_id"] == uid)
        self.user = AuthedUser(id=uid, email=email, role="authenticated")
        return self

    def get(self, biz):
        return self.c.get(f"/church/map?business_id={biz}")

    def put(self, biz, what, body):
        return self.c.put(f"/church/map/{what}?business_id={biz}", json=body)


def _enter(office, db, biz):
    """A church's map_intent, entered as its office would: the role switches
    on Leaders & roles, then each department, answers-to and the settings
    through these routes, as the owner."""
    m, defs = db.intent[biz], cr.by_key(cr.defs(biz))
    for key, flips in m["roles"].items():
        cr.update_role(biz, defs[key]["id"], flips)
    office.as_(biz)
    for n, d in enumerate(m["departments"]):
        units = [{"kind": k, "ref": defs[r]["id"] if k == "role" else r} if k in ("role", "group") else
                 {"kind": k, "label": r} for k, r in d["units"]]
        r = office.put(biz, "departments", {"name": d["name"], "leader_contact_id": d["leader"],
                                            "overseer_contact_id": d["overseer"], "support_duty": d["duty"],
                                            "area": d["area"], "sort": n * 10, "units": units})
        assert r.status_code == 200, r.json()
    for h in [h for h in db.t["church_leader_roles"] if h["business_id"] == biz and h["contact_id"] in m["answers_to"]]:
        r = office.put(biz, "answers-to", {"holder_id": h["id"], "answers_to_contact_id": m["answers_to"][h["contact_id"]]})
        assert r.status_code == 200, r.json()
    said = dict(m["settings"])
    if "office_overseer_roles" in said:
        said["office_overseer_roles"] = [defs[k]["id"] for k in said["office_overseer_roles"]]
    assert office.put(biz, "settings", said).status_code == 200


def _tables(db, biz):
    """What the map's tables say for one church, without ids and stamps."""
    mine = lambda t: [r for r in db.t[t] if r["business_id"] == biz]  # noqa: E731
    name = {d["id"]: d["name"] for d in mine("church_departments")}
    st = mine("church_role_settings")[0]
    return {"departments": sorted((tuple(d[k] for k in ("name", "leader_contact_id", "overseer_contact_id",
                                                        "support_duty", "area", "status", "source", "sort"))
                                   for d in mine("church_departments")), key=repr),
            "units": sorted([(name[u["department_id"]], *[u[k] for k in ("kind", *cm.UNIT_REF.values(), "label")])
                             for u in mine("church_department_units")], key=repr),
            "answers_to": sorted(((h["contact_id"], h["role"], h["answers_to_contact_id"])
                                  for h in mine("church_leader_roles")), key=repr),
            "settings": {k: st.get(k) for k in (*cm.LEVELS, *cm.PICKS)},
            "switches": sorted(((d["key"], *(d.get(k) for k in K)) for d in mine("church_role_defs")), key=repr)}


@pytest.mark.parametrize("biz", CHURCHES, ids=[NAMES[b] for b in CHURCHES])
def test_each_churchs_map_entered_through_the_routes_is_the_direct_writes(monkeypatch, biz):
    want = _tables(build(monkeypatch), biz)
    db = build(monkeypatch, filled=False)
    _enter(Office(db), db, biz)
    assert _tables(db, biz) == want


def test_the_switch_the_seats_and_the_503s(monkeypatch):
    db = build(monkeypatch, filled=False)
    o, kitchen = Office(db), {"name": "Kitchen"}
    money = {"pastor_from_cents": 40_000}
    assert o.as_(LC, "naiya").get(LC).status_code == 200, "a manager reads"
    assert o.put(LC, "departments", kitchen).status_code == 404, "and writes nothing: the 404 a stranger gets"
    o.as_(LC, "minnie")
    assert o.put(LC, "departments", kitchen).json()["department"]["name"] == "Kitchen", "an admin writes"
    assert o.put(LC, "settings", money).status_code == 403, "but not money"
    assert o.put(LC, "settings", {"office_overseer_roles": []}).json()["settings"]["office_overseer_roles"] == []
    assert o.get(LC).json()["you"] == {"role": "admin", "writes": True, "money": False}
    o.as_(LC)
    assert o.put(LC, "settings", money).json()["settings"]["pastor_from_cents"] == 40_000, "the owner"
    assert o.get(GRACE).status_code == 404, "no seat at another church"
    assert o.c.get("/church/map?business_id=nope").status_code == 400
    kid = _dept(db, LC, "Kitchen")["id"]
    assert o.c.post(f"/church/map/departments/{kid}/archive?business_id={LC}").json()["department"]["status"] == "archived"
    monkeypatch.setenv("CHURCH_MAP", "owner")
    assert o.get(LC).status_code == 200, "owner: the platform owner's login"
    assert o.as_(LC, "minnie").get(LC).status_code == 404, "owner: no one else's"
    assert o.as_(GRACE).get(GRACE).status_code == 404, "owner: not even another church's own owner"
    monkeypatch.setenv("CHURCH_MAP", "off")
    assert o.as_(LC).get(LC).status_code == 404 and o.put(LC, "departments", kitchen).status_code == 404
    monkeypatch.setenv("CHURCH_MAP", "on")
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith("/church_department_units?") else real(p, **k))
    assert (o.get(LC).status_code, o.put(LC, "departments", kitchen).status_code) == (503, 503), "a failed load"
    cm._READY.clear()
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith("/church_role_defs?select=") else real(p, **k))
    holder = {"holder_id": next(h["id"] for h in db.t["church_leader_roles"] if h["business_id"] == LC)}
    assert (o.get(LC).status_code, o.put(LC, "answers-to", holder).status_code) == (503, 503), \
        "a failed probe (state() None) is a failed read, and the writes refuse"
    db = build(monkeypatch, filled=False, migrated=False)
    o = Office(db).as_(LC)
    assert (o.get(LC).status_code, o.put(LC, "settings", money).status_code) == (503, 503), "before the migration"


def test_the_routes_are_mounted_before_the_catch_all():
    paths = {r.path for r in church_map_router.router.routes}
    assert paths == {"/church/map", "/church/map/departments", "/church/map/departments/{department_id}/archive",
                     "/church/map/answers-to", "/church/map/settings"}
    src = open(os.path.join(ROOT, "kmj_intake_automation.py"), encoding="utf-8").read()
    assert src.index("app.include_router(church_map_router)") < src.rindex("app.include_router(public_site_router)")

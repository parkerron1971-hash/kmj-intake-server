"""One change, one row: the leaders map's change log with Undo
(church_map_batch.py; docs/CHURCH_LEADERS_STEP2.md §4.1-§4.3, §7 B3a).

Each part kind applies and undoes back to every field it touched; an undo
after something changed since is a 409 that names it, and writes nothing; a
part that fails after another got in leaves the change failed with what got
in, and applying it again finishes it; money is the owner's; a change can
wait for a yes, then be applied or discarded; the routes' switch, seats and
503s (before step 2's file, and on a failed probe); and the step-1 routes log
one change a save once the file is there, none before."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_map as cm  # noqa: E402
import church_map_batch as batch  # noqa: E402
import church_shepherding as shep  # noqa: E402
import sb_clients  # noqa: E402
from church_three import GRACE, LOVE_CITY as LC, build, church  # noqa: E402
from test_church_map_writes import Office  # noqa: E402

SKIP = ("updated_at", "updated_by", "map_by", "map_at", "created_at", "created_by")


@pytest.fixture
def db(monkeypatch):
    return build(monkeypatch)


def owner(db, biz=LC):
    return church(db, biz)["owner_id"]


def apply(db, parts, *, role="owner", by=None, biz=LC, **k):
    return batch.apply(church(db, biz), parts, by or owner(db, biz), "chief", role=role, **k)


def refused(fn, *a, code=409, **k):
    with pytest.raises(HTTPException) as e:
        fn(*a, **k)
    assert e.value.status_code == code, e.value.detail
    return str(e.value.detail)


def changes(db, biz=LC):
    return [r for r in db.t["church_map_changes"] if r["business_id"] == biz]


def state(db, biz=LC):
    """What a change can touch, without stamps, unit ids or archived
    departments; a column the fake never set reads as null, as it does in
    the database."""
    def rows(t, drop=()):
        return sorted((tuple(sorted((k, repr(v)) for k, v in r.items() if k not in SKIP + drop and v is not None))
                       for r in db.t[t] if r.get("business_id") == biz and r.get("status") != "archived"), key=repr)
    return {"departments": rows("church_departments"), "units": rows("church_department_units", ("id",)),
            "roles": rows("church_role_defs"), "holders": rows("church_leader_roles"),
            "settings": rows("church_role_settings"), "shepherding": shep.settings(biz)}


def dept(db, name, biz=LC):
    return next(d for d in db.t["church_departments"] if d["business_id"] == biz and d["name"] == name)


def role(db, key, biz=LC):
    return next(d for d in db.t["church_role_defs"] if d["business_id"] == biz and d["key"] == key)


# ─── Each part kind, made and put back ────────────────────────────────

KINDS = {
    "department_changed": [{"kind": "department", "department": "Youth", "leader": "Tasha Williams",
                            "support_duty": "first_guests", "units": [{"kind": "serve_option",
                                                                       "label": "Youth Ministry (YWD)"}]}],
    "department_made": [{"kind": "department", "name": "Kids", "area": "kids_youth",
                         "units": [{"kind": "space", "label": "kids"}]}],
    "department_drafted": [{"kind": "department", "name": "Media", "status": "draft"}],
    "department_archived": [{"kind": "department", "department": "Prayer", "status": "archived"}],
    "role_changed": [{"kind": "role", "role": "team_leader", "can_oversee": True, "definition": "Leads a team."}],
    "role_drafted": [{"kind": "role", "title": "Media Lead", "job": "team"}],
    "answers_to": [{"kind": "answers_to", "person": "Tanya Brooks", "role": "Elders", "to": "Jessica McCloud"}],
    "settings": [{"kind": "settings", "pastor_from_cents": 30_000, "board_over_cents": 300_000}],
    "shepherding": [{"kind": "shepherding", "cap": 8, "ministers": True}],
}


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_applies_then_undo_puts_every_field_back(db, kind):
    before = state(db)
    out = apply(db, KINDS[kind], said="as asked")
    assert out["change"]["status"] == "applied" and state(db) != before
    row = changes(db)[0]
    assert (row["origin"], row["said"], row["money"], len(row["parts"])) == ("chief", "as asked", kind == "settings", 1)
    part = row["parts"][0]
    assert part["kind"] == KINDS[kind][0]["kind"] and part["id"], "a made thing's id is kept too"
    undone = batch.undo(church(db, LC), row["id"], owner(db), role="owner")
    assert state(db) == before, "every field it touched is back"
    old, new = changes(db)
    assert (old["status"], bool(old["undone_at"]), new["undoes"], new["status"]) == ("undone", True, old["id"], "applied")
    assert undone["undone"] == old["id"]
    if kind == "department_drafted":
        assert not [d for d in db.t["church_departments"] if d["name"] == "Media"], "a draft it made is deleted"
    if kind == "department_made":
        assert dept(db, "Kids")["status"] == "archived", "an active department it made is archived"
    assert "put back already" in refused(batch.undo, church(db, LC), old["id"], owner(db), role="owner")
    assert "put another one back" in refused(batch.undo, church(db, LC), new["id"], owner(db), role="owner")


def test_the_parts_record_before_and_after_and_read_in_plain_words(db):
    w = db.who[LC]
    apply(db, KINDS["department_changed"] + KINDS["answers_to"])
    p = changes(db)[0]["parts"]
    assert p[0]["label"] == "Youth" and p[0]["before"]["leader_contact_id"] == w["yolanda"]
    assert p[0]["after"]["leader_contact_id"] == w["tasha"] and set(p[0]["after"]) == \
        {"leader_contact_id", "support_duty", "units"}, "only what it changes"
    assert (p[1]["label"], p[1]["before"], p[1]["after"]) == (
        "Tanya Brooks (Elders)", {"answers_to_contact_id": None}, {"answers_to_contact_id": w["jessica"]})
    lines = batch.recent(church(db, LC), "owner")["recent"][0]["lines"]
    assert lines == ["Youth: leader Yolanda Reed → Tasha Williams",
                     "Youth: office helper Youth and Teen Bible Study → First-time guests and welcome calls",
                     "Youth: teams, groups and spaces: took off Youth and the youth space",
                     "Tanya Brooks (Elders): who they answer to nobody → Jessica McCloud"]
    apply(db, KINDS["settings"] + KINDS["shepherding"])
    assert batch.recent(church(db, LC), "owner")["recent"][0]["lines"] == [
        "Your church: the pastor’s yes from the usual → $300", "Your church: the board’s yes over the usual → $3,000",
        "Shepherding: Ministers shepherd off → on", "Shepherding: families per shepherd 12 → 8"]
    for word in ("batch", " op ", "template", "switch", "unit", "status", "phase"):
        assert not any(word in x for x in lines), word


# ─── Undo is whole, or not at all ─────────────────────────────────────

def test_undo_after_something_changed_since_is_a_409_that_names_it(db):
    w, biz = db.who[LC], church(db, LC)
    apply(db, [{"kind": "department", "department": "Youth", "overseer": w["eve"]},
               {"kind": "shepherding", "cap": 9}])
    row = changes(db)[0]
    cm.save_department(biz, {"id": dept(db, "Youth")["id"], "overseer_contact_id": w["andre"]}, owner(db))
    before = state(db)
    says = refused(batch.undo, biz, row["id"], owner(db), role="owner")
    assert says.startswith("Youth’s overseer was changed again on ") and says.endswith("; change it directly.")
    assert state(db) == before and len(changes(db)) == 1, "never a half undo: Shepherding's cap stays 9"
    cm.save_department(biz, {"id": dept(db, "Youth")["id"], "overseer_contact_id": w["eve"]}, owner(db))
    row["applied_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    assert "more than 30 days old" in refused(batch.undo, biz, row["id"], owner(db), role="owner")


def test_undo_that_its_own_write_would_refuse_is_a_409(db):
    """Prayer's intercessor roles went to a new department after Prayer was
    archived: putting Prayer back would hang them from two."""
    biz = church(db, LC)
    apply(db, KINDS["department_archived"])
    cm.save_department(biz, {"name": "Intercession", "units": [{"kind": "role", "ref": role(db, "intercessors")["id"]}]},
                       owner(db))
    assert refused(batch.undo, biz, changes(db)[0]["id"], owner(db), role="owner").startswith(
        "That can’t be put back: Intercessors already hangs from Intercession")
    assert dept(db, "Prayer")["status"] == "archived"


# ─── Checked first; a write that fails after another got in ───────────

LEAD_PRAYER = [{"kind": "role", "role": "team_leader", "can_oversee": True},
               {"kind": "department", "department": "Prayer", "overseer": "Tasha Williams"}]


def test_every_part_is_checked_first_against_the_parts_before_it(db):
    before = state(db)
    says = refused(apply, db, LEAD_PRAYER[::-1], code=400)
    assert "Tasha Williams doesn’t hold a role that can oversee" in says
    assert state(db) == before and not changes(db), "nothing written, nothing logged"
    apply(db, LEAD_PRAYER)
    assert dept(db, "Prayer")["overseer_contact_id"] == db.who[LC]["tasha"]
    for bad, says in (([{"kind": "group"}], "A change is made of"), (LEAD_PRAYER[:1] * 2, "once in a change"),
                      ([{"kind": "department", "department": "Choir"}], "There’s no department called Choir"),
                      ([{"kind": "answers_to", "person": "Andre Wallace"}], "Say who they answer to")):
        assert says in refused(apply, db, bad, code=400)


def test_a_part_that_fails_leaves_the_change_failed_and_applying_it_again_finishes_it(db, monkeypatch):
    patch = sb_clients.sb_patch_as_service
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **k: None
                        if path.startswith("/church_departments") else patch(path, body, **k))
    says = refused(apply, db, LEAD_PRAYER, code=503)
    assert says == "That didn’t save. Try again." + batch.WENT_IN
    row = changes(db)[0]
    assert (row["status"], [p.get("done") for p in row["parts"]]) == ("failed", [None, False])
    assert role(db, "team_leader")["can_oversee"] is True, "what got in stays in, and says so"
    assert "didn’t go in" in batch.recent(church(db, LC), "owner")["recent"][0]["lines"][1]
    refused(batch.apply_pending, church(db, LC), row["id"], owner(db), role="owner", code=503)
    assert row["status"] == "failed", "a failed retry keeps it failed"
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    out = batch.apply_pending(church(db, LC), row["id"], owner(db), role="owner")
    assert out["change"]["status"] == row["status"] == "applied" and not row["error"]
    assert dept(db, "Prayer")["overseer_contact_id"] == db.who[LC]["tasha"]
    assert "isn’t waiting" in refused(batch.apply_pending, church(db, LC), row["id"], owner(db), role="owner")
    batch.undo(church(db, LC), row["id"], owner(db), role="owner")
    assert (role(db, "team_leader")["can_oversee"], dept(db, "Prayer")["overseer_contact_id"]) == \
        (False, db.who[LC]["paul"])


def test_finishing_a_failed_undo_lets_go_of_what_waits_on_the_drafts_it_took_out(db, monkeypatch):
    """#1729 review: apply_pending finishing an undo lets go, as undo() does, so no dead change stays waiting."""
    import church_templates as ct
    biz, by = church(db, GRACE), owner(db, GRACE)
    out = ct.adopt(biz, "shape", "multi_staff", by, role="owner")
    waiting = out["waiting"]["id"]
    real, calls = sb_clients.sb_delete_as_service, []

    def delete(path, **k):          # the first draft role goes, the next one doesn't
        if path.startswith("/church_role_defs"):
            calls.append(path)
            if len(calls) > 1:
                return False
        return real(path, **k)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    assert "apply it again to finish it" in refused(batch.undo, biz, out["change"]["id"], by, role="owner", code=503)
    half = next(r for r in changes(db, GRACE) if r["status"] == "failed")
    assert half["undoes"] == out["change"]["id"]
    assert next(r for r in changes(db, GRACE) if r["id"] == waiting)["status"] == "pending", "nothing let go yet"
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", real)
    done = batch.apply_pending(biz, half["id"], by, role="owner")
    assert done["let_go"] == [waiting] and done["change"]["status"] == "applied"
    assert next(r for r in changes(db, GRACE) if r["id"] == waiting)["status"] == "discarded"
    assert next(r for r in changes(db, GRACE) if r["id"] == out["change"]["id"])["status"] == "undone"
    other = apply(db, KINDS["shepherding"], stage=True, biz=GRACE)["change"]
    assert batch.apply_pending(biz, other["id"], by, role="owner")["let_go"] == [], "only an undo lets go"


def test_a_lone_part_that_fails_logs_nothing_and_answers_as_its_write_does(db, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda *a, **k: None)
    assert refused(apply, db, KINDS["department_changed"], code=503) == "That didn’t save. Try again."
    assert not changes(db)


# ─── Money, waiting changes, seats ────────────────────────────────────

def test_money_is_the_owners_to_change_undo_apply_or_discard(db):
    admin = db.who[LC]["minnie@"]
    assert "Only the owner changes" in refused(apply, db, KINDS["settings"], role="admin", by=admin, code=403)
    assert "Only the owner" in refused(apply, db, [{"kind": "role", "role": "elders", "can_board_yes": True}],
                                       role="admin", by=admin, code=403), "a board yes is money (decision 3)"
    apply(db, [{"kind": "role", "role": "elders", "can_board_yes": True}])
    apply(db, KINDS["settings"])
    assert [r["money"] for r in changes(db)] == [True, True]
    assert "Only the owner" in refused(batch.undo, church(db, LC), changes(db)[1]["id"], admin, role="admin", code=403)
    batch.undo(church(db, LC), changes(db)[1]["id"], owner(db), role="owner")
    staged = apply(db, KINDS["settings"], stage=True)["change"]
    for fn in (batch.apply_pending, batch.discard):
        refused(fn, church(db, LC), staged["id"], admin, role="admin", code=403)
    assert apply(db, KINDS["shepherding"], role="admin", by=admin)["change"]["money"] is False
    for seat in ("manager", "viewer", ""):
        assert "owner or an admin" in refused(apply, db, KINDS["shepherding"], role=seat, code=403)


def test_a_waiting_change_is_applied_or_discarded(db):
    before, biz = state(db), church(db, LC)
    waiting = apply(db, KINDS["role_changed"], stage=True, phase="leaders")["change"]
    assert waiting["status"] == "pending" and state(db) == before, "staged: nothing written"
    assert changes(db)[0]["phase"] == "leaders"
    sheet = batch.recent(biz, "owner")
    assert [c["id"] for c in sheet["pending"]] == [waiting["id"]] and sheet["recent"] == []
    assert sheet["pending"][0]["can_apply"] and not sheet["pending"][0]["can_undo"]
    assert "Only a change that was made" in refused(batch.undo, biz, waiting["id"], owner(db), role="owner")
    batch.apply_pending(biz, waiting["id"], owner(db), role="owner")
    assert role(db, "team_leader")["can_oversee"] is True and changes(db)[0]["applied_at"]
    other = apply(db, KINDS["department_drafted"], stage=True)["change"]
    assert batch.discard(biz, other["id"], owner(db), role="owner")["change"]["status"] == "discarded"
    assert not [d for d in db.t["church_departments"] if d["name"] == "Media"]
    for fn in (batch.discard, batch.apply_pending):
        refused(fn, biz, other["id"], owner(db), role="owner")
    made = apply(db, KINDS["department_made"], stage=True)["change"]
    batch.apply_pending(biz, made["id"], owner(db), role="owner")
    assert next(r for r in changes(db) if r["id"] == made["id"])["parts"][0]["id"] == dept(db, "Kids")["id"], \
        "a waiting change that makes something keeps its id once made, for Undo"
    late = apply(db, [{"kind": "department", "department": "Youth", "sort": 7}], stage=True)["change"]
    cm.save_department(biz, {"id": dept(db, "Youth")["id"], "sort": 8}, owner(db))
    assert "after this change was saved" in refused(batch.apply_pending, biz, late["id"], owner(db), role="owner")
    assert apply(db, [{"kind": "department", "department": "Youth", "sort": 8}], stage=True)["change"] is None, \
        "a change of nothing logs nothing"
    assert refused(batch.undo, church(db, GRACE), waiting["id"], owner(db, GRACE), role="owner", code=404) == \
        "That change isn’t here", "another church's change"


# ─── The routes ───────────────────────────────────────────────────────

def test_the_changes_routes_seats_switch_and_503s(monkeypatch):
    db = build(monkeypatch, filled=False)
    o = Office(db).as_(LC)
    saved = o.put(LC, "departments", {"name": "Kitchen"}).json()
    assert saved["department"]["name"] == "Kitchen" and saved["change"]["status"] == "applied"
    got = o.c.get(f"/church/map/changes?business_id={LC}").json()
    assert got["recent"][0]["lines"] == ["Made Kitchen: leader nobody; overseer nobody; office helper none; area none; "
                                         "holds nothing yet"] and got["recent"][0]["can_undo"], "all it got (11-04)"
    assert o.as_(LC, "naiya").c.get(f"/church/map/changes?business_id={LC}").status_code == 200, "a manager reads"
    url = f"/church/map/changes/{saved['change']['id']}/undo?business_id={LC}"
    assert o.c.post(url).status_code == 404, "and puts nothing back"
    assert o.as_(LC, "minnie").c.post(url).json()["undone"] == saved["change"]["id"], "an admin does"
    assert db.t["church_departments"][-1]["status"] == "archived"
    for act in ("apply", "discard"):
        assert o.c.post(f"/church/map/changes/{saved['change']['id']}/{act}?business_id={LC}").status_code == 409
    monkeypatch.setenv("CHURCH_MAP", "owner")
    assert o.c.get(f"/church/map/changes?business_id={LC}").status_code == 200,         "owner: the platform owner's church, Love City's admin too (11-04)"
    assert o.as_(GRACE).c.get(f"/church/map/changes?business_id={GRACE}").status_code == 404, "no other church"
    monkeypatch.setenv("CHURCH_MAP", "on")
    cm._READY.clear()
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: None if p.startswith(
        ("/church_map_changes?select=id", "/church_role_defs?select=id")) else real(p, **k))
    o.as_(LC)
    assert o.c.get(f"/church/map/changes?business_id={LC}").json()["detail"] == cm.UNREAD
    assert o.put(LC, "departments", {"name": "Pantry"}).status_code == 503, "a failed probe: a save never runs unlogged"
    db = build(monkeypatch, filled=False, migrated2=False)
    o = Office(db).as_(LC)
    assert o.c.get(f"/church/map/changes?business_id={LC}").json()["detail"] == batch.NOT_READY
    assert o.c.post(f"/church/map/changes/{saved['change']['id']}/undo?business_id={LC}").status_code == 503


@pytest.mark.parametrize("migrated2", [True, False], ids=["step2_applied", "step2_absent"])
def test_the_step1_routes_log_one_change_a_save_once_step2_is_there(monkeypatch, migrated2):
    db = build(monkeypatch, filled=False, migrated2=migrated2)
    o, w = Office(db).as_(LC), db.who[LC]
    made = o.put(LC, "departments", {"name": "Youth", "leader_contact_id": w["yolanda"]}).json()["department"]
    o.put(LC, "departments", {"id": made["id"], "overseer_contact_id": w["andre"]})
    holder = next(h["id"] for h in db.t["church_leader_roles"] if h["contact_id"] == w["tanya"])
    o.put(LC, "answers-to", {"holder_id": holder, "answers_to_contact_id": w["jessica"]})
    money = {"pastor_from_cents": 40_000}
    assert o.put(LC, "settings", money).json()["settings"]["pastor_from_cents"] == 40_000
    assert o.put(LC, "settings", money).json()["changed"] is False
    archived = o.c.post(f"/church/map/departments/{made['id']}/archive?business_id={LC}").json()
    assert archived["department"]["status"] == "archived"
    if not migrated2:
        assert (archived["change"], archived["made"], archived["can_undo"]) == (None, None, False) and             not db.t["church_map_changes"], "as today: nothing logged, so whether it changed isn't told"
        return
    rows = sorted(db.t["church_map_changes"], key=lambda r: r["made_at"])
    assert [(r["origin"], r["status"], r["money"], [p["kind"] for p in r["parts"]]) for r in rows] == [
        ("office", "applied", False, ["department"]), ("office", "applied", False, ["department"]),
        ("office", "applied", False, ["answers_to"]), ("office", "applied", True, ["settings"]),
        ("office", "applied", False, ["department"])], "one a save; the same levels again log nothing"
    assert archived["change"]["id"] == rows[-1]["id"] and rows[-1]["parts"][0]["after"] is None


def test_every_logged_save_says_whether_it_made_anything_and_whether_undo_can_put_it_back(monkeypatch):
    """F8 review, 11-04: the logged saves dropped the batch's `made`, so the page couldn't tell "nothing
    changed" from "saved, but its record didn't save", and said "Saved" with no Undo either way. Each now
    answers with change, made, can_undo and, without a change, a note saying which."""
    import church_map_router as r
    db = build(monkeypatch, filled=False)
    o, w = Office(db).as_(LC), db.who[LC]
    made = o.put(LC, "departments", {"name": "Kitchen"}).json()
    assert (made["made"], made["can_undo"], made["note"], made["change"]["status"]) == (True, True, "", "applied")
    kid = made["department"]["id"]
    same = o.put(LC, "departments", {"id": kid, "name": "Kitchen"}).json()
    assert (same["ok"], same["made"], same["change"], same["can_undo"], same["note"]) == (True, False, None, False,
                                                                                         r.NOTHING)
    holder = next(h["id"] for h in db.t["church_leader_roles"] if h["contact_id"] == w["tanya"])
    to = {"holder_id": holder, "answers_to_contact_id": w["jessica"]}
    first = o.put(LC, "answers-to", to).json()
    assert first["made"] and first["can_undo"] and first["holder"]["answers_to_contact_id"] == w["jessica"]
    assert (o.put(LC, "answers-to", to).json()["note"]) == r.NOTHING
    money = o.put(LC, "settings", {"pastor_from_cents": 40_000}).json()
    assert money["made"] and money["change"]["money"] and money["can_undo"], "the owner's own money change"
    again = o.put(LC, "settings", {"pastor_from_cents": 40_000}).json()
    assert (again["made"], again["changed"], again["note"]) == (False, False, r.NOTHING), "the old field stays"
    admin = o.as_(LC, "minnie").put(LC, "settings", {"office_overseer_roles": []}).json()
    assert (admin["made"], admin["can_undo"], admin["change"]["money"]) == (True, True, False), "an admin's, no money"
    o.as_(LC)
    real = db.post
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, prefer=None, **k: None if path.startswith(
        "/church_map_changes") else real(path, body, prefer, **k))
    lost = o.put(LC, "departments", {"id": kid, "area": "office"}).json()
    assert (lost["made"], lost["change"], lost["can_undo"], lost["note"]) == (True, None, False, r.UNLOGGED)
    assert next(d for d in db.t["church_departments"] if d["id"] == kid)["area"] == "office", "it saved"
    url = f"/church/map/departments/{kid}/archive?business_id={LC}"
    gone = o.c.post(url).json()
    assert (gone["made"], gone["change"], gone["can_undo"], gone["note"]) == (True, None, False, r.UNLOGGED), \
        "archived, its record lost"
    monkeypatch.setattr(sb_clients, "sb_post_as_service", real)
    twice = o.c.post(url).json()
    assert (twice["made"], twice["change"], twice["can_undo"], twice["note"]) == (False, None, False, r.NOTHING), \
        "archived already"

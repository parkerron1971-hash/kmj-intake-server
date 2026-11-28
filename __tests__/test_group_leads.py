"""Every group has a leader (church_group_leads.py; mission M-8, Kevin
2026-11-28). Pins, at the three test churches:

  1. who may: the owner, an admin and an office login that looks after groups
     name a group's leader, co-leaders and who it answers to; the group's own
     lead (from their login) changes only co-leaders; anyone else is refused
  2. naming someone puts them straight in, as the group's lead row; whoever
     led before stays on as a co-leader unless the save lists the co-leaders;
     leaving the co-leaders makes someone a member again, never removes them
  3. one person a group: they must hold an active role here, can't be one of
     the group's leaders, and are this church's
  4. a class group points at its Course Studio class; a team at a Serve card
     choice; nothing else does
  5. the note: "You now lead Sisters in the City" to a phone, and an email to
     an adult without one; a co-leader's says co-leader
  6. the switch (closed: 404) and before the file (reads say ready: false,
     writes are a 503)
  7. the Lead tab: the lead adds and takes off a co-leader from the people in
     the group; a co-leader can't
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_group_leads as cgl  # noqa: E402
import church_groups_office as cgo  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from church_three import GRACE, LOVE_CITY as LC, NAMES, OWNER_EMAIL, build, church  # noqa: E402


def _gid(db, biz, name):
    return next(g["id"] for g in db.t["groups"] if g["business_id"] == biz and g["name"] == name)


class Office:
    def __init__(self, db):
        app = FastAPI()
        app.include_router(cgo.router)
        app.dependency_overrides[require_user] = lambda: self.user
        self.c, self.db, self.user = TestClient(app), db, None

    def as_(self, uid, email=""):
        self.user = AuthedUser(id=uid, email=email, role="authenticated")
        return self.c


@pytest.fixture
def lc(monkeypatch):
    db = build(monkeypatch)
    monkeypatch.setenv("GROUP_LEADS", "on")
    cgl._READY.clear()
    for g in db.t["groups"]:
        g.setdefault("answers_to_contact_id", None)
        g.setdefault("course_id", None)
        g.setdefault("serve_option", None)
        g.setdefault("youth", False)
    for m in db.t["group_members"]:
        m.setdefault("co_leader", False)
    # group_members' primary key (group_id, contact_id): merge-duplicates updates.
    real = sb_clients.sb_post_as_service

    def post(path, body, *a, **k):
        if path.startswith("/group_members?on_conflict=group_id,contact_id"):
            out = []
            for b in body if isinstance(body, list) else [body]:
                old = next((r for r in db.t["group_members"]
                            if r["group_id"] == b["group_id"] and r["contact_id"] == b["contact_id"]), None)
                if old:
                    old.update(b)
                else:
                    db.t["group_members"].append(dict(b))
                    old = db.t["group_members"][-1]
                out.append(dict(old))
            return out
        return real(path, body, *a, **k)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    db.pushed, db.emails = [], []
    import member_push
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: db.pushed.append((kind, k)) or 1)

    async def resend(**k):
        db.emails.append(k)
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", resend)
    import group_email
    monkeypatch.setattr(group_email, "app_url", lambda b: "https://lovecity.example")
    db.t.setdefault("member_push_subscriptions", [])
    db.t.setdefault("academy_courses", [])
    return db


def _owner(db, biz=LC):
    uid = church(db, biz)["owner_id"]
    return uid, OWNER_EMAIL[uid]


def _rows(db, gid):
    return sorted((m["contact_id"], m["role"], bool(m.get("co_leader"))) for m in db.t["group_members"] if m["group_id"] == gid)


def _put(o, uid, gid, body, email="", biz=LC):
    return o.as_(uid, email).put(f"/church/groups/{gid}/leads", json={"business_id": biz, **body})


# ── 1. who may ───────────────────────────────────────────────────────

def test_the_owner_names_a_leader_and_who_the_group_answers_to(lc):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    r = _put(o, *_owner(lc)[:1], gid, {"leader_contact_id": w["dana"], "answers_to_contact_id": w["marcus"]},
             email=_owner(lc)[1])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["leader"] == {"contact_id": w["dana"], "name": "Dana Owens"}
    assert body["co_leaders"] == [{"contact_id": w["gloria"], "name": "Gloria Hunt"}]      # who led before stays on
    assert body["answers_to"] == {"contact_id": w["marcus"], "name": "Marcus Taylor"}
    assert (w["dana"], "leader", False) in _rows(lc, gid) and (w["gloria"], "leader", True) in _rows(lc, gid)
    assert next(g for g in lc.t["groups"] if g["id"] == gid)["answers_to_contact_id"] == w["marcus"]


@pytest.mark.parametrize("handle,ok", [("minnie", True), ("tiara", True), ("laquesha", False), ("shapretta", False)])
def test_office_logins_name_leaders_only_when_they_look_after_groups(lc, handle, ok):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    r = _put(o, w[handle + "@"], gid, {"leader_contact_id": w["dana"]})
    assert r.status_code == (200 if ok else 403), r.text
    if not ok:
        assert "names a group’s leader" in r.json()["detail"]
        assert (w["gloria"], "leader", False) in _rows(lc, gid)          # nothing changed


def test_the_groups_lead_changes_co_leaders_only(lc):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    # Gloria leads it and has an office login tied to her person.
    lc.t["business_users"].append({"business_id": LC, "user_id": "51000000-0000-4000-8000-000000000001", "role": "viewer",
                                   "status": "active", "contact_id": w["gloria"], "invited_email": "gloria@lovecity.org"})
    lc.t["group_members"].append({"group_id": gid, "business_id": LC, "contact_id": w["eve"], "role": "member", "co_leader": False})
    me = "51000000-0000-4000-8000-000000000001"
    r = _put(o, me, gid, {"co_leader_contact_ids": [w["eve"]]})
    assert r.status_code == 200, r.text
    assert r.json()["co_leaders"] == [{"contact_id": w["eve"], "name": "Eve Hall"}]
    for body in ({"answers_to_contact_id": w["marcus"]}, {"leader_contact_id": w["eve"]}):
        r = _put(o, me, gid, body)
        assert r.status_code == 403 and "office names the leader" in r.json()["detail"]
    # Someone not in the group can't be made co-leader by the lead.
    r = _put(o, me, gid, {"co_leader_contact_ids": [w["eve"], w["paul"]]})
    assert r.status_code == 400 and "already in the group" in r.json()["detail"]


def test_a_stranger_is_refused_and_a_read_says_what_each_may_do(lc):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    assert _put(o, "5f000000-0000-4000-8000-000000000009", gid, {"leader_contact_id": w["dana"]}).status_code == 403
    uid, email = _owner(lc)
    r = o.as_(uid, email).get(f"/church/groups/{gid}/leads", params={"business_id": LC})
    assert r.status_code == 200
    assert r.json()["can"] == {"name_leader": True, "co_leaders": True, "answers_to": True}
    names = [p["name"] for p in r.json()["answer_choices"]]
    assert "Marcus Taylor" in names and "Gloria Hunt" not in names        # only people who hold a role
    r = o.as_(w["laquesha@"]).get(f"/church/groups/{gid}/leads", params={"business_id": LC})
    assert r.status_code == 200 and r.json()["can"]["name_leader"] is False and "answer_choices" not in r.json()


# ── 2. straight in; co-leaders; back to member ───────────────────────

def test_listing_the_co_leaders_sets_them_and_whoever_left_is_a_member_again(lc):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    uid, email = _owner(lc)
    _put(o, uid, gid, {"leader_contact_id": w["dana"], "co_leader_contact_ids": [w["eve"], w["ivy"]]}, email=email)
    assert _rows(lc, gid) == sorted([(w["dana"], "leader", False), (w["eve"], "leader", True), (w["ivy"], "leader", True),
                                     (w["gloria"], "member", False)])
    _put(o, uid, gid, {"co_leader_contact_ids": [w["ivy"]]}, email=email)
    assert (w["eve"], "member", False) in _rows(lc, gid)                  # still in the group
    r = _put(o, uid, gid, {"co_leader_contact_ids": [w[h] for h in ("eve", "ivy", "iris", "paul", "ruth")]}, email=email)
    assert r.status_code == 400 and "at most 4" in r.json()["detail"]


def test_a_co_leader_needs_a_lead(lc):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    uid, email = _owner(lc)
    r = _put(o, uid, gid, {"leader_contact_id": None, "co_leader_contact_ids": [w["eve"]]}, email=email)
    assert r.status_code == 400 and "leader first" in r.json()["detail"]


# ── 3. one person a group ────────────────────────────────────────────

@pytest.mark.parametrize("who,says", [("gloria", "one of themselves"), ("calvin", "Give them a role first")])
def test_who_the_group_answers_to(lc, who, says):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    uid, email = _owner(lc)
    r = _put(o, uid, gid, {"answers_to_contact_id": w[who]}, email=email)
    assert r.status_code == 400 and says in r.json()["detail"]


def test_another_churchs_person_is_refused(lc):
    o = Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    uid, email = _owner(lc)
    other = next(iter(lc.who[GRACE].values()))
    r = _put(o, uid, gid, {"leader_contact_id": other}, email=email)
    assert r.status_code == 400 and "this church's people" in r.json()["detail"]


# ── 4. a class's Course Studio class; a team's Serve choice ──────────

def test_a_class_group_points_at_its_class_and_a_team_at_a_serve_choice(lc):
    w, o = lc.who[LC], Office(lc)
    uid, email = _owner(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    course = "c0000000-0000-4000-8000-000000000001"
    lc.t["academy_courses"].append({"id": course, "business_id": LC, "title": "New Members"})
    r = _put(o, uid, gid, {"course_id": course}, email=email)
    assert r.status_code == 400 and "class group" in r.json()["detail"]
    next(g for g in lc.t["groups"] if g["id"] == gid)["kind"] = "class"
    r = _put(o, uid, gid, {"course_id": course}, email=email)
    assert r.status_code == 200 and r.json()["course"] == {"id": course, "title": "New Members"}
    r = _put(o, uid, gid, {"serve_option": "Hospitality Team"}, email=email)
    assert r.status_code == 400 and "serving team" in r.json()["detail"]
    next(g for g in lc.t["groups"] if g["id"] == gid)["kind"] = "team"
    r = _put(o, uid, gid, {"serve_option": "  Hospitality   Team "}, email=email)
    assert r.status_code == 200 and r.json()["serve_option"] == "Hospitality Team"


# ── 5. the note ──────────────────────────────────────────────────────

def test_the_note_to_a_phone_and_an_email_to_the_rest(lc):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    uid, email = _owner(lc)
    lc.t["member_push_subscriptions"].append({"business_id": LC, "contact_id": w["dana"]})
    r = _put(o, uid, gid, {"leader_contact_id": w["dana"], "co_leader_contact_ids": [w["eve"]]}, email=email)
    assert r.status_code == 200
    bodies = sorted(k["body"] for _kind, k in lc.pushed)
    assert bodies == ["You now lead Sisters in the City. Open it on the Lead tab.",
                      "You’re now a co-leader of Sisters in the City. Open it on the Lead tab."]
    assert [m["to_email"] for m in lc.emails] == ["eve@lovecity.org"]      # Dana has a phone; Eve doesn't
    assert "co-leader of Sisters in the City" in lc.emails[0]["subject"]
    # Saving again tells nobody new.
    lc.pushed.clear()
    lc.emails.clear()
    _put(o, uid, gid, {"answers_to_contact_id": w["marcus"]}, email=email)
    assert lc.pushed == [] and lc.emails == []


# ── 6. the switch and the file ───────────────────────────────────────

def test_closed_is_a_404_and_before_the_file_writes_are_a_503(lc, monkeypatch):
    w, o = lc.who[LC], Office(lc)
    gid = _gid(lc, LC, "Sisters in the City")
    uid, email = _owner(lc)
    monkeypatch.setenv("GROUP_LEADS", "off")
    assert o.as_(uid, email).get(f"/church/groups/{gid}/leads", params={"business_id": LC}).status_code == 404
    monkeypatch.setenv("GROUP_LEADS", "on")
    monkeypatch.setattr(cgl, "ready", lambda *a: False)
    r = o.as_(uid, email).get(f"/church/groups/{gid}/leads", params={"business_id": LC})
    assert r.status_code == 200 and r.json()["ready"] is False and r.json()["can"]["name_leader"] is False
    assert [x["name"] for x in r.json()["leaders"]] == ["Gloria Hunt"]
    r = _put(o, uid, gid, {"leader_contact_id": w["dana"]}, email=email)
    assert r.status_code == 503 and r.json()["detail"] == cgl.NOT_YET


def test_the_choices_before_a_group_exists(lc):
    w, o = lc.who[LC], Office(lc)
    uid, email = _owner(lc)
    lc.t["academy_courses"].append({"id": "c0000000-0000-4000-8000-000000000002", "business_id": LC, "title": "The Making",
                                    "status": "published"})
    r = o.as_(uid, email).get("/church/groups/leads/choices", params={"business_id": LC})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] and body["can_name"] and "Marcus Taylor" in [p["name"] for p in body["answer_choices"]]
    assert body["classes"] == [{"id": "c0000000-0000-4000-8000-000000000002", "title": "The Making"}]
    assert isinstance(body["serve_options"], list)
    r = o.as_(w["laquesha@"]).get("/church/groups/leads/choices", params={"business_id": LC})
    assert r.status_code == 200 and r.json()["can_name"] is False and r.json()["answer_choices"] == []


def test_every_probe_names_the_church(lc, monkeypatch):
    real = sb_clients.sb_get_as_service
    seen = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, *a, **k: seen.append(path) or real(path, *a, **k))
    cgl._READY.clear()
    assert cgl.ready(LC)
    assert seen and all(f"business_id=eq.{LC}" in p for p in seen)


def test_owner_mode_opens_only_the_platform_owners_church(lc, monkeypatch):
    monkeypatch.setenv("GROUP_LEADS", "owner")
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == LC)
    assert cgl.church_open(LC) and not cgl.church_open(GRACE)


# ── 7. the Lead tab ──────────────────────────────────────────────────

def test_the_lead_adds_and_takes_off_a_co_leader_on_the_lead_tab(lc, monkeypatch):
    import member_portal_church as mpc
    import member_portal_lead as mpl
    w = lc.who[LC]
    gid = _gid(lc, LC, "Sisters in the City")
    lc.t["group_members"].append({"group_id": gid, "business_id": LC, "contact_id": w["eve"], "role": "member", "co_leader": False})
    biz = church(lc, LC)
    me = {"id": w["gloria"], "name": "Gloria Hunt"}

    async def signed_in(request):
        return {"business": biz, "site": {}}, me, False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpl, "_allowed", lambda church, me: True)
    app = FastAPI()
    app.include_router(mpl.router)
    c = TestClient(app)
    r = c.post("/my/lead/groups/co-leaders", data={"group_id": gid, "contact_id": w["eve"], "do": "add"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/lead/groups/{gid}?done=co_leader_added"
    assert (w["eve"], "leader", True) in _rows(lc, gid)
    assert any("co-leader of Sisters in the City" in k["body"] for _kind, k in lc.pushed) or lc.emails
    # A co-leader can't add or take off anyone.
    me["id"] = w["eve"]
    r = c.post("/my/lead/groups/co-leaders", data={"group_id": gid, "contact_id": w["eve"], "do": "off"}, follow_redirects=False)
    assert r.headers["location"] == f"/my/lead/groups/{gid}" and (w["eve"], "leader", True) in _rows(lc, gid)
    me["id"] = w["gloria"]
    r = c.post("/my/lead/groups/co-leaders", data={"group_id": gid, "contact_id": w["eve"], "do": "off"}, follow_redirects=False)
    assert r.headers["location"].endswith("done=co_leader_off") and (w["eve"], "member", False) in _rows(lc, gid)


def test_the_lead_tab_shows_the_co_leaders_block_to_the_lead_only(lc):
    import group_lead
    w = lc.who[LC]
    gid = _gid(lc, LC, "Sisters in the City")
    people = [{"id": w["gloria"], "name": "Gloria Hunt"}, {"id": w["eve"], "name": "Eve Hall"}]
    v = {"leads": {"lead": w["gloria"], "co": []}}
    kw = dict(ic=lambda n, s: "", esc=lambda s: str(s), face=lambda p: "", name=lambda p: p["name"])
    html = group_lead._co_leaders_block(v, w["gloria"], people, gid, **kw)
    assert "Your co-leaders" in html and "Make co-leader" in html and "Eve Hall" in html
    assert group_lead._co_leaders_block(v, w["eve"], people, gid, **kw) == ""
    assert group_lead._co_leaders_block({"leads": None}, w["gloria"], people, gid, **kw) == ""

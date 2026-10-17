"""The role library (church_roles.py; church_follow_up's routing and chain on
it; church_router's /church/leaders, /church/roles, /church/type; Chief's
leaders section and draft). Kevin, 2026-10-17: every role is the church's
own title on a job Chief understands; every church type; roles a church
makes itself are wired the same; a late step climbs the leader's chain.
Design canvas BKNqVVNiyxfAGAa7UAVWUC.

The tables are faked in memory with the PostgREST filters these modules
use (the follow-up tests' fake, plus `not.is.null`), so the reads and
writes are the real paths."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import church_roles as cr  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import (BIZ, OTHER_BIZ, OWNER, NAMES, PASTOR, MINISTER, TASHA, ROBERT, DANA, MARCUS,  # noqa: E402
                                   KEISHA, ANDRE, SERVE, BAPTISM, VISIT, TRIP, _split, _role)


def _cmp(row, col, op, val):
    v = row.get(col)
    if op == "not":
        inner_op, _, inner = val.partition(".")
        return not _cmp(row, col, inner_op, inner)
    if op == "is":
        return v is None if val == "null" else str(v).lower() == val
    if op == "in":
        return str(v) in set(_split(val.strip("()")))
    if op == "eq":
        return str(v).lower() == val.lower() if isinstance(v, bool) else str(v) == val
    if op == "neq":
        return str(v) != val
    if v is None:
        return False
    if isinstance(v, (int, float)):
        val = type(v)(val)
    return {"gt": v > val, "lt": v < val, "gte": v >= val, "lte": v <= val}[op]


class FakeDB:
    def __init__(self, **tables):
        self.t = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.writes = []

    def _parse(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        filters, limit = [], None
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            v = unquote(v)
            if k in ("select", "order", "on_conflict"):
                continue
            if k == "limit":
                limit = int(v)
            elif k == "or":
                filters.append(("or", [tuple(c.split(".", 2)) for c in _split(v.strip("()"))]))
            else:
                op, _, val = v.partition(".")
                filters.append((k, op, val))
        return table, filters, limit

    def _match(self, row, filters):
        for f in filters:
            if f[0] == "or":
                if not any(_cmp(row, c, o, v) for c, o, v in f[1]):
                    return False
            elif not _cmp(row, *f):
                return False
        return True

    def get(self, path, **_):
        table, filters, limit = self._parse(path)
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, filters)]
        return rows[:limit] if limit else rows

    def post(self, path, body, prefer=None, **_):
        table = path.lstrip("/").split("?")[0]
        rows = body if isinstance(body, list) else [body]
        out = []
        for b in rows:
            row = dict(b)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", cfu._iso(cfu._now()))
            have = self.t.setdefault(table, [])
            if table == "church_role_defs":
                row.setdefault("status", "active")
                row.setdefault("reports_to", None)
                row.setdefault("oversees_teams", [])
                row.setdefault("sort", 0)
                if any(r["business_id"] == row["business_id"] and r["key"] == row["key"] for r in have):
                    continue  # unique (business_id, key): ignore-duplicates
            if table == "church_role_settings":
                old = next((r for r in have if r["business_id"] == row["business_id"]), None)
                if old:
                    old.update(row)
                    out.append(dict(old))
                    continue
            have.append(row)
            self.writes.append(("POST", table, row))
            out.append(dict(row))
        return out

    def patch(self, path, body, **_):
        table, filters, _ = self._parse(path)
        out = []
        for r in self.t.get(table, []):
            if self._match(r, filters):
                r.update(body)
                out.append(dict(r))
        self.writes.append(("PATCH", table, body))
        return out

    def delete(self, path, **_):
        table, filters, _ = self._parse(path)
        self.t[table] = [r for r in self.t.get(table, []) if not self._match(r, filters)]
        return True


CHURCH = {"id": BIZ, "name": "Love City Church", "type": "ministry"}
COURSE = "c0000000-0000-0000-0000-000000000001"


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        contacts=[{"id": k, "business_id": BIZ, "name": v, "email": f"{v.split()[0].lower()}@example.com", "phone": "555-0100"}
                  for k, v in NAMES.items()],
        church_leader_roles=[_role(PASTOR, "pastor"), _role(MINISTER, "baptism_minister"),
                             _role(TASHA, "team_leader", "Hospitality Team"), _role(ROBERT, "welcome_lead")],
        church_follow_ups=[], church_follow_up_notes=[], events=[], church_role_defs=[], church_role_settings=[],
        ministry_care_requests=[], academy_enrollments=[],
        academy_courses=[{"id": COURSE, "business_id": BIZ, "title": "The Making: Leaders", "status": "published"}],
        intake_forms=[dict(f, business_id=BIZ) for f in (BAPTISM, SERVE, VISIT, TRIP)],
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER}],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "html_content": "<h1>Love City Church</h1>",
                         "site_config": {"custom_domain": "lovecityc.com"}}],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    return fake


def _defs(db):
    return {d["key"]: d for d in db.t["church_role_defs"] if d["status"] != "archived"}


# ─── Chief's guess at the church type ─────────────────────────────────

@pytest.mark.parametrize("name,want", [
    ("Greater Mt. Zion Missionary Baptist Church", "baptist"),
    ("Holy Temple Church of God in Christ", "cogic"),
    ("Bethel AME Church", "ame"),
    ("First Presbyterian Church", "presby"),
    ("Westside Church of Christ", "coc"),
    ("St. Mark's Episcopal Church", "liturgical"),
    ("Love City Church", "nondenom"),
])
def test_a_name_that_names_its_tradition_settles_the_type(name, want):
    assert cr.guess_type(name, [])[0] == want


def test_the_website_decides_only_when_the_name_is_silent_and_it_says_so_twice():
    assert cr.guess_type("Grace Church", ["<p>We are a Baptist church.</p>"])[0] == "nondenom"
    key, why = cr.guess_type("Grace Church", ["<p>We are a Baptist church.</p><p>Baptist since 1921.</p>"])
    assert key == "baptist" and "website" in why
    key, why = cr.guess_type("Love City Church", ["<script>baptist baptist</script><p>Welcome home</p>"])
    assert key == "nondenom" and "No denomination" in why, "script text is not the website's words"


# ─── Filling the library ──────────────────────────────────────────────

def test_love_city_gets_the_non_denominational_titles_its_intercessor_leader_and_its_chain(db):
    st = cr.ensure_library(CHURCH)
    assert st["church_type"] == "nondenom" and st["guessed_type"] == "nondenom"
    d = _defs(db)
    for key in ("pastor", "associate_pastor", "elders", "ministers", "intercessor_leader", "intercessors", "deacons",
                "youth_pastor", "team_leader", "welcome_lead", "administrator", "treasurer"):
        assert key in d, key
    assert d["pastor"]["job"] == "senior" and d["pastor"]["title"] == "Lead Pastor"
    assert d["intercessor_leader"]["job"] == "prayer" and d["intercessor_leader"]["handles"] == ["prayer_shared"]
    assert "Love City Church in prayer" in d["intercessor_leader"]["definition"]
    assert d["intercessors"]["reports_to"] == d["intercessor_leader"]["id"]
    assert d["intercessor_leader"]["reports_to"] == d["pastor"]["id"]
    assert d["team_leader"]["covers"] == "team" and d["team_leader"]["reports_to"] == d["associate_pastor"]["id"]
    assert d["welcome_lead"]["oversees_teams"] == ["Hospitality Team"]
    assert d["youth_pastor"]["oversees_teams"] == ["Youth Ministry (YWD)"]
    # A key the church already gave someone is kept as a role of its own.
    assert d["baptism_minister"]["job"] == "pastoral" and d["baptism_minister"]["handles"] == ["baptism"]
    assert d["pastor"]["reports_to"] is None


def test_filling_twice_adds_nothing(db):
    cr.ensure_library(CHURCH)
    n = len(db.t["church_role_defs"])
    cr.ensure_library(CHURCH)
    assert len(db.t["church_role_defs"]) == n


def test_a_failed_read_fills_nothing(db, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith("/church_role_settings") else real(p))
    assert cr.ensure_library(CHURCH) is None and db.t["church_role_defs"] == []


# ─── Making and changing a role ───────────────────────────────────────

def test_a_church_mother_is_made_on_the_care_job_and_answers_to_the_senior_role(db):
    cr.ensure_library(CHURCH)
    row = cr.create_role(CHURCH, {"title": "Church Mother", "job": "care"})
    d = _defs(db)
    assert row["key"] == "church_mother" and row["handles"] == ["care_need"]
    assert row["reports_to"] == d["pastor"]["id"]
    assert row["definition"].startswith("Church Mother serves the church’s care needs")
    again = cr.create_role(CHURCH, {"title": "Church Mother", "job": "care"})
    assert again["key"] == "church_mother_2", "a second one never takes the first one's key"


def test_a_role_is_only_handed_what_its_job_allows_and_a_senior_role_always_takes_the_rest(db):
    cr.ensure_library(CHURCH)
    row = cr.create_role(CHURCH, {"title": "Hospital visitor", "job": "care", "handles": ["baptism", "care_need", "serve"]})
    assert row["handles"] == ["care_need"]
    sen = cr.create_role(CHURCH, {"title": "Co-Pastor", "job": "senior", "handles": []})
    assert sen["handles"] == ["leftover"]
    with pytest.raises(Exception) as e:
        cr.create_role(CHURCH, {"title": "Wizard", "job": "wizard"})
    assert e.value.status_code == 400


def test_the_chain_never_loops(db):
    cr.ensure_library(CHURCH)
    d = _defs(db)
    with pytest.raises(Exception) as e:
        cr.update_role(BIZ, d["intercessor_leader"]["id"], {"reports_to": d["intercessors"]["id"]})
    assert e.value.status_code == 400 and "answer to itself or to someone who answers to it" in e.value.detail
    with pytest.raises(Exception):
        cr.update_role(BIZ, d["elders"]["id"], {"reports_to": d["elders"]["id"]})
    cr.update_role(BIZ, d["intercessors"]["id"], {"reports_to": d["elders"]["id"]})
    assert _defs(db)["intercessors"]["reports_to"] == d["elders"]["id"]


def test_the_last_senior_role_stays_and_a_role_with_people_in_it_is_not_archived(db):
    cr.ensure_library(CHURCH)
    d = _defs(db)
    with pytest.raises(Exception) as e:
        cr.update_role(BIZ, d["pastor"]["id"], {"job": "care"})
    assert e.value.status_code == 400
    with pytest.raises(Exception) as e:
        cr.archive_role(BIZ, d["welcome_lead"]["id"])
    assert e.value.status_code == 400 and "Take the people out" in e.value.detail
    with pytest.raises(Exception) as e:
        cr.update_role(BIZ, d["team_leader"]["id"], {"covers": "church"})
    assert e.value.status_code == 400


def test_archiving_a_role_hands_the_roles_under_it_to_the_one_above(db):
    cr.ensure_library(CHURCH)
    d = _defs(db)
    assert cr.archive_role(BIZ, d["intercessor_leader"]["id"]) == {"archived": True}
    assert _defs(db)["intercessors"]["reports_to"] == d["pastor"]["id"]
    assert "intercessor_leader" not in {x["key"] for x in cr.defs(BIZ)}


def test_a_chief_draft_hands_nobody_anything_and_is_discarded_outright(db):
    cr.ensure_library(CHURCH)
    row = cr.chief_draft(CHURCH, "Armor Bearer")
    assert row["status"] == "draft" and row["source"] == "chief" and row["job"] == "team"
    assert "armor_bearer" not in {x["key"] for x in cr.defs(BIZ)}, "routing never sees a draft"
    with pytest.raises(Exception) as e:
        cfu.add_role(BIZ, DANA, row["id"], by_user=OWNER)
    assert e.value.status_code == 400 and "draft" in e.value.detail
    assert cr.archive_role(BIZ, row["id"]) == {"deleted": True}
    assert "armor_bearer" not in {x["key"] for x in db.t["church_role_defs"]}


@pytest.mark.parametrize("title,job", [("Church Mother", "care"), ("Deacon Board", "care"), ("Intercessors", "prayer"),
                                       ("Youth Pastor", "ministry"), ("Usher Board president", "team"),
                                       ("Trustees", "office"), ("Lead Pastor", "senior")])
def test_chief_knows_the_job_a_title_does(title, job):
    assert cr.job_for_title(title) == job


def test_the_church_type_adds_only_the_titles_picked_and_takes_none_away(db):
    cr.ensure_library(CHURCH)
    before = set(_defs(db))
    out = cr.set_type(CHURCH, "baptist", ["mothers_board", "deacons", "trustees"], by_user=OWNER)
    after = _defs(db)
    assert out["added"] == 2 and set(after) == before | {"mothers_board", "trustees"}
    assert after["deacons"]["title"] == "Deacons", "a role already there is left as it is"
    assert db.t["church_role_settings"][0]["church_type"] == "baptist"
    assert db.t["church_role_settings"][0]["set_by"] == "owner"


# ─── Who gets a card, on the church's own roles ───────────────────────

def _choose(db, kind, answers):
    return cfu.choose(kind, answers, cfu.roles(BIZ), {}, cr.defs(BIZ))


def test_a_care_need_on_a_connect_card_goes_to_a_care_role_and_a_team_name_is_never_a_hospital(db):
    cr.ensure_library(CHURCH)
    db.t["church_leader_roles"].append(_role(KEISHA, "deacons"))
    pick = _choose(db, "connect", [{"q": "Anything else?", "a": "My mom is in the hospital after surgery"}])
    assert pick["leader"]["contact_id"] == KEISHA and pick["reason"] == \
        "Their card mentions a care need. Care needs go to the Deacons."
    pick = _choose(db, "serve", [{"q": "Where would you like to serve?", "a": "Hospitality Team"}])
    assert pick["leader"]["contact_id"] == TASHA


def test_a_team_with_no_leader_goes_to_the_role_it_is_under_then_up_the_chain(db):
    cr.ensure_library(CHURCH)
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["contact_id"] != TASHA]
    pick = _choose(db, "serve", [{"q": "Where would you like to serve?", "a": "Hospitality Team"}])
    assert pick["leader"]["contact_id"] == ROBERT and "under the Welcome Team lead" in pick["reason"]
    pick = _choose(db, "serve", [{"q": "Where would you like to serve?", "a": "Graphic and web design"}])
    assert pick["leader"]["contact_id"] == PASTOR, "no team role, no Associate Pastor: the Lead Pastor"
    db.t["church_leader_roles"].append(_role(MARCUS, "associate_pastor"))
    pick = _choose(db, "serve", [{"q": "Where would you like to serve?", "a": "Graphic and web design"}])
    assert pick["leader"]["contact_id"] == MARCUS and pick["reason"] == \
        "Graphic and web design has no leader yet, so it goes to the Associate Pastor."


def test_a_role_made_for_a_card_comes_before_a_broader_one(db):
    cr.ensure_library(CHURCH)
    db.t["church_leader_roles"].append(_role(KEISHA, "ministers"))
    pick = _choose(db, "baptism", [])
    assert pick["leader"]["contact_id"] == MINISTER and pick["reason"] == "Baptism cards go to the Baptism minister."
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["contact_id"] != MINISTER]
    assert _choose(db, "baptism", [])["leader"]["contact_id"] == KEISHA


def test_asking_for_a_pastor_goes_to_a_pastoral_role_before_the_lead_pastor(db):
    cr.ensure_library(CHURCH)
    ask = [{"q": "Have you given your life to Jesus?", "a": "I’d like to talk with a pastor"}]
    assert _choose(db, "baptism", ask)["leader"]["contact_id"] == PASTOR
    db.t["church_leader_roles"].append(_role(MARCUS, "elders"))
    pick = _choose(db, "baptism", ask)
    assert pick["leader"]["contact_id"] == MARCUS and pick["reason"] == "They asked to talk with a pastor."


def test_the_chain_passes_over_an_empty_role_and_ends_at_the_senior_role(db):
    cr.ensure_library(CHURCH)
    all_defs = cr.defs(BIZ)
    held = cr.active_holders(cfu.roles(BIZ))
    d = cr.by_key(all_defs)
    above = cr.chain_above(d["team_leader"], all_defs, held, team="Hospitality Team", skip={TASHA})
    assert [(r["key"], [h["contact_id"] for h in people]) for r, people in above] == \
        [("welcome_lead", [ROBERT]), ("pastor", [PASTOR])]
    above = cr.chain_above(d["intercessors"], all_defs, held)
    assert [r["key"] for r, _ in above] == ["pastor"], "an Intercessor leader no one holds is passed over"


# ─── Asking someone ───────────────────────────────────────────────────

def test_a_role_that_needs_a_class_waits_until_they_finish_it(db):
    cr.ensure_library(CHURCH)
    d = _defs(db)
    cr.update_role(BIZ, d["intercessor_leader"]["id"], {"needs_class": COURSE})
    with pytest.raises(Exception) as e:
        cfu.add_role(BIZ, DANA, d["intercessor_leader"]["id"], by_user=OWNER)
    assert e.value.status_code == 400 and e.value.detail == "Dana hasn’t finished The Making: Leaders yet"
    db.t["academy_enrollments"].append({"id": "e1", "business_id": BIZ, "contact_id": DANA, "course_id": COURSE,
                                        "completed_at": "2026-10-01T00:00:00+00:00"})
    row = cfu.add_role(BIZ, DANA, d["intercessor_leader"]["id"], by_user=OWNER)
    assert row["role"] == "intercessor_leader" and row["status"] == "invited"


def test_office_and_kids_roles_are_not_asked_through_the_member_page(db):
    cr.ensure_library(CHURCH)
    d = _defs(db)
    with pytest.raises(Exception) as e:
        cfu.add_role(BIZ, DANA, d["treasurer"]["id"], by_user=OWNER)
    assert "office login" in e.value.detail
    kid = cr.create_role(CHURCH, {"title": "Nursery worker", "job": "kids"})
    with pytest.raises(Exception) as e:
        cfu.add_role(BIZ, DANA, kid["id"], by_user=OWNER)
    assert "Kids check-in" in e.value.detail


def test_the_invitation_says_what_the_role_is_and_who_they_answer_to(db, monkeypatch):
    cr.ensure_library(CHURCH)
    d = _defs(db)
    sent = []

    async def email(biz, to, name, subject, body, key):
        sent.append((to, subject, body))
        return True
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(cfu, "site_origin", lambda b: "https://lovecityc.com")
    row = cfu.add_role(BIZ, DANA, d["intercessor_leader"]["id"], by_user=OWNER)
    assert asyncio.run(cfu.send_invite(CHURCH, row)) is True
    to, subject, body = sent[0]
    assert to == "dana@example.com" and subject == "Will you be Love City Church’s Intercessor leader?"
    assert "Leads Love City Church in prayer" in body and "answer to the Lead Pastor" in body
    assert "https://lovecityc.com/my/lead" in body
    team = cfu.add_role(BIZ, MARCUS, d["team_leader"]["id"], "Hospitality Team", by_user=OWNER)
    asyncio.run(cfu.send_invite(CHURCH, team))
    assert sent[1][1] == "Will you lead the Hospitality Team at Love City Church?"


def test_saying_yes_to_a_role_with_a_term_starts_it_and_the_office_hears_when_it_ends(db, monkeypatch):
    cr.ensure_library(CHURCH)
    d = _defs(db)
    cr.update_role(BIZ, d["deacons"]["id"], {"term_months": 12})
    row = cfu.add_role(BIZ, KEISHA, d["deacons"]["id"], by_user=OWNER)
    assert cfu.answer_invite(BIZ, KEISHA, row["id"], True)
    held = next(r for r in db.t["church_leader_roles"] if r["id"] == row["id"])
    ends = cfu._parse(held["term_ends_at"])
    assert 360 <= (ends - cfu._now()).days <= 366
    alerts = []

    async def alert(biz_id, title, body, key, person):
        alerts.append(title)
        return True
    monkeypatch.setattr(cfu, "_office_alert", alert)
    asyncio.run(cfu._sweep_terms(ends + timedelta(days=1)))
    asyncio.run(cfu._sweep_terms(ends + timedelta(days=2)))
    assert alerts == ["Keisha Morgan’s term as Deacons has ended"], "said once"


# ─── What Chief reads ─────────────────────────────────────────────────

def test_chief_reads_the_roles_and_never_fills_the_library_itself(db):
    lines = cr.chief_lines(CHURCH)
    assert db.t["church_role_defs"] == [], "a read writes nothing"
    joined = "\n".join(lines)
    assert "Lead Pastor [job: Senior pastor] held by Kevin McCloud" in joined
    assert "Team leader [job: Team leader] held by Tasha Williams (Hospitality Team)" in joined
    cr.ensure_library(CHURCH)
    joined = "\n".join(cr.chief_lines(CHURCH))
    assert "Intercessor leader [job: Prayer] held by no one yet; answers to Lead Pastor" in joined
    assert "Graphic and web design (no leader: sign-ups go up the chain)" in joined
    assert "Never repeat a prayer request's words" in joined


def test_chiefs_draft_action_says_it_is_a_draft(db, monkeypatch):
    import chief_church_actions as cca
    monkeypatch.setattr(cca, "_caller_role", lambda biz: "owner")
    cr.ensure_library(CHURCH)
    out = asyncio.run(cca.handle_draft_church_role(None, CHURCH, {"type": "draft_church_role", "title": "Church Mother"}))
    assert out["label"] == "Drafted “Church Mother”" and "hands nobody anything until the owner saves it" in out["result"]
    assert out["nav"] == {"tab": "operate", "sub": "leaders"}
    leaders = asyncio.run(cca.handle_church_people(None, CHURCH, {"section": "leaders"}))
    assert leaders["label"] == "Leaders & roles" and "Church Mother" not in leaders["result"], "drafts aren't roles yet"


# ─── The routes ───────────────────────────────────────────────────────

@pytest.fixture
def office(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    import church_router
    who = {"role": "owner"}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: who["role"])

    async def invite(biz, row):
        return True
    monkeypatch.setattr(cfu, "send_invite", invite)
    app = FastAPI()
    app.include_router(church_router.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=OWNER, email="kevin@example.com", user_metadata={})))
    client = TestClient(app)
    client.who = who
    return client


def test_the_library_reads_whole_and_fills_once(office, db):
    r = office.get(f"/church/leaders?business_id={BIZ}")
    assert r.status_code == 200
    lib = r.json()
    assert lib["church_type"]["key"] == "nondenom" and lib["church_type"]["set_by"] == "chief"
    assert lib["job_order"][0] == "senior" and set(lib["jobs"]["prayer"]["allowed"]) == {"prayer_shared", "prayer_passed"}
    il = next(x for x in lib["roles"] if x["key"] == "intercessor_leader")
    assert il["is_new"] and il["holders"] == [] and il["reports_to_title"] == "Lead Pastor"
    pastor = next(x for x in lib["roles"] if x["key"] == "pastor")
    assert [h["name"] for h in pastor["holders"]] == ["Kevin McCloud"]
    assert [t["key"] for t in lib["types"]] == list(cr.TYPE_ORDER)
    assert next(t for t in lib["types"] if t["key"] == "nondenom")["rows"][0]["in_library"] is True
    assert lib["classes"] == [{"id": COURSE, "title": "The Making: Leaders"}]
    n = len(db.t["church_role_defs"])
    office.get(f"/church/leaders?business_id={BIZ}")
    assert len(db.t["church_role_defs"]) == n


def test_the_office_makes_changes_and_archives_a_role(office, db):
    office.get(f"/church/leaders?business_id={BIZ}")
    r = office.post(f"/church/roles?business_id={BIZ}", json={"title": "Church Mother", "job": "care"})
    assert r.status_code == 200 and r.json()["role"]["key"] == "church_mother"
    rid = r.json()["role"]["id"]
    r = office.patch(f"/church/roles/{rid}?business_id={BIZ}", json={"definition": "Mothers the church.", "term_months": 24})
    assert r.json()["role"]["definition"] == "Mothers the church." and r.json()["role"]["term_months"] == 24
    assert office.delete(f"/church/roles/{rid}?business_id={BIZ}").json() == {"ok": True, "archived": True}
    r = office.post(f"/church/type?business_id={BIZ}", json={"type": "cogic", "add": ["church_mother", "armor_bearers"]})
    assert r.json()["added"] == 1 and r.json()["church_type"]["key"] == "cogic", \
        "church_mother's key is archived, so only Armor Bearers is new"
    r = office.post(f"/church/leaders?business_id={BIZ}",
                    json={"contact_id": DANA, "role_id": _defs(db)["intercessor_leader"]["id"]})
    assert r.status_code == 200 and r.json()["status"] == "invited"


def test_a_member_seat_reads_and_changes_no_roles(office, db):
    office.who["role"] = "member"
    assert office.get(f"/church/leaders?business_id={BIZ}").status_code == 404
    assert office.post(f"/church/roles?business_id={BIZ}", json={"title": "X", "job": "care"}).status_code == 404
    assert office.post(f"/church/type?business_id={BIZ}", json={"type": "baptist"}).status_code == 404
    assert db.t["church_role_defs"] == []


@pytest.mark.parametrize("seat", ["member", "viewer", None])
def test_chief_gives_the_leaders_and_drafts_only_to_the_seats_the_page_allows(db, monkeypatch, seat):
    """Review of #1477: the same seats as Leaders & roles (owner, admin,
    manager). An outside agent has no seat at all."""
    import chief_church_actions as cca
    monkeypatch.setattr(cca, "_caller_role", lambda biz: seat)
    out = asyncio.run(cca.handle_church_people(None, CHURCH, {"section": "leaders"}))
    assert out["result"].startswith("refused") and "Kevin" not in out["result"]
    out = asyncio.run(cca.handle_draft_church_role(None, CHURCH, {"type": "draft_church_role", "title": "Church Mother"}))
    assert out.get("failed") and db.t["church_role_defs"] == []


def test_a_failed_read_never_cuts_the_roles_below_off_the_chain(db, monkeypatch):
    """Review of #1477: archiving reads who the role answered to; a read
    that fails stops it instead of setting everyone below to no one."""
    cr.ensure_library(CHURCH)
    d = _defs(db)
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith(f"/church_role_defs?id=eq.{d['intercessor_leader']['id']}&business_id")
                        and "select=reports_to" in p else real(p))
    with pytest.raises(Exception) as e:
        cr.archive_role(BIZ, d["intercessor_leader"]["id"])
    assert e.value.status_code == 503
    assert _defs(db)["intercessors"]["reports_to"] == d["intercessor_leader"]["id"]
    assert _defs(db)["intercessor_leader"]["status"] == "active"


def test_a_late_step_climbs_only_when_the_person_above_was_told(db, monkeypatch):
    """Review of #1477: the office's alert alone isn't the rung; the email
    to the role above has to go out too, or the next sweep tries again."""
    cr.ensure_library(CHURCH)
    f = cfu.on_intake_form(CHURCH, SERVE, {"team": "Hospitality Team"}, DANA)
    down = {"robert": True}

    async def email(biz, to, name, subject, body, key):
        return not (down["robert"] and to.startswith("robert"))

    async def alert(biz_id, title, body, key, person):
        return True
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(cfu, "_office_alert", alert)
    asyncio.run(cfu.sweep())
    row = next(r for r in db.t["church_follow_ups"] if r["id"] == f["id"])
    due = cfu._parse(row["due_at"])
    asyncio.run(cfu.sweep(now=due + timedelta(hours=1)))
    asyncio.run(cfu.sweep(now=due + timedelta(days=1, hours=1)))
    assert row["late_level"] == 1, "Robert's email failed: not climbed"
    down["robert"] = False
    asyncio.run(cfu.sweep(now=due + timedelta(days=1, hours=2)))
    assert row["late_level"] == 2

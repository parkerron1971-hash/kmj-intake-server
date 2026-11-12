"""Church job descriptions through the real routes (church_job_descriptions.py;
docs/CHURCH_JOB_DESCRIPTIONS.md), at the test churches (church_three).

Pins:
  * every route needs a seat at the church; the roster and whose are the office
    seats' (Manager and up); a Member reads only their own and whoever they're
    over; a Viewer nothing
  * one person's job, the draft, whose job some work is
  * write: the owner or someone over them; an office seat never a pastor's or
    an elder's; pay refused; clear and undo; every write answers with what it
    saved
  * before the file is applied every route is a 503 that says it isn't ready; a
    failed read is a 503; the switch off is a 404
  * the migration: new server-only tables, the #1801 habit, nothing dropped
  * words: stop words out, light stemming
"""
from __future__ import annotations

import os
import re
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_job_descriptions as cjd  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_three import LOVE_CITY  # noqa: E402

MEMBER = "1a000000-0000-4000-8000-000000000444"
VIEWER = "1a000000-0000-4000-8000-000000000555"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    d = c3.build(monkeypatch)
    d.t["church_job_descriptions"], d.t["church_job_description_changes"] = [], []
    for u, role in ((MEMBER, "member"), (VIEWER, "viewer")):
        d.t["business_users"].append({"business_id": LOVE_CITY, "user_id": u, "role": role,
                                      "invited_email": f"{role}@lovecity.org", "lane": None, "areas": None,
                                      "contact_id": None, "name": role.title(), "status": "active"})
    monkeypatch.setattr(cjd, "_READY", {})
    return d


@pytest.fixture
def app(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    a = FastAPI()
    a.include_router(cjd.router)
    who = {"id": None, "email": None}
    a.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
    c = TestClient(a)
    c.who, c.db = who, db
    return c


def uid(db, handle):
    if handle in (MEMBER, VIEWER):
        return handle
    return c3.church(db, LOVE_CITY)["owner_id"] if handle == "owner" else db.who[LOVE_CITY][handle + "@"]


def as_(app, handle):
    u = uid(app.db, handle)
    seat = next((s for s in app.db.t["business_users"] if s["user_id"] == u), None)
    app.who.update(id=u, email=seat["invited_email"] if seat else c3.OWNER_EMAIL[u])


def cid(db, handle):
    return db.who[LOVE_CITY][handle]


def put(app, handle, **body):
    return app.put("/church/jobs/person", json={"business_id": LOVE_CITY, "contact_id": cid(app.db, handle), **body})


# ─── Reads ────────────────────────────────────────────────────────────

def test_the_roster_is_everyone_once_in_order_for_the_office_seats(app):
    as_(app, "jessica")
    r = app.get("/church/jobs", params={"business_id": LOVE_CITY})
    assert r.status_code == 200, r.text
    people = r.json()["people"]
    names = [p["name"] for p in people]
    assert names[0] == "Kevin McCloud", "the owner first, as their person"
    assert names[1] == "Minnie Tatum", "then the office logins, the Admins first"
    assert len(names) == len(set(names)) and r.json()["more"] == 0
    naiya = next(p for p in people if p["name"] == "Naiya Clark")
    assert naiya["for"] == f"person:{cid(app.db, 'naiya')}" and naiya["title"] == "Office & Leadership"
    assert naiya["written"] is False and naiya["line"].startswith("Naiya Clark (Office & Leadership): does The front desk")
    assert {"Marcus Taylor", "Ruth Okafor", "Tasha Williams"} <= set(names), "the leaders, by role or department"
    for who in (MEMBER, VIEWER):
        as_(app, who)
        assert app.get("/church/jobs", params={"business_id": LOVE_CITY}).status_code in (403, 404), who


def test_one_persons_job_and_the_draft(app):
    as_(app, "naiya")
    r = app.get("/church/jobs/person", params={"business_id": LOVE_CITY, "contact_id": cid(app.db, "jessica")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["title"] == "Executive Pastor" and [d["key"] for d in j["duties"]] == ["monthly_report", "oversee_lanes"]
    assert j["covers"] is True and j["over"] == ["Pastor Kevin"] and j["can_write"] is False
    assert j["roles"][0]["title"] == "Executive Pastor" and j["roles"][0]["definition"]
    d = app.get("/church/jobs/draft", params={"business_id": LOVE_CITY, "contact_id": cid(app.db, "marcus")}).json()
    assert d["source"] == "drafted" and d["title"] == "Elders"
    assert d["description"].startswith("Summary\nElders. Answers to Jessica McCloud.\nThe Elders pray for the church")
    assert d["description"].endswith("On Sunday\nNo Sunday duty in the system yet.\n" + cjd.SUNDAY_TIMES)
    assert app.db.t["church_job_descriptions"] == []


def test_whose_job_through_the_route(app):
    as_(app, "owner")
    assert put(app, "laquesha", title="Facilities lead",
               description="The building, keys, fire extinguishers and safety.").status_code == 200
    r = app.get("/church/jobs/whose", params={"business_id": LOVE_CITY, "q": "fire extinguishers before December"})
    assert r.status_code == 200, r.text
    m = r.json()["matches"][0]
    assert m["person"]["name"] == "Laquesha Bailey-Smith" and m["can_give"] is True
    assert m["matched"] == [{"words": ["fire", "extinguishers"], "where": "their written job description"}]
    assert m["lines"] == ["The building, keys, fire extinguishers and safety."]
    assert "description" not in m["person"] and m["person"]["excerpt"].startswith("The building, keys")
    roster = app.get("/church/jobs", params={"business_id": LOVE_CITY}).json()["people"]
    assert all("description" not in p for p in roster), "the roster carries excerpts, never the whole"
    one = app.get("/church/jobs/person", params={"business_id": LOVE_CITY, "contact_id": cid(app.db, "laquesha")})
    assert one.json()["description"] == "The building, keys, fire extinguishers and safety."
    assert m["over"] == ["Jessica McCloud"] and r.json()["fallback"] is None
    assert app.get("/church/jobs/whose", params={"business_id": LOVE_CITY, "q": "the"}).status_code == 400


def test_a_member_reads_only_their_own_and_a_viewer_nothing(app):
    as_(app, MEMBER)
    assert app.get("/church/jobs/whose", params={"business_id": LOVE_CITY, "q": "weekly text"}).status_code == 403
    r = app.get("/church/jobs/person", params={"business_id": LOVE_CITY, "contact_id": cid(app.db, "naiya")})
    assert r.status_code == 403
    assert app.get("/church/jobs/draft", params={"business_id": LOVE_CITY,
                                                 "contact_id": cid(app.db, "naiya")}).status_code == 403
    own = app.get("/church/jobs/person", params={"business_id": LOVE_CITY, "user_id": MEMBER})
    assert own.status_code == 200 and own.json()["name"] == "Member"
    as_(app, VIEWER)
    for path, params in (("/church/jobs/person", {"user_id": VIEWER}), ("/church/jobs", {})):
        assert app.get(path, params={"business_id": LOVE_CITY, **params}).status_code == 404, path


# ─── Writes ───────────────────────────────────────────────────────────

def test_a_write_answers_with_what_it_saved_and_undo_puts_it_back(app):
    as_(app, "jessica")
    r = put(app, "naiya", title="Office Manager", description="Runs the front desk.", source="said")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["saved"]["description"] == "Runs the front desk." and got["saved"]["title"] == "Office Manager"
    assert got["saved"]["updated_by"] == "Jessica McCloud" and got["can_undo"] is True and got["change_id"]
    r = put(app, "naiya", description="Runs the front desk and the calendar.")
    assert r.json()["saved"]["title"] == "Office Manager", "no title said keeps the written one"
    log = app.db.t["church_job_description_changes"]
    assert log[-1]["before"]["description"] == "Runs the front desk."
    assert log[-1]["after"]["description"] == "Runs the front desk and the calendar."
    back = app.post("/church/jobs/person/undo", json={"business_id": LOVE_CITY, "contact_id": cid(app.db, "naiya")})
    assert back.status_code == 200 and back.json()["saved"]["description"] == "Runs the front desk."
    gone = app.post("/church/jobs/person/undo", json={"business_id": LOVE_CITY, "contact_id": cid(app.db, "naiya")})
    assert gone.status_code == 400 and "only the last change" in gone.json()["detail"]
    cleared = put(app, "naiya", clear=True)
    assert cleared.status_code == 200 and cleared.json()["cleared"] is True and cleared.json()["saved"]["written"] is False
    assert app.db.t["church_job_descriptions"] == []


def test_an_office_seat_cant_write_a_pastors_and_pay_stays_out(app):
    as_(app, "minnie")
    for who in ("andre", "marcus", "kevin"):
        r = put(app, who, description="Leads the retreat.")
        assert r.status_code == 403, who
    assert "no office seat is over a pastor or an elder" in put(app, "andre", description="x").json()["detail"]
    as_(app, "jessica")
    r = put(app, "naiya", description="Front desk at $15 per hour.")
    assert r.status_code == 400 and r.json()["detail"] == cjd.PAY
    assert put(app, "naiya", description="x", source="emailed").status_code == 400
    assert put(app, "naiya", description="x" * 8001).status_code == 400
    assert put(app, "naiya", title="x" * 81, description="x").status_code == 400
    assert app.db.t["church_job_descriptions"] == []
    as_(app, "naiya")
    assert put(app, "tiara", description="Care.").status_code == 403, "a lane's Manager is over no one"
    as_(app, MEMBER)
    assert app.put("/church/jobs/person", json={"business_id": LOVE_CITY, "user_id": MEMBER,
                                                "description": "x"}).status_code == 403, "not your own either"


def test_someone_who_isnt_the_churchs_is_a_404(app):
    as_(app, "owner")
    other = c3.pid(2, 2)                                   # one of Grace's people
    assert app.put("/church/jobs/person", json={"business_id": LOVE_CITY, "contact_id": other,
                                                "description": "x"}).status_code == 404
    assert app.get("/church/jobs/person", params={"business_id": LOVE_CITY,
                                                  "user_id": c3.G_OWNER}).status_code == 404
    assert app.get("/church/jobs/person", params={"business_id": LOVE_CITY}).status_code == 400


# ─── Not ready, a failed read, the switch ─────────────────────────────

def test_before_the_file_every_route_says_it_isnt_ready(app, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_job_desc") else real(path, **kw))
    as_(app, "owner")
    for r in (app.get("/church/jobs", params={"business_id": LOVE_CITY}),
              app.get("/church/jobs/whose", params={"business_id": LOVE_CITY, "q": "weekly text"}),
              app.get("/church/jobs/person", params={"business_id": LOVE_CITY, "contact_id": cid(app.db, "naiya")}),
              app.get("/church/jobs/draft", params={"business_id": LOVE_CITY, "contact_id": cid(app.db, "naiya")}),
              put(app, "naiya", description="x"),
              app.post("/church/jobs/person/undo", json={"business_id": LOVE_CITY, "contact_id": cid(app.db, "naiya")})):
        assert r.status_code == 503 and r.json()["detail"] == cjd.NOT_READY, r.text


def test_a_failed_read_is_a_503_never_a_yes(app, monkeypatch):
    as_(app, "jessica")
    assert app.get("/church/jobs", params={"business_id": LOVE_CITY}).status_code == 200      # ready, remembered
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_job_descriptions?business_id")
                        else real(path, **kw))
    assert app.get("/church/jobs", params={"business_id": LOVE_CITY}).status_code == 503
    assert put(app, "naiya", description="x").status_code == 503
    assert app.db.t["church_job_descriptions"] == []
    # Who is over whom unread: a 503, never a yes.
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_leader_roles") else real(path, **kw))
    assert put(app, "naiya", description="x").status_code == 503


def test_the_switch_off_is_a_404(app, monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    as_(app, "owner")
    assert app.get("/church/jobs", params={"business_id": LOVE_CITY}).status_code == 404


# ─── The migration, the words ─────────────────────────────────────────

def test_the_migration_is_new_server_only_tables_and_drops_nothing():
    sql = open(os.path.join(ROOT, "supabase", "APPLY-2026-11-12-church-job-descriptions.sql"), encoding="utf-8").read()
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert body.strip().startswith("begin;") and body.rstrip().endswith("commit;")
    assert not re.search(r"\bdrop\s+(table|column)\b", body, re.I)
    for t in ("church_job_descriptions", "church_job_description_changes"):
        assert f"create table if not exists public.{t}(" in body
        assert f"alter table public.{t} enable row level security" in body
        assert f"revoke all on public.{t} from anon, authenticated" in body
    assert "create policy" not in body
    assert re.search(r"create unique index if not exists church_job_descriptions_person\s+on public\."
                     r"church_job_descriptions \(business_id, contact_id\)\s+where contact_id is not null", body)
    assert re.search(r"create unique index if not exists church_job_descriptions_login\s+on public\."
                     r"church_job_descriptions \(business_id, user_id\)\s+where contact_id is null", body)
    for name in ("church_job_descriptions_contact_id_fkey", "church_job_descriptions_someone",
                 "church_job_descriptions_words", "church_job_description_changes_someone"):
        assert re.search(rf"add constraint {name}\b[^;]*\bnot valid;", body, re.S), name
    assert "('said', 'pasted', 'document', 'drafted')" in body and set(cjd.SOURCES) == {"said", "pasted", "document",
                                                                                         "drafted"}
    assert "between 1 and 80" in body and "between 1 and 8000" in body
    assert (cjd.TITLE_MAX, cjd.DESCRIPTION_MAX) == (80, 8000)


def test_words_drop_stop_words_and_stem_lightly():
    assert [w for w, _st in cjd.terms("Whose job is the fire extinguishers before December?")] == [
        "fire", "extinguishers", "december"]
    assert dict(cjd.terms("inspecting policies rooms boxes"))["inspecting"] == "inspect"
    stems = {w: st for w, st in cjd.terms("inspecting policies rooms boxes")}
    assert stems == {"inspecting": "inspect", "policies": "policy", "rooms": "room", "boxes": "box"}
    assert cjd._hit("month", "monthly") and cjd._hit("pray", "prayer") and not cjd._hit("kid", "kit")
    assert not cjd.has_pay("Manages the $5k youth budget and the benefit dinner")
    assert cjd.has_pay("Salary: $40k") and cjd.has_pay("$20/hr") and cjd.has_pay("paid hourly")


def test_the_descriptions_go_with_the_church_and_their_log_stays_behind():
    import account_lifecycle as al
    order = {t: i for i, t in enumerate(al.BUSINESS_CHILD_TABLES)}
    assert order["church_job_descriptions"] < order["contacts"], "exported, before the people they cite"
    assert "church_job_descriptions" in al._IMPORT_SKIP, "they cite people by id: a restored church saves them again"
    assert "church_job_description_changes" in al.EXPORT_EXCLUDED

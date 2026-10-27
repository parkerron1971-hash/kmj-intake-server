"""The church register (church_register.py). Kevin 2026-10-27, on the Church
Office Prototypes ("Church register" tab): "lets go with your list".
Baptisms, dedications, weddings, funerals and membership dates, kept for
good, with certificates.

Pins:
  * by area: the owner, admins and People & care logins see everything (the
    asks too); an Office login sees the register without funerals or
    membership removals (not even their numbers), and can't add them; any
    other login is refused; a viewer reads and doesn't write
  * another church's entries, people and asks are unreachable
  * a member's life-event ask becomes an entry once, planned or done, and
    its Prayer & care row moves along (reviewed, then closed)
  * baptism dates from the Subsplash import are offered, never written on
    a read; one press adds each once; a removed one isn't offered again; a
    baptism recorded by hand covers the person
  * only the owner and admins remove an entry, and a removed entry stays on
    file, off the page and the numbers
  * the switch, and the table before its migration: nothing answers 500
  * a certificate says what the entry says and nothing from anyone's record
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas  # noqa: E402
import church_register as cr  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SALON = "33333333-3333-4333-8333-333333333333"
NAMES = ("owner", "admin", "carer", "clerk", "viewer", "singer", "stranger", "other_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
T0 = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
JORDAN = "cccccccc-0000-4000-8000-000000000001"
MIA = "cccccccc-0000-4000-8000-000000000002"
DANA = "cccccccc-0000-4000-8000-000000000003"
ANDRE = "cccccccc-0000-4000-8000-000000000004"
THEIR_PERSON = "cccccccc-0000-4000-8000-000000000009"
ASK = "dddddddd-0000-4000-8000-000000000001"
WEDDING_ASK = "dddddddd-0000-4000-8000-000000000002"
HELP_ASK = "dddddddd-0000-4000-8000-000000000003"
CLOSED_ASK = "dddddddd-0000-4000-8000-000000000004"
THEIR_ASK = "dddddddd-0000-4000-8000-000000000005"
FUNERAL_ASK = "dddddddd-0000-4000-8000-000000000006"


class RegisterDB(FakeDB):
    """The register's defaults and its two one-row rules, PostgREST's JSON
    filters (submission->>kind, metadata->>imported_from), array
    containment (contact_ids=cs.{id}) and the import's select alias."""

    ENTRY_DEFAULTS = {"membership": None, "status": "done", "people": [], "contact_ids": [], "officiant": None,
                      "place": None, "other_church": None, "notes": "", "source": "office", "care_request_id": None,
                      "import_key": None, "removed_at": None, "removed_by": None}

    def _match(self, row, filters):
        plain = []
        for f in filters:
            if f[0] != "or" and f[1] == "cs":
                want = set(f[2].strip("{}").split(",")) - {""}
                if not want <= {str(x) for x in (row.get(f[0]) or [])}:
                    return False
                continue
            if f[0] != "or" and "->>" in f[0]:
                base, key = f[0].split("->>", 1)
                v = (row.get(base) or {}).get(key) if isinstance(row.get(base), dict) else None
                row = {**row, f[0]: v}
            plain.append(f)
        return super()._match(row, plain)

    def _gone(self, path):
        return self.missing and path.lstrip("/").split("?")[0].startswith("church_register_")

    def get(self, path, **kw):
        """PostgREST's order, limit and offset too: the page reads its first
        and last years and reads long lists a page at a time."""
        if self._gone(path):
            return None
        self.reads.append(path)
        table, _, qs = path.lstrip("/").partition("?")
        parts = qs.split("&") if qs else []
        order = next((unquote(x[6:]) for x in parts if x.startswith("order=")), None)
        offset = next((int(x[7:]) for x in parts if x.startswith("offset=")), 0)
        limit = next((int(x[6:]) for x in parts if x.startswith("limit=")), None)
        rest = [x for x in parts if not x.startswith(("order=", "offset=", "limit="))]
        rows = super().get("/" + table + ("?" + "&".join(rest) if rest else ""), **kw)
        for spec in reversed((order or "").split(",") if order else []):
            col, _, way = spec.partition(".")
            rows.sort(key=lambda r: str(r.get(col) or ""), reverse=way.startswith("desc"))
        rows = rows[offset:offset + limit] if limit else rows[offset:]
        if "imported:metadata->imported" in path:
            rows = [{**r, "imported": (r.get("metadata") or {}).get("imported")} for r in rows]
        return rows

    def post(self, path, body, prefer=None, **kw):
        if self._gone(path):
            return None
        table = path.lstrip("/").split("?")[0]
        rows = body if isinstance(body, list) else [body]
        if table == "church_register_entries":
            rows = [{**self.ENTRY_DEFAULTS, **r} for r in rows]
            have = self.t.setdefault(table, [])
            fresh = []
            for r in rows:
                clash = (r.get("care_request_id") and any(h.get("care_request_id") == r["care_request_id"] for h in have)) or \
                        (r.get("import_key") and any(h["business_id"] == r["business_id"] and h.get("import_key") == r["import_key"]
                                                     for h in have + fresh))
                if not clash:
                    fresh.append(r)
            if len(fresh) < len(rows) and "on_conflict=" not in path:
                return None   # 409 from a unique constraint
            if not fresh:
                return []     # ignore-duplicates: nothing new
            rows = fresh
        return super().post(path, rows, prefer=prefer, **kw)

    def patch(self, path, body, **kw):
        return None if self._gone(path) else super().patch(path, body, **kw)


def _care(cid, biz, sub, status="new", contact=DANA):
    return {"id": cid, "business_id": biz, "status": status, "contact_id": contact, "submission": sub,
            "created_at": "2026-10-26T14:00:00+00:00", "status_changed_at": None, "updated_at": None}


@pytest.fixture
def db(monkeypatch):
    seats = (("admin", "admin"), ("carer", "member"), ("clerk", "member"), ("viewer", "viewer"), ("singer", "member"))
    imported = lambda day: {"imported_from": "Subsplash", "imported": {"Baptism date": day, "Gender": "F"}}  # noqa: E731
    fake = RegisterDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"],
                     "settings": {"brand_kit": {"colors": {"primary": "#1F3A5F", "secondary": "#C9A227"},
                                                "logo_url": "https://cdn.example/lcc.png"}}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"], "settings": {}},
                    {"id": SALON, "name": "Shear Joy", "type": "salon", "owner_id": ID["owner"], "settings": {}}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active",
                         "invited_email": f"{n}@lovecity.org"} for n, r in seats],
        contacts=[{"id": JORDAN, "business_id": BIZ, "name": "Jordan Ellis", "email": "jordan@example.com",
                   "phone": "216-555-0101", "metadata": imported("2019-04-21")},
                  {"id": MIA, "business_id": BIZ, "name": "Mia Ellis", "metadata": {}},
                  {"id": DANA, "business_id": BIZ, "name": "Dana Johnson", "metadata": imported("6/2/2015")},
                  {"id": ANDRE, "business_id": BIZ, "name": "Andre Cole", "metadata": imported("not a date")},
                  {"id": THEIR_PERSON, "business_id": OTHER, "name": "Grace Member", "metadata": imported("2020-01-05")}],
        ministry_care_requests=[
            _care(ASK, BIZ, {"kind": "life_event", "life_event": "A baptism", "request": "Me and my daughter, Mia",
                             "name": "Dana Johnson", "date": "2026-11-15", "confidential": "yes",
                             "source": "Member app, Ask the church"}),
            _care(WEDDING_ASK, BIZ, {"kind": "life_event", "life_event": "A wedding", "request": "A wedding",
                                     "name": "Andre Cole"}, contact=ANDRE),
            _care(FUNERAL_ASK, BIZ, {"kind": "life_event", "life_event": "A funeral", "request": "For my mother",
                                     "name": "Mia Ellis"}, contact=MIA),
            _care(HELP_ASK, BIZ, {"kind": "help", "need": "A bill", "request": "Light bill"}),
            _care(CLOSED_ASK, BIZ, {"kind": "life_event", "life_event": "A baptism", "request": "Done already"},
                  status="closed"),
            _care(THEIR_ASK, OTHER, {"kind": "life_event", "life_event": "A baptism", "request": "Theirs"},
                  contact=THEIR_PERSON),
        ],
        church_register_entries=[],
    )
    fake.missing = False
    fake.reads = []
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_REGISTER", "on")
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setattr(cr, "_now", lambda: T0)
    monkeypatch.setattr(cr, "_tz", lambda biz: ZoneInfo("America/New_York"))
    # Who sees what: the carer works People & care, the clerk the Office,
    # the viewer People & care (reads only), the singer worship only.
    areas = {ID["carer"]: ["people_care"], ID["clerk"]: ["office"], ID["viewer"]: ["people_care"],
             ID["singer"]: ["worship_media"]}
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {"areas": areas.get(uid), "by": "picked"})
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(cr.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def _page(name, biz=BIZ, year=None):
    got = client(name).get(f"/church/register?business_id={biz}" + (f"&year={year}" if year else ""))
    assert got.status_code == 200, got.text
    return got.json()


def _add(who, biz=BIZ, **kw):
    body = {"business_id": biz, "kind": "baptism", "event_on": "2026-10-18", "officiant": "Pastor Reed",
            "place": "Love City Church", "people": [{"contact_id": JORDAN}, {"contact_id": MIA}], **kw}
    return client(who).post("/church/register/entries", json=body)


def _entry(db, eid):
    return next(r for r in db.t["church_register_entries"] if r["id"] == eid)


def _care_row(db, cid):
    return next(r for r in db.t["ministry_care_requests"] if r["id"] == cid)


FUNERAL = {"kind": "funeral", "event_on": "2026-09-12", "people": [{"name": "Evelyn Shaw"}]}
REMOVED = {"kind": "membership", "membership": "removed", "event_on": "2026-08-02", "people": [{"contact_id": ANDRE}]}


# ─── The switch, the table ───────────────────────────────────────────

def test_status_is_false_when_the_switch_is_off_or_the_table_isnt_made(db, monkeypatch):
    def status(name):
        return client(name).get(f"/church/register/status?business_id={BIZ}").json()["enabled"]
    monkeypatch.setenv("CHURCH_REGISTER", "off")
    assert status("owner") is False and status("admin") is False
    assert client("owner").get(f"/church/register?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_REGISTER", "owner")   # the platform owner alone until a Thursday
    assert status("owner") is True and status("admin") is False
    assert _add("admin").status_code == 404
    monkeypatch.setenv("CHURCH_REGISTER", "on")
    assert status("admin") is True
    db.missing = True
    assert client("owner").get(f"/church/register/status?business_id={BIZ}").json() == {
        "enabled": False, "view": None, "write": False, "remove": False, "asks": False}
    c = client("owner")
    for got in (c.get(f"/church/register?business_id={BIZ}"), _add("owner"),
                c.post(f"/church/register/asks/{ASK}", json={"business_id": BIZ, "status": "planned"}),
                c.get(f"/church/register/import?business_id={BIZ}"),
                c.post("/church/register/import", json={"business_id": BIZ}),
                c.get(f"/church/register/person/{JORDAN}?business_id={BIZ}")):
        assert got.status_code == 503, got.text
    assert _care_row(db, ASK)["status"] == "new", "nothing moved while the table wasn't there"


def test_status_says_what_each_login_may_do(db):
    def status(name, biz=BIZ):
        return client(name).get(f"/church/register/status?business_id={biz}").json()
    assert status("owner") == {"enabled": True, "view": "care", "write": True, "remove": True, "asks": True}
    assert status("admin") == {"enabled": True, "view": "care", "write": True, "remove": True, "asks": True}
    assert status("carer") == {"enabled": True, "view": "care", "write": True, "remove": False, "asks": True}
    assert status("clerk") == {"enabled": True, "view": "office", "write": True, "remove": False, "asks": False}
    assert status("viewer") == {"enabled": True, "view": "care", "write": False, "remove": False, "asks": True}
    assert status("singer")["enabled"] is False, "their areas leave out care and the office"
    assert status("owner", SALON)["enabled"] is False, "churches only"
    assert client("stranger").get(f"/church/register/status?business_id={BIZ}").status_code == 404


# ─── Who sees what ───────────────────────────────────────────────────

def test_funerals_and_removals_are_people_and_cares_alone(db):
    baptism = _add("carer").json()["entry"]
    funeral = _add("carer", **FUNERAL).json()["entry"]
    removed = _add("carer", **REMOVED).json()["entry"]
    joined = _add("carer", kind="membership", membership="joined", event_on="2026-09-06",
                  people=[{"contact_id": DANA}]).json()["entry"]

    carer = _page("carer")
    assert {e["id"] for e in carer["entries"]} == {baptism["id"], funeral["id"], removed["id"], joined["id"]}
    assert carer["counts"]["funeral"] == 1 and carer["counts"]["removed"] == 1
    assert carer["counts"]["baptism"] == 1 and carer["counts"]["new_members"] == 1
    assert {a["id"] for a in carer["asks"]} == {ASK, WEDDING_ASK, FUNERAL_ASK}

    clerk = _page("clerk")
    assert {e["id"] for e in clerk["entries"]} == {baptism["id"], joined["id"]}
    assert clerk["counts"]["funeral"] is None and clerk["counts"]["removed"] is None, "not even a number"
    assert clerk["counts"]["baptism"] == 1 and clerk["counts"]["new_members"] == 1
    assert clerk["asks"] == [], "asks come from Prayer & care, which is the care team's"
    assert clerk["me"] == {"view": "office", "write": True, "remove": False, "asks": False}
    c = client("clerk")
    for eid in (funeral["id"], removed["id"]):
        assert c.patch(f"/church/register/entries/{eid}", json={"business_id": BIZ, "notes": "x"}).status_code == 404
    assert _add("clerk", **FUNERAL).status_code == 403
    assert _add("clerk", **REMOVED).status_code == 403
    # Nor can the office turn something it sees into one.
    assert c.patch(f"/church/register/entries/{joined['id']}",
                   json={"business_id": BIZ, "membership": "removed"}).status_code == 403
    assert c.patch(f"/church/register/entries/{baptism['id']}",
                   json={"business_id": BIZ, **FUNERAL}).status_code == 403
    assert c.post(f"/church/register/asks/{WEDDING_ASK}", json={"business_id": BIZ, "status": "planned",
                                                                "event_on": "2026-12-05"}).status_code == 403
    # A person's page follows the same rule.
    assert [e["kind"] for e in c.get(f"/church/register/person/{ANDRE}?business_id={BIZ}").json()["entries"]] == []
    assert [e["kind"] for e in client("carer").get(
        f"/church/register/person/{ANDRE}?business_id={BIZ}").json()["entries"]] == ["membership"]

    assert _add("viewer").status_code == 403, "a viewer only reads"
    assert _page("viewer")["entries"]
    assert client("singer").get(f"/church/register?business_id={BIZ}").status_code == 403
    assert client("stranger").get(f"/church/register?business_id={BIZ}").status_code == 404


def test_while_who_sees_what_is_off_every_login_sees_the_whole_church(db, monkeypatch):
    _add("carer", **FUNERAL)
    monkeypatch.setenv("CHURCH_AREAS", "off")
    assert _page("clerk")["counts"]["funeral"] == 1
    assert _page("singer")["me"]["view"] == "care"


# ─── Another church ──────────────────────────────────────────────────

def test_another_church_is_unreachable(db):
    theirs = _add("other_owner", biz=OTHER, people=[{"contact_id": THEIR_PERSON}]).json()["entry"]
    mine = _add("owner").json()["entry"]
    c = client("owner")
    # Their entry, through my church: missing everywhere.
    assert c.patch(f"/church/register/entries/{theirs['id']}", json={"business_id": BIZ, "notes": "x"}).status_code == 404
    assert c.delete(f"/church/register/entries/{theirs['id']}?business_id={BIZ}").status_code == 404
    assert c.get(f"/church/register/entries/{theirs['id']}/certificate?business_id={BIZ}").status_code == 404
    assert _entry(db, theirs["id"])["notes"] == "" and _entry(db, theirs["id"])["removed_at"] is None
    # Their person can't be named in mine, by adding or by editing.
    assert _add("owner", people=[{"contact_id": THEIR_PERSON}]).status_code == 400
    assert _add("owner", people=[{"contact_id": THEIR_PERSON, "name": "Grace Member"}]).status_code == 400
    assert c.patch(f"/church/register/entries/{mine['id']}",
                   json={"business_id": BIZ, "people": [{"contact_id": THEIR_PERSON, "name": "G"}]}).status_code == 400
    assert _entry(db, mine["id"])["contact_ids"] == sorted([JORDAN, MIA])
    assert c.get(f"/church/register/person/{THEIR_PERSON}?business_id={BIZ}").status_code == 404
    # Their ask isn't mine to turn into an entry; their page isn't mine to read.
    assert c.post(f"/church/register/asks/{THEIR_ASK}", json={"business_id": BIZ, "status": "done",
                                                              "event_on": "2026-10-18"}).status_code == 404
    assert _care_row(db, THEIR_ASK)["status"] == "new"
    assert client("owner").get(f"/church/register?business_id={OTHER}").status_code == 404
    assert all(e["id"] != theirs["id"] for e in _page("owner")["entries"])
    # Their baptism dates aren't offered to mine.
    offer = c.get(f"/church/register/import?business_id={BIZ}").json()
    assert THEIR_PERSON not in {p["contact_id"] for p in offer["people"]}


# ─── Asks from the member app ────────────────────────────────────────

def test_an_ask_becomes_an_entry_once_and_its_prayer_and_care_row_moves(db):
    page = _page("carer")
    ask = next(a for a in page["asks"] if a["id"] == ASK)
    assert ask["kind"] == "baptism" and ask["who"] == "Dana Johnson" and ask["date"] == "2026-11-15"
    assert ask["text"] == "Me and my daughter, Mia"
    assert all(a["id"] not in (HELP_ASK, CLOSED_ASK) for a in page["asks"]), "help asks and closed ones aren't waiting"
    assert db.t["church_register_entries"] == [], "reading writes nothing"

    c = client("carer")
    planned = c.post(f"/church/register/asks/{ASK}", json={
        "business_id": BIZ, "status": "planned",
        "people": [{"contact_id": DANA}, {"contact_id": MIA}]})
    assert planned.status_code == 200, planned.text
    entry = planned.json()["entry"]
    assert entry["status"] == "planned" and entry["event_on"] == "2026-11-15", "the day the member asked for"
    assert entry["kind"] == "baptism" and entry["from_ask"] is True and entry["source"] == "app"
    assert [p["name"] for p in entry["people"]] == ["Dana Johnson", "Mia Ellis"]
    assert _care_row(db, ASK)["status"] == "reviewed" and _care_row(db, ASK)["status_changed_at"]

    # Twice is once: the second press answers with the first entry.
    again = c.post(f"/church/register/asks/{ASK}", json={"business_id": BIZ, "status": "done", "event_on": "2026-10-18"})
    assert again.status_code == 200 and again.json()["already"] is True and again.json()["entry"]["id"] == entry["id"]
    assert len([r for r in db.t["church_register_entries"] if r["care_request_id"] == ASK]) == 1
    page = _page("carer")
    assert ASK not in {a["id"] for a in page["asks"]}, "no longer waiting"
    assert [p["id"] for p in page["planned"]] == [entry["id"]]

    # When it happens, the planned entry is recorded and the ask closes.
    done = c.patch(f"/church/register/entries/{entry['id']}",
                   json={"business_id": BIZ, "status": "done", "event_on": "2026-10-25", "officiant": "Pastor Reed"})
    assert done.status_code == 200 and done.json()["entry"]["status"] == "done"
    assert _care_row(db, ASK)["status"] == "closed"
    assert _page("carer")["counts"]["baptism"] == 1

    # Recorded straight away: done, and closed at once.
    wed = c.post(f"/church/register/asks/{WEDDING_ASK}", json={
        "business_id": BIZ, "status": "done", "event_on": "2026-10-10",
        "people": [{"contact_id": ANDRE}, {"name": "Tasha Green"}]}).json()["entry"]
    assert wed["kind"] == "wedding" and [p["role"] for p in wed["people"]] == ["spouse", "spouse"]
    assert _care_row(db, WEDDING_ASK)["status"] == "closed"


def test_an_ask_whose_row_didnt_move_moves_on_the_next_press(db, monkeypatch):
    real = db.patch
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **kw: None if path.startswith("/ministry_care_requests") else real(path, body, **kw))
    c = client("carer")
    first = c.post(f"/church/register/asks/{ASK}", json={"business_id": BIZ, "status": "planned",
                                                         "people": [{"contact_id": DANA}]})
    assert first.status_code == 200 and _care_row(db, ASK)["status"] == "new", "the entry stands; the move failed"
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    again = c.post(f"/church/register/asks/{ASK}", json={"business_id": BIZ, "status": "planned"})
    assert again.json()["already"] is True and _care_row(db, ASK)["status"] == "reviewed"


def test_an_ask_this_login_cant_see_is_missing_even_once_it_is_an_entry(db):
    youth = "dddddddd-0000-4000-8000-000000000007"
    db.t["ministry_care_requests"].append(_care(youth, BIZ, {"kind": "life_event", "life_event": "A baptism",
                                                             "request": "Mine", "youth": "yes"}, contact=MIA))
    assert youth not in {a["id"] for a in _page("carer")["asks"]}
    assert youth in {a["id"] for a in _page("owner")["asks"]}
    made = client("owner").post(f"/church/register/asks/{youth}", json={
        "business_id": BIZ, "status": "planned", "event_on": "2026-11-15", "people": [{"contact_id": MIA}]})
    assert made.status_code == 200
    got = client("carer").post(f"/church/register/asks/{youth}", json={"business_id": BIZ, "status": "planned"})
    assert got.status_code == 404 and "entry" not in got.text


def test_long_lists_are_read_a_page_at_a_time(db, monkeypatch):
    monkeypatch.setattr(cr, "PAGE", 2)
    for day in ("2026-01-04", "2026-02-01", "2026-03-01", "2026-04-05", "2026-05-03"):
        assert _add("carer", event_on=day, people=[{"name": f"Person {day}"}]).status_code == 200
    page = _page("carer")
    assert page["counts"]["baptism"] == 5 and len(page["entries"]) == 5
    assert [e["event_on"] for e in page["entries"]] == ["2026-05-03", "2026-04-05", "2026-03-01", "2026-02-01", "2026-01-04"]
    # The import's people and the baptisms it checks against, past one page.
    for i in range(3):
        db.t["contacts"].append({"id": f"cccccccc-0000-4000-8000-0000000001{i:02d}", "business_id": BIZ, "name": f"Extra {i}",
                                 "metadata": {"imported_from": "Subsplash", "imported": {"Baptism date": "2018-05-0" + str(i + 1)}}})
    _add("carer", event_on="2018-05-01", people=[{"contact_id": "cccccccc-0000-4000-8000-000000000100"}])
    offer = client("carer").get(f"/church/register/import?business_id={BIZ}").json()
    assert offer["count"] == 4, "Jordan, Dana and two extras; the one recorded by hand is covered"
    assert page["years"] == [2026] and page["first_year"] == 2026
    assert _page("carer")["years"] == list(range(2026, 2017, -1))


def test_an_ask_nobody_here_can_act_on_writes_nothing(db):
    c = client("carer")
    assert c.post(f"/church/register/asks/{CLOSED_ASK}", json={"business_id": BIZ, "status": "done",
                                                               "event_on": "2026-10-18"}).status_code == 409
    assert c.post(f"/church/register/asks/{HELP_ASK}", json={"business_id": BIZ, "status": "done",
                                                             "event_on": "2026-10-18"}).status_code == 404
    # Done needs a day that has come; planned needs a day at all.
    assert c.post(f"/church/register/asks/{WEDDING_ASK}", json={"business_id": BIZ, "status": "planned"}).status_code == 400
    assert c.post(f"/church/register/asks/{WEDDING_ASK}", json={"business_id": BIZ, "status": "done",
                                                                "event_on": "2026-12-05"}).status_code == 400
    assert client("viewer").post(f"/church/register/asks/{ASK}", json={"business_id": BIZ, "status": "planned"}).status_code == 403
    assert db.t["church_register_entries"] == []
    assert {_care_row(db, x)["status"] for x in (ASK, WEDDING_ASK, HELP_ASK)} == {"new"}


# ─── Baptism dates from the import ───────────────────────────────────

def test_imported_baptism_dates_are_offered_and_come_in_once_on_a_press(db):
    c = client("carer")
    offer = c.get(f"/church/register/import?business_id={BIZ}").json()
    assert offer["count"] == 2 and offer["first_year"] == 2015 and offer["last_year"] == 2019
    assert {(p["contact_id"], p["baptized_on"]) for p in offer["people"]} == {(JORDAN, "2019-04-21"), (DANA, "2015-06-02")}
    assert db.t["church_register_entries"] == [], "nothing is written until the office presses"
    # A person's page says so, quietly.
    assert c.get(f"/church/register/person/{JORDAN}?business_id={BIZ}").json()["imported"] == {"baptized_on": "2019-04-21"}
    assert c.get(f"/church/register/person/{ANDRE}?business_id={BIZ}").json()["imported"] is None, "not a date"

    got = c.post("/church/register/import", json={"business_id": BIZ})
    assert got.status_code == 200 and got.json() == {"added": 2}
    rows = db.t["church_register_entries"]
    assert {(r["kind"], r["status"], r["event_on"], r["source"]) for r in rows} == {
        ("baptism", "done", "2019-04-21", "import"), ("baptism", "done", "2015-06-02", "import")}
    assert {r["people"][0]["name"] for r in rows} == {"Jordan Ellis", "Dana Johnson"}
    assert c.post("/church/register/import", json={"business_id": BIZ}).json() == {"added": 0}, "twice is once"
    assert c.get(f"/church/register/import?business_id={BIZ}").json()["count"] == 0
    assert _page("carer", year=2019)["counts"]["baptism"] == 1
    assert 2015 in _page("carer")["years"]
    assert c.get(f"/church/register/person/{JORDAN}?business_id={BIZ}").json()["imported"] is None

    # Removed by an admin: it stays out of the offer.
    jordan = next(r for r in rows if r["contact_ids"] == [JORDAN])
    assert client("admin").delete(f"/church/register/entries/{jordan['id']}?business_id={BIZ}").status_code == 200
    assert c.get(f"/church/register/import?business_id={BIZ}").json()["count"] == 0
    assert c.post("/church/register/import", json={"business_id": BIZ}).json() == {"added": 0}
    assert len(db.t["church_register_entries"]) == 2
    assert client("viewer").post("/church/register/import", json={"business_id": BIZ}).status_code == 403


def test_a_baptism_recorded_by_hand_covers_the_person_and_one_person_comes_in_alone(db):
    _add("carer", people=[{"contact_id": JORDAN}])
    c = client("carer")
    offer = c.get(f"/church/register/import?business_id={BIZ}").json()
    assert [p["contact_id"] for p in offer["people"]] == [DANA]
    one = c.post("/church/register/import", json={"business_id": BIZ, "contact_id": DANA})
    assert one.status_code == 200 and one.json() == {"added": 1}
    assert c.post("/church/register/import", json={"business_id": BIZ, "contact_id": DANA}).status_code == 409
    assert c.post("/church/register/import", json={"business_id": BIZ, "contact_id": THEIR_PERSON}).status_code == 409
    assert len(db.t["church_register_entries"]) == 2


@pytest.mark.parametrize("raw,want", [
    ("2019-04-21", "2019-04-21"), ("2019-04-21 00:00:00", "2019-04-21"), ("4/21/2019", "2019-04-21"),
    ("04/02/2019", "2019-04-02"), ("", None), ("Spring 2019", None), ("2/30/2019", None), ("1850-01-01", None),
    ("2030-01-01", None),
])
def test_an_import_date_is_read_the_way_subsplash_writes_it(monkeypatch, raw, want):
    monkeypatch.setattr(cr, "_now", lambda: T0)
    got = cr.import_day(raw)
    assert (got.isoformat() if got else None) == want


# ─── Adding, changing, removing ──────────────────────────────────────

def test_an_entry_is_checked_and_names_people_as_the_day_recorded_them(db):
    entry = _add("carer").json()["entry"]
    assert [(p["role"], p["name"], p["contact_id"]) for p in entry["people"]] == [
        ("person", "Jordan Ellis", JORDAN), ("person", "Mia Ellis", MIA)]
    assert set(_entry(db, entry["id"])["contact_ids"]) == {JORDAN, MIA}
    # Bad shapes are refused, in words.
    for bad in ({"kind": "christening"}, {"event_on": "2026-13-01"}, {"event_on": "2026-12-25"}, {"people": []},
                {"kind": "membership"}, {"kind": "wedding", "people": [{"role": "person", "name": "A"}]},
                {"kind": "wedding", "people": [{"role": "spouse", "name": n} for n in "ABC"]},
                {"kind": "dedication", "people": [{"role": "parent", "name": "Mom"}]},
                {"people": [{"contact_id": JORDAN}, {"contact_id": JORDAN}]}, {"people": [{"name": "  "}]},
                {"event_on": "1700-01-01"}):
        got = _add("carer", **bad)
        assert got.status_code == 400, (bad, got.text)
        assert isinstance(got.json()["detail"], str) and got.json()["detail"]
    # Planned may be ahead; a dedication names the child and the parents.
    ded = _add("carer", kind="dedication", status="planned", event_on="2026-11-22",
               people=[{"role": "child", "name": "Noah Price"}, {"role": "parent", "name": "Leah Price"}]).json()["entry"]
    assert ded["status"] == "planned" and ded["certificate"] is False
    # A transfer keeps the other church; anything else drops it.
    t = _add("carer", kind="membership", membership="transferred_in", other_church="First Baptist, Akron",
             people=[{"contact_id": DANA}]).json()["entry"]
    assert t["other_church"] == "First Baptist, Akron"
    j = _add("carer", kind="membership", membership="joined", other_church="Nowhere", people=[{"contact_id": DANA}])
    assert j.json()["entry"]["other_church"] is None


def test_only_the_owner_and_admins_remove_and_a_removed_entry_stays_on_file(db):
    entry = _add("carer").json()["entry"]
    for name in ("carer", "clerk", "viewer"):
        assert client(name).delete(f"/church/register/entries/{entry['id']}?business_id={BIZ}").status_code == 403, name
    assert _page("carer")["counts"]["baptism"] == 1
    got = client("admin").delete(f"/church/register/entries/{entry['id']}?business_id={BIZ}")
    assert got.status_code == 200
    row = _entry(db, entry["id"])
    assert row["removed_at"] and row["removed_by"] == ID["admin"], "kept, marked"
    page = _page("carer")
    assert page["entries"] == [] and page["counts"]["baptism"] == 0
    assert client("owner").delete(f"/church/register/entries/{entry['id']}?business_id={BIZ}").status_code == 404
    assert client("carer").patch(f"/church/register/entries/{entry['id']}",
                                 json={"business_id": BIZ, "notes": "x"}).status_code == 404
    assert client("owner").get(f"/church/register/person/{JORDAN}?business_id={BIZ}").json()["entries"] == []


def test_the_year_has_its_numbers_and_the_years_the_register_holds(db):
    _add("carer")
    _add("carer", event_on="2025-05-04", people=[{"contact_id": DANA}])
    _add("carer", kind="wedding", event_on="2026-10-10",
         people=[{"role": "spouse", "contact_id": ANDRE}, {"role": "spouse", "name": "Tasha Green"}])
    _add("carer", kind="membership", membership="transferred_in", event_on="2026-03-01", people=[{"name": "A Newcomer"}])
    _add("carer", kind="dedication", status="planned", event_on="2026-11-22", people=[{"role": "child", "name": "Noah"}])
    page = _page("carer")
    assert page["year"] == 2026 and page["years"] == [2026, 2025] and page["today"] == "2026-10-27"
    assert page["counts"]["baptism"] == 1 and page["counts"]["wedding"] == 1 and page["counts"]["new_members"] == 1
    assert page["counts"]["dedication"] == 0, "planned isn't counted until it happens"
    assert [e["kind"] for e in page["planned"]] == ["dedication"]
    last = _page("carer", year=2025)
    assert last["counts"]["baptism"] == 1 and [e["event_on"] for e in last["entries"]] == ["2025-05-04"]
    assert client("carer").get(f"/church/register?business_id={BIZ}&year=soon").status_code == 400


def test_a_person_who_left_the_list_keeps_their_name_on_an_old_entry(db):
    entry = _add("carer").json()["entry"]
    db.t["contacts"] = [c for c in db.t["contacts"] if c["id"] != MIA]
    got = client("carer").patch(f"/church/register/entries/{entry['id']}",
                                json={"business_id": BIZ, "place": "The river"})
    assert got.status_code == 200, got.text
    people = got.json()["entry"]["people"]
    assert [p["name"] for p in people] == ["Jordan Ellis", "Mia Ellis"]
    assert people[1]["contact_id"] is None and _entry(db, entry["id"])["contact_ids"] == [JORDAN]


# ─── The certificate ─────────────────────────────────────────────────

def test_the_certificate_says_what_the_entry_says_and_nothing_else(db):
    entry = _add("carer", notes="Private: talked through her fear of water").json()["entry"]
    # Members changes later: the register (and its certificate) keeps the day's names.
    next(c for c in db.t["contacts"] if c["id"] == JORDAN)["name"] = "Jordan Ellis-Brooks"
    got = client("clerk").get(f"/church/register/entries/{entry['id']}/certificate?business_id={BIZ}")
    assert got.status_code == 200, got.text
    cert = got.json()
    assert cert["title"] == "Certificate of Baptism" and cert["kind"] == "baptism"
    assert [p["name"] for p in cert["people"]] == ["Jordan Ellis", "Mia Ellis"]
    assert cert["event_on"] == "2026-10-18" and cert["officiant"] == "Pastor Reed" and cert["place"] == "Love City Church"
    assert cert["church"] == {"name": "Love City Church", "logo": "https://cdn.example/lcc.png",
                              "colors": {"primary": "#1F3A5F", "secondary": "#C9A227", "accent": None}}
    said = repr(cert)
    for leak in ("Ellis-Brooks", "jordan@example.com", "216-555-0101", "fear of water", JORDAN, "Gender"):
        assert leak not in said, leak
    assert set(cert) == {"id", "kind", "title", "people", "event_on", "officiant", "place", "church"}
    # Nor does it read anyone's record to make it.
    db.reads.clear()
    client("carer").get(f"/church/register/entries/{entry['id']}/certificate?business_id={BIZ}")
    assert not any(r.startswith("/contacts") for r in db.reads)

    c = client("carer")
    funeral = _add("carer", **FUNERAL).json()["entry"]
    assert c.get(f"/church/register/entries/{funeral['id']}/certificate?business_id={BIZ}").status_code == 400
    planned = _add("carer", kind="wedding", status="planned", event_on="2026-12-05",
                   people=[{"role": "spouse", "name": "A"}, {"role": "spouse", "name": "B"}]).json()["entry"]
    assert c.get(f"/church/register/entries/{planned['id']}/certificate?business_id={BIZ}").status_code == 409
    assert client("clerk").get(f"/church/register/entries/{funeral['id']}/certificate?business_id={BIZ}").status_code == 404

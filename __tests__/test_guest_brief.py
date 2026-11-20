"""Chief's call brief and "How did it go?" (guest_brief.py, the Welcome Path
step 3), with the card's new questions (new_here, member_im_new), the office
note's outcome (church_follow_up.office_note, church_router), the Lead tab's
brief (member_portal_lead) and the bulletin guest card that is a general form
(church_follow_up.on_intake_form).

Kevin, 2026-11-20, on the Welcome Path mock: "build". Pinned here, on one
made-up church in an in-memory PostgREST (every reader runs its real path):
  1. The brief: who they are (the visit, the door, who invited them, the
     kids), what they asked for, how to reach them, the prayer flag (never
     its words), the texts, the opening line, and worth mentioning: the
     church's real groups, teams, classes and people only
  2. Who may read it: the caller's login, the Guests room's logins, the
     owner and admins; anyone else 403/404; the switch off is a 404
  3. "How did it go?": what Chief will do, then Talked hands each ask to its
     person (serve, baptism, pastor, a group's leader, else People & Care),
     never twice; the other taps hand nothing on
  4. The card's new questions are kept (and only asked with the path on)
  5. A general form picked as the bulletin's guest card is a guest's call
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_access as ba  # noqa: E402
import church_follow_up as cfu  # noqa: E402
import guest_brief as gb  # noqa: E402
import guest_calls as gc  # noqa: E402
import guest_path  # noqa: E402
import sb_clients  # noqa: E402

ET = ZoneInfo("America/New_York")
BIZ = "6b000000-0000-4000-8000-000000000001"
OTHER = "6b000000-0000-4000-8000-000000000002"
OWNER = "6a000000-0000-4000-8000-000000000001"


def cid(n: int) -> str:
    return f"6c000000-0000-4000-8000-{n:012d}"


def fid(n: int) -> str:
    return f"6f000000-0000-4000-8000-{n:012d}"


RENEE, PASTOR, MINISTER, TASHA, ALICIA, BEN, MARIA, TYRELL, DENISE, MEDIA = (cid(i) for i in range(1, 11))
RENEE_SEAT, MEDIA_SEAT, ADMIN_SEAT = "u-renee", "u-media", "u-admin"
G_WOMEN, G_MEN, G_YOUTH, G_GREET, G_ELDERS = (f"6e000000-0000-4000-8000-00000000000{i}" for i in range(1, 6))
SUNDAY = datetime(2026, 11, 22, 10, 30, tzinfo=ET)
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=ET)            # Monday morning


def at(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def z(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── A small PostgREST, in memory (JSON paths, inserts, patches) ──────

def _split(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + ([cur] if cur else [])


def _value(row, col):
    parts = col.replace("->>", "->").split("->")
    v = row.get(parts[0])
    for p in parts[1:]:
        v = v.get(p) if isinstance(v, dict) else None
    return v


def _cmp(row, col, op, val):
    if op == "not":
        sub_op, _, sub_val = val.partition(".")
        return not _cmp(row, col, sub_op, sub_val)
    v = _value(row, col)
    if op == "is":
        return v is None if val == "null" else str(v).lower() == val
    if op == "in":
        return str(v) in set(_split(val.strip("()")))
    if op == "ilike":
        return v is not None and str(v).lower() == val.replace("\\_", "_").replace("\\%", "%").lower()
    if op == "like":
        import fnmatch
        return v is not None and fnmatch.fnmatchcase(str(v), val)
    if op == "eq":
        return str(v).lower() == val.lower() if isinstance(v, bool) else str(v) == val
    if op == "neq":
        return str(v) != val
    if v is None:
        return False
    a, b = str(v), val
    if "T" in a and "T" in b:
        a, b = cfu._parse(a), cfu._parse(b)
    return {"gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[op]


class FakeDB:
    def __init__(self, **tables):
        self.t = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.paths = []

    def _filters(self, qs):
        filters, limit = [], None
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            v = unquote(v)
            if k in ("select", "order", "offset"):
                continue
            if k == "limit":
                limit = int(v)
            elif k == "or":
                filters.append(("or", [tuple(c.split(".", 2)) for c in _split(v.strip("()"))]))
            else:
                op, _, val = v.partition(".")
                filters.append((unquote(k), op, val))
        return filters, limit

    def _match(self, row, filters):
        for f in filters:
            if f[0] == "or":
                if not any(_cmp(row, c, o, v) for c, o, v in f[1]):
                    return False
            elif not _cmp(row, *f):
                return False
        return True

    def get(self, path, **_):
        self.paths.append(path)
        table, _, qs = path.lstrip("/").partition("?")
        if table in getattr(self, "broken", ()):
            return None
        filters, limit = self._filters(qs)
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, filters)]
        return rows[:limit] if limit else rows

    def post(self, path, body, prefer=None, **_):
        table = path.lstrip("/").split("?")[0]
        if table.startswith("rpc/"):
            return None
        row = dict(body)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", cfu._iso(cfu._now()))
        if table == "church_follow_ups" and row.get("source_event") and any(
                r.get("source_event") == row["source_event"] and r["business_id"] == row["business_id"]
                for r in self.t.get(table, [])):
            return None
        self.t.setdefault(table, []).append(row)
        return [dict(row)]

    def patch(self, path, body, **_):
        table, _, qs = path.lstrip("/").partition("?")
        filters, _ = self._filters(qs)
        out = []
        for r in self.t.get(table, []):
            if self._match(r, filters):
                r.update(body)
                out.append(dict(r))
        return out

    def delete(self, path, **_):
        table, _, qs = path.lstrip("/").partition("?")
        filters, _ = self._filters(qs)
        self.t[table] = [r for r in self.t.get(table, []) if not self._match(r, filters)]
        return True


def _role(contact, role, scope=""):
    return {"id": str(uuid.uuid4()), "business_id": BIZ, "contact_id": contact, "role": role, "scope": scope,
            "status": "active", "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None}


SERVE = {"id": "f-serve", "name": "Serve with us", "form_type": "volunteer", "fields": [
    {"name": "team", "label": "Where would you like to serve?", "options": ["Hospitality Team", "Parking Team"]}]}
WELCOME_CARD = {"id": "f-welcome", "name": "Welcome card", "form_type": "general", "fields": [
    {"name": "name", "label": "Your name"}, {"name": "email", "label": "Email"},
    {"name": "heard", "label": "How did you hear about us?"}]}

NAMES = {RENEE: "Renee Ellis", PASTOR: "Kevin McCloud", MINISTER: "Angela Price", TASHA: "Tasha Williams",
         ALICIA: "Alicia Grant", BEN: "Ben Carter", DENISE: "Denise Robinson", MEDIA: "Mia Booth"}


def _guest_meta(**card):
    return {"new_here": {"code": "ABCD2345", "door": "kids", "texted_at": z(SUNDAY), "texts_ok": True, "texts": "on",
                         "visits": 1, "card": {"first_time": True, "heard": "A friend or family", "kids": "2",
                                               "prayer": True, **card}}}


def _church():
    contacts = [{"id": k, "business_id": BIZ, "name": v, "email": f"{v.split()[0].lower()}@example.com", "phone": "",
                 "metadata": {}, "created_at": "2026-01-01T00:00:00+00:00"} for k, v in NAMES.items()]
    contacts += [
        {"id": MARIA, "business_id": BIZ, "name": "Maria Lopez", "email": "maria@example.com", "phone": "+15555550142",
         "created_at": at(SUNDAY), "metadata": _guest_meta(invited_by="Denise Robinson",
                                                           wants=["group", "serve", "baptism", "class", "pastor"],
                                                           reach="text")},
        {"id": TYRELL, "business_id": BIZ, "name": "Tyrell Hayes", "email": "", "phone": "+15555550199",
         "created_at": at(SUNDAY), "metadata": {"new_here": {"code": "WXYZ2345", "door": "text", "texted_at": z(SUNDAY),
                                                             "visits": 1}}},
    ]
    fus = [
        {"id": fid(1), "business_id": BIZ, "contact_id": MARIA, "card_key": "checkin:first", "card_name": "First check-in",
         "path_kind": "connect", "answers": [{"q": "First visit", "a": "First time at Sunday Worship · 2 kids checked in"}],
         "steps": cfu.PATHS["connect"], "step": 0, "status": "open", "leader_contact_id": RENEE,
         "leader_role": gc.MARK, "assigned_by": "guest_calls:people_care", "assigned_at": at(SUNDAY),
         "due_at": at(datetime(2026, 11, 24, 18, tzinfo=ET)), "created_at": at(SUNDAY), "source_event": "first-visit:h:h1"},
        {"id": fid(2), "business_id": BIZ, "contact_id": TYRELL, "card_key": "text:new_here", "card_name": "New here card",
         "path_kind": "connect", "answers": [{"q": "First time?", "a": "Yes"}], "steps": cfu.PATHS["connect"], "step": 0,
         "status": "open", "leader_contact_id": RENEE, "leader_role": gc.MARK, "assigned_by": "guest_calls:people_care",
         "assigned_at": at(SUNDAY), "due_at": at(datetime(2026, 11, 24, 18, tzinfo=ET)), "created_at": at(SUNDAY),
         "source_event": "new-here:x"},
    ]
    sched = [
        {"id": "s1", "business_id": BIZ, "run_at": at(SUNDAY + timedelta(minutes=35)), "status": "done",
         "last_run_at": at(SUNDAY + timedelta(minutes=35)),
         "action": {"type": "new_here_text", "step": "welcome", "contact_id": MARIA, "texted_at": at(SUNDAY), "door": "kids"}},
        {"id": "s2", "business_id": BIZ, "run_at": at(SUNDAY + timedelta(hours=3, minutes=35)), "status": "done",
         "last_run_at": at(SUNDAY + timedelta(hours=3, minutes=35)),
         "action": {"type": "new_here_text", "step": "thanks", "contact_id": MARIA, "texted_at": at(SUNDAY), "door": "kids"}},
        {"id": "s3", "business_id": BIZ, "run_at": at(datetime(2026, 11, 23, 10, tzinfo=ET)), "status": "queued",
         "last_run_at": None,
         "action": {"type": "new_here_text", "step": "monday", "contact_id": MARIA, "texted_at": at(SUNDAY), "door": "kids"}},
        {"id": "s4", "business_id": BIZ, "run_at": at(datetime(2026, 11, 26, 18, tzinfo=ET)), "status": "queued",
         "last_run_at": None,
         "action": {"type": "new_here_text", "step": "invite", "contact_id": MARIA, "texted_at": at(SUNDAY), "door": "kids"}},
    ]
    sms = [{"id": f"m{i}", "business_id": BIZ, "contact_id": MARIA, "direction": "outbound",
            "created_at": at(SUNDAY + timedelta(minutes=m))} for i, m in ((1, 35), (2, 215))]
    groups = [
        {"id": G_WOMEN, "business_id": BIZ, "name": "Women’s Study", "kind": "small_group", "meets": "", "meet_day": 2,
         "meet_time": "19:00:00", "meet_every": 1, "active": True, "join_mode": "open", "open_to_join": True, "youth": False},
        {"id": G_MEN, "business_id": BIZ, "name": "Men’s Breakfast", "kind": "small_group", "meets": "Saturdays, 8 am",
         "meet_day": None, "meet_time": None, "active": True, "join_mode": "ask", "open_to_join": True, "youth": False},
        {"id": G_YOUTH, "business_id": BIZ, "name": "Youth Night", "kind": "small_group", "meets": "Fridays", "active": True,
         "join_mode": "open", "youth": True},
        {"id": G_GREET, "business_id": BIZ, "name": "Greeters", "kind": "team", "meets": "", "active": True,
         "join_mode": "open", "youth": False},
        {"id": G_ELDERS, "business_id": BIZ, "name": "Elders", "kind": "small_group", "meets": "", "active": True,
         "join_mode": "invite", "youth": False},
    ]
    members = [{"business_id": BIZ, "group_id": G_WOMEN, "contact_id": ALICIA, "role": "leader"},
               {"business_id": BIZ, "group_id": G_MEN, "contact_id": BEN, "role": "leader"},
               {"business_id": BIZ, "group_id": G_YOUTH, "contact_id": TASHA, "role": "leader"}]
    return FakeDB(
        businesses=[{"id": BIZ, "name": "Grace Hill Church", "type": "ministry", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Kevin"}},
                    {"id": OTHER, "name": "Other Church", "type": "ministry", "owner_id": "x", "settings": {}}],
        contacts=contacts,
        church_leader_roles=[_role(PASTOR, "pastor"), _role(MINISTER, "baptism_minister"),
                             _role(TASHA, "team_leader", "Hospitality Team"),
                             _role(ALICIA, "team_leader", "Parking Team")],
        church_role_defs=[], church_role_settings=[], church_duty_holders=[],
        church_follow_ups=fus, church_follow_up_notes=[], events=[],
        intake_forms=[dict(SERVE, business_id=BIZ), dict(WELCOME_CARD, business_id=BIZ)],
        business_sites=[{"business_id": BIZ, "slug": "grace-hill", "site_config": {}}],
        business_users=[
            {"business_id": BIZ, "user_id": RENEE_SEAT, "invited_email": "renee@example.com", "role": "manager",
             "lane": "people_care", "status": "active", "name": "Renee Ellis"},
            {"business_id": BIZ, "user_id": MEDIA_SEAT, "invited_email": "mia@example.com", "role": "manager",
             "lane": "media_comms", "status": "active", "name": "Mia Booth"},
            {"business_id": BIZ, "user_id": ADMIN_SEAT, "invited_email": "office@example.com", "role": "admin",
             "status": "active", "name": "The Office"}],
        household_adults=[{"household_id": "h1", "contact_id": MARIA, "business_id": BIZ}],
        children=[{"id": "k1", "business_id": BIZ, "household_id": "h1", "first_name": "Sofia", "birthdate": "2019-05-01",
                   "active": True},
                  {"id": "k2", "business_id": BIZ, "household_id": "h1", "first_name": "Mateo", "birthdate": "2022-03-01",
                   "active": True}],
        child_checkins=[{"id": "cc1", "business_id": BIZ, "household_id": "h1", "child_id": "k1",
                         "checked_in_at": at(SUNDAY)}],
        attendance=[], chief_scheduled_actions=sched, sms_messages=sms, groups=groups, group_members=members,
        academy_courses=[{"id": "a1", "business_id": BIZ, "title": "Foundations", "status": "published", "self_join": True,
                          "product_id": None, "private": False},
                         {"id": "a2", "business_id": BIZ, "title": "Ordination track", "status": "published",
                          "self_join": True, "product_id": None, "private": True}],
        ministry_care_requests=[{"id": "p1", "business_id": BIZ, "contact_id": MARIA,
                                 "submission": {"prayer_request": "PRIVATE-WORDS my husband’s surgery"}}],
        audit_log=[],
    )


@pytest.fixture
def db(monkeypatch):
    fake = _church()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    on = {"on": True}
    monkeypatch.setattr(guest_path, "switched_on", lambda biz: on["on"] and str(biz) == BIZ)
    fake.on = on
    import member_asks
    import messaging_router
    import church_over
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: "kevin@example.com")
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "kevin@example.com")
    monkeypatch.setattr(church_over, "_OWNER_EMAIL", {})
    monkeypatch.setattr(gb, "_tz", lambda business: ET)
    monkeypatch.setattr(gc, "_zone", lambda ch: ET)
    monkeypatch.setattr(cfu, "_now", lambda: NOW.astimezone(timezone.utc))
    monkeypatch.setattr(gb, "_now", lambda: NOW.astimezone(timezone.utc))
    told = []
    monkeypatch.setattr(gc, "tell_login", lambda ctx, uid, words, ref: told.append((uid, words, ref)) or True)
    fake.told = told
    return fake


def _biz(db):
    return dict(db.t["businesses"][0])


def _row(db, f):
    return next(r for r in db.t["church_follow_ups"] if r["id"] == f)


def _brief(db, f=fid(1), viewer=""):
    return gb.brief(_biz(db), _row(db, f), viewer_cid=viewer, now=NOW.astimezone(timezone.utc))


def _notes(db, f):
    return [n for n in db.t["church_follow_up_notes"] if n["follow_up_id"] == f]


# ── 1. the brief ──────────────────────────────────────────────────────

def test_the_brief_says_who_they_are_what_they_asked_and_how_to_reach_them(db):
    b = _brief(db)
    g = b["guest"]
    assert (g["name"], g["first"], g["door"], g["door_words"]) == ("Maria Lopez", "Maria", "kids", "Kids desk")
    assert g["visit"] == "First visit yesterday, 10:30 AM · invited by Denise"
    assert b["kids"] == {"line": "Sofia (7) and Mateo (4)", "count": 2}
    assert [w["key"] for w in b["wants"]] == ["group", "serve", "baptism", "class", "pastor"]
    assert b["prefers_text"] is True and b["reach"] == "text"
    assert b["chips"] == ["Kids desk", "2 kids", "Asked for 5 things", "Prefers a text", "Prayer: with the pastors"]
    assert b["summary"] == (
        "Denise Robinson invited Maria. Sofia (7) and Mateo (4) were in Kids. On the card, Maria asked to find a group, "
        "serve, get baptized, take a class and talk with a pastor. Maria would rather get a text than a call. Maria "
        "shared a prayer request, and the pastors have it.")
    assert b["opening"] == ("Hi Maria, this is Renee from Grace Hill. We loved having you and the kids yesterday. "
                            "I just wanted to say thank you for coming.")
    assert b["follow_up"]["due_words"] == "Tuesday 6 PM" and b["follow_up"]["caller"]["name"] == "Renee Ellis"
    assert b["prayer_line"] == "They shared a prayer request; the pastors have it."


def test_the_prayer_is_a_flag_its_words_never_read_or_said(db):
    db.paths.clear()
    b = _brief(db)
    assert "PRIVATE-WORDS" not in json.dumps(b) and "surgery" not in json.dumps(b)
    assert not any(p.startswith("/ministry_care_requests") for p in db.paths)
    db.t["contacts"][-2]["metadata"]["new_here"]["card"]["prayer"] = False
    b = _brief(db)
    assert b["prayer"] is False and b["prayer_line"] is None and "prayer" not in b["summary"]


def test_a_guest_with_no_kids_no_one_who_invited_them_and_no_asks(db):
    b = _brief(db, fid(2))
    assert b["kids"] is None and b["wants"] == [] and b["asks"] == [] and b["mentions"] == []
    assert b["guest"]["invited_by"] == "" and "invited" not in b["guest"]["visit"]
    assert b["summary"] == "Tyrell texted NEW yesterday."
    assert b["opening"] == ("Hi Tyrell, this is Renee from Grace Hill. We loved having you yesterday. "
                            "I just wanted to say thank you for coming.")
    assert b["prefers_text"] is False and b["chips"] == ["Text NEW"]


def test_the_texts_so_far_and_whats_next(db):
    t = _brief(db)["texts"]
    assert t["ok"] is True
    assert [(s["label"], s["state"], s["when"]) for s in t["steps"]] == [
        ("Welcome text", "done", "yesterday 11:05 AM"), ("Thank-you text", "done", "yesterday 2:05 PM"),
        ("Monday note", "waiting", "today 10 AM"), ("Invite back", "waiting", "Thursday 6 PM")]
    assert t["next"] == {"label": "Monday note", "when": "today 10 AM"}
    db.t["contacts"][-2]["metadata"]["new_here"].update(texts_ok=False, texts="no_yes")
    t = _brief(db)["texts"]
    assert t["ok"] is False and t["steps"] == [] and t["note"] == "The church hasn’t texted them: no yes to texts."


def test_worth_mentioning_is_the_churchs_real_things_only(db):
    lines = [m["line"] for m in _brief(db)["mentions"]]
    assert lines == [
        "Men’s Breakfast meets Saturdays, 8 am. Ben Carter leads it.",
        "Women’s Study meets Wednesdays at 7 PM. Alicia Grant leads it.",
        "Teams to serve on: Hospitality Team and Parking Team.",
        "Baptism goes to Angela Price (Baptism minister).",
        "Open to join now: Foundations.",
        "A pastor to talk with: Kevin McCloud (Lead Pastor).",
    ]
    joined = " ".join(lines)
    for never in ("Youth Night", "Greeters", "Elders", "Ordination"):
        assert never not in joined
    # Nothing at the church for it: the line is left out, never made up.
    db.t["groups"], db.t["academy_courses"], db.t["intake_forms"] = [], [], []
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["role"] == "pastor"]
    lines = [m["line"] for m in _brief(db)["mentions"]]
    assert lines == ["Baptism goes to Kevin McCloud (Lead Pastor).", "A pastor to talk with: Kevin McCloud (Lead Pastor)."]


def test_what_chief_will_do_for_each_tap(db):
    b = _brief(db)
    asks = {a["key"]: a for a in b["asks"]}
    assert asks["group"]["line"] == "Note on Maria’s follow-up that they’d like to find a group"
    assert [c["line"] for c in asks["group"]["choices"]] == [
        "Note on Maria’s follow-up that they’d like to try Men’s Breakfast",
        "Hand Maria’s group step to Alicia Grant, who leads Women’s Study"]
    assert [c["id"] for c in asks["serve"]["choices"]] == ["Hospitality Team", "Parking Team"]
    assert asks["serve"]["choices"][0]["line"] == "Hand Maria’s step to serve on Hospitality Team to Tasha Williams (Team leader)"
    assert asks["baptism"]["line"] == "Hand Maria’s baptism step to Angela Price (Baptism minister)"
    assert asks["pastor"]["line"] == "Hand Maria’s ask to talk with a pastor to Kevin McCloud (Lead Pastor)"
    assert asks["class"]["line"] == "Note on Maria’s follow-up that they’d like to take Foundations"
    will = {o["key"]: o["will"] for o in b["outcomes"]}
    assert will["talked"] == ["Mark “Reach out” done", "Keep Thursday’s invite, since Maria hasn’t been back yet"]
    assert will["message"][:2] == ["Mark “Reach out” done", "Hand on what they asked for once you log “Talked”"]
    assert will["noanswer"][0] == "Keep the call on your list, due Tuesday 6 PM"
    assert will["notnow"][0] == "Keep Maria on your list, and hand nothing on"
    # Back since: New here skips the invite by its own rule, and the brief says so.
    db.t["attendance"].append({"id": "a1", "business_id": BIZ, "contact_id": MARIA,
                               "checked_in_at": at(datetime(2026, 11, 23, 8, tzinfo=ET))})
    assert _brief(db)["outcomes"][0]["will"][-1] == "Skip Thursday’s invite, since Maria has been back"


def test_another_caller_tells_people_and_care_by_name(db):
    _row(db, fid(1))["leader_contact_id"] = MINISTER
    asks = {a["key"]: a for a in _brief(db)["asks"]}
    assert asks["group"]["line"] == "Tell People & Care (Renee Ellis) Maria would like to find a group"
    assert _brief(db)["opening"].startswith("Hi Maria, this is Angela from Grace Hill.")


# ── 2. who may read it ────────────────────────────────────────────────

@pytest.fixture
def office(db, monkeypatch):
    import church_areas
    import church_duties
    who = {"role": "manager", "id": RENEE_SEAT, "areas": {"areas": ["worship_media"]}}
    monkeypatch.setattr(ba, "_resolve_role", lambda b, u: who["role"])
    monkeypatch.setattr(ba.billing_context, "set_current", lambda b: None)
    monkeypatch.setattr(church_duties, "_CACHE", {})
    monkeypatch.setattr(church_areas, "mode", lambda: "on")
    monkeypatch.setattr(church_areas, "my_areas", lambda b, u, r: who["areas"])
    app = FastAPI()
    app.include_router(gb.router)
    import church_router
    app.include_router(church_router.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email="x@example.com",
                                                     user_metadata={"full_name": "Renee Ellis"})))
    c = TestClient(app)
    c.who = who
    return c


def _get(office, f=fid(1)):
    return office.get(f"/church/guests/{BIZ}/brief/{f}")


def test_the_caller_reads_their_guests_brief_whatever_their_areas(office, db):
    r = _get(office)
    assert r.status_code == 200, r.text
    assert r.json()["guest"]["name"] == "Maria Lopez"


def test_a_login_that_isnt_the_caller_needs_the_guests_room(office, db):
    office.who.update(id=MEDIA_SEAT, areas={"areas": ["worship_media"]})
    assert _get(office).status_code == 403
    office.who.update(areas={"areas": ["people_care"]})
    assert _get(office).status_code == 200
    office.who.update(role="admin", id=ADMIN_SEAT, areas={"areas": []})
    assert _get(office).status_code == 200


def test_outsiders_and_seats_below_manager_get_nothing(office, db):
    office.who.update(role="member")
    assert _get(office).status_code == 404
    office.who.update(role=None, id="u-stranger")
    assert _get(office).status_code == 404


def test_the_switch_off_and_a_card_that_isnt_a_guests(office, db):
    db.t["church_follow_ups"].append(dict(_row(db, fid(1)), id=fid(9), card_key="form:f-baptism", path_kind="baptism",
                                          source_event="b"))
    assert _get(office, fid(9)).status_code == 404
    assert _get(office, fid(8)).status_code == 404
    db.on["on"] = False
    assert _get(office).status_code == 404
    assert gb.brief_for(_biz(db), fid(1)) is None


# ── 3. how did it go ──────────────────────────────────────────────────

def _log(office, outcome, picks=None, text="", f=fid(1)):
    return office.post(f"/church/follow-ups/{f}/note", params={"business_id": BIZ},
                       json={"text": text, "pastors_only": False, "outcome": outcome, "picks": picks or {}})


def _handoffs(db):
    return {r["card_key"]: r for r in db.t["church_follow_ups"] if str(r.get("card_key")).startswith("call:")}


def test_talked_hands_each_ask_to_its_person_and_never_twice(office, db):
    r = _log(office, "talked", {"group": G_WOMEN, "serve": "Hospitality Team"}, "Loved Sunday.")
    assert r.status_code == 200, r.text
    did = r.json()["did"]
    made = _handoffs(db)
    assert {k: v["leader_contact_id"] for k, v in made.items()} == {
        "call:group": ALICIA, "call:serve": TASHA, "call:baptism": MINISTER, "call:pastor": PASTOR}
    assert made["call:baptism"]["path_kind"] == "baptism" and made["call:serve"]["path_kind"] == "serve"
    assert made["call:group"]["reason"] == "Maria asked on their welcome call to try Women’s Study, and Alicia leads it."
    for row in made.values():
        assert row["contact_id"] == MARIA and row["answers"][0]["q"] == gb.ASKED
        assert not guest_path.is_guest_follow_up(row), "a hand-off is a normal follow-up, not a second guest call"
        assert any(n["body"] == f"{gb.ASKED} with Renee Ellis." for n in _notes(db, row["id"]))
    assert did == ["Handed Maria’s “Find a group” to Alicia Grant.", "Handed Maria’s “Serve” to Tasha Williams.",
                   "Handed Maria’s “Get baptized” to Angela Price.",
                   "Noted for People & Care: Maria would like to take Foundations.",
                   "Handed Maria’s “Talk with a pastor” to Kevin McCloud."]
    guest = _row(db, fid(1))
    assert guest["step"] == 1, "Talked finishes Reach out"
    kinds = [n["kind"] for n in _notes(db, fid(1))]
    assert kinds.count("talked") == 1 and "step" in kinds
    assert db.told == [], "Renee is People & Care and made the call: her own follow-up's note says it"
    # The same tap again (or a later Talked): nothing new, nothing twice.
    again = _log(office, "talked", {"group": G_WOMEN, "serve": "Hospitality Team"})
    assert again.json()["did"] == [] and len(_handoffs(db)) == 4
    asks = {a["key"]: a for a in _brief(db)["asks"]}
    assert all(a["done"] for a in asks.values())
    assert asks["baptism"]["line"] == "“Get baptized” was already handed on from this call"


def test_a_group_whose_leader_holds_no_role_and_no_pick_go_to_people_and_care(office, db):
    _row(db, fid(1))["leader_contact_id"] = MINISTER        # someone else made the call
    r = _log(office, "talked", {"group": G_MEN, "serve": "", "baptism": gb.SKIP, "pastor": gb.SKIP, "class": gb.SKIP})
    did = r.json()["did"]
    assert did == ["Noted for People & Care: Maria would like to try Men’s Breakfast.",
                   "Noted for People & Care: Maria would like to serve."]
    assert _handoffs(db) == {}, "skipped asks and notes hand nothing on"
    bodies = [n["body"] for n in _notes(db, fid(1)) if n["author_kind"] == "chief"]
    assert f"{gb.ASKED}: Find a group. Maria Lopez would like to try Men’s Breakfast. Noted here for People & Care." in bodies
    [(uid, words, ref)] = db.told
    assert uid == RENEE_SEAT and words["body"].startswith("Maria Lopez talked with Angela Price and would like to try")
    assert ref == f"gb-pc-{fid(1)}"


def test_an_ask_already_open_for_them_is_left_where_it_is(office, db):
    db.t["church_follow_ups"].append({
        "id": fid(5), "business_id": BIZ, "contact_id": MARIA, "card_key": "form:f-baptism", "card_name": "Baptism",
        "path_kind": "baptism", "answers": [], "steps": cfu.PATHS["baptism"], "step": 0, "status": "open",
        "leader_contact_id": PASTOR, "created_at": at(SUNDAY), "source_event": "bap"})
    asks = {a["key"]: a for a in _brief(db)["asks"]}
    assert asks["baptism"]["done"] is True and asks["baptism"]["line"] == "Already with Kevin McCloud: “Get baptized”"
    _log(office, "talked", {"group": gb.SKIP, "serve": gb.SKIP, "class": gb.SKIP, "pastor": gb.SKIP})
    assert "call:baptism" not in _handoffs(db)


def test_the_other_taps_hand_nothing_on(office, db):
    for outcome in ("message", "noanswer", "notnow"):
        r = _log(office, outcome)
        assert r.status_code == 200 and r.json()["did"] == []
    assert _handoffs(db) == {}
    assert _row(db, fid(1))["step"] == 1, "a message reached them: Reach out is done"
    kinds = [n["kind"] for n in _notes(db, fid(1)) if n["author_kind"] == "office" and n["kind"] != "step"]
    assert kinds == ["message", "noanswer", "notnow"]


def test_no_answer_keeps_the_call_open_and_a_bad_outcome_is_refused(office, db):
    assert _log(office, "noanswer").status_code == 200
    assert _row(db, fid(1))["step"] == 0
    assert _log(office, "maybe").status_code == 400
    plain = office.post(f"/church/follow-ups/{fid(1)}/note", params={"business_id": BIZ}, json={"text": ""})
    assert plain.status_code == 400, "a plain note still needs words"
    old = office.post(f"/church/follow-ups/{fid(1)}/note", params={"business_id": BIZ}, json={"text": "Hello"})
    assert old.status_code == 200 and "did" not in old.json(), "the old app's note is the note it always was"


def test_with_the_path_off_a_call_is_just_a_note(office, db):
    db.on["on"] = False
    r = _log(office, "talked", {"group": G_WOMEN})
    assert r.status_code == 200 and r.json()["did"] == []
    assert _handoffs(db) == {}
    assert _row(db, fid(1))["step"] == 1


def test_a_hand_off_says_what_was_asked_in_the_leaders_email(db):
    row = {"card_key": "call:baptism", "answers": [{"q": gb.ASKED, "a": "Get baptized"}], "reason": "Baptism cards go."}
    assert cfu._came_line(row, "Maria Lopez", "Grace Hill Church") == (
        "Maria Lopez asked for this on their welcome call at Grace Hill Church: <b>Get baptized</b>. "
        "Chief handed them to you. Baptism cards go.")
    assert cfu._came_line({"card_name": "Serve with us", "reason": ""}, "Ann", "Grace Hill").startswith(
        "Ann filled in the <b>Serve with us</b> at Grace Hill")


# ── 4. the Lead tab: a member caller ──────────────────────────────────

def test_the_lead_tab_draws_the_brief_and_what_chief_will_do(db):
    import member_portal_lead as mpl
    b = _brief(db)
    view = cfu._view(_row(db, fid(1)), {MARIA: {"id": MARIA, "name": "Maria Lopez", "email": "", "phone": "+15555550142"}},
                     [], {}, NOW.astimezone(timezone.utc))
    token = mpl.BRIEF.set(b)
    try:
        page = mpl._file(view, _biz(db), {"id": RENEE, "name": "Renee Ellis"})
    finally:
        mpl.BRIEF.reset(token)
    assert "Chief’s brief" in page and "Hi Maria, this is Renee from Grace Hill." in page
    assert page.index("sms:") < page.index("tel:"), "they'd rather get a text: Text comes first"
    assert 'name="pick_group"' in page and 'name="pick_serve"' in page and 'value="skip"' in page
    assert "Hand Maria’s group step to Alicia Grant, who leads Women’s Study" in page
    assert 'data-for="noanswer"' in page and "PRIVATE-WORDS" not in page
    plain = mpl._file(view, _biz(db), {"id": RENEE, "name": "Renee Ellis"})
    assert "Chief’s brief" not in plain and "pick_group" not in plain, "no brief: the file as it was"


def test_a_member_callers_talked_hands_on_the_same_way(db):
    cfu.leader_note(BIZ, {"id": RENEE, "name": "Renee Ellis"}, fid(1), "talked", "", False)
    did = gb.after_call(BIZ, fid(1), "talked", {"group": G_WOMEN, "serve": gb.SKIP}, by_name="Renee Ellis")
    assert "Handed Maria’s “Find a group” to Alicia Grant." in did
    assert set(_handoffs(db)) == {"call:group", "call:baptism", "call:pastor"}


# ── 5. the card's new questions ───────────────────────────────────────

def test_the_new_here_card_asks_the_new_questions_only_with_the_path_on():
    import new_here
    on = new_here.card_html("Grace Hill Church", "ABCD2345", path=True)
    for q in ("Who invited you?", "Your kids' names and ages", "What would you like?", "Best way to reach you",
              'value="group"', 'value="class"', 'value="text"'):
        assert q in on
    off = new_here.card_html("Grace Hill Church", "ABCD2345")
    assert "Who invited you?" not in off and "Best way to reach you" not in off


def test_the_card_keeps_the_answers_and_the_caller_reads_them_never_the_prayer(db, monkeypatch):
    import new_here
    monkeypatch.setattr(new_here, "second_door", lambda *a, **k: False)
    started = {}
    monkeypatch.setattr(cfu, "start", lambda *a, **k: started.update(k) or None)
    guest = {"id": TYRELL, "name": "+15555550199", "phone": "+15555550199", "tags": [],
             "metadata": dict(db.t["contacts"][-1]["metadata"])}
    form = {"name": "Tyrell Hayes", "first": "yes", "heard": "Online", "kids": "2", "prayer": "PRIVATE-WORDS please",
            "invited": "  Denise   Robinson ", "kid_names": "Ava, 6 and Ben, 3", "wants": ["serve", "nope", "group"],
            "reach": "text"}
    assert new_here.save_card(_biz(db), guest, form)
    card = next(c for c in db.t["contacts"] if c["id"] == TYRELL)["metadata"]["new_here"]["card"]
    assert card["invited_by"] == "Denise Robinson" and card["kids_names"] == "Ava, 6 and Ben, 3"
    assert card["wants"] == ["group", "serve"] and card["reach"] == "text" and card["prayer"] is True
    answers = started["answers"]
    assert {"q": "Who invited them", "a": "Denise Robinson"} in answers
    assert {"q": "They'd like to", "a": "Find a group and serve"} in answers
    assert {"q": "Best way to reach them", "a": "Text me instead"} in answers
    assert "PRIVATE-WORDS" not in json.dumps(answers)
    # The path off: the card is what it was.
    db.on["on"] = False
    assert new_here.save_card(_biz(db), guest, form)
    card = next(c for c in db.t["contacts"] if c["id"] == TYRELL)["metadata"]["new_here"]["card"]
    assert set(card) == {"first_time", "heard", "kids", "prayer"}


def test_the_member_apps_im_new_asks_who_invited_and_the_best_way_with_the_path_on():
    import member_im_new as imn
    form = {"first": "yes", "kids": "yes", "ages": "4 and 7", "invited": "Denise", "reach": "text"}
    a = imn.clean(form, ["group"], path=True)
    assert a["invited"] == "Denise" and a["reach"] == "text"
    lines = imn.answers_for(a)
    assert {"q": "Who invited them", "a": "Denise"} in lines and {"q": "Best way to reach them", "a": "Text me instead"} in lines
    off = imn.clean(form, ["group"])
    assert "invited" not in off and "reach" not in off
    assert all(x["q"] not in ("Who invited them", "Best way to reach them") for x in imn.answers_for(off))


# ── 6. the bulletin's guest card that is a general form ───────────────

def test_a_general_form_picked_as_the_guest_card_is_a_guests_call(db, monkeypatch):
    import new_here
    monkeypatch.setattr(new_here, "enroll_by_id", lambda *a, **k: None)
    biz = _biz(db)
    biz["settings"] = dict(biz["settings"], new_here={"guest_form": "f-welcome"})
    db.t["businesses"][0]["settings"] = biz["settings"]
    db.t["contacts"].append({"id": cid(40), "business_id": BIZ, "name": "Sam Lee", "email": "", "phone": "",
                             "metadata": {}, "created_at": at(SUNDAY)})
    row = cfu.on_intake_form(biz, dict(WELCOME_CARD, business_id=BIZ), {"heard": "Online"}, cid(40), "rcpt-1")
    assert row["path_kind"] == "connect" and guest_path.is_guest_follow_up(row)
    assert row["assigned_by"].startswith("guest_calls:"), "Who calls our guests hands it"
    # Not the picked card: a general form keeps its own path.
    other = dict(WELCOME_CARD, id="f-contact", name="Contact us")
    row = cfu.on_intake_form(biz, other, {"heard": "Online"}, cid(40), "rcpt-2")
    assert row["path_kind"] == "general" and not guest_path.is_guest_follow_up(row)
    # The path off: the picked card is the general form it always was.
    db.on["on"] = False
    row = cfu.on_intake_form(biz, dict(WELCOME_CARD, business_id=BIZ), {"heard": "Online"}, DENISE, "rcpt-3")
    assert row["path_kind"] == "general" and row["assigned_by"] == "chief"


def test_one_group_is_the_callers_pick_until_they_change_it(db):
    db.t["groups"] = [g for g in db.t["groups"] if g["id"] != G_MEN]
    db.t["intake_forms"] = []
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["scope"] != "Parking Team"]
    asks = {a["key"]: a for a in _brief(db)["asks"]}
    assert asks["group"]["pick"] == G_WOMEN and asks["serve"]["pick"] == "Hospitality Team"
    assert asks["baptism"]["pick"] == ""


def test_the_member_pages_church_row_has_no_owner_and_the_brief_reads_one(db):
    row = {k: v for k, v in _biz(db).items() if k != "owner_id"}
    b = gb.brief_for(row, fid(1), viewer_cid=RENEE, now=NOW.astimezone(timezone.utc))
    assert b and b["guest"]["name"] == "Maria Lopez"
    assert gb.brief_for(row, fid(2), now=NOW.astimezone(timezone.utc))["guest"]["name"] == "Tyrell Hayes"
    assert gb.brief_for(row, "not-an-id") is None


def test_a_group_read_that_fails_hands_nothing_and_writes_nothing(office, db):
    db.broken = {"groups"}
    r = _log(office, "talked", {"group": G_WOMEN, "serve": gb.SKIP, "baptism": gb.SKIP, "pastor": gb.SKIP,
                                "class": gb.SKIP})
    assert r.json()["did"] == ["Chief couldn’t check who takes “Find a group” just now, so it wasn’t handed on yet."]
    assert _handoffs(db) == {}
    assert not any(str(n["body"]).startswith(gb.ASKED) for n in _notes(db, fid(1)))
    # Read again later, the same pick goes where it should.
    db.broken = set()
    r = _log(office, "talked", {"group": G_WOMEN, "serve": gb.SKIP, "baptism": gb.SKIP, "pastor": gb.SKIP,
                                "class": gb.SKIP})
    assert r.json()["did"] == ["Handed Maria’s “Find a group” to Alicia Grant."]
    db.broken = {"church_leader_roles"}
    did = gb.after_call(BIZ, fid(1), "talked", {"serve": "Hospitality Team", "class": gb.SKIP})
    assert did and all("couldn’t" in d for d in did) and set(_handoffs(db)) == {"call:group"}


def test_the_brief_never_says_no_kids_or_no_caller_on_a_failed_read(office, db):
    db.broken = {"children"}
    assert _get(office).status_code == 503
    assert gb.brief_for(_biz(db), fid(1)) is None
    db.broken = {"household_adults"}
    assert _get(office).status_code == 503
    db.broken = set()
    assert _get(office).json()["others_read"] is True

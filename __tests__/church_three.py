"""The three test churches (docs/CHURCH_LEADERS_MAP.md §6): Love City, Grace
Baptist and New Hope, all in one in-memory PostgREST, so every reader runs its
real path and a read that leaks across churches shows.

    build(monkeypatch, *, map_on=True, filled=True, migrated=True) -> db

Each library is filled by the real church_roles.ensure_library; then the
custom roles, the holders, the households and Sunday attendance, the office
logins and the duty moves. The people are made up, except Love City's office
(test_church_duties' logins). Who sees what is on, as production runs it.

The map (departments and their units, answers-to links, money levels,
office-overseer roles, the switches flipped) is kept in `db.map_intent`, by
role key and person id, and with filled=True written into the map's tables
(supabase/APPLY-2026-11-04-church-map.sql) as the office will write it (PR 5);
filled=False is the empty map every preservation test uses. migrated=False is
the database before that file: a read or write naming its columns or tables
fails as PostgREST's would. CHURCH_MAP follows map_on.

    db.who[church][handle] -> a person's (or a login's) id
    db.label[id]           -> that person's first name, or a login's name
"""
from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_checks  # noqa: E402
import church_duties as cd  # noqa: E402
import church_follow_up as cfu  # noqa: E402
import church_leader_tasks as clt  # noqa: E402
import church_map  # noqa: E402
import church_money_levels as cml  # noqa: E402
import church_roles as cr  # noqa: E402
import church_shepherd_signals as sig  # noqa: E402
import member_asks  # noqa: E402
import messaging_router  # noqa: E402
import sb_clients  # noqa: E402
from test_church_duties import ADMIN, C_JESS, C_NAIYA, JESS, LAQ, NAIYA, PLATFORM, SHAP, TIARA, DutyDB  # noqa: E402
from test_church_follow_up import BIZ as LOVE_CITY, OWNER as LC_OWNER, SERVE  # noqa: E402

GRACE = "2b000000-0000-4000-8000-000000000000"
NEW_HOPE = "3b000000-0000-4000-8000-000000000000"
G_OWNER = "2a000000-0000-4000-8000-000000000000"
NH_OWNER = "3a000000-0000-4000-8000-000000000000"
CHURCHES = (LOVE_CITY, GRACE, NEW_HOPE)
NAMES = {LOVE_CITY: "love_city", GRACE: "grace", NEW_HOPE: "new_hope"}
OWNER_EMAIL = {LC_OWNER: PLATFORM, G_OWNER: "pastor@gracebaptist.org", NH_OWNER: "nathan@newhope.church"}
# Every Sunday the senior pastor checked in, 8/23 to 11/1; the drifting
# family came 9/20 and 9/27, then missed 10/4, 10/11 and 10/18.
SUNDAYS = [date(2026, 11, 1) - timedelta(weeks=i) for i in range(11)]
FAMILY_CAME = (date(2026, 9, 20), date(2026, 9, 27))
TABLES = ("business_sites business_users contacts church_leader_roles church_role_defs church_role_settings "
          "intake_forms households household_adults children child_care_notes church_family_dismissals attendance "
          "module_entries church_shepherds church_shepherd_settings church_shepherd_touches church_shepherd_signals "
          "church_shepherd_notices church_shepherd_drafts church_checkin_settings church_duty_holders "
          "church_duty_changes church_boards church_board_members church_check_approvals church_follow_ups "
          "church_follow_up_notes church_area_places groups group_members tasks space_leaders academy_courses "
          "academy_enrollments worship_team msg_member_officers msg_safety_officers church_space_bookings events "
          "business_collaborators church_departments church_department_units").split()
# What the map's migration adds: before it, PostgREST refuses any read or write that names one.
MAP_NEW = re.compile(r"\b(can_shepherd|can_oversee|can_lead|can_board_yes|can_see_all|made_for|answers_to_contact_id|"
                     r"pastor_from_cents|board_over_cents|pastor_yes_roles|office_overseer_roles|map_by|map_at|"
                     r"church_departments|church_department_units)\b")


def pid(church: int, n: int) -> str:
    return f"{church}c000000-0000-4000-8000-{n:012d}"


def uid(church: int, n: int) -> str:
    return f"{church}a000000-0000-4000-8000-{n:012d}"


class ThreeDB(DutyDB):
    """test_church_duties' fake (the role tests' PostgREST with church_duty_set),
    plus `like`, which the shepherding emails' sent-once ledger reads by, and
    ids that come out the same on every run, and (migrated=False) the
    database before the map's migration. Migrated, a role insert runs the
    live trigger's fill (church_role_defs_switches): a row with none of its
    switches said, all at their column defaults, gets today's rule. Each
    insert's body, as sent, is kept in `role_inserts`."""
    migrated = True

    def _switches_trigger(self, row):
        self.role_inserts = getattr(self, "role_inserts", []) + [dict(row)]
        if row.get("can_shepherd") is None and not row.get("made_for") and \
                not any(row.get(k) for k in ("can_oversee", "can_lead", "can_board_yes", "can_see_all")):
            from test_church_map_vectors import switches as todays_rule
            row.update(todays_rule({"handles": [], **row}))
        return row

    def _refused(self, path, body=None):
        names = path + " " + " ".join(k for b in (body if isinstance(body, list) else [body or {}]) for k in b)
        return not self.migrated and MAP_NEW.search(names)

    def nid(self, table):
        self.made = getattr(self, "made", 0) + 1
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"church-three/{table}/{self.made}"))

    def get(self, path, **kw):
        return None if self._refused(path) else super().get(path, **kw)

    def post(self, path, body, prefer=None, **kw):
        if self._refused(path, body):
            return None
        if isinstance(body, dict) and "id" not in body and not path.startswith("/rpc/"):
            body = dict(body, id=self.nid(path.lstrip("/").split("?")[0]))
        if self.migrated and path.startswith("/church_role_defs") and isinstance(body, dict):
            body = self._switches_trigger(dict(body))
        return super().post(path, body, prefer, **kw)

    def patch(self, path, body, **kw):
        return None if self._refused(path, body) else super().patch(path, body, **kw)

    def _match(self, row, filters):
        rest = []
        for f in filters:
            if f[0] != "or" and f[1] == "like":
                if not fnmatch.fnmatchcase(str(row.get(f[0]) or ""), f[2]):
                    return False
            else:
                rest.append(f)
        return super()._match(row, rest)


class _Church:
    def __init__(self, db, biz, n, domain):
        self.db, self.biz, self.n, self.domain = db, biz, n, domain
        self.who = db.who.setdefault(biz, {})
        self.row = next(b for b in db.t["businesses"] if b["id"] == biz)

    def person(self, n, name, *, email=None, cid=None, born=None, status="active"):
        cid = cid or pid(self.n, n)
        first = name.split()[0]
        self.db.t["contacts"].append({"id": cid, "business_id": self.biz, "name": name, "status": status,
                                      "birthdate": born, "metadata": {}, "phone": "",
                                      "email": email or f"{first.lower()}@{self.domain}"})
        self.who[first.lower()] = cid
        self.db.label[cid] = first
        return cid

    def hold(self, key, *handles, scope=""):
        for h in handles:
            self.db.t["church_leader_roles"].append({
                "id": self.db.nid("church_leader_roles"), "business_id": self.biz, "contact_id": self.who[h], "role": key,
                "scope": scope, "status": "active", "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None,
                "answers_to_contact_id": None})

    def login(self, n, handle, role, *, lane=None, areas=None, tie=False):
        u = {"minnie": ADMIN, "naiya": NAIYA, "tiara": TIARA, "laquesha": LAQ, "jessica": JESS,
             "shapretta": SHAP}[handle] if self.biz == LOVE_CITY else uid(self.n, n)
        c = next(x for x in self.db.t["contacts"] if x["id"] == self.who[handle])
        if lane and areas is None:
            areas = ca.LANES[lane]["areas"]          # what an invite on a lane writes
        self.db.t["business_users"].append({
            "business_id": self.biz, "user_id": u, "role": role, "invited_email": c["email"].lower(),
            "lane": lane, "areas": areas, "contact_id": c["id"] if tie else None, "name": c["name"],
            "status": "active"})
        self.who[handle + "@"] = u
        self.db.label[u] = c["name"].split()[0]
        return u

    def retitle(self, key, title):
        rid = next(d["id"] for d in self.db.t["church_role_defs"] if d["business_id"] == self.biz and d["key"] == key)
        cr.update_role(self.biz, rid, {"title": title})

    def family(self, name, adults, youth, shepherd):
        hid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.biz}-{name}"))
        self.db.t["households"].append({"id": hid, "business_id": self.biz, "name": name, "created_at": "2026-09-01"})
        for a in adults:
            self.db.t["household_adults"].append({"household_id": hid, "contact_id": self.who[a],
                                                  "business_id": self.biz, "relationship": "parent"})
        for k in youth:
            c = next(x for x in self.db.t["contacts"] if x["id"] == self.who[k])
            self.db.t["children"].append({"id": self.db.nid("children"), "business_id": self.biz, "household_id": hid,
                                          "contact_id": c["id"], "first_name": c["name"].split()[0],
                                          "last_name": c["name"].split()[-1], "birthdate": c["birthdate"],
                                          "active": True})
        if shepherd:
            self.db.t["church_shepherds"].append({"household_id": hid, "business_id": self.biz, "reason": "",
                                                  "shepherd_contact_id": self.who[shepherd],
                                                  "assigned_at": "2026-08-01T12:00:00+00:00"})
        self.who["family"] = hid
        return hid

    def sundays(self, regular, came):
        for d in SUNDAYS:
            eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.biz}-svc-{d}"))
            self.db.t["module_entries"].append({"id": eid, "business_id": self.biz,
                                                "data": {"_checkin_day": d.isoformat()}})
            for h in [regular] + ([came] if d in FAMILY_CAME else []):
                self.db.t["attendance"].append({"id": self.db.nid("attendance"), "business_id": self.biz, "entry_id": eid,
                                                "contact_id": self.who[h], "method": "self",
                                                "checked_in_at": f"{d.isoformat()}T15:10:00+00:00"})

    def group(self, name, leader):
        gid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.biz}-group-{name}"))
        self.db.t["groups"].append({"id": gid, "business_id": self.biz, "name": name, "active": True,
                                    "kind": "ministry"})
        self.db.t["group_members"].append({"group_id": gid, "business_id": self.biz, "contact_id": self.who[leader],
                                           "role": "leader"})
        return gid

    def late_work(self, leader, key, youth):
        """Y's past-due task (due 10/26) and Y's late youth follow-up (due 10/26)."""
        b, y = self.biz, self.who[leader]
        self.db.t["tasks"].append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{b}-task")), "business_id": b, "status": "todo",
            "title": "Plan the youth lock-in", "description": None, "due_date": "2026-10-26",
            "assigned_contact_id": y, "assigned_to": None, "leader_told_at": "2026-10-20T12:00:00+00:00",
            "late_told_at": None, "done_by_contact_id": None, "completed_at": None,
            "created_at": "2026-10-20T12:00:00+00:00", "handed_by": self.row["owner_id"]})
        self.db.t["church_follow_ups"].append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{b}-fu")), "business_id": b, "status": "open",
            "contact_id": self.who[youth], "leader_contact_id": y, "leader_role": key, "card_name": "Connect card",
            "path_kind": "connect", "answers": [], "reason": "", "step": 1, "late_level": 0,
            "steps": [{"title": "Reach out", "rule": "within two days"}, {"title": "Welcome them in", "rule": "this week"}],
            "due_at": "2026-10-26T12:00:00+00:00", "leader_told_at": "2026-10-20T12:00:00+00:00",
            "assigned_at": "2026-10-20T12:00:00+00:00", "created_at": "2026-10-20T12:00:00+00:00"})


def _love_city(db):
    c = _Church(db, LOVE_CITY, 1, "lovecity.org")
    for n, name in enumerate(["Andre Wallace", "Marcus Taylor", "Tanya Brooks", "Angela Price", "Ruth Okafor",
                              "Iris Bell", "Ivy Lane", "Paul Mensah", "Eve Hall", "Yolanda Reed", "Cora Diaz",
                              "Tasha Williams", "Tyrone Banks", "Tiara Adams", "Laquesha Bailey-Smith",
                              "Shapretta McClain", "Minnie Tatum", "Calvin Owens", "Dana Owens", "Gloria Hunt"], 2):
        c.person(n, name)
    c.person(1, "Kevin McCloud", email=PLATFORM)
    c.person(0, "Jessica McCloud", email="Jessica@LoveCity.org", cid=C_JESS)
    c.person(0, "Naiya Clark", cid=C_NAIYA)
    c.person(30, "Jaylen Owens", born="2011-03-14")
    # Love City made these before the map: the backfill gave them today's
    # rule, so its Prophets, with no shepherd word, don't shepherd (a new
    # custom pastoral role would: decision 2).
    for title, job, said in (("Prophets", "pastoral", {"can_shepherd": False}), ("Evangelists", "welcome", {})):
        cr.create_role(c.row, {"title": title, "job": job, **said})
    for key, *who in (("pastor", "kevin"), ("executive_pastor", "jessica"), ("associate_pastor", "andre"),
                      ("elders", "marcus", "tanya"), ("ministers", "angela"), ("intercessor_leader", "ruth"),
                      ("intercessors", "iris", "ivy"), ("prophets", "paul"), ("evangelists", "eve"),
                      ("youth_pastor", "yolanda"), ("childrens_director", "cora")):
        c.hold(key, *who)
    c.hold("team_leader", "tasha", scope="Hospitality Team")
    c.hold("team_leader", "tyrone", scope="Youth Ministry (YWD)")
    c.login(0, "minnie", "admin", lane="treasurer")
    c.login(0, "naiya", "manager", lane="office_leadership", tie=True)
    c.login(0, "tiara", "manager", areas=["kids_youth", "people_care", "groups_classes"])
    c.login(0, "laquesha", "manager", lane="sunday_serving")
    c.login(0, "jessica", "manager")
    c.login(0, "shapretta", "manager", lane="media_comms")
    youth = c.group("Youth", "yolanda")
    c.group("Sisters in the City", "gloria")
    board = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{LOVE_CITY}-elder-board"))
    db.t["church_boards"].append({"id": board, "business_id": LOVE_CITY, "name": "Elder Board", "archived": False})
    for h in ("marcus", "tanya"):
        db.t["church_board_members"].append({"business_id": LOVE_CITY, "board_id": board, "contact_id": c.who[h],
                                             "user_id": None, "name": "", "active": True})
    c.family("The Owens family", ["calvin", "dana"], ["jaylen"], "marcus")
    c.sundays("kevin", "calvin")
    c.late_work("yolanda", "youth_pastor", "jaylen")
    w = c.who
    return {"departments": [
        {"name": "Prayer", "leader": w["ruth"], "overseer": w["paul"], "duty": "prayer", "area": "people_care",
         "units": [("role", "intercessor_leader"), ("role", "intercessors")]},
        {"name": "Outreach & Welcome", "leader": w["tasha"], "overseer": w["eve"], "duty": "first_guests",
         "area": "people_care", "units": [("serve_option", "Hospitality Team"), ("role", "welcome_lead"),
                                          ("role", "evangelists")]},
        {"name": "Youth", "leader": w["yolanda"], "overseer": w["andre"], "duty": "youth", "area": "kids_youth",
         "units": [("serve_option", "Youth Ministry (YWD)"), ("group", youth), ("space", "youth")]}],
        "answers_to": {w["marcus"]: w["jessica"]},
        "roles": {"prophets": {"can_oversee": True}, "evangelists": {"can_oversee": True}},
        "settings": {"office_overseer_roles": ["executive_pastor"]}}


def _grace(db):
    c = _Church(db, GRACE, 2, "gracebaptist.org")
    c.person(1, "Samuel Gray", email=OWNER_EMAIL[G_OWNER])
    for n, name in enumerate(["Daniel Moore", "Doris King", "Dwight Fields", "Della Hart", "Yvette Long",
                              "Thelma Ross", "Sharon Wells", "Leon Jordan", "Rita Jordan"], 2):
        c.person(n, name)
    c.person(11, "Mia Jordan", born="2011-05-02")
    rest = [c.person(n, f"G{n:02d} Member") for n in range(12, 91)]       # 90 people in all
    for i in range(29):                                                    # 30 households with the Jordans
        hid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{GRACE}-home-{i}"))
        db.t["households"].append({"id": hid, "business_id": GRACE, "name": f"Household {i}",
                                   "created_at": "2026-09-01"})
        db.t["household_adults"] += [{"household_id": hid, "contact_id": x, "business_id": GRACE,
                                      "relationship": "parent"} for x in rest[i::29]]
    c.hold("pastor", "samuel")
    c.hold("deacons", "daniel", "doris", "dwight", "della")
    c.hold("youth_minister", "yvette")
    c.login(1, "thelma", "admin", lane="treasurer")
    sharon = c.login(2, "sharon", "manager", lane="office_leadership")
    db.t["church_duty_holders"] += [{"business_id": GRACE, "duty": k, "user_id": sharon}
                                    for k, d in cd.CATALOG.items() if not d["money"]]
    youth = c.group("Youth", "yvette")
    c.family("The Jordan family", ["leon", "rita"], ["mia"], "doris")
    c.sundays("samuel", "leon")
    c.late_work("yvette", "youth_minister", "mia")
    w = c.who
    return {"departments": [
        {"name": "Youth", "leader": w["yvette"], "overseer": w["daniel"], "duty": "youth", "area": "kids_youth",
         "units": [("serve_option", "Youth Ministry"), ("group", youth), ("space", "youth")]}],
        "answers_to": {},
        "roles": {"deacons": {"can_shepherd": True, "can_oversee": True}},
        "settings": {"pastor_from_cents": 20_000, "board_over_cents": 100_000}}


def _new_hope(db):
    c = _Church(db, NEW_HOPE, 3, "newhope.church")
    for n, name in enumerate(["Nathan Cole", "Abel Ford", "Amara Stone", "Asher Lyle", "Yusuf Grant", "Elena Ruiz",
                              "Elliot Shaw", "Esther Moss", "Ezra Kim", "Eden Park", "Owen Diaz", "Wren Ellis",
                              "Kara Bell", "Celia Ward", "Tessa Hale", "Olive Marsh", "Paige Lowe", "Sunny Vale",
                              "Mila Fox", "Kira Moon", "Hugo Brandt", "Lena Brandt"], 1):
        c.person(n, name)
    c.person(23, "Max Brandt", born="2011-08-20")
    for n in range(24, 501):                                               # 500 people in all
        c.person(n, f"N{n:03d} Member")
    cr.create_role(c.row, {"title": "Director of Operations", "job": "ministry"})
    c.retitle("pastor", "Senior Pastor")
    c.retitle("youth_pastor", "Youth Director")
    c.retitle("worship_leader", "Worship Director")
    for key, *who in (("pastor", "nathan"), ("associate_pastor", "abel", "amara", "asher"), ("youth_pastor", "yusuf"),
                      ("elders", "elena", "elliot", "esther", "ezra", "eden"), ("director_of_operations", "owen"),
                      ("worship_leader", "wren"), ("childrens_director", "kara"), ("deacons", "celia")):
        c.hold(key, *who)
    c.login(1, "tessa", "admin", lane="treasurer")
    for n, (h, lane) in enumerate((("olive", "office_leadership"), ("paige", "people_care"),
                                   ("sunny", "sunday_serving"), ("mila", "media_comms")), 2):
        c.login(n, h, "manager", lane=lane)
    c.login(6, "owen", "manager", tie=True)
    c.login(7, "kira", "manager", areas=["kids_youth"])
    youth = c.group("Youth", "yusuf")
    c.family("The Brandt family", ["hugo", "lena"], ["max"], "elena")
    c.sundays("nathan", "hugo")
    c.late_work("yusuf", "youth_pastor", "max")
    w = c.who
    dept = [("Worship", "wren", "abel", "sunday_plan", "worship_media",
             [("serve_option", "Worship Team"), ("role", "worship_leader")]),
            ("Youth", "yusuf", "amara", "youth", "kids_youth",
             [("serve_option", "Youth Volunteers"), ("group", youth), ("space", "youth")]),
            ("Kids", "kara", "amara", "kids", "kids_youth", [("serve_option", "Kids Check-in"), ("space", "kids")]),
            ("Care", "celia", "asher", "care_visits", "people_care", [("role", "deacons"), ("role", "care_team")])]
    return {"departments": [{"name": n, "leader": w[ld], "overseer": w[ov], "duty": du, "area": ar, "units": un}
                            for n, ld, ov, du, ar, un in dept],
            "answers_to": {w[e]: w[a] for e, a in (("elena", "amara"), ("elliot", "abel"), ("esther", "asher"),
                                                    ("ezra", "abel"), ("eden", "asher"))},
            "roles": {"elders": {"can_board_yes": True}},
            "settings": {"pastor_from_cents": 100_000, "board_over_cents": 500_000,
                         "office_overseer_roles": ["director_of_operations"]}}


# ─── Probes: who hears, through each path's real entry point ──────────

MONDAYS = [datetime(2026, 10, 19, 15, tzinfo=timezone.utc) + timedelta(weeks=i) for i in range(3)]
MORNING = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)      # every church's morning, a Wednesday
AMOUNTS = (18_000, 25_000, 60_000)
ROOM = "5e000000-0000-4000-8000-000000000001"


def church(db, biz):
    return next(dict(b) for b in db.t["businesses"] if b["id"] == biz)


def _by_email(db, biz, emails):
    first = {c["email"].lower(): c["name"].split()[0] for c in db.t["contacts"] if c["business_id"] == biz}
    return sorted(first.get(e.lower(), e) for e in emails)


def _mail(monkeypatch):
    sent = []

    async def email(biz, to, name, subject, body, key):
        sent.append((to, key))
        return True

    async def alert(*a, **k):
        return True
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(cfu, "_office_alert", alert)
    return sent


def drift_told(monkeypatch, db, biz):
    """Who the shepherd-signals sweep tells about the drifting family on three
    Mondays: the shepherd's digest the first week, then each climb's email."""
    sent, out = _mail(monkeypatch), []
    for i, now in enumerate(MONDAYS):
        sent.clear()
        stats = dict.fromkeys(("churches", "care", "emails", "drifting", "climbed", "resolved"), 0)
        asyncio.run(sig.run_church(church(db, biz), now, stats))
        kind = "digest" if i == 0 else "up"
        out.append(_by_email(db, biz, [to for to, key in sent if key.startswith(f"shep-{biz}-{kind}-")]))
    return out


def late_follow_up(monkeypatch, db, biz):
    """Who Y's late youth follow-up emails a day late, then three days late."""
    sent, out = _mail(monkeypatch), []
    row = next(f for f in db.t["church_follow_ups"] if f["business_id"] == biz)
    for days in (1, 3):
        sent.clear()
        stats = dict.fromkeys(("told", "office", "reached", "nudged", "overseer_told", "next_up"), 0)
        asyncio.run(cfu._sweep_church(biz, [dict(row)], cfu._parse(row["due_at"]) + timedelta(days=days, hours=1),
                                      stats))
        out.append(_by_email(db, biz, [to for to, _k in sent]))
    return out


def late_task(monkeypatch, db, biz):
    """Who Y's past-due task goes up to, in the church's morning."""
    sent = []
    monkeypatch.setattr(clt, "deliver", lambda b, to, *a, **k: sent.append(to))
    monkeypatch.setattr(clt, "zone", lambda b: ZoneInfo(b["settings"]["timezone"]))
    stats = dict.fromkeys(("late", "late_no_one", "late_no_email", "late_unsent"), 0)
    clt.tell_late(church(db, biz), [dict(t) for t in db.t["tasks"] if t["business_id"] == biz], MORNING, stats)
    return _by_email(db, biz, sent)


def room_alerts(monkeypatch, db, biz):
    """The logins a member's room request phones (the bell aside)."""
    import church_spaces
    import notification_engine
    import push_notifications
    phoned = []

    async def bell(*a, **k):
        return None
    monkeypatch.setattr(notification_engine, "create_urgent_alert", bell)
    monkeypatch.setattr(push_notifications, "send_to_user", lambda u, **k: phoned.append(str(u)) or 1)
    monkeypatch.setattr(member_asks, "_later", lambda fn: fn())
    monkeypatch.setattr(member_asks, "open_rooms", lambda b: [{"id": ROOM, "name": "Fellowship Hall"}])
    monkeypatch.setattr(member_asks, "_spaces_tz", lambda b: ZoneInfo("America/New_York"))
    monkeypatch.setattr(member_asks, "_now", lambda: MORNING)
    monkeypatch.setattr(church_spaces, "clashes", lambda *a, **k: False)
    monkeypatch.setattr(church_spaces, "book", lambda *a, **k: {})
    adult = next(a["contact_id"] for a in db.t["household_adults"] if a["business_id"] == biz)
    ok, code, _keep = member_asks.ask_room(church(db, biz), {"id": adult, "name": "A member"}, {
        "space": ROOM, "day": "2026-11-10", "start": "18:00", "end": "20:00", "reason": "Youth night"})
    assert ok, code
    return sorted(db.label[u] for u in phoned)


def logins(db, biz):
    """(user id, role, sign-in email): the owner, then each active seat."""
    b = church(db, biz)
    return [(b["owner_id"], "owner", OWNER_EMAIL[b["owner_id"]])] + [
        (s["user_id"], s["role"], s["invited_email"]) for s in db.t["business_users"]
        if s["business_id"] == biz and s["status"] == "active"]


def money_me(db, biz, user, role, email):
    """A login as Check requests sees it (church_checks._access)."""
    keeps = church_checks.treasurer(biz, user, role)
    return {"biz": church(db, biz), "role": role, "uid": user, "user": SimpleNamespace(email=email),
            "treasurer": keeps, "boss": role in church_checks.KEEPS_ALL,
            "writer": keeps and role in church_checks.WRITERS}


def money(db, biz):
    """(each amount's steps, each step's logins, and the board's people, who
    say yes from the member app): a $180, $250 and $600 request to one payee,
    read by the owner."""
    mes = {u: money_me(db, biz, u, r, e) for u, r, e in logins(db, biz)}
    me = mes[church(db, biz)["owner_id"]]
    needs = {}
    for amt in AMOUNTS:
        row = {"id": f"req-{amt}", "status": "new", "amount_cents": amt, "payee": "Camp Pinewood",
               "created_at": "2026-10-28T15:00:00+00:00", "ministry": "Youth"}
        needs[amt] = cml.of(me, row, cml.context(me, [row], []))["needs"]
    who = {s: sorted(db.label[u] for u, m in mes.items() if s in cml.steps_of(m)) for s in cml.STEPS}
    who["board people"] = sorted(db.label[c] for c in cml.board_people(me))
    return needs, who


def _serve(biz, teams):
    form = dict(SERVE, id=f"f-serve-{biz[:2]}", business_id=biz)
    form["fields"] = [dict(f, options=teams) if f["name"] == "team" else f for f in SERVE["fields"]]
    return form


def write_map(db, biz, m):
    """A church's map_intent into the map's tables: departments and their
    units, holders' answers-to, the settings, and the switches flipped
    (through church_roles.update_role, the office's own write)."""
    defs = {d["key"]: d for d in db.t["church_role_defs"] if d["business_id"] == biz}
    for n, d in enumerate(m["departments"]):
        did = db.nid("church_departments")
        db.t["church_departments"].append({
            "id": did, "business_id": biz, "name": d["name"], "leader_contact_id": d["leader"],
            "overseer_contact_id": d["overseer"], "support_duty": d["duty"], "area": d["area"], "status": "active",
            "source": "office", "sort": n * 10, "updated_by": None, "updated_at": "2026-11-03T12:00:00+00:00"})
        for kind, ref in d["units"]:
            db.t["church_department_units"].append({
                "id": db.nid("church_department_units"), "business_id": biz, "department_id": did, "kind": kind,
                "group_id": ref if kind == "group" else None, "role_id": defs[ref]["id"] if kind == "role" else None,
                "board_id": None, "worship_ministry_id": None, "label": "" if kind in ("group", "role") else ref})
    for h in db.t["church_leader_roles"]:
        if h["business_id"] == biz and h["contact_id"] in m["answers_to"]:
            h["answers_to_contact_id"] = m["answers_to"][h["contact_id"]]
    for key, flips in m["roles"].items():
        cr.update_role(biz, defs[key]["id"], flips)
    st = next(s for s in db.t["church_role_settings"] if s["business_id"] == biz)
    said = dict(m["settings"])
    if "office_overseer_roles" in said:
        said["office_overseer_roles"] = [defs[k]["id"] for k in said["office_overseer_roles"]]
    st.update(said, map_by=church(db, biz)["owner_id"], map_at="2026-11-03T12:00:00+00:00")


def build(monkeypatch, *, map_on: bool = True, filled: bool = True, migrated: bool = True) -> ThreeDB:
    assert migrated or not filled, "a map needs its tables"
    db = ThreeDB(**{t: [] for t in TABLES}, businesses=[
        {"id": LOVE_CITY, "name": "Love City Church", "type": "ministry", "owner_id": LC_OWNER,
         "settings": {"practitioner_name": "Pastor Kevin", "timezone": "America/Detroit"}},
        {"id": GRACE, "name": "Grace Baptist Church", "type": "ministry", "owner_id": G_OWNER,
         "settings": {"practitioner_name": "Pastor Gray", "timezone": "America/Chicago"}},
        {"id": NEW_HOPE, "name": "New Hope Church", "type": "ministry", "owner_id": NH_OWNER,
         "settings": {"practitioner_name": "Pastor Nathan", "timezone": "America/New_York"}}])
    db.t["intake_forms"] = [_serve(LOVE_CITY, SERVE["fields"][2]["options"]),
                            _serve(GRACE, ["Usher Board", "Youth Ministry", "Kitchen Committee"]),
                            _serve(NEW_HOPE, ["Worship Team", "Youth Volunteers", "Kids Check-in", "Guest Experience",
                                              "Parking Team"])]
    db.who, db.label, db.migrated = {}, {LC_OWNER: "owner", G_OWNER: "owner", NH_OWNER: "owner"}, migrated
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(db, name))
    for k in ("CHURCH_DUTIES", "CHURCH_MONEY_LEVELS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", PLATFORM)
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setenv("CHURCH_MAP", "on" if map_on else "off")
    monkeypatch.setattr(messaging_router, "_owner_email", lambda u: OWNER_EMAIL.get(str(u), ""))
    monkeypatch.setattr(church_checks, "_church_owner_email", lambda u: OWNER_EMAIL.get(str(u), ""))
    # Fresh per-replica caches, put back after the test: this fake's answers
    # never reach the next test file on the same worker.
    for mod, name in ((ca, "_MY_CACHE"), (cd, "_CACHE"), (cd, "_FAILED"), (member_asks, "_OWNER_CACHE"),
                      (church_map, "_READY")):
        monkeypatch.setattr(mod, name, {})
    for b in db.t["businesses"]:
        cr.ensure_library(b)
    intent = {LOVE_CITY: _love_city(db), GRACE: _grace(db), NEW_HOPE: _new_hope(db)}
    db.map_intent = intent if filled else {}
    for biz, m in db.map_intent.items():
        write_map(db, biz, m)
    return db

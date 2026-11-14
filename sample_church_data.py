"""
sample_church_data.py — what Grace Street Fellowship holds (BE-2, 2026-11-15).

The sample church (sample_church.py) is a made-up church of about 190 on a
Sunday that a church looks around before it starts. This module says, as
plain rows, everything in it: people and families, eight Sundays and more of
attendance, kids check-ins, a year of giving by fund, a building campaign
with pledges, nine groups, the serving roster, the calendar, sermons, the
member app's posts and devotional, follow-ups, care, shepherding, the
office's week, Chief's notes, and the website. sample_church_seed writes it.

PURE AND DETERMINISTIC: build(today, tz, business_id, slug) reads no network
and no database (only the two checked-in fixtures in sample_church/). The
same inputs give the same rows, byte for byte; random.Random is seeded with
SEED and with strings (stable in every process; str seeds hash with SHA-512).

RELATIVE TO TODAY: every date is computed from `today` on the church's clock
(`tz`), so the sample always looks current, and every weekday is the real
calendar's: last Sunday is last Sunday.

STABLE WHERE IT MUST BE: a gift is a function of its own calendar date, never
of today, so a weekly refresh only adds the new days' gifts and removes the
ones that passed a year. Re-writing gifts would write the tamper-evident
audit_log (the invoices delete trigger) and the GL queue every week. The
people (contacts) keep their ids; their gifts point at them.

FAKE CONTACT DATA ONLY: every email is @example.org (RFC 2606, no inbox),
every phone is +1<area>555-01NN (the 555-0100..0199 block is reserved for
fiction), every address is on made-up streets in a made-up town with ZIP
00000. Nothing here can reach a real person.

DESIGN FOR EVERY CHURCH CULTURE: names come from many backgrounds and are
handed to roles at random; four story people are fixed (the approved mock):
Denise Carter (greeting team), Luis Moreno (sound booth), Angela Brooks and
Samuel Okafor, who have missed the last three Sundays; Priya Shah and the
Mensah family, first-time guests last Sunday; and Pastor Jordan Daniels.
"""
from __future__ import annotations

import json
import random
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

SEED = 20261115
NAME = "Grace Street Fellowship"
PASTOR_FIRST, PASTOR_LAST = "Jordan", "Daniels"
PASTOR = f"{PASTOR_FIRST} {PASTOR_LAST}"
SOURCE = "sample_church"
TOWN, ZIP = "Riverton", "00000"
CHURCH_ADDRESS = "1400 Grace Street, Riverton 00000"
AREA_CODES = ("312", "404", "214", "615", "919", "503", "602", "704")
FIXTURES = Path(__file__).resolve().parent / "sample_church"
_BASE_NS = uuid.UUID("5a3c2e10-6b1f-4f7e-9b3a-0d6c8e1f2a77")

FUNDS = ("General", "Missions", "Building", "Benevolence")
ROOMS = (("Nursery", 0, 2), ("Preschool", 3, 5), ("Elementary", 6, 11))
CODE_ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"
SUNDAYS_BACK = 16          # Sundays of attendance (the chart shows the last 8; drift reads 11)
GIFT_DAYS = 364            # a year of giving
WEEKS_AHEAD = 4

# The story the approved mock tells (the last eight Sundays, oldest first:
# [in the room, online]); last Sunday is 186, twelve more than the week before.
STORY_SUNDAYS: Tuple[Tuple[int, int], ...] = (
    (142, 30), (150, 31), (146, 33), (139, 35), (155, 32), (148, 30), (141, 33), (152, 34))
# Sunday's serving: team, role id, [(position, needed)], filled per position.
SERVING: Tuple[Tuple[str, str, Tuple[Tuple[str, int, int], ...]], ...] = (
    ("Worship team", "worship", (("Worship leader", 1, 1), ("Vocals", 2, 2), ("Keys", 1, 1), ("Drums", 1, 1))),
    ("Kids rooms", "kids", (("Nursery", 2, 1), ("Preschool", 2, 2), ("Elementary", 2, 1))),
    ("Greeters", "greeters", (("Front door", 2, 2), ("Welcome desk", 1, 1), ("Coffee", 1, 1))),
    ("Sound and slides", "sound", (("Sound", 1, 1), ("Slides", 1, 0), ("Livestream", 1, 1))),
)
KIDS_LAST_SUNDAY = 38

# Tables, in the order they are written (parents first). The seed deletes
# in the reverse order. Every one has a business_id column.
TABLES: Tuple[str, ...] = (
    "custom_modules", "contacts", "households", "household_adults", "household_pickups", "children",
    "child_care_notes", "church_role_settings", "church_role_defs", "church_leader_roles",
    "church_register_entries", "groups", "group_members", "group_meetings", "group_meeting_attendance",
    "serve_teams", "serve_positions", "serve_trained", "worship_songs", "worship_services",
    "serve_assignments", "module_entries", "attendance", "attendance_headcounts",
    "church_checkin_settings", "checkin_stations", "child_checkins", "giving_services", "giving_counts",
    "invoices", "church_campaigns", "church_pledges", "sermon_series", "sermons", "church_posts",
    "devotionals", "church_follow_ups", "church_follow_up_notes", "ministry_care_requests",
    "ministry_care_notes", "church_help_settings", "church_help_requests", "church_help_given",
    "church_shepherd_settings", "church_shepherds", "church_shepherd_touches", "church_shepherd_signals",
    "church_shepherd_notices", "church_boards", "church_board_members", "church_board_meetings",
    "church_board_items", "church_board_attendance", "church_board_decisions", "events", "tasks",
    "chief_notifications", "business_sites",
)
# Every church room and the tables its reads need filled (mapped 2026-11-15
# from the app's reads and the routers behind them). The "empty room" test
# fails on any room this seed leaves empty.
ROOM_TABLES: Dict[str, Tuple[str, ...]] = {
    "Home (stories and what needs you)": ("module_entries", "attendance", "attendance_headcounts", "invoices",
                                          "ministry_care_requests", "chief_notifications", "worship_services",
                                          "church_shepherds", "contacts"),
    "People (the roll)": ("contacts", "households", "household_adults", "children", "church_leader_roles",
                          "church_register_entries", "group_members"),
    "Families": ("households", "household_adults", "children", "household_pickups", "child_care_notes"),
    "Kids check-in": ("church_checkin_settings", "checkin_stations", "child_checkins", "children", "module_entries"),
    "Attendance": ("module_entries", "attendance", "attendance_headcounts"),
    "Giving": ("invoices",),
    "Giving: Sunday counts": ("giving_services", "giving_counts"),
    "Giving: pledges and campaigns": ("church_campaigns", "church_pledges"),
    "Reports": ("invoices", "attendance", "groups", "child_checkins", "church_register_entries", "church_follow_ups"),
    "Groups": ("groups", "group_members", "group_meetings", "group_meeting_attendance"),
    "Services & Events (calendar)": ("custom_modules", "module_entries"),
    "Sunday planning and the serving roster": ("worship_services", "worship_songs", "serve_teams", "serve_positions",
                                               "serve_assignments", "serve_trained"),
    "Sermons": ("sermon_series", "sermons"),
    "Member app: news": ("church_posts",),
    "Member app: devotionals": ("devotionals",),
    "Follow-ups and first-time guests": ("church_follow_ups", "church_follow_up_notes", "events"),
    "Prayer and care": ("ministry_care_requests", "ministry_care_notes"),
    "Benevolence": ("church_help_settings", "church_help_requests", "church_help_given"),
    "Shepherding": ("church_shepherds", "church_shepherd_settings", "church_shepherd_touches",
                    "church_shepherd_signals", "church_role_defs", "church_leader_roles"),
    "Leaders and roles": ("church_role_settings", "church_role_defs", "church_leader_roles"),
    "Office: tasks": ("tasks",),
    "Office: notifications": ("chief_notifications",),
    "Office: the board": ("church_boards", "church_board_members", "church_board_meetings", "church_board_items",
                          "church_board_decisions", "church_board_attendance"),
    "Website": ("business_sites",),
}
# Rooms the sample leaves empty on purpose, and why.
EMPTY_BY_DESIGN: Dict[str, str] = {
    "Messages (member chat)": "msg_* turns members' chat on and pushes; nothing in a sample may message",
    "Church email": "church_mail is real mail with alerts; a sample has no mailbox",
    "Texting": "sms_* sends and bills; never seeded",
    "Recurring gifts": "they live only in Stripe, and a sample has no Stripe account",
    "Funds for the year and the bank": "they hang off real bank (Plaid) transactions",
    "Office logins and areas": "a login is a real person's account (business_users)",
    "Live": "a live stream is a real broadcast",
}
# Kept across a refresh (sample_church_seed): written by id and diffed, never
# wiped, because gifts point at them and a gift delete writes the audit log.
STABLE_TABLES: Tuple[str, ...] = ("contacts", "giving_services", "giving_counts", "invoices")
# The column a bulk insert asks back (tables without an id column).
TABLE_KEYS: Dict[str, str] = {
    "household_adults": "contact_id", "group_members": "contact_id", "group_meeting_attendance": "contact_id",
    "serve_teams": "group_id", "serve_trained": "contact_id", "church_checkin_settings": "business_id",
    "church_role_settings": "business_id", "church_shepherd_settings": "business_id",
    "church_shepherds": "household_id", "church_shepherd_notices": "key", "child_care_notes": "child_id",
    "church_help_settings": "business_id", "church_board_attendance": "member_id",
}


# ─── Dates ────────────────────────────────────────────────────────────

def last_sunday(today: date) -> date:
    """The most recent Sunday before today (a week ago when today is Sunday)."""
    back = (today.weekday() + 1) % 7 or 7
    return today - timedelta(days=back)


def next_sunday(today: date) -> date:
    """The Sunday on or after today: the one the church is getting ready for."""
    return today + timedelta(days=(6 - today.weekday()) % 7)


def week_dates(today: date, weekday: int, back: int, ahead: int) -> List[date]:
    """Every `weekday` (0=Mon) from `back` weeks before to `ahead` weeks after today."""
    first = today + timedelta(days=(weekday - today.weekday()) % 7)
    return [first + timedelta(days=7 * n) for n in range(-back, ahead + 1)]


def load_fixture(name: str) -> Dict[str, Any]:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


# ─── Name pools (many backgrounds; roles are handed out at random) ────

_FEMALE = (
    "Aaliyah", "Abena", "Adaeze", "Adriana", "Aisha", "Alicia", "Amara", "Ana", "Andrea", "Ayesha",
    "Beatriz", "Bianca", "Brenda", "Camila", "Carmen", "Chiamaka", "Claire", "Daniela", "Deborah",
    "Elena", "Esther", "Fatima", "Folake", "Gabriela", "Grace", "Hana", "Ines", "Imani", "Jasmine",
    "Joy", "Keisha", "Lauren", "Leah", "Lucia", "Mai", "Maria", "Marisol", "Meera", "Mercy",
    "Naomi", "Nadia", "Olivia", "Patricia", "Rachel", "Rosa", "Ruth", "Sarah", "Sofia", "Tamara",
    "Teresa", "Vanessa", "Wanjiru", "Yolanda", "Yuna", "Zainab")
_MALE = (
    "Aaron", "Abdiel", "Adrian", "Andre", "Anthony", "Arjun", "Benjamin", "Caleb", "Carlos",
    "Chinedu", "Daniel", "David", "Desmond", "Diego", "Elijah", "Emmanuel", "Eric", "Felipe",
    "Gabriel", "Hiroshi", "Isaac", "Jamal", "James", "Javier", "Jerome", "Joel", "Jonah", "Jorge",
    "Joseph", "Kwame", "Malik", "Marcus", "Mateo", "Michael", "Minh", "Nathan", "Omar",
    "Pablo", "Paul", "Rafael", "Raj", "Reggie", "Ricardo", "Robert", "Ruben", "Simon", "Stephen",
    "Thomas", "Tobi", "Victor", "Wesley", "Xavier", "Yusuf")
_KID_F = ("Ava", "Chloe", "Ella", "Hazel", "Isla", "Kemi", "Layla", "Lily", "Luna", "Maya", "Mia",
          "Nia", "Nora", "Ruby", "Sienna", "Valentina", "Zara", "Zoe", "Aria", "Esme", "Iris", "June",
          "Amani", "Camila", "Eden", "Imani", "Kiara", "Leilani", "Mei", "Nadia", "Penelope", "Sadie")
_KID_M = ("Aiden", "Amir", "Ben", "Eli", "Ethan", "Gabe", "Isaiah", "Jayden", "Kai", "Leo",
          "Liam", "Lucas", "Micah", "Noah", "Owen", "Theo", "Zion", "Rowan", "Felix", "Ezra",
          "Andres", "Caleb", "Dante", "Elias", "Hudson", "Jonah", "Kofi", "Mateo", "Rohan", "Silas")
_SURNAMES = (
    "Adeyemi", "Alvarez", "Asante", "Baker", "Banda", "Bennett", "Boateng", "Castillo", "Chen",
    "Coleman", "Cruz", "Davis", "Diaz", "Edwards", "Ellis", "Evans", "Fernandez", "Foster", "Garcia",
    "Gomez", "Green", "Haddad", "Hall", "Harris", "Hughes", "Ibrahim", "Jackson", "Johnson", "Kaur",
    "Khoury", "Kim", "Kowalski", "Lee", "Lewis", "Lopez", "Martin", "Mendoza", "Mitchell", "Morales",
    "Murphy", "Nakamura", "Nguyen", "Novak", "Nwosu", "O'Neill", "Ortiz", "Osei", "Owens", "Park",
    "Patel", "Perez", "Phillips", "Price", "Ramirez", "Reyes", "Richardson", "Rivera", "Robinson",
    "Rodriguez", "Ross", "Sanchez", "Santos", "Scott", "Silva", "Simmons", "Singh", "Sullivan",
    "Tan", "Taylor", "Thomas", "Thompson", "Torres", "Tran", "Turner", "Vargas", "Walker", "Ward",
    "Watson", "White", "Williams", "Wright", "Young")
_STREETS = ("Maple Avenue", "Juniper Lane", "Cedar Hill Road", "Orchard Street", "Willow Bend",
            "Harbor View Drive", "Larkspur Court", "Aster Way", "Birchwood Lane", "Sycamore Street",
            "Meadow Run", "Chestnut Avenue", "Riverside Drive", "Bluebell Road")


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


# ─── The builder ──────────────────────────────────────────────────────

class _B:
    """One build: the inputs, the id namespace, the clock and the rows."""

    def __init__(self, today: date, tz: str, business_id: str, slug: str):
        self.today, self.tz, self.biz, self.slug = today, tz, str(business_id), slug
        self.zone = ZoneInfo(tz)
        self.ns = uuid.uuid5(_BASE_NS, self.biz)
        self.rows: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TABLES}
        self.last_sun = last_sunday(today)
        self.next_sun = next_sunday(today)
        self.sundays = [self.last_sun - timedelta(days=7 * n) for n in range(SUNDAYS_BACK - 1, -1, -1)]
        self.story: Dict[str, Any] = {}

    def id(self, *parts: Any) -> str:
        return str(uuid.uuid5(self.ns, ":".join(str(p) for p in parts)))

    def at(self, d: date, hh: int, mm: int = 0, ss: int = 0) -> str:
        """A wall-clock time on the church's clock, as UTC ISO."""
        return datetime.combine(d, time(hh, mm, ss), tzinfo=self.zone).astimezone(timezone.utc).isoformat()

    def add(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        if table not in self.rows:
            raise KeyError(table)
        row = {"business_id": self.biz, **row}
        self.rows[table].append(row)
        return row


# ─── People ───────────────────────────────────────────────────────────

class Person(dict):
    """key, first, last, sex, age, kind (adult|teen|child), status, household."""


def _people(b: _B) -> Dict[str, Any]:
    """The church's people and families. Independent of `today` except for
    birth years, so every contact keeps its id and its gifts week to week."""
    rng = random.Random(f"{SEED}:people")
    fem, mal = list(_FEMALE), list(_MALE)
    kf, km = list(_KID_F), list(_KID_M)
    sur = list(_SURNAMES)
    for pool in (fem, mal, kf, km, sur):
        rng.shuffle(pool)
    people: List[Person] = []
    homes: List[Dict[str, Any]] = []

    def person(first, last, sex, age, kind, status="active", **extra) -> Person:
        p = Person(key=f"p{len(people)}", first=first, last=last, sex=sex, age=age, kind=kind,
                   status=status, home=None, **extra)
        people.append(p)
        return p

    def home(name, members, guest=False):
        h = {"key": f"h{len(homes)}", "name": name, "members": members, "guest": guest}
        for m in members:
            m["home"] = h["key"]
        homes.append(h)
        return h

    def kid(last, age, sex=None):
        sex = sex or rng.choice("FM")
        pool = kf if sex == "F" else km
        first = pool.pop() if pool else rng.choice(_KID_F if sex == "F" else _KID_M)
        return person(first, last, sex, age, "child" if age < 13 else "teen")

    # The story's people (the approved mock).
    dj = person(PASTOR_FIRST, PASTOR_LAST, "M", 46, "adult", story="pastor")
    md = person("Michelle", PASTOR_LAST, "F", 44, "adult")
    home(f"The {PASTOR_LAST} family", [dj, md, kid(PASTOR_LAST, 14, "F"), kid(PASTOR_LAST, 9, "M")])
    for first, last, sex, age, story in (("Denise", "Carter", "F", 54, "greeter"),
                                         ("Luis", "Moreno", "M", 34, "sound"),
                                         ("Angela", "Brooks", "F", 67, "member"),
                                         ("Samuel", "Okafor", "M", 41, "member")):
        p = person(first, last, sex, age, "adult", story="drifter", drift_role=story)
        home(f"{first} {last}", [p])
    # Families with children (two parents), single parents, couples, singles.
    for n in range(16):
        last = sur.pop()
        a = person(mal.pop(), last, "M", rng.randint(29, 48), "adult")
        w = person(fem.pop(), last if rng.random() < 0.85 else sur.pop(), "F", max(27, a["age"] + rng.randint(-5, 3)), "adult")
        count = rng.choice((2, 2, 3, 3, 3))
        # The eldest is a teenager in six families: the youth group.
        kids = [kid(last, (rng.randint(13, 17) if n < 6 else rng.randint(0, 12)) if i == 0 else rng.randint(0, 11))
                for i in range(count)]
        home(f"The {last} family", [a, w] + kids)
    for n in range(4):
        last = sur.pop()
        sex = rng.choice("FFFM")
        a = person((fem if sex == "F" else mal).pop(), last, sex, rng.randint(28, 45), "adult")
        home(f"The {last} family", [a] + [kid(last, rng.randint(1, 12)) for _ in range(rng.choice((1, 2, 2)))])
    for n in range(7):
        last = sur.pop()
        age = rng.choice((31, 38, 52, 58, 63, 69, 74, 78))
        a = person(mal.pop(), last, "M", age, "adult")
        w = person(fem.pop(), last, "F", max(25, age + rng.randint(-4, 2)), "adult")
        home(f"The {last} family", [a, w])
    for n in range(8):
        sex = rng.choice("FM")
        last = sur.pop()
        a = person((fem if sex == "F" else mal).pop(), last, sex, rng.choice((23, 26, 29, 35, 47, 61, 72, 84)), "adult")
        home(f"{a['first']} {last}", [a])
    # Two who came as guests this autumn, came back, and joined a group.
    joined = []
    for n in range(2):
        sex = "F" if n == 0 else "M"
        a = person((fem if sex == "F" else mal).pop(), sur.pop(), sex, rng.choice((24, 27, 31)), "adult",
                   guest=f"joined{n}")
        home(f"{a['first']} {a['last']}", [a])
        joined.append(a)
    # Guests: Priya Shah and the Mensah family last Sunday; four more this autumn.
    priya = person("Priya", "Shah", "F", 29, "adult", status="lead", guest="new0")
    kofi = person("Kofi", "Mensah", "M", 38, "adult", status="lead", guest="new1")
    abena = person("Abena", "Mensah", "F", 36, "adult", status="lead")
    mensah_kids = [person("Ama", "Mensah", "F", 6, "child", status="lead"),
                   person("Yaw", "Mensah", "M", 3, "child", status="lead")]
    home("The Mensah family", [kofi, abena] + mensah_kids, guest=True)
    guests = [priya, kofi]
    for n, (age, sex) in enumerate(((33, "M"), (45, "F"), (52, "M"), (27, "F"))):
        g = person((fem if sex == "F" else mal).pop(), sur.pop(), sex, age, "adult", status="lead", guest=f"old{n}")
        guests.append(g)
    return {"people": people, "homes": homes, "pastor": dj, "joined": joined, "guests": guests,
            "mensah_kids": mensah_kids}


def _birthdate(b: _B, p: Person, rng: random.Random) -> str:
    month, day = rng.randint(1, 12), rng.randint(1, 28)
    year = b.today.year - p["age"]
    if (month, day) > (b.today.month, b.today.day):
        year -= 1            # their birthday this year hasn't come yet: still `age`
    return date(year, month, day).isoformat()


def _contacts(b: _B, world: Dict[str, Any]) -> None:
    rng = random.Random(f"{SEED}:contacts")
    homes = {h["key"]: h for h in world["homes"]}
    phone_n = 0
    used_emails: Dict[str, int] = {}
    streets = {}
    for h in world["homes"]:
        streets[h["key"]] = (f"{rng.randint(12, 2890)} {rng.choice(_STREETS)}")
    created_back = random.Random(f"{SEED}:joined")
    for p in world["people"]:
        prng = random.Random(f"{SEED}:person:{p['key']}")
        p["id"] = b.id("contact", p["key"])
        p["birthdate"] = _birthdate(b, p, prng)
        email = phone = None
        if p["kind"] == "adult" or (p["kind"] == "teen" and p["age"] >= 16):
            base = f"{_ascii(p['first'])}.{_ascii(p['last']).replace(chr(39), '')}"
            n = used_emails.get(base, 0)
            used_emails[base] = n + 1
            email = f"{base}{n + 1 if n else ''}@example.org"
            if p["kind"] == "adult" and (prng.random() < 0.93 or p.get("story")):
                phone_n += 1        # 312-555-0100 is the church's own (the website)
                area = AREA_CODES[phone_n // 100 % len(AREA_CODES)]
                phone = f"+1{area}55501{phone_n % 100:02d}"
        p["email"], p["phone"] = email, phone
        # When they first came: years for the church's members, this autumn
        # for its guests (their first visit sets it, below).
        days = created_back.randint(120, 2600) if p["status"] == "active" else 200
        if p.get("story") == "pastor":
            days = 4100          # eleven years at Grace Street
        p["since"] = b.today - timedelta(days=days)
        h = homes.get(p.get("home") or "")
        address = {"line1": streets[h["key"]], "city": TOWN, "state": "", "zip": ZIP} if h else None
        p["address"] = address
    # Children's records share their family's first-came date.
    for h in world["homes"]:
        adults = [m for m in h["members"] if m["kind"] == "adult"]
        for m in h["members"]:
            if m["kind"] != "adult" and adults:
                m["since"] = max(adults[0]["since"], date.fromisoformat(m["birthdate"]))


def _guest_dates(b: _B, world: Dict[str, Any]) -> None:
    """When each guest first came, and the Sundays they came back."""
    s = b.sundays
    plan = {"new0": (-1, []), "new1": (-1, []), "old0": (-2, [-1]), "joined0": (-3, [-2, -1]),
            "joined1": (-5, [-3, -2]), "old1": (-6, []), "old2": (-8, [-7]), "old3": (-11, [])}
    for p in world["people"]:
        g = p.get("guest")
        if g in plan:
            first, back = plan[g]
            p["first_visit"] = s[first]
            p["came_back"] = [s[i] for i in back]
            p["since"] = s[first]
    # The Mensah family came with Kofi.
    for p in world["people"]:
        if p["last"] == "Mensah":
            p["since"] = b.last_sun


def _contact_rows(b: _B, world: Dict[str, Any]) -> None:
    for p in world["people"]:
        created = b.at(p["since"], 12, 0)
        meta: Dict[str, Any] = {"first_name": p["first"], "last_name": p["last"], "sample": True}
        if p["address"]:
            meta["address"] = p["address"]
        health = 25 if p.get("story") == "drifter" else (40 if p["status"] == "lead" else 60 + (len(p["key"]) * 7 + int(p["key"][1:])) % 35)
        b.add("contacts", {
            "id": p["id"], "name": f"{p['first']} {p['last']}", "email": p["email"], "phone": p["phone"],
            "role": None, "status": p["status"], "tags": [], "source": SOURCE,
            "source_detail": "Grace Street Fellowship (a made-up sample church)",
            "metadata": meta, "health_score": health, "lead_score": 0, "birthdate": p["birthdate"],
            "created_at": created, "updated_at": created,
            # Stamped as answered so no "nobody has replied" alert ever counts
            # them (lead_response / notification_engine). Who reached a guest
            # is told by events and texts, not by this.
            "first_response_at": created, "last_interaction": None,
        })


def _families(b: _B, world: Dict[str, Any]) -> None:
    rng = random.Random(f"{SEED}:families")
    pick_rel = ("Grandmother", "Grandfather", "Aunt", "Uncle", "Family friend")
    pickup_n = 0
    for h in world["homes"]:
        hid = b.id("household", h["key"])
        h["id"] = hid
        b.add("households", {"id": hid, "name": h["name"], "created_at": b.at(min(m["since"] for m in h["members"]), 12),
                             "updated_at": b.at(min(m["since"] for m in h["members"]), 12)})
        kids = [m for m in h["members"] if m["kind"] != "adult"]
        for m in h["members"]:
            if m["kind"] == "adult":
                b.add("household_adults", {"household_id": hid, "contact_id": m["id"],
                                           "relationship": "parent" if kids else "other",
                                           "created_at": b.at(m["since"], 12)})
        for m in kids:
            cid = b.id("child", m["key"])
            m["child_id"] = cid
            room = next((r for r, lo, hi in ROOMS if lo <= m["age"] <= hi), "")
            m["room"] = room
            grade = "" if m["age"] < 5 else ("K" if m["age"] == 5 else f"{min(12, m['age'] - 5)}")
            b.add("children", {"id": cid, "household_id": hid, "first_name": m["first"], "last_name": m["last"],
                               "birthdate": m["birthdate"], "grade": grade, "room": room, "active": True,
                               "contact_id": m["id"], "created_at": b.at(m["since"], 12),
                               "updated_at": b.at(m["since"], 12)})
            if m["kind"] == "child" and rng.random() < 0.12:
                b.add("child_care_notes", {"child_id": cid, "allergies": rng.choice(("Peanuts", "Tree nuts", "Dairy", "Bee stings")),
                                           "medical": "", "custody": "", "updated_at": b.at(b.today - timedelta(days=40), 12)})
        if kids and rng.random() < 0.55:
            pickup_n += 1
            sex = rng.choice("FM")
            first = rng.choice(_FEMALE if sex == "F" else _MALE)
            b.add("household_pickups", {"id": b.id("pickup", h["key"]), "household_id": hid,
                                        "name": f"{first} {rng.choice(_SURNAMES)}",
                                        "phone": f"+1{AREA_CODES[(pickup_n + 3) % len(AREA_CODES)]}55501{(60 + pickup_n) % 100:02d}",
                                        "relationship": rng.choice(pick_rel), "created_at": b.at(b.today - timedelta(days=90), 12)})


# ─── Roles (the church's library and who holds what) ──────────────────

def _roles(b: _B, world: Dict[str, Any]) -> Dict[str, List[Person]]:
    import church_roles as cr
    rows = list(cr.TYPES["nondenom"]["rows"])
    stamp = b.at(b.today - timedelta(days=200), 9)
    ids = {r["key"]: b.id("role_def", r["key"]) for r in rows}
    for n, r in enumerate(rows):
        handles = cr._seed_handles(r, [])
        up = None if r["job"] == "senior" else ids.get(r["reports"]) or ids["pastor"]
        b.add("church_role_defs", {
            "id": ids[r["key"]], "key": r["key"], "title": r["title"], "job": r["job"],
            "definition": cr._fill(r["definition"] or cr.JOBS[r["job"]]["definition"], r["title"], NAME, "Intercessor leader"),
            "covers": r["covers"], "reports_to": up, "oversees_teams": [], "handles": handles,
            "sees": cr.clean_sees(r["job"], None), "status": "active", "source": "catalog", "catalog_key": r["key"],
            "sort": n * 10, **cr._catalog_switches(r, handles), "created_at": stamp, "updated_at": stamp,
        })
    b.add("church_role_settings", {
        "church_type": "nondenom", "guessed_type": "nondenom", "guess_reason": "", "set_by": "chief",
        "set_at": stamp, "seeded_at": stamp, "seeded_as": "active", "created_at": stamp, "updated_at": stamp,
    })
    rng = random.Random(f"{SEED}:roles")
    adults = [p for p in world["people"] if p["kind"] == "adult" and p["status"] == "active"
              and not p.get("story") and not p.get("guest")]
    rng.shuffle(adults)
    holders: Dict[str, List[Person]] = {"pastor": [world["pastor"]]}
    plan = (("associate_pastor", 1), ("elders", 3), ("deacons", 5), ("worship_leader", 1), ("youth_pastor", 1),
            ("childrens_director", 1), ("welcome_lead", 1), ("team_leader", 2), ("care_team", 2),
            ("intercessor_leader", 1), ("class_teachers", 1), ("administrator", 1), ("treasurer", 1))
    for key, n in plan:
        holders[key] = [adults.pop() for _ in range(n)]
    for key, ps in holders.items():
        for p in ps:
            p.setdefault("roles", []).append(key)
            b.add("church_leader_roles", {
                "id": b.id("holds", key, p["key"]), "contact_id": p["id"], "role": key, "scope": "",
                "status": "active", "invited_at": stamp, "answered_at": stamp, "created_at": stamp,
                "updated_at": stamp, "term_ends_at": None, "term_told_at": None,
            })
    return holders


# ─── Groups, serving teams ────────────────────────────────────────────

GROUPS = (
    # name, kind, description, meet_day (0=Mon), meet_time, every, location, youth, size
    ("Young Adults", "small_group", "Twenties and thirties: dinner, the week's sermon, and real life.", 3, "19:30", 1, "The Okoro-Lee home", False, 11),
    ("Comunidad en Español", "small_group", "Estudio bíblico y oración en español. Everyone is welcome.", 1, "19:00", 1, "Room 204", False, 9),
    ("Parents of Little Ones", "small_group", "For parents of babies to five-year-olds. Childcare in the nursery.", 5, "10:00", 2, "Fellowship hall", False, 10),
    ("Golden Years", "ministry", "Seniors' fellowship: lunch, hymns and a short study.", 2, "11:00", 1, "Fellowship hall", False, 9),
    ("Youth", "ministry", "Grades 6 to 12. Fridays at 7, games, worship and small groups.", None, None, 1, "Youth room", True, 12),
    ("Men's Breakfast", "small_group", "Every other Saturday, breakfast and a chapter of Proverbs.", 5, "08:00", 2, "Fellowship hall", False, 10),
    ("Women's Bible Study", "small_group", "Monday nights, working through a book of the Bible together.", 0, "19:00", 1, "Room 201", False, 12),
    ("Prayer Team", "ministry", "Praying for the church's requests, Sunday mornings before the first service.", 6, "08:15", 1, "Prayer room", False, 8),
    ("Wednesday Bible Study", "class", "Midweek teaching and discussion. Wednesdays at 7 in the fellowship hall.", None, None, 1, "Fellowship hall", False, 16),
)


def _groups(b: _B, world: Dict[str, Any], holders: Dict[str, List[Person]]) -> None:
    rng = random.Random(f"{SEED}:groups")
    people = world["people"]
    members = [p for p in people if p["status"] == "active" and p["kind"] == "adult" and p.get("story") != "drifter"]
    teens = [p for p in people if p["kind"] == "teen" and p["status"] == "active"]
    seniors = [p for p in members if p["age"] >= 58]
    parents = [p for p in members if any(m["kind"] == "child" and m["age"] <= 5
                                          for h in world["homes"] if h["key"] == p["home"] for m in h["members"])]
    young = [p for p in members if p["age"] <= 35]
    joined = world["joined"]
    made_on = b.today - timedelta(days=700)
    b.story["groups"] = []
    for gi, (name, kind, desc, day, clock, every, place, youth, size) in enumerate(GROUPS):
        gid = b.id("group", name)
        if name == "Young Adults":
            pool = young
        elif name == "Golden Years":
            pool = seniors
        elif name == "Parents of Little Ones":
            pool = parents
        elif name == "Youth":
            pool = teens
        elif name == "Men's Breakfast":
            pool = [p for p in members if p["sex"] == "M"]
        elif name == "Women's Bible Study":
            pool = [p for p in members if p["sex"] == "F"]
        else:
            pool = members
        grng = random.Random(f"{SEED}:group:{name}")
        chosen = sorted(pool, key=lambda p: p["key"])
        grng.shuffle(chosen)
        chosen = chosen[:size]
        if name == "Young Adults":
            chosen = [p for p in chosen if p not in joined][: size - 1] + [joined[0]]
        if name == "Women's Bible Study" and joined[1]["sex"] == "F" or name == "Men's Breakfast" and joined[1]["sex"] == "M":
            chosen = [p for p in chosen if p is not joined[1]][: size - 1] + [joined[1]]
        elif name not in ("Young Adults",):
            chosen = [p for p in chosen if p not in joined]
        if name == "Youth":
            leads = holders["youth_pastor"] + [p for p in members if p not in holders["youth_pastor"]][:1]
            chosen = chosen + leads
        leader = holders["youth_pastor"][0] if name == "Youth" else chosen[0]
        b.add("groups", {
            "id": gid, "name": name, "kind": kind, "description": desc,
            "meets": {None: "Fridays at 7 PM" if name == "Youth" else "Wednesdays at 7 PM"}.get(day, ""),
            "location": place, "capacity": None, "open_to_join": True, "active": True, "youth": youth,
            "join_mode": "ask", "name_display": "full", "chat_on": False, "chat_writers": "all",
            "meet_day": day, "meet_time": clock, "meet_address": "", "meet_note": "", "meet_skips": [],
            "study_on": False, "meet_every": every, "meet_from": (b.today - timedelta(days=364)).isoformat() if day is not None else None,
            "meet_nth": None, "chat_extras": True, "created_at": b.at(made_on, 10), "updated_at": b.at(made_on, 10),
        })
        roster = []
        for p in chosen:
            joined_on = (p["first_visit"] + timedelta(days=7)) if p.get("guest") else (made_on + timedelta(days=grng.randint(0, 300)))
            roster.append((p, joined_on))
            b.add("group_members", {"group_id": gid, "contact_id": p["id"],
                                    "role": "leader" if p is leader else "member",
                                    "joined_on": joined_on.isoformat(), "can_host_live": False,
                                    "created_at": b.at(joined_on, 12)})
        # Meetings: the last eight times it met (weekly or every other week).
        meet_wd = day if day is not None else (4 if name == "Youth" else 2)
        dates = [d for d in week_dates(b.today, meet_wd, 16, 0) if d < b.today]
        dates = dates[::-1][::every][:8][::-1]
        for mi, d in enumerate(dates):
            mid = b.id("meeting", name, d.isoformat())
            here = [p for p, j in roster if j <= d and grng.random() < 0.78]
            b.add("group_meetings", {"id": mid, "group_id": gid, "met_on": d.isoformat(),
                                     "visitors": grng.choice((0, 0, 0, 1, 2)), "notes": "",
                                     "created_at": b.at(d, 21), "updated_at": b.at(d, 21)})
            last3 = mi >= len(dates) - 3
            for p, j in roster:
                came = p in here
                # Nobody here has drifted from their group: each member came
                # to at least one of its last three meetings.
                if last3 and mi == len(dates) - 1 and not came and not any(
                        r["contact_id"] == p["id"] and r["meeting_id"] in {b.id("meeting", name, x.isoformat()) for x in dates[-3:-1]}
                        for r in b.rows["group_meeting_attendance"]):
                    came = j <= d
                if came:
                    b.add("group_meeting_attendance", {"meeting_id": mid, "contact_id": p["id"], "how": "office"})
        b.story["groups"].append({"name": name, "members": len(roster), "leader": f"{leader['first']} {leader['last']}",
                                  "kind": kind})


def _serving(b: _B, world: Dict[str, Any], holders: Dict[str, List[Person]]) -> Dict[str, Any]:
    """The four Sunday teams (groups of kind team), their positions, who is
    trained, and who serves where."""
    rng = random.Random(f"{SEED}:serving")
    people = world["people"]
    by_story = {p.get("drift_role"): p for p in people if p.get("story") == "drifter"}
    leads = {id(x) for k in ("worship_leader", "childrens_director", "welcome_lead", "team_leader", "pastor")
             for x in holders[k]}
    pool = [p for p in people if p["status"] == "active" and p["kind"] == "adult" and not p.get("story")
            and id(p) not in leads]
    pool.sort(key=lambda p: p["key"])
    rng.shuffle(pool)
    teams = []
    made_on = b.today - timedelta(days=600)
    for ti, (team, role_id, positions) in enumerate(SERVING):
        gid = b.id("team", team)
        lead = {"Worship team": holders["worship_leader"], "Kids rooms": holders["childrens_director"],
                "Greeters": holders["welcome_lead"]}.get(team, holders["team_leader"][:1])[0]
        crew = [lead] + [pool.pop() for _ in range(sum(n for _, n, _ in positions) + 2)]
        if team == "Greeters":
            crew.append(by_story["greeter"])
        if team == "Sound and slides":
            crew.append(by_story["sound"])
        b.add("groups", {
            "id": gid, "name": team, "kind": "team", "description": "", "meets": "", "location": "",
            "capacity": None, "open_to_join": True, "active": True, "youth": False, "join_mode": "ask",
            "name_display": "full", "chat_on": False, "chat_writers": "all", "meet_day": None, "meet_time": None,
            "meet_address": "", "meet_note": "", "meet_skips": [], "study_on": False, "meet_every": 1,
            "meet_from": None, "meet_nth": None, "chat_extras": True,
            "created_at": b.at(made_on, 10), "updated_at": b.at(made_on, 10)})
        b.add("serve_teams", {"group_id": gid, "call_time": "08:15" if ti in (0, 3) else "08:40", "max_month": 2,
                              "swap_needs_ok": False, "families": True, "sort": ti, "owner": "churchsavvy",
                              "created_at": b.at(made_on, 10), "updated_at": b.at(made_on, 10)})
        for p in crew:
            b.add("group_members", {"group_id": gid, "contact_id": p["id"], "role": "leader" if p is lead else "member",
                                    "joined_on": (made_on + timedelta(days=rng.randint(0, 200))).isoformat(),
                                    "can_host_live": False, "created_at": b.at(made_on, 12)})
        pos_rows = []
        for pi, (pname, needed, filled) in enumerate(positions):
            pid = b.id("position", team, pname)
            b.add("serve_positions", {"id": pid, "group_id": gid, "name": pname, "needed": needed, "note": "",
                                      "sort": pi, "active": True, "created_at": b.at(made_on, 10)})
            pos_rows.append((pid, pname, needed, filled))
        for p in crew:
            for pid, pname, needed, filled in pos_rows:
                if p is lead or rng.random() < 0.45 or (p.get("drift_role") == "sound" and pname == "Sound"):
                    b.add("serve_trained", {"position_id": pid, "contact_id": p["id"], "level": "trained",
                                            "created_at": b.at(made_on, 12)})
        teams.append({"team": team, "role_id": role_id, "group_id": gid, "lead": lead, "crew": crew,
                      "positions": pos_rows})
    return {"teams": teams}


# ─── The calendar: Services & Events ──────────────────────────────────

def _modules(b: _B) -> Dict[str, str]:
    fx = load_fixture("modules.json")["modules"]
    out = {}
    stamp = b.at(b.today - timedelta(days=720), 9)
    for m in fx:
        mid = b.id("module", m["module_slug"])
        params = dict(m.get("archetype_params") or {})
        if m.get("archetype") == "event_roster":
            params.update({"title_field": "title", "date_field": "date", "location_field": "location",
                           "capacity_field": "capacity", "signups_field": "signups",
                           "roles": [{"id": rid, "label": team, "needed": sum(n for _, n, _ in pos)}
                                     for team, rid, pos in SERVING]})
        b.add("custom_modules", {
            "id": mid, "name": m["module_name"], "slug": m["module_slug"], "description": m.get("description") or "",
            "icon": m.get("icon") or "", "schema": m.get("schema") or {"fields": []},
            "agent_config": m.get("agent_config") or {"enabled": True, "triggers": []},
            "is_active": True, "sort_order": m.get("sort_order") or 0,
            "archetype": m.get("archetype") or "fallback_generic", "archetype_params": params,
            "public_display": m.get("public_display") or {}, "presentation": {},
            "created_at": stamp, "updated_at": stamp,
        })
        out[m["module_slug"]] = mid
    return out


# Weekday events: (weekday 0=Mon, clock, title, type, location, signups)
WEEK_EVENTS = (
    (1, "19:00", "Deacons", "event", "Room 201", 6),
    (2, "19:00", "Bible study", "class", "Fellowship hall", 24),
    (3, "18:30", "Worship rehearsal", "event", "Sanctuary", 8),
    (4, "19:00", "Youth night", "event", "Youth room", 16),
    (5, "09:00", "Food pantry", "event", "Fellowship hall", 12),
)


def _signups(people: List[Person], n: int, role: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    for p in people[:n]:
        s = {"contact_id": p["id"], "name": f"{p['first']} {p['last']}", "status": "yes"}
        if role:
            s["role"] = role
        out.append(s)
    return out


def _calendar(b: _B, world: Dict[str, Any], mods: Dict[str, str], holders, serving) -> Dict[str, Any]:
    rng = random.Random(f"{SEED}:calendar")
    mod = mods["services-events"]
    created = b.at(b.today - timedelta(days=1), 6)
    sundays: Dict[date, str] = {}
    people = world["people"]
    adults = sorted([p for p in people if p["kind"] == "adult" and p["status"] == "active"
                     and p.get("story") != "drifter"], key=lambda p: p["key"])
    future = [b.next_sun + timedelta(days=7 * n) for n in range(WEEKS_AHEAD)]
    for d in b.sundays + [x for x in future if x not in b.sundays]:
        eid = b.id("occasion", d.isoformat())
        sundays[d] = eid
        signups: List[Dict[str, Any]] = []
        for t in serving["teams"]:
            crew = [p for p in t["crew"] if p.get("story") != "drifter"]
            trng = random.Random(f"{SEED}:roster:{t['team']}:{d.isoformat()}")
            trng.shuffle(crew)
            # Each place filled names one person, by position, as the roster does.
            for pid, pname, needed, filled in t["positions"]:
                take = filled if d == b.next_sun else needed
                signups += _signups(crew[:take], take, t["role_id"])
                crew = crew[take:]
        b.add("module_entries", {
            "id": eid, "module_id": mod, "status": "active", "created_by": SOURCE, "source": SOURCE,
            "data": {"title": "Sunday Worship", "type": "service", "date": f"{d.isoformat()}T11:00",
                     "location": "Sanctuary and online", "signups": signups, "_visibility": "public",
                     "_checkin_day": d.isoformat(),
                     "notes": "Two services, 9:00 and 11:00. The 11:00 is streamed."},
            "created_at": created, "updated_at": created,
        })
    # The week's other gatherings, two weeks back to four ahead.
    youth = [p for p in people if p["kind"] == "teen"] + holders["youth_pastor"]
    deacons = holders["deacons"] + holders["pastor"]
    worship_team = next(t for t in serving["teams"] if t["team"] == "Worship team")["crew"]
    week = []
    for wd, clock, title, kind, place, n in WEEK_EVENTS:
        for d in week_dates(b.today, wd, 2, WEEKS_AHEAD):
            who = {"Deacons": deacons, "Youth night": youth, "Worship rehearsal": worship_team}.get(title, adults)
            who = sorted(who, key=lambda p: p["key"])
            random.Random(f"{SEED}:who:{title}:{d.isoformat()}").shuffle(who)
            eid = b.id("event", title, d.isoformat())
            b.add("module_entries", {
                "id": eid, "module_id": mod, "status": "active", "created_by": SOURCE, "source": SOURCE,
                "data": {"title": title, "type": kind, "date": f"{d.isoformat()}T{clock}", "location": place,
                         "signups": _signups(who, n), "_visibility": "private" if title == "Deacons" else "public",
                         "_roles": [], "notes": ""},
                "created_at": created, "updated_at": created,
            })
            if b.today <= d < b.today + timedelta(days=7):
                week.append({"date": d.isoformat(), "time": clock, "title": title, "coming": min(n, len(who))})
    # A baptism Sunday on the calendar, three weeks out.
    bd = b.next_sun + timedelta(days=21)
    b.add("module_entries", {
        "id": b.id("event", "Baptism Sunday", bd.isoformat()), "module_id": mod, "status": "active",
        "created_by": SOURCE, "source": SOURCE,
        "data": {"title": "Baptism Sunday", "type": "special", "date": f"{bd.isoformat()}T12:30",
                 "location": "Sanctuary", "signups": [], "_visibility": "public", "_roles": [],
                 "notes": "After the 11:00 service. Lunch in the fellowship hall."},
        "created_at": created, "updated_at": created})
    b.story["week"] = sorted(week, key=lambda w: (w["date"], w["time"]))
    return {"sundays": sundays}


# ─── Sundays: attendance and kids ─────────────────────────────────────

def _attendance(b: _B, world: Dict[str, Any], cal: Dict[str, Any]) -> None:
    people = world["people"]
    sundays = b.sundays
    occ = cal["sundays"]
    n = len(sundays)
    regulars = [p for p in people if p["status"] == "active" and p["kind"] in ("adult", "teen")
                and not p.get("guest")]
    came: Dict[str, List[date]] = {}
    for p in sorted(regulars, key=lambda p: p["key"]):
        prng = random.Random(f"{SEED}:attend:{p['key']}")
        rate = prng.uniform(0.55, 0.95)
        days = [d for d in sundays if random.Random(f"{SEED}:att:{p['key']}:{d.isoformat()}").random() < rate]
        if p.get("story") == "drifter":
            gone = 3 if p["drift_role"] in ("greeter", "sound") else 4   # last here 3 or 4 Sundays back
            stop = sundays[n - 1 - gone]
            days = [d for d in days if d < stop] + [stop]
            # at least three of the eight before the last three
            window = sundays[n - 11:n - 3]
            for d in window:
                if sum(1 for x in days if x in window) >= 4:
                    break
                if d < stop and d not in days:
                    days.append(d)
            days = sorted(set(d for d in days if d <= stop))
        else:
            if not any(d in days for d in sundays[-3:]):
                days.append(sundays[-1 - prng.randint(0, 2)])
            days = sorted(set(days))
        came[p["key"]] = days
    # Guests: their first visit, and the Sundays they came back.
    for p in people:
        if p.get("first_visit"):
            came[p["key"]] = sorted({p["first_visit"], *p["came_back"]})
    world["came"] = came
    by_day: Dict[date, List[Tuple[Person, bool]]] = {d: [] for d in sundays}
    for p in people:
        for d in came.get(p["key"], []):
            if d in by_day:
                by_day[d].append((p, d == p.get("first_visit")))
    methods = ("station", "station", "station", "self", "self", "staff", "online")
    first_named = {}
    for i, d in enumerate(sundays):
        eid = occ[d]
        rows = sorted(by_day[d], key=lambda x: x[0]["key"])
        online_named = 0
        for p, first in rows:
            r = random.Random(f"{SEED}:how:{p['key']}:{d.isoformat()}")
            method = "station" if first else r.choice(methods)
            if method == "online":
                online_named += 1
            service = 9 if r.random() < 0.4 else 11
            b.add("attendance", {
                "id": b.id("attendance", p["key"], d.isoformat()), "entry_id": eid, "contact_id": p["id"],
                "name": f"{p['first']} {p['last']}", "first_time": bool(first), "method": method,
                "checked_in_at": b.at(d, service - 1, 40 + r.randint(0, 19)), "created_at": b.at(d, 13)})
        # Headcounts: the story's eight Sundays, and plausible ones before them.
        k = i - (n - len(STORY_SUNDAYS))
        if k >= 0:
            room, online = STORY_SUNDAYS[k]
        else:
            hr = random.Random(f"{SEED}:heads:{d.isoformat()}")
            room, online = hr.randint(134, 156), hr.randint(27, 35)
        named_room = sum(1 for p, _ in rows) - online_named
        room = max(room, named_room)
        early = round(room * 0.42)
        for area, count in (("9:00 service", early), ("11:00 service", room - early), ("Online", max(online, online_named))):
            b.add("attendance_headcounts", {"id": b.id("headcount", d.isoformat(), area), "entry_id": eid,
                                            "area": area, "count": count, "counted_by": None,
                                            "updated_at": b.at(d, 12, 30)})
        first_named[d] = sum(1 for _, f in rows if f)
    last = sundays[-1]
    room, online = STORY_SUNDAYS[-1]
    prev = STORY_SUNDAYS[-2]
    b.story["last_sunday"] = {"date": last.isoformat(), "total": room + online, "in_room": room, "online": online,
                              "first_time": first_named[last], "change": (room + online) - sum(prev)}
    b.story["eight_sundays"] = [{"date": d.isoformat(), "in_room": r, "online": o}
                                for d, (r, o) in zip(sundays[-8:], STORY_SUNDAYS)]


def _kids(b: _B, world: Dict[str, Any], cal: Dict[str, Any]) -> None:
    """Kids check-in: the last eight Sundays, last Sunday's 38 in the three rooms."""
    homes = {h["key"]: h for h in world["homes"]}
    kids = sorted([p for p in world["people"] if p["kind"] == "child" and p.get("room")], key=lambda p: p["key"])
    came = world["came"]
    b.add("church_checkin_settings", {"enabled": True, "weekday": 6, "start_time": "09:00", "timezone": b.tz,
                                      "opens_before_min": 30, "closes_after_min": 240, "title": "Sunday Worship",
                                      "updated_by": None, "updated_at": b.at(b.today - timedelta(days=300), 9)})
    stations = []
    for name, mode in (("Kids desk", "staff"), ("Lobby kiosk", "self")):
        sid = b.id("station", name)
        stations.append(sid)
        b.add("checkin_stations", {"id": sid, "name": name, "mode": mode,
                                   # Never a real PIN: a sample's station can't be paired or opened.
                                   "pin_hash": "sample-church:no-pin", "token_hash": None, "pair_code_hash": None,
                                   "created_at": b.at(b.today - timedelta(days=300), 9), "paired_at": None,
                                   "last_seen_at": None, "revoked_at": None})
    last = b.last_sun
    # Last Sunday: 38 children, each with a parent there in person.
    # The Mensah children came with their parents; the rest by lot.
    order = sorted(kids, key=lambda p: (p["last"] != "Mensah", random.Random(f"{SEED}:kid:{p['key']}").random()))
    here_last = order[:KIDS_LAST_SUNDAY]
    for d in b.sundays[-8:]:
        eid = cal["sundays"][d]
        if d == last:
            present = here_last
        else:
            present = [p for p in kids if random.Random(f"{SEED}:kidday:{p['key']}:{d.isoformat()}").random() < 0.82
                       and not (p["last"] == "Mensah")]
        codes: Dict[str, str] = {}
        for p in present:
            h = homes[p["home"]]
            if h["key"] not in codes:
                cr = random.Random(f"{SEED}:code:{h['key']}:{d.isoformat()}")
                codes[h["key"]] = "".join(cr.choice(CODE_ALPHABET) for _ in range(4))
            adults = [m for m in h["members"] if m["kind"] == "adult"]
            parent = next((m for m in adults if d in came.get(m["key"], [])), adults[0])
            # Whoever dropped them off was there: make sure the record says so.
            if d not in came.setdefault(parent["key"], []):
                came[parent["key"]] = sorted(came[parent["key"]] + [d])
            r = random.Random(f"{SEED}:kidrow:{p['key']}:{d.isoformat()}")
            age = p["age"] - (1 if d < b.today - timedelta(days=200) else 0)
            room = next((rm for rm, lo, hi in ROOMS if lo <= age <= hi), p["room"])
            inn = b.at(d, 8, 45 + r.randint(0, 14)) if r.random() < 0.45 else b.at(d, 10, 45 + r.randint(0, 14))
            out_at = (datetime.fromisoformat(inn) + timedelta(minutes=95 + r.randint(0, 20))).isoformat()
            b.add("child_checkins", {
                "id": b.id("kidcheck", p["key"], d.isoformat()), "entry_id": eid, "child_id": p["child_id"],
                "household_id": h["id"], "room": room, "code": codes[h["key"]], "dropped_off_by": parent["id"],
                "method": "station" if r.random() < 0.6 else "staff", "checked_in_at": inn,
                "checked_in_by": None, "checked_out_at": out_at, "checked_out_by": None,
                "released_to": f"{parent['first']} {parent['last']}",
                "station_id": stations[0] if r.random() < 0.5 else stations[1], "released_by_contact": None})
    rooms: Dict[str, int] = {}
    for p in here_last:
        rooms[p["room"]] = rooms.get(p["room"], 0) + 1
    b.story["kids_last_sunday"] = {"total": len(here_last), "rooms": dict(sorted(rooms.items()))}


def _attendance_parents_fix(b: _B, world: Dict[str, Any], cal: Dict[str, Any]) -> None:
    """Kids' parents were there in person: add their check-ins when the
    drawing above didn't (never for anyone who has drifted)."""
    have = {(r["contact_id"], r["entry_id"]) for r in b.rows["attendance"]}
    by_key = {p["key"]: p for p in world["people"]}
    rev = {v: k for k, v in cal["sundays"].items()}
    for row in b.rows["child_checkins"]:
        cid, eid = row["dropped_off_by"], row["entry_id"]
        if (cid, eid) in have:
            continue
        p = next(x for x in by_key.values() if x["id"] == cid)
        if p.get("story") == "drifter":
            continue
        d = rev[eid]
        r = random.Random(f"{SEED}:parentfix:{p['key']}:{d.isoformat()}")
        b.add("attendance", {"id": b.id("attendance", p["key"], d.isoformat()), "entry_id": eid,
                             "contact_id": cid, "name": f"{p['first']} {p['last']}", "first_time": False,
                             "method": "kids_parent", "checked_in_at": row["checked_in_at"], "created_at": b.at(d, 13)})
        have.add((cid, eid))
        del r


# ─── Giving ───────────────────────────────────────────────────────────

def _givers(world: Dict[str, Any]) -> List[Dict[str, Any]]:
    """55 givers, each with a stable habit: how often, how, how much, to what."""
    rng = random.Random(f"{SEED}:givers")
    adults = sorted([p for p in world["people"] if p["kind"] == "adult" and p["status"] == "active"
                     and not p.get("guest")], key=lambda p: p["key"])
    rng.shuffle(adults)
    chosen = adults[:55]
    amounts = (50, 80, 100, 120, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 1500)
    weights = (6, 6, 10, 8, 10, 10, 9, 8, 7, 6, 4, 3, 2, 1)
    givers = []
    for p in sorted(chosen, key=lambda p: p["key"]):
        g = random.Random(f"{SEED}:giver:{p['key']}")
        givers.append({
            "p": p, "monthly": g.choices(amounts, weights)[0],
            "cadence": g.choices(("weekly", "biweekly", "monthly", "sometimes"), (40, 15, 30, 15))[0],
            "how": g.choices(("online", "check", "cash"), (45, 32, 23))[0],
            "missions": g.choice((0, 0, 0, 25, 40, 50, 100)) if g.random() < 0.32 else 0,
            "benevolence": g.choice((10, 20, 25, 40)) if g.random() < 0.12 else 0,
            "parity": g.randint(0, 1), "day": g.choice((1, 15)),
        })
    total = sum(x["monthly"] for x in givers)
    for x in givers:   # the general fund, about $19,500 a month promised across them
        x["monthly"] = max(25, int(round(x["monthly"] * 19500 / total / 5.0)) * 5)
    return givers


PLEDGERS = 18


def _giving(b: _B, world: Dict[str, Any]) -> None:
    givers = _givers(world)
    world["givers"] = givers
    pledgers = givers[:PLEDGERS]
    for i, g in enumerate(pledgers):
        g["pledge_month"] = int(random.Random(f"{SEED}:pledge:{g['p']['key']}").choice((50, 75, 100, 150, 200, 250, 300, 400)))
    services = []
    svc_made = b.at(b.today - timedelta(days=420), 9)
    for key, name, clock in (("s9", "9:00 service", "09:00"), ("s11", "11:00 service", "11:00")):
        sid = b.id("giving_service", key)
        services.append((key, sid, name, clock))
        b.add("giving_services", {"id": sid, "name": name, "kind": "weekly", "weekday": 6, "on_date": None,
                                  "start_time": clock, "collects_online": False, "archived_at": None,
                                  "created_at": svc_made, "updated_at": svc_made})
    start = b.today - timedelta(days=GIFT_DAYS)
    counters_pool = sorted([p for p in world["people"] if p["kind"] == "adult" and p["status"] == "active"
                            and p.get("story") != "drifter"], key=lambda p: p["key"])
    d = start
    month_totals: Dict[str, float] = {}
    while d < b.today:
        _gifts_on(b, d, givers, services, counters_pool, month_totals)
        d += timedelta(days=1)
    # Today, when it is Sunday: the counts are open and nothing is in them yet.
    if b.today.weekday() == 6:
        for key, sid, name, clock in services:
            b.add("giving_counts", _count_row(b, b.today, key, sid, name, clock, 0, 0, [], "open"))
    this_month = b.today.strftime("%Y-%m")
    prev_month = (b.today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    by_fund: Dict[str, float] = {f: 0.0 for f in FUNDS}
    n_this = 0
    for r in b.rows["invoices"]:
        if r["paid_at"][:7] == this_month:
            by_fund[r["gift_fund"]] += r["total"]
            n_this += 1
    b.story["giving"] = {"this_month": round(sum(by_fund.values()), 2), "gifts_this_month": n_this,
                         "by_fund": {k: round(v, 2) for k, v in by_fund.items()},
                         "last_month": round(month_totals.get(prev_month, 0.0), 2),
                         "monthly_average": round(sum(month_totals.values()) / max(1, len(month_totals)), 2),
                         "givers": len(givers), "gifts": len(b.rows["invoices"])}
    _campaign(b, pledgers)


def _count_row(b, d, key, sid, name, clock, cash, checks, counters, status="closed"):
    hh, mm = int(clock[:2]), int(clock[3:])
    return {"id": b.id("count", key, d.isoformat()), "service_id": sid, "name": name,
            "service_date": d.isoformat(), "starts_at": b.at(d, hh, mm), "collects_online": False,
            "status": status, "counted_cash_cents": cash if status == "closed" else None,
            "counted_checks_cents": checks if status == "closed" else None,
            "counters": counters, "closed_at": b.at(d, 13, 30) if status == "closed" else None,
            "closed_by": None, "note": "",
            "created_at": b.at(d, hh, mm), "updated_at": b.at(d, 13, 30)}


def _gift(b: _B, d: date, slot: str, contact: Optional[Person], amount: float, fund: str, method: str,
          count_id: Optional[str], hh: int, mm: int, note: str = "") -> None:
    paid = b.at(d, hh, mm)
    designated = fund != "General"
    label = "General Fund" if fund == "General" else f"{fund} Fund"
    online = method == "stripe"
    content = f"{d.isoformat()}|{slot}|{contact['key'] if contact else '-'}|{amount:.2f}|{fund}|{method}"
    gid = b.id("gift", content)
    number = (f"GIVE-web-{gid[:8]}{gid[9:13]}" if online else f"GIVE-manual-{gid}")
    b.add("invoices", {
        "id": gid, "contact_id": contact["id"] if contact else None, "invoice_number": number,
        "status": "paid", "is_gift": True, "gift_fund": fund, "category": "restricted" if designated else None,
        "payment_method": method,
        "items": [{"description": f"Gift — {label}", "quantity": 1, "unit_price": amount, "total": amount}],
        "subtotal": amount, "tax_rate": 0, "tax_amount": 0, "total": amount, "currency": "USD",
        "due_date": d.isoformat(), "paid_at": paid, "sent_at": paid, "notes": note,
        "giving_count_id": count_id, "created_at": paid, "updated_at": paid,
    })


def _gifts_on(b: _B, d: date, givers, services, counters_pool, month_totals) -> None:
    """One day's gifts: a pure function of the day (and the givers), never of today."""
    day = d.isoformat()
    sunday = d.weekday() == 6
    first_sunday = sunday and d.day <= 7
    week = d.toordinal() // 7
    tally = {key: [0, 0] for key, _, _, _ in services}   # cash, checks (cents) per service
    def svc(r):
        return services[0] if r.random() < 0.4 else services[1]
    before = len(b.rows["invoices"])
    for g in givers:
        p = g["p"]
        r = random.Random(f"{SEED}:g:{p['key']}:{day}")
        cad, how = g["cadence"], g["how"]
        gives = False
        per = g["monthly"]
        if cad == "weekly":
            gives = sunday and r.random() < 0.86
            per = g["monthly"] / 4.33
        elif cad == "biweekly":
            gives = sunday and week % 2 == g["parity"] and r.random() < 0.92
            per = g["monthly"] / 2.17
        elif cad == "monthly":
            gives = (d.day == g["day"]) if how == "online" else first_sunday
        else:
            gives = sunday and r.random() < 0.23
            per = g["monthly"] / 1.0
        if gives:
            amount = max(10.0, round(per * r.uniform(0.9, 1.1) / 5.0) * 5.0)
            _one(b, d, g, "general", amount, "General", r, services, tally, svc)
        if g.get("pledge_month") and ((how == "online" and d.day == 1) or (how != "online" and first_sunday)):
            _one(b, d, g, "pledge", float(g["pledge_month"]), "Building", r, services, tally, svc)
        mday, mweek = (1, (1, 7)) if g["parity"] == 0 else (15, (15, 21))
        if g["missions"] and ((how == "online" and d.day == mday) or
                              (how != "online" and sunday and mweek[0] <= d.day <= mweek[1])):
            _one(b, d, g, "missions", float(g["missions"]), "Missions", r, services, tally, svc)
        if g["benevolence"] and first_sunday:
            _one(b, d, g, "benevolence", float(g["benevolence"]), "Benevolence", r, services, tally, svc)
    if sunday:
        lr = random.Random(f"{SEED}:loose:{day}")
        for key, sid, name, clock in services:
            amount = float(lr.randint(60, 190))
            cid = b.id("count", key, day)
            _gift(b, d, f"loose-{key}", None, amount, "General", "cash", cid,
                  int(clock[:2]) + 1, 15, "Loose offering")
            tally[key][0] += int(amount * 100)
            if first_sunday:
                bamount = float(lr.randint(140, 290))
                _gift(b, d, f"benevolence-{key}", None, bamount, "Benevolence", "cash", cid,
                      int(clock[:2]) + 1, 20, "Loose offering · benevolence plate")
                tally[key][0] += int(bamount * 100)
        cr = random.Random(f"{SEED}:counters:{day}")
        for key, sid, name, clock in services:
            two = cr.sample(counters_pool, 2)
            b.add("giving_counts", _count_row(b, d, key, sid, name, clock, tally[key][0], tally[key][1],
                                              [f"{x['first']} {x['last'][0]}." for x in two]))
    for row in b.rows["invoices"][before:]:
        month_totals[row["paid_at"][:7]] = month_totals.get(row["paid_at"][:7], 0.0) + row["total"]


def _one(b, d, g, slot, amount, fund, r, services, tally, svc):
    how = g["how"]
    if how == "online":
        # Mornings on the church's clock, so the gift's UTC day (what the app
        # reads) is the church's own day in every US zone.
        hh, mm = (7 + r.randint(0, 4), r.randint(0, 59)) if d.weekday() == 6 else (8 + r.randint(0, 4), r.randint(0, 59))
        _gift(b, d, slot, g["p"], amount, fund, "stripe", None, hh, mm)
        return
    key, sid, name, clock = svc(r)
    cid = b.id("count", key, d.isoformat())
    note = f"Check #{1000 + r.randint(0, 8999)}" if how == "check" else ""
    _gift(b, d, slot, g["p"], amount, fund, how, cid, int(clock[:2]) + 1, r.randint(0, 40), note)
    tally[key][0 if how == "cash" else 1] += int(round(amount * 100))


def _campaign(b: _B, pledgers) -> None:
    cid = b.id("campaign", "room-to-grow")
    starts = b.today - timedelta(days=300)
    b.add("church_campaigns", {"id": cid, "name": "Room to Grow", "goal_cents": 12_000_000, "fund": "Building",
                               "starts_on": starts.isoformat(), "ends_on": (b.today + timedelta(days=240)).isoformat(),
                               "note": "A bigger kids wing and a new roof over the fellowship hall.",
                               "created_by": None, "created_at": b.at(starts, 9), "updated_at": b.at(starts, 9)})
    for g in pledgers:
        per = int(g["pledge_month"]) * 100
        b.add("church_pledges", {"id": b.id("pledge", g["p"]["key"]), "campaign_id": cid, "contact_id": g["p"]["id"],
                                 "total_cents": per * 18, "per_period_cents": per, "period": "monthly", "periods": 18,
                                 "note": "", "recorded_by": None, "recorded_at": b.at(starts + timedelta(days=14), 12),
                                 "request_id": None})
    raised = sum(r["total"] for r in b.rows["invoices"] if r["gift_fund"] == "Building"
                 and r["paid_at"][:10] >= starts.isoformat())
    b.story["campaign"] = {"name": "Room to Grow", "goal": 120000, "raised": round(raised, 2),
                           "pledged": sum(int(g["pledge_month"]) * 18 for g in pledgers), "pledges": len(pledgers)}


# ─── Sundays' plans, songs, sermons ───────────────────────────────────

SONGS = (
    ("Amazing Grace", "John Newton"), ("Be Thou My Vision", "Irish hymn, tr. Mary Byrne"),
    ("Come Thou Fount of Every Blessing", "Robert Robinson"), ("Holy, Holy, Holy", "Reginald Heber"),
    ("It Is Well with My Soul", "Horatio Spafford"), ("Blessed Assurance", "Fanny Crosby"),
    ("Great Is the Lord (sample)", "Grace Street worship team"), ("Doxology", "Thomas Ken"),
    ("Joyful, Joyful, We Adore Thee", "Henry van Dyke"), ("Leaning on the Everlasting Arms", "Elisha Hoffman"),
    ("Nothing but the Blood", "Robert Lowry"), ("This Is My Father's World", "Maltbie Babcock"),
)
SERIES = (
    ("Open Table", "Luke's meals with Jesus: who gets a seat, and why.", (
        ("A Seat for Everyone", "Luke 14:12-14"), ("The Feast Nobody Expected", "Luke 14:15-24"),
        ("Dinner with Zacchaeus", "Luke 19:1-10"), ("Bread on the Road", "Luke 24:28-35"))),
    ("Psalms for Ordinary Days", "Prayers for Mondays, waiting rooms and good news.", (
        ("When Morning Comes", "Psalm 5:1-3"), ("A Song for the Waiting", "Psalm 13"),
        ("The Lord Is My Shepherd", "Psalm 23"), ("Deep Calls to Deep", "Psalm 42:5-8"),
        ("Every Breath", "Psalm 150"), ("Teach Us to Number Our Days", "Psalm 90:12-17"))),
    ("Built Together", "Ephesians: one church from many people.", (
        ("Chosen and Loved", "Ephesians 1:3-10"), ("Brought Near", "Ephesians 2:11-18"),
        ("A Dwelling Place", "Ephesians 2:19-22"), ("Grow Up in Love", "Ephesians 4:11-16"),
        ("Walk in Love", "Ephesians 5:1-2"), ("Stand Firm", "Ephesians 6:10-18"))),
)


def _songs_and_plans(b: _B, world, serving) -> None:
    rng = random.Random(f"{SEED}:songs")
    made = b.at(b.today - timedelta(days=500), 10)
    song_ids = []
    for title, author in SONGS:
        sid = b.id("song", title)
        song_ids.append((sid, title))
        b.add("worship_songs", {"id": sid, "title": title, "needs_title": False, "authors": author,
                                "ccli_number": None, "copyright": "" if "sample" in title else "Public domain",
                                "public_domain": "sample" not in title, "song_key": rng.choice(("C", "D", "G", "A", "Bb", "E")),
                                "tempo": rng.choice((68, 72, 76, 84, 92, 104)), "sections": [], "arrangements": [],
                                "lines_per_slide": 2, "has_words": False, "source": "typed", "source_ref": "",
                                "times_sung": {}, "last_sung": None, "archived_at": None,
                                "created_at": made, "updated_at": made})
    sermons = _sermon_plan(b)
    plans = [b.last_sun - timedelta(days=7 * n) for n in (2, 1, 0)] + [b.next_sun]
    for d in sorted(set(plans)):
        sermon = sermons.get(d) or sermons[max(sermons)]
        prng = random.Random(f"{SEED}:plan:{d.isoformat()}")
        picks = prng.sample(song_ids, 4)
        items = [dict(it, show="all", notes="", who="", stage="") for it in [
            {"id": "welcome", "kind": "section", "title": "Welcome", "minutes": 3},
            {"id": "song-1", "kind": "song", "song_id": picks[0][0], "minutes": 5},
            {"id": "song-2", "kind": "song", "song_id": picks[1][0], "minutes": 5},
            {"id": "announce", "kind": "announcement", "title": "This week at Grace Street",
             "when": "", "body": "Food pantry Saturday at 9, Bible study Wednesday at 7.", "minutes": 3},
            {"id": "word", "kind": "section", "title": "The message", "minutes": 0},
            {"id": "reading", "kind": "scripture", "ref": sermon["ref"], "translation": "kjv", "minutes": 3},
            {"id": "sermon", "kind": "section", "title": sermon["title"], "minutes": 32},
            {"id": "song-3", "kind": "song", "song_id": picks[2][0], "minutes": 5},
            {"id": "send", "kind": "section", "title": "Blessing and sending", "minutes": 3},
        ]]
        pid = b.id("plan", d.isoformat())
        b.add("worship_services", {"id": pid, "title": "Sunday Worship", "starts_at": b.at(d, 11, 0), "items": items,
                                   "notes": "", "is_template": False, "archived_at": None,
                                   "created_at": b.at(d - timedelta(days=10), 10), "updated_at": b.at(d - timedelta(days=3), 10)})
        _roster(b, d, pid, serving)


def _roster(b: _B, d: date, plan_id: str, serving) -> None:
    """ChurchSavvy's serving roster for one Sunday: who said yes to which
    place. Next Sunday has its three open places (no row = open)."""
    stamp = b.at(d - timedelta(days=9), 18)
    open_sunday = d == b.next_sun
    for t in serving["teams"]:
        crew = [p for p in t["crew"] if p.get("story") != "drifter"]
        r = random.Random(f"{SEED}:roster:{t['team']}:{d.isoformat()}")
        r.shuffle(crew)
        for pid, pname, needed, filled in t["positions"]:
            take = filled if open_sunday else needed
            for slot in range(1, take + 1):
                p = crew.pop()
                b.add("serve_assignments", {
                    "id": b.id("assign", d.isoformat(), pid, slot), "service_id": plan_id, "position_id": pid,
                    "slot": slot, "contact_id": p["id"], "status": "yes", "note": "", "asked_by": "office",
                    "asked_at": stamp, "answered_at": stamp, "swap_to": None, "swap_asked_at": None,
                    # Every notice is stamped as sent: the serving sweeps pass these by.
                    "notified_at": stamp, "nudged_at": stamp, "leader_told_at": stamp, "week_sent_at": stamp,
                    "day_sent_at": stamp, "morning_sent_at": stamp, "swap_told_at": stamp,
                    "here_at": b.at(d, 8, 30) if d < b.today else None})


def _sermon_plan(b: _B) -> Dict[date, Dict[str, str]]:
    """The sermon each Sunday: the current series from its start to next
    Sunday, the two before it in turn, back across the Sundays recorded."""
    days = b.sundays + [b.next_sun] if b.next_sun not in b.sundays else list(b.sundays)
    days = sorted(set(days))
    flat = []
    for title, about, talks in SERIES:
        for t, ref in talks:
            flat.append((title, t, ref))
    out = {}
    # Newest Sunday gets the current series' 4th talk; walk back from there.
    seq = flat[:4][::-1] + flat[4:]
    for i, d in enumerate(sorted(days, reverse=True)):
        s, t, ref = seq[i % len(seq)]
        out[d] = {"series": s, "title": t, "ref": ref}
    return out


def _sermons(b: _B, holders) -> None:
    plan = _sermon_plan(b)
    series_ids = {}
    for title, about, _ in SERIES:
        sid = b.id("series", title)
        series_ids[title] = sid
        first = min((d for d, s in plan.items() if s["series"] == title), default=b.today)
        b.add("sermon_series", {"id": sid, "title": title, "description": about,
                                "created_at": b.at(first - timedelta(days=14), 10), "updated_at": b.at(first, 10)})
    assoc = holders["associate_pastor"][0]
    for d, s in sorted(plan.items()):
        if d >= b.today:
            continue
        speaker = PASTOR if random.Random(f"{SEED}:speaker:{d.isoformat()}").random() < 0.85 else \
            f"{assoc['first']} {assoc['last']}"
        b.add("sermons", {
            "id": b.id("sermon", d.isoformat()), "series_id": series_ids[s["series"]], "title": s["title"],
            "preached_on": d.isoformat(), "speaker": f"Pastor {speaker}" if speaker == PASTOR else speaker,
            "scripture": s["ref"],
            "summary": f"From {s['ref']}: part of {s['series']}. What it asks of us this week, at home and at work.",
            # Filled in, so no group study is ever drafted (paid) from it.
            "questions": "1. What stood out to you in the passage?\n2. Where do you see yourself in it?\n"
                         "3. What is one thing you will do this week because of it?",
            "video_url": "", "audio_url": "", "published": True,
            "created_at": b.at(d, 14), "updated_at": b.at(d, 14)})
    latest = max(d for d in plan if d < b.today)
    b.story["sermon"] = {"series": plan[latest]["series"], "title": plan[latest]["title"], "ref": plan[latest]["ref"],
                         "next": plan.get(b.next_sun, {}).get("title")}


# ─── The member app ───────────────────────────────────────────────────

def _posts(b: _B, world, holders) -> None:
    posts = (
        (12, "New series: Open Table", "Starting this Sunday we're eating our way through Luke: the meals Jesus shared, and who got a seat. Bring a friend.", True),
        (9, "Kids rooms need two more", "We're two short in the kids rooms most Sundays. Thirty minutes of training and you're in. Reply here or tell any greeter.", False),
        (6, "Food pantry this Saturday", "Doors open at 9 in the fellowship hall. We need hands from 8:30 to sort and pack.", False),
        (4, "Youth night: bring a friend", "Friday at 7 in the youth room. Pizza, games and a short talk.", False),
        (2, "Baptism Sunday is coming", "If you'd like to be baptized, talk with Pastor Jordan or fill in a card in the app. Baptisms are after the 11:00.", False),
        (1, "Thank you, Grace Street", "Last Sunday you filled two vans for the pantry. Thank you for showing up for our neighbors.", False),
    )
    office = holders["administrator"][0]
    for back, title, body, pinned in posts:
        d = b.today - timedelta(days=back)
        at = b.at(d, 10)
        b.add("church_posts", {
            "id": b.id("post", title), "kind": "announcement", "title": title, "body": body, "group_id": None,
            "posted_by": office["id"], "office_user": None, "author_label": "Grace Street office",
            "source": "office", "status": "posted", "pinned_until": b.at(b.today + timedelta(days=5), 23) if pinned else None,
            "important": False, "comments": "on", "publish_at": None, "attach": [], "person_id": None,
            "decided_at": None, "decided_by": "", "told_at": at, "created_at": at, "removed_at": None,
            "celebrate_on": None, "partner_id": None,
            # Stamped as already sent: the news alert and reach sweeps pass these by.
            "alerted_at": at, "reached_at": at, "reach": None})


def _devotional(b: _B) -> None:
    starts = b.today - timedelta(days=4)
    themes = (("Thanks in the morning", "Psalm 92:1-2"), ("Daily bread", "Matthew 6:9-13"),
              ("Count the gifts", "James 1:17"), ("Thanks in the hard days", "1 Thessalonians 5:16-18"),
              ("A thankful table", "Acts 2:46-47"), ("Old mercies, new mornings", "Lamentations 3:22-23"),
              ("Thanks out loud", "Psalm 107:1-2"), ("The one who came back", "Luke 17:11-19"),
              ("Enough", "Philippians 4:11-13"), ("Gifts for others", "1 Peter 4:10"),
              ("Thanks for each other", "Philippians 1:3-6"), ("When it's quiet", "Psalm 46:10"),
              ("The cup that overflows", "Psalm 23:5"), ("Thanks that sends us", "Colossians 3:15-17"))
    days = [{"title": t, "scripture": ref,
             "body": f"Read {ref} slowly. Notice one word that stays with you, and carry it into your day.",
             "pull": "Gratitude is attention, practiced.", "pray": "Thank you, Lord, for one thing I almost missed today.",
             "act": "Tell someone one thing you're thankful for about them.",
             "together": "Share at dinner: what was good today?", "journal": "Where did I see God's kindness today?"}
            for t, ref in themes]
    b.add("devotionals", {
        "id": b.id("devotional", "give-thanks"), "title": "Give Thanks: 14 days", "kind": "series",
        "author": f"Pastor {PASTOR}", "about": "Two weeks of short readings on gratitude, for the whole church together.",
        "practices": [{"key": "readit", "title": "Read the passage", "sub": "Out loud if you can"},
                      {"key": "prayit", "title": "Pray the prayer", "sub": "One minute is plenty"},
                      {"key": "thanks1", "title": "Thank someone", "sub": "A text counts"}],
        "days": days, "starts_on": starts.isoformat(), "voice": "grace", "audio": {}, "status": "published",
        "published_at": b.at(starts - timedelta(days=1), 18),
        "created_at": b.at(starts - timedelta(days=6), 10), "updated_at": b.at(starts - timedelta(days=1), 18)})
    b.story["devotional"] = {"title": "Give Thanks: 14 days", "day": (b.today - starts).days + 1, "of": len(days)}


# ─── Follow-ups, care, shepherding ────────────────────────────────────

def _follow_ups(b: _B, world, holders) -> None:
    import church_follow_up as cfu
    welcome = holders["welcome_lead"][0]
    homes = {h["key"]: h for h in world["homes"]}
    steps = cfu.PATHS["connect"]
    out = []
    for p in world["people"]:
        if not p.get("first_visit"):
            continue
        g = p["guest"]
        first = p["first_visit"]
        h = homes.get(p.get("home") or "")
        # church_first_visit keys a first visit by the family when the person
        # has one (even a family of one), else by the person.
        family_key = f"h:{h['id']}" if h else f"c:{p['id']}"
        assigned = b.at(first, 13)
        done = g in ("joined0", "joined1", "old2", "old3")
        step = 0 if g in ("new0", "new1") else 1
        fid = b.id("follow_up", p["key"])
        b.add("church_follow_ups", {
            "id": fid, "contact_id": p["id"], "card_key": "checkin:first", "card_name": "First check-in",
            "path_kind": "connect", "answers": [{"q": "First visit", "a": "Checked in for the first time"}],
            "steps": steps, "step": len(steps) - 1 if done else step, "leader_contact_id": welcome["id"],
            "leader_role": "welcome_lead", "reason": "First check-ins go to the Welcome Team lead.",
            "assigned_by": "chief", "assigned_at": assigned, "leader_told_at": assigned,
            "due_at": b.at(first + timedelta(days=2 if step == 0 else 14), 17),
            # Past the top of the late ladder: the follow-up sweep never
            # nudges, climbs or emails about a sample's follow-up.
            "status": ("closed" if g == "old3" else "done") if done else "open", "late_level": 3,
            "source_event": f"first-visit:{family_key}"[:80], "created_at": assigned,
            "updated_at": assigned, "done_at": b.at(first + timedelta(days=12), 15) if done else None})
        b.add("church_follow_up_notes", {"id": b.id("fu_note", p["key"], "assigned"), "follow_up_id": fid,
                                         "author_kind": "chief", "author_contact_id": None, "author_user_id": None,
                                         "author_name": "Chief", "kind": "assigned",
                                         "body": f"Handed to {welcome['first']} {welcome['last']}. First check-ins go to the Welcome Team lead.",
                                         "pastors_only": False, "created_at": assigned})
        if step:
            talked = b.at(first + timedelta(days=2), 18)
            b.add("church_follow_up_notes", {"id": b.id("fu_note", p["key"], "talked"), "follow_up_id": fid,
                                             "author_kind": "leader", "author_contact_id": welcome["id"],
                                             "author_user_id": None, "author_name": f"{welcome['first']} {welcome['last']}",
                                             "kind": "talked", "body": "Called to say thank you for coming. Lovely conversation.",
                                             "pastors_only": False, "created_at": talked})
            # Reached: a logged call after their first visit takes them off
            # "first-time guests nobody has reached".
            b.add("events", {"id": b.id("event_row", p["key"], "call"), "contact_id": p["id"],
                             "event_type": "activity_logged", "source": "office",
                             "data": {"kind": "call", "note": "Thank-you call after their first Sunday",
                                      "by": f"{welcome['first']} {welcome['last']}"},
                             "created_at": talked, "provider_event_id": None, "agent_handled_at": talked})
        out.append(fid)
    world["follow_ups"] = out


CARE = (
    # days back, hours, status, text, wants_call, needs_pastor, prayer_team
    (2, 8, "new", "Please pray for my mother. Her surgery is on Thursday and she's nervous.", False, False, True),
    (1, 15, "new", "I lost my job last week. Praying for the next door to open, and for peace at home.", False, False, True),
    (0, 6, "new", "Our son starts treatment next week. We'd love a call from a pastor.", True, True, False),
    (9, 11, "reviewed", "Thank you for praying for my dad. He is home from the hospital.", False, False, True),
    (16, 19, "reviewed", "Pray for our marriage. We're seeing a counselor and want to do this right.", True, True, False),
    (24, 10, "closed", "For my sister's new job in Atlanta, and the move.", False, False, True),
    (37, 12, "closed", "Travel mercies for our missions team this month.", False, False, True),
)


def _care(b: _B, world, holders) -> None:
    rng = random.Random(f"{SEED}:care")
    adults = sorted([p for p in world["people"] if p["kind"] == "adult" and p["status"] == "active"
                     and not p.get("story")], key=lambda p: p["key"])
    rng.shuffle(adults)
    for i, (back, hh, status, text, call, pastor, team) in enumerate(CARE):
        p = adults[i]
        at = b.at(b.today - timedelta(days=back), hh)
        rid = b.id("care", i)
        b.add("ministry_care_requests", {
            "id": rid, "form_id": None, "contact_id": p["id"],
            "submission": {"name": f"{p['first']} {p['last']}", "prayer_request": text, "wants_call": call},
            "status": status, "created_at": at, "legacy_source": None,
            "prayed_at": b.at(b.today - timedelta(days=back - 1), 9) if status != "new" else None,
            "status_changed_at": at if status == "new" else b.at(b.today - timedelta(days=back - 1), 9),
            "updated_at": at, "assigned_at": None, "assigned_by": None,
            "prayer_team": team, "wants_call": call, "needs_pastor": pastor,
            # Never handed to a member who leads: the prayer sweep reads those.
            "leader_contact_id": None, "leader_role": "", "leader_assigned_at": None, "leader_due_at": None,
            "leader_told_at": None, "leader_late_level": 0, "leader_prayed_at": None, "leader_noted_at": None})
        if status != "new":
            b.add("ministry_care_notes", {"id": b.id("care_note", i), "request_id": rid, "author_id": None,
                                          "body": "Prayed with them on Sunday. Will check in next week.",
                                          "created_at": b.at(b.today - timedelta(days=back - 1), 12)})
    fresh = [c for c in CARE if c[2] == "new"]
    b.story["care"] = {"new": len(fresh), "oldest_new_days": max(c[0] for c in fresh)}
    # Benevolence: the help fund and two requests.
    b.add("church_help_settings", {"fund": "Benevolence", "monthly_budget_cents": 80000, "gift_limit_cents": 15000,
                                   "updated_by": None, "updated_at": b.at(b.today - timedelta(days=200), 9)})
    for i, (need, status, cents, notes, back) in enumerate((
            ("bill", "helped", 12500, "Electric bill, one month, paid straight to the utility.", 11),
            ("food", "approved", 6000, "Grocery cards for a family of four.", 3))):
        p = adults[10 + i]
        hid = b.id("help", i)
        at = b.at(b.today - timedelta(days=back), 10)
        b.add("church_help_requests", {"id": hid, "contact_id": p["id"], "name": f"{p['first']} {p['last']}",
                                       "anonymous": False, "pastors_only": False, "wants_call": False, "need": need,
                                       "amount_cents": cents, "approved_cents": cents, "notes": notes,
                                       "status": status, "source": "phone", "care_request_id": None, "created_by": None,
                                       "decided_by": None, "decided_at": at, "created_at": at, "updated_at": at})
        if status == "helped":
            b.add("church_help_given", {"id": b.id("help_given", i), "request_id": hid, "how": "check",
                                        "amount_cents": cents, "given_on": (b.today - timedelta(days=back - 1)).isoformat(),
                                        "payee": "Riverton Power & Light (sample)", "note": "", "expense_id": None,
                                        "recorded_by": None, "created_at": at})


def _shepherding(b: _B, world, holders) -> None:
    shepherds = holders["pastor"] + holders["associate_pastor"] + holders["elders"]
    homes = [h for h in world["homes"] if not h["guest"]]
    rng = random.Random(f"{SEED}:shepherds")
    order = sorted(homes, key=lambda h: h["key"])
    rng.shuffle(order)
    placed = order[: max(1, round(len(order) * 0.78))]
    stamp = b.at(b.today - timedelta(days=150), 10)
    for i, h in enumerate(sorted(placed, key=lambda h: h["key"])):
        s = shepherds[i % len(shepherds)]
        b.add("church_shepherds", {"household_id": h["id"], "shepherd_contact_id": s["id"], "assigned_at": stamp,
                                   "assigned_by": None, "reason": ""})
        if rng.random() < 0.6:
            b.add("church_shepherd_touches", {"id": b.id("touch", h["key"]), "household_id": h["id"],
                                              "shepherd_contact_id": s["id"], "kind": rng.choice(("call", "visit", "text", "church")),
                                              "note": "", "needs_pastor": False,
                                              "created_at": b.at(b.today - timedelta(days=rng.randint(2, 26)), 18)})
    b.add("church_shepherd_settings", {"ministers": False, "cap": 12, "lead_cap": 10, "rhythm_days": 30,
                                       "updated_by": None, "updated_at": stamp})
    # The four who have drifted (each lives alone, so the family is them).
    came = world["came"]
    for p in world["people"]:
        if p.get("story") != "drifter":
            continue
        h = next(x for x in world["homes"] if x["key"] == p["home"])
        last = max(came[p["key"]])
        missed = [d for d in b.sundays if d > last]
        b.add("church_shepherd_signals", {"id": b.id("signal", p["key"]), "household_id": h["id"], "kind": "drift",
                                          "started_on": missed[0].isoformat(), "last_seen": last.isoformat(),
                                          "level": 1, "told_at": b.at(missed[-1] + timedelta(days=1), 7),
                                          "resolved_at": None, "created_at": b.at(missed[-1] + timedelta(days=1), 7)})
    # The shepherding sweep keeps a note of what it has sent. Marking the
    # coming Mondays' notes (and every follow-up's) as already sent means it
    # never writes to anyone about a sample.
    for k in range(9):
        monday = b.today + timedelta(days=(0 - b.today.weekday()) % 7 + 7 * k)
        b.add("church_shepherd_notices", {"key": f"monday-{monday.isoformat()}", "sent_at": b.at(b.today, 0, 5)})
    for fid in world.get("follow_ups", []):
        b.add("church_shepherd_notices", {"key": f"care-{fid}", "sent_at": b.at(b.today, 0, 5)})
    b.story["shepherds"] = {"families": len(homes), "placed": len(placed), "shepherds": len(shepherds)}


# ─── The office ───────────────────────────────────────────────────────

def _register(b: _B, world) -> None:
    for p in world["people"]:
        if p["status"] != "active" or p["kind"] != "adult" or p.get("story") == "pastor":
            continue
        d = p["first_visit"] + timedelta(days=21) if p.get("first_visit") else p["since"] + timedelta(days=60)
        if d >= b.today:
            continue
        b.add("church_register_entries", {
            "id": b.id("register", p["key"]), "kind": "membership", "membership": "joined", "status": "done",
            "event_on": d.isoformat(), "people": [{"role": "person", "name": f"{p['first']} {p['last']}", "contact_id": p["id"]}],
            "contact_ids": [p["id"]], "officiant": None, "place": None, "other_church": None, "notes": "",
            "source": "office", "care_request_id": None, "import_key": None, "created_by": None, "updated_by": None,
            "created_at": b.at(d, 12), "updated_at": b.at(d, 12), "removed_at": None, "removed_by": None})
    j = world["joined"][0]
    bd = b.next_sun + timedelta(days=21)
    b.add("church_register_entries", {
        "id": b.id("register", "baptism", j["key"]), "kind": "baptism", "membership": None, "status": "planned",
        "event_on": bd.isoformat(), "people": [{"role": "person", "name": f"{j['first']} {j['last']}", "contact_id": j["id"]}],
        "contact_ids": [j["id"]], "officiant": f"Pastor {PASTOR}", "place": "Sanctuary", "other_church": None,
        "notes": "", "source": "office", "care_request_id": None, "import_key": None, "created_by": None,
        "updated_by": None, "created_at": b.at(b.today - timedelta(days=3), 12),
        "updated_at": b.at(b.today - timedelta(days=3), 12), "removed_at": None, "removed_by": None})


def _board(b: _B, holders) -> None:
    bid = b.id("board", "deacons")
    made = b.at(b.today - timedelta(days=500), 10)
    b.add("church_boards", {"id": bid, "name": "Deacons", "quorum_kind": "majority", "quorum_count": None,
                            "sort": 0, "archived": False, "created_by": None, "created_at": made, "updated_at": made})
    members = []
    for p in holders["deacons"] + holders["pastor"]:
        mid = b.id("board_member", p["key"])
        members.append(mid)
        b.add("church_board_members", {"id": mid, "board_id": bid, "contact_id": p["id"], "user_id": None,
                                       "name": f"{p['first']} {p['last']}", "title": "Chair" if p is holders["deacons"][0] else "",
                                       "active": True, "created_at": made, "updated_at": made})
    nxt = b.today + timedelta(days=(1 - b.today.weekday()) % 7 or 7)
    past = nxt - timedelta(days=28)
    for d, status in ((past, "approved"), (nxt, "planned")):
        mid = b.id("board_meeting", d.isoformat())
        at = b.at(d, 19)
        b.add("church_board_meetings", {"id": mid, "board_id": bid, "title": "Deacons", "starts_at": at,
                                        "place": "Room 201", "video_url": "", "status": status,
                                        "sent_at": None, "sent_by": None, "sent_count": 0,
                                        "approved_at": b.at(d + timedelta(days=28), 20) if status == "approved" else None,
                                        "approved_by": None, "approved_in": None, "created_by": None,
                                        "created_at": b.at(d - timedelta(days=10), 10), "updated_at": b.at(d - timedelta(days=10), 10)})
        items = (("Benevolence requests this month", "Two requests; both within the fund's limits."),
                 ("Fellowship hall roof", "Three bids in. Recommend the middle one."),
                 ("Thanksgiving baskets", "Sign-up sheet for drivers.")) if status == "planned" else (
                 ("Van insurance renewal", "Renewed at the same rate."), ("Food pantry hours", "Add a second Saturday a month."))
        for n, (title, notes) in enumerate(items):
            iid = b.id("board_item", d.isoformat(), n)
            b.add("church_board_items", {"id": iid, "meeting_id": mid, "position": n, "title": title, "notes": notes,
                                         "minutes": "" if status == "planned" else notes, "status": "open" if status == "planned" else "done",
                                         "documents": [], "carried_from": None, "follow_up_member": None,
                                         "follow_up_due": None, "task_id": None,
                                         "created_at": b.at(d - timedelta(days=9), 10), "updated_at": b.at(d - timedelta(days=9), 10)})
            if status == "approved" and n == 1:
                b.add("church_board_decisions", {"id": b.id("decision", d.isoformat()), "board_id": bid, "meeting_id": mid,
                                                 "item_id": iid, "item_title": title,
                                                 "motion": "Open the food pantry on the first and third Saturdays.",
                                                 "moved_by": members[0], "seconded_by": members[1], "votes_for": 5,
                                                 "votes_against": 0, "votes_abstain": 0, "result": "carried",
                                                 "decided_on": d.isoformat(), "created_by": None, "created_at": at, "updated_at": at})
        if status == "approved":
            for i, m in enumerate(members):
                b.add("church_board_attendance", {"meeting_id": mid, "member_id": m,
                                                  "status": "present" if i != 2 else "excused", "marked_by": None,
                                                  "marked_at": at})


def _tasks(b: _B, holders) -> None:
    """The office's to-do list. Every open task is due more than a week out
    (the Home counts a task due today as a thing that needs you), and every
    told stamp is set so the task sweeps pass them by."""
    stamp = b.at(b.today - timedelta(days=2), 9)
    for i, (title, desc, due, done) in enumerate((
            ("Order communion cups for next month", "Two cases of the pre-filled cups.", 16, False),
            ("Confirm the food pantry delivery", "Call the regional food bank to confirm the drop-off window.", 9, False),
            ("Renew the church van registration", "Due at the end of next month.", 24, False),
            ("Print new visitor cards", "The ones with the QR code to the app.", 12, False),
            ("Send last month's giving summary to the finance team", "", -3, True),
            ("Book the baptism tank cleaning", "", -6, True))):
        due_d = b.today + timedelta(days=due)
        b.add("tasks", {
            "id": b.id("task", i), "contact_id": None, "project_id": None, "title": title, "description": desc,
            "status": "done" if done else "todo", "priority": "medium", "due_date": due_d.isoformat(),
            "completed_at": b.at(due_d, 15) if done else None, "created_at": stamp, "updated_at": stamp,
            # No assignee (the columns are left to their null default): a
            # made-up task is never handed to anyone (church_over's rule).
            "leader_told_at": stamp, "late_told_at": stamp,
            "done_by_contact_id": None, "handed_by": None, "seat_told_at": stamp, "seat_late_told_at": stamp,
            "duty": None, "done_when": None, "check_key": None, "startup_key": None, "stuck_note": None,
            "stuck_at": None, "raised_at": None, "raised_to": None, "raised_to_contact_id": None, "raised_by": None,
            "raised_told_at": stamp, "checked_at": None, "handed_by_contact_id": None, "raised_by_contact_id": None})


def _notifications(b: _B, world) -> None:
    """Five people waiting on a reply (unread), and a few read notes."""
    adults = sorted([p for p in world["people"] if p["kind"] == "adult" and p["status"] == "active"
                     and not p.get("story")], key=lambda p: p["key"])
    random.Random(f"{SEED}:notes").shuffle(adults)
    unread = (
        ("email", "replied to the food pantry email", "Asked whether teenagers can help sort on Saturday."),
        ("email", "asked about baptism", "Wants to know what to wear and whether family can come up front."),
        ("email", "wrote about the kids rooms", "Can serve in the nursery twice a month starting next month."),
        ("text", "texted about Wednesday", "Running late to Bible study, can someone save two seats?"),
        ("text", "texted about a ride", "Needs a ride to the 11:00 on Sunday."),
    )
    for i, (how, what, body) in enumerate(unread):
        p = adults[i]
        at = b.at(b.today - timedelta(days=1 if i < 2 else 0), 7 + i)
        b.add("chief_notifications", {
            "id": b.id("note", i), "type": "info", "title": f"{p['first']} {p['last']} {what}", "body": body,
            "priority": "normal", "status": "unread", "suggested_action": "Reply",
            "action_payload": {"contact_id": p["id"]}, "related_contact_id": p["id"], "related_module_id": None,
            "related_session_id": None, "scheduled_for": at, "shown_at": None, "read_at": None, "created_at": at,
            "data": {"kind": "message", "via": how, "nav": {"tab": "messages"}, "sample": True}})
    read = (("insight", "Giving is steady", "This month is tracking with the last three."),
            ("insight", "Two first-time guests came back", "Both came back the next Sunday."),
            ("info", "Sunday's roster is posted", "Three places are still open."))
    for i, (kind, title, body) in enumerate(read):
        at = b.at(b.today - timedelta(days=3 + i), 8)
        b.add("chief_notifications", {
            "id": b.id("note", "read", i), "type": kind, "title": title, "body": body, "priority": "normal",
            "status": "read", "suggested_action": None, "action_payload": None, "related_contact_id": None,
            "related_module_id": None, "related_session_id": None, "scheduled_for": at, "shown_at": at,
            "read_at": at, "created_at": at, "data": {"sample": True}})
    b.story["waiting_on_reply"] = len(unread)


# ─── The website ──────────────────────────────────────────────────────

def site_config(slug: str) -> Dict[str, Any]:
    """The business_sites.site_config: the fixture's words and photos, the
    sample's own address, and noindex."""
    fx = load_fixture("site_config.json")
    return {"slug": slug, "noindex": True, "sample": True, "html_source": "sample_church",
            "layout": fx["layout"], "words": fx["words"], "facts": fx["facts"], "photos": fx["photos"]}


def _site(b: _B) -> None:
    at = b.at(b.today - timedelta(days=90), 10)
    b.add("business_sites", {"id": b.id("site"), "site_config": site_config(b.slug), "status": "published",
                             "slug": b.slug, "html_content": None, "published_at": at, "created_at": at,
                             "updated_at": at, "hero_composer_module": None})


# ─── Settings ─────────────────────────────────────────────────────────

def settings(tz: str) -> Dict[str, Any]:
    """The sample's settings (merged over BE-1's): its funds, its clock, the
    member app on, and every send switched off."""
    try:
        import member_push
        kinds = list(member_push.KIND_KEYS)
    except Exception:  # noqa: BLE001 — the list is known; never fail a build over an import
        kinds = ["announcements", "live", "messages", "sermons", "events", "classes", "prayer", "groups",
                 "youth", "kids", "news", "serving"]
    return {
        "timezone": tz,
        "availability": {"timezone": tz},
        "giving": {"funds": list(FUNDS), "preset_amounts": [25, 50, 100, 250]},
        "member_portal": {"enabled": True, "notifications": {k: False for k in kinds}},
        "news": {"celebrate": "ask", "ask_members": False, "milestone_classes": False, "reach_rest": False},
        "churchsavvy": {"planning_email": False},
        "feed2": {"contribute": False},
        "messaging": {"enabled": False},
        "autopilot": {"overall": "manual", "per_team": {}},
        "automations_paused": True,
        "checklist_dismissed": True,
    }


# ─── The digest (what the sample's Chief reads, BE-4) ─────────────────

def digest(b: _B, world) -> str:
    s = b.story
    people = world["people"]
    members = sum(1 for p in people if p["status"] == "active")
    guests = sum(1 for p in people if p["status"] == "lead")
    kids = sum(1 for p in people if p["kind"] == "child")
    teens = sum(1 for p in people if p["kind"] == "teen")
    homes = sum(1 for h in world["homes"] if not h["guest"])
    ls = s["last_sunday"]
    g = s["giving"]
    lines = [
        f"{NAME} is a made-up sample church (~190 on a Sunday). Senior pastor: Pastor {PASTOR}. "
        f"Today is {b.today.strftime('%A, %B')} {b.today.day}, {b.today.year}. Nothing here is real; nothing is sent.",
        f"PEOPLE: {len(people)} people on file: {members} on the roll and {guests} guests; {kids} children and {teens} teens; "
        f"{homes} families. Services: Sundays 9:00 and 11:00 (11:00 streamed), Sanctuary.",
        f"LAST SUNDAY ({ls['date']}): {ls['total']} total, {ls['in_room']} in the room, {ls['online']} online, "
        f"{ls['first_time']} first-time; {ls['change']:+d} on the week before. Kids checked in: "
        f"{s['kids_last_sunday']['total']} (" + ", ".join(f"{k} {v}" for k, v in s['kids_last_sunday']['rooms'].items()) + ").",
        "EIGHT SUNDAYS (in room + online): " + "; ".join(f"{x['date']} {x['in_room']}+{x['online']}" for x in s["eight_sundays"]) + ".",
        "THE WAY IN (90 days): 8 first visits, 4 came back, 2 joined a group.",
        "FIRST-TIME GUESTS NOT YET REACHED: " + ", ".join(s["guests_unreached"]) + " (both last Sunday).",
        "MISSED THE LAST THREE SUNDAYS: " + "; ".join(s["drifters"]) + ".",
        f"SERVING NEXT SUNDAY ({b.next_sun.isoformat()}): {s['serving']['filled']} of {s['serving']['needed']} places filled; open: "
        + ", ".join(s["serving"]["open"]) + ". Teams: " + "; ".join(s["serving"]["teams"]) + ".",
        "THIS WEEK: " + "; ".join(f"{w['date']} {w['time']} {w['title']} ({w['coming']} coming)" for w in s["week"]) + ".",
        f"GIVING this month: ${g['this_month']:,.2f} in {g['gifts_this_month']} gifts; by fund: "
        + ", ".join(f"{k} ${v:,.2f}" for k, v in g["by_fund"].items())
        + f". Last month closed at ${g['last_month']:,.2f}. Monthly average ${g['monthly_average']:,.2f} from {g['givers']} givers.",
        f"CAMPAIGN: {s['campaign']['name']} (Building fund), goal ${s['campaign']['goal']:,}; "
        f"{s['campaign']['pledges']} pledges totalling ${s['campaign']['pledged']:,}; ${s['campaign']['raised']:,.2f} given since it began.",
        "GROUPS: " + "; ".join(f"{x['name']} ({x['members']}, led by {x['leader']})" for x in s["groups"]) + ".",
        f"SERMONS: series {s['sermon']['series']}; last Sunday \"{s['sermon']['title']}\" ({s['sermon']['ref']})"
        + (f"; next Sunday \"{s['sermon']['next']}\"." if s['sermon'].get('next') else "."),
        f"CARE: {s['care']['new']} new prayer requests, the oldest {s['care']['oldest_new_days']} days old. "
        f"Shepherds: {s['shepherds']['placed']} of {s['shepherds']['families']} families have one.",
        f"MEMBER APP: devotional {s['devotional']['title']}, day {s['devotional']['day']} of {s['devotional']['of']}. "
        f"{s['waiting_on_reply']} people are waiting on a reply.",
        "NEEDS YOU: 3 serving places open for Sunday; 2 first-time guests not reached; "
        f"{s['care']['new']} new prayer requests; {s['waiting_on_reply']} messages waiting.",
    ]
    return "\n".join(lines)


# ─── Build ────────────────────────────────────────────────────────────

def build(today: date, tz: str, business_id: str, slug: str) -> Dict[str, Any]:
    """Everything the sample church holds, for `today` on the clock `tz`.
    {tables: [(table, rows)] in write order, settings, digest, story}."""
    b = _B(today, tz, business_id, slug)
    world = _people(b)
    _contacts(b, world)
    _guest_dates(b, world)
    _contact_rows(b, world)
    _families(b, world)
    holders = _roles(b, world)
    mods = _modules(b)
    serving = _serving(b, world, holders)
    _groups(b, world, holders)
    cal = _calendar(b, world, mods, holders, serving)
    _attendance(b, world, cal)
    _kids(b, world, cal)
    _attendance_parents_fix(b, world, cal)
    _giving(b, world)
    _songs_and_plans(b, world, serving)
    _sermons(b, holders)
    _posts(b, world, holders)
    _devotional(b)
    _follow_ups(b, world, holders)
    _care(b, world, holders)
    _shepherding(b, world, holders)
    _register(b, world)
    _board(b, holders)
    _tasks(b, holders)
    _notifications(b, world)
    _site(b)
    # The story's last pieces, for the digest.
    came = world["came"]
    b.story["guests_unreached"] = [f"{p['first']} {p['last']}" for p in world["people"] if p.get("guest") in ("new0", "new1")]
    b.story["drifters"] = []
    for p in world["people"]:
        if p.get("story") == "drifter":
            role = {"greeter": "greeting team", "sound": "sound booth"}.get(p["drift_role"], "member")
            b.story["drifters"].append(f"{p['first']} {p['last']} ({role}, last here {max(came[p['key']]).isoformat()})")
    open_places, teams_line, filled, needed = [], [], 0, 0
    for team, rid, positions in SERVING:
        f = sum(x[2] for x in positions)
        n = sum(x[1] for x in positions)
        filled, needed = filled + f, needed + n
        teams_line.append(f"{team} {f} of {n}")
        open_places += [f"{team}: {pos}" for pos, nn, ff in positions for _ in range(nn - ff)]
    b.story["serving"] = {"filled": filled, "needed": needed, "open": open_places, "teams": teams_line}
    b.story["people"] = {"contacts": len(b.rows["contacts"]), "households": len(b.rows["households"]),
                         "children": sum(1 for p in world["people"] if p["kind"] == "child")}
    return {"tables": [(t, b.rows[t]) for t in TABLES], "settings": settings(tz),
            "digest": digest(b, world), "story": b.story, "today": today.isoformat(), "tz": tz}

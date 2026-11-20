"""The leaders schedule's tables on the four test churches (church_three), for
test_church_schedule_roster.py and test_church_schedule.py.

    db = build(monkeypatch)        church_three.build, plus the schedule's
                                   four tables and serve_away, the switch on,
                                   the tables "there" (church_schedule._FORCE)
    db = build(monkeypatch, limits=True)
                                   step 2's file applied too (see below)
    db = build(monkeypatch, meetings=True)
                                   step 3's file applied too (Meetings &
                                   minutes: the board's six tables and its
                                   new columns and tables; see STEP 3 below)
    app = meetings_client(db)      the board's and the meetings' routers,
                                   signed in by as_() through require_user
    app = client(db)               the real routers; as_(app, church, handle)
                                   signs a login in

The tables behave as supabase/APPLY-2026-11-19-church-schedule.sql says (the
PGlite check, church_schedule_db.mjs, runs the real file): the defaults, the
checks, the same-church triggers, one waiting ask for the same days
(church_away_asks_one_open), one row a person on the lists, and
church_away_settle exactly as the function is written, `changed: false`
included. Things that repeat (S1-7): church_away_commitments' defaults, its
checks (the label, the weekday, the pattern, nth only for month_nth, until
after the start, every other week's start on its weekday) and its same-church
trigger, on an insert. A write the database would refuse answers None, as
sb_clients does, and `db.refused` keeps why.

    db.fail = {"post": "/church_away_asks", ...}   that write (or read) fails
    db.posts = [(table or rpc, redact)]             every POST, with whether it
                                                    was sent redacted
    db.before_settle = fn                           runs just before the
                                                    function locks the row: the
                                                    other answer landing first
    db.later = [fn, ...]                            the notices a write handed
                                                    on (member_push._later),
                                                    kept and NOT run: nothing
                                                    is told inside a write.
                                                    later(db) runs them

STEP 2 (supabase/APPLY-2026-11-20-church-schedule-limits.sql; its PGlite check
is church_schedule_limits_db.mjs). `limits=False`, the default, is a database
with step 1's file alone: every read or write that names one of step 2's
tables, columns or its function is refused, as PostgREST refuses what isn't
there, and church_schedule_limits._FORCE is False. So every step 1 suite runs
on exactly the database it was written for. `limits=True` is the database
with both files: the two numbers and the usual service days on
church_schedule_settings (their checks), church_schedule_department_limits
(one number a department, the department and whoever set it the church's
own), church_protected_days (one row a date a church, merged), church_away_pairs
(its before trigger, then ordered and the note's length, then one row a pair:
on an insert, and on an update the trigger only when it names a person or
the church, as the SQL's column list says), `excepted` and
`team_group_id` on an ask (their defaults, church_away_asks_excepted on every
write, the team the church's own), and church_away_settle_excepted exactly as
the function is written: church_away_settle's decision, then the exception
saved on a yes it just made, each flag once in order, and a bad one refused
with the yes and its away date undone.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import re  # noqa: E402

import church_schedule as cs  # noqa: E402
import church_schedule_limits as csl  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_three import LOVE_CITY, NEW_HOPE  # noqa: E402

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)      # Wednesday, 10 AM in Detroit
TODAY = date(2026, 11, 18)
KINDS = ("time_off", "commitment", "cant")
FLAGS = {"short_notice", "over_limit", "protected_day", "pair", "serving"}
EXCEPTIONS = {"over_limit", "protected_day", "pair"}
# What step 2's file adds: before it, PostgREST refuses any read or write that names one.
STEP2_NEW = re.compile(r"\b(church_schedule_department_limits|church_protected_days|church_away_pairs|leaders_limit|"
                       r"office_limit|service_weekdays|excepted|team_group_id|church_away_settle_excepted)\b")


def day(n: int) -> str:
    """The day `n` days from today."""
    return (TODAY + timedelta(days=n)).isoformat()


def _mine(d, table, biz, cid) -> bool:
    return any(c["id"] == cid and c["business_id"] == biz for c in d.t[table])


def _ask_row(d, b):
    """An insert into church_away_asks: the table's defaults, then its checks
    and its trigger. None, with why, for one the database refuses."""
    row = {"made_by": None, "department_id": None, "reason": None, "cover_contact_id": None, "cover_name": None,
           "to_user_id": None, "to_contact_id": None, "state": "asked", "flags": [], "decided_by_user_id": None,
           "decided_by_contact_id": None, "decided_at": None, "decided_note": None, "withdrawn_at": None,
           "told_at": None, "answer_told_at": None, "nudged_at": None,
           **({"excepted": [], "team_group_id": None} if d.limits else {}), **b}
    a, z = date.fromisoformat(row["starts_on"]), date.fromisoformat(row["ends_on"])
    why = None
    if row["grp"] not in ("leaders", "office", "volunteers") or row["kind"] not in KINDS:
        why = "check: grp or kind"
    elif z < a or (z - a).days > 366:
        why = "check: church_away_asks_days"
    elif row["reason"] is not None and len(row["reason"]) > 500:
        why = "check: reason"
    elif row["cover_name"] is not None and not 1 <= len(row["cover_name"].strip()) <= 80:
        why = "check: cover_name"
    elif row["to_user_id"] and row["to_contact_id"]:
        why = "check: church_away_asks_to_one"
    elif row["cover_contact_id"] and row["cover_contact_id"] == row["contact_id"]:
        why = "check: church_away_asks_cover_other"
    elif not set(row["flags"]) <= FLAGS:
        why = "check: flags"
    elif row["state"] != "asked":
        why = "check: church_away_asks_decided"
    elif not all(_mine(d, "contacts", row["business_id"], row[k])
                 for k in ("contact_id", "cover_contact_id", "to_contact_id") if row[k] or k == "contact_id"):
        why = "trigger: church_away_asks_same_business"
    elif row["department_id"] and not _mine(d, "church_departments", row["business_id"], row["department_id"]):
        why = "trigger: church_away_asks_same_business"
    elif any(r["state"] == "asked" and all(r[k] == row[k] for k in ("business_id", "contact_id", "starts_on",
                                                                    "ends_on"))
             for r in d.t["church_away_asks"]):
        why = "unique: church_away_asks_one_open"
    elif d.limits and _excepted_wrong(row):
        why = "check: church_away_asks_excepted"
    elif d.limits and row["team_group_id"] and not _mine(d, "groups", row["business_id"], row["team_group_id"]):
        why = "trigger: church_away_asks_team_same_business"
    if why:
        d.refused.append(why)
        return None
    return row


def _excepted_wrong(row) -> bool:
    """church_away_asks_excepted: an exception is for a flag the ask has
    (over the limit, a protected day, a pair), and sits only on a yes or on
    a yes that was taken back."""
    x = list(row.get("excepted") or [])
    return bool(not set(x) <= EXCEPTIONS or not set(x) <= set(row.get("flags") or [])
                or (x and row.get("state") not in ("yes", "withdrawn")))


def settle_excepted(d, b):
    """church_away_settle_excepted, as step 2's file writes it:
    church_away_settle makes the decision; then, only for a yes it just made
    and only when an exception was passed, the exception is saved on the
    ask, each flag once and in order. One for a flag the ask doesn't have is
    refused by name, and the yes and its away date go with it."""
    x = sorted({str(e) for e in (b.get("p_excepted") or [])})
    asks, facts = [dict(r) for r in d.t["church_away_asks"]], [dict(r) for r in d.t["serve_away"]]
    r = settle(d, {k: v for k, v in b.items() if k != "p_excepted"})
    if r is None or b.get("p_state") != "yes" or not x or not r["changed"]:
        return r
    if not (set(x) <= EXCEPTIONS and set(x) <= set(r["ask"].get("flags") or [])):
        d.t["church_away_asks"], d.t["serve_away"] = asks, facts      # one statement: the yes is undone with it
        d.refused.append("raise: An exception is for a flag the ask has")
        return None
    v = next(a for a in d.t["church_away_asks"] if a["id"] == b.get("p_ask_id"))
    v["excepted"] = x
    return {"changed": True, "ask": dict(v)}


def _setting(d, b) -> bool:
    """church_schedule_settings: the checks on its numbers and its usual
    service days (a plain list of 1 to 7 of the days 1 to 7). True when the
    database would refuse the row."""
    for k in ("leaders_limit", "office_limit"):
        n = b.get(k)
        if n is not None and (isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 99):
            d.refused.append("check: church_schedule_settings_limits")
            return True
    w = b.get("service_weekdays")
    if w is not None and not (isinstance(w, list) and 1 <= len(w) <= 7
                              and all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 7 for x in w)):
        d.refused.append("check: church_schedule_settings_weekdays")
        return True
    return False


def _upsert(d, table, keys, b, defaults):
    """An insert that merges on `keys` (resolution=merge-duplicates)."""
    have = next((r for r in d.t[table] if all(r.get(k) == b.get(k) for k in keys)), None)
    if have is None:
        have = {**defaults, **({"id": str(uuid.uuid4())} if "id" in defaults else {})}
        d.t[table].append(have)
    have.update(b)
    return [dict(have)]


def _department_limit(d, b, prefer):
    """church_schedule_department_limits: one number a department (its
    primary key), 1 to 99, set by a login or a person and never both, the
    department and that person the row's own church's."""
    n = b.get("at_most")
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 99:
        d.refused.append("check: at_most")
        return None
    if b.get("set_by_user_id") and b.get("set_by_contact_id"):
        d.refused.append("check: church_schedule_department_limits_by_one")
        return None
    if not _mine(d, "church_departments", b.get("business_id"), b.get("department_id")):
        d.refused.append("trigger: That department is not in this church")
        return None
    if b.get("set_by_contact_id") and not _mine(d, "contacts", b["business_id"], b["set_by_contact_id"]):
        d.refused.append("trigger: The person who set it is not in this church")
        return None
    have = next((r for r in d.t["church_schedule_department_limits"] if r["department_id"] == b["department_id"]), None)
    if have is not None and "merge-duplicates" not in (prefer or ""):
        d.refused.append("unique: church_schedule_department_limits_pkey")
        return None
    return _upsert(d, "church_schedule_department_limits", ("department_id",), b,
                   {"set_by_user_id": None, "set_by_contact_id": None, "updated_at": NOW.isoformat()})


def _protected(d, b, prefer):
    """church_protected_days: one row a date a church
    (church_protected_days_one), a name of 1 to 80 letters."""
    name = b.get("name")
    try:
        date.fromisoformat(str(b.get("day")))
    except ValueError:
        d.refused.append("type: day")
        return None
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        d.refused.append("check: name")
        return None
    have = next((r for r in d.t["church_protected_days"]
                 if r["business_id"] == b.get("business_id") and r["day"] == b.get("day")), None)
    if have is not None and "merge-duplicates" not in (prefer or ""):
        d.refused.append("unique: church_protected_days_one")
        return None
    return _upsert(d, "church_protected_days", ("business_id", "day"), b,
                   {"id": None, "created_by": None, "created_at": NOW.isoformat()})


def _pair_wrong(d, row, old=None):
    """church_away_pairs' guards on a row as it would stand, in Postgres's
    order: the before trigger church_schedule_limits_same_business first
    (on an insert, or an update that names either person or the church:
    both people this church's, which someone paired with themself is not),
    then the checks (church_away_pairs_ordered: the smaller id first, as
    their lower-case text orders, which is how Postgres orders uuids; the
    note 140 at most), then church_away_pairs_one. Why, or None."""
    a, z = str(row.get("a_contact_id") or ""), str(row.get("b_contact_id") or "")
    named = old is None or any(row.get(k) != old.get(k) for k in ("a_contact_id", "b_contact_id", "business_id"))
    if named and (a == z or not (_mine(d, "contacts", row.get("business_id"), a)
                                 and _mine(d, "contacts", row.get("business_id"), z))):
        return "trigger: A pair is two people in this church"
    if not a.lower() < z.lower():
        return "check: church_away_pairs_ordered"
    if row.get("note") is not None and len(row["note"]) > 140:
        return "check: note"
    if any(r is not old and r["business_id"] == row.get("business_id") and r["a_contact_id"] == a
           and r["b_contact_id"] == z for r in d.t["church_away_pairs"]):
        return "unique: church_away_pairs_one"
    return None


def _pair(d, b):
    """church_away_pairs: the smaller id first, two of the church's own
    people, one row a pair, a note of 140 at most."""
    row = {"id": str(uuid.uuid4()), "note": None, "created_by": None, "created_at": NOW.isoformat(), **b}
    why = _pair_wrong(d, row)
    if why:
        d.refused.append(why)
        return None
    d.t["church_away_pairs"].append(row)
    return [dict(row)]


def settle(d, b):
    """church_away_settle, as the migration writes it."""
    state = b.get("p_state")
    if state not in ("yes", "no", "withdrawn"):
        d.refused.append("raise: An ask is answered yes or no, or withdrawn")
        return None                                             # the function raises; sb_clients gives None
    if d.before_settle:
        fn, d.before_settle = d.before_settle, None
        fn()
    v = next((r for r in d.t["church_away_asks"]
              if r["id"] == b.get("p_ask_id") and r["business_id"] == b.get("p_business_id")), None)
    if v is None:
        return None                                             # the function answers null
    if (state in ("yes", "no") and v["state"] != "asked") or (state == "withdrawn" and v["state"] not in ("asked", "yes")):
        return {"changed": False, "ask": dict(v)}
    d.ticks += 1
    now = (NOW + timedelta(seconds=d.ticks)).isoformat()
    if state == "withdrawn":
        v.update(state="withdrawn", withdrawn_at=now, updated_at=now)
        d.t["serve_away"] = [s for s in d.t["serve_away"]
                             if not (s.get("ask_id") == v["id"] and s["business_id"] == v["business_id"])]
    else:
        if b.get("p_by_user") and b.get("p_by_contact"):
            d.refused.append("check: church_away_asks_by_one")
            return None
        if b.get("p_by_contact") and not _mine(d, "contacts", v["business_id"], b["p_by_contact"]):
            d.refused.append("trigger: church_away_asks_same_business")
            return None
        v.update(state=state, decided_at=now, decided_by_user_id=b.get("p_by_user"),
                 decided_by_contact_id=b.get("p_by_contact"),
                 decided_note=((b.get("p_note") or "")[:300].strip() or None), answer_told_at=None, updated_at=now)
        if state == "yes" and not any(s.get("ask_id") == v["id"] for s in d.t["serve_away"]):
            d.t["serve_away"].append({"id": str(uuid.uuid4()), "business_id": v["business_id"],
                                      "contact_id": v["contact_id"], "starts_on": v["starts_on"],
                                      "ends_on": v["ends_on"], "note": "", "ask_id": v["id"], "kind": v["kind"],
                                      "created_at": now})
    return {"changed": True, "ask": dict(v)}


def _commitment(d, b):
    """An insert into church_away_commitments (S1-7), as step 1's file makes
    the table: its defaults, its checks (the label 1 to 80 letters once
    trimmed, a weekday 1 to 7, the three patterns, nth exactly when it is
    month_nth and 1 to 5, until on or after the start, every other week's
    start on its weekday), and its trigger (the person is the church's
    own). None, with why, for a row the database refuses."""
    row = {"nth": None, "until_on": None, "told_at": None, **b}
    label, wd, nth = row.get("label"), row.get("weekday"), row.get("nth")
    why = None
    try:
        start = date.fromisoformat(str(row.get("starts_on")))
        until = date.fromisoformat(str(row["until_on"])) if row.get("until_on") else None
    except ValueError:
        start = until = None
        why = "type: date"
    if why:
        pass
    elif not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
        why = "check: label"
    elif isinstance(wd, bool) or not isinstance(wd, int) or not 1 <= wd <= 7:
        why = "check: weekday"
    elif row.get("pattern") not in ("weekly", "every_other", "month_nth"):
        why = "check: pattern"
    elif (row["pattern"] == "month_nth") != (nth is not None) or (nth is not None and not 1 <= nth <= 5):
        why = "check: church_away_commitments_nth"
    elif until is not None and until < start:
        why = "check: church_away_commitments_until"
    elif row["pattern"] == "every_other" and start.isoweekday() != wd:
        why = "check: church_away_commitments_anchor"
    elif not _mine(d, "contacts", row.get("business_id"), row.get("contact_id")):
        why = "trigger: church_schedule_person_same_business"
    if why:
        d.refused.append(why)
        return None
    return row


def _listed(d, b):
    """church_schedule_people: one row a person (its primary key), merged."""
    if (b.get("listed") == "add") != (b.get("grp") is not None) or b.get("listed") not in ("add", "remove") \
            or b.get("grp") not in (None, "leaders", "office"):
        d.refused.append("check: church_schedule_people_group")
        return None
    if not _mine(d, "contacts", b["business_id"], b["contact_id"]):
        d.refused.append("trigger: church_schedule_person_same_business")
        return None
    have = next((r for r in d.t["church_schedule_people"]
                 if r["business_id"] == b["business_id"] and r["contact_id"] == b["contact_id"]), None)
    if have is None:
        have = {}
        d.t["church_schedule_people"].append(have)
    have.update(b)
    return [dict(have)]



# ─── STEP 3: Meetings & minutes (supabase/APPLY-2026-11-21-church-meetings.sql) ───
#
# build(meetings=True) is the database with Board & minutes' six tables and
# step 3's file: church_boards' kind and audience, church_board_members'
# from_list, church_board_meetings' new columns, and church_meeting_answers
# (with series, notices and links there, empty). The rules are the file's own,
# as its PGlite check (church_meetings_db.mjs) runs them: the checks, the
# triggers (a group keeps its audience; a seat is the list's exactly when its
# group follows the list, names a person, and stays that person's; an
# answer's seat sits on the meeting's group), the unique indexes (one open
# group for the list a name, whatever its case; one list seat a person a
# group: both partial, so a POST naming them in on_conflict is refused as
# Postgres refuses it, 42P10), and the answers' primary key (meeting_id,
# member_id), plain, which PostgREST's on_conflict may name. A write the
# database would refuse changes nothing, answers None, and leaves why in
# sb_clients.last_error() ({status, code, message}) and db.refused.
#
# build(meetings=False), the default, is the database before that file: a
# read or write naming one of its tables, or one of its columns on the three
# board tables, is refused as PostgREST refuses what isn't there.

MEET_TABLES = ("church_meeting_series", "church_meeting_answers", "church_meeting_notices", "church_calendar_links")
MEET_COLS = re.compile(r"\b(kind|audience|from_list|series_id|series_day|length_minutes|space_id|booking_id|"
                       r"cancelled_at|cancelled_by|changed_alone_at)\b")
BOARD_TABLES = ("church_boards", "church_board_members", "church_board_meetings")
BOARD_DEFAULTS = {"quorum_kind": "majority", "quorum_count": None, "sort": 0, "archived": False, "created_by": None,
                  "kind": "board", "audience": "members"}
SEAT_DEFAULTS = {"contact_id": None, "user_id": None, "title": "", "active": True, "from_list": False}
MEETING_DEFAULTS = {"title": "", "place": "", "video_url": "", "status": "planned", "sent_at": None, "sent_by": None,
                    "sent_count": 0, "approved_at": None, "approved_by": None, "approved_in": None,
                    "created_by": None, "series_id": None, "series_day": None, "length_minutes": None,
                    "space_id": None, "booking_id": None, "cancelled_at": None, "cancelled_by": None,
                    "changed_alone_at": None}
ITEM_DEFAULTS = {"notes": "", "minutes": "", "status": "open", "documents": [], "carried_from": None,
                 "follow_up_member": None, "follow_up_due": None, "task_id": None, "position": 0}
DECISION_DEFAULTS = {"moved_by": None, "seconded_by": None, "votes_for": 0, "votes_against": 0, "votes_abstain": 0}
ANSWER_DEFAULTS = {"note": None, "by_user_id": None, "by_contact_id": None}
# The unique keys PostgREST's on_conflict may name on each table (a plain
# unique index or a primary key). Anything else is Postgres's 42P10.
ON_CONFLICT = {"church_board_items": {"carried_from"}, "church_board_attendance": {"meeting_id,member_id"},
               "church_meeting_answers": {"meeting_id,member_id"}}
_TABLES_WRITTEN = ("church_boards", "church_board_members", "church_board_meetings", "church_board_items",
                   "church_board_attendance", "church_board_decisions", "church_meeting_answers")


def _err(d, why, code, status=400):
    """A refusal, as sb_clients reports one: None, and why in last_error()."""
    d.refused.append(why)
    sb_clients._LAST.error = {"status": status, "code": code, "message": why}
    return None


def _meet_absent(d, path, body=None) -> bool:
    """Before step 3's file: its tables, and its columns on the board's
    tables, aren't there to name."""
    if d.meetings:
        return False
    table = path.lstrip("/").split("?")[0]
    if table in MEET_TABLES:
        _err(d, f"absent: {table}", "PGRST205", 404)
        return True
    if table in BOARD_TABLES:
        keys = " ".join(k for b in (body if isinstance(body, list) else [body or {}]) for k in b)
        if MEET_COLS.search(path.partition("?")[2] + " " + keys):
            _err(d, "absent: a step 3 column", "42703")
            return True
    return False


def _conflict_cols(path):
    m = re.search(r"[?&]on_conflict=([^&]+)", path)
    return m.group(1) if m else None


def _group_wrong(d, row, old=None):
    """church_boards' rules, in Postgres's order: the before trigger
    (church_boards_audience_kept), the checks, then the partial unique
    index church_boards_one_list_name."""
    if old is not None and row.get("audience") != old.get("audience"):
        return "trigger: A meeting keeps who it is for", "P0001"
    if row.get("kind") not in ("board", "meeting"):
        return "check: church_boards_kind", "23514"
    if row.get("audience") not in ("members", "leaders", "office"):
        return "check: church_boards_audience", "23514"
    if not (row["audience"] == "members" or row["kind"] == "meeting"):
        return "check: church_boards_list_is_meeting", "23514"
    if not 1 <= len(str(row.get("name") or "")) <= 80:
        return "check: name", "23514"
    if row.get("quorum_kind") == "count" and row.get("quorum_count") is None:
        return "check: church_boards_count_needs_number", "23514"
    if row["audience"] != "members" and not row.get("archived"):
        if any(r is not old and r["business_id"] == row["business_id"] and r.get("audience") == row["audience"]
               and not r.get("archived") and str(r.get("name") or "").lower() == str(row["name"]).lower()
               for r in d.t["church_boards"]):
            return "unique: church_boards_one_list_name", "23505"
    return None


def _seat_wrong(d, row, old=None):
    """church_board_members' rules: church_board_members_follow_list (before
    insert, and before an update of from_list, board_id, business_id or
    contact_id), the name's check, then the partial unique index
    church_board_members_one_from_list."""
    if old is not None and row.get("from_list") and row.get("contact_id") is not None \
            and row.get("contact_id") != old.get("contact_id"):
        return "trigger: A seat from the list stays its person's", "P0001"
    if old is None or any(row.get(k) != old.get(k) for k in ("from_list", "board_id", "business_id")):
        g = next((b for b in d.t["church_boards"]
                  if b["id"] == row.get("board_id") and b["business_id"] == row.get("business_id")), None)
        if g is None:
            return "foreign key: church_board_members_board", "23503"
        a = g.get("audience") or "members"
        if row.get("from_list") and a == "members":
            return "trigger: Only a meeting for every leader or the office follows the list", "P0001"
        if not row.get("from_list") and a != "members":
            return "trigger: This meeting follows the leaders list: add them there", "P0001"
        if row.get("from_list") and row.get("contact_id") is None:
            return "trigger: Someone the list adds is one of the church's people", "P0001"
    if not 1 <= len(str(row.get("name") or "")) <= 120:
        return "check: name", "23514"
    if row.get("from_list") and row.get("contact_id") is not None:
        if any(r is not old and r.get("from_list") and r["board_id"] == row["board_id"]
               and r.get("contact_id") == row["contact_id"] for r in d.t["church_board_members"]):
            return "unique: church_board_members_one_from_list", "23505"
    return None


def _meeting_wrong(d, row, old=None):
    """church_board_meetings' checks (step 3's four, and the status's own)."""
    if row.get("status") not in ("planned", "in_progress", "drafted", "approved"):
        return "check: status", "23514"
    n = row.get("length_minutes")
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or not 5 <= n <= 720):
        return "check: church_board_meetings_length", "23514"
    if (row.get("cancelled_at") and row.get("status") != "planned") or (row.get("cancelled_by")
                                                                         and not row.get("cancelled_at")):
        return "check: church_board_meetings_called_off", "23514"
    if row.get("series_id") and not row.get("series_day"):
        return "check: church_board_meetings_series_day", "23514"
    if row.get("changed_alone_at") and not row.get("series_day"):
        return "check: church_board_meetings_alone", "23514"
    if old is None and not any(b["id"] == row.get("board_id") and b["business_id"] == row.get("business_id")
                               for b in d.t["church_boards"]):
        return "foreign key: church_board_meetings_board", "23503"
    return None


def _answer_wrong(d, row):
    """church_meeting_answers' checks, its foreign keys and the same-church
    trigger: the seat sits on the meeting's group; the person who answered
    is the church's."""
    if row.get("answer") not in ("yes", "cant"):
        return "check: answer", "23514"
    note = row.get("note")
    if note is not None and not 1 <= len(str(note).strip()) <= 200:
        return "check: note", "23514"
    if note is not None and row["answer"] != "cant":
        return "check: church_meeting_answers_note", "23514"
    if row.get("by_user_id") and row.get("by_contact_id"):
        return "check: church_meeting_answers_by_one", "23514"
    if not row.get("for_starts_at"):
        return "not null: for_starts_at", "23502"
    m = next((x for x in d.t["church_board_meetings"]
              if x["id"] == row.get("meeting_id") and x["business_id"] == row.get("business_id")), None)
    s = next((x for x in d.t["church_board_members"]
              if x["id"] == row.get("member_id") and x["business_id"] == row.get("business_id")), None)
    if m is None or s is None:
        return "foreign key: church_meeting_answers_meeting / _member", "23503"
    if s["board_id"] != m["board_id"]:
        return "trigger: church_meetings_same_business (the seat is on the meeting's group)", "P0001"
    if row.get("by_contact_id") and not _mine(d, "contacts", row["business_id"], row["by_contact_id"]):
        return "trigger: church_meetings_same_business (the person who answered)", "P0001"
    return None


_WRONG = {"church_boards": _group_wrong, "church_board_members": _seat_wrong,
          "church_board_meetings": _meeting_wrong}
_DEFAULTS = {"church_boards": BOARD_DEFAULTS, "church_board_members": SEAT_DEFAULTS,
             "church_board_meetings": MEETING_DEFAULTS, "church_board_items": ITEM_DEFAULTS,
             "church_board_decisions": DECISION_DEFAULTS, "church_meeting_answers": ANSWER_DEFAULTS}
_KEYS = {"church_board_items": ("carried_from",), "church_board_attendance": ("meeting_id", "member_id"),
         "church_meeting_answers": ("meeting_id", "member_id")}


def _meet_post(d, path, body, prefer):
    """An insert into one of the board's tables or the answers, as the
    database (with step 3's file) takes it. One statement: a row refused
    refuses them all."""
    table = path.lstrip("/").split("?")[0]
    cols = _conflict_cols(path)
    if cols is not None and cols not in ON_CONFLICT.get(table, set()):
        # PostgREST sends no index predicate: Postgres can't infer a partial
        # (or an expression) index from the columns alone.
        return _err(d, f"42P10: no unique index on {table}({cols}) to name", "42P10")
    rows = [dict({**_DEFAULTS.get(table, {}), **r}) for r in (body if isinstance(body, list) else [body])]
    have = d.t.setdefault(table, [])
    out, fresh, merged = [], [], []
    keys = _KEYS.get(table)
    for r in rows:
        if table not in ("church_board_attendance", "church_meeting_answers"):
            r.setdefault("id", d.nid(table))
        r.setdefault("created_at", (NOW + timedelta(seconds=len(have) + len(fresh))).isoformat())
        if table == "church_meeting_answers":
            r.setdefault("answered_at", NOW.isoformat())
            why = _answer_wrong(d, r)
        else:
            fn = _WRONG.get(table)
            why = fn(d, r) if fn else None
        if why:
            return _err(d, *why)
        old = next((h for h in have + fresh if keys and all(h.get(k) == r.get(k) for k in keys)
                    and all(r.get(k) is not None for k in keys)), None)
        if old is not None:
            if cols is None:
                return _err(d, f"unique: {table} {keys}", "23505", 409)
            if "merge-duplicates" in (prefer or ""):
                merged.append((old, r))
            continue                            # ignore-duplicates: left as it is
        if table in ("church_boards", "church_board_members"):
            # Two rows of one statement clash with each other too.
            d.t[table] = have + fresh
            why = _WRONG[table](d, r)
            d.t[table] = have
            if why:
                return _err(d, *why)
        fresh.append(r)
    for old, r in merged:
        old.update({k: v for k, v in r.items() if k != "created_at"})
        out.append(dict(old))
    have.extend(fresh)
    out += [dict(r) for r in fresh]
    return out


def _meet_patch(d, path, body):
    """An update, the rules run on each row as it would stand after; one
    refused changes nothing."""
    table, filters, _limit = d._parse(path)
    hits = [r for r in d.t.get(table, []) if d._match(r, filters)]
    fn = _WRONG.get(table)
    for r in hits:
        after = {**r, **body}
        why = fn(d, after, old=r) if fn else (_answer_wrong(d, after) if table == "church_meeting_answers" else None)
        if why:
            return _err(d, *why)
    for r in hits:
        r.update(body)
    return [dict(r) for r in hits]


def _meet_delete(d, path):
    table, filters, _limit = d._parse(path)
    gone = [r for r in d.t.get(table, []) if d._match(r, filters)]
    d.t[table] = [r for r in d.t.get(table, []) if not d._match(r, filters)]
    if table == "church_board_meetings":
        # What goes with a meeting: its agenda, attendance, decisions, answers.
        ids = {r["id"] for r in gone}
        for t in ("church_board_items", "church_board_attendance", "church_board_decisions",
                  "church_meeting_answers"):
            d.t[t] = [r for r in d.t.get(t, []) if r.get("meeting_id") not in ids]
    return True


def _meetings_tables(d, meetings):
    """The board's six tables at every church (church_three made two of
    them), as the board's own file and step 3's make them."""
    for t in ("church_board_meetings", "church_board_items", "church_board_attendance", "church_board_decisions"):
        d.t.setdefault(t, [])
    if meetings:
        for t in MEET_TABLES:
            d.t[t] = []
    for b in d.t["church_boards"]:
        for k, v in BOARD_DEFAULTS.items():
            if meetings or k not in ("kind", "audience"):
                b.setdefault(k, v)
        b.setdefault("created_at", "2026-10-01T00:00:00+00:00")
    for s in d.t["church_board_members"]:
        s.setdefault("id", d.nid("church_board_members"))
        s.setdefault("title", "")
        s.setdefault("created_at", "2026-10-01T00:00:00+00:00")
        if meetings:
            s.setdefault("from_list", False)
        if not s.get("name"):
            c = next((x for x in d.t["contacts"] if x["id"] == s.get("contact_id")), None)
            s["name"] = (c or {}).get("name") or "A member"


def build(monkeypatch, *, mode: str = "on", limits: bool = False, meetings: bool = False,
          meetings_mode: str = "on", **kw):
    monkeypatch.setenv("CHURCH_SCHEDULE", mode)
    d = c3.build(monkeypatch, **kw)
    d.meetings = meetings
    _meetings_tables(d, meetings)
    for t in ("church_schedule_settings", "church_schedule_people", "church_away_asks", "church_away_commitments",
              "serve_away"):
        d.t[t] = []
    d.limits = limits
    if limits:
        for t in ("church_schedule_department_limits", "church_protected_days", "church_away_pairs"):
            d.t[t] = []
    d.refused, d.fail, d.before_settle, d.ticks, d.reads, d.posts = [], {}, None, 0, [], []
    real = {n: getattr(d, n) for n in ("get", "post", "patch", "delete")}

    def failing(verb, path):
        want = d.fail.get(verb)
        return bool(want) and path.startswith(want)

    def absent(path, body=None):
        """Before step 2's file: what it adds isn't there to name."""
        if d.limits:
            return False
        names = path + " " + " ".join(k for b in (body if isinstance(body, list) else [body or {}]) for k in b)
        if STEP2_NEW.search(names):
            d.refused.append("absent: step 2")
            return True
        return False

    def get(path, **k):
        d.reads.append(path)
        sb_clients._LAST.error = None
        return None if failing("get", path) or absent(path) or _meet_absent(d, path) else real["get"](path, **k)

    def post(path, body, prefer=None, **k):
        d.posts.append((path.split("?")[0], bool(k.get("redact"))))
        sb_clients._LAST.error = None
        if failing("post", path) or absent(path, body) or _meet_absent(d, path, body):
            return None
        if d.meetings and path.lstrip("/").split("?")[0] in _TABLES_WRITTEN:
            return _meet_post(d, path, body, prefer)
        if path.startswith("/rpc/church_away_settle_excepted"):
            d.rpcs.append(dict(body))
            return settle_excepted(d, body)
        if path.startswith("/rpc/church_away_settle"):
            d.rpcs.append(dict(body))
            return settle(d, body)
        if path.startswith("/church_schedule_people"):
            return _listed(d, body)
        if path.startswith("/church_schedule_settings"):
            if not 0 <= body.get("notice_days", 14) <= 90:
                d.refused.append("check: notice_days")
                return None
            if _setting(d, body):
                return None
            if d.limits and not any(r.get("business_id") == body.get("business_id")
                                    for r in d.t["church_schedule_settings"]):
                # A new row: the column defaults.
                body = {"notice_days": 14, "leaders_limit": None, "office_limit": None, "service_weekdays": None,
                        **body}
        if path.startswith("/church_schedule_department_limits"):
            return _department_limit(d, body, prefer)
        if path.startswith("/church_protected_days"):
            return _protected(d, body, prefer)
        if path.startswith("/church_away_pairs"):
            return _pair(d, body)
        if path.startswith("/church_away_asks"):
            body = _ask_row(d, body)
            if body is None:
                return None
            d.ticks += 1
            body = dict(body, created_at=(NOW + timedelta(seconds=d.ticks)).isoformat())
        if path.startswith("/church_away_commitments"):
            body = _commitment(d, body)
            if body is None:
                return None
            d.ticks += 1
            body = dict(body, created_at=(NOW + timedelta(seconds=d.ticks)).isoformat())
        return real["post"](path, body, prefer, **k)

    def patch(path, body, **k):
        """An update. On an ask, the table's checks are run on the row as it
        would stand after: a write the database would refuse changes
        nothing and answers None."""
        sb_clients._LAST.error = None
        if failing("patch", path) or absent(path, body) or _meet_absent(d, path, body):
            return None
        if d.meetings and path.lstrip("/").split("?")[0] in _TABLES_WRITTEN:
            return _meet_patch(d, path, body)
        if path.startswith("/church_away_pairs"):
            table, filters, _limit = d._parse(path)
            for r in d.t[table]:
                if d._match(r, filters):
                    why = _pair_wrong(d, {**r, **body}, old=r)
                    if why:
                        d.refused.append(why)
                        return None
        if path.startswith("/church_away_asks"):
            table, filters, _limit = d._parse(path)
            for r in d.t[table]:
                if not d._match(r, filters):
                    continue
                after = {**r, **body}
                why = None
                if not set(after.get("flags") or []) <= FLAGS:
                    why = "check: flags"
                elif after.get("to_user_id") and after.get("to_contact_id"):
                    why = "check: church_away_asks_to_one"
                elif d.limits and _excepted_wrong(after):
                    why = "check: church_away_asks_excepted"
                if why:
                    d.refused.append(why)
                    return None
        return real["patch"](path, body, **k)

    def delete(path, **k):
        sb_clients._LAST.error = None
        if failing("delete", path) or absent(path) or _meet_absent(d, path):
            return False
        if d.meetings and path.lstrip("/").split("?")[0] in _TABLES_WRITTEN:
            return _meet_delete(d, path)
        return real["delete"](path, **k)

    for name, fn in (("get", get), ("post", post), ("patch", patch), ("delete", delete)):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", fn)
        setattr(d, name, fn)
    for b in d.t["businesses"]:                                  # the church's clock (church_work_checks.church_zone)
        tz = (b.get("settings") or {}).get("timezone")
        if tz:
            b["settings"] = {**b["settings"], "availability": {"timezone": tz}}
    monkeypatch.setattr(cs, "_now", lambda: NOW)
    monkeypatch.setattr(cs, "_FORCE", True)
    monkeypatch.setattr(csl, "_FORCE", bool(limits))
    monkeypatch.setattr(cs, "_KEPT", {})
    monkeypatch.setattr(cs, "_WAITING", {})
    monkeypatch.setattr(cs, "_OPEN", {})
    monkeypatch.setattr(cs, "_LAST", {})
    # What a write hands on to be told (church_schedule._after) waits here, as
    # it waits for its own thread in production: never run inside the write.
    import member_push
    d.later = []
    monkeypatch.setattr(member_push, "_later", lambda fn, *a, **k: d.later.append(lambda: fn(*a, **k)))
    # Meetings & minutes (step 3): the board's switch open, ours as asked, the
    # tables there exactly when meetings=True, the board's clock the church's.
    import church_board as cb
    import church_meetings as cmt
    from zoneinfo import ZoneInfo
    monkeypatch.setenv("CHURCH_BOARD", "on")
    monkeypatch.setenv("CHURCH_MEETINGS", meetings_mode)
    monkeypatch.setattr(cmt, "_FORCE", bool(meetings))
    monkeypatch.setattr(cmt, "_now", lambda: NOW)
    monkeypatch.setattr(cb, "_now", lambda: NOW)
    zones = {b["id"]: (b.get("settings") or {}).get("timezone") or "America/Detroit" for b in d.t["businesses"]}
    monkeypatch.setattr(cb, "_tz", lambda biz: ZoneInfo(zones.get(str(biz), "America/Detroit")))
    monkeypatch.setattr(cb, "owner_email", lambda uid: c3.OWNER_EMAIL.get(str(uid), ""))
    d.sent = []
    monkeypatch.setattr(cb, "deliver", lambda biz, to, name, subject, text, key, **kw: d.sent.append(
        {"to": to, "name": name, "subject": subject, "text": text, "key": key, **kw}))
    return d


def later(d):
    """Run what the writes handed on, oldest first, as member_push._later's
    thread does (a notice that fails is dropped, never raised). Answers with
    how many ran."""
    ran = 0
    while d.later:
        fn = d.later.pop(0)
        ran += 1
        try:
            fn()
        except Exception:  # noqa: BLE001
            d.dropped = getattr(d, "dropped", 0) + 1
    return ran


def seat(d, biz, handle, role="member", tie=True):
    """A login for one of the church's people who has none (a leader signs
    in to the office app on a Member seat), tied to their own record."""
    c = next(x for x in d.t["contacts"] if x["id"] == d.who[biz][handle])
    u = f"{c3.FOUR.index(biz) + 1}e000000-0000-4000-8000-{len(d.t['business_users']):012d}"
    d.t["business_users"].append({"business_id": biz, "user_id": u, "role": role, "invited_email": c["email"].lower(),
                                  "lane": None, "areas": None, "contact_id": c["id"] if tie else None, "name": c["name"],
                                  "status": "active"})
    d.who[biz][handle + "@"] = u
    d.label[u] = c["name"].split()[0]
    return u


def client(d):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import church_schedule_repeats as crep
    a = FastAPI()
    a.include_router(cs.router)
    a.include_router(csl.router)
    a.include_router(crep.router)
    who = {"id": None, "email": None}
    a.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
    c = TestClient(a)
    c.who, c.db = who, d
    return c


def meetings_client(d):
    """The board's routes and the meetings' (church_board, church_meetings),
    signed in as as_() says, through require_user as production does."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import church_board as cb
    import church_meetings as cmt
    from auth_supabase import AuthedUser, require_user
    a = FastAPI()
    a.include_router(cb.router)
    a.include_router(cmt.router)
    who = {"id": None, "email": None}
    a.dependency_overrides[require_user] = lambda: AuthedUser(id=who["id"], email=who["email"], role="authenticated")
    c = TestClient(a)
    c.who, c.db = who, d
    return c


def uid(d, biz, handle):
    return c3.church(d, biz)["owner_id"] if handle == "owner" else d.who[biz][handle + "@"]


def as_(app, biz, handle):
    u = uid(app.db, biz, handle)
    s = next((s for s in app.db.t["business_users"] if s["user_id"] == u and s["business_id"] == biz), None)
    app.who.update(id=u, email=s["invited_email"] if s else c3.OWNER_EMAIL[u])
    return u


__all__ = ["NOW", "TODAY", "LOVE_CITY", "NEW_HOPE", "as_", "build", "client", "day", "later", "meetings_client",
           "seat", "settle", "settle_excepted", "uid"]

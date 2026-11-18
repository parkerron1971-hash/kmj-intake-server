"""The leaders schedule's tables on the four test churches (church_three), for
test_church_schedule_roster.py and test_church_schedule.py.

    db = build(monkeypatch)        church_three.build, plus the schedule's
                                   four tables and serve_away, the switch on,
                                   the tables "there" (church_schedule._FORCE)
    db = build(monkeypatch, limits=True)
                                   step 2's file applied too (see below)
    app = client(db)               the real routers; as_(app, church, handle)
                                   signs a login in

The tables behave as supabase/APPLY-2026-11-19-church-schedule.sql says (the
PGlite check, church_schedule_db.mjs, runs the real file): the defaults, the
checks, the same-church triggers, one waiting ask for the same days
(church_away_asks_one_open), one row a person on the lists, and
church_away_settle exactly as the function is written, `changed: false`
included. A write the database would refuse answers None, as sb_clients does,
and `db.refused` keeps why.

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
(ordered, one row a pair, both people the church's own), `excepted` and
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


def _pair(d, b):
    """church_away_pairs: the smaller id first, two of the church's own
    people, one row a pair, a note of 140 at most."""
    a, z = str(b.get("a_contact_id") or ""), str(b.get("b_contact_id") or "")
    if not (_mine(d, "contacts", b.get("business_id"), a) and _mine(d, "contacts", b.get("business_id"), z)) or a == z:
        d.refused.append("trigger: A pair is two people in this church")
        return None
    if not a.lower() < z.lower():
        d.refused.append("check: church_away_pairs_ordered")
        return None
    if b.get("note") is not None and len(b["note"]) > 140:
        d.refused.append("check: note")
        return None
    if any(r["business_id"] == b["business_id"] and r["a_contact_id"] == a and r["b_contact_id"] == z
           for r in d.t["church_away_pairs"]):
        d.refused.append("unique: church_away_pairs_one")
        return None
    row = {"id": str(uuid.uuid4()), "note": None, "created_by": None, "created_at": NOW.isoformat(), **b}
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


def build(monkeypatch, *, mode: str = "on", limits: bool = False, **kw):
    monkeypatch.setenv("CHURCH_SCHEDULE", mode)
    d = c3.build(monkeypatch, **kw)
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
        return None if failing("get", path) or absent(path) else real["get"](path, **k)

    def post(path, body, prefer=None, **k):
        d.posts.append((path.split("?")[0], bool(k.get("redact"))))
        if failing("post", path) or absent(path, body):
            return None
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
        return real["post"](path, body, prefer, **k)

    def patch(path, body, **k):
        """An update. On an ask, the table's checks are run on the row as it
        would stand after: a write the database would refuse changes
        nothing and answers None."""
        if failing("patch", path) or absent(path, body):
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
        return False if failing("delete", path) or absent(path) else real["delete"](path, **k)

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
    a = FastAPI()
    a.include_router(cs.router)
    a.include_router(csl.router)
    who = {"id": None, "email": None}
    a.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
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


__all__ = ["NOW", "TODAY", "LOVE_CITY", "NEW_HOPE", "as_", "build", "client", "day", "later", "seat", "settle",
           "settle_excepted", "uid"]

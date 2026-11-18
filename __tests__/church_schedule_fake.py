"""The leaders schedule's tables on the four test churches (church_three), for
test_church_schedule_roster.py and test_church_schedule.py.

    db = build(monkeypatch)        church_three.build, plus the schedule's
                                   four tables and serve_away, the switch on,
                                   the tables "there" (church_schedule._FORCE)
    app = client(db)               the real router; as_(app, church, handle)
                                   signs a login in

The tables behave as supabase/APPLY-2026-11-19-church-schedule.sql says (the
PGlite check, church_schedule_db.mjs, runs the real file): the defaults, the
checks, the same-church triggers, one waiting ask for the same days
(church_away_asks_one_open), one row a person on the lists, and
church_away_settle exactly as the function is written, `changed: false`
included. A write the database would refuse answers None, as sb_clients does,
and `db.refused` keeps why.

    db.fail = {"post": "/church_away_asks", ...}   that write (or read) fails
    db.before_settle = fn                           runs just before the
                                                    function locks the row: the
                                                    other answer landing first
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

import church_schedule as cs  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_three import LOVE_CITY, NEW_HOPE  # noqa: E402

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)      # Wednesday, 10 AM in Detroit
TODAY = date(2026, 11, 18)
KINDS = ("time_off", "commitment", "cant")
FLAGS = {"short_notice", "over_limit", "protected_day", "pair", "serving"}


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
           "told_at": None, "answer_told_at": None, "nudged_at": None, **b}
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
    if why:
        d.refused.append(why)
        return None
    return row


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


def build(monkeypatch, *, mode: str = "on", **kw):
    monkeypatch.setenv("CHURCH_SCHEDULE", mode)
    d = c3.build(monkeypatch, **kw)
    for t in ("church_schedule_settings", "church_schedule_people", "church_away_asks", "church_away_commitments",
              "serve_away"):
        d.t[t] = []
    d.refused, d.fail, d.before_settle, d.ticks, d.reads = [], {}, None, 0, []
    real = {n: getattr(d, n) for n in ("get", "post", "patch", "delete")}

    def failing(verb, path):
        want = d.fail.get(verb)
        return bool(want) and path.startswith(want)

    def get(path, **k):
        d.reads.append(path)
        return None if failing("get", path) else real["get"](path, **k)

    def post(path, body, prefer=None, **k):
        if failing("post", path):
            return None
        if path.startswith("/rpc/church_away_settle"):
            d.rpcs.append(dict(body))
            return settle(d, body)
        if path.startswith("/church_schedule_people"):
            return _listed(d, body)
        if path.startswith("/church_schedule_settings") and not 0 <= body.get("notice_days", 14) <= 90:
            d.refused.append("check: notice_days")
            return None
        if path.startswith("/church_away_asks"):
            body = _ask_row(d, body)
            if body is None:
                return None
            d.ticks += 1
            body = dict(body, created_at=(NOW + timedelta(seconds=d.ticks)).isoformat())
        return real["post"](path, body, prefer, **k)

    def delete(path, **k):
        return False if failing("delete", path) else real["delete"](path, **k)

    for name, fn in (("get", get), ("post", post), ("delete", delete)):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", fn)
        setattr(d, name, fn)
    for b in d.t["businesses"]:                                  # the church's clock (church_work_checks.church_zone)
        tz = (b.get("settings") or {}).get("timezone")
        if tz:
            b["settings"] = {**b["settings"], "availability": {"timezone": tz}}
    monkeypatch.setattr(cs, "_now", lambda: NOW)
    monkeypatch.setattr(cs, "_FORCE", True)
    monkeypatch.setattr(cs, "_KEPT", {})
    return d


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


__all__ = ["NOW", "TODAY", "LOVE_CITY", "NEW_HOPE", "as_", "build", "client", "day", "seat", "settle", "uid"]

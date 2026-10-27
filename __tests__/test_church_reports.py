"""The Reports pack (church_reports.py). Kevin 2026-10-27, on the Church
Office Prototypes ("Reports pack" tab): "lets go with your list". One page
with the year's numbers a church is asked for, a printed annual report, and
a CSV for the denomination.

Pins:
  * each number's arithmetic on a made-up church: attendance (headcount or
    names, whichever is more; services nobody counted left out), members on
    January 1 rewound through logged status changes, the register's counts,
    first-time guests once each, groups and the share of members in one,
    serving hours, giving less refunds with funds and the budget, help given
    and families helped, prayer & care requests, events and their sign-ups
  * giving is the owner's, admins' and accountant's: anyone else gets "kept
    with the treasurer", and no giving table is even read for them
  * no name, no story and no person's id in any care or giving number
  * another church's rows never count, and its reports are unreachable
  * reads past PostgREST's 1000-row cap are paged, never cut short
  * the switch, and who sees the page (the Office; funerals People & care's)
  * a number that can't be known is "—" with its reason, never a guess
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import datetime, timezone
from fnmatch import fnmatchcase
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
import church_reports as rp  # noqa: E402
import church_serving  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB, _cmp  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SALON = "33333333-3333-4333-8333-333333333333"
NAMES = ("owner", "admin", "clerk", "carer", "singer", "books", "stranger", "other_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
T0 = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
NY = ZoneInfo("America/New_York")

M1, M2, M3, M4, M5 = (f"cccccccc-0000-4000-8000-00000000000{i}" for i in range(1, 6))
G1, G2, K1 = "cccccccc-0000-4000-8000-000000000011", "cccccccc-0000-4000-8000-000000000012", \
    "cccccccc-0000-4000-8000-000000000013"
GONE = "cccccccc-0000-4000-8000-000000000099"
THEIRS = "cccccccc-0000-4000-8000-000000000077"
MOD, THEIR_MOD = "eeeeeeee-0000-4000-8000-000000000001", "eeeeeeee-0000-4000-8000-000000000002"
S_JAN4, S_JAN11, S_FEB1, S_OCT3, S_OCT25, S_DEC28 = (f"ffffffff-0000-4000-8000-00000000000{i}" for i in range(1, 7))
FEST, STUDY, CONCERT, UNDATED = (f"ffffffff-0000-4000-8000-00000000001{i}" for i in range(1, 5))
THEIR_SVC = "ffffffff-0000-4000-8000-000000000099"
R1, R2, R3, R_OLD = (f"aaaaaaaa-0000-4000-8000-00000000000{i}" for i in range(1, 5))
STORY = "Our light bill is past due and my mother is sick"
PRAYER = "Please pray for my brother in the hospital"


class ReportsDB(FakeDB):
    """PostgREST as the reports read it: select lists with aliases and JSON
    paths (col->>key), JSON-path filters and ordering, `like` with *, order,
    offset and limit, and the server's cap of 1000 rows a read whatever the
    limit asks. A table in `missing` answers like one before its migration."""

    CAP = 1000

    def __init__(self, **tables):
        super().__init__(**tables)
        self.missing = set()
        self.reads = []

    @staticmethod
    def _path(row, expr):
        if "->>" in expr:
            col, key = expr.split("->>", 1)
            v = row.get(col)
            v = v.get(key) if isinstance(v, dict) else None
            return None if v is None else (v if isinstance(v, str) else json.dumps(v))
        if "->" in expr:
            col, key = expr.split("->", 1)
            v = row.get(col)
            return v.get(key) if isinstance(v, dict) else None
        return row.get(expr)

    def get(self, path, **_):
        table, _, qs = path.lstrip("/").partition("?")
        if table in self.missing:
            return None
        self.reads.append(path)
        select, order, offset, limit, filters = None, None, 0, None, []
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            v = unquote(v)
            if k == "select":
                select = v
            elif k == "order":
                order = v
            elif k == "offset":
                offset = int(v)
            elif k == "limit":
                limit = int(v)
            elif k == "or":
                raise AssertionError("the reports never read with or=")
            else:
                op, _, val = v.partition(".")
                filters.append((k, op, val))
        rows = []
        for r in self.t.get(table, []):
            ok = True
            for col, op, val in filters:
                v = self._path(r, col)
                if op == "like":
                    ok = v is not None and fnmatchcase(str(v), val)
                else:
                    ok = _cmp({col: v}, col, op, val)
                if not ok:
                    break
            if ok:
                rows.append(dict(r))
        for spec in reversed(order.split(",") if order else []):
            col, _, way = spec.rpartition(".")
            if way not in ("asc", "desc"):
                col, way = spec, "asc"
            rows.sort(key=lambda r: str(self._path(r, col) or ""), reverse=way == "desc")
        rows = rows[offset:]
        rows = rows[:min(limit or self.CAP, self.CAP)]
        if select and select != "*":
            out = []
            for r in rows:
                o = {}
                for item in select.split(","):
                    alias, _, expr = item.rpartition(":")
                    o[alias or expr.split("->")[0]] = self._path(r, expr)
                out.append(o)
            rows = out
        return rows


def _svc(eid, day, title="Sunday Worship", biz=BIZ, mod=MOD, **data):
    return {"id": eid, "business_id": biz, "module_id": mod, "status": "active",
            "data": {"title": title, "date": day, "signups": [], **data}}


def _att(entry, n, biz=BIZ, first=(), day="2026-01-04"):
    """`n` people checked in by name; `first` = [(contact_id or None, name)] of them first-timers."""
    out = []
    for i in range(n):
        ft = first[i] if i < len(first) else None
        out.append({"id": f"{entry}-{i:05d}", "business_id": biz, "entry_id": entry,
                    "contact_id": ft[0] if ft else None, "name": ft[1] if ft else f"Person {i}",
                    "first_time": bool(ft), "checked_in_at": f"{day}T15:{i % 60:02d}:00+00:00"})
    return out


def _gift(i, total, paid_at, contact=None, fund=None, refund=0, status="paid", gift=True, biz=BIZ):
    return {"id": f"99999999-0000-4000-8000-{i:012d}", "business_id": biz, "is_gift": gift, "status": status,
            "total": total, "refund_amount_cents": refund, "gift_fund": fund, "category": None,
            "contact_id": contact, "paid_at": paid_at, "notes": "Thank you Pastor!"}


@pytest.fixture
def db(monkeypatch):
    rp._CACHE.clear()
    seats = (("admin", "admin"), ("clerk", "member"), ("carer", "member"), ("singer", "member"), ("books", "member"))
    contact = lambda cid, name, status, made, **kw: {"id": cid, "business_id": BIZ, "name": name,  # noqa: E731
                                                      "email": f"{name.split()[0].lower()}@example.com",
                                                      "status": status, "created_at": made, "metadata": {}, **kw}
    fake = ReportsDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"],
                     "created_at": "2024-03-01T12:00:00+00:00",
                     "settings": {"brand_kit": {"colors": {"primary": "#1F3A5F", "secondary": "#C9A227"}}}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"],
                     "created_at": "2024-01-01T00:00:00+00:00", "settings": {}},
                    {"id": SALON, "name": "Shear Joy", "type": "salon", "owner_id": ID["owner"],
                     "created_at": "2024-01-01T00:00:00+00:00", "settings": {}}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active",
                         "invited_email": f"{n}@lovecity.org"} for n, r in seats],
        business_collaborators=[{"id": "col-1", "business_id": BIZ, "user_id": ID["books"], "status": "active",
                                 "role": "accountant"}],
        contacts=[
            contact(M1, "Dana Johnson", "active", "2024-05-01T12:00:00+00:00"),
            contact(M2, "Andre Cole", "vip", "2025-01-01T12:00:00+00:00"),
            contact(M3, "Mia Ellis", "active", "2026-02-01T12:00:00+00:00"),
            contact(M4, "Jordan Ellis", "active", "2025-06-01T12:00:00+00:00"),
            contact(M5, "Evelyn Shaw", "inactive", "2024-06-01T12:00:00+00:00"),
            contact(G1, "Guest One", "lead", "2026-01-04T12:00:00+00:00"),
            contact(G2, "Guest Two", "lead", "2025-12-28T12:00:00+00:00"),
            contact(K1, "Kid Desk Parent", "lead", "2026-03-08T12:00:00+00:00"),
            {"id": THEIRS, "business_id": OTHER, "name": "Grace Member", "status": "active",
             "created_at": "2024-01-01T00:00:00+00:00", "metadata": {}},
        ],
        events=[
            # M4 became a member in April; M5 stopped being one in May.
            {"id": "ev-1", "business_id": BIZ, "contact_id": M4, "event_type": "contact_status_changed",
             "data": {"from": "lead", "to": "active"}, "created_at": "2026-04-01T12:00:00+00:00"},
            {"id": "ev-2", "business_id": BIZ, "contact_id": M5, "event_type": "contact_status_changed",
             "data": {"from": "active", "to": "inactive"}, "created_at": "2026-05-01T12:00:00+00:00"},
            {"id": "ev-3", "business_id": BIZ, "contact_id": M5, "event_type": "contact_status_changed",
             "data": {"from": "inactive", "to": "inactive"}, "created_at": "2026-06-01T12:00:00+00:00"},
            # Another church's log never rewinds this one's people.
            {"id": "ev-4", "business_id": OTHER, "contact_id": M1, "event_type": "contact_status_changed",
             "data": {"from": "lead", "to": "active"}, "created_at": "2026-03-01T12:00:00+00:00"},
            {"id": "ev-5", "business_id": BIZ, "contact_id": M1, "event_type": "note_added",
             "data": {"from": "lead"}, "created_at": "2026-03-01T12:00:00+00:00"},
        ],
        custom_modules=[
            {"id": MOD, "business_id": BIZ, "archetype": "event_roster", "is_active": True, "name": "Services & Events",
             "archetype_params": {}, "created_at": "2024-03-01T12:00:00+00:00"},
            {"id": THEIR_MOD, "business_id": OTHER, "archetype": "event_roster", "is_active": True, "name": "Events",
             "archetype_params": {}, "created_at": "2024-03-01T12:00:00+00:00"},
        ],
        module_entries=[
            _svc(S_JAN4, "2026-01-04T11:00"), _svc(S_JAN11, "2026-01-11", "Sunday Worship (Baptism Sunday)"),
            _svc(S_FEB1, "2026-02-01"),
            _svc(S_OCT3, "2026-10-03T18:00", "Saturday Night Service", type="service"),
            _svc(S_OCT25, "2026-10-25"), _svc(S_DEC28, "2025-12-28"),
            _svc(FEST, "2026-10-10", "Fall Festival", type="event",
                 signups=[{"name": "A", "status": "yes"}, {"name": "B"}, {"name": "C", "status": "maybe"}]),
            _svc(STUDY, "2026-10-14T19:00", "Wednesday Bible Study"),
            _svc(CONCERT, "2026-12-20", "Christmas Concert", type="event", signups=[{"name": "D", "status": "yes"}]),
            {"id": UNDATED, "business_id": BIZ, "module_id": MOD, "status": "active", "data": {"title": "Someday"}},
            _svc(THEIR_SVC, "2026-01-04", biz=OTHER, mod=THEIR_MOD),
        ],
        attendance=(
            _att(S_JAN4, 120, first=[(G1, "Guest One")], day="2026-01-04")
            + _att(S_JAN11, 50, first=[(G2, "Guest Two")], day="2026-01-11")
            + _att(S_OCT25, 90, first=[(None, "Pat Visitor"), (None, " pat   VISITOR "), (G1, "Guest One")],
                   day="2026-10-25")
            + _att(S_DEC28, 70, first=[(G2, "Guest Two")], day="2025-12-28")
            + _att(THEIR_SVC, 400, biz=OTHER, first=[(THEIRS, "Grace Member")])
        ),
        attendance_headcounts=[
            {"id": "h1", "business_id": BIZ, "entry_id": S_JAN11, "area": "Sanctuary", "count": 110},
            {"id": "h2", "business_id": BIZ, "entry_id": S_JAN11, "area": "Kids", "count": 20},
            {"id": "h3", "business_id": BIZ, "entry_id": S_OCT3, "area": "Sanctuary", "count": 40},
            {"id": "h4", "business_id": BIZ, "entry_id": S_JAN4, "area": "Sanctuary", "count": 100},
            {"id": "h5", "business_id": OTHER, "entry_id": THEIR_SVC, "area": "Sanctuary", "count": 900},
        ],
        child_checkins=[{"id": f"k{i}", "business_id": BIZ, "entry_id": S_JAN4} for i in range(12)]
        + [{"id": f"k{i + 20}", "business_id": BIZ, "entry_id": S_OCT25} for i in range(9)],
        church_follow_ups=[
            {"id": "fu1", "business_id": BIZ, "contact_id": K1, "source_event": "first-visit:h:hh1",
             "created_at": "2026-03-08T16:00:00+00:00"},
            {"id": "fu2", "business_id": BIZ, "contact_id": G1, "source_event": "first-visit:c:" + G1,
             "created_at": "2026-01-05T16:00:00+00:00"},
            {"id": "fu3", "business_id": BIZ, "contact_id": M3, "source_event": "card:connect",
             "created_at": "2026-04-05T16:00:00+00:00"},
            # Guest Two's family came through the kids desk in February, but
            # their first visit was last December: not this year's guest.
            {"id": "fu4", "business_id": BIZ, "contact_id": G2, "source_event": "first-visit:h:hh2",
             "created_at": "2026-02-15T16:00:00+00:00"},
        ],
        groups=[
            {"id": "g1", "business_id": BIZ, "kind": "small_group", "active": True, "name": "Tuesday Women"},
            {"id": "g2", "business_id": BIZ, "kind": "class", "active": True, "name": "Membership class"},
            {"id": "g3", "business_id": BIZ, "kind": "team", "active": True, "name": "Greeters"},
            {"id": "g4", "business_id": BIZ, "kind": "small_group", "active": False, "name": "Old group"},
            {"id": "g9", "business_id": OTHER, "kind": "small_group", "active": True, "name": "Theirs"},
        ],
        group_members=[
            {"group_id": "g1", "business_id": BIZ, "contact_id": M1}, {"group_id": "g1", "business_id": BIZ, "contact_id": M2},
            {"group_id": "g1", "business_id": BIZ, "contact_id": G1}, {"group_id": "g2", "business_id": BIZ, "contact_id": M1},
            {"group_id": "g2", "business_id": BIZ, "contact_id": M3}, {"group_id": "g3", "business_id": BIZ, "contact_id": M4},
            {"group_id": "g4", "business_id": BIZ, "contact_id": M4},
        ],
        church_register_entries=[
            {"id": f"re{i}", "business_id": b, "kind": k, "membership": ms, "status": st, "event_on": on,
             "removed_at": rm, "people": [{"role": "person", "name": "Someone Named"}]}
            for i, (b, k, ms, st, on, rm) in enumerate([
                (BIZ, "baptism", None, "done", "2026-04-05", None), (BIZ, "baptism", None, "done", "2026-10-18", None),
                (BIZ, "dedication", None, "done", "2026-09-27", None), (BIZ, "wedding", None, "done", "2026-10-10", None),
                (BIZ, "funeral", None, "done", "2026-09-12", None),
                (BIZ, "membership", "joined", "done", "2026-04-05", None),
                (BIZ, "membership", "joined", "done", "2026-09-06", None),
                (BIZ, "membership", "transferred_in", "done", "2026-08-23", None),
                (BIZ, "membership", "transferred_out", "done", "2026-07-01", None),
                (BIZ, "membership", "removed", "done", "2026-05-03", None),
                (BIZ, "baptism", None, "done", "2026-06-07", "2026-06-08T00:00:00+00:00"),
                (BIZ, "baptism", None, "planned", "2026-11-15", None),
                (BIZ, "baptism", None, "done", "2025-12-21", None),
                (OTHER, "baptism", None, "done", "2026-05-05", None),
            ])],
        invoices=[
            _gift(1, 100, "2026-01-04T15:00:00+00:00", M1, "Tithes"),
            _gift(2, 250, "2026-02-01T15:00:00+00:00", M1, "Building Fund"),
            _gift(3, 50, "2026-10-04T15:00:00+00:00", M2, "Building"),
            _gift(4, 40, "2026-10-04T16:00:00+00:00", None, None),
            _gift(5, 75, "2026-05-04T15:00:00+00:00", M2, "Missions", refund=7500),
            _gift(6, 30, "2026-03-01T15:00:00+00:00", M3, "Missions", refund=1000),
            _gift(7, 500, "2026-03-01T15:00:00+00:00", M1, None, status="open"),
            _gift(8, 900, "2026-03-01T15:00:00+00:00", M1, None, gift=False),
            _gift(9, 60, "2025-12-31T23:00:00+00:00", M1, None),
            _gift(10, 5000, "2026-03-01T15:00:00+00:00", THEIRS, None, biz=OTHER),
        ],
        business_budgets=[{"id": f"bb{m}", "business_id": BIZ, "year": 2026, "month": m, "category": "revenue",
                           "amount": 50} for m in range(1, 13)]
        + [{"id": "bb-op", "business_id": BIZ, "year": 2026, "month": 1, "category": "operating", "amount": 999},
           {"id": "bb-25", "business_id": BIZ, "year": 2025, "month": 1, "category": "revenue", "amount": 75}],
        church_check_settings=[{"business_id": BIZ, "lines": [{"name": "Kids", "budget_cents": 200000},
                                                              {"name": "Youth", "budget_cents": 0}]}],
        business_expenses=[
            {"id": "x1", "business_id": BIZ, "date": "2026-03-01", "amount": 121.0, "subcategory": "Kids"},
            {"id": "x2", "business_id": BIZ, "date": "2026-09-01", "amount": 10, "subcategory": "kids"},
            {"id": "x3", "business_id": BIZ, "date": "2026-09-01", "amount": 5, "subcategory": "Youth"},
            {"id": "x4", "business_id": BIZ, "date": "2025-09-01", "amount": 70, "subcategory": "Kids"},
        ],
        church_help_requests=[
            {"id": R1, "business_id": BIZ, "contact_id": M1, "name": "Dana Johnson", "need": "bill", "notes": STORY},
            {"id": R2, "business_id": BIZ, "contact_id": None, "name": "A neighbor", "need": "food", "notes": STORY},
            {"id": R3, "business_id": BIZ, "contact_id": M1, "name": "Dana Johnson", "need": "food", "notes": STORY},
            {"id": R_OLD, "business_id": BIZ, "contact_id": M2, "name": "Andre Cole", "need": "ride", "notes": STORY},
        ],
        church_help_given=[
            {"id": "hg1", "business_id": BIZ, "request_id": R1, "amount_cents": 15000, "given_on": "2026-02-10",
             "payee": "Cleveland Electric", "note": STORY},
            {"id": "hg2", "business_id": BIZ, "request_id": R2, "amount_cents": 4000, "given_on": "2026-06-01", "note": ""},
            {"id": "hg3", "business_id": BIZ, "request_id": R2, "amount_cents": 2000, "given_on": "2026-06-08", "note": ""},
            {"id": "hg4", "business_id": BIZ, "request_id": R3, "amount_cents": 0, "given_on": "2026-10-01", "note": ""},
            {"id": "hg5", "business_id": BIZ, "request_id": R_OLD, "amount_cents": 3000, "given_on": "2025-11-01"},
        ],
        ministry_care_requests=[
            {"id": "cr1", "business_id": BIZ, "legacy_source": None, "created_at": "2026-02-01T15:00:00+00:00",
             "submission": {"kind": "prayer", "request": PRAYER, "name": "Dana Johnson"}},
            {"id": "cr2", "business_id": BIZ, "legacy_source": None, "created_at": "2026-10-20T15:00:00+00:00",
             "submission": {"kind": "help", "request": STORY}},
            {"id": "cr3", "business_id": BIZ, "legacy_source": None, "created_at": "2026-10-21T15:00:00+00:00",
             "submission": {"kind": "visit", "request": "Visit me"}},
            {"id": "cr4", "business_id": BIZ, "legacy_source": "contact:x", "created_at": "2026-09-29T15:00:00+00:00",
             "submission": {"legacy_metadata": {}}},
            {"id": "cr5", "business_id": BIZ, "legacy_source": None, "created_at": "2025-12-31T15:00:00+00:00",
             "submission": {"kind": "prayer", "request": PRAYER}},
            {"id": "cr6", "business_id": OTHER, "legacy_source": None, "created_at": "2026-03-01T15:00:00+00:00",
             "submission": {"kind": "prayer", "request": PRAYER}},
        ],
        church_event_registrations=[
            {"id": "er1", "business_id": BIZ, "entry_id": FEST, "status": "paid", "seats": 3, "name": "Dana Johnson"},
            {"id": "er2", "business_id": BIZ, "entry_id": FEST, "status": "confirmed", "seats": 1, "name": "Andre Cole"},
            {"id": "er3", "business_id": BIZ, "entry_id": FEST, "status": "cancelled", "seats": 2, "name": "X"},
            {"id": "er4", "business_id": BIZ, "entry_id": FEST, "status": "refunded", "seats": 1, "name": "Y"},
            {"id": "er5", "business_id": BIZ, "entry_id": CONCERT, "status": "paid", "seats": 5, "name": "Z"},
        ],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_REPORTS", "on")
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setattr(rp, "_now", lambda: T0)
    monkeypatch.setattr(rp, "_tz", lambda biz: NY)
    # Who sees what: the clerk and the accountant work the Office, the carer
    # People & care, the singer worship only.
    areas = {ID["clerk"]: ["office"], ID["books"]: ["office"], ID["carer"]: ["people_care"],
             ID["singer"]: ["worship_media"]}
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {"areas": areas.get(uid), "by": "picked"})
    # Serving's arithmetic is church_serving's own (its suite pins it); here
    # its readers answer with credits.
    monkeypatch.setattr(church_serving, "_zone", lambda biz: NY)
    monkeypatch.setattr(church_serving, "_sunday_spans", lambda biz, zone, lo, hi, s: ([
        {"contact_id": M1, "team": "t1", "minutes": 120, "day": "2026-01-04"},
        {"contact_id": M2, "team": "t1", "minutes": 90, "day": "2026-10-04"},
        {"contact_id": GONE, "team": "t1", "minutes": 600, "day": "2026-03-01"},
    ], {}))
    monkeypatch.setattr(church_serving, "_group_credits", lambda biz, lo, hi, s: (
        [{"contact_id": M1, "group": "g1", "minutes": 90, "day": "2026-02-10"}], {}))
    monkeypatch.setattr(church_serving, "_extra_rows", lambda biz: [])
    monkeypatch.setattr(church_serving, "_extra_credits", lambda rows, year: [
        {"contact_id": M3, "minutes": 60, "day": "2026-10-01", "id": "x", "note": "Work day", "by": "Office"}])
    monkeypatch.setattr(church_serving, "_people", lambda biz, ids: {
        i: {"id": i, "name": "Someone"} for i in ids if i != GONE})
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(rp.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def _report(name="owner", biz=BIZ, year=None):
    got = client(name).get(f"/church/reports?business_id={biz}" + (f"&year={year}" if year else ""))
    assert got.status_code == 200, got.text
    return got.json()


def _stats(report, section):
    return {s["key"]: s for s in report["sections"][section]["stats"]}


def _v(report, section, key):
    return _stats(report, section)[key]["value"]


def _every_stat(report):
    for name, sec in report["sections"].items():
        for s in sec.get("stats") or []:
            yield name, s


# ─── The switch, and who sees the page ───────────────────────────────

def test_the_switch(db, monkeypatch):
    def status(name):
        return client(name).get(f"/church/reports/status?business_id={BIZ}").json()["enabled"]
    monkeypatch.setenv("CHURCH_REPORTS", "off")
    assert status("owner") is False
    assert client("owner").get(f"/church/reports?business_id={BIZ}").status_code == 404
    assert client("owner").get(f"/church/reports/export?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_REPORTS", "owner")   # the platform owner alone until a Thursday
    assert status("owner") is True and status("admin") is False
    assert client("admin").get(f"/church/reports?business_id={BIZ}").status_code == 404
    monkeypatch.delenv("CHURCH_REPORTS")            # unset is owner
    assert status("owner") is True and status("admin") is False
    monkeypatch.setenv("CHURCH_REPORTS", "on")
    assert status("admin") is True


def test_status_says_what_each_login_sees(db, monkeypatch):
    def status(name, biz=BIZ):
        return client(name).get(f"/church/reports/status?business_id={biz}")
    assert status("owner").json() == {"enabled": True, "giving": True, "deaths": True, "care": True}
    assert status("admin").json() == {"enabled": True, "giving": True, "deaths": True, "care": True}
    assert status("clerk").json() == {"enabled": True, "giving": False, "deaths": False, "care": False}
    assert status("books").json() == {"enabled": True, "giving": True, "deaths": False, "care": False}, \
        "the accountant sees giving"
    off = {"enabled": False, "giving": False, "deaths": False, "care": False}
    assert status("carer").json() == off, "People & care alone doesn't open the office's reports"
    assert status("singer").json() == off
    assert status("owner", SALON).json() == off, "not a church"
    assert status("stranger").status_code == 404 and status("other_owner").status_code == 404
    for who in ("carer", "singer"):
        assert client(who).get(f"/church/reports?business_id={BIZ}").status_code == 403
    # While Who sees what is off, every login sees the whole church, as before.
    monkeypatch.setenv("CHURCH_AREAS", "off")
    assert status("carer").json() == {"enabled": True, "giving": False, "deaths": True, "care": True}
    assert status("singer").json()["enabled"] is True


def test_a_view_that_couldnt_be_read_is_never_everything(db, monkeypatch):
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: None)
    assert client("clerk").get(f"/church/reports?business_id={BIZ}").status_code == 503
    assert client("clerk").get(f"/church/reports/status?business_id={BIZ}").json()["enabled"] is False
    assert client("owner").get(f"/church/reports?business_id={BIZ}").status_code == 200


def test_another_church_is_unreachable_and_never_counted(db):
    for who in ("other_owner", "stranger"):
        assert client(who).get(f"/church/reports?business_id={BIZ}").status_code == 404
        assert client(who).get(f"/church/reports/export?business_id={BIZ}").status_code == 404
    assert client("owner").get(f"/church/reports?business_id={OTHER}").status_code == 404
    assert client("owner").get("/church/reports?business_id=not-an-id").status_code == 400
    r = _report()
    # Grace Chapel's 400 people, 900 headcount, $5,000 gift, baptism, prayer
    # request and member are in the tables, and nowhere in the numbers.
    assert _v(r, "sunday", "attendance_peak") == 130
    assert _v(r, "giving", "giving_total") == 460.0
    assert _v(r, "people", "baptisms") == 2
    assert _v(r, "care", "care_requests") == 3
    assert _v(r, "people", "members_end") == 4
    assert all(f"business_id=eq.{BIZ}" in p for p in db.reads
               if not p.startswith(("/businesses", "/business_users", "/business_collaborators")))


# ─── Each number ─────────────────────────────────────────────────────

def test_sunday_attendance(db):
    r = _report()
    s = r["sections"]["sunday"]
    # Jan 4: 120 named over a headcount of 100; Jan 11: headcount 130 over 50
    # named; Oct 3 (a Saturday, typed a service): headcount 40; Oct 25: 90
    # named. Feb 1 nobody counted: left out. Dec 28 is last year's; the
    # festival, the Wednesday study and the concert are events.
    assert _v(r, "sunday", "attendance_avg") == 95          # (120 + 130 + 40 + 90) / 4
    assert _v(r, "sunday", "services_counted") == 4
    peak = _stats(r, "sunday")["attendance_peak"]
    assert peak["value"] == 130 and peak["note"] == "Sunday Worship (Baptism Sunday), Jan 11"
    assert _v(r, "sunday", "kids_avg") == 11                 # (12 + 9) / 2, half up
    months = s["months"]
    assert months[0] == {"avg": 125, "services": 2}
    assert months[1] == {"avg": None, "services": 0}, "a service nobody counted is no month's average"
    assert months[9] == {"avg": 65, "services": 2}
    assert months[10] is None and months[11] is None, "November and December haven't come yet"
    assert [c["total"] for c in s["counts"]] == [120, 130, 40, 90]


def test_people_members_register_and_guests(db):
    # M6 was on the list last year as a visitor and became a member in July.
    db.t["contacts"].append({"id": "cccccccc-0000-4000-8000-000000000006", "business_id": BIZ, "name": "Tyler Green",
                             "status": "active", "created_at": "2025-03-01T12:00:00+00:00", "metadata": {}})
    db.t["events"].append({"id": "ev-6", "business_id": BIZ, "contact_id": "cccccccc-0000-4000-8000-000000000006",
                           "event_type": "contact_status_changed", "data": {"from": "visitor", "to": "active"},
                           "created_at": "2026-07-01T12:00:00+00:00"})
    r = _report()
    p = _stats(r, "people")
    # Today: M1, M2 (VIP), M3, M4 and M6. On January 1: M1, M2, and M5 (who
    # stopped in May); not M4 or M6 (members since April and July), not M3
    # (added in February). Another church's log never rewinds M1.
    assert p["members_end"]["value"] == 5 and p["members_end"]["label"] == "Members today"
    assert p["members_start"]["value"] == 3 and p["members_start"]["label"] == "Members on January 1, 2026"
    # The register: removed, planned, last year's and another church's don't count.
    assert {k: p[k]["value"] for k in ("new_members", "transfers_in", "transfers_out", "baptisms", "dedications",
                                       "weddings", "deaths")} == {
        "new_members": 3, "transfers_in": 1, "transfers_out": 1, "baptisms": 2, "dedications": 1,
        "weddings": 1, "deaths": 1}
    # Guests: Guest One (January, again in October: once), Pat Visitor (one
    # person however the name was typed), the kids desk's family (March).
    # Guest Two's first visit was last December.
    assert p["guests"]["value"] == 3
    assert r["sections"]["people"]["guests_by_month"][:10] == [1, 0, 1, 0, 0, 0, 0, 0, 0, 1]
    assert r["sections"]["people"]["guests_by_month"][10:] == [None, None]


def test_members_on_a_day_before_the_records_reach(db):
    db.t["businesses"][0]["created_at"] = "2026-03-15T12:00:00+00:00"
    p = _stats(_report(), "people")
    assert p["members_start"]["value"] is None
    assert p["members_start"]["reason"].startswith("Love City Church started in the app on March 15, 2026")
    assert p["members_end"]["value"] == 4, "today's count is exact whenever the church started"
    rp._CACHE.clear()
    db.t["businesses"][0]["created_at"] = "2024-03-01T12:00:00+00:00"
    db.t["contacts"][0]["metadata"] = {"imported_at": "2026-10-12T14:00:00+00:00", "imported_from": "Subsplash"}
    p = _stats(_report(), "people")
    assert p["members_start"]["value"] is None
    assert p["members_start"]["reason"] == ("Your people came over from Subsplash on October 12, 2026, "
                                            "so who was a member before then isn't on record.")
    # An import before the day is no reason to doubt it.
    rp._CACHE.clear()
    db.t["contacts"][0]["metadata"] = {"imported_at": "2025-08-01T14:00:00+00:00", "imported_from": "Subsplash"}
    assert _v(_report(), "people", "members_start") == 3


def test_groups_today_and_never_for_a_past_year(db):
    r = _report()
    g = _stats(r, "groups")
    # g1 and g2: the Sunday team and the closed group don't count.
    assert g["groups"]["value"] == 2
    assert g["in_groups"]["value"] == 4                     # M1, M2, M3 and Guest One
    assert g["groups_share"]["value"] == 75                 # M1, M2, M3 of the 4 members
    assert g["groups_share"]["note"] == "3 of 4 members, today"
    assert r["sections"]["groups"]["by_kind"] == [{"kind": "small_group", "label": "Small groups", "count": 1},
                                                  {"kind": "class", "label": "Classes", "count": 1}]
    past = _stats(_report(year=2025), "groups")
    assert all(s["value"] is None and s["reason"].startswith("Groups are kept as they are today") for s in past.values())


def test_serving_hours(db):
    r = _report()
    # M1 120 + 90, M2 90, M3 60: 360 minutes. A record that's gone takes its
    # hours with it, as on the Serving page.
    assert _v(r, "serving", "serving_hours") == 6
    assert _v(r, "serving", "serving_people") == 3
    assert r["sections"]["serving"]["months"][:10] == [2, 2, 0, 0, 0, 0, 0, 0, 0, 3]   # October 2.5 rounds up


def test_giving_less_refunds_with_funds_and_the_budget(db):
    r = _report()
    g = _stats(r, "giving")
    # $100 + $250 + $50 + $40 + ($30 - $10). Fully refunded, unpaid, not a
    # gift, last year's (UTC) and another church's don't count.
    assert g["giving_total"]["value"] == 460.0
    assert g["gifts"]["value"] == 5
    assert g["givers"]["value"] == 3 and g["givers"]["note"] == "plus $40.00 given with no giver on file"
    assert g["designated_total"]["value"] == 320.0         # Building Fund 300, Missions 20
    assert g["fund:Building Fund"]["value"] == 300.0, "Building and Building Fund are one fund"
    assert g["fund:Missions Fund"]["value"] == 20.0
    assert "fund:Tithes" not in g and "fund:General Fund" not in g, "tithes and offerings are the general fund"
    assert g["giving_budget"]["value"] == 600.0
    assert g["giving_vs_budget"]["value"] == 92 and g["giving_vs_budget"]["note"] == "through October"   # 460 / 500
    sec = r["sections"]["giving"]
    assert [f["name"] for f in sec["funds"]] == ["Building Fund", "Tithes", "General Fund", "Missions Fund"]
    assert sec["months"][0] == {"cents": 10000, "budget_cents": 5000}
    assert sec["months"][4] == {"cents": 0, "budget_cents": 5000}, "a fully refunded gift is no gift"
    assert sec["months"][11] is None
    assert sec["ministries"] == [{"name": "Kids", "budget_usd": 2000.0, "spent_usd": 131.0}]


def test_giving_budget_missing_says_so(db):
    db.t["business_budgets"] = []
    g = _stats(_report(), "giving")
    assert g["giving_vs_budget"]["value"] is None
    assert g["giving_vs_budget"]["reason"] == "No giving budget is set for 2026 (Giving › Gifts › Budgets)."
    assert g["giving_total"]["value"] == 460.0


def test_giving_is_kept_with_the_treasurer(db):
    db.reads.clear()
    r = _report("clerk")
    assert r["me"] == {"giving": False, "deaths": False, "care": False}
    assert r["sections"]["giving"] == {"kept": True, "reason": "Kept with the treasurer."}
    money = ("/invoices", "/business_budgets", "/church_check_settings", "/business_expenses")
    assert not [p for p in db.reads if p.startswith(money)], "no giving table is read for them"
    assert "460" not in json.dumps(r)
    text = client("clerk").get(f"/church/reports/export?business_id={BIZ}").text
    assert "Kept with the treasurer." in text and "Total given" not in text and "Designated" not in text
    # The owner's report, read first, is never the clerk's.
    rp._CACHE.clear()
    _report("owner")
    assert _report("clerk")["sections"]["giving"] == {"kept": True, "reason": "Kept with the treasurer."}


def test_funerals_are_the_care_teams(db):
    r = _report("clerk")
    d = _stats(r, "people")["deaths"]
    assert d["value"] is None and d["reason"] == "Kept with the pastors and the care team."
    assert _v(r, "people", "baptisms") == 2


def test_care_is_the_care_teams_even_as_totals(db):
    """Help given and Prayer & care are People & care's on their own pages
    (church_help, private_care): an Office login gets "kept", and nothing
    is read for it."""
    db.reads.clear()
    r = _report("clerk")
    assert r["sections"]["care"] == {"kept": True, "reason": "Kept with the pastors and the care team."}
    assert not [p for p in db.reads if p.startswith(("/church_help_", "/ministry_care_requests"))]
    text = client("clerk").get(f"/church/reports/export?business_id={BIZ}").text
    assert "Kept with the pastors and the care team." in text and "Help given" not in text
    # The pastors and the care team, the owner and admins see it, and so does
    # every login while Who sees what is off.
    assert _v(_report("owner"), "care", "help_given") == 210.0


def test_a_report_with_a_failed_read_is_never_kept(db):
    db.missing |= {"invoices"}
    assert _stats(_report(), "giving")["giving_total"]["value"] is None
    db.missing.clear()
    assert _v(_report(), "giving", "giving_total") == 460.0, "the blip isn't handed to the next reader"
    # A report every read answered is kept: the next read reads nothing.
    db.reads.clear()
    assert _v(_report(), "giving", "giving_total") == 460.0
    assert not [p for p in db.reads if not p.startswith(("/businesses", "/business_users", "/business_collaborators"))]


def test_a_section_that_breaks_is_not_kept_either(db, monkeypatch):
    calls = []

    def flaky(ctx):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("blip")
        return {"stats": [], "months": []}
    monkeypatch.setitem(rp.BUILDERS, "events", flaky)
    assert _report()["sections"]["events"]["failed"] is True
    assert "failed" not in _report()["sections"]["events"]


def test_a_guest_checked_in_by_name_and_from_their_record_is_one(db):
    # Guest One came in January from their record, and the greeter typed
    # their name alone in March: one guest, in January.
    db.t["attendance"] += _att(S_FEB1, 1, first=[(None, "  GUEST one ")], day="2026-03-01")
    r = _report()
    assert _v(r, "people", "guests") == 3
    assert r["sections"]["people"]["guests_by_month"][:3] == [1, 0, 1]
    # A name nobody on the list has stays a guest of its own.
    rp._CACHE.clear()
    db.t["attendance"] += _att(S_OCT3, 1, first=[(None, "Visiting Cousin")], day="2026-03-02")
    assert _v(_report(), "people", "guests") == 4


def test_care_help_and_requests(db):
    r = _report()
    c = _stats(r, "care")
    assert c["help_given"]["value"] == 210.0                # 150 + 40 + 20 + groceries; last year's not
    assert c["help_times"]["value"] == 4
    assert c["families_helped"]["value"] == 2               # Dana (twice), and a neighbor not on the list
    assert c["care_requests"]["value"] == 3                 # not the backfill, not last year's, not theirs
    assert r["sections"]["care"]["by_need"] == [
        {"need": "bill", "label": "Bills", "usd": 150.0, "times": 1},
        {"need": "food", "label": "Food", "usd": 60.0, "times": 3}]
    assert r["sections"]["care"]["months"][:10] == [0, 1, 0, 0, 0, 0, 0, 0, 0, 2]


def test_no_name_no_story_no_person_in_care_or_giving(db):
    for who in ("owner", "clerk", "books"):
        r = _report(who)
        dump = json.dumps({k: r["sections"][k] for k in ("care", "giving", "people")})
        for secret in (STORY, PRAYER, "Dana", "Andre", "Johnson", "A neighbor", "Cleveland Electric", "Thank you Pastor",
                       "Someone Named", "Guest One", "Pat Visitor", M1, M2, M3, R1, R2, "hg1", "cr1"):
            assert secret not in dump, f"{secret!r} in {who}'s report"
        csv_text = client(who).get(f"/church/reports/export?business_id={BIZ}").text
        for secret in (STORY, PRAYER, "Dana", M1, R1):
            assert secret not in csv_text
    # Prayer & care is counted by its day alone: no submission is read.
    assert not [p for p in db.reads if p.startswith("/ministry_care_requests") and "submission" in p]
    assert not [p for p in db.reads if p.startswith("/church_help_") and ("notes" in p or "name" in p or "note" in p)]


def test_events_and_signups(db):
    r = _report()
    e = _stats(r, "events")
    # The festival and the Wednesday study (no type, not a Sunday): the
    # concert hasn't happened. Two yeses (no status is a yes), not the maybe.
    assert e["events_held"]["value"] == 2
    assert e["rsvps"]["value"] == 2
    assert e["paid_signups"]["value"] == 4                  # paid 3 + confirmed 1; not cancelled, refunded, or the concert
    assert e["signups"]["value"] == 6
    assert r["sections"]["events"]["months"][9] == 2


def test_occasion_kinds_follow_the_app():
    from datetime import date
    sunday, wednesday = date(2026, 10, 25), date(2026, 10, 14)
    assert rp.occasion_kind({"type": "service"}, wednesday, None) == "service"
    assert rp.occasion_kind({"type": "Class"}, sunday, None) == "event"
    assert rp.occasion_kind({}, wednesday, "Services") == "service"
    assert rp.occasion_kind({}, sunday, "Workshop") == "event"
    assert rp.occasion_kind({}, sunday, None) == "service"
    assert rp.occasion_kind({}, wednesday, "") == "event"


# ─── Long reads, missing sources, the year ───────────────────────────

def test_reads_past_the_row_cap_are_paged(db):
    db.t["attendance"] = [r for r in db.t["attendance"] if r["entry_id"] != S_OCT25] + _att(S_OCT25, 2500, day="2026-10-25")
    db.t["invoices"] += [_gift(1000 + i, 1, "2026-06-01T15:00:00+00:00", M2, None) for i in range(1500)]
    db.t["contacts"] += [{"id": f"dddddddd-0000-4000-8000-{i:012d}", "business_id": BIZ, "name": f"Member {i}",
                          "status": "active", "created_at": "2025-01-01T00:00:00+00:00", "metadata": {}}
                         for i in range(1200)]
    r = _report()
    assert _stats(r, "sunday")["attendance_peak"]["value"] == 2500
    assert _v(r, "sunday", "attendance_avg") == 698         # (120 + 130 + 40 + 2500) / 4, half up
    assert _v(r, "giving", "giving_total") == 1960.0
    assert _v(r, "giving", "gifts") == 1505
    assert _v(r, "people", "members_end") == 1204
    assert _v(r, "people", "members_start") == 1203
    assert any("offset=1000" in p and p.startswith("/attendance") for p in db.reads)
    assert any("offset=2000" in p and p.startswith("/attendance") for p in db.reads)


def test_a_source_that_isnt_there_says_why(db):
    db.missing |= {"church_register_entries", "church_help_given", "church_event_registrations",
                   "church_check_settings", "child_checkins"}
    r = _report()
    p = _stats(r, "people")
    for k in ("new_members", "baptisms", "weddings", "deaths"):
        assert p[k]["value"] is None
        assert p[k]["reason"] == "The church register isn't set up yet, or couldn't be read just now."
    c = _stats(r, "care")
    assert c["help_given"]["reason"] == "Help requests aren't set up yet, or couldn't be read just now."
    assert c["care_requests"]["value"] == 3, "the rest of the section stands"
    e = _stats(r, "events")
    assert e["events_held"]["value"] == 2 and e["rsvps"]["value"] == 2
    assert e["paid_signups"]["value"] is None and e["signups"]["value"] is None
    assert e["signups"]["reason"].startswith("Paid sign-ups couldn't be counted")
    assert _stats(r, "sunday")["kids_avg"]["reason"] == "Kids check-in couldn't be read just now."
    assert r["sections"]["giving"]["ministries"] is None
    assert r["sections"]["giving"]["ministries_reason"] == "Budgets by ministry aren't set up yet, or couldn't be read just now."
    assert _v(r, "sunday", "attendance_avg") == 95


def test_a_failed_read_is_never_a_zero(db):
    db.missing |= {"attendance", "invoices", "contacts"}
    r = _report()
    s = _stats(r, "sunday")
    assert s["attendance_avg"]["value"] is None and s["attendance_avg"]["reason"] == "Attendance couldn't be read just now."
    assert _stats(r, "giving")["giving_total"]["reason"] == "Giving couldn't be read just now."
    assert _stats(r, "people")["members_end"]["value"] is None
    assert _stats(r, "groups")["groups_share"]["value"] is None


def test_a_section_that_breaks_is_its_own_dash(db, monkeypatch):
    def boom(ctx):
        raise RuntimeError("nope")
    monkeypatch.setitem(rp.BUILDERS, "events", boom)
    r = _report()
    assert r["sections"]["events"] == {"stats": [], "failed": True, "reason": "Events couldn't be put together just now."}
    assert _v(r, "sunday", "attendance_avg") == 95


def test_every_unknown_number_says_why(db):
    db.missing |= {"church_register_entries", "attendance"}
    for who, year in (("owner", None), ("clerk", None), ("owner", 2025), ("owner", 2022)):
        for name, s in _every_stat(_report(who, year=year)):
            assert (s["value"] is None) == bool(s["reason"]), (name, s)
            assert s["source"], (name, s)


def test_a_church_in_its_first_year(db):
    for t in ("attendance", "attendance_headcounts", "child_checkins", "invoices", "church_register_entries",
              "church_help_given", "ministry_care_requests", "church_follow_ups", "groups", "group_members",
              "business_budgets", "events", "church_event_registrations"):
        db.t[t] = [r for r in db.t[t] if r.get("business_id") != BIZ]
    db.t["module_entries"] = [r for r in db.t["module_entries"] if r["business_id"] != BIZ]
    db.t["businesses"][0]["created_at"] = "2026-09-01T12:00:00+00:00"
    r = _report()
    s = _stats(r, "sunday")
    assert s["attendance_avg"]["value"] is None and s["attendance_avg"]["reason"] == "No service has a count yet this year."
    assert s["services_counted"]["value"] == 0
    assert r["sections"]["sunday"]["reason"] == "No service has a count yet this year."
    assert _v(r, "people", "baptisms") == 0
    assert _v(r, "giving", "giving_total") == 0.0
    assert _stats(r, "people")["members_start"]["reason"].startswith("Love City Church started in the app")
    assert _stats(r, "groups")["groups"]["value"] == 0


def test_the_years(db):
    r = _report()
    assert r["year"] == 2026 and r["years"] == [2026, 2025, 2024, 2023, 2022]
    assert r["current"] is True and r["through"] == "2026-10-27" and r["today"] == "2026-10-27"
    assert r["church"]["name"] == "Love City Church" and r["church"]["colors"]["primary"] == "#1F3A5F"
    for bad in ("2021", "2027", "twenty"):
        assert client("owner").get(f"/church/reports?business_id={BIZ}&year={bad}").status_code == 400
    past = _report(year=2025)
    assert past["current"] is False and past["through"] == "2025-12-31"
    assert all(m is not None for m in past["sections"]["sunday"]["months"]), "a past year's months have all come"
    p = _stats(past, "people")
    # December 31, 2025: M1, M2 and M5 (M4 joined in April 2026; M3 came later).
    assert p["members_end"]["value"] == 3 and p["members_end"]["label"] == "Members on December 31, 2025"
    assert p["baptisms"]["value"] == 1
    assert _v(past, "giving", "giving_total") == 60.0
    assert _stats(past, "giving")["giving_vs_budget"]["value"] == 80   # $60 of the $75 budget
    assert past["sections"]["giving"]["ministries_reason"] == "Ministry budgets are kept for this year only."
    assert _stats(past, "sunday")["attendance_avg"]["value"] == 70


# ─── The CSV ─────────────────────────────────────────────────────────

def test_the_csv_carries_every_number_and_its_source(db):
    db.t["invoices"].append(_gift(50, 10, "2026-07-01T15:00:00+00:00", M1, "=HYPERLINK(\"http://x\")"))
    got = client("owner").get(f"/church/reports/export?business_id={BIZ}")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("text/csv")
    assert got.headers["content-disposition"] == 'attachment; filename="love-city-church-2026-numbers.csv"'
    rows = list(csv.reader(io.StringIO(got.text.lstrip("﻿"))))
    assert rows[0] == ["Church", "Year", "Through", "Section", "Number", "Value", "Unit", "Note", "Source"]
    by = {(r[3], r[4]): r for r in rows[1:]}
    assert by[("Sunday", "Average attendance at services")][5:7] == ["95", "people"]
    assert by[("Sunday", "Average attendance, January")][5] == "125"
    assert by[("Sunday", "Average attendance, February")][5:8] == ["—", "people", "No service was counted."]
    assert ("Sunday", "Average attendance, November") not in by
    assert by[("Giving", "Total given")][5:7] == ["470.00", "US dollars"]
    assert by[("Giving", "Of the giving budget")][7] == "through October"
    assert by[("People", "Members today")][8] == rp.SRC["members_now"]
    fund = next(r for r in rows if r[4].startswith("Designated · ") and "HYPERLINK" in r[4])
    assert fund[4].startswith("Designated · =HYPERLINK") and not fund[4].startswith("=")
    assert rp._cell("=SUM(A1)") == "'=SUM(A1)" and rp._cell("-3") == "'-3" and rp._cell("Kids") == "Kids"
    assert all(len(r) == 9 for r in rows)

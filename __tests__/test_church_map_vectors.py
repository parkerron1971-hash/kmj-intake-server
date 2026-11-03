"""The switches' backfill, pinned (docs/CHURCH_LEADERS_MAP.md §2, PR 2).

supabase/APPLY-2026-11-04-church-map.sql freezes today's rules into each
role's switches once, so day one changes nothing. This oracle computes the
same values with today's Python:

    can_shepherd   church_shepherding.role_rows: senior, or pastoral with a
                   shepherd word, is True; pastoral with "minister" follows
                   the Ministers setting (None); anything else False
    can_lead       the job is in member_portal_messaging.LEADER_JOBS
    can_oversee    senior or pastoral (no reader today: no departments yet)
    can_board_yes  False (a board's yes comes from church_board_members)
    can_see_all    the senior job (church_roles.JOBS senior sees everything)
    made_for       the handled streams whose word is in key + title: the
                   tie-break in church_follow_up.choose (:386-388)
    office_overseer_roles  the active roles with key or catalog_key
                   executive_pastor (church_duties._exec_users,
                   church_office_tasks.overseers); None when there are none

over every church_roles.TYPES row of the eight types, the four LEGACY rows,
every role in the three test churches' libraries (church_three) and a few
edges. __tests__/church_map_db.mjs runs the SQL over the same rows and must
get the same values; this test holds the oracle to the file, and the SQL's
literals to the Python constants they copy.

After a deliberate change, regenerate:  python __tests__/test_church_map_vectors.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_duties as cd  # noqa: E402
import church_follow_up as cfu  # noqa: E402
import church_office_tasks as cot  # noqa: E402
import church_roles as cr  # noqa: E402
import church_shepherding as shep  # noqa: E402
import member_portal_messaging as mpm  # noqa: E402

VECTORS = os.path.join(HERE, "fixtures", "church_map_backfill_vectors.json")
MIGRATION = os.path.join(ROOT, "supabase", "APPLY-2026-11-04-church-map.sql")

# Rows no catalog has: any status, a shepherd word beside "minister", case, a
# pastor word on a job that never shepherds, the stream word in the key alone,
# the Executive Pastor by catalog_key only, and an archived one left out.
EDGES = [
    ("associate_pastor", "Associate Pastor", "pastoral", ["pastor_ask", "care_need"], "archived", "associate_pastor"),
    ("ministers", "Ministers", "pastoral", ["baptism"], "draft", "ministers"),
    ("minister_elder", "Minister and Elder", "pastoral", ["pastor_ask"], "active", ""),
    ("pastoral_care_minister", "PASTORAL CARE MINISTER", "pastoral", ["pastor_ask", "care_need"], "active", ""),
    ("overseer", "Overseer", "pastoral", [], "active", ""),
    ("bishop", "Bishop", "senior", ["pastor_ask"], "active", ""),
    ("kids_pastor", "Kids Pastor", "kids", [], "active", ""),
    ("care_minister", "Care Minister", "care", ["care_need"], "active", ""),
    ("prayer_pastor", "Prayer Pastor", "prayer", ["prayer_shared"], "active", ""),
    ("baptism_lead", "Immersion lead", "pastoral", ["baptism"], "active", ""),
    ("serve_captain", "Serve Team captain", "team", ["serve"], "active", ""),
    ("connections", "Connections", "welcome", ["visit", "connect"], "active", ""),
    ("teachers", "Teachers", "teach", None, "active", ""),
    ("office_admin", "Office Administrator", "office", None, "active", ""),
    ("ops_lead", "Operations lead", "ministry", ["serve"], "active", "executive_pastor"),
    ("executive_pastor", "Executive Pastor", "pastoral", [], "archived", "executive_pastor"),
]


def made_for(key: str, title: str, handles) -> list:
    """church_follow_up.choose's tie-break, as data: a stream whose word (its
    first part, six letters at most) is in the role's key and title."""
    return [s for s in handles if s.split("_")[0][:6] in (key + " " + title.casefold())]


def switches(row: dict) -> dict:
    job, key, title, handles = row["job"], row["key"], row["title"], list(row["handles"])
    rr = shep.role_rows([{"key": key, "title": title, "job": job}], {"ministers": False})
    can_shepherd = (None if rr[0]["switch"] == "ministers" else rr[0]["shepherds"]) if rr else False
    return {"can_shepherd": can_shepherd, "can_oversee": job in ("senior", "pastoral"),
            "can_lead": job in mpm.LEADER_JOBS, "can_board_yes": False, "can_see_all": job == "senior",
            "made_for": made_for(key, title, handles)}


def _role(key, title, job, handles, status="active", catalog_key="") -> dict:
    return {"key": key, "title": title, "job": job, "status": status, "catalog_key": catalog_key,
            "handles": list(handles)}


def _church(name: str, roles: list) -> dict:
    oo = sorted(r["key"] for r in roles if r["status"] == "active"
                and (r["key"] in cot.OVERSEER_KEYS or r["catalog_key"] in cot.OVERSEER_KEYS))
    return {"church": name, "office_overseer_roles": oo or None,
            "roles": [dict(r, **switches(r)) for r in roles]}


def compute(monkeypatch) -> dict:
    import church_three
    churches = []
    for t in cr.TYPE_ORDER:
        churches.append(_church(f"type:{t}", [_role(r["key"], r["title"], r["job"], cr.clean_handles(r["job"], r["handles"]),
                                                    catalog_key=r["key"]) for r in cr.TYPES[t]["rows"]]))
    churches.append(_church("legacy", [_role(r["key"], r["title"], r["job"], cr.clean_handles(r["job"], r["handles"]),
                                             catalog_key=r["key"]) for r in cr.LEGACY.values()]))
    db = church_three.build(monkeypatch, map_on=False, filled=False)
    for biz in church_three.CHURCHES:
        rows = sorted((d for d in db.t["church_role_defs"] if d["business_id"] == biz), key=lambda d: d["key"])
        churches.append(_church(f"fixture:{church_three.NAMES[biz]}", [
            _role(d["key"], d["title"], d["job"], d.get("handles") or [], d.get("status") or "active",
                  d.get("catalog_key") or "") for d in rows]))
    churches.append(_church("edge", [_role(k, t, j, cr.clean_handles(j, h), s, c) for k, t, j, h, s, c in EDGES]))
    return {"_about": ("Today's rules for each role's switches (docs/CHURCH_LEADERS_MAP.md §2), computed by "
                       "__tests__/test_church_map_vectors.py; supabase/APPLY-2026-11-04-church-map.sql must backfill "
                       "the same values (__tests__/church_map_db.mjs). Regenerate with "
                       "python __tests__/test_church_map_vectors.py"),
            "churches": churches}


def _dump(data: dict) -> str:
    """One role a line, so a change to one role is one line of the diff."""
    def j(v):
        return json.dumps(v, ensure_ascii=False)
    out = ["{", f' "_about": {j(data["_about"])},', ' "churches": [']
    for i, c in enumerate(data["churches"]):
        head = {k: v for k, v in c.items() if k != "roles"}
        out.append("  {" + j(head)[1:-1] + ', "roles": [')
        out += [f"   {j(r)}" + ("," if n < len(c["roles"]) - 1 else "") for n, r in enumerate(c["roles"])]
        out.append("  ]}" + ("," if i < len(data["churches"]) - 1 else ""))
    return "\n".join(out + [" ]", "}"]) + "\n"


def test_the_oracle_equals_the_vectors_file(monkeypatch):
    with open(VECTORS, encoding="utf-8") as f:
        assert json.load(f) == compute(monkeypatch), \
            "today's rules moved: if that's deliberate, run python __tests__/test_church_map_vectors.py"


def test_the_vectors_cover_every_catalog_row_and_the_fixture():
    with open(VECTORS, encoding="utf-8") as f:
        got = {c["church"]: c for c in json.load(f)["churches"]}
    for t in cr.TYPE_ORDER:
        assert [r["key"] for r in got[f"type:{t}"]["roles"]] == [r["key"] for r in cr.TYPES[t]["rows"]], t
    lc = {r["key"]: r for r in got["fixture:love_city"]["roles"]}
    nh = {r["key"]: r for r in got["fixture:new_hope"]["roles"]}
    gr = {r["key"]: r for r in got["fixture:grace"]["roles"]}
    # The fixture's own titles: two custom roles at Love City, a custom one and three retitles at New Hope.
    assert (lc["prophets"]["title"], lc["evangelists"]["title"]) == ("Prophets", "Evangelists")
    assert [nh[k]["title"] for k in ("director_of_operations", "pastor", "youth_pastor", "worship_leader")] == \
        ["Director of Operations", "Senior Pastor", "Youth Director", "Worship Director"]
    assert gr["deacons"]["title"] == "Deacon Board"
    # Who shepherds: test_church_three_today's SHEPHERDING, as stored switches (None = the Ministers setting).
    assert {k: r["can_shepherd"] for k, r in lc.items() if r["job"] in ("senior", "pastoral")} == {
        "pastor": True, "executive_pastor": True, "associate_pastor": True, "elders": True, "ministers": None,
        "prophets": False}
    assert {k: r["can_shepherd"] for k, r in gr.items() if r["job"] in ("senior", "pastoral")} == {
        "pastor": True, "associate_ministers": None}
    assert gr["deacons"]["can_shepherd"] is False                # a care job: PR 4's flip, not the backfill
    assert lc["prophets"]["can_oversee"] is True                 # every pastoral role, not a flip
    assert (lc["evangelists"]["can_oversee"], lc["evangelists"]["can_lead"]) == (False, True)
    assert (got["fixture:love_city"]["office_overseer_roles"], got["fixture:new_hope"]["office_overseer_roles"],
            got["fixture:grace"]["office_overseer_roles"]) == (["executive_pastor"], ["executive_pastor"], None)
    assert got["edge"]["office_overseer_roles"] == ["ops_lead"]
    # made_for: the role made for a stream, as choose's tie-break picks it.
    assert {r["key"]: r["made_for"] for r in got["legacy"]["roles"]} == {
        "pastor": ["pastor_ask"], "baptism_minister": ["baptism"], "welcome_lead": [], "team_leader": []}


@pytest.mark.parametrize("stream,kind,answers,job", [
    ("baptism", "baptism", [], "pastoral"),
    ("pastor_ask", "connect", [{"q": "Anything else?", "a": "I’d like to talk with a pastor"}], "pastoral"),
    ("care_need", "connect", [{"q": "Anything else?", "a": "My mom is in the hospital"}], "care"),
    ("connect", "connect", [], "welcome"),
    ("visit", "visit", [], "welcome"),
])
def test_made_for_is_the_tie_break_choose_uses_today(stream, kind, answers, job):
    """Two roles alike but for the stream's word: choose hands the card to the
    one made_for names, though it comes second; with neither worded, the first."""
    word = {"pastor_ask": "Pastor", "care_need": "Care", "connect": "Connection"}.get(stream, stream.title())

    def card(second_title):
        defs = [{"id": "r1", "key": "helpers", "title": "Helpers", "job": job, "covers": "church", "reports_to": None,
                 "oversees_teams": [], "handles": [stream], "status": "active"},
                {"id": "r2", "key": "aides", "title": second_title, "job": job, "covers": "church", "reports_to": None,
                 "oversees_teams": [], "handles": [stream], "status": "active"}]
        holders = [{"id": f"h{n}", "contact_id": f"c{n}", "role": d["key"], "status": "active", "name": f"Person {n}"}
                   for n, d in enumerate(defs, 1)]
        return cfu.choose(kind, answers, holders, {}, defs)["role"], [made_for(d["key"], d["title"], d["handles"])
                                                                      for d in defs]

    picked, mf = card(f"{word} aides")
    assert (picked, mf) == ("aides", [[], [stream]])
    picked, mf = card("Aides")
    assert (picked, mf) == ("helpers", [[], []])


def test_the_sql_copies_todays_literals():
    """The migration's rule is written out in SQL; these are the Python
    constants it copies, so a change to one without the other fails here."""
    with open(MIGRATION, encoding="utf-8") as f:
        sql = f.read()
    assert f"~* '{shep.SHEPHERD_TITLE.pattern}'" in sql
    assert f"~* '{shep.MINISTER_TITLE.pattern}'" in sql
    assert shep.SHEPHERD_TITLE.flags & re.I and shep.MINISTER_TITLE.flags & re.I
    assert "p_job in (" + ", ".join(f"'{j}'" for j in mpm.LEADER_JOBS) + ")" in sql
    assert set(cot.OVERSEER_KEYS) == {cd.EXEC} == {"executive_pastor"}
    assert "d.key = 'executive_pastor' or d.catalog_key = 'executive_pastor'" in sql
    assert "left(split_part(h.s, '_', 1), 6)" in sql


if __name__ == "__main__":
    with pytest.MonkeyPatch.context() as mp:
        data = compute(mp)
    os.makedirs(os.path.dirname(VECTORS), exist_ok=True)
    with open(VECTORS, "w", encoding="utf-8", newline="\n") as f:
        f.write(_dump(data))
    print(f"wrote {VECTORS}: {sum(len(c['roles']) for c in data['churches'])} roles in {len(data['churches'])} churches")

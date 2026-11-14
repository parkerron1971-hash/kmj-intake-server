"""Every server path that hands someone a task, audited (docs/CHURCH_ASSIGNMENTS.md,
"Every path that hands someone a task"). Kevin, 2026-11-12: "admins can not
give work to elders and pastors": only the church's owner, or the ministry
chain on the leaders map, can.

A task is handed by writing tasks.assigned_to (a login) or
tasks.assigned_contact_id (one of the church's people). On 2026-11-14 every
server module that writes either was read and judged; this pins that list, so
a new path can't start handing out tasks without someone asking the rule
(church_over.may_hand, as church_board.make_tasks does, or church_over.is_over,
as the assignment routes do).

What this can't see: the office's Tasks screen writes `tasks` straight to the
database from the browser, with the login's own session. No server code is in
that path, so a request made by hand can still land. The hourly sweeps that
tell someone a task is theirs ask the rule first and take such a hand-off back
(church_leader_tasks.take_back, since 2026-11-14), so nobody is told about it.
Until that sweep runs, for up to an hour, the task can show on that person's
My week or Lead tab. That is the limit left, said in the doc.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = Path(os.path.dirname(HERE))
for p in (str(ROOT), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

# An assignee column written as a key ("assigned_to": x, assigned_contact_id=x),
# never one only read or filtered on (assigned_to=eq.<id> in a path).
WRITES_WHO = re.compile(r"""["']assigned_(?:to|contact_id)["']\s*:|\bassigned_(?:to|contact_id)\s*=(?![=>]|eq\.|in\.|is\.|not\.|neq\.)""")
# The tasks table: its PostgREST path, or named in a table list a write loops over.
TASKS = re.compile(r"""/tasks[?"']|\(\s*["']tasks["']\s*,""")

# module -> what it does with the assignee, and why an office seat can't use
# it to hand a pastor or an elder work around the rule.
AUDITED = {
    "church_assignments.py": "the assignment routes: every hand-off asks church_over.is_over first (_allowed)",
    "church_startup.py": "a first assignment: only called by the assignment routes, Chief's verb and the member "
                         "app's Lead tab, each after is_over",
    "church_board.py": "a board's follow-ups: church_over.may_hand for each one (_not_handed, PR #1844)",
    "church_leader_tasks.py": "return_tasks: a task whose leader left goes back to the login that handed it out "
                              "(tasks.handed_by, stamped by the database); it never names anyone new. take_back "
                              "(both hourly sweeps): only ever un-hands, after church_over.may_hand says no",
    "business_users_router.py": "hand_back_login: a removed login's open tasks are un-handed (assigned_to null)",
}


def _modules():
    for path in sorted(list(ROOT.glob("*.py")) + list(ROOT.glob("*/*.py"))):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("__tests__/", "scripts/", "_", ".")):
            continue
        yield rel, path.read_text(encoding="utf-8", errors="ignore")


def test_every_module_that_hands_a_task_is_one_that_was_audited():
    found = sorted(rel for rel, text in _modules() if TASKS.search(text) and WRITES_WHO.search(text))
    assert found == sorted(AUDITED), (
        "A module writes tasks.assigned_to or tasks.assigned_contact_id and isn't on the audited list (or one on "
        "the list no longer does). A hand-off an office seat can reach must ask church_over.may_hand (as "
        "church_board._not_handed does) or church_over.is_over (as church_assignments._allowed does) while "
        "church_over.church_open is true. Then add it here and to docs/CHURCH_ASSIGNMENTS.md.")


def test_the_guarded_ones_still_ask_the_rule():
    by = dict(_modules())
    assert "co.is_over(ch, me, target)" in by["church_assignments.py"]
    assert "co.may_hand(ch, asker, *ids)" in by["church_board.py"]
    # A leader's task goes back only to whoever handed it out; a removed login's is handed to no one.
    assert '{"assigned_contact_id": None, "assigned_to": t.get("handed_by") or None}' in by["church_leader_tasks.py"]
    assert '("tasks", "tasks_returned", "status=neq.done", {"assigned_to": None})' in by["business_users_router.py"]


def test_both_sweeps_ask_the_rule_before_anyone_is_told():
    """The one path no route guards (the Tasks screen's own write) reaches
    server code in the hourly sweeps: each asks before it claims or tells
    (behaviour: test_church_task_sweep_rule.py)."""
    by = dict(_modules())
    office, leaders = by["church_office_tasks.py"], by["church_leader_tasks.py"]
    asked = 'rows = clt.take_back(biz, rows, "assigned_to", "seat_told_at", stats, "office_")'
    assert asked in office and office.index(asked) < office.index('_claim(b, t, "seat_told_at", stamp)')
    asked = 'rows = take_back(biz, rows, "assigned_contact_id", "leader_told_at", stats)'
    assert asked in leaders and leaders.index(asked) < leaders.index('_claim(b, t, "leader_told_at", stamp)')
    assert "wrong = co.wrong_hands(biz, ask, column)" in leaders
    assert 'may_hand(ch, who(LOGIN, t["handed_by"]), *targets)' in by["church_over.py"]
    # It only ever un-hands: the one column it writes is set to no one.
    assert "{column: None," in leaders


def test_chief_and_the_automations_make_tasks_handed_to_no_one():
    """Chief's create_task (the tag and the native tool), the rules engine
    and the site's photo list each make a task; none can name who it's for."""
    by = dict(_modules())
    for rel in ("chief_of_staff.py", "mcp_server.py", "rules_engine.py", "site_photo_list.py", "church_work_checks.py"):
        assert "/tasks" in by[rel] or rel == "mcp_server.py", rel
        assert not re.search(r"assigned_(?:to|contact_id)", by[rel]), rel

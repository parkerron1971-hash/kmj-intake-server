"""The lint that pins every read of the board's tables (docs/CHURCH_SCHEDULE.md
10.2, PR S3-2). Step 3 puts meetings beside boards in church_boards: a group
is a `board` (it governs: its people give the board's yes on money, it is a
board on the leaders map and the Board tab) or a `meeting` (the huddle, the
leaders meeting, a check-in). A reader that takes every row for a board would
hand a huddle's people the board's yes on a check request.

So every read of church_boards, church_board_members and church_board_meetings,
in every module of the server (church_board.py included), must name `kind`
or `audience` (or, for a seat, `from_list`: a seat is the list's exactly when
its group's audience isn't members; or, for a read that lists or counts
meetings, `cancelled_at`), directly or through one of church_meetings' helpers
that add them once the columns are there (board_kind, group_cols,
meeting_cols, seat_cols, and church_board's meeting_fields, member_fields,
board_fields). Or it is on PINNED below, by module, function and table, with
how many such reads the function makes and why it may read as it does. A new
read fails until it says which; a pin whose reads changed or went fails too.

church_map reads the boards by table name (_THINGS), not by a path: it reads
them only through church_map.thing(), which names kind (the last test).
"""
from __future__ import annotations

import ast
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

TABLES = ("church_boards", "church_board_members", "church_board_meetings")
_PATH = re.compile(r"/(church_boards|church_board_members|church_board_meetings)\?")
NAMES = re.compile(r"\b(kind|audience|cancelled_at|from_list)\b|\b(board_kind|group_cols|meeting_cols|seat_cols|"
                   r"meeting_fields|member_fields|board_fields)\(")
WRITES = ("sb_post_as_service", "sb_patch_as_service", "sb_delete_as_service")
READS = ("_need", "_get", "_all", "_every", "sb_get_as_service", "sb_get_all_as_service", "sb_count_as_service")
SKIP_DIRS = {"__tests__", "research", ".git", "node_modules", "video_worker", "__pycache__", ".playwright-mcp"}

# (module, function, table) -> (how many reads, why it may read without naming kind)
PINNED = {
    ("church_board.py", "meeting_page", "church_board_meetings"): (
        4, "the day an item was carried from, the drafted minutes waiting, the minutes approved in this meeting and "
           "the meeting they were approved in: each by a meeting's own id or by drafted/approved status, and a "
           "meeting called off is only ever planned (church_board_meetings_called_off), so none can be one"),
    ("church_board.py", "decisions_log", "church_board_meetings"): (
        1, "each decision's own meeting, by id, for its day and title: the decisions were already read from the "
           "boards (or the one group named) whose log this is"),
    ("church_money_levels.py", "board", "church_board_members"): (
        1, "the seats of _open_boards' ids only, and _open_boards reads kind=eq.board"),
    ("church_money_levels.py", "board_people", "church_board_members"): (
        1, "the seats of _open_boards' ids only, and _open_boards reads kind=eq.board"),
    ("member_portal_board.py", "boards_of", "church_board_members"): (
        1, "the person's seats, whose groups are then read with kind=eq.board in the same function"),
    ("member_portal_board.py", "decisions_view", "church_board_meetings"): (
        1, "whether each decision's own meeting has its minutes out, by id: the decisions are the boards' log's"),
    ("housing_allowance.py", "_boards_vote", "church_board_meetings"): (
        1, "the decision's own meeting, by id, for the group that held it: that group is then read with "
           "kind=eq.board"),
}
# Not one of the three tables, so not scanned; kept here because the design
# names it (docs/CHURCH_SCHEDULE.md 10.2): church_monthly_report counts tasks
# made from every group's agenda items, meetings' included, on purpose: the
# "Decisions to done" duty is the huddle's and the leaders meeting's
# (church_duties.py, "decisions").
ON_PURPOSE = {("church_monthly_report.py", "church_board_items"):
              "tasks from meetings: every group's, on purpose (the Decisions to done duty is the huddle's)"}


def _modules():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def _func_name(node) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _text(node) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
                       for v in node.values)
    return ""


def reads():
    """Every read of the three tables: (module, function, table, the read's
    source, whether it names kind)."""
    out = []
    for path in _modules():
        src = open(path, encoding="utf-8").read()
        if not _PATH.search(src):
            continue
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        tree = ast.parse(src)
        parent = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parent[c] = n
        seen = set()
        for n in ast.walk(tree):
            if not isinstance(n, (ast.JoinedStr, ast.Constant)) or isinstance(parent.get(n), ast.JoinedStr):
                continue
            m = _PATH.search(_text(n))
            if not m:
                continue
            up, call, stmt, fn = parent.get(n), None, None, "<module>"
            write = False
            while up is not None:
                if isinstance(up, ast.Call) and call is None:
                    name = _func_name(up)
                    if name in WRITES:
                        write = True
                        break
                    if name in READS:
                        call = up
                if stmt is None and isinstance(up, ast.stmt):
                    stmt = up
                if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = up.name
                    break
                up = parent.get(up)
            if write:
                continue
            seg = ast.get_source_segment(src, call or stmt or n) or ""
            key = (rel, fn, m.group(1), seg)
            if key in seen:
                continue
            seen.add(key)
            out.append((rel, fn, m.group(1), seg, bool(NAMES.search(seg))))
    return out


def test_every_read_of_the_boards_tables_names_kind_or_is_pinned_with_a_reason():
    got = reads()
    assert len(got) > 20, "the lint found the reads (church_board.py alone makes many)"
    bare = Counter((rel, fn, table) for rel, fn, table, _seg, named in got if not named)
    loose = {k: n for k, n in bare.items() if k not in PINNED}
    assert not loose, ("A read of the board's tables names neither kind, audience, from_list nor cancelled_at, and "
                       f"isn't pinned (docs/CHURCH_SCHEDULE.md 10.2): {loose}")
    stale = {k: (bare.get(k, 0), want) for k, (want, _why) in PINNED.items() if bare.get(k, 0) != want}
    assert not stale, f"A pin no longer matches its reads (found, pinned): {stale}"
    assert all(len(why) > 40 for _n, why in PINNED.values()), "each pin says why"


def test_the_four_readers_the_design_names_read_kind():
    """church_money_levels._open_boards, member_portal_board.boards_of (and
    housing_allowance's vote) name kind=eq.board through board_kind(), never
    a pin."""
    got = reads()
    want = {("church_money_levels.py", "_open_boards", "church_boards"),
            ("member_portal_board.py", "boards_of", "church_boards"),
            ("housing_allowance.py", "_boards_vote", "church_boards")}
    hits = {(rel, fn, t): seg for rel, fn, t, seg, _named in got}
    for k in want:
        assert k in hits and "board_kind()" in hits[k], k


def test_church_maps_boards_are_read_only_through_thing():
    src = open(os.path.join(ROOT, "church_map.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    uses = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for n in ast.walk(fn):
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "_THINGS":
                uses.append(fn.name)
    assert uses == ["thing"], uses
    for rel in ("chief_map.py", "church_map_batch.py"):
        other = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "_THINGS[" not in other, f"{rel} reads a board through church_map.thing()"
    import church_map
    import church_meetings as cmt
    old = cmt._FORCE
    try:
        cmt._FORCE = True
        assert church_map.thing("board")[2].endswith("&kind=eq.board")
        cmt._FORCE = False
        assert church_map.thing("board") == ("church_boards", "name", "&archived=eq.false")
    finally:
        cmt._FORCE = old


def test_the_monthly_reports_tasks_from_meetings_are_every_groups_on_purpose():
    src = open(os.path.join(ROOT, "church_monthly_report.py"), encoding="utf-8").read()
    assert src.count("/church_board_items?") == 1 and "kind" not in src.split("/church_board_items?")[1][:80]
    assert ON_PURPOSE

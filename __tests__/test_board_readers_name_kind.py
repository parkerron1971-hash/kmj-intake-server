"""The lint that pins every read of the board's tables (docs/CHURCH_SCHEDULE.md
10.2, PR S3-2). Step 3 puts meetings beside boards in church_boards: a group
is a `board` (it governs: its people give the board's yes on money, it is a
board on the leaders map and the Board tab) or a `meeting` (the huddle, the
leaders meeting, a check-in). A reader that takes every row for a board would
hand a huddle's people the board's yes on a check request.

Every read of church_boards, church_board_members, church_board_meetings and
church_board_decisions, in every module of the server (church_board.py
included), is one of:

  * a read of church_boards that FILTERS on kind (church_meetings.board_kind()
    or `kind=eq.` in its path): it means a board;
  * a read of the seats or the meetings that names kind, audience, from_list
    (a seat is the list's exactly when its group's audience isn't members) or
    cancelled_at, directly or through one of church_meetings' helpers
    (group_cols, meeting_cols, seat_cols, not_called_off, and church_board's
    meeting_fields, member_fields, board_fields);
  * or on PINNED below, by module, function and table, with how many such
    reads the function makes and why it may read as it does.

And each read goes through a reader that falls back to the old read only when
the database says for certain step 3's columns aren't there
(church_meetings.read): never sb_get_as_service on its own, so a timeout is a
503 and never a meeting read as a board. A new read fails until it says
which; a pin whose reads changed or went fails too. The callers outside
church_board.py of the helpers that read every group (_boards, _members,
groups_of_login) are pinned the same way (EXTERNAL).

church_map reads the boards by table name (_THINGS), not by a path: it reads
them only through church_map.thing(), which names kind (the last tests).
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

TABLES = ("church_boards", "church_board_members", "church_board_meetings", "church_board_decisions")
_PATH = re.compile(r"/(church_boards|church_board_members|church_board_meetings|church_board_decisions)\?")
NAMES = re.compile(r"\b(kind|audience|cancelled_at|from_list)\b|\b(board_kind|group_cols|meeting_cols|seat_cols|"
                   r"not_called_off|meeting_fields|member_fields|board_fields)\(")
FILTERS = re.compile(r"\bboard_kind\(|kind=eq\.")
WRITES = ("sb_post_as_service", "sb_patch_as_service", "sb_delete_as_service")
READS = ("_need", "_get", "_all", "_every", "_rows", "read", "sb_get_as_service", "sb_get_all_as_service",
         "sb_count_as_service")
RAW = ("sb_get_as_service", "sb_get_all_as_service", "sb_count_as_service")
SKIP_DIRS = {"__tests__", "research", ".git", "node_modules", "video_worker", "__pycache__", ".playwright-mcp"}
# The readers every board read goes through: each reads through church_meetings.read.
READERS = {"church_board.py": "_need", "church_money_levels.py": "_need", "church_map.py": "_need",
           "housing_allowance.py": "_get", "church_meetings.py": "_need", "member_portal_board.py": "cb._need"}
_ALIASES = {"cb": "church_board.py", "church_board": "church_board.py", "cm": "church_map.py"}

BY_ID = "one row by its own id"
# (module, function, table) -> (how many reads, why it may read as it does)
PINNED = {
    ("church_board.py", "_boards", "church_boards"): (
        1, "every group this login may see, boards and meetings both, each read with its kind and audience: the "
           "page shows both, may_write reads the audience, and decisions_log keeps the boards by kind"),
    ("church_board.py", "_board", "church_boards"): (
        1, f"{BY_ID}, with its kind and audience: a caller that means a board (approve, the decisions log) asks "
           "its kind"),
    ("church_board.py", "add_board", "church_boards"): (
        1, "the open groups' names and order, every kind: a new board's name is checked against every group"),
    ("church_meetings.py", "_open_list_groups", "church_boards"): (
        1, "the open groups for the leaders list, by audience: a group for the list is always a meeting "
           "(church_boards_list_is_meeting)"),
    ("church_meetings.py", "list_group", "church_boards"): (
        1, "every open group's order, every kind, for the new group's place"),
    ("church_meetings.py", "_group_row", "church_boards"): (
        1, f"{BY_ID}, with its kind and audience, for the meeting the member app opens"),
    ("church_board.py", "meeting_page", "church_board_meetings"): (
        4, "the day an item was carried from, the drafted minutes waiting, the minutes approved in this meeting and "
           "the meeting they were approved in: each by a meeting's own id or by drafted/approved status, and a "
           "meeting called off is only ever planned (church_board_meetings_called_off), so none can be one"),
    ("church_board.py", "decisions_log", "church_board_meetings"): (
        1, "each decision's own meeting, by id, for its day and title: the decisions were already read from the "
           "boards (or the one group named) whose log this is"),
    ("church_board.py", "decisions_log", "church_board_decisions"): (
        1, "the decisions of the groups _boards gave, kept to kind board unless one group is named"),
    ("church_board.py", "_decisions_of", "church_board_decisions"): (
        1, "the decisions of meetings already read (a meeting's own page, the board page's groups)"),
    ("church_board.py", "_decision", "church_board_decisions"): (1, f"{BY_ID}; its meeting is then read and seen"),
    ("church_board.py", "delete_meeting", "church_board_decisions"): (
        1, "whether a meeting already read has a decision, before it may go"),
    ("church_board.py", "delete_item", "church_board_decisions"): (
        1, "whether an item already read has a decision, before it may go"),
    ("church_board.py", "resettle", "church_board_decisions"): (1, "an item's own decisions, for where it stands"),
    ("church_board.py", "_ready", "church_board_decisions"): (1, "whether the six tables answer: one id, nothing read"),
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
    ("housing_allowance.py", "_boards_vote", "church_board_decisions"): (
        1, f"{BY_ID}: its group and its meeting's are then read with kind=eq.board"),
}
# Callers outside church_board.py of the helpers that read every group, a
# meeting's too: (module, function, helper) -> why it may.
EXTERNAL = {
    ("church_meetings.py", "answers_view", "_members"): "a meeting's own seats: who comes to it, whatever its group",
    ("church_meetings.py", "put_answer", "_members"): "a meeting's own seats, for the one answering",
    ("church_meetings.py", "_person_seat", "_members"): "a meeting's own seats, for the person in the member app",
    ("church_meetings.py", "person_view", "_members"): "a meeting's own active seats, to count who is coming",
}
WIDE = ("_boards", "_members", "groups_of_login")
# Not one of the scanned tables; kept here because the design names it
# (docs/CHURCH_SCHEDULE.md 10.2): church_monthly_report counts tasks made from
# every group's agenda items, meetings' included, on purpose: the "Decisions to
# done" duty is the huddle's and the leaders meeting's (church_duties.py).
ON_PURPOSE = {("church_monthly_report.py", "church_board_items"):
              "tasks from meetings: every group's, on purpose (the Decisions to done duty is the huddle's)"}


def _modules(root=ROOT):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def _func_name(node) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _callee(node) -> str:
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f"{f.value.id}.{f.attr}"
    return _func_name(node)


def _text(node) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
                       for v in node.values)
    return ""


def _parents(tree):
    parent = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parent[c] = n
    return parent


def reads(root=ROOT):
    """Every read of the scanned tables: (module, function, table, the read's
    source, whether it names kind, whether it filters on kind, the reader
    it calls or None)."""
    out = []
    for path in _modules(root):
        src = open(path, encoding="utf-8").read()
        if not _PATH.search(src):
            continue
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        tree = ast.parse(src)
        parent = _parents(tree)
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
            out.append((rel, fn, m.group(1), seg, bool(NAMES.search(seg)), bool(FILTERS.search(seg)),
                        _callee(call) if call is not None else None))
    return out


def loose(got):
    """The reads that neither name (seats, meetings) nor filter (boards) on
    kind, by (module, function, table)."""
    bare = Counter()
    for rel, fn, table, _seg, named, filtered, _call in got:
        ok = filtered if table == "church_boards" else (named and table != "church_board_decisions")
        if not ok:
            bare[(rel, fn, table)] += 1
    return bare


def test_every_read_of_the_boards_tables_filters_or_names_kind_or_is_pinned_with_a_reason():
    got = reads()
    assert len(got) > 30, "the lint found the reads (church_board.py alone makes many)"
    bare = loose(got)
    unpinned = {k: n for k, n in bare.items() if k not in PINNED}
    assert not unpinned, ("A read of the board's tables neither filters church_boards on kind nor names kind, "
                          "audience, from_list or cancelled_at, and isn't pinned (docs/CHURCH_SCHEDULE.md 10.2): "
                          f"{unpinned}")
    stale = {k: (bare.get(k, 0), want) for k, (want, _why) in PINNED.items() if bare.get(k, 0) != want}
    assert not stale, f"A pin no longer matches its reads (found, pinned): {stale}"
    assert all(len(why) > 30 for _n, why in PINNED.values()), "each pin says why"


def test_every_board_read_goes_through_a_reader_that_falls_back_only_when_the_columns_are_not_there():
    got = reads()
    assert any(c for *_x, c in got), "the reads' readers were found"
    for rel, fn, table, seg, _named, _filtered, call in got:
        short = (call or "").split(".")[-1]
        assert short not in RAW, f"{rel}:{fn} reads {table} with {call} on its own: read it through its reader"
        if call is not None:
            assert rel in READERS and short in (READERS[rel].split(".")[-1], "read"), (rel, fn, call)
    for rel, name in READERS.items():
        mod, fn = (("church_board.py", "_need") if name.startswith("cb.") else (rel, name))
        src = open(os.path.join(ROOT, mod), encoding="utf-8").read()
        node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == fn)
        body = ast.get_source_segment(src, node)
        if "_rows(" in body and "cmt.read(" not in body:               # church_map: _need -> _rows
            node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_rows")
            body = ast.get_source_segment(src, node)
        assert "cmt.read(" in body or "= read(" in body, f"{mod}:{fn} reads through church_meetings.read"


def test_the_callers_of_the_helpers_that_read_every_group_are_pinned():
    found = set()
    for path in _modules():
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        if rel == "church_board.py":
            continue
        src = open(path, encoding="utf-8").read()
        if not any(w + "(" in src for w in WIDE):
            continue
        tree = ast.parse(src)
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in WIDE \
                        and isinstance(n.func.value, ast.Name) and n.func.value.id in ("cb", "church_board"):
                    found.add((rel, fn.name, n.func.attr))
    assert found == set(EXTERNAL), (sorted(found - set(EXTERNAL)), sorted(set(EXTERNAL) - found))


def test_the_four_readers_the_design_names_filter_on_kind():
    """church_money_levels._open_boards, member_portal_board.boards_of and
    the housing allowance's vote filter kind=eq.board through board_kind(),
    never a pin."""
    hits = {(rel, fn, t): (seg, filtered) for rel, fn, t, seg, _n, filtered, _c in reads()}
    for k in (("church_money_levels.py", "_open_boards", "church_boards"),
              ("member_portal_board.py", "boards_of", "church_boards"),
              ("housing_allowance.py", "_boards_vote", "church_boards")):
        assert k in hits and "board_kind()" in hits[k][0] and hits[k][1], k


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
        for pin in (True, None):
            cmt._FORCE = pin
            assert church_map.thing("board")[2].endswith("&kind=eq.board"), pin
        cmt._FORCE = False
        assert church_map.thing("board") == ("church_boards", "name", "&archived=eq.false")
    finally:
        cmt._FORCE = old


def test_the_monthly_reports_tasks_from_meetings_are_every_groups_on_purpose():
    src = open(os.path.join(ROOT, "church_monthly_report.py"), encoding="utf-8").read()
    assert src.count("/church_board_items?") == 1 and "kind" not in src.split("/church_board_items?")[1][:80]
    assert ON_PURPOSE


def test_the_lint_goes_red_on_a_new_unfiltered_read(tmp_path):
    """A scratch copy with a new reader of each kind the lint must catch."""
    (tmp_path / "church_new_thing.py").write_text(
        "import church_board as cb\n"
        "def boards(me):\n"
        "    return cb._need(f\"/church_boards?business_id=eq.{me}&archived=eq.false&select=id,name&limit=9\")\n"
        "def votes(me):\n"
        "    return cb._need(f\"/church_board_decisions?business_id=eq.{me}&select=id&limit=9\")\n"
        "def raw(me):\n"
        "    import sb_clients\n"
        "    return sb_clients.sb_get_as_service(f\"/church_boards?business_id=eq.{me}&kind=eq.board&select=id\")\n"
        "def wide(me):\n"
        "    return cb._boards(me)\n", encoding="utf-8")
    got = reads(str(tmp_path))
    bare = loose(got)
    assert bare == {("church_new_thing.py", "boards", "church_boards"): 1,
                    ("church_new_thing.py", "votes", "church_board_decisions"): 1}
    assert [c for *_x, c in got if (c or "").split(".")[-1] in RAW] == ["sb_clients.sb_get_as_service"]

"""Rule (a) of docs/CHURCH_LEADERS_MAP.md §0: words suggest, data decides. A
title or a key may suggest a value once, when the thing first appears; no code
reads a title word or a role key at read time to decide behavior.

Each reader §0's first table names is listed with the words it reads. Each is
xfail(strict=True) until the PR that deletes it (DONE is the last one merged
here): PR 9, after CHURCH_MAP=on everywhere, for all but job_for_title's
"care", which §4 dropped in PR 8. The areas' read-time words stay as the
closed map's path until PR 9. Words that only change wording on screen are
display, and aren't here."""
from __future__ import annotations

import ast
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source(module: str, func: str = "") -> str:
    """A module's source, or one function's ("" when it's gone)."""
    with open(os.path.join(ROOT, f"{module}.py"), encoding="utf-8") as f:
        text = f.read()
    if not func:
        return text
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            return ast.get_source_segment(text, node) or ""
    return ""


DONE = 8
READERS = [
    # (module, function or "" for the whole module, the read, what decides instead, the PR that deletes it)
    ("church_shepherding", "", r"\b(SHEPHERD|MINISTER)_TITLE\b", "can_shepherd decides", 9),
    ("church_follow_up", "choose", r"""split\("_"\)\[0\]|\["title"\]\.casefold\(\)""", "made_for decides", 9),
    # PR 7 moved the key query out of _exec_users into overseer_keys, where it is
    # the closed map's path until PR 9.
    ("church_duties", "overseer_keys", r"\bkey\.eq\.|catalog_key", "office_overseer_roles decides", 9),
    ("church_office_tasks", "overseers", r"\bOVERSEER_KEYS\b|catalog_key", "office_overseer_roles decides", 9),
    ("church_areas", "place_role", r"\bguess_area\(|_AREA_WORDS", "the department's area, then a stored guess", 9),
    ("church_areas", "place_team", r"\bguess_area\(|_AREA_WORDS", "the department's area, then a stored guess", 9),
    ("church_roles", "job_for_title", r"""return\s+["']care["']""", "guess_job, which can say it doesn't know", 8),
]


@pytest.mark.parametrize("module,func,read", [
    pytest.param(m, f, rx, id=f"{m}.{f or '*'}",
                 marks=() if pr <= DONE else pytest.mark.xfail(strict=True, raises=AssertionError,
                                                               reason=f"PR {pr}: {why}"))
    for m, f, rx, why, pr in READERS])
def test_no_reader_decides_by_a_title_word_or_a_role_key(module, func, read):
    assert not re.search(read, source(module, func)), f"{module}.{func or '*'} still reads /{read}/"


def test_every_reader_is_still_where_the_list_says():
    """A renamed function would make its line above pass for nothing."""
    for module, func, _read, _why, _pr in READERS:
        assert source(module, func), f"{module}.{func} moved: point READERS at it"

"""Every page on a church's menu is decided: Chief can read it, can't yet (said by
name), or it holds nothing to read (church_room_lookups).

Kevin, 2026-11-22: the treasurer asked what came in and Chief had no lookup for
it, and nothing caught that. This fails the next time a church room ships
without anyone deciding whether Chief can see it.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import action_registry  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import church_room_lookups as crl  # noqa: E402


def test_every_page_on_a_churchs_menu_is_decided_once():
    pages = crl.menu_pages()
    assert len(pages) > 90, "the menu was read"
    decided = list(crl.LOOKUPS) + list(crl.NO_LOOKUP) + list(crl.NOT_A_ROOM)
    undecided = sorted(set(pages) - set(decided))
    assert not undecided, (
        f"church rooms nobody decided about for Chief: {undecided}. Put each in church_room_lookups: "
        "LOOKUPS (the read actions that answer it), NO_LOOKUP (Chief can't read it yet) or NOT_A_ROOM.")
    twice = sorted(k for k in set(decided) if decided.count(k) > 1)
    assert not twice, f"in more than one list: {twice}"
    gone = sorted(set(decided) - set(pages))
    assert not gone, f"no longer on the menu (take them out): {gone}"


def test_every_lookup_named_is_one_of_chiefs_reads():
    for page, verbs in crl.LOOKUPS.items():
        assert verbs, page
        for v in verbs:
            assert v in cos.ACTION_HANDLERS, f"{page}: {v} has no handler"
            cls = action_registry.classification(v) or {}
            assert cls.get("effect") == "read", f"{page}: {v} is not a read"


def test_chief_is_told_the_rooms_it_cant_read_by_their_menu_names():
    line = crl.cant_read_line()
    pages = crl.menu_pages()
    assert line.startswith(f"Rooms you can't read yet ({len(crl.NO_LOOKUP)}): ")
    for k in crl.NO_LOOKUP:
        assert pages[k] in line
    assert "Never guess what is in it, and never say it is empty" in line and "use only what this prompt already shows" in line
    listed = line.split(": ", 1)[1].split(". Asked")[0].split(", ")
    assert len(listed) == len(crl.NO_LOOKUP) and set(listed) <= {pages[k] for k in crl.NO_LOOKUP}

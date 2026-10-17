"""ownership_sweep reads each function's text with its own _segment, over
lines split once per file, instead of ast.get_source_segment, which
re-split the whole file for every one of ~12,000 functions. The text must
be exactly what get_source_segment gives, or a guard the sweep looks for
in a handler's body could appear or vanish."""
from __future__ import annotations

import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ownership_sweep  # noqa: E402

TRICKY = (
    "def one(): return 1\r\n"
    "async def crlf(a,\r\n          b):\r\n    return 'é' + \"\\u2028\"\r\n"
    "def lone_cr():\r    x = 'form\x0cfeed'\r    return x\r"
    "class K:\n    def method(self):\n        def inner():\n            return '\u2028 é 中'\n"
    "        return inner\n"
    "def last_line_without_newline(): return '中文'"
)


def _same_as_get_source_segment(src: str) -> int:
    lines = ownership_sweep._source_lines(src)
    count = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert ownership_sweep._segment(lines, node) == ast.get_source_segment(src, node), node.name
            count += 1
    return count


def test_tricky_line_endings_and_characters_read_the_same():
    assert _same_as_get_source_segment(TRICKY) == 6


@pytest.mark.parametrize("name", ["ownership_sweep.py", "church_cards.py", "form_page_renderer.py",
                                  "site_page_helpers.py", "intake_endpoint.py"])
def test_real_files_read_the_same(name):
    with open(os.path.join(ROOT, name), encoding="utf-8", errors="ignore") as f:
        assert _same_as_get_source_segment(f.read()) > 0

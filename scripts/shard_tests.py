"""scripts/shard_tests.py — one part of the pytest suite, for CI's parallel test jobs.

Kevin, 2026-11-13: agents were waiting on each other's 20-minute test runs
to merge. CI now runs the suite as PARTS jobs side by side; this prints
the test files that belong to one part, so each file runs in exactly one.

    python scripts/shard_tests.py 2 4      # the files for part 2 of 4
    python scripts/shard_tests.py --check  # every file in exactly one part

The files are the ones pytest collects from __tests__ and agents with its
default names (test_*.py, *_test.py). Each file weighs its number of tests,
and the heaviest go first to the lightest part, so the parts finish close
together. The split depends only on the files, so every job agrees on it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
DIRS = ("__tests__", "agents")
SKIP = {"__pycache__", "node_modules", ".pytest_cache"}
TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+test", re.M)


def collect_files() -> List[Path]:
    out = []
    for d in DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if SKIP & set(p.relative_to(ROOT).parts):
                continue
            if p.name.startswith("test_") or p.name.endswith("_test.py"):
                out.append(p)
    return sorted(out, key=lambda p: p.relative_to(ROOT).as_posix())


def weight(p: Path) -> int:
    try:
        return max(1, len(TEST_DEF.findall(p.read_text(encoding="utf-8", errors="replace"))))
    except OSError:
        return 1


def parts(n: int) -> List[List[str]]:
    files = [(weight(p), p.relative_to(ROOT).as_posix()) for p in collect_files()]
    files.sort(key=lambda f: (-f[0], f[1]))
    bins: List[List[str]] = [[] for _ in range(n)]
    load = [0] * n
    for w, name in files:
        i = min(range(n), key=lambda k: (load[k], k))
        bins[i].append(name)
        load[i] += w
    return [sorted(b) for b in bins]


def check(n: int = 4) -> Dict[str, int]:
    every = [p.relative_to(ROOT).as_posix() for p in collect_files()]
    seen = [f for b in parts(n) for f in b]
    assert sorted(seen) == sorted(every), "a test file is missing from the parts, or in two"
    assert all(parts(n)), "a part has no test files"
    return {"files": len(every), "parts": n}


def main(argv: List[str]) -> int:
    if argv[:1] == ["--check"]:
        print(check())
        return 0
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    k, n = int(argv[0]), int(argv[1])
    if not 1 <= k <= n:
        print(f"part {k} isn't one of 1..{n}", file=sys.stderr)
        return 2
    print(" ".join(parts(n)[k - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

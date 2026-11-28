"""__tests__/db_checks_ci.py — does CI run this database check?

Since 2026-11-28 CI no longer lists the PGlite checks one by one in ci.yml.
scripts/db_checks.mjs FINDS them: every scripts/*-db-check.mjs and every
__tests__/*_db.mjs, minus the few named under "skip" in
scripts/db_checks.json. A test that used to assert
`"node __tests__/x_db.mjs" in ci.yml` asserts `runs_in_ci("__tests__/x_db.mjs")`.

This mirrors the finding rule in scripts/db_checks.mjs, and also checks that
ci.yml's database job really runs that script, so the answer is about CI and
not only about the file's name.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def runs_in_ci(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    folder, _, name = rel.rpartition("/")
    found = (folder == "scripts" and name.endswith("-db-check.mjs")) or (
        folder == "__tests__" and name.endswith("_db.mjs"))
    if not found or not (ROOT / rel).is_file():
        return False
    cfg = ROOT / "scripts" / "db_checks.json"
    skip = json.loads(cfg.read_text(encoding="utf-8")).get("skip", {}) if cfg.exists() else {}
    if rel in skip:
        return False
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci[ci.index("  test-db:"):ci.index("\n  test:\n")]
    return "node scripts/db_checks.mjs --run" in job

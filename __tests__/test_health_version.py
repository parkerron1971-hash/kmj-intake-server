"""/health says which commit is running.

The deploy check (.github/workflows/deploy-check.yml) waits for this
field to equal the merged commit. If it went missing, every merge would
look like a failed deploy, so its shape is pinned here.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import kmj_intake_automation as kia


def test_reports_the_railway_commit(monkeypatch):
    sha = "0123456789abcdef0123456789abcdef01234567"
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", sha)
    assert asyncio.run(kia.health())["version"] == sha


def test_unknown_version_is_null_not_empty(monkeypatch):
    """Null reads as 'cannot tell' in the workflow; an empty string would
    too, but null is what the field means."""
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    assert asyncio.run(kia.health())["version"] is None

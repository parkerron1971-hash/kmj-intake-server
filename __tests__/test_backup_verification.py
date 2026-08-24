"""The backup verifier has to go RED on a bad backup.

Every failure mode below produces a tidy directory, a plausible file size
and an exit code of zero from the job that made it. That is the whole
problem with backups: the bad ones are indistinguishable from the good
ones until the day you reach for them, and by then the good one has aged
out of retention.

So each test here IS the rehearsal, run on every push instead of once by
hand. The one that matters most is `test_a_public_only_dump_is_rejected`
— a `--schema=public` dump is the single most common way to end up with
a Supabase backup that restores into a database nobody can log into.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import scripts.verify_backup as vb  # noqa: E402


LIVE = {"policies": 316, "tables": 200, "objects": 45}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The verifier compares against live. Tests answer for it."""
    def fake(sql: str):
        if "pg_policies" in sql:
            return [{"n": LIVE["policies"]}]
        if "information_schema.tables" in sql:
            return [{"n": LIVE["tables"]}]
        if "storage.objects" in sql:
            return [{"n": LIVE["objects"]}]
        raise AssertionError(f"unexpected query: {sql}")
    monkeypatch.setattr(vb, "live_query", fake)
    vb.failures.clear()


def _good_dump() -> str:
    return (
        "CREATE SCHEMA auth;\n"
        + "".join(f'CREATE TABLE "public"."t{i}" (id uuid);\n'
                  for i in range(LIVE["tables"]))
        + "".join(f'CREATE POLICY "p{i}" ON "public"."t0";\n'
                  for i in range(LIVE["policies"]))
        + 'COPY auth.users (id, email) FROM stdin;\n'
        + 'COPY "public"."t0" (id) FROM stdin;\n'
        + "x" * 200_000
    )


def _write(tmp_path, dump_text: str, objects: int = LIVE["objects"],
           errors=None, on_disk: bool = True, total_bytes: int = 42_000_000):
    dump = tmp_path / "db.sql"
    io.open(dump, "w", encoding="utf-8").write(dump_text)

    storage = tmp_path / "storage"
    storage.mkdir(exist_ok=True)
    entries = []
    for i in range(objects):
        rel = f"biz/file{i}.bin"
        entries.append({"bucket": "b", "path": rel, "bytes": 10, "sha256": "x"})
        if on_disk:
            dest = storage / "b" / "biz"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"file{i}.bin").write_bytes(b"0123456789")
    manifest = {
        "buckets": [{"name": "b", "public": False}],
        "objects": entries,
        "errors": errors or [],
        "total_objects": len(entries),
        "total_bytes": total_bytes,
    }
    io.open(storage / "manifest.json", "w", encoding="utf-8").write(
        json.dumps(manifest))
    return str(dump), str(storage)


def _run(dump, storage) -> int:
    argv = ["verify_backup.py", "--dump", dump, "--storage", storage]
    old = sys.argv
    sys.argv = argv
    try:
        return vb.main()
    finally:
        sys.argv = old


def test_a_good_backup_passes(tmp_path):
    assert _run(*_write(tmp_path, _good_dump())) == 0
    assert vb.failures == []


def test_a_public_only_dump_is_rejected(tmp_path):
    """`pg_dump --schema=public` — restores to a database where nobody
    can log in and every owner_id points at a ghost."""
    dump = _good_dump().replace("CREATE SCHEMA auth;\n", "").replace(
        "COPY auth.users (id, email) FROM stdin;\n", "")
    assert _run(*_write(tmp_path, dump)) == 1
    assert any("auth" in f for f in vb.failures)


def test_a_dump_without_rls_policies_is_rejected(tmp_path):
    """Restoring data without policies stands every customer's records
    up with row-level security switched off."""
    dump = _good_dump().replace('CREATE POLICY "p1" ON "public"."t0";\n', "")
    dump = dump.replace("CREATE POLICY", "-- redacted", LIVE["policies"] - 10)
    assert _run(*_write(tmp_path, dump)) == 1
    assert any("RLS" in f for f in vb.failures)


def test_a_schema_only_dump_is_rejected(tmp_path):
    """Right shape, no rows. Passes a size check easily."""
    dump = _good_dump().replace("COPY auth.users (id, email) FROM stdin;\n", "")
    dump = dump.replace('COPY "public"."t0" (id) FROM stdin;\n', "")
    assert _run(*_write(tmp_path, dump)) == 1


def test_a_truncated_dump_is_rejected(tmp_path):
    assert _run(*_write(tmp_path, "CREATE SCHEMA auth;\n")) == 1
    assert any("small" in f for f in vb.failures)


def test_a_missing_dump_is_rejected(tmp_path):
    _, storage = _write(tmp_path, _good_dump())
    assert _run(str(tmp_path / "nope.sql"), storage) == 1


def test_storage_that_silently_skipped_objects_is_rejected(tmp_path):
    """The lister that does not recurse backs up 6 of 45 and exits 0."""
    assert _run(*_write(tmp_path, _good_dump(), objects=6)) == 1
    assert any("storage" in f for f in vb.failures)


def test_a_manifest_promising_files_that_are_not_there_is_rejected(tmp_path):
    assert _run(*_write(tmp_path, _good_dump(), on_disk=False)) == 1
    assert any("disk" in f for f in vb.failures)


def test_storage_errors_are_not_tolerated(tmp_path):
    assert _run(*_write(tmp_path, _good_dump(),
                        errors=["get b/x: 403"])) == 1


def test_zero_byte_storage_is_rejected(tmp_path):
    assert _run(*_write(tmp_path, _good_dump(), total_bytes=0)) == 1


def test_small_storage_drift_is_tolerated(tmp_path):
    """Objects legitimately move between the storage pass and this one.
    A tolerance that is too tight makes the alarm cry wolf until it gets
    ignored, which is the same as not having one."""
    assert _run(*_write(tmp_path, _good_dump(),
                        objects=LIVE["objects"] - 2)) == 0


def test_the_verifier_reports_failure_when_it_cannot_reach_live(monkeypatch, tmp_path):
    """An exception in the verifier must never read as a passing backup."""
    def boom(sql):
        raise RuntimeError("management API down")
    monkeypatch.setattr(vb, "live_query", boom)
    dump, storage = _write(tmp_path, _good_dump())
    with pytest.raises(RuntimeError):
        _run(dump, storage)

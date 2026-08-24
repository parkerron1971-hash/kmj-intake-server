#!/usr/bin/env python3
"""verify_backup.py — decide whether last night's backup is a backup.

A backup job that exits 0 has proved that a program ran, not that
anything was saved. The failures this exists to catch all produce a
tidy-looking directory and a green tick:

  * pg_dump connected, authenticated, and dumped an EMPTY schema list
  * the dump ran as a role that could not read most tables, so it
    contains a schema and almost no rows
  * `--schema=public` was used, so `auth.users` is absent -- restore it
    and nobody can log in, and every owner_id points at a ghost
  * RLS policies did not come across, so a restore stands up every
    customer's records with row-level security switched off
  * storage backed up 6 of 45 objects because the lister did not recurse

So this compares the artefact against the LIVE database rather than
against its own expectations, and fails loudly on any of them.

Usage:
  SUPABASE_ACCESS_TOKEN=... python scripts/verify_backup.py \
      --dump backup/db.sql --storage backup/storage
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "brqjgbpzackdihgjsorf")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        failures.append(label)
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{'' if ok or not detail else f'  <-- {detail}'}")


def live_query(sql: str) -> list[dict]:
    token = os.environ.get("SUPABASE_ACCESS_TOKEN") or ""
    if not token:
        raise RuntimeError("SUPABASE_ACCESS_TOKEN is required to verify against live")
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
        method="POST", data=json.dumps({"query": sql}).encode("utf-8"))
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))



def _q(schema: str, table: str) -> str:
    """Regex fragment matching schema.table with or without quoting."""
    return rf'"?{re.escape(schema)}"?\."?{re.escape(table)}"?'


def _mentions(sql: str, schema: str, table: str) -> bool:
    return re.search(_q(schema, table), sql) is not None


def _schema(sql: str, name: str) -> bool:
    return re.search(rf'CREATE SCHEMA (IF NOT EXISTS )?"?{re.escape(name)}"?',
                     sql) is not None


def _copy_rows(sql: str, schema: str, table: str):
    """Number of data rows in this table's COPY block, or None if the
    table has no COPY block at all.

    A COPY block runs from `COPY <table> (...) FROM stdin;` to a line
    containing only `\\.`. Every line between is one row.
    """
    m = re.search(rf'^COPY {_q(schema, table)}[^\n]*FROM stdin;$',
                  sql, re.MULTILINE)
    if not m:
        return None
    rows = 0
    for line in sql[m.end():].split("\n")[1:]:
        if line.strip() == "\\.":
            return rows
        rows += 1
    return rows


def read_dump(path: str) -> str:
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    with io.open(path, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--storage", required=True)
    # Storage tolerance: objects can legitimately be added or removed
    # between the storage pass and this one. A small drift is normal; a
    # large one means the lister broke.
    ap.add_argument("--storage-tolerance", type=int, default=3)
    args = ap.parse_args()

    # ── the dump ────────────────────────────────────────────────────
    check("the dump file exists", os.path.exists(args.dump), args.dump)
    if not os.path.exists(args.dump):
        return 1

    size = os.path.getsize(args.dump)
    check("the dump is not trivially small", size > 100_000, f"{size} bytes")

    sql = read_dump(args.dump)

    # auth.users is THE Supabase restore trap.
    #
    # These were substring checks for "auth.users" and they reported a
    # perfectly good backup as broken, because the dump is taken with
    # --quote-all-identifiers and therefore says "auth"."users". A check
    # that can be defeated by quoting was never checking the thing it
    # claimed to.
    #
    # Rather than loosen it, it now counts the ROWS in the auth.users
    # COPY block and compares them against live. Quoting cannot fool a
    # row count, and neither can a dump that emits the table definition
    # while silently skipping its data -- which is the failure that
    # actually matters, because it restores to a database that looks
    # complete and cannot log anybody in.
    check("the dump contains the auth schema",
          _mentions(sql, "auth", "users") or "CREATE SCHEMA" in sql and _schema(sql, "auth"),
          "no auth schema -- a restore from this cannot log anybody in")

    dumped_users = _copy_rows(sql, "auth", "users")
    live_users = live_query(
        "select count(*)::int as n from auth.users")[0]["n"]
    check("the dump carries every auth.users row",
          dumped_users is not None and dumped_users == live_users,
          f"{dumped_users} rows in dump vs {live_users} live -- "
          "accounts would restore missing or empty")

    # RLS is the difference between a restore and a data breach.
    policies_in_dump = sql.count("CREATE POLICY")
    live_policies = live_query(
        "select count(*)::int as n from pg_policies")[0]["n"]
    check("the dump carries the RLS policies",
          policies_in_dump >= live_policies * 0.9,
          f"{policies_in_dump} in dump vs {live_policies} live -- "
          "restoring this would drop row-level security")

    # Table coverage.
    tables_in_dump = sql.count("CREATE TABLE")
    live_tables = live_query(
        "select count(*)::int as n from information_schema.tables "
        "where table_schema in ('public','auth','storage')")[0]["n"]
    check("the dump covers the tables",
          tables_in_dump >= live_tables * 0.9,
          f"{tables_in_dump} in dump vs {live_tables} live")

    # Rows, not just shape. A schema-only dump passes everything above.
    check("the dump contains data, not just schema",
          "COPY " in sql or "INSERT INTO " in sql,
          "no COPY/INSERT anywhere -- this is a schema-only dump")

    # ── storage ─────────────────────────────────────────────────────
    manifest_path = os.path.join(args.storage, "manifest.json")
    check("the storage manifest exists", os.path.exists(manifest_path),
          manifest_path)
    if os.path.exists(manifest_path):
        with io.open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)

        check("the storage pass recorded no errors",
              not manifest.get("errors"),
              "; ".join(manifest.get("errors", [])[:3]))

        live_objects = live_query(
            "select count(*)::int as n from storage.objects")[0]["n"]
        got = manifest.get("total_objects", 0)
        check("storage backed up every object",
              abs(got - live_objects) <= args.storage_tolerance,
              f"{got} backed up vs {live_objects} live")

        # ...and the files are actually on disk, not just in the manifest.
        missing = 0
        for o in manifest.get("objects", []):
            p = os.path.join(args.storage, o["bucket"],
                             o["path"].replace("/", os.sep))
            if not os.path.exists(p):
                missing += 1
        check("every manifested object is on disk", missing == 0,
              f"{missing} listed but absent")

        check("storage bytes are non-zero",
              manifest.get("total_bytes", 0) > 0,
              "manifest says zero bytes")

    print()
    if failures:
        print(f"BACKUP NOT VERIFIED — {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("backup verified")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                       # noqa: BLE001
        # An exception here must not read as success.
        print(f"BACKUP NOT VERIFIED — verifier itself failed: {exc}",
              file=sys.stderr)
        sys.exit(2)

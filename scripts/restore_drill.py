#!/usr/bin/env python3
"""restore_drill.py — rehearse a recovery without risking the live one.

A backup nobody has restored is a hypothesis. This makes the rehearsal
repeatable, which is the difference between "we have backups" and "we
know what happens when we use them".

WHAT IT DOES

Copies a set of critical tables into an isolated `restore_drill` schema
inside the same database, compares row counts, and then reports what did
NOT come across. The schema is dropped at the end, and dropped again on
the way IN, so a crashed run cannot leave anything behind.

WHAT IT DELIBERATELY DOES NOT DO

It never calls POST /v1/projects/{ref}/restore. That endpoint restores
IN PLACE — it overwrites the live database with a backup. There is no
dry-run flag and no undo. Rehearsing a restore by performing one on
production is not a rehearsal.

WHY A DATA-ONLY COPY IS THE RIGHT THING TO REHEARSE

It models the recovery somebody actually reaches for under pressure:
"pull the rows across". The drill exists to show what that silently
leaves behind — on this database, 286 RLS policies and 488 indexes.
Restoring the data without the policies stands up every customer's
records with row-level security switched off.

A proper pg_restore of the physical backup DOES bring policies and
indexes. That path is Supabase's and is not exercised here; what this
proves is that the manual shortcut is not equivalent to it.

Usage:  SUPABASE_ACCESS_TOKEN=... python scripts/restore_drill.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "brqjgbpzackdihgjsorf")

# Representative rather than exhaustive: the tables whose loss would end
# the business, not the ones that are merely large.
CRITICAL_TABLES = [
    "businesses", "contacts", "invoices", "sessions",
    "credit_ledger", "ledger_entries", "business_users", "products",
]


def _query(sql: str):
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if not token:
        sys.exit("SUPABASE_ACCESS_TOKEN is not set")
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:300]}


def _scalar(sql: str, default=0):
    r = _query(sql)
    if isinstance(r, list) and r:
        return list(r[0].values())[0]
    return default


def main() -> int:
    print("RESTORE DRILL — isolated schema, dropped on entry and exit\n")

    # Dropped on the way IN as well as OUT: a run that died mid-drill must
    # not make the next one measure yesterday's leftovers.
    _query("drop schema if exists restore_drill cascade;")
    _query("create schema restore_drill;")

    started = time.time()
    restored, missing = [], []
    for table in CRITICAL_TABLES:
        res = _query(f"create table restore_drill.{table} "
                     f"as select * from public.{table};")
        if isinstance(res, dict) and res.get("error"):
            missing.append(table)
        else:
            restored.append(table)
    elapsed = time.time() - started

    if missing:
        print(f"  tables not present in public (skipped): {', '.join(missing)}")
    print(f"  recreated {len(restored)} tables in {elapsed:.1f}s\n")

    print(f"  {'table':<22}{'live':>8}{'restored':>10}   result")
    all_match = True
    for table in restored:
        live = _scalar(f"select count(*) from public.{table};")
        copy = _scalar(f"select count(*) from restore_drill.{table};")
        match = live == copy
        all_match &= match
        print(f"  {table:<22}{live:>8}{copy:>10}   {'OK' if match else 'MISMATCH'}")

    print(f"\n  every row count matches: {all_match}\n")

    print("  WHAT A DATA-ONLY RESTORE LEAVES BEHIND")
    checks = [
        ("RLS enabled tables",
         "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace "
         "where n.nspname='restore_drill' and c.relrowsecurity",
         "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace "
         "where n.nspname='public' and c.relrowsecurity"),
        ("RLS policies",
         "select count(*) from pg_policies where schemaname='restore_drill'",
         "select count(*) from pg_policies where schemaname='public'"),
        ("indexes",
         "select count(*) from pg_indexes where schemaname='restore_drill'",
         "select count(*) from pg_indexes where schemaname='public'"),
        ("PK / FK constraints",
         "select count(*) from information_schema.table_constraints "
         "where table_schema='restore_drill' and constraint_type in ('PRIMARY KEY','FOREIGN KEY')",
         "select count(*) from information_schema.table_constraints "
         "where table_schema='public' and constraint_type in ('PRIMARY KEY','FOREIGN KEY')"),
    ]
    for label, drill_sql, live_sql in checks:
        print(f"  {label:<22}{_scalar(drill_sql):>8}{_scalar(live_sql):>10}   "
              f"{'<-- LOST' if _scalar(drill_sql) == 0 else ''}")

    _query("drop schema if exists restore_drill cascade;")
    left = _scalar("select count(*) from information_schema.schemata "
                   "where schema_name='restore_drill';")
    print(f"\n  drill schema cleaned up: {left == 0}")

    # Non-zero exit if the drill itself failed, so this can gate CI later.
    return 0 if (all_match and left == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())

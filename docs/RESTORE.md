# Restoring the Solutionist database

Written 2026-08-10, after actually rehearsing it. Every number here was
measured, not estimated.

---

## What exists today

| | |
|---|---|
| physical backups (WAL-G) | **on** — daily, 6 retained |
| **PITR** | **OFF** |
| newest restore point | hours old (06:46 UTC on the day of writing) |
| retained window | 2026-08-03 → 2026-08-10, **2026-08-04 is missing** |
| database size | 44 MB, 171 tables |
| what a restore must bring back | 286 RLS policies, 488 indexes, 322 PK/FK constraints, 3 auth users |

**Worst-case data loss is up to 24 hours** — the gap between daily
backups. PITR would take that to minutes; it is a paid Supabase add-on
and the decision is Kevin's. That single fact is the whole difference
between "we lost this morning's bookings" and "we lost a minute".

The missing 2026-08-04 backup has never been explained. Backups being
present is not the same as backups being *complete*, and nothing was
watching the gap.

---

## The dangerous part, first

`POST /v1/projects/{ref}/restore` restores **IN PLACE**. It overwrites
the live database with a backup. There is no dry-run flag and no undo.

**Never run it to test anything.** Rehearsing a restore by performing
one on production is not a rehearsal, it is the outage.

`scripts/restore_drill.py` exists so the rehearsal can be repeated
safely, and it deliberately never touches that endpoint.

---

## Rehearsing it safely

```bash
SUPABASE_ACCESS_TOKEN=... python scripts/restore_drill.py
```

Copies the critical tables into an isolated `restore_drill` schema,
compares row counts, reports what did not come across, and drops the
schema — on the way in as well as out, so a crashed run cannot make the
next one measure yesterday's leftovers. Exits non-zero if anything
mismatched or the cleanup failed.

Last run: **8 tables, 3.3s, every row count matched.**

---

## What the rehearsal found

Row counts came back perfectly. Everything that protects those rows did
not:

| | restored | live |
|---|---|---|
| rows | all match | — |
| **RLS enabled tables** | **0** | 159 |
| **RLS policies** | **0** | 286 |
| **indexes** | **0** | 488 |
| **PK / FK constraints** | **0** | 322 |

This is the finding worth remembering. Under pressure the instinct is
"just pull the rows across" — and that reconstructs every customer's
records **with row-level security switched off**. Every tenant's data
readable by every other tenant, in a database that looks like it worked
because the counts are right.

A proper `pg_restore` of the physical backup *does* bring policies and
indexes. The shortcut does not, and the shortcut is what gets reached
for at 3am.

---

## What no database restore brings back

**Storage files.** `storage.objects` holds 43 rows of *metadata*; the
bytes live in S3. A database restore returns rows pointing at objects it
did not restore — client documents, proposals, site images. Verify the
storage side separately; it is not covered by the numbers above.

**Anything outside Postgres**: Railway env vars, the Stripe/Resend/Plaid
configuration, Vercel state.

---

## If a real restore is ever needed

1. **Stop the writers first.** Railway must not be appending to a
   database that is about to be rolled back, or the restore races the
   app and the result is neither state.
2. Restore via the Supabase dashboard (in-place) — take the most recent
   COMPLETED backup, and note its timestamp before starting.
3. Re-verify the security layer, do not assume it: `select count(*) from
   pg_policies where schemaname='public'` should be **286**, and
   `relrowsecurity` should be true on **159** tables. If those are zero,
   stop — the data is exposed.
4. Re-check storage separately (43 objects, 6 buckets;
   `business-documents` and `proposals` must be **private**).
5. Run the app's own readiness probe: `/health/ready` must report
   `ready:true, supabase:true`.

---

## Known gaps, stated plainly

- **PITR is off** — up to 24h of loss. Kevin's spend decision.
- **A full in-place restore has still never been performed.** This
  rehearsal proves the data is readable and copyable and that a naive
  copy is unsafe. It does *not* prove Supabase's own restore path works,
  because exercising that requires either downtime or a second project.
- **Backups are single-vendor.** There is no independent off-platform
  copy. If the Supabase account itself were lost, none of the above
  applies.
- **The 2026-08-04 gap is unexplained.**

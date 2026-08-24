# Backup and restore

What exists, what it does not cover, and what to actually do when
something is gone. Written 2026-08-23 from measured state, not from
intent.

## The shape of the data

| | size | where |
|---|---|---|
| Database | 49 MB, 186 tables | Supabase Postgres 17, `us-east-2` |
| Storage | 40 MB, 45 objects, 8 buckets | Supabase Storage (**separate**) |

~90 MB total. Small enough that a complete nightly copy is the right
answer and nothing clever is needed.

## Three layers

### 1. Supabase daily physical backups — already on

Daily, 7 retained, WAL-G, taken around 07:10 UTC. Nothing to configure.

**PITR is OFF.** Recovery granularity is therefore **24 hours**. This is
the sharpest edge in this system specifically, because Chief holds **137
write verbs** and not all writes are human-initiated: a bad autonomous
write at 14:00 can only be escaped by restoring to 07:10 and losing the
day. Turning PITR on (a paid Supabase add-on) closes it. Until then,
layer 2 is what narrows the window.

These backups **cannot**:
- survive losing the account — they live in it
- cover Storage
- reach back past 7 days

### 2. Nightly off-platform copy — `.github/workflows/backup.yml`

Runs **07:40 UTC**, on GitHub rather than Railway, for the same reason
`uptime.yml` does: a backup inside the thing being backed up is a single
point of failure wearing a seatbelt.

Each run dumps `public` + `auth` + `storage`, downloads every storage
object, **verifies the result against the live database**, encrypts, and
uploads.

**Destinations resolve by what is configured** — it works the moment it
merges and improves when you add a bucket:

1. S3-compatible (Backblaze B2 / S3 / R2) when `BACKUP_S3_*` are set
2. GitHub artifact otherwise — free and immediate, but **capped at 90
   days**, so it is a floor rather than a destination

Retention ladder (7 daily / 4 weekly / 12 monthly) lives on the **bucket
lifecycle rules**, not in the workflow, because a ladder implemented in a
workflow stops running the moment the workflow does.

### 3. Monthly restore drill — `.github/workflows/restore-drill.yml`

08:20 UTC on the 1st. Runs `scripts/restore_drill.py`, which existed and
was correct but was scheduled by nothing.

## Setup — what is still yours to do

The workflow **fails loudly** rather than producing an empty backup, so
until these exist it will open an issue every night.

**Required:**

| secret | where it comes from |
|---|---|
| `SUPABASE_DB_URL` | Supabase → Project Settings → Database → Connection string (URI). Use the **direct** connection, not the pooler — pooled connections cannot run `pg_dump`. |
| `SUPABASE_SERVICE_ROLE_KEY` | Project Settings → API → `service_role`. Reads private buckets. |
| `SUPABASE_ACCESS_TOKEN` | supabase.com/dashboard/account/tokens. Used to verify against live. |

**Strongly recommended:**

| secret | why |
|---|---|
| `BACKUP_AGE_PUBLIC_KEY` | The dump contains PII and Plaid-derived bank data. TINs are already encrypted by `tin_crypto`; nothing else is. Generate with `age-keygen -o key.txt` — the **public** key (`age1…`) goes here, the private key goes somewhere that is not this repo, or you cannot read your own backups. |

**Optional, for real retention:**

`BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`,
`BACKUP_S3_ENDPOINT` (B2/R2), `BACKUP_S3_REGION`.

## The two traps

Both produce a restore that looks like it worked.

**1. `auth` is a separate schema.** A `--schema=public` dump omits
`auth.users`. Restore it and nobody can log in, and every `owner_id`
points at a user that no longer exists. The workflow dumps `auth`
explicitly and `verify_backup.py` fails if `auth.users` rows are missing.

**2. Storage is two halves.** `storage.objects` rows are in the database
backup; the **files** are not. Restore the database alone and you get a
table full of working-looking references to nothing. Both halves or
neither.

## Restoring

### A few rows, or one table

Fastest path. Pull from the newest artifact:

```bash
tar -xzf solutionist-YYYY-MM-DD.tar.gz          # add `age -d` first if encrypted
grep -A100000 "COPY \"public\".\"contacts\"" db.sql | head -100
```

### The whole database

**Prefer Supabase's own physical backup** (Dashboard → Database →
Backups → Restore). It brings policies, indexes and constraints. The
drill exists precisely to show that the manual shortcut does not:

> a data-only copy leaves behind **316 RLS policies, 544 indexes and 358
> constraints** (measured 2026-08-23)

Restoring data without policies stands up every customer's records with
row-level security switched off. If you ever restore from `db.sql`
instead, restore the **whole file** — schema, policies and all — into an
empty database. Never cherry-pick tables into a live one.

Supabase's restore is **in place and has no undo**. Take a fresh backup
first if the current state has anything worth keeping.

### Storage

```bash
# per bucket, from the extracted backup/storage/<bucket>/…
supabase storage cp -r ./storage/business-documents \
    ss:///business-documents --experimental
```

`manifest.json` holds a sha256 per object — verify before trusting.

## What this does not protect against

- **Between 07:40 runs.** Worst case ~24h of loss, same as Supabase's
  own. PITR is the fix.
- **A bad write you do not notice for months.** The monthly rung reaches
  12 months; past that, nothing.
- **The action ledger's hash chain and Hedera anchoring are integrity,
  not recovery.** They prove data was not altered. They cannot bring it
  back. Easy to feel covered by them and not be.

## Targets

| | current | with PITR |
|---|---|---|
| RPO (data you can lose) | ~24 h | ~2 min |
| RTO (time to be back) | ~1 h, untested end-to-end | ~1 h |

RTO is honest rather than measured — the drill proves the data copies
and what a shortcut loses, not a full wall-clock recovery. That is the
next thing worth rehearsing.

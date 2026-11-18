-- APPLY-2026-11-17-church-jobs.sql
--
-- A church's own jobs, and the record of who changed a person's sheet
-- (church_job_defs.py, church_sheet.py, chief_church_sheet.py). Kevin,
-- 2026-11-17, on "One sheet per person" (artifact WE3jy89EXadQSjz9t8A2FV):
-- "yes to all and build it. also allow for custom roles to be set that way,
-- it becomes easy for other churches to set there own leadership flow", then
-- "also allow for permission to be given to a person to create roles like how
-- my wife over administration team".
--
-- church_jobs (server-only: RLS on, no policies, browser roles revoked): a
-- job a church made beside the five starting ones (church_areas.LANES).
--   key            a slug, unique in the church for good (a removed job
--                  keeps its key, so a login that held it still reads as its
--                  title); business_users.lane carries it
--   label          the job's title, 2 to 60
--   does           one line of what it does, 240 at most
--   description    the job in the church's words, 8000 at most; null = none
--   role           the login the job is: viewer | member | manager | admin
--                  (an Admin job is the owner's alone to make)
--   areas          the areas it works (church_areas.AREAS keys); empty for
--                  an Admin job, which sees the whole church
--   duties         the duties it starts with (church_duties.CATALOG keys)
--   deleted_at     when it was taken off the list (never hard-deleted)
-- A job is a label and a starting point: saving, changing or removing one
-- never changes a login that already holds it.
--
-- church_sheet_changes (server-only, the same): one line a change.
--   kind             sheet | job
--   subject_user_id  whose sheet (kind sheet)
--   job_key          which job (kind job)
--   changed_by, changed_at, summary ("changed Tiara Adams's sheet: added
--                    Kids & youth"), detail (what was sent)
-- No foreign key on the logins: a login that leaves leaves the record.
--
-- Nothing here for who "sets up jobs and people's sheets": that grant is a
-- row in church_duty_holders under the key jobs_and_sheets (the duties' own
-- table, which already logs who gave what to whom in church_duty_changes).
--
-- New tables only: one transaction, safe to run twice, nothing dropped. Apply
-- any time: until then the code reads "no custom jobs" (the five starting
-- jobs still work, and every sheet still opens and saves), a write to a job
-- answers 503 "Custom jobs are being switched on", and a change's record is
-- skipped.
begin;

set local lock_timeout = '5s';

create table if not exists public.church_jobs(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  key text not null,
  label text not null,
  does text not null default '',
  description text,
  role text not null default 'manager',
  areas text[] not null default '{}',
  duties text[] not null default '{}',
  created_by uuid,
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.church_sheet_changes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null,
  subject_user_id uuid,
  job_key text,
  changed_by uuid,
  changed_at timestamptz not null default now(),
  summary text not null default '',
  detail jsonb not null default '{}'::jsonb
);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'church_jobs_key_shape'
                 and conrelid = 'public.church_jobs'::regclass) then
    alter table public.church_jobs
      add constraint church_jobs_key_shape check (key ~ '^[a-z][a-z0-9_]{1,39}$') not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_jobs_label_length'
                 and conrelid = 'public.church_jobs'::regclass) then
    alter table public.church_jobs
      add constraint church_jobs_label_length check (char_length(label) between 2 and 60) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_jobs_does_length'
                 and conrelid = 'public.church_jobs'::regclass) then
    alter table public.church_jobs
      add constraint church_jobs_does_length check (char_length(does) <= 240) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_jobs_description_length'
                 and conrelid = 'public.church_jobs'::regclass) then
    alter table public.church_jobs
      add constraint church_jobs_description_length
        check (description is null or char_length(description) between 1 and 8000) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_jobs_role'
                 and conrelid = 'public.church_jobs'::regclass) then
    alter table public.church_jobs
      add constraint church_jobs_role check (role in ('viewer', 'member', 'manager', 'admin')) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_sheet_changes_kind'
                 and conrelid = 'public.church_sheet_changes'::regclass) then
    alter table public.church_sheet_changes
      add constraint church_sheet_changes_kind check (kind in ('sheet', 'job')) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_sheet_changes_summary_length'
                 and conrelid = 'public.church_sheet_changes'::regclass) then
    alter table public.church_sheet_changes
      add constraint church_sheet_changes_summary_length check (char_length(summary) <= 500) not valid;
  end if;
end $$;

-- One key a church, for good: a removed job keeps its key.
create unique index if not exists church_jobs_business_key on public.church_jobs(business_id, key);
create index if not exists church_sheet_changes_business_at
  on public.church_sheet_changes(business_id, changed_at desc);

alter table public.church_jobs enable row level security;
alter table public.church_sheet_changes enable row level security;
revoke all on public.church_jobs from public, anon, authenticated;
revoke all on public.church_sheet_changes from public, anon, authenticated;
grant all on public.church_jobs to service_role;
grant all on public.church_sheet_changes to service_role;

commit;

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--     from pg_class c
--    where c.oid in ('public.church_jobs'::regclass, 'public.church_sheet_changes'::regclass)
--    order by c.relname;
--   -- 2 rows, each: true, 0, false, false
--   select count(*) from pg_indexes where schemaname = 'public'
--      and indexname in ('church_jobs_business_key', 'church_sheet_changes_business_at');
--   -- 2
--   select conname, convalidated from pg_constraint
--    where conrelid in ('public.church_jobs'::regclass, 'public.church_sheet_changes'::regclass)
--      and contype = 'c' order by conname;
--   -- 7 rows, each false (NOT VALID: enforced on every new write)
--
-- Rollback (loses every job a church made and the record of sheet changes; logins that held one of those jobs
-- keep their areas and duties and read as having no job):
--   drop table if exists public.church_sheet_changes;
--   drop table if exists public.church_jobs;

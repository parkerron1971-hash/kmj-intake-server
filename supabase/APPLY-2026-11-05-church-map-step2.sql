-- The church leaders map, step 2 (docs/CHURCH_LEADERS_STEP2.md §1.2, §1.3, PR
-- B2; Kevin approved the design 2026-11-03, artifact 4V41zJz1kEJGdeo4J9D2Ym,
-- "Your two ideas"). Step 1 made each church's leaders structure data; step 2
-- makes that map easy for any church to set up and change: setup sessions
-- with Chief, a ready-made directory, Chief's changes with Undo, drafts for new
-- churches. This file adds the data. Nothing reads it until B3a
-- (church_map_batch) and CHURCH_MAP / CHURCH_SETUP open, so day one changes
-- nothing.
--
--   church_departments      template_key, template_version: the ready-made a
--                           copy came from (null = the church's own; the
--                           platform never writes the row again).
--                           unfinished_at: a save that failed half-way
--                           (church_map.save_department's failure path sets
--                           it from B3b; the retry finishes the department
--                           and clears it). Backfilled once, below.
--   church_role_defs        template_key, template_version, as above. The
--                           source check gains 'template' and keeps catalog,
--                           custom, legacy and chief. Its real name is
--                           church_role_defs_source_check: the name Postgres
--                           gave the inline check in
--                           APPLY-2026-10-17-church-role-library.sql:50.
--   church_role_settings    seeded_as ('active' or 'draft'; every church today
--                           is 'active', so already confirmed), confirmed_at,
--                           shape_key and shape_version (the ready-made shape
--                           a church started from). A library is unconfirmed
--                           exactly when seeded_as = 'draft' and confirmed_at
--                           is null.
--   church_map_changes      every change to a map, one row a change, each part
--                           with its before and after (§4.1): pending, applied,
--                           undone, discarded or failed. An undo is a change
--                           too (undoes = the one it put back, which gets
--                           undone_at). `money` marks a change only the owner
--                           may apply, undo or launch.
--   church_setup_tracks     a church's setup sessions with Chief, one row a
--                           church (§3), read only through GET /church/setup.
--
-- Not made for any church, Love City included: a change, a track, a template
-- mark, a draft library. Every church already seeded reads as confirmed.
--
-- Server-only: both new tables RLS on with no policies, anon and authenticated
-- revoked, service_role granted. No trigger or function is added or changed.
-- Additive and idempotent: each column, constraint and the backfill is
-- guarded, so a second run changes nothing, schema or data, and drops nothing.
-- Applied by hand after review, before B3a merges.
begin;

-- Fail fast rather than queue behind a long read of a church table (a waiting
-- ACCESS EXCLUSIVE lock would stall every query behind it). Re-run if it times out.
set local lock_timeout = '5s';

-- ─── Departments: where a copy came from; a save that didn't finish ─────

-- An office draft with nothing hung from it can only be a half-made save: a
-- new department is saved active, and save_department marks one a draft only
-- when its units failed and taking it back out failed too
-- (church_map.py:810-821). No screen or Chief verb saves a department yet (the
-- sheet is F2/F3, the verbs B5), so only a hand-made API call could have saved
-- one as a draft on purpose; the ledger's pre-check lists every row this marks.
-- Marked once, as the column is added, so a later run never marks a draft a
-- church saves on purpose after B3b.
do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_departments' and column_name = 'template_key') then
    alter table public.church_departments add column template_key text
      constraint church_departments_template_key_shape check (template_key ~ '^[a-z0-9_.]{2,60}$');
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_departments' and column_name = 'template_version') then
    alter table public.church_departments add column template_version smallint
      constraint church_departments_template_version_range check (template_version between 1 and 999);
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_departments' and column_name = 'unfinished_at') then
    alter table public.church_departments add column unfinished_at timestamptz;
    update public.church_departments d set unfinished_at = d.updated_at
     where d.status = 'draft' and d.source = 'office' and d.unfinished_at is null
       and not exists (select 1 from public.church_department_units u where u.department_id = d.id);
  end if;
end $$;

-- ─── Roles: where a copy came from; 'template' as a source ──────────────

-- The source check is swapped once: a second run finds 'template' in it and
-- leaves it. Any other check on source (a name this file doesn't know) stops
-- the file rather than leave a second check that would still refuse
-- 'template'. Every existing row already fits the wider check.
do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_role_defs' and column_name = 'template_key') then
    alter table public.church_role_defs add column template_key text
      constraint church_role_defs_template_key_shape check (template_key ~ '^[a-z0-9_.]{2,60}$');
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_role_defs' and column_name = 'template_version') then
    alter table public.church_role_defs add column template_version smallint
      constraint church_role_defs_template_version_range check (template_version between 1 and 999);
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.church_role_defs'::regclass
                   and conname = 'church_role_defs_source_check'
                   and pg_get_constraintdef(oid) like '%''template''%') then
    alter table public.church_role_defs drop constraint if exists church_role_defs_source_check;
    if exists (select 1 from pg_constraint where conrelid = 'public.church_role_defs'::regclass
                 and contype = 'c' and pg_get_constraintdef(oid) ~ '\msource\M') then
      raise exception 'church_role_defs has a check on source this file does not know; read it before applying';
    end if;
    alter table public.church_role_defs add constraint church_role_defs_source_check
      check (source in ('catalog', 'custom', 'legacy', 'chief', 'template'));
  end if;
end $$;

-- ─── Church settings: a library seeded as drafts, and its shape ─────────

do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_role_settings' and column_name = 'seeded_as') then
    alter table public.church_role_settings add column seeded_as text not null default 'active'
      constraint church_role_settings_seeded_as_known check (seeded_as in ('active', 'draft'));
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_role_settings' and column_name = 'confirmed_at') then
    alter table public.church_role_settings add column confirmed_at timestamptz;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_role_settings' and column_name = 'shape_key') then
    alter table public.church_role_settings add column shape_key text
      constraint church_role_settings_shape_key_shape check (shape_key ~ '^[a-z0-9_]{2,40}$');
  end if;
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_role_settings' and column_name = 'shape_version') then
    alter table public.church_role_settings add column shape_version smallint
      constraint church_role_settings_shape_version_range check (shape_version between 1 and 999);
  end if;
end $$;

-- ─── Every change to a map ──────────────────────────────────────────────

-- One row a change, each part {kind, id, before, after}: before null means the
-- change made the thing, after null that it archived it. The jsonb checks are
-- CASEs so a part list that isn't a list is refused by its check, not by
-- jsonb_array_length's error.
create table if not exists public.church_map_changes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  status text not null check (status in ('pending', 'applied', 'undone', 'discarded', 'failed')),
  origin text not null check (origin in ('office', 'chief', 'session', 'template', 'launch')),
  phase text check (phase in ('church', 'ministries', 'leaders', 'shepherding', 'office_help', 'rhythm_launch')),
  said text not null default '' check (char_length(said) <= 400),
  parts jsonb not null check (case when jsonb_typeof(parts) = 'array'
                                   then jsonb_array_length(parts) between 1 and 80 else false end),
  money boolean not null default false,
  made_by uuid references auth.users(id) on delete set null,
  made_at timestamptz not null default now(),
  applied_by uuid references auth.users(id) on delete set null,
  applied_at timestamptz,
  undoes uuid references public.church_map_changes(id) on delete set null,
  undone_at timestamptz,
  error text not null default '' check (char_length(error) <= 400),
  constraint church_map_changes_applied check (status not in ('applied', 'undone') or applied_at is not null)
);
create index if not exists church_map_changes_recent on public.church_map_changes(business_id, made_at desc);
create index if not exists church_map_changes_pending on public.church_map_changes(business_id) where status = 'pending';
-- The undo link's foreign key: deleting a church's changes sets each undo's
-- link to null, and without this every deleted row would scan the table.
create index if not exists church_map_changes_undoes on public.church_map_changes(undoes) where undoes is not null;

-- ─── A church's setup sessions, one row a church ────────────────────────

create table if not exists public.church_setup_tracks(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  status text not null default 'in_progress' check (status in ('in_progress', 'launched')),
  started_from text not null default 'blank' check (started_from ~ '^(blank|live|shape:[a-z0-9_]{2,40})$'),
  current_phase text not null default 'church'
    check (current_phase in ('church', 'ministries', 'leaders', 'shepherding', 'office_help', 'rhythm_launch')),
  phases jsonb not null default '{}' check (jsonb_typeof(phases) = 'object'),     -- {phase: {state, at, note}}
  asks jsonb not null default '[]' check (case when jsonb_typeof(asks) = 'array'
                                              then jsonb_array_length(asks) <= 200 else false end),
  rhythm jsonb not null default '{}' check (jsonb_typeof(rhythm) = 'object'),
  session_log jsonb not null default '[]' check (jsonb_typeof(session_log) = 'array'),
  turns smallint not null default 0 check (turns between 0 and 999),
  launched_at timestamptz,
  launched_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Server-only: RLS on, browser roles revoked, service role granted, no policies.
do $$ declare t text; begin
  foreach t in array array['church_map_changes', 'church_setup_tracks'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

notify pgrst, 'reload schema';

commit;

-- Check after applying (the 9 new columns; 'template' in the source check;
-- both new tables RLS on with no policies and no browser select; the
-- departments the backfill marked, which must be the pre-check's list):
--   select table_name, column_name, data_type, is_nullable, column_default from information_schema.columns
--    where table_schema = 'public' and (table_name, column_name) in (
--      ('church_departments','template_key'), ('church_departments','template_version'),
--      ('church_departments','unfinished_at'), ('church_role_defs','template_key'),
--      ('church_role_defs','template_version'), ('church_role_settings','seeded_as'),
--      ('church_role_settings','confirmed_at'), ('church_role_settings','shape_key'),
--      ('church_role_settings','shape_version'));   -- 9 rows
--   select pg_get_constraintdef(oid) from pg_constraint
--    where conrelid = 'public.church_role_defs'::regclass and conname = 'church_role_defs_source_check';
--     -- catalog, custom, legacy, chief, template
--   select c.relname, c.relrowsecurity, (select count(*) from pg_policies p where p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads
--     from pg_class c where c.relname in ('church_map_changes', 'church_setup_tracks') order by 1;   -- RLS on, 0, false
--   select business_id, id, name, unfinished_at from church_departments where unfinished_at is not null order by 1, 3;
--
-- Rollback, only after the code that reads these is gone. It drops the change
-- log, the setup sessions and the template marks, with whatever the churches
-- put in them; a library seeded as drafts (B7) would read as confirmed. Only
-- while no role says 'template': the old source check goes back as it was, so
-- a role made from a ready-made makes the rollback fail rather than lose it.
--   begin;
--   drop table if exists public.church_setup_tracks;
--   drop table if exists public.church_map_changes;
--   alter table public.church_role_settings drop column if exists seeded_as, drop column if exists confirmed_at,
--     drop column if exists shape_key, drop column if exists shape_version;
--   alter table public.church_role_defs drop constraint if exists church_role_defs_source_check;
--   alter table public.church_role_defs add constraint church_role_defs_source_check
--     check (source in ('catalog', 'custom', 'legacy', 'chief'));
--   alter table public.church_role_defs drop column if exists template_key, drop column if exists template_version;
--   alter table public.church_departments drop column if exists template_key,
--     drop column if exists template_version, drop column if exists unfinished_at;
--   notify pgrst, 'reload schema';
--   commit;

-- APPLY-2026-11-20-church-schedule-limits.sql
--
-- The leaders schedule, step 2: the tables for the limit on how many can be
-- away at once (docs/CHURCH_SCHEDULE.md, PR S2-1). Nothing reads them yet;
-- church_schedule_limits.py comes in the PRs after this one. The platform
-- owner, 2026-11-18: "making sure that everyone is not gone at the same time
-- on our services. allowing only so many people off at the same time."
--
-- Run it after APPLY-2026-11-19-church-schedule.sql (step 1, applied
-- 2026-11-18). What is new:
--
--   church_schedule_settings.leaders_limit / office_limit
--                           how many of each group may be away on one service
--                           date (null = worked out: one in four, one at least)
--   church_schedule_settings.service_weekdays
--                           the church's usual service days, 1 Monday … 7
--                           Sunday (null = worked out from its own plans,
--                           else Sunday)
--   church_schedule_department_limits
--                           one number a department. No row = no limit.
--   church_protected_days   a day nobody takes off: one row a date a church,
--                           with a short name
--   church_away_pairs       two people who can't be away together: one row a
--                           pair, the smaller id first. Private: only the
--                           owner and whoever oversees the office read them.
--   church_away_asks.excepted
--                           the flags a yes was given over (over the limit, a
--                           protected day, a pair): the exception. Only ever
--                           on a yes; decided_by says who gave it.
--   church_away_asks.team_group_id
--                           a volunteer's ask: the team whose leader it went to
--   church_away_settle_excepted()
--                           the same decision as church_away_settle, with the
--                           exception a yes was given over (a seventh
--                           argument, '{}' when left out)
--
-- THE DECISION FUNCTION: WHAT WAS CHOSEN, AND WHY
--
-- Step 1's church_away_settle (six arguments) is live and is being called by
-- deployed code. This file does not touch it: not its body, not its
-- arguments, not its grants. The exception gets a function of its own name,
-- church_away_settle_excepted, which calls church_away_settle for the
-- decision and then, for a yes it just made, records the exception on the
-- ask. One statement, so one transaction: if the exception is refused the
-- yes and its away date are undone with it. There is still one place the
-- decision is made, so the two can't drift apart.
--
-- The two other ways were run on a real Postgres (the check keeps both
-- runs) and turned down:
--
--   1. Two functions of the same name, the new one with a seventh argument
--      that has a default. Postgres itself then refuses every call that
--      leaves the seventh out ("function church_away_settle(p_business_id =>
--      uuid, …) is not unique"), and by its own rule PostgREST refuses it
--      before that (PGRST203: it picks by argument names and both match).
--      Every answer at the live church would fail.
--   2. Dropping the six-argument function and making a seven-argument one of
--      the same name in this transaction. It works on the day (a
--      six-argument call lands on the new function through the default). But
--      it takes a live function away to do it, and it leaves a trap: step 1's
--      file is safe to run twice and makes the six-argument function again,
--      so running it once more after this one would bring back case 1 and
--      break every answer until someone noticed. With two names there is no
--      order of running the two files, however many times, that leaves two
--      functions for one name.
--
-- So after this file there are two functions on purpose, one a name:
-- church_away_settle(6 arguments), exactly as step 1 left it, and
-- church_away_settle_excepted(7 arguments). Neither is overloaded, so
-- neither a six-name nor a seven-name call has anything to choose between.
--
-- Server-only: every new table RLS on with no policies, anon and
-- authenticated revoked, service_role granted; every function revoked from
-- public, anon and authenticated. One transaction, lock_timeout 5s, safe to
-- run twice. Additive: no table, column, function or row is dropped or
-- rewritten (this file's own triggers are dropped and made again, as every
-- file here does). The new columns are null, or '{}' by a constant default,
-- on every row that exists, so no row is rewritten. serve_away is not
-- touched at all. The three checks and the one foreign key added to
-- church_away_asks and church_schedule_settings are checked as they go in:
-- both tables are days old and open at one church, every row in them
-- passes, and the look is over in a moment. The foreign key takes a short
-- lock on groups and reads none of it. Ends with NOTIFY pgrst so the API
-- sees the tables and the function at once.
--
-- Safe before the code that reads it: the deployed code names every column
-- it reads and never sends the new ones, so an ask, an answer, a take-back,
-- the notices and Who serves when all work as they did the moment this runs.
begin;

set local lock_timeout = '5s';

-- ─── The church's numbers and its usual service days ────────────────────

alter table public.church_schedule_settings
  add column if not exists leaders_limit smallint,
  add column if not exists office_limit smallint,
  add column if not exists service_weekdays smallint[];

-- ─── The ask: the exception, and a volunteer's team ─────────────────────

alter table public.church_away_asks
  add column if not exists excepted text[] not null default '{}',
  add column if not exists team_group_id uuid;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'church_schedule_settings_limits'
                   and conrelid = 'public.church_schedule_settings'::regclass) then
    alter table public.church_schedule_settings add constraint church_schedule_settings_limits
      check ((leaders_limit is null or leaders_limit between 1 and 99)
             and (office_limit is null or office_limit between 1 and 99));
  end if;
  -- A plain list of days, 1 to 7: never empty, never a list of lists.
  if not exists (select 1 from pg_constraint where conname = 'church_schedule_settings_weekdays'
                   and conrelid = 'public.church_schedule_settings'::regclass) then
    alter table public.church_schedule_settings add constraint church_schedule_settings_weekdays
      check (service_weekdays is null
             or (array_ndims(service_weekdays) = 1
                 and cardinality(service_weekdays) between 1 and 7
                 and service_weekdays <@ array[1, 2, 3, 4, 5, 6, 7]::smallint[]));
  end if;
  -- An exception is for a flag the ask has, never for short notice or
  -- serving, and it only ever sits on a yes (or on a yes that was taken
  -- back, which keeps it).
  if not exists (select 1 from pg_constraint where conname = 'church_away_asks_excepted'
                   and conrelid = 'public.church_away_asks'::regclass) then
    alter table public.church_away_asks add constraint church_away_asks_excepted
      check (excepted <@ array['over_limit', 'protected_day', 'pair']::text[]
             and excepted <@ flags
             and (cardinality(excepted) = 0 or state in ('yes', 'withdrawn')));
  end if;
  -- A team deleted leaves the ask, with no team.
  if not exists (select 1 from pg_constraint where conname = 'church_away_asks_team_group_id_fkey'
                   and conrelid = 'public.church_away_asks'::regclass) then
    alter table public.church_away_asks add constraint church_away_asks_team_group_id_fkey
      foreign key (team_group_id) references public.groups(id) on delete set null;
  end if;
end $$;

-- ─── One number a department ────────────────────────────────────────────

create table if not exists public.church_schedule_department_limits(
  department_id uuid primary key references public.church_departments(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  at_most smallint not null check (at_most between 1 and 99),
  set_by_user_id uuid references auth.users(id) on delete set null,
  set_by_contact_id uuid references public.contacts(id) on delete set null,
  updated_at timestamptz not null default now(),
  constraint church_schedule_department_limits_by_one
    check (set_by_user_id is null or set_by_contact_id is null)
);
create index if not exists church_schedule_department_limits_by_church
  on public.church_schedule_department_limits (business_id);

-- ─── A day nobody takes off ─────────────────────────────────────────────

create table if not exists public.church_protected_days(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  day date not null,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
create unique index if not exists church_protected_days_one
  on public.church_protected_days (business_id, day);

-- ─── Two people who can't be away together ──────────────────────────────

-- One row a pair: the smaller id is a_contact_id, so the same two people
-- can't be saved the other way round, and nobody is paired with themself.
-- Postgres orders two uuids as their lower-case text orders, so the server
-- sorts the two ids as text before it writes.
create table if not exists public.church_away_pairs(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  a_contact_id uuid not null references public.contacts(id) on delete cascade,
  b_contact_id uuid not null references public.contacts(id) on delete cascade,
  note text check (note is null or char_length(note) <= 140),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  constraint church_away_pairs_ordered check (a_contact_id < b_contact_id)
);
create unique index if not exists church_away_pairs_one
  on public.church_away_pairs (business_id, a_contact_id, b_contact_id);
create index if not exists church_away_pairs_b on public.church_away_pairs (business_id, b_contact_id);

-- ─── Everything named is the church's own ───────────────────────────────

-- A department's number names this church's department, and the person who
-- set it is this church's; a pair is two of this church's people; a
-- volunteer's ask names one of this church's groups. Each is checked only
-- when a write names it: a foreign key setting one of them null (a person
-- removed, a team deleted, a church going) checks nothing. Each table's
-- checks sit under its own table test, because the other tables' columns
-- aren't there to read.
create or replace function public.church_schedule_limits_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'church_schedule_department_limits' then
    if tg_op = 'INSERT' or new.department_id is distinct from old.department_id
       or new.business_id is distinct from old.business_id then
      if not exists (select 1 from public.church_departments d
                     where d.id = new.department_id and d.business_id = new.business_id) then
        raise exception 'That department is not in this church';
      end if;
    end if;
    if new.set_by_contact_id is not null
       and (tg_op = 'INSERT' or new.set_by_contact_id is distinct from old.set_by_contact_id
            or new.business_id is distinct from old.business_id) then
      if not exists (select 1 from public.contacts c
                     where c.id = new.set_by_contact_id and c.business_id = new.business_id) then
        raise exception 'The person who set it is not in this church';
      end if;
    end if;
  end if;
  if tg_table_name = 'church_away_pairs' then
    if tg_op = 'INSERT' or new.a_contact_id is distinct from old.a_contact_id
       or new.b_contact_id is distinct from old.b_contact_id
       or new.business_id is distinct from old.business_id then
      if (select count(*) from public.contacts c
           where c.id in (new.a_contact_id, new.b_contact_id) and c.business_id = new.business_id) <> 2 then
        raise exception 'A pair is two people in this church';
      end if;
    end if;
  end if;
  if tg_table_name = 'church_away_asks' then
    if new.team_group_id is not null
       and (tg_op = 'INSERT' or new.team_group_id is distinct from old.team_group_id) then
      if not exists (select 1 from public.groups g
                     where g.id = new.team_group_id and g.business_id = new.business_id) then
        raise exception 'That team is not in this church';
      end if;
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_schedule_limits_same_business() from public, anon, authenticated;

drop trigger if exists church_schedule_limits_same_business on public.church_schedule_department_limits;
create trigger church_schedule_limits_same_business
  before insert or update of department_id, business_id, set_by_contact_id
  on public.church_schedule_department_limits
  for each row execute function public.church_schedule_limits_same_business();
drop trigger if exists church_schedule_limits_same_business on public.church_away_pairs;
create trigger church_schedule_limits_same_business
  before insert or update of a_contact_id, b_contact_id, business_id on public.church_away_pairs
  for each row execute function public.church_schedule_limits_same_business();
-- An ask can't change its church (step 1's trigger), so its team is checked
-- when the team is written.
drop trigger if exists church_away_asks_team_same_business on public.church_away_asks;
create trigger church_away_asks_team_same_business
  before insert or update of team_group_id on public.church_away_asks
  for each row execute function public.church_schedule_limits_same_business();

-- ─── The decision, with the exception a yes was given over ──────────────

-- church_away_settle makes the decision, exactly as it does when it is
-- called alone: the same answers ({"changed": …, "ask": …}, or null when
-- this church has no such ask), the same refusals, and it never makes a fact
-- again for an ask that is already a yes. Then, only for a yes it just made
-- and only when an exception was passed, the exception is saved on the ask:
-- each flag once, in order. A no, a take-back, an ask that had already moved
-- on and an empty exception all come back as church_away_settle answered
-- them, with nothing more written. An exception for a flag the ask doesn't
-- have is refused by name, and the yes and its away date go with it.
create or replace function public.church_away_settle_excepted(
  p_business_id uuid, p_ask_id uuid, p_state text,
  p_by_user uuid default null, p_by_contact uuid default null, p_note text default null,
  p_excepted text[] default '{}')
returns jsonb
language plpgsql set search_path = public as $$
declare
  r jsonb;
  v public.church_away_asks;
  x text[] := array(select distinct e from unnest(coalesce(p_excepted, '{}')) e order by e);
begin
  r := public.church_away_settle(p_business_id, p_ask_id, p_state, p_by_user, p_by_contact, p_note);
  if r is null or p_state <> 'yes' or cardinality(x) = 0 or not (r->>'changed')::boolean then
    return r;
  end if;
  if not (x <@ array['over_limit', 'protected_day', 'pair']::text[]
          and x <@ array(select jsonb_array_elements_text(r->'ask'->'flags'))) then
    raise exception 'An exception is for a flag the ask has: over the limit, a protected day or a pair';
  end if;
  update public.church_away_asks a
     set excepted = x
   where a.id = p_ask_id and a.business_id = p_business_id returning * into v;
  return jsonb_build_object('changed', true, 'ask', to_jsonb(v));
end $$;
revoke all on function public.church_away_settle_excepted(uuid, uuid, text, uuid, uuid, text, text[]) from public, anon, authenticated;
grant execute on function public.church_away_settle_excepted(uuid, uuid, text, uuid, uuid, text, text[]) to service_role;

-- ─── Server-only ────────────────────────────────────────────────────────

do $$ declare t text; begin
  foreach t in array array['church_schedule_department_limits', 'church_protected_days', 'church_away_pairs'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

comment on column public.church_schedule_settings.leaders_limit is
  'The leaders schedule: how many of the leaders group may be away on one service date. Null = worked out (one in four, one at least).';
comment on column public.church_schedule_settings.office_limit is
  'The leaders schedule: how many of the office group may be away on one service date. Null = worked out (one in four, one at least).';
comment on column public.church_schedule_settings.service_weekdays is
  'The leaders schedule: the church''s usual service days (1 Monday … 7 Sunday), for dates with no service planned yet. Null = worked out from its own plans, else Sunday.';
comment on table public.church_schedule_department_limits is
  'The leaders schedule: how many of a department''s people may be away on one service date. No row = no limit. Server-only (RLS on, no policies).';
comment on table public.church_protected_days is
  'The leaders schedule: a day nobody takes off (one row a date a church). Only the owner or whoever oversees the office says yes to an ask on one. Server-only.';
comment on table public.church_away_pairs is
  'The leaders schedule: two people who can''t be away together (a_contact_id < b_contact_id, one row a pair). Private: read only by the owner and whoever oversees the office, and never named to anyone else. Server-only.';
comment on column public.church_away_pairs.note is
  'Private, like the pair itself.';
comment on column public.church_away_asks.excepted is
  'The flags (over_limit, protected_day, pair) a yes was given over: the exception. Only on a yes, or a yes taken back. decided_by says who gave it. Written by church_away_settle_excepted.';
comment on column public.church_away_asks.team_group_id is
  'A volunteer''s ask: the team whose leader it went to (the ask''s own church''s).';
comment on function public.church_away_settle_excepted(uuid, uuid, text, uuid, uuid, text, text[]) is
  'The leaders schedule: church_away_settle, then the exception a yes was given over saved on the ask, in one transaction. church_away_settle itself is unchanged and still makes every decision.';

commit;

notify pgrst, 'reload schema';

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--     from pg_class c where c.relnamespace = 'public'::regnamespace
--      and c.relname in ('church_schedule_department_limits','church_protected_days','church_away_pairs')
--    order by c.relname;
--   -- 3 rows: true, 0, false, false
--   select table_name, column_name from information_schema.columns
--    where table_schema = 'public'
--      and ((table_name = 'church_schedule_settings' and column_name in ('leaders_limit','office_limit','service_weekdays'))
--        or (table_name = 'church_away_asks' and column_name in ('excepted','team_group_id')))
--    order by table_name, column_name;
--   -- 5 rows: church_away_asks excepted, team_group_id; church_schedule_settings leaders_limit, office_limit, service_weekdays
--   select conname, convalidated from pg_constraint
--    where conname in ('church_schedule_settings_limits','church_schedule_settings_weekdays',
--                      'church_away_asks_excepted','church_away_asks_team_group_id_fkey')
--    order by conname;
--   -- 4 rows, convalidated true
--   select p.proname, p.pronargs,
--          has_function_privilege('authenticated', p.oid, 'execute') as browser_runs,
--          has_function_privilege('anon', p.oid, 'execute') as anon_runs,
--          has_function_privilege('service_role', p.oid, 'execute') as server_runs
--     from pg_proc p where p.pronamespace = 'public'::regnamespace
--      and p.proname in ('church_away_settle','church_away_settle_excepted')
--    order by p.proname;
--   -- exactly 2 rows, one a name: church_away_settle 6, church_away_settle_excepted 7; each false, false, true
--   select count(*) from church_away_asks where excepted <> '{}' or team_group_id is not null;
--   -- 0
--
-- Rollback (loses every number, usual service day, protected day, pair and recorded exception; every ask, answer and away date stays, and church_away_settle is as it was):
--   drop function if exists public.church_away_settle_excepted(uuid, uuid, text, uuid, uuid, text, text[]);
--   drop trigger if exists church_away_asks_team_same_business on public.church_away_asks;
--   drop table if exists public.church_away_pairs, public.church_protected_days,
--                        public.church_schedule_department_limits;
--   drop function if exists public.church_schedule_limits_same_business();
--   alter table public.church_away_asks
--     drop constraint if exists church_away_asks_excepted,
--     drop constraint if exists church_away_asks_team_group_id_fkey,
--     drop column if exists excepted, drop column if exists team_group_id;
--   alter table public.church_schedule_settings
--     drop constraint if exists church_schedule_settings_limits,
--     drop constraint if exists church_schedule_settings_weekdays,
--     drop column if exists leaders_limit, drop column if exists office_limit,
--     drop column if exists service_weekdays;
--   notify pgrst, 'reload schema';

-- The role library (Kevin, 2026-10-17: "build functions with definitions and
-- details that helps chief know the role and what information each role
-- should get. every church and their catagory … and also a way for people
-- to create thier own roles and the wiring is the same"; design canvas
-- BKNqVVNiyxfAGAa7UAVWUC, "build it"). Idempotent.
--
--   church_role_defs        a church's roles: its own TITLE on one of the
--                           fixed JOBS (church_roles.JOBS), with the
--                           definition Chief reads, what it is handed, who it
--                           answers to (the chain a late step climbs), the
--                           teams under it, a term and a class it needs.
--                           A role's `key` is what church_leader_roles.role
--                           and church_follow_ups.leader_role hold; the four
--                           keys of 2026-10-17 (pastor, baptism_minister,
--                           welcome_lead, team_leader) are kept as keys.
--   church_role_settings    the church type (its tradition), Chief's guess
--                           and why, and when the library was first filled.
--   church_leader_roles     the role CHECK becomes a key shape (a church's
--                           own roles), and a holder's term end.
--   church_follow_up_notes  two more note kinds for the chain.
--   ministry_care_requests  prayer shared with the prayer team: the
--                           person's consent, whether they want a call,
--                           crisis words (always the pastor's), and the
--                           member leader it was handed to, when it is due,
--                           and when they prayed and sent a note.
--
-- Every new table is server-only (RLS on, anon/authenticated revoked):
-- church_roles.py, church_follow_up.py and church_prayer.py are the doors.
-- Each trigger reads a table's own columns only inside an IF that has
-- already picked that table (APPLY-2026-10-17-church-leaders-trigger-fix.sql:
-- PL/pgSQL resolves every field an IF names, so a combined IF refuses every
-- row of a table without that column).
begin;

create table if not exists public.church_role_defs(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  key text not null check (key ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
  title text not null check (length(title) between 1 and 80),
  job text not null check (job in ('senior','pastoral','prayer','care','ministry','team','welcome','teach','kids','office')),
  definition text not null default '' check (length(definition) <= 1200),
  covers text not null default 'church' check (covers in ('church','team','age','class')),
  reports_to uuid references public.church_role_defs(id) on delete set null,
  oversees_teams text[] not null default '{}' check (cardinality(oversees_teams) <= 40),
  handles text[] not null default '{}' check (cardinality(handles) <= 12),
  sees text[] not null default '{}' check (cardinality(sees) <= 8),
  term_months integer check (term_months is null or term_months between 1 and 120),
  needs_class uuid,
  status text not null default 'active' check (status in ('active','draft','archived')),
  source text not null default 'custom' check (source in ('catalog','custom','legacy','chief')),
  catalog_key text not null default '' check (length(catalog_key) <= 40),
  sort integer not null default 0,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (business_id, key)
);
create index if not exists church_role_defs_business on public.church_role_defs(business_id, status, job);

create table if not exists public.church_role_settings(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  church_type text not null default '' check (length(church_type) <= 20),
  guessed_type text not null default '' check (length(guessed_type) <= 20),
  guess_reason text not null default '' check (length(guess_reason) <= 300),
  set_by text not null default 'chief' check (set_by in ('chief','owner')),
  set_at timestamptz,
  seeded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$ declare t text; begin
  foreach t in array array['church_role_defs','church_role_settings'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- A role answers to another role of the same church, never to itself.
create or replace function public.church_role_defs_guard() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.reports_to is not null then
    if new.reports_to = new.id then
      raise exception 'A role can''t answer to itself';
    end if;
    if not exists (select 1 from public.church_role_defs d
                   where d.id = new.reports_to and d.business_id = new.business_id) then
      raise exception 'That role is not in this business';
    end if;
  end if;
  if new.needs_class is not null then
    if not exists (select 1 from public.academy_courses c
                   where c.id = new.needs_class and c.business_id = new.business_id) then
      raise exception 'That class is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_role_defs_guard() from public, anon, authenticated;
drop trigger if exists church_role_defs_guard on public.church_role_defs;
create trigger church_role_defs_guard before insert or update on public.church_role_defs
  for each row execute function public.church_role_defs_guard();

-- Holders: a church's own role keys, and when a term ends.
alter table public.church_leader_roles drop constraint if exists church_leader_roles_role_check;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'church_leader_roles_role_key_shape') then
    alter table public.church_leader_roles
      add constraint church_leader_roles_role_key_shape check (role ~ '^[a-z0-9][a-z0-9_-]{0,39}$');
  end if;
end $$;
alter table public.church_leader_roles add column if not exists term_ends_at timestamptz;
alter table public.church_leader_roles add column if not exists term_told_at timestamptz;

-- The chain: who a late step was taken to.
alter table public.church_follow_up_notes drop constraint if exists church_follow_up_notes_kind_check;
alter table public.church_follow_up_notes add constraint church_follow_up_notes_kind_check
  check (kind in ('talked','message','noanswer','notnow','note','assigned','reassigned','step','nudged',
                  'pastors_told','reassign_asked','handed_back','done','overseer_told','next_up'));

-- Prayer shared with the prayer team.
alter table public.ministry_care_requests add column if not exists prayer_team boolean not null default false;
alter table public.ministry_care_requests add column if not exists wants_call boolean not null default false;
alter table public.ministry_care_requests add column if not exists needs_pastor boolean not null default false;
alter table public.ministry_care_requests add column if not exists leader_contact_id uuid
  references public.contacts(id) on delete set null;
alter table public.ministry_care_requests add column if not exists leader_role text not null default '';
alter table public.ministry_care_requests add column if not exists leader_assigned_at timestamptz;
alter table public.ministry_care_requests add column if not exists leader_due_at timestamptz;
alter table public.ministry_care_requests add column if not exists leader_told_at timestamptz;
alter table public.ministry_care_requests add column if not exists leader_late_level integer not null default 0;
alter table public.ministry_care_requests add column if not exists leader_prayed_at timestamptz;
alter table public.ministry_care_requests add column if not exists leader_noted_at timestamptz;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'ministry_care_requests_leader_role_len') then
    alter table public.ministry_care_requests
      add constraint ministry_care_requests_leader_role_len check (length(leader_role) <= 40);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'ministry_care_requests_leader_late_level') then
    alter table public.ministry_care_requests
      add constraint ministry_care_requests_leader_late_level check (leader_late_level between 0 and 3);
  end if;
end $$;
create index if not exists ministry_care_requests_leader
  on public.ministry_care_requests(leader_contact_id) where leader_contact_id is not null;
create index if not exists ministry_care_requests_leader_due
  on public.ministry_care_requests(leader_due_at) where leader_contact_id is not null and leader_prayed_at is null;

-- The member a request is handed to is this church's own, and never a
-- request the person kept for the pastors or one that needs a pastor.
create or replace function public.care_leader_guard() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.leader_contact_id is not null then
    if not new.prayer_team then
      raise exception 'Only a request shared with the prayer team can be handed to a member';
    end if;
    if new.needs_pastor then
      raise exception 'A request that needs a pastor stays with the pastor';
    end if;
    if not exists (select 1 from public.contacts c
                   where c.id = new.leader_contact_id and c.business_id = new.business_id) then
      raise exception 'That leader is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.care_leader_guard() from public, anon, authenticated;
drop trigger if exists care_leader_guard on public.ministry_care_requests;
create trigger care_leader_guard before insert or update on public.ministry_care_requests
  for each row execute function public.care_leader_guard();

commit;

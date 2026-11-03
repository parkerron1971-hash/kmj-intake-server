-- The church leaders map, step 1 (docs/CHURCH_LEADERS_MAP.md §1, §2; Kevin
-- 2026-11-03: "what i don't want is what i build works for love city but is
-- broken and messed up for other churches"; design 4V41zJz1kEJGdeo4J9D2Ym,
-- approved). Every church runs on one engine; each church's structure is data.
-- This file adds the data. Nothing reads it until church_map.py (PR 3) and
-- CHURCH_MAP open, and the backfill freezes today's rules, so day one changes
-- nothing.
--
--   church_role_defs        a role's switches: can_shepherd (null = follows
--                           church_shepherd_settings.ministers), can_oversee,
--                           can_lead, can_board_yes, can_see_all, made_for
--                           (the streams it is the role made for; always a
--                           part of handles). Backfilled once from today's
--                           rules (§2, church_role_switches_today). A role
--                           added later with none of them said gets the same
--                           rule; a change to handles drops what it no
--                           longer takes from made_for.
--   church_leader_roles     answers_to_contact_id: the person a holder answers
--                           to (never themselves; this church's own).
--   church_role_settings    the church's money levels (null = $500 / $2,500),
--                           its pastor's-yes roles (null = every active senior
--                           role), its office-overseer roles (backfilled from
--                           the Executive Pastor role, the last key read), and
--                           who changed the map and when. Code never writes
--                           null to the two lists ('{}' = none named).
--   church_departments      one leader, one overseer, one office duty that
--                           helps; draft/active/archived; office/chief/template.
--   church_department_units what hangs from a department: a group, a role, a
--                           board, a worship ministry, a serve option, the
--                           youth or kids space, a check line. A thing hangs
--                           from one department only.
--   church_area_places      by ('church' = the church's pick, 'guess' = Chief's
--                           stored guess) and word; every row today is a pick.
--
-- Not made for any church, Love City included: departments, units, answers-to
-- links, money levels, pastor's-yes picks, any switch beyond today's rule.
--
-- Server-only: both new tables RLS on with no policies, anon and authenticated
-- revoked, service_role granted; every function here revoked from public, anon
-- and authenticated. Each guard reads a table's own columns only inside an IF
-- that has already picked that table (APPLY-2026-10-17-church-leaders-trigger-
-- fix.sql). Additive and idempotent: a second run changes nothing, and nothing
-- here drops anything. Applied by hand after review, before PR 3 merges.
begin;

-- Fail fast rather than queue behind a long read of a church table (a waiting
-- ACCESS EXCLUSIVE lock would stall every query behind it). Re-run if it times out.
set local lock_timeout = '5s';

-- ─── Roles: the switches ────────────────────────────────────────────────

-- Today's rules, once (§2), for the backfill and for a role added with none of
-- the switches said:
--   can_shepherd   church_shepherding.role_rows (:163-178, SHEPHERD_TITLE and
--                  MINISTER_TITLE :61-62): senior, or pastoral with a shepherd
--                  word, true; pastoral with "minister" null (the Ministers
--                  setting decides, as ShepherdingPage's switch does); else false
--   can_oversee    senior or pastoral
--   can_lead       member_portal_messaging.LEADER_JOBS (:159)
--   can_board_yes  false (the board's yes is church_board_members')
--   can_see_all    senior (church_roles.JOBS senior sees everything, :77)
--   made_for       the handled streams whose word is in key and title: the
--                  tie-break in church_follow_up.choose (:386-388)
-- __tests__/test_church_map_vectors.py computes the same with the Python, and
-- __tests__/church_map_db.mjs holds this to it.
create or replace function public.church_role_switches_today(
    p_job text, p_key text, p_title text, p_handles text[],
    out can_shepherd boolean, out can_oversee boolean, out can_lead boolean,
    out can_board_yes boolean, out can_see_all boolean, out made_for text[])
language sql immutable set search_path = public as $$
  select case when p_job = 'senior' then true
              when p_job = 'pastoral' and p_title ~* 'pastor|elder|bishop|overseer|shepherd' then true
              when p_job = 'pastoral' and p_title ~* 'minister' then null
              else false end,
         p_job in ('senior', 'pastoral'),
         p_job in ('senior', 'pastoral', 'ministry', 'team', 'welcome', 'teach'),
         false,
         p_job = 'senior',
         array(select h.s from unnest(coalesce(p_handles, '{}'::text[])) with ordinality as h(s, n)
                where strpos(coalesce(p_key, '') || ' ' || lower(coalesce(p_title, '')),
                             left(split_part(h.s, '_', 1), 6)) > 0
                order by h.n)
$$;
revoke all on function public.church_role_switches_today(text, text, text, text[]) from public, anon, authenticated;
-- The server's own writes fire the trigger that calls it.
grant execute on function public.church_role_switches_today(text, text, text, text[]) to service_role;

-- Once: the columns, today's values in every row (any status), then the rule
-- that made_for is part of handles. church_role_defs_guard is off for the one
-- update: needs_class has no foreign key, so a role whose class was deleted
-- would make the guard refuse its row and abort the file. It's back on before
-- the block ends, inside this transaction, under the table lock the ALTER holds.
do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_role_defs' and column_name = 'made_for') then
    alter table public.church_role_defs
      add column can_shepherd  boolean,
      add column can_oversee   boolean not null default false,
      add column can_lead      boolean not null default false,
      add column can_board_yes boolean not null default false,
      add column can_see_all   boolean not null default false,
      add column made_for      text[]  not null default '{}';
    alter table public.church_role_defs disable trigger church_role_defs_guard;
    update public.church_role_defs d
       set (can_shepherd, can_oversee, can_lead, can_board_yes, can_see_all, made_for) =
           (select t.can_shepherd, t.can_oversee, t.can_lead, t.can_board_yes, t.can_see_all, t.made_for
              from public.church_role_switches_today(d.job, d.key, d.title, d.handles) t);
    alter table public.church_role_defs enable trigger church_role_defs_guard;
    alter table public.church_role_defs
      add constraint church_role_defs_made_for check (made_for <@ handles);
  end if;
end $$;

-- After the backfill. Until the code writes the switches (PR 3), a role the
-- library or the office adds would otherwise get the column defaults
-- (can_shepherd null, can_lead false): a Lead Pastor that no longer
-- shepherds, a team leader out of the leaders room, once PR 4 reads them. So
-- a row inserted with none of them said (all at their defaults, which today's
-- rule never makes: a null can_shepherd comes with can_oversee) gets today's
-- rule, once, as the backfill gave every other row; a row that says any of
-- them keeps what it says. And today's code changes a role's handles without
-- knowing made_for, so whatever handles no longer take leaves made_for, rather
-- than the check refusing the save.
create or replace function public.church_role_defs_switches() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    if new.can_shepherd is null and not new.can_oversee and not new.can_lead and not new.can_board_yes
       and not new.can_see_all and cardinality(new.made_for) = 0 then
      select t.can_shepherd, t.can_oversee, t.can_lead, t.can_board_yes, t.can_see_all, t.made_for
        into new.can_shepherd, new.can_oversee, new.can_lead, new.can_board_yes, new.can_see_all, new.made_for
        from public.church_role_switches_today(new.job, new.key, new.title, new.handles) t;
    end if;
  end if;
  new.made_for := array(select m.s from unnest(new.made_for) with ordinality as m(s, n)
                         where m.s = any(new.handles) order by m.n);
  return new;
end $$;
revoke all on function public.church_role_defs_switches() from public, anon, authenticated;
create or replace trigger church_role_defs_switches before insert or update of handles, made_for
  on public.church_role_defs for each row execute function public.church_role_defs_switches();

-- ─── People: a holder answers to a person ───────────────────────────────

do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_leader_roles' and column_name = 'answers_to_contact_id') then
    alter table public.church_leader_roles
      add column answers_to_contact_id uuid
        constraint church_leader_roles_answers_to_fkey references public.contacts(id) on delete set null;
  end if;
end $$;
create index if not exists church_leader_roles_answers_to
  on public.church_leader_roles(answers_to_contact_id) where answers_to_contact_id is not null;

create or replace function public.church_answers_to_guard() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.answers_to_contact_id is not null then
    if new.answers_to_contact_id = new.contact_id then
      raise exception 'A leader can''t answer to themselves';
    end if;
    if not exists (select 1 from public.contacts c
                   where c.id = new.answers_to_contact_id and c.business_id = new.business_id) then
      raise exception 'The person they answer to is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_answers_to_guard() from public, anon, authenticated;
create or replace trigger church_answers_to_guard
  before insert or update of answers_to_contact_id, contact_id, business_id
  on public.church_leader_roles for each row execute function public.church_answers_to_guard();

-- ─── Church settings (null = today's platform rule) ─────────────────────

do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_role_settings' and column_name = 'office_overseer_roles') then
    alter table public.church_role_settings
      add column pastor_from_cents integer
        constraint church_role_settings_pastor_from_range check (pastor_from_cents between 0 and 10000000),
      add column board_over_cents integer
        constraint church_role_settings_board_over_range check (board_over_cents between 0 and 10000000),
      add column pastor_yes_roles uuid[]
        constraint church_role_settings_pastor_yes_size check (cardinality(pastor_yes_roles) <= 20),
      add column office_overseer_roles uuid[]
        constraint church_role_settings_office_overseer_size check (cardinality(office_overseer_roles) <= 20),
      add column map_by uuid,
      add column map_at timestamptz;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'church_role_settings_levels'
                   and conrelid = 'public.church_role_settings'::regclass) then
    alter table public.church_role_settings add constraint church_role_settings_levels
      check (board_over_cents is null or pastor_from_cents is null or board_over_cents >= pastor_from_cents);
  end if;
end $$;

-- The office overseers today: each church's active roles with the Executive
-- Pastor's key or catalog key (church_duties._exec_users :437-438,
-- church_office_tasks.overseers :83-85), oldest first. Only a church never set
-- (null) is filled, so a second run changes nothing and a church that named
-- its own (or none: '{}') keeps it. A church with roles but no settings row
-- gets one carrying only this; the library still fills as before (seeded_at
-- stays null).
insert into public.church_role_settings as s (business_id, office_overseer_roles)
select d.business_id, (array_agg(d.id order by d.sort, d.created_at, d.id))[1:20]
  from public.church_role_defs d
 where d.status = 'active' and (d.key = 'executive_pastor' or d.catalog_key = 'executive_pastor')
 group by d.business_id
on conflict (business_id) do update set office_overseer_roles = excluded.office_overseer_roles
 where s.office_overseer_roles is null;

-- After the backfill: a role named in either list is this church's own. Only
-- the ids a write adds are checked, so a role deleted since never blocks a
-- later save of the church's settings (the library's own upserts name neither
-- list, so this never fires for them).
create or replace function public.church_role_settings_guard() returns trigger
language plpgsql set search_path = public as $$
declare
  v_pastor uuid[] := '{}';
  v_office uuid[] := '{}';
begin
  if tg_op = 'UPDATE' then
    if new.business_id = old.business_id then
      v_pastor := coalesce(old.pastor_yes_roles, '{}');
      v_office := coalesce(old.office_overseer_roles, '{}');
    end if;
  end if;
  if new.pastor_yes_roles is not null then
    if exists (select 1 from unnest(new.pastor_yes_roles) r
               where r is null or (not (r = any(v_pastor)) and not exists (
                 select 1 from public.church_role_defs d where d.id = r and d.business_id = new.business_id))) then
      raise exception 'A role picked for the pastor''s yes is not in this business';
    end if;
  end if;
  if new.office_overseer_roles is not null then
    if exists (select 1 from unnest(new.office_overseer_roles) r
               where r is null or (not (r = any(v_office)) and not exists (
                 select 1 from public.church_role_defs d where d.id = r and d.business_id = new.business_id))) then
      raise exception 'A role picked to oversee the office is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_role_settings_guard() from public, anon, authenticated;
create or replace trigger church_role_settings_guard
  before insert or update of pastor_yes_roles, office_overseer_roles, business_id
  on public.church_role_settings for each row execute function public.church_role_settings_guard();

-- ─── Departments ────────────────────────────────────────────────────────

create table if not exists public.church_departments(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  leader_contact_id   uuid references public.contacts(id) on delete set null,
  overseer_contact_id uuid references public.contacts(id) on delete set null,
  support_duty text check (support_duty ~ '^[a-z][a-z0-9_]{1,39}$'),     -- a church_duties.CATALOG key
  area text check (area in ('worship_media', 'people_care', 'giving_money', 'kids_youth',
                            'groups_classes', 'messages_safety', 'website_outreach', 'office')),
  status text not null default 'active' check (status in ('draft', 'active', 'archived')),
  source text not null default 'office' check (source in ('office', 'chief', 'template')),
  sort smallint not null default 0 check (sort between 0 and 999),
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_departments_two check (leader_contact_id <> overseer_contact_id)
);
create unique index if not exists church_departments_name
  on public.church_departments(business_id, lower(btrim(name))) where status <> 'archived';
create index if not exists church_departments_leader
  on public.church_departments(leader_contact_id) where status = 'active';
create index if not exists church_departments_overseer
  on public.church_departments(overseer_contact_id) where status = 'active';

-- What hangs from a department: the five leader sources, plus the loose ones.
create table if not exists public.church_department_units(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  department_id uuid not null references public.church_departments(id) on delete cascade,
  kind text not null check (kind in ('group', 'role', 'board', 'worship_ministry', 'serve_option', 'space', 'check_line')),
  group_id uuid references public.groups(id) on delete cascade,          -- any kind, serve teams and ministries too
  role_id uuid references public.church_role_defs(id) on delete cascade,
  board_id uuid references public.church_boards(id) on delete cascade,
  worship_ministry_id uuid references public.worship_ministries(id) on delete cascade,
  label text not null default '' check (char_length(label) <= 120),     -- a serve option, 'youth'|'kids', a check line
  created_at timestamptz not null default now(),
  constraint church_department_units_shape check (
    num_nonnulls(group_id, role_id, board_id, worship_ministry_id)
      = case when kind in ('serve_option', 'space', 'check_line') then 0 else 1 end
    and (kind <> 'group' or group_id is not null) and (kind <> 'role' or role_id is not null)
    and (kind <> 'board' or board_id is not null) and (kind <> 'worship_ministry' or worship_ministry_id is not null)
    and (kind not in ('serve_option', 'check_line') or label <> '') and (kind <> 'space' or label in ('youth', 'kids')))
);
-- One department per thing.
create unique index if not exists church_department_units_group
  on public.church_department_units(business_id, group_id) where group_id is not null;
create unique index if not exists church_department_units_role
  on public.church_department_units(business_id, role_id) where role_id is not null;
create unique index if not exists church_department_units_board
  on public.church_department_units(business_id, board_id) where board_id is not null;
create unique index if not exists church_department_units_worship_ministry
  on public.church_department_units(business_id, worship_ministry_id) where worship_ministry_id is not null;
create unique index if not exists church_department_units_label
  on public.church_department_units(business_id, kind, lower(label)) where kind in ('serve_option', 'space', 'check_line');
create index if not exists church_department_units_department on public.church_department_units(department_id);

-- A department's people, and a unit's department, group, role, board and
-- worship ministry, are all this church's own; neither moves to another church.
create or replace function public.church_map_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_op = 'UPDATE' then
    if new.business_id <> old.business_id then
      raise exception 'A department stays with its church';
    end if;
  end if;
  if tg_table_name = 'church_departments' then
    if new.leader_contact_id is not null then
      if not exists (select 1 from public.contacts c
                     where c.id = new.leader_contact_id and c.business_id = new.business_id) then
        raise exception 'That leader is not in this business';
      end if;
    end if;
    if new.overseer_contact_id is not null then
      if not exists (select 1 from public.contacts c
                     where c.id = new.overseer_contact_id and c.business_id = new.business_id) then
        raise exception 'That overseer is not in this business';
      end if;
    end if;
  end if;
  if tg_table_name = 'church_department_units' then
    if not exists (select 1 from public.church_departments d
                   where d.id = new.department_id and d.business_id = new.business_id) then
      raise exception 'That department is not in this business';
    end if;
    if new.group_id is not null then
      if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
        raise exception 'That group is not in this business';
      end if;
    end if;
    if new.role_id is not null then
      if not exists (select 1 from public.church_role_defs r where r.id = new.role_id and r.business_id = new.business_id) then
        raise exception 'That role is not in this business';
      end if;
    end if;
    if new.board_id is not null then
      if not exists (select 1 from public.church_boards b where b.id = new.board_id and b.business_id = new.business_id) then
        raise exception 'That board is not in this business';
      end if;
    end if;
    if new.worship_ministry_id is not null then
      if not exists (select 1 from public.worship_ministries w
                     where w.id = new.worship_ministry_id and w.business_id = new.business_id) then
        raise exception 'That ministry is not in this business';
      end if;
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_map_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['church_departments', 'church_department_units'] loop
    execute format('create or replace trigger church_map_same_business before insert or update on public.%I
      for each row execute function public.church_map_same_business()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- ─── Areas: the church's picks vs Chief's stored guesses ────────────────

do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                   and table_name = 'church_area_places' and column_name = 'word') then
    alter table public.church_area_places
      add column by text not null default 'church'
        constraint church_area_places_by_known check (by in ('church', 'guess')),
      add column word text not null default ''
        constraint church_area_places_word_len check (char_length(word) <= 40);
  end if;
end $$;

notify pgrst, 'reload schema';

commit;

-- Check after applying (the columns and tables; RLS on with no policies; the
-- functions only the server runs; the guard back on):
--   select table_name, column_name, data_type, is_nullable, column_default from information_schema.columns
--    where table_schema = 'public' and (table_name, column_name) in (
--      ('church_role_defs','can_shepherd'), ('church_role_defs','can_oversee'), ('church_role_defs','can_lead'),
--      ('church_role_defs','can_board_yes'), ('church_role_defs','can_see_all'), ('church_role_defs','made_for'),
--      ('church_leader_roles','answers_to_contact_id'), ('church_role_settings','pastor_from_cents'),
--      ('church_role_settings','board_over_cents'), ('church_role_settings','pastor_yes_roles'),
--      ('church_role_settings','office_overseer_roles'), ('church_role_settings','map_by'),
--      ('church_role_settings','map_at'), ('church_area_places','by'), ('church_area_places','word'));   -- 15 rows
--   select c.relname, c.relrowsecurity, (select count(*) from pg_policies p where p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads
--     from pg_class c where c.relname in ('church_departments', 'church_department_units');    -- RLS on, 0, false
--   select tgname, tgenabled from pg_trigger where tgrelid = 'public.church_role_defs'::regclass and not tgisinternal;
--     -- church_role_defs_guard O, church_role_defs_switches O
--
-- Rollback, only after the code that reads these is gone: it drops the map and
-- the switches with whatever the churches put in them. A settings row the
-- backfill made for a church that had none carries only church_type '' and
-- seeded_at null, which the library reads as no row, so it stays.
--   begin;
--   drop table if exists public.church_department_units;
--   drop table if exists public.church_departments;
--   drop function if exists public.church_map_same_business();
--   drop trigger if exists church_answers_to_guard on public.church_leader_roles;
--   drop function if exists public.church_answers_to_guard();
--   drop index if exists public.church_leader_roles_answers_to;
--   alter table public.church_leader_roles drop column if exists answers_to_contact_id;
--   drop trigger if exists church_role_settings_guard on public.church_role_settings;
--   drop function if exists public.church_role_settings_guard();
--   alter table public.church_role_settings drop constraint if exists church_role_settings_levels,
--     drop column if exists pastor_from_cents, drop column if exists board_over_cents,
--     drop column if exists pastor_yes_roles, drop column if exists office_overseer_roles,
--     drop column if exists map_by, drop column if exists map_at;
--   drop trigger if exists church_role_defs_switches on public.church_role_defs;
--   drop function if exists public.church_role_defs_switches();
--   alter table public.church_role_defs drop constraint if exists church_role_defs_made_for,
--     drop column if exists can_shepherd, drop column if exists can_oversee, drop column if exists can_lead,
--     drop column if exists can_board_yes, drop column if exists can_see_all, drop column if exists made_for;
--   drop function if exists public.church_role_switches_today(text, text, text, text[]);
--   alter table public.church_area_places drop column if exists by, drop column if exists word;
--   commit;

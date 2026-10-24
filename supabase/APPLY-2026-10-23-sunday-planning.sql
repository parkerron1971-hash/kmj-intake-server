-- ChurchSavvy Planning: a church's Sunday teams and who serves when (design
-- canvas Ct88v7pxpq5a4PGYX3MuQQ, boards 2-10; Kevin 2026-10-23: "This is a
-- good build. i agree with your plan"). Server-only tables (RLS on, no
-- policies, browser roles revoked); sunday_planning.py reads and writes them.
--
--   serve_teams        a group (kind 'team') that serves on Sundays: when its
--                      people arrive, how many Sundays a month each, whether a
--                      swap needs the leader's OK, families on the same Sundays.
--                      Its people, leaders and thread are the group's own.
--   serve_positions    the places a team fills each Sunday ("Sound", 1 place).
--   serve_trained      who can take a place, or is learning it.
--   serve_assignments  one place on one service: who was asked, and their
--                      answer. No row is an open place; an 'offered' row went
--                      to the whole team and has nobody yet.
--   serve_away         days a person can't serve; nobody asks them then.
--
-- A volunteer is a contact (they answer in the member app), never a
-- business_users seat: a seat reads the whole business through
-- is_business_member (its people, its giving, its books).
-- Idempotent.
begin;

create table if not exists public.serve_teams(
  group_id uuid primary key references public.groups(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  call_time time,
  max_month smallint not null default 2 check (max_month between 0 and 5),
  swap_needs_ok boolean not null default false,
  families boolean not null default true,
  sort smallint not null default 0 check (sort between 0 and 999),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists serve_teams_by_church on public.serve_teams (business_id, sort);

create table if not exists public.serve_positions(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.serve_teams(group_id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 40),
  needed smallint not null default 1 check (needed between 1 and 10),
  note text not null default '' check (char_length(note) <= 200),
  sort smallint not null default 0 check (sort between 0 and 999),
  active boolean not null default true,
  created_at timestamptz not null default now()
);
create unique index if not exists serve_positions_one_name on public.serve_positions (group_id, lower(btrim(name)))
  where active;
create index if not exists serve_positions_by_team on public.serve_positions (business_id, group_id, sort);

create table if not exists public.serve_trained(
  position_id uuid not null references public.serve_positions(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  level text not null default 'trained' check (level in ('trained', 'learning')),
  created_at timestamptz not null default now(),
  primary key (position_id, contact_id)
);
create index if not exists serve_trained_by_person on public.serve_trained (contact_id);
create index if not exists serve_trained_by_church on public.serve_trained (business_id);

create table if not exists public.serve_assignments(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  service_id uuid not null references public.worship_services(id) on delete cascade,
  position_id uuid not null references public.serve_positions(id) on delete cascade,
  slot smallint not null default 1 check (slot between 1 and 10),
  contact_id uuid references public.contacts(id) on delete cascade,
  status text not null default 'asked' check (status in ('offered', 'asked', 'yes', 'no')),
  note text not null default '' check (char_length(note) <= 300),
  asked_by text not null default '' check (char_length(asked_by) <= 80),
  asked_at timestamptz not null default now(),
  answered_at timestamptz,
  -- Asks go out on the next sweep (quiet hours kept), so a month filled by
  -- mistake can be taken back before anyone's phone buzzes.
  notified_at timestamptz,
  nudged_at timestamptz,
  check ((status = 'offered') = (contact_id is null))
);
create index if not exists serve_assignments_to_tell on public.serve_assignments (asked_at)
  where notified_at is null and status in ('asked', 'offered');
create unique index if not exists serve_assignments_one_each on public.serve_assignments (service_id, position_id, slot);
create index if not exists serve_assignments_by_person on public.serve_assignments (contact_id, status);
create index if not exists serve_assignments_by_church on public.serve_assignments (business_id, service_id);

create table if not exists public.serve_away(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  starts_on date not null,
  ends_on date not null,
  note text not null default '' check (char_length(note) <= 100),
  created_at timestamptz not null default now(),
  check (ends_on >= starts_on and ends_on - starts_on <= 366)
);
create index if not exists serve_away_by_person on public.serve_away (business_id, contact_id, ends_on);

-- Every row stays inside one church: its group, place, service and person
-- must all be that church's. Each check is nested under its own table test:
-- PL/pgSQL does not short-circuit `and`, and a field one table lacks would
-- error (42703).
create or replace function public.serve_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'serve_teams' then
    if not exists (select 1 from public.groups g
                   where g.id = new.group_id and g.business_id = new.business_id and g.kind = 'team') then
      raise exception 'That serving team is not in this business';
    end if;
  end if;
  if tg_table_name = 'serve_positions' then
    if not exists (select 1 from public.serve_teams t
                   where t.group_id = new.group_id and t.business_id = new.business_id) then
      raise exception 'That team is not in this business';
    end if;
  end if;
  if tg_table_name in ('serve_trained', 'serve_assignments') then
    if not exists (select 1 from public.serve_positions p
                   where p.id = new.position_id and p.business_id = new.business_id) then
      raise exception 'That place is not in this business';
    end if;
  end if;
  if tg_table_name = 'serve_assignments' then
    if not exists (select 1 from public.worship_services s
                   where s.id = new.service_id and s.business_id = new.business_id) then
      raise exception 'That service is not in this business';
    end if;
  end if;
  if tg_table_name in ('serve_trained', 'serve_assignments', 'serve_away') then
    if new.contact_id is not null and not exists (select 1 from public.contacts c
                   where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.serve_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['serve_teams', 'serve_positions', 'serve_trained', 'serve_assignments', 'serve_away'] loop
    execute format('drop trigger if exists serve_same_business on public.%I', t);
    execute format('create trigger serve_same_business before insert or update on public.%I
      for each row execute function public.serve_same_business()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

commit;

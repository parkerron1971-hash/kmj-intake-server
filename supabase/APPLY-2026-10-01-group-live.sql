-- Group live meetings (Kevin's church plan, decided 2026-09-29).
-- A group's leader starts a video meeting for the group from the member
-- app. The church decides who may host (group_members.can_host_live, on
-- leaders); a youth group needs TWO approved adults before anyone else
-- can come in (groups.youth); joining counts as group attendance; there
-- is no recording. Video runs on the same LiveKit project as Academy
-- classes. Sessions are SERVER-ONLY: members are not Supabase users, so
-- member_portal_group_live.py is the door, behind the member's session.
begin;

alter table public.groups add column if not exists youth boolean not null default false;
alter table public.group_members add column if not exists can_host_live boolean not null default false;

create table if not exists public.group_live_sessions(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.groups(id) on delete cascade,
  -- meeting: everyone can be on camera · broadcast: only hosts are.
  mode text not null default 'meeting' check (mode in ('meeting','broadcast')),
  -- waiting: a youth group's first adult is in; members wait for a second.
  status text not null default 'live' check (status in ('waiting','live','ended')),
  room_name text not null unique check (room_name ~ '^grp-[0-9a-f-]{36}$'),
  started_by uuid references public.contacts(id) on delete set null,
  second_adult uuid references public.contacts(id) on delete set null,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- One meeting at a time per group.
create unique index if not exists group_live_one_open on public.group_live_sessions(group_id)
  where status in ('waiting','live');
create index if not exists group_live_business on public.group_live_sessions(business_id, started_at desc);

alter table public.group_live_sessions enable row level security;
revoke all on public.group_live_sessions from anon, authenticated;
grant all on public.group_live_sessions to service_role;

-- Same business as its group and people (nested IFs: PL/pgSQL does not
-- short-circuit AND).
create or replace function public.group_live_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
    raise exception 'That group is not in this business';
  end if;
  if new.started_by is not null then
    if not exists (select 1 from public.contacts c where c.id = new.started_by and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  if new.second_adult is not null then
    if not exists (select 1 from public.contacts c where c.id = new.second_adult and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
drop trigger if exists group_live_same_business on public.group_live_sessions;
create trigger group_live_same_business before insert or update on public.group_live_sessions
  for each row execute function public.group_live_same_business();

-- Who may host, and whether a group is a youth group, are safety
-- settings. Making things LESS safe — letting someone host, or taking a
-- group off the youth rule — is for the owner, an admin or a manager
-- only, not every seat that can edit groups. Making things safer (taking
-- hosting away, marking a youth group) is open to any editor. The
-- server's own writes carry no signed-in user and are not affected.
create or replace function public.group_live_settings_guard() returns trigger
language plpgsql set search_path = public as $$
declare changed boolean;
begin
  if auth.uid() is null then
    return new;
  end if;
  if tg_table_name = 'groups' then
    if tg_op = 'INSERT' then
      changed := false;
    else
      changed := old.youth and not new.youth;
    end if;
  else
    if tg_op = 'INSERT' then
      changed := new.can_host_live;
    else
      changed := new.can_host_live and not old.can_host_live;
    end if;
  end if;
  if changed then
    if coalesce(public.business_role(new.business_id), '') not in ('owner','admin','manager') then
      raise exception 'Only a manager or the owner can change who hosts live meetings or a youth group setting';
    end if;
  end if;
  return new;
end $$;
drop trigger if exists group_live_settings_guard on public.groups;
create trigger group_live_settings_guard before insert or update on public.groups
  for each row execute function public.group_live_settings_guard();
drop trigger if exists group_live_settings_guard on public.group_members;
create trigger group_live_settings_guard before insert or update on public.group_members
  for each row execute function public.group_live_settings_guard();

commit;

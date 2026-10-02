-- Groups (the church plan: attendance & check-in, then small groups &
-- households). Small groups, serving teams, classes and ministries: who
-- leads, who belongs, when and where they meet, and a log of each
-- meeting — who came, how many visitors — so a group can see who has
-- started missing. Idempotent.
--
-- Access is the rest of the church's records (like attendance): the
-- owner and any writing seat (member/manager/admin) record, any active
-- seat reads. Members' own view of their groups (the member page) comes
-- later, through the server.
begin;

create table if not exists public.groups(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (length(btrim(name)) between 1 and 80),
  kind text not null default 'small_group' check (kind in ('small_group','team','class','ministry')),
  description text not null default '' check (length(description) <= 1000),
  -- "Tuesdays, 7 pm" — the church's own words, not a schedule engine.
  meets text not null default '' check (length(meets) <= 120),
  location text not null default '' check (length(location) <= 160),
  capacity integer check (capacity is null or capacity between 1 and 10000),
  open_to_join boolean not null default true,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists groups_business on public.groups(business_id, active, name);

create table if not exists public.group_members(
  group_id uuid not null references public.groups(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  role text not null default 'member' check (role in ('leader','member')),
  joined_on date not null default current_date,
  created_at timestamptz not null default now(),
  primary key (group_id, contact_id)
);
create index if not exists group_members_contact on public.group_members(contact_id);
create index if not exists group_members_business on public.group_members(business_id);

create table if not exists public.group_meetings(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.groups(id) on delete cascade,
  met_on date not null,
  -- People who came but aren't members (a friend brought along).
  visitors integer not null default 0 check (visitors between 0 and 10000),
  notes text not null default '' check (length(notes) <= 2000),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (group_id, met_on)
);
create index if not exists group_meetings_business on public.group_meetings(business_id, met_on desc);

create table if not exists public.group_meeting_attendance(
  meeting_id uuid not null references public.group_meetings(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  primary key (meeting_id, contact_id)
);
create index if not exists group_meeting_attendance_contact on public.group_meeting_attendance(contact_id);

do $$ declare t text; begin
  foreach t in array array['groups','group_members','group_meetings','group_meeting_attendance'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists business_member_access on public.%I', t);
    execute format('create policy business_member_access on public.%I for all to authenticated
      using (business_id in (select id from public.businesses where owner_id = auth.uid()))
      with check (business_id in (select id from public.businesses where owner_id = auth.uid()))', t);
    execute format('drop policy if exists tenant_writer_write on public.%I', t);
    execute format('create policy tenant_writer_write on public.%I for all to authenticated
      using (public.is_business_writer(business_id)) with check (public.is_business_writer(business_id))', t);
    execute format('drop policy if exists tenant_member_read on public.%I', t);
    execute format('create policy tenant_member_read on public.%I for select to authenticated
      using (public.is_business_member(business_id))', t);
    execute format('revoke all on public.%I from anon', t);
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- Every row's group, person and meeting must be this business's own.
-- Each check is nested under its own table test: PL/pgSQL does not
-- short-circuit `and`, and a field one table lacks would error (42703).
create or replace function public.groups_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name in ('group_members','group_meetings') then
    if not exists (select 1 from public.groups g
                   where g.id = new.group_id and g.business_id = new.business_id) then
      raise exception 'That group is not in this business';
    end if;
  end if;
  if tg_table_name in ('group_members','group_meeting_attendance') then
    if not exists (select 1 from public.contacts c
                   where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  if tg_table_name = 'group_meeting_attendance' then
    if not exists (select 1 from public.group_meetings m
                   where m.id = new.meeting_id and m.business_id = new.business_id) then
      raise exception 'That meeting is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.groups_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['group_members','group_meetings','group_meeting_attendance'] loop
    execute format('drop trigger if exists groups_same_business on public.%I', t);
    execute format('create trigger groups_same_business before insert or update on public.%I
      for each row execute function public.groups_same_business()', t);
  end loop;
end $$;

commit;

-- A group gets its own place in the member app (Kevin, 2026-10-20: "there is
-- no area where people can communicate like a chat. receive announcements
-- from group leader. etc... there is a entire area missing"). Part 1 of the
-- approved "Church Groups, Together" canvas: a group's page, its Board
-- (announcements from its leaders, with "Got it"), who's in it, and asking
-- to join. Kevin's calls the same day:
--   * members of a group see each other's FULL names, and each group's
--     leader may switch that to first names (name_display);
--   * how people join depends on the group's type and on whoever creates
--     it (join_mode: open = join right away, ask = a leader says yes,
--     invite = hidden, leaders bring people in).
-- Idempotent.
--
--   groups.join_mode, groups.name_display   new settings on each group
--   group_join_requests  someone asked to join; a leader says yes or not now
--   group_posts          the Board: a leader's announcement to their group
--                        (group_id null = from the pastors, to every group)
--   group_post_seen      who has opened a post, and who pressed "Got it"
--
-- The new tables are written only by the server (member_portal_groups.py
-- is the one door, acting for a signed-in member). Seats may READ them, so
-- the office sees who is waiting and what was posted.
begin;

-- ─── settings on each group ─────────────────────────────────────────
do $$ begin
  if not exists (select 1 from information_schema.columns
                 where table_schema = 'public' and table_name = 'groups' and column_name = 'join_mode') then
    alter table public.groups add column join_mode text not null default 'ask'
      check (join_mode in ('open','ask','invite'));
    -- Groups that already exist: a closed one stays closed (invite);
    -- an open one takes its type's default.
    update public.groups set join_mode = case
      when not open_to_join then 'invite'
      when kind = 'class' then 'open'
      else 'ask' end;
  end if;
end $$;
alter table public.groups add column if not exists name_display text not null default 'full'
  check (name_display in ('full','first'));

-- open_to_join (what the office and older code read) follows join_mode,
-- and a change made the old way (only open_to_join) moves join_mode too.
create or replace function public.groups_join_mode_sync() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    if not new.open_to_join then
      new.join_mode := 'invite';
    end if;
  elsif new.join_mode is distinct from old.join_mode then
    null;
  elsif new.open_to_join is distinct from old.open_to_join then
    new.join_mode := case when not new.open_to_join then 'invite'
                          when new.kind = 'class' then 'open' else 'ask' end;
  end if;
  new.open_to_join := new.join_mode <> 'invite';
  return new;
end $$;
revoke all on function public.groups_join_mode_sync() from public, anon, authenticated;
drop trigger if exists groups_join_mode_sync on public.groups;
create trigger groups_join_mode_sync before insert or update on public.groups
  for each row execute function public.groups_join_mode_sync();

-- ─── asking to join ─────────────────────────────────────────────────
create table if not exists public.group_join_requests(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.groups(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  status text not null default 'waiting' check (status in ('waiting','yes','no','withdrawn')),
  asked_at timestamptz not null default now(),
  decided_at timestamptz,
  decided_by uuid references public.contacts(id) on delete set null
);
create unique index if not exists group_join_requests_one_waiting
  on public.group_join_requests(group_id, contact_id) where status = 'waiting';
create index if not exists group_join_requests_business on public.group_join_requests(business_id, status, asked_at desc);

-- ─── the Board ──────────────────────────────────────────────────────
create table if not exists public.group_posts(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  -- null = from the pastors, to every group (the office's word to all)
  group_id uuid references public.groups(id) on delete cascade,
  title text not null default '' check (length(title) <= 120),
  body text not null check (length(btrim(body)) between 1 and 4000),
  pinned boolean not null default false,
  ask_ack boolean not null default true,
  posted_by uuid references public.contacts(id) on delete set null,
  created_at timestamptz not null default now(),
  removed_at timestamptz
);
create index if not exists group_posts_recent on public.group_posts(business_id, group_id, created_at desc);

create table if not exists public.group_post_seen(
  post_id uuid not null references public.group_posts(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  seen_at timestamptz not null default now(),
  acked_at timestamptz,
  primary key (post_id, contact_id)
);
create index if not exists group_post_seen_contact on public.group_post_seen(contact_id);

-- Seats read; only the server writes.
do $$ declare t text; begin
  foreach t in array array['group_join_requests','group_posts','group_post_seen'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists business_owner_read on public.%I', t);
    execute format('create policy business_owner_read on public.%I for select to authenticated
      using (business_id in (select id from public.businesses where owner_id = auth.uid()))', t);
    execute format('drop policy if exists tenant_member_read on public.%I', t);
    execute format('create policy tenant_member_read on public.%I for select to authenticated
      using (public.is_business_member(business_id))', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- Every row's group, person and post must be this church's own. Nested
-- per table: PL/pgSQL does not short-circuit `and` (a field one table
-- lacks would error 42703).
create or replace function public.group_space_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'group_join_requests' then
    if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
      raise exception 'That group is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
    if new.decided_by is not null then
      if not exists (select 1 from public.contacts c where c.id = new.decided_by and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
    end if;
  elsif tg_table_name = 'group_posts' then
    if new.group_id is not null then
      if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
        raise exception 'That group is not in this business';
      end if;
    end if;
    if new.posted_by is not null then
      if not exists (select 1 from public.contacts c where c.id = new.posted_by and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
    end if;
  elsif tg_table_name = 'group_post_seen' then
    if not exists (select 1 from public.group_posts p where p.id = new.post_id and p.business_id = new.business_id) then
      raise exception 'That post is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.group_space_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['group_join_requests','group_posts','group_post_seen'] loop
    execute format('drop trigger if exists group_space_same_business on public.%I', t);
    execute format('create trigger group_space_same_business before insert or update on public.%I
      for each row execute function public.group_space_same_business()', t);
  end loop;
end $$;

commit;

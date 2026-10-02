-- Member messaging: group chats and direct messages (Kevin, 2026-10-02).
--
-- Settled rules (see member_messaging_rules.py for the one place they are
-- applied):
--   · A member can message only with BOTH a birthdate on their record
--     (under 18 = teen rules) AND the church's "Can use messaging" switch.
--   · Teens privately message only their linked parents and other teens;
--     a linked parent can read all of their teen's chats; a group chat
--     with a teen in it needs two approved adult leaders.
--   · Messages are kept a year (the church can change it).
--   · Every message is screened; harmful ones are held for two safety
--     officers; staff don't read chats by default, and every safety look
--     is logged and shown to the people in that chat.
--
-- The team edits three things from the app (RLS): a member's messaging
-- switch, parent links, and the church's safety officers. Turning things
-- ON (a switch, a parent link) is a manager's call; turning them off is
-- open to any editor. Everything members write is SERVER-ONLY.
begin;

-- ─── on the member's record ─────────────────────────────────────────
alter table public.contacts add column if not exists birthdate date
  check (birthdate is null or birthdate > date '1900-01-01');

create table if not exists public.msg_members(
  contact_id uuid primary key references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  -- The church's "Can use messaging" switch.
  enabled boolean not null default false,
  enabled_by uuid,
  enabled_at timestamptz,
  -- The member agreed to the community guidelines (member app).
  guidelines_at timestamptz,
  photo_url text not null default '' check (photo_url = '' or (length(photo_url) <= 500 and photo_url ~ '^https://')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists msg_members_business on public.msg_members(business_id);

create table if not exists public.msg_guardians(
  teen_contact_id uuid not null references public.contacts(id) on delete cascade,
  guardian_contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  created_by uuid,
  created_at timestamptz not null default now(),
  primary key (teen_contact_id, guardian_contact_id),
  check (teen_contact_id <> guardian_contact_id)
);
create index if not exists msg_guardians_guardian on public.msg_guardians(guardian_contact_id);

create table if not exists public.msg_safety_officers(
  business_id uuid not null references public.businesses(id) on delete cascade,
  user_id uuid not null,
  added_by uuid,
  created_at timestamptz not null default now(),
  primary key (business_id, user_id)
);

-- ─── what members write (server-only) ───────────────────────────────
create table if not exists public.msg_threads(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null check (kind in ('group','direct')),
  group_id uuid references public.groups(id) on delete cascade,
  -- "a:b", the two people of a direct chat in sorted order: one chat per pair.
  direct_key text unique,
  last_message_at timestamptz,
  created_at timestamptz not null default now(),
  check ((kind = 'group' and group_id is not null and direct_key is null)
      or (kind = 'direct' and group_id is null and direct_key is not null))
);
create unique index if not exists msg_threads_one_per_group on public.msg_threads(group_id) where kind = 'group';
create index if not exists msg_threads_business on public.msg_threads(business_id, last_message_at desc);

create table if not exists public.msg_participants(
  thread_id uuid not null references public.msg_threads(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  -- requested: a direct message from someone you don't share a group with,
  -- waiting for you to accept. declined: you ignored it.
  state text not null default 'active' check (state in ('active','requested','declined')),
  last_read_at timestamptz,
  muted boolean not null default false,
  created_at timestamptz not null default now(),
  primary key (thread_id, contact_id)
);
create index if not exists msg_participants_contact on public.msg_participants(contact_id);

create table if not exists public.msg_messages(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  thread_id uuid not null references public.msg_threads(id) on delete cascade,
  sender_contact_id uuid references public.contacts(id) on delete set null,
  body text not null check (length(btrim(body)) between 1 and 2000),
  -- held: kept back for the safety officers · removed: taken down.
  status text not null default 'delivered' check (status in ('delivered','held','removed')),
  -- What the screen saw: harm (held) or self_harm (delivered, care alerted).
  flag text check (flag is null or flag in ('harm','self_harm')),
  removed_by uuid,
  removed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists msg_messages_thread on public.msg_messages(thread_id, created_at);
create index if not exists msg_messages_business on public.msg_messages(business_id, created_at);

create table if not exists public.msg_blocks(
  blocker_contact_id uuid not null references public.contacts(id) on delete cascade,
  blocked_contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker_contact_id, blocked_contact_id),
  check (blocker_contact_id <> blocked_contact_id)
);

create table if not exists public.msg_reports(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  message_id uuid not null references public.msg_messages(id) on delete cascade,
  -- Never shown to the person reported.
  reporter_contact_id uuid references public.contacts(id) on delete set null,
  reason text not null default '' check (length(reason) <= 500),
  status text not null default 'open' check (status in ('open','closed')),
  outcome text not null default '' check (length(outcome) <= 500),
  closed_by uuid,
  closed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists msg_reports_open on public.msg_reports(business_id, status, created_at desc);

-- Every time a safety officer opens a chat. The chat's people see it.
create table if not exists public.msg_staff_views(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  thread_id uuid not null references public.msg_threads(id) on delete cascade,
  user_id uuid not null,
  reason text not null check (length(btrim(reason)) between 1 and 300),
  created_at timestamptz not null default now()
);
create index if not exists msg_staff_views_thread on public.msg_staff_views(thread_id, created_at desc);

-- ─── access ─────────────────────────────────────────────────────────
-- Team-edited: messaging switch, parent links (tenant pattern); safety
-- officers (the owner only — they decide who may read reported chats).
do $$ declare t text; begin
  foreach t in array array['msg_members','msg_guardians'] loop
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

alter table public.msg_safety_officers enable row level security;
drop policy if exists owner_manages on public.msg_safety_officers;
create policy owner_manages on public.msg_safety_officers for all to authenticated
  using (business_id in (select id from public.businesses where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses where owner_id = auth.uid()));
drop policy if exists tenant_member_read on public.msg_safety_officers;
create policy tenant_member_read on public.msg_safety_officers for select to authenticated
  using (public.is_business_member(business_id));
revoke all on public.msg_safety_officers from anon;
grant select, insert, update, delete on public.msg_safety_officers to authenticated;
grant all on public.msg_safety_officers to service_role;

do $$ declare t text; begin
  foreach t in array array['msg_threads','msg_participants','msg_messages','msg_blocks','msg_reports','msg_staff_views'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- ─── safety guards ──────────────────────────────────────────────────
-- Granting is a manager's call: switching a member's messaging ON, adding
-- a parent link (it lets someone read a teen's chats), or changing the
-- birthdate of someone who can already message (it can turn a teen into
-- an adult). Turning things off is open to any editor. The server's own
-- writes carry no signed-in user and are not affected.
create or replace function public.msg_grant_guard() returns trigger
language plpgsql set search_path = public as $$
declare granting boolean := false;
begin
  if auth.uid() is null then
    return new;
  end if;
  if tg_table_name = 'msg_members' then
    if tg_op = 'INSERT' then
      granting := new.enabled;
    else
      granting := new.enabled and not old.enabled;
    end if;
  elsif tg_table_name = 'msg_guardians' then
    granting := true;
  elsif tg_table_name = 'contacts' then
    if new.birthdate is distinct from old.birthdate then
      if exists (select 1 from public.msg_members m where m.contact_id = new.id and m.enabled) then
        granting := true;
      end if;
    end if;
  end if;
  if granting then
    if coalesce(public.business_role(new.business_id), '') not in ('owner','admin','manager') then
      raise exception 'Only a manager or the owner can turn on messaging, link a parent, or change the birthdate of someone who can message';
    end if;
  end if;
  return new;
end $$;
drop trigger if exists msg_grant_guard on public.msg_members;
create trigger msg_grant_guard before insert or update on public.msg_members
  for each row execute function public.msg_grant_guard();
drop trigger if exists msg_grant_guard on public.msg_guardians;
create trigger msg_grant_guard before insert or update on public.msg_guardians
  for each row execute function public.msg_grant_guard();
drop trigger if exists msg_grant_guard on public.contacts;
create trigger msg_grant_guard before update on public.contacts
  for each row execute function public.msg_grant_guard();

-- Same business everywhere (nested IFs: PL/pgSQL does not short-circuit).
create or replace function public.msg_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name in ('msg_members') then
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif tg_table_name = 'msg_guardians' then
    if not exists (select 1 from public.contacts c where c.id = new.teen_contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.guardian_contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif tg_table_name = 'msg_threads' then
    if new.group_id is not null then
      if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
        raise exception 'That group is not in this business';
      end if;
    end if;
  elsif tg_table_name in ('msg_participants','msg_messages','msg_staff_views') then
    if not exists (select 1 from public.msg_threads t where t.id = new.thread_id and t.business_id = new.business_id) then
      raise exception 'That chat is not in this business';
    end if;
  elsif tg_table_name = 'msg_reports' then
    if not exists (select 1 from public.msg_messages m where m.id = new.message_id and m.business_id = new.business_id) then
      raise exception 'That message is not in this business';
    end if;
  elsif tg_table_name = 'msg_blocks' then
    if not exists (select 1 from public.contacts c where c.id = new.blocker_contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.blocked_contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
do $$ declare t text; begin
  foreach t in array array['msg_members','msg_guardians','msg_threads','msg_participants','msg_messages',
                           'msg_blocks','msg_reports','msg_staff_views'] loop
    execute format('drop trigger if exists msg_same_business on public.%I', t);
    execute format('create trigger msg_same_business before insert or update on public.%I
      for each row execute function public.msg_same_business()', t);
  end loop;
end $$;

-- A thread's latest activity, for the inbox order.
create or replace function public.msg_touch_thread() returns trigger
language plpgsql set search_path = public as $$
begin
  update public.msg_threads set last_message_at = new.created_at where id = new.thread_id;
  return new;
end $$;
drop trigger if exists msg_touch_thread on public.msg_messages;
create trigger msg_touch_thread after insert on public.msg_messages
  for each row execute function public.msg_touch_thread();

commit;

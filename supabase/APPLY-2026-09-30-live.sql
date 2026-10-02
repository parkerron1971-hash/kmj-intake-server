-- Live, part 1 (Kevin's church plan, "Sermons & Live", 2026-09-30).
-- The church streams on YouTube/Facebook/Vimeo as it does today; the
-- member app shows that video with OUR chat beside it: signed-in members
-- only, host moderation (hide a message, pause a person), private prayer
-- (to Prayer & care, never the chat), and "I'm here", which counts the
-- member as online attendance for the service.
--
-- All four tables are SERVER-ONLY (like the kids check-in tables): members
-- are not Supabase users, and chat carries names, so the service role in
-- live_router.py / member_portal_live.py is the only door, behind the
-- team's role check or the member's signed session.
begin;

create table if not exists public.live_sessions(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  title text not null check (length(btrim(title)) between 1 and 120),
  stream_url text not null default '' check (stream_url = '' or (length(stream_url) <= 500 and stream_url ~ '^https://')),
  -- The service it counts toward: "I'm here" checks the member in there.
  entry_id uuid references public.module_entries(id) on delete set null,
  status text not null default 'live' check (status in ('live','ended')),
  chat_open boolean not null default true,
  -- Bumped on every chat insert/update, so a member's phone can ask
  -- "anything new?" with one cheap read.
  chat_version integer not null default 0,
  started_by uuid,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- One live service at a time per church.
create unique index if not exists live_sessions_one_live on public.live_sessions(business_id) where status = 'live';
create index if not exists live_sessions_business on public.live_sessions(business_id, started_at desc);

create table if not exists public.live_chat(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  session_id uuid not null references public.live_sessions(id) on delete cascade,
  -- Null for the host's own messages.
  contact_id uuid references public.contacts(id) on delete set null,
  -- "Ana R." — first name and last initial, fixed when sent.
  author text not null check (length(btrim(author)) between 1 and 80),
  host boolean not null default false,
  body text not null check (length(btrim(body)) between 1 and 500),
  hidden boolean not null default false,
  hidden_by uuid,
  hidden_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists live_chat_session on public.live_chat(session_id, created_at);

create table if not exists public.live_mutes(
  session_id uuid not null references public.live_sessions(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  muted_by uuid,
  created_at timestamptz not null default now(),
  primary key (session_id, contact_id)
);

create table if not exists public.live_presence(
  session_id uuid not null references public.live_sessions(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (session_id, contact_id)
);
create index if not exists live_presence_business on public.live_presence(business_id, created_at desc);

do $$ declare t text; begin
  foreach t in array array['live_sessions','live_chat','live_mutes','live_presence'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- Every row belongs to the business of the session / occasion / person it
-- points at. Nested IFs: PL/pgSQL does not short-circuit AND, and a
-- column a table doesn't have must never be read.
create or replace function public.live_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'live_sessions' then
    if new.entry_id is not null then
      if not exists (select 1 from public.module_entries e where e.id = new.entry_id and e.business_id = new.business_id) then
        raise exception 'That service is not in this business';
      end if;
    end if;
  else
    if not exists (select 1 from public.live_sessions s where s.id = new.session_id and s.business_id = new.business_id) then
      raise exception 'That live service is not in this business';
    end if;
    if new.contact_id is not null then
      if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
    end if;
  end if;
  return new;
end $$;

do $$ declare t text; begin
  foreach t in array array['live_sessions','live_chat','live_mutes','live_presence'] loop
    execute format('drop trigger if exists live_same_business on public.%I', t);
    execute format('create trigger live_same_business before insert or update on public.%I
      for each row execute function public.live_same_business()', t);
  end loop;
end $$;

create or replace function public.live_chat_bump() returns trigger
language plpgsql set search_path = public as $$
begin
  update public.live_sessions set chat_version = chat_version + 1, updated_at = now() where id = new.session_id;
  return new;
end $$;
drop trigger if exists live_chat_bump on public.live_chat;
create trigger live_chat_bump after insert or update on public.live_chat
  for each row execute function public.live_chat_bump();

-- "I'm here" checks the member in to the service as online attendance.
alter table public.attendance drop constraint if exists attendance_method_check;
alter table public.attendance add constraint attendance_method_check
  check (method in ('staff','station','self','rsvp','online'));

commit;

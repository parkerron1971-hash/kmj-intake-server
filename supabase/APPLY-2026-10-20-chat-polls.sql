-- Polls in a group's chat (Kevin, 2026-10-20: "let's continue so we can
-- finish up"; the approved canvas "Church Groups, Together", board Chat:
-- "Potluck theme for Nov 19? · Soul food 9 · Breakfast for dinner 4 · Taco
-- bar 3 · 16 votes · closes Friday"; board Settings: "Photos and polls").
-- A poll is a message: its question is the message's text, checked like
-- any message, and its choices are checked with it. Idempotent.
--
--   msg_polls           a message's 2-4 choices and when voting closes
--   msg_poll_votes      one vote per person per poll
--   groups.chat_extras  a group's leaders can turn photos and polls off
--                       (on by default)
begin;

alter table public.groups add column if not exists chat_extras boolean not null default true;

-- 2-4 choices, each 1-60 characters after trimming.
create or replace function public.msg_poll_choices_ok(c text[]) returns boolean
language sql immutable set search_path = public as $$
  select coalesce(array_length(c, 1) between 2 and 4, false)
     and coalesce((select bool_and(x is not null and char_length(btrim(x)) between 1 and 60) from unnest(c) x), false)
$$;

create table if not exists public.msg_polls(
  message_id uuid primary key references public.msg_messages(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  choices text[] not null check (public.msg_poll_choices_ok(choices)),
  closes_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index if not exists msg_polls_business on public.msg_polls(business_id);

create table if not exists public.msg_poll_votes(
  message_id uuid not null references public.msg_polls(message_id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  choice smallint not null check (choice between 0 and 3),
  created_at timestamptz not null default now(),
  primary key (message_id, contact_id)
);
create index if not exists msg_poll_votes_business on public.msg_poll_votes(business_id);

-- Server-only, like the messages themselves.
alter table public.msg_polls enable row level security;
alter table public.msg_poll_votes enable row level security;
revoke all on public.msg_polls, public.msg_poll_votes from anon, authenticated;
grant all on public.msg_polls, public.msg_poll_votes to service_role;
revoke all on function public.msg_poll_choices_ok(text[]) from public, anon, authenticated;

-- A poll's message is this church's own; a vote is this church's own
-- person on this church's own poll, for one of its choices.
create or replace function public.msg_poll_same_business() returns trigger
language plpgsql set search_path = public as $$
declare n int;
begin
  if tg_table_name = 'msg_polls' then
    if not exists (select 1 from public.msg_messages m where m.id = new.message_id and m.business_id = new.business_id) then
      raise exception 'That message is not in this business';
    end if;
  else
    select array_length(p.choices, 1) into n from public.msg_polls p
     where p.message_id = new.message_id and p.business_id = new.business_id;
    if n is null then
      raise exception 'That poll is not in this business';
    end if;
    if new.choice >= n then
      raise exception 'That poll has no such choice';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.msg_poll_same_business() from public, anon, authenticated;
do $$ declare t text; begin
  foreach t in array array['msg_polls','msg_poll_votes'] loop
    execute format('drop trigger if exists msg_poll_same_business on public.%I', t);
    execute format('create trigger msg_poll_same_business before insert or update on public.%I
      for each row execute function public.msg_poll_same_business()', t);
  end loop;
end $$;

commit;

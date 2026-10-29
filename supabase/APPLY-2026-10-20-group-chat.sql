-- A group's chat lives inside the group (Kevin, 2026-10-20: "there is no
-- area where people can communicate like a chat"; part 2 of the approved
-- canvas "Church Groups, Together"). The thread is still messaging's
-- (msg_threads kind group, every message checked by msg_screen); this adds
-- what a group chat needs. Idempotent.
--
--   msg_reactions          Love / Praying / Amen on a message, one of each
--                          per person
--   msg_messages.reply_to  a reply quotes the message it answers
--   groups.chat_on         the office can make a group Board-only
--   groups.chat_writers    all | leaders — a big team where only leaders write
begin;

alter table public.groups add column if not exists chat_on boolean not null default true;
alter table public.groups add column if not exists chat_writers text not null default 'all'
  check (chat_writers in ('all','leaders'));

alter table public.msg_messages add column if not exists reply_to uuid references public.msg_messages(id) on delete set null;

create table if not exists public.msg_reactions(
  message_id uuid not null references public.msg_messages(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null check (kind in ('love','pray','amen')),
  created_at timestamptz not null default now(),
  primary key (message_id, contact_id, kind)
);
create index if not exists msg_reactions_business on public.msg_reactions(business_id);

-- Server-only, like the messages themselves.
alter table public.msg_reactions enable row level security;
revoke all on public.msg_reactions from anon, authenticated;
grant all on public.msg_reactions to service_role;

-- A reaction's message and person, and a reply's message, are this
-- church's own (and a reply stays in its chat).
create or replace function public.msg_chat_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'msg_reactions' then
    if not exists (select 1 from public.msg_messages m where m.id = new.message_id and m.business_id = new.business_id) then
      raise exception 'That message is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif tg_table_name = 'msg_messages' then
    if new.reply_to is not null then
      if not exists (select 1 from public.msg_messages m
                     where m.id = new.reply_to and m.business_id = new.business_id and m.thread_id = new.thread_id) then
        raise exception 'That reply is not to a message in this chat';
      end if;
    end if;
  end if;
  return new;
end $$;
revoke all on function public.msg_chat_same_business() from public, anon, authenticated;
do $$ declare t text; begin
  foreach t in array array['msg_reactions','msg_messages'] loop
    execute format('drop trigger if exists msg_chat_same_business on public.%I', t);
    execute format('create trigger msg_chat_same_business before insert or update on public.%I
      for each row execute function public.msg_chat_same_business()', t);
  end loop;
end $$;

commit;

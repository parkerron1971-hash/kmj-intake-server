-- APPLY-2026-09-02-support-thread.sql
-- The conversation, so it stops dying.
--
-- Apply AFTER APPLY-2026-09-02-support-fix-queue.sql (this reads the
-- fix_state that one introduces). Idempotent; apply after merge.
--
-- What a practitioner could see about a ticket they filed, before this:
-- a three-value status, and ONE admin_reply column that the next reply
-- overwrites. No progress, no history, and no way to say anything back.
-- The support-tickets migration named the fix in its own header — "a
-- support_ticket_messages table is the clean v2 extension" — and this is
-- that table.
--
-- Everything in support_ticket_messages is TENANT-READABLE by design: it
-- is the practitioner's side of the conversation. Operator judgement stays
-- where it already lives, in support_triage, which no tenant can read.
-- That split is the whole safety model here, so nothing internal may ever
-- be written into this table — the server guards it with a word list, and
-- a test holds the guard.

create table if not exists public.support_ticket_messages (
  id          uuid primary key default gen_random_uuid(),
  ticket_id   uuid not null references public.support_tickets(id) on delete cascade,
  -- Denormalized so the tenant policy can subquery businesses directly,
  -- the same one-way shape tickets_tenant_select uses. Reaching the owner
  -- through support_tickets instead would add a second hop to a table
  -- whose own policy subqueries businesses, and A->B->C policy chains are
  -- how the 42P17 recursion outage started.
  business_id uuid not null references public.businesses(id) on delete cascade,
  created_at  timestamptz not null default now(),

  --   practitioner — the person who filed it
  --   support      — a human answering them
  --   system       — the ticket telling its own story: someone is looking,
  --                  a fix is being worked on, the fix has shipped
  author      text not null check (author in ('practitioner', 'support', 'system')),

  -- Which step a system message marks, so the app can badge it without
  -- parsing prose. Null on human messages.
  kind        text,

  body        text not null check (char_length(body) between 1 and 5000)
);

create index if not exists support_messages_ticket_idx
  on public.support_ticket_messages (ticket_id, created_at);
create index if not exists support_messages_business_idx
  on public.support_ticket_messages (business_id, created_at desc);

alter table public.support_ticket_messages enable row level security;

-- Read: the businesses you own. Same subquery shape as tickets_tenant_select.
drop policy if exists support_messages_tenant_select on public.support_ticket_messages;
create policy support_messages_tenant_select on public.support_ticket_messages
  for select to authenticated
  using (business_id in (select id from public.businesses where owner_id = auth.uid()));

-- Write: platform owner only. A practitioner's own message goes through
-- POST /support/tickets/{id}/messages (JWT + owner check) rather than a
-- direct insert, because sending it has to DO things — reopen the ticket,
-- put it back in the queue, and tell the operator somebody is waiting.
-- None of that can hang off a PostgREST insert.
drop policy if exists support_messages_owner_all on public.support_ticket_messages;
create policy support_messages_owner_all on public.support_ticket_messages
  for all to authenticated
  using (public.is_platform_owner())
  with check (public.is_platform_owner());

-- ────────────────────────────────────────────────────────────────────
-- The practitioner-facing projection, cached on the ticket.
--
-- stage is what THEY see: received -> looking -> working -> fixed ->
-- answered. It is NOT a fourth status (support_tickets.status keeps its
-- three values; Mission Control's panel indexes a lookup table by that
-- column and a new value would blank the panel) and it is NOT a second
-- source of truth — it is written only by the same server call that
-- appends the matching system message, so the badge and the thread can
-- never disagree.
--
-- Deliberately NO check constraint. The workspace_archetype CHECK went
-- out of step with the app's own list in August and Postgres rejected
-- writes that the app had already called successful, silently. Stages
-- will gain values; the app falls back to "received" on anything it does
-- not recognise, so a stale value degrades to a working badge.
-- ────────────────────────────────────────────────────────────────────

alter table public.support_tickets
  add column if not exists stage text not null default 'received';

-- Who spoke last, and when. Denormalized for the same reason as stage:
-- the list view has to show "waiting on you" without a per-row query.
alter table public.support_tickets
  add column if not exists last_message_at timestamptz;
alter table public.support_tickets
  add column if not exists last_message_author text;

create index if not exists support_tickets_waiting_idx
  on public.support_tickets (last_message_author, last_message_at desc)
  where last_message_author = 'practitioner';

-- Existing tickets: the reply that is already on them is the first message
-- of their thread, so an old ticket opens as a conversation rather than a
-- blank page. Runs once — the insert skips any ticket that already has one.
insert into public.support_ticket_messages (ticket_id, business_id, created_at, author, body)
select t.id, t.business_id, coalesce(t.replied_at, t.updated_at, t.created_at),
       'support', t.admin_reply
  from public.support_tickets t
 where t.admin_reply is not null
   and char_length(t.admin_reply) between 1 and 5000
   and not exists (select 1 from public.support_ticket_messages m
                    where m.ticket_id = t.id);

update public.support_tickets t
   set stage = case when t.status = 'resolved' then 'answered'
                    when t.status = 'in_progress' then 'looking'
                    else 'received' end,
       last_message_at = coalesce(t.replied_at, t.created_at),
       last_message_author = case when t.admin_reply is not null
                                  then 'support' else 'practitioner' end
 where t.last_message_at is null;

-- ────────────────────────────────────────────────────────────────────
-- VERIFICATION (run after applying)
--
--   select to_regclass('public.support_ticket_messages') is not null;
--   select policyname, cmd from pg_policies
--    where tablename = 'support_ticket_messages';   -- expect select + all
--   select count(*) from public.support_ticket_messages;  -- = tickets with
--                                                          an admin_reply
--   select stage, count(*) from public.support_tickets group by stage;
--   -- and no ticket left unprojected:
--   select count(*) from public.support_tickets where last_message_at is null;
-- ────────────────────────────────────────────────────────────────────

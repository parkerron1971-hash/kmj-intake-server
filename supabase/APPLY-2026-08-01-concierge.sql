-- APPLY-2026-08-01-concierge.sql
-- RUN ONCE in the Supabase SQL Editor (whole file). NOT YET APPLIED.
--
-- THE SITE CONCIERGE (site_concierge.py) — a customer-facing chat agent
-- on practitioners' public composed sites. Two tables:
--
--   concierge_conversations — one row per visitor conversation
--     (business_id, visitor_key = hashed ip+ua, status open/escalated/
--      closed, contact_id once a lead is captured)
--   concierge_messages      — the turns (role visitor/concierge)
--
-- ACCESS MODEL:
--   * WRITES: backend service-role ONLY (the public endpoints are anon
--     HTTP but write through the service client, rate-limited + capped
--     in site_concierge.py). No anon/authenticated INSERT/UPDATE/DELETE
--     policies exist, so PostgREST callers cannot write at all.
--   * READS: tenant_member_read for any ACTIVE seat + the owner, via
--     the SECURITY DEFINER helpers public.is_business_member /
--     public.is_business_owner (2026_06_10_hotfix_rls_recursion.sql) —
--     the trust-seat-visibility pattern. concierge_messages carries no
--     business_id by design, so its policy goes through a NEW
--     SECURITY DEFINER helper that resolves the conversation's
--     business_id first. Inline cross-table EXISTS inside policies is
--     the 42P17 recursion outage class — never that.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.concierge_conversations (
  id          uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  started_at  timestamptz not null default now(),
  visitor_key text,
  status      text not null default 'open'
              check (status in ('open', 'escalated', 'closed')),
  contact_id  uuid references public.contacts(id) on delete set null
);

create index if not exists idx_concierge_conversations_biz
  on public.concierge_conversations (business_id, started_at desc);
create index if not exists idx_concierge_conversations_visitor
  on public.concierge_conversations (business_id, visitor_key);

create table if not exists public.concierge_messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null
                  references public.concierge_conversations(id) on delete cascade,
  role            text not null check (role in ('visitor', 'concierge')),
  body            text not null,
  created_at      timestamptz not null default now()
);

create index if not exists idx_concierge_messages_conv
  on public.concierge_messages (conversation_id, created_at);
create index if not exists idx_concierge_messages_created
  on public.concierge_messages (created_at);

-- ─── RLS ────────────────────────────────────────────────────────────

alter table public.concierge_conversations enable row level security;
alter table public.concierge_messages      enable row level security;

-- Conversations: owner + active seats read. (is_business_member covers
-- seats only; the owner needs is_business_owner — new tables have no
-- pre-existing owner policy to lean on, unlike the trust surfaces.)
drop policy if exists tenant_member_read on public.concierge_conversations;
create policy tenant_member_read on public.concierge_conversations
  for select to authenticated
  using (public.is_business_owner(business_id)
         or public.is_business_member(business_id));

-- Messages: resolve conversation → business through a SECURITY DEFINER
-- helper (no inline cross-table EXISTS in the policy — 42P17 class).
create or replace function public.is_concierge_conversation_member(conv uuid)
returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce(
    (select public.is_business_owner(c.business_id)
            or public.is_business_member(c.business_id)
       from public.concierge_conversations c
      where c.id = conv),
    false);
$$;

revoke all on function public.is_concierge_conversation_member(uuid)
  from public, anon;
grant execute on function public.is_concierge_conversation_member(uuid)
  to authenticated;

drop policy if exists tenant_member_read on public.concierge_messages;
create policy tenant_member_read on public.concierge_messages
  for select to authenticated
  using (public.is_concierge_conversation_member(conversation_id));

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expected: 2 rows, one tenant_member_read per table, cmd = SELECT.
select tablename, policyname, cmd
  from pg_policies
 where schemaname = 'public'
   and tablename in ('concierge_conversations', 'concierge_messages')
   and policyname = 'tenant_member_read'
 order by tablename;

-- Expected: zero write policies — anon/authenticated cannot write; the
-- service role bypasses RLS.
select count(*) as should_be_zero
  from pg_policies
 where schemaname = 'public'
   and tablename in ('concierge_conversations', 'concierge_messages')
   and cmd in ('INSERT', 'UPDATE', 'DELETE');

-- Expected: both tables have RLS enabled (relrowsecurity = true).
select relname, relrowsecurity
  from pg_class
 where relname in ('concierge_conversations', 'concierge_messages')
   and relnamespace = 'public'::regnamespace;

-- Expected: the helper exists and is SECURITY DEFINER (prosecdef = true).
select proname, prosecdef
  from pg_proc
 where proname = 'is_concierge_conversation_member'
   and pronamespace = 'public'::regnamespace;

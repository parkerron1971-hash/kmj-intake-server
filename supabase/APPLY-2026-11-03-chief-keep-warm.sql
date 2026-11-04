-- APPLY-2026-11-03-chief-keep-warm.sql
--
-- Chief's keep-warm, held in the database (chief_keep_warm.py). Chief's brief
-- is cached for an hour after its last use; a no-reply ping every ~50 minutes
-- keeps it while the business is using Chief. The pings were asyncio tasks in
-- the web process, and every merge to main restarts it: 475 deploys in the 30
-- days to 2026-11-03, a median of 26 minutes apart, against a first ping due
-- 55 minutes after a message, so 33 pings went out in 30 days and 4 of the 5
-- messages 1-4 h after the last one were full rewrites (~59c, not ~10c).
--
-- One row a business, written by the web after each main Chief call and read
-- by the worker's chief_keep_warm job (scheduler leader only), so a deploy of
-- either service no longer drops the chain:
--
--   payload            the ping as JSON text: the last call's request cut at
--                      its last 1-hour cache breakpoint, max_tokens 0. Text,
--                      not jsonb: jsonb puts object keys in its own order,
--                      and a tool schema with its keys moved is another
--                      prompt to the cache, so the ping would pay to write a
--                      copy instead of reading one. It holds the business's
--                      cached brief, so the table is server-only.
--   headers            the request's anthropic-beta header
--   prefix_hash        sha256 of payload + headers: the web sends the payload
--                      again only when it changed
--   last_call_at       the last main Chief call
--   touched_at         the last time the cached copy was used (that call, or
--                      a ping that read it); the worker pings at ~50 minutes
--   window_ends_at     the pings stop after this (4 h; 24 h for a business
--                      that uses Chief most days)
--   pings              pings since last_call_at
--   pinging_at         a worker's hold while its ping is out (90 s at most):
--                      touched_at moves only once the ping has read, so a
--                      worker that dies mid-ping leaves the true last use
--   stopped_at,        why the chain ended: wrote (a ping found no copy and
--   stopped_reason     paid for one), lapsed, window, midnight (the copy is
--                      gone at 00:00 UTC), refused, budget, off
--
-- Server-only: RLS on, no policies, the browser's roles revoked. A business
-- that goes takes its row. Additive, idempotent, nothing dropped. Until this is
-- applied the web keeps its in-process pings and the job does nothing.
-- Rollback: drop table public.chief_keep_warm;
begin;
set local lock_timeout = '5s';

create table if not exists public.chief_keep_warm(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  payload text not null check (left(payload, 1) = '{' and length(payload) <= 8000000),
  headers jsonb not null default '{}'::jsonb check (jsonb_typeof(headers) = 'object'),
  prefix_hash text not null check (prefix_hash ~ '^[0-9a-f]{64}$'),
  last_call_at timestamptz not null,
  touched_at timestamptz not null,
  window_ends_at timestamptz not null,
  pings integer not null default 0 check (pings >= 0),
  pinging_at timestamptz,
  stopped_at timestamptz,
  stopped_reason text check (stopped_reason is null or stopped_reason in
    ('wrote', 'lapsed', 'window', 'midnight', 'refused', 'budget', 'off'))
);

-- The worker's look for due copies: live chains, oldest touch first.
create index if not exists chief_keep_warm_live
  on public.chief_keep_warm (touched_at) where stopped_at is null;

alter table public.chief_keep_warm enable row level security;
revoke all on public.chief_keep_warm from anon, authenticated;
grant all on public.chief_keep_warm to service_role;

commit;

-- Verify after:
--   select c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = 'chief_keep_warm') as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--   from pg_class c where c.relname = 'chief_keep_warm';
--   (true, 0, false, false)

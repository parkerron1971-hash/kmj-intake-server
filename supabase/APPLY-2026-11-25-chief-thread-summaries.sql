-- APPLY-2026-11-25-chief-thread-summaries.sql
--
-- What was said earlier in a long conversation with Chief, kept short
-- (chief_thread_summary.py). Kevin, 2026-11-24, on Chief forgetting the start
-- of a long sitting: "ok great. lets build this."
--
-- The app sends Chief the last 30 messages of a chat. Anything older was
-- dropped, so in a long conversation Chief lost what was asked and decided at
-- the start. From now on the server folds the oldest messages of a long chat
-- into a short running summary before they fall off, and Chief reads that
-- summary with the messages it can still see.
--
-- chief_thread_summaries (server-only: RLS on, no policies, browser roles
-- revoked): one row a chat.
--   business_id, user_id, conversation_id
--                  whose chat: the business, the login that is talking, and
--                  the app's own id for the chat. One login's summary is never
--                  read for another login.
--   summary        the running summary, 4000 at most
--   folded         fingerprints (not text) of the last messages folded in, so
--                  the server can tell where the summary ends in what the app
--                  sends next
--   folded_count   how many messages have been folded in so far
--   version        goes up by one a write; a write names the version it read,
--                  so two replicas folding at once can't both land
-- No foreign key on the login: a login that leaves leaves nothing readable
-- (nobody reads this table but the server, for that login's own turns).
-- A business that goes takes its rows.
--
-- New table only: one transaction, safe to run twice, nothing dropped. Apply
-- any time: until then Chief works exactly as before (the oldest messages of a
-- long chat are dropped), and nothing is summarised or stored.
--
-- CHECK BEFORE (expect: no row):
--   select to_regclass('public.chief_thread_summaries');
begin;

set local lock_timeout = '5s';

create table if not exists public.chief_thread_summaries(
  business_id uuid not null references public.businesses(id) on delete cascade,
  user_id uuid not null,
  conversation_id text not null,
  summary text not null default '',
  folded jsonb not null default '[]'::jsonb,
  folded_count integer not null default 0,
  version integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (business_id, user_id, conversation_id),
  constraint chief_thread_summaries_id_len check (char_length(conversation_id) between 1 and 120),
  constraint chief_thread_summaries_summary_len check (char_length(summary) <= 4000),
  constraint chief_thread_summaries_folded_list check (jsonb_typeof(folded) = 'array'),
  constraint chief_thread_summaries_counts check (folded_count >= 0 and version >= 0)
);

-- For clearing out chats nobody has touched in a long while.
create index if not exists chief_thread_summaries_updated
  on public.chief_thread_summaries (updated_at);

alter table public.chief_thread_summaries enable row level security;
revoke all on public.chief_thread_summaries from public, anon, authenticated;
grant select, insert, update, delete on public.chief_thread_summaries to service_role;

notify pgrst, 'reload schema';
commit;

-- CHECK AFTER (expect: rls true, 0 policies, browser_reads false, server_writes true):
--   select c.relrowsecurity as rls,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('service_role', c.oid, 'insert') as server_writes
--     from pg_class c where c.relname = 'chief_thread_summaries';
--
-- ROLLBACK: CHIEF_THREAD_SUMMARY=off on kmj-intake-server stops the reading and the
-- folding at once. To remove what was stored as well:
--   drop table if exists public.chief_thread_summaries;

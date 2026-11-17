-- APPLY-2026-11-17-church-storage.sql
--
-- A storage allowance per church plan (church_storage.py; Kevin, 2026-11-17:
-- "build"). Each church plan includes a fixed amount of storage for all of
-- its files (Small 100 GB, Growing 250 GB, Established 500 GB, Large 1 TB).
-- When it is full the church chooses what to delete; the one rule is that a
-- recording made while already full is kept 14 days, with three warnings,
-- and is never deleted while it is a published sermon.
--
--   stream_sessions.removed_at      the church deleted it (or it was deleted
--                                   after its 14 days): its files are gone
--                                   from the media bucket. Not counted.
--   stream_sessions.keep_until      a recording made while the church was
--                                   over its allowance is kept until then.
--   stream_sessions.warnings_sent   0..3, the warnings about keep_until.
--   stream_sessions.last_warned_at  when the last one went out.
--   church_storage_notes            one row per church: near_noted_at, the
--                                   80% heads-up went out for this crossing
--                                   (cleared again below 75%). SERVER-ONLY,
--                                   like stream_sessions.
--   church_storage_files_bytes(p_business)  the bytes of every Supabase
--                                   Storage object whose path starts with
--                                   "<business id>/" (any bucket), which
--                                   PostgREST can't read itself. SECURITY
--                                   DEFINER, search_path '', reads only
--                                   storage.objects, EXECUTE for
--                                   service_role only.
--
-- Additive: four columns (the defaults need no table rewrite), one table,
-- one function. No data changed, one transaction, lock_timeout 5s, safe to
-- run twice. The backend works before it: CHURCH_STORAGE ships off, and
-- with it off nothing reads these columns. Apply it BEFORE setting
-- CHURCH_STORAGE=owner (or on). Until it is applied the storage meter, if
-- switched on, can't count files (files_counted false) and the session
-- reads fail.
--
-- Before (read-only):
--   select column_name from information_schema.columns
--    where table_schema = 'public' and table_name = 'stream_sessions'
--      and column_name in ('removed_at', 'keep_until', 'warnings_sent', 'last_warned_at');
--   -- expected before: 0 rows
begin;

set local lock_timeout = '5s';

alter table public.stream_sessions add column if not exists removed_at timestamptz;
alter table public.stream_sessions add column if not exists keep_until timestamptz;
alter table public.stream_sessions add column if not exists warnings_sent smallint not null default 0;
alter table public.stream_sessions add column if not exists last_warned_at timestamptz;
alter table public.stream_sessions drop constraint if exists stream_sessions_warnings_sent;
alter table public.stream_sessions add constraint stream_sessions_warnings_sent
  check (warnings_sent between 0 and 3);
-- The daily job's read: the recordings being kept.
create index if not exists stream_sessions_kept on public.stream_sessions(keep_until)
  where keep_until is not null and removed_at is null;

create table if not exists public.church_storage_notes(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  near_noted_at timestamptz,
  updated_at timestamptz not null default now()
);
alter table public.church_storage_notes enable row level security;
revoke all on public.church_storage_notes from anon, authenticated;
grant all on public.church_storage_notes to service_role;

create or replace function public.church_storage_files_bytes(p_business uuid)
returns bigint
language sql stable security definer set search_path = '' as $$
  select coalesce(sum(case when o.metadata->>'size' ~ '^[0-9]{1,18}$'
                           then (o.metadata->>'size')::bigint end), 0)::bigint
    from storage.objects o
   where o.name like p_business::text || '/%'
$$;
revoke all on function public.church_storage_files_bytes(uuid) from public, anon, authenticated;
grant execute on function public.church_storage_files_bytes(uuid) to service_role;

commit;

notify pgrst, 'reload schema';

-- Check:
--   select column_name, data_type, column_default, is_nullable from information_schema.columns
--    where table_schema = 'public' and table_name = 'stream_sessions'
--      and column_name in ('removed_at', 'keep_until', 'warnings_sent', 'last_warned_at') order by 1;
--   -- 4 rows; warnings_sent smallint, default 0, NOT NULL
--   select has_function_privilege('anon', 'public.church_storage_files_bytes(uuid)', 'EXECUTE') as anon,
--          has_function_privilege('authenticated', 'public.church_storage_files_bytes(uuid)', 'EXECUTE') as app,
--          has_function_privilege('service_role', 'public.church_storage_files_bytes(uuid)', 'EXECUTE') as server;
--   -- false, false, true
--   select has_table_privilege('authenticated', 'public.church_storage_notes', 'SELECT') as app_reads;
--   -- false
--   select public.church_storage_files_bytes('<a church id>');   -- its uploaded files, in bytes
--
-- Rollback (nothing else depends on it; switch CHURCH_STORAGE off first):
--   begin;
--   drop function if exists public.church_storage_files_bytes(uuid);
--   drop table if exists public.church_storage_notes;
--   drop index if exists public.stream_sessions_kept;
--   alter table public.stream_sessions drop constraint if exists stream_sessions_warnings_sent;
--   alter table public.stream_sessions drop column if exists last_warned_at,
--     drop column if exists warnings_sent, drop column if exists keep_until, drop column if exists removed_at;
--   commit;
--   notify pgrst, 'reload schema';

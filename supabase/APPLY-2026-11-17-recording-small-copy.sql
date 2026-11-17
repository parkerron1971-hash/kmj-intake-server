-- APPLY-2026-11-17-recording-small-copy.sql
--
-- Each service recording's smaller copy, which is also its download
-- (recording_copy.py; Kevin, 2026-11-17: "build"). The clip service makes
-- one ~720p MP4 of every ended recording (live/<business>/<session>/copy.mp4,
-- about 1.3 GB for a two-hour service instead of 6), and 14 days after the
-- service the full-quality segments are deleted and the copy stays.
--
--   stream_sessions.copy_state      null (no copy yet) | queued | working |
--                                   ready (made and checked) | failed
--   stream_sessions.copy_job        the clip service's job id for this try
--   stream_sessions.copy_tries      tries made (a try that made way for a
--                                   clip run isn't counted); at most 3
--   stream_sessions.copy_at         when copy_state last moved
--   stream_sessions.copy_bytes      the copy's size, read back from the
--                                   bucket; set only while it is ready
--   stream_sessions.copy_seconds    the copy's length (ffprobe)
--   stream_sessions.copy_made_at    when it became ready
--   stream_sessions.copy_error      why the last try failed
--   stream_sessions.full_removed_at the full-quality segments were deleted;
--                                   only ever with a ready copy (checked)
--
-- The storage meter counts bytes + copy_bytes while the full recording is
-- there and copy_bytes after full_removed_at (church_storage.stored_bytes).
--
-- Additive: nine columns (the one default needs no table rewrite), four
-- checks, two partial indexes. No data changed, one transaction,
-- lock_timeout 5s, safe to run twice. stream_sessions stays server-only (RLS
-- on, no policies). The backend works before it: the meter and the player
-- read these columns only once they exist, and CHURCH_STORAGE_SMALL_COPY
-- ships off. Apply it BEFORE setting CHURCH_STORAGE_SMALL_COPY=owner.
--
-- Before (read-only):
--   select column_name from information_schema.columns
--    where table_schema = 'public' and table_name = 'stream_sessions'
--      and (column_name like 'copy\_%' or column_name = 'full_removed_at');
--   -- expected before: 0 rows
begin;

set local lock_timeout = '5s';

alter table public.stream_sessions add column if not exists copy_state text;
alter table public.stream_sessions add column if not exists copy_job uuid;
alter table public.stream_sessions add column if not exists copy_tries smallint not null default 0;
alter table public.stream_sessions add column if not exists copy_at timestamptz;
alter table public.stream_sessions add column if not exists copy_bytes bigint;
alter table public.stream_sessions add column if not exists copy_seconds numeric(10, 2);
alter table public.stream_sessions add column if not exists copy_made_at timestamptz;
alter table public.stream_sessions add column if not exists copy_error text;
alter table public.stream_sessions add column if not exists full_removed_at timestamptz;

alter table public.stream_sessions drop constraint if exists stream_sessions_copy_state;
alter table public.stream_sessions add constraint stream_sessions_copy_state
  check (copy_state is null or copy_state in ('queued', 'working', 'ready', 'failed'));
alter table public.stream_sessions drop constraint if exists stream_sessions_copy_tries;
alter table public.stream_sessions add constraint stream_sessions_copy_tries
  check (copy_tries between 0 and 20);
alter table public.stream_sessions drop constraint if exists stream_sessions_copy_bytes;
alter table public.stream_sessions add constraint stream_sessions_copy_bytes
  check (copy_bytes is null or copy_bytes > 0);
-- The full-quality recording goes only when a checked copy stays.
alter table public.stream_sessions drop constraint if exists stream_sessions_full_removed;
alter table public.stream_sessions add constraint stream_sessions_full_removed
  check (full_removed_at is null or (copy_state = 'ready' and copy_bytes is not null));

-- The job's reads: recordings still to copy or trim, and the copy under way.
create index if not exists stream_sessions_copy_todo on public.stream_sessions(ended_at)
  where status = 'ended' and removed_at is null and full_removed_at is null;
create index if not exists stream_sessions_copy_busy on public.stream_sessions(copy_at)
  where copy_state in ('queued', 'working');

commit;

notify pgrst, 'reload schema';

-- Check:
--   select column_name, data_type, column_default, is_nullable from information_schema.columns
--    where table_schema = 'public' and table_name = 'stream_sessions'
--      and (column_name like 'copy\_%' or column_name = 'full_removed_at') order by 1;
--   -- 9 rows; copy_tries smallint, default 0, NOT NULL
--   select conname from pg_constraint where conrelid = 'public.stream_sessions'::regclass
--      and conname in ('stream_sessions_copy_state', 'stream_sessions_copy_tries',
--                      'stream_sessions_copy_bytes', 'stream_sessions_full_removed') order by 1;
--   -- 4 rows
--   select copy_state, count(*) from public.stream_sessions group by 1;   -- all null at first
--
-- Rollback (switch CHURCH_STORAGE_SMALL_COPY off first; a recording whose
-- full_removed_at is set has only its copy left, so keep the columns while
-- any row has one: select count(*) from stream_sessions where full_removed_at is not null):
--   begin;
--   drop index if exists public.stream_sessions_copy_busy;
--   drop index if exists public.stream_sessions_copy_todo;
--   alter table public.stream_sessions drop constraint if exists stream_sessions_full_removed,
--     drop constraint if exists stream_sessions_copy_bytes, drop constraint if exists stream_sessions_copy_tries,
--     drop constraint if exists stream_sessions_copy_state;
--   alter table public.stream_sessions drop column if exists full_removed_at, drop column if exists copy_error,
--     drop column if exists copy_made_at, drop column if exists copy_seconds, drop column if exists copy_bytes,
--     drop column if exists copy_at, drop column if exists copy_tries, drop column if exists copy_job,
--     drop column if exists copy_state;
--   commit;
--   notify pgrst, 'reload schema';

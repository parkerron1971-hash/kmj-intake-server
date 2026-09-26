-- APPLY-2026-09-26-calendar-feeds.sql
--
-- "Use the calendar you already have." A practitioner pastes a private
-- calendar link (Google's secret iCal address, an Outlook published
-- calendar, an iCloud public calendar, an Acuity sync feed; Calendly and
-- Square come in through the Google or Outlook calendar they write to)
-- and its busy times block booking slots. Code: outside_calendar.py,
-- calendar_feeds_router.py.
--
-- calendar_feeds        one row per connected calendar. `url` is a
--                       SECRET: anyone holding it reads the whole
--                       calendar. The server never returns it whole,
--                       never logs it, and never exports it.
-- calendar_busy_blocks  busy times ONLY: start, end, all-day, and a hash
--                       of the event UID so a re-sync updates rather than
--                       duplicates. No titles, attendees, descriptions or
--                       locations are stored: that is other people's data.
--
-- Server-owned: RLS on, NO policies, no anon/authenticated grants
-- (docs/RLS_MODEL.md). Every read and write goes through the service role
-- after the owner check in calendar_feeds_router. Both tables cascade
-- with the business (account_lifecycle.EXPORT_EXCLUDED says why).
--
-- The code is fail-soft without this migration: slots are computed
-- exactly as before and the app shows the card as "coming soon".
--
-- Idempotent.

begin;

create table if not exists public.calendar_feeds (
  id               uuid primary key default gen_random_uuid(),
  business_id      uuid not null references public.businesses(id) on delete cascade,
  label            text not null default 'My calendar' check (char_length(label) between 1 and 80),
  url              text not null check (char_length(url) between 8 and 2048),
  url_hash         text not null,                  -- sha256(url): dedupe without comparing secrets
  provider         text not null default 'other'
                     check (provider in ('google','outlook','icloud','acuity','calendly','square','other')),
  status           text not null default 'pending' check (status in ('pending','ok','error')),
  last_synced_at   timestamptz,
  last_error       text,                           -- plain words, shown to the practitioner
  busy_count       integer not null default 0,
  failure_count    integer not null default 0,     -- drives the retry back-off
  next_sync_at     timestamptz,                    -- when the scheduler should read it next
  sync_lock_until  timestamptz,                    -- one sync at a time, across replicas
  created_by       uuid,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (business_id, url_hash)
);

create index if not exists calendar_feeds_business_idx
  on public.calendar_feeds (business_id);
create index if not exists calendar_feeds_next_sync_idx
  on public.calendar_feeds (next_sync_at nulls first);

create table if not exists public.calendar_busy_blocks (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses(id) on delete cascade,
  feed_id      uuid not null references public.calendar_feeds(id) on delete cascade,
  starts_at    timestamptz not null,
  ends_at      timestamptz not null,
  all_day      boolean not null default false,
  uid_hash     text not null,
  sync_run     uuid,                               -- which sync wrote it; older runs are swept
  created_at   timestamptz not null default now(),
  check (ends_at > starts_at),
  unique (feed_id, uid_hash, starts_at)
);

-- The booking paths ask "anything busy overlapping [lo, hi) for this
-- business?": business_id + starts_at < hi, then ends_at > lo.
create index if not exists calendar_busy_blocks_business_time_idx
  on public.calendar_busy_blocks (business_id, starts_at, ends_at);
create index if not exists calendar_busy_blocks_feed_idx
  on public.calendar_busy_blocks (feed_id);

alter table public.calendar_feeds enable row level security;
alter table public.calendar_busy_blocks enable row level security;
revoke all on table public.calendar_feeds from anon, authenticated;
revoke all on table public.calendar_busy_blocks from anon, authenticated;
grant all on table public.calendar_feeds to service_role;
grant all on table public.calendar_busy_blocks to service_role;

commit;

-- PostgREST picks up new tables on its own after DDL; if the app still
-- reports "not set up yet" a minute later, run:
--   notify pgrst, 'reload schema';
--
-- Verify:
--   select to_regclass('public.calendar_feeds') is not null,
--          to_regclass('public.calendar_busy_blocks') is not null;          -- true, true
--   select relname, relrowsecurity from pg_class
--    where relname in ('calendar_feeds','calendar_busy_blocks');            -- both true
--   select count(*) from pg_policies
--    where tablename in ('calendar_feeds','calendar_busy_blocks');          -- 0
--   select has_table_privilege('anon', 'public.calendar_feeds', 'select'),
--          has_table_privilege('authenticated', 'public.calendar_feeds', 'select');  -- false, false

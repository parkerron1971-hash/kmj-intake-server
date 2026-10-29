-- APPLY-2026-10-26-worship-calendar.sql
--
-- ChurchSavvy's "Bring in from the calendar" (round 5, canvas board 18; idea
-- A4): the calendar link a church pastes once (Google's iCal address,
-- Outlook's published calendar, iCloud), so its events can come onto the
-- announcements board. One row a church. The link is a secret, like
-- calendar_feeds' (a Google secret address reads the whole calendar): it is
-- never returned whole, never logged, and never exported
-- (account_lifecycle.EXPORT_EXCLUDED). worship_announce_import.py checks it
-- (outside_calendar.normalize_feed_url) and only ever fetches it through
-- outside_calendar.fetch_feed.
--
-- Server-only: RLS on with no policies, browser roles revoked. Additive:
-- nothing reads it until the code ships. Safe to run twice.

create table if not exists public.worship_calendar (
  business_id uuid primary key references public.businesses(id) on delete cascade,
  url text not null check (char_length(url) between 12 and 2000 and url like 'https://%'),
  provider text not null default 'other' check (char_length(provider) <= 20),
  updated_at timestamptz not null default now()
);

alter table public.worship_calendar enable row level security;
revoke all on public.worship_calendar from anon, authenticated;
grant all on public.worship_calendar to service_role;

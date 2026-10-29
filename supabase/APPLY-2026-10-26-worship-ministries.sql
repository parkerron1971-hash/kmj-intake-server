-- APPLY-2026-10-26-worship-ministries.sql
--
-- ChurchSavvy's ministries send their own announcements (round 5, canvas
-- UZu4VsoY9KemkUGorz234j boards 18 and 20; idea A5). One row per ministry a
-- church gives a link to: its name, its leader and the leader's email (the
-- office's answer and Wednesday's reminder go there), whether the leader
-- wants that reminder, the link's number (a new link retires the old one)
-- and the day the last reminder went (the sweep's once-a-week claim).
-- worship_ministries.py checks every field; the checks here hold the shape.
--
-- Server-only: RLS on with no policies, browser roles revoked. Additive:
-- nothing reads it until the code ships. Safe to run twice.

create table if not exists public.worship_ministries (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 60),
  leader_name text not null default '' check (char_length(leader_name) <= 80),
  leader_email text not null default '' check (char_length(leader_email) <= 254),
  remind boolean not null default true,
  link_n integer not null default 1 check (link_n between 1 and 1000000),
  reminded_on date,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists worship_ministries_by_church
  on public.worship_ministries (business_id, archived_at);

alter table public.worship_ministries enable row level security;
revoke all on public.worship_ministries from anon, authenticated;
grant all on public.worship_ministries to service_role;

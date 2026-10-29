-- The announcements board (ChurchSavvy round 5, canvas UZu4VsoY9KemkUGorz234j
-- boards 18-21; Kevin 2026-10-26: "these are a go. build it").
--
--   worship_announcements   one announcement a church makes once: its words,
--                           a picture or the whole flyer, a QR code, its
--                           design, the days it shows (it retires itself the
--                           day after `show_until`) and where (the room, the
--                           lobby, online, phones). A ministry's request
--                           waits for the office (`status` waiting).
--
-- Server-only like the other worship tables: RLS on, no policies, browser
-- roles revoked; worship_announce_router.py checks the seat on every call.
-- Idempotent.
begin;

create table if not exists public.worship_announcements(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  title text not null check (char_length(btrim(title)) between 1 and 80),
  when_text text not null default '' check (char_length(when_text) <= 80),
  where_text text not null default '' check (char_length(where_text) <= 80),
  body text not null default '' check (char_length(body) <= 140),
  image_url text not null default '' check (image_url = '' or (image_url ~ '^https://' and char_length(image_url) <= 600)),
  design text not null default 'side' check (design in ('side', 'flyer', 'date', 'card', 'week', 'save')),
  event_on date,
  qr jsonb not null default '{}'::jsonb check (jsonb_typeof(qr) = 'object' and octet_length(qr::text) <= 1000),
  show_from date,
  show_until date,
  shows jsonb not null default '{"room": true, "lobby": true, "online": false, "phones": true}'::jsonb
    check (jsonb_typeof(shows) = 'object' and octet_length(shows::text) <= 200),
  status text not null default 'on' check (status in ('on', 'waiting', 'declined')),
  source text not null default 'typed' check (source in ('typed', 'calendar', 'ministry')),
  source_ref text not null default '' check (char_length(source_ref) <= 200),
  sent_by jsonb not null default '{}'::jsonb check (jsonb_typeof(sent_by) = 'object' and octet_length(sent_by::text) <= 1000),
  sort integer not null default 0 check (sort between 0 and 10000),
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (show_from is null or show_until is null or show_from <= show_until)
);
create index if not exists worship_announcements_by_church
  on public.worship_announcements (business_id, archived_at, show_until);

alter table public.worship_announcements enable row level security;
revoke all on public.worship_announcements from anon, authenticated;
grant all on public.worship_announcements to service_role;

commit;

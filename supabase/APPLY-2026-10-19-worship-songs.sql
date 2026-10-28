-- The church song library for Sunday screens (ChurchSavvy, step 2:
-- "the show engine and songs"; Kevin approved the "ChurchSavvy Presenter"
-- canvas 2026-10-19: "add 1-4 to the canvas, then start step 2 ... you can
-- begin"). One table, server-only (RLS on, no policies, browser roles
-- revoked); worship_router.py checks the seat on every read and write.
--
--   worship_songs   a song: its words as sections (worship_lyrics.py's
--                   shape: [{id, kind, number, label, lines}]), the
--                   orders it is sung in ([{id, name, order: [section id]}]),
--                   how many lines go on a slide, and the facts a CCLI
--                   report needs. `source` says where the words came from;
--                   (source, source_ref) keeps a Proclaim import from
--                   adding the same song twice. `times_sung` is
--                   {"2026": 15}: counts brought over from Proclaim now,
--                   and Sundays run in ChurchSavvy later.
-- Idempotent.
begin;

create table if not exists public.worship_songs(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  title text not null check (char_length(btrim(title)) between 1 and 160),
  needs_title boolean not null default false,
  authors text not null default '' check (char_length(authors) <= 300),
  ccli_number text check (ccli_number is null or ccli_number ~ '^[0-9]{3,9}$'),
  copyright text not null default '' check (char_length(copyright) <= 300),
  public_domain boolean not null default false,
  song_key text check (song_key is null or song_key ~ '^[A-G](#|b)?m?$'),
  tempo integer check (tempo is null or tempo between 20 and 300),
  sections jsonb not null default '[]'::jsonb
    check (jsonb_typeof(sections) = 'array' and jsonb_array_length(sections) <= 40 and octet_length(sections::text) <= 60000),
  arrangements jsonb not null default '[]'::jsonb
    check (jsonb_typeof(arrangements) = 'array' and jsonb_array_length(arrangements) <= 12 and octet_length(arrangements::text) <= 20000),
  lines_per_slide integer not null default 2 check (lines_per_slide between 1 and 6),
  has_words boolean not null default false,
  source text not null default 'typed' check (source in ('typed', 'pasted', 'songselect', 'proclaim', 'photo', 'hymnal')),
  source_ref text not null default '' check (char_length(source_ref) <= 200),
  times_sung jsonb not null default '{}'::jsonb check (jsonb_typeof(times_sung) = 'object'),
  last_sung date,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists worship_songs_by_church
  on public.worship_songs (business_id, archived_at, title);
-- An import that runs twice updates, never duplicates.
create unique index if not exists worship_songs_source_once
  on public.worship_songs (business_id, source, source_ref) where source_ref <> '';

alter table public.worship_songs enable row level security;
revoke all on public.worship_songs from anon, authenticated;
grant all on public.worship_songs to service_role;

commit;

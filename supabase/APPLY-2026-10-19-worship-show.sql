-- The show engine under Sunday's screens (ChurchSavvy, step 2; Kevin
-- 2026-10-19: "keep going with step 2 I want the entire thing built").
-- Four tables, server-only (RLS on, no policies, browser roles revoked);
-- worship_show_router.py checks the seat on every signed-in read and
-- write, and a screen's own link (its token) is the only key to what that
-- screen shows.
--
--   worship_services   one service (a Sunday): its items in order, each a
--                      song, a passage, text slides, an announcement,
--                      a picture or video, a countdown, or a section
--                      heading (worship_show.py's shapes). A template is
--                      a service kept to start the next one from.
--   worship_screens    each screen the church shows on: the room's
--                      projector, the stream's lower third, an LED wall,
--                      the stage display, the lobby. `token` is the
--                      screen's link; a new link retires the old one.
--   worship_settings   one row a church: the look every slide wears.
--   worship_live       one row a church: what is on screen now (the
--                      service, item and slide, black/logo/clear, a
--                      passage put up on the spot, a message to the
--                      stage). `rev` only goes up; screens follow it.
-- Idempotent.
begin;

create table if not exists public.worship_services(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  title text not null default 'Sunday service' check (char_length(btrim(title)) between 1 and 120),
  starts_at timestamptz,
  items jsonb not null default '[]'::jsonb
    check (jsonb_typeof(items) = 'array' and jsonb_array_length(items) <= 80 and octet_length(items::text) <= 200000),
  notes text not null default '' check (char_length(notes) <= 4000),
  is_template boolean not null default false,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists worship_services_by_church
  on public.worship_services (business_id, archived_at, starts_at desc);

create table if not exists public.worship_screens(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 60),
  role text not null default 'room' check (role in ('room', 'online', 'led', 'stage', 'lobby')),
  width integer not null default 1920 check (width between 320 and 16384),
  height integer not null default 1080 check (height between 120 and 8192),
  fit text not null default 'wide' check (fit in ('wide', 'stretch', 'center')),
  led jsonb not null default '{}'::jsonb check (jsonb_typeof(led) = 'object' and octet_length(led::text) <= 500),
  token text not null check (token ~ '^[A-Za-z0-9_-]{32,64}$'),
  sort integer not null default 0 check (sort between 0 and 1000),
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists worship_screens_token on public.worship_screens (token);
create index if not exists worship_screens_by_church
  on public.worship_screens (business_id, archived_at, sort);

create table if not exists public.worship_settings(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  look jsonb not null default '{}'::jsonb check (jsonb_typeof(look) = 'object' and octet_length(look::text) <= 8000),
  updated_at timestamptz not null default now()
);

create table if not exists public.worship_live(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  service_id uuid references public.worship_services(id) on delete set null,
  state jsonb not null default '{}'::jsonb check (jsonb_typeof(state) = 'object' and octet_length(state::text) <= 60000),
  rev bigint not null default 0 check (rev >= 0),
  updated_at timestamptz not null default now()
);

alter table public.worship_services enable row level security;
alter table public.worship_screens enable row level security;
alter table public.worship_settings enable row level security;
alter table public.worship_live enable row level security;
revoke all on public.worship_services, public.worship_screens, public.worship_settings, public.worship_live from anon, authenticated;
grant all on public.worship_services, public.worship_screens, public.worship_settings, public.worship_live to service_role;

commit;

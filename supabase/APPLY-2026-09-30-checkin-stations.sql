-- Check-in stations (Kevin, 2026-09-29: "build it all so they can have
-- option as to how they want to do it" — a PIN-locked station tablet,
-- team seats, and a family self check-in kiosk). Idempotent.
--
-- A station is a device a manager pairs to the church: a tablet at the
-- welcome desk (mode 'staff': volunteers unlock it with the station PIN,
-- no team login) or a kiosk families use themselves (mode 'self': a
-- parent types their mobile number). The device holds a random token;
-- only its SHA-256 is stored. The PIN is stored as an HMAC under a
-- per-church key. Pairing uses a short-lived one-time code, stored hashed.
--
-- Server-only, like every families table. kids_station.py is the door.
begin;

create table if not exists public.checkin_stations(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (length(btrim(name)) between 1 and 60),
  mode text not null default 'staff' check (mode in ('staff','self')),
  pin_hash text not null,
  token_hash text,
  pair_code_hash text,
  pair_expires_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  paired_at timestamptz,
  last_seen_at timestamptz,
  revoked_at timestamptz
);
create index if not exists checkin_stations_business on public.checkin_stations(business_id, created_at desc);
create unique index if not exists checkin_stations_token on public.checkin_stations(token_hash) where token_hash is not null;
create unique index if not exists checkin_stations_pair on public.checkin_stations(pair_code_hash) where pair_code_hash is not null;

alter table public.checkin_stations enable row level security;
revoke all on public.checkin_stations from anon, authenticated;
grant all on public.checkin_stations to service_role;

-- Which station checked a child in (null for a team seat).
alter table public.child_checkins
  add column if not exists station_id uuid references public.checkin_stations(id) on delete set null;

create or replace function public.child_checkin_station_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.station_id is not null and not exists (
       select 1 from public.checkin_stations s
       where s.id = new.station_id and s.business_id = new.business_id) then
    raise exception 'That station is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.child_checkin_station_same_business() from public, anon, authenticated;
drop trigger if exists child_checkin_station_same_business on public.child_checkins;
create trigger child_checkin_station_same_business before insert or update on public.child_checkins
  for each row execute function public.child_checkin_station_same_business();

commit;

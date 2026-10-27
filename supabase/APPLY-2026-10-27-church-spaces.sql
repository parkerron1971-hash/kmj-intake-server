-- Rooms & spaces, with Rentals (church_spaces.py; Kevin 2026-10-27 on the
-- Church Menu Gaps check, "lets start building this": a family calls for the
-- fellowship hall for a funeral meal on Saturday, and there's no list of
-- rooms and no booking). Two tables, server-only (RLS on, no policies,
-- browser roles revoked); church_spaces.py reads and writes them.
--
--   church_spaces          a church's rooms, vehicles and equipment: name,
--                          kind, capacity, notes, active, sort order
--   church_space_bookings  one space for one stretch of time: requested,
--                          booked, declined or cancelled; who it's for (a
--                          contact) and who booked it (a sign-in id); a
--                          weekly repeat is one row a week sharing series_id.
--                          A rental carries a fee, a deposit (cents) and the
--                          bill (invoices.id) made for it once
--
-- Two BOOKED bookings of one space never overlap: an exclusion constraint
-- (btree_gist, for the space id's equality) refuses the second even when two
-- people press Book at the same moment. Requests, declined and cancelled
-- rows may overlap anything. A booking's space is its own church's (the
-- foreign key carries the business id).
-- Idempotent.
begin;

create extension if not exists btree_gist with schema extensions;

create table if not exists public.church_spaces(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  kind text not null default 'room' check (kind in ('room', 'vehicle', 'equipment')),
  capacity int check (capacity is null or capacity between 0 and 100000),
  notes text not null default '' check (char_length(notes) <= 1000),
  active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (business_id, id)
);

create table if not exists public.church_space_bookings(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  space_id uuid not null,
  title text not null check (char_length(title) between 1 and 120),
  start_at timestamptz not null,
  end_at timestamptz not null,
  contact_id uuid references public.contacts(id) on delete set null,
  booked_by uuid,
  status text not null default 'requested' check (status in ('requested', 'booked', 'declined', 'cancelled')),
  notes text not null default '' check (char_length(notes) <= 2000),
  series_id uuid,
  repeat_until date,
  kind text not null default 'use' check (kind in ('use', 'rental')),
  renter_name text check (renter_name is null or char_length(renter_name) <= 120),
  renter_email text check (renter_email is null or char_length(renter_email) <= 200),
  renter_phone text check (renter_phone is null or char_length(renter_phone) <= 120),
  fee_cents int not null default 0 check (fee_cents between 0 and 10000000),
  deposit_cents int not null default 0 check (deposit_cents between 0 and 10000000),
  invoice_id uuid references public.invoices(id) on delete set null,
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_space_bookings_space foreign key (business_id, space_id)
    references public.church_spaces(business_id, id) on delete cascade,
  constraint church_space_bookings_order check (end_at > start_at),
  constraint church_space_bookings_length check (end_at - start_at <= interval '14 days'),
  constraint church_space_bookings_no_clash exclude using gist
    (space_id with =, tstzrange(start_at, end_at) with &&) where (status = 'booked')
);

create index if not exists church_spaces_list
  on public.church_spaces(business_id, sort_order);
create index if not exists church_space_bookings_when
  on public.church_space_bookings(business_id, start_at);
create index if not exists church_space_bookings_waiting
  on public.church_space_bookings(business_id, status, start_at);
create index if not exists church_space_bookings_series
  on public.church_space_bookings(series_id) where series_id is not null;
create index if not exists church_space_bookings_rentals
  on public.church_space_bookings(business_id, end_at) where kind = 'rental';

alter table public.church_spaces enable row level security;
alter table public.church_space_bookings enable row level security;
revoke all on public.church_spaces from anon, authenticated;
revoke all on public.church_space_bookings from anon, authenticated;
grant all on public.church_spaces to service_role;
grant all on public.church_space_bookings to service_role;

commit;

-- Giving recorded by service (Kevin, 2026-11-01: "the system should be able
-- to recognize Sunday and already prepare for that service for giving").
-- giving_services.py. Server-only tables (RLS on, no policies, browser roles
-- revoked); every read and write goes through the giving gate (owner, admin
-- or the outside accountant, behind the giving keeper).
--
--   giving_services   the church's services: every week on a day at a time,
--                     or once on a date. collects_online: the online gifts
--                     since the last such service count toward this one.
--   giving_counts     one service's giving on one day, recorded together.
--                     Made when the day comes; closed once it's counted
--                     (the counted cash and checks, who counted, the lock).
--   invoices.giving_count_id   the count a gift belongs to.
--
-- The ledger triggers on invoices fire on total/status/paid_at/refund/
-- sent_at only, so placing a gift in a count never re-posts it; the gift
-- history trigger records the move. Idempotent.
begin;

create table if not exists public.giving_services(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  kind text not null check (kind in ('weekly', 'once')),
  weekday smallint check (weekday between 0 and 6),          -- 0 = Monday
  on_date date,
  start_time time not null,                                   -- the church's clock
  collects_online boolean not null default false,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((kind = 'weekly' and weekday is not null and on_date is null)
      or (kind = 'once' and on_date is not null and weekday is null))
);
create index if not exists giving_services_by_church
  on public.giving_services (business_id, archived_at);

create table if not exists public.giving_counts(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  service_id uuid references public.giving_services(id) on delete set null,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  service_date date not null,
  starts_at timestamptz not null,
  collects_online boolean not null default false,
  status text not null default 'open' check (status in ('open', 'closed')),
  counted_cash_cents bigint check (counted_cash_cents between 0 and 100000000),
  counted_checks_cents bigint check (counted_checks_cents between 0 and 100000000),
  counters text[] not null default '{}' check (cardinality(counters) <= 4),
  closed_at timestamptz,
  closed_by uuid,
  note text not null default '' check (char_length(note) <= 1000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint giving_counts_one_per_day unique (business_id, service_id, service_date)
);
create index if not exists giving_counts_by_day
  on public.giving_counts (business_id, service_date desc);

alter table public.invoices
  add column if not exists giving_count_id uuid references public.giving_counts(id) on delete set null;
create index if not exists invoices_by_giving_count
  on public.invoices (giving_count_id) where giving_count_id is not null;

alter table public.giving_services enable row level security;
alter table public.giving_counts enable row level security;
revoke all on public.giving_services, public.giving_counts from anon, authenticated;
grant all on public.giving_services, public.giving_counts to service_role;

commit;

-- Check:
--   select count(*) from information_schema.columns
--    where table_name = 'invoices' and column_name = 'giving_count_id';      -- 1
--   select to_regclass('public.giving_services'), to_regclass('public.giving_counts');

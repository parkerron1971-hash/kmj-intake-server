-- APPLY-2026-07-31-payroll-interest.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- The payroll waitlist (Gusto ruling: offer as demand-capture, pay
-- Gusto nothing until real clients ask). One row per business that
-- pressed the button; Kevin gets each one in the platform inbox with
-- a running total.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.payroll_interest (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,
  requested_by  uuid,
  requested_at  timestamptz not null default now(),
  unique (business_id)
);

alter table public.payroll_interest enable row level security;

drop policy if exists payroll_interest_owner_select on public.payroll_interest;
create policy payroll_interest_owner_select on public.payroll_interest
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = payroll_interest.business_id and b.owner_id = auth.uid()
  ));

comment on table public.payroll_interest is
  'The Gusto waitlist: businesses that pressed "I want payroll". Writes via the owner-gated /payroll/interest endpoint; the activation ruling reads the count.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='payroll_interest') as table_ok,
  (select count(*) from pg_policies
    where schemaname='public' and tablename='payroll_interest') as policies;

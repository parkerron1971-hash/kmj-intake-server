-- A minister's housing allowance (housing_allowance.py; Kevin 2026-10-30: "I
-- do have a housing allowance setup. so we need structure for this setup in
-- the system", and on who sees it: the owner only).
--
--   minister_housing_allowances  one minister's allowance for one tax year:
--                                the amount the board designated, the day it
--                                did (and the Board decision, when it was
--                                recorded there), the home's fair rental
--                                value (furnished, plus utilities) when
--                                known, and who the minister is: a name, and
--                                optionally one of the church's people and
--                                the payroll employee
--   minister_housing_entries     what happened against it: allowance PAID to
--                                the minister, or housing costs the minister
--                                SPENT (rent or mortgage, utilities,
--                                furnishings, repairs, insurance, property
--                                tax, other), each dated, with where it came
--                                from (typed in, a pay run, a bank row). A
--                                pay run's or bank row's entry is unique, so
--                                nothing counts twice
--
-- Server-only: RLS on, no policies, browser roles revoked. housing_allowance.py
-- is the only reader and writer, and it lets the business owner alone in.
-- Additive and idempotent; no drops.
begin;

create table if not exists public.minister_housing_allowances(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  minister_name text not null check (char_length(minister_name) between 1 and 120),
  contact_id uuid references public.contacts(id) on delete set null,
  employee_id uuid references public.employees(id) on delete set null,
  tax_year int not null check (tax_year between 2000 and 2200),
  designated_amount numeric(12,2) not null check (designated_amount >= 0),
  designated_on date not null,
  board_decision_id uuid references public.church_board_decisions(id) on delete set null,
  fair_rental_value numeric(12,2) check (fair_rental_value is null or fair_rental_value >= 0),
  notes text not null default '' check (char_length(notes) <= 2000),
  archived_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (business_id, id)
);

-- One live allowance per minister per year.
create unique index if not exists minister_housing_allowances_one_a_year
  on public.minister_housing_allowances(business_id, lower(minister_name), tax_year)
  where archived_at is null;

create table if not exists public.minister_housing_entries(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  allowance_id uuid not null,
  kind text not null check (kind in ('paid', 'spent')),
  entry_date date not null,
  amount numeric(12,2) not null check (amount > 0),
  category text not null default 'other' check (category in
    ('allowance', 'rent_mortgage', 'utilities', 'furnishings', 'repairs', 'insurance', 'property_tax', 'other')),
  note text not null default '' check (char_length(note) <= 500),
  source text not null default 'manual' check (source in ('manual', 'pay_run', 'bank')),
  source_id text check (source_id is null or char_length(source_id) <= 120),
  created_by uuid,
  created_at timestamptz not null default now(),
  constraint minister_housing_entries_allowance foreign key (business_id, allowance_id)
    references public.minister_housing_allowances(business_id, id) on delete cascade,
  constraint minister_housing_entries_kind_category check (
    (kind = 'paid' and category = 'allowance') or (kind = 'spent' and category <> 'allowance'))
);

create unique index if not exists minister_housing_entries_once
  on public.minister_housing_entries(allowance_id, source, source_id)
  where source_id is not null;
create index if not exists minister_housing_entries_allowance_day
  on public.minister_housing_entries(business_id, allowance_id, entry_date);

alter table public.minister_housing_allowances enable row level security;
alter table public.minister_housing_entries enable row level security;
revoke all on public.minister_housing_allowances from anon, authenticated;
revoke all on public.minister_housing_entries from anon, authenticated;
grant all on public.minister_housing_allowances to service_role;
grant all on public.minister_housing_entries to service_role;

commit;

notify pgrst, 'reload schema';

-- Check after applying (two rows, RLS on, no policies):
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies
--     from pg_class c where c.relname like 'minister_housing%' and c.relkind = 'r' order by 1;

-- Funds for the year (funds.py; Kevin 2026-10-31: "if we created a fund for
-- the year. we can place all what was paid out or sent out aligned with
-- that. wether it is housing pay etc...", and then, "build that", with the
-- money "exactly based on transaction").
--
--   business_funds        one fund for one year: its name, the budget set
--                         for it (optional), notes
--   business_fund_items   a bank transaction placed on a fund: all of it or
--                         a part (the housing part of a paycheck), with the
--                         day, a note, and whether it was money out or in
--                         (the bank row's sign, kept so the figures never
--                         hang on the bank feed). What all funds hold of
--                         one row never adds up past it (the server
--                         checks), and a row is on a fund once
--
-- Server-only: RLS on, no policies, browser roles revoked. funds.py is the
-- only reader and writer: the Transactions screen's readers may read, the
-- owner alone may change. Additive and idempotent; no drops.
begin;

create table if not exists public.business_funds(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  year int not null check (year between 2000 and 2200),
  name text not null check (char_length(name) between 1 and 80),
  budget numeric(14,2) check (budget is null or budget >= 0),
  notes text not null default '' check (char_length(notes) <= 2000),
  archived_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (business_id, id)
);

-- One live fund of a name a year.
create unique index if not exists business_funds_one_a_year
  on public.business_funds(business_id, year, lower(name))
  where archived_at is null;

create table if not exists public.business_fund_items(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  fund_id uuid not null,
  transaction_id text not null check (char_length(transaction_id) between 1 and 120),
  amount numeric(14,2) not null check (amount > 0),
  direction text not null check (direction in ('out', 'in')),
  entry_date date not null,
  note text not null default '' check (char_length(note) <= 500),
  placed_by uuid,
  created_at timestamptz not null default now(),
  constraint business_fund_items_fund foreign key (business_id, fund_id)
    references public.business_funds(business_id, id) on delete cascade
);

create unique index if not exists business_fund_items_once
  on public.business_fund_items(fund_id, transaction_id);
create index if not exists business_fund_items_by_row
  on public.business_fund_items(business_id, transaction_id);

alter table public.business_funds enable row level security;
alter table public.business_fund_items enable row level security;
revoke all on public.business_funds from anon, authenticated;
revoke all on public.business_fund_items from anon, authenticated;
grant all on public.business_funds to service_role;
grant all on public.business_fund_items to service_role;

commit;

notify pgrst, 'reload schema';

-- Check after applying (two rows, RLS on, no policies):
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies
--     from pg_class c where c.relname like 'business_fund%' and c.relkind = 'r' order by 1;

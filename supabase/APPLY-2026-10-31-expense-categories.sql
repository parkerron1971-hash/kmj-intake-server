-- A business's own expense categories (2026-10-31). Idempotent. Apply in the
-- Supabase SQL editor before the code (the categories read 503s until then).
--
-- Kevin: "can chief make expense catagories if i request it so transactions
-- can go under there?" A category is a name ("Utilities", "Benevolence") and
-- the line of the books it rolls up to; it is the label
-- (business_subcategory) the Profit & Loss already breaks spending out by.
-- The list keeps one spelling per name: one live category of a name per
-- business, whatever its case or spacing (expense_categories.py).
--
-- Server-only like the funds: RLS on, no policies.
begin;

create table if not exists public.expense_categories (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses(id) on delete cascade,
  name         text not null check (char_length(btrim(name)) between 1 and 60),
  bucket       text not null check (bucket in ('operating', 'tax', 'owner_pay', 'savings', 'other')),
  archived_at  timestamptz,
  created_by   uuid,
  created_at   timestamptz not null default now()
);
create unique index if not exists expense_categories_one_name
  on public.expense_categories (business_id, lower(btrim(name))) where archived_at is null;

alter table public.expense_categories enable row level security;
revoke all on public.expense_categories from anon, authenticated;
grant all on public.expense_categories to service_role;

commit;

notify pgrst, 'reload schema';

-- Check it landed:
--   select count(*) from information_schema.columns where table_name = 'expense_categories';   -- 7

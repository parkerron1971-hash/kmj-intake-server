-- A business's own names for the lines of its books, and lines of its own
-- (2026-11-01). Idempotent. Apply in the Supabase SQL editor before the code
-- (the categories read 503s until then: it reads expense_categories.line).
--
-- Kevin: "build option 1 with church names as default but allow for them to
-- be changed because other business would want different names also allow
-- for there to be added more to this list."
--
-- The five built-in lines (operating, tax, owner_pay, savings, other) stay the
-- books' accounts (5000-5900) and the only values business_category takes. A
-- row here either renames one of them (key = its base) or adds a line of the
-- business's own (key l_xxxxxxxx) that counts as one of the five in the books;
-- a category placed on an added line (expense_categories.line) shows under it
-- in the Profit & Loss (expense_lines.py).
--
-- Server-only like the categories: RLS on, no policies.
begin;

create table if not exists public.expense_lines (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses(id) on delete cascade,
  key          text not null check (key ~ '^(operating|tax|owner_pay|savings|other|l_[0-9a-f]{8})$'),
  name         text not null check (char_length(btrim(name)) between 1 and 40),
  base         text not null check (base in ('operating', 'tax', 'owner_pay', 'savings', 'other')),
  archived_at  timestamptz,
  created_by   uuid,
  created_at   timestamptz not null default now(),
  -- a rename of a built-in line is that line: its base is itself
  check (key like 'l\_%' or base = key)
);
create unique index if not exists expense_lines_one_key
  on public.expense_lines (business_id, key) where archived_at is null;
create unique index if not exists expense_lines_one_name
  on public.expense_lines (business_id, lower(btrim(name))) where archived_at is null;

alter table public.expense_lines enable row level security;
revoke all on public.expense_lines from anon, authenticated;
grant all on public.expense_lines to service_role;

-- The line a category rolls up to when it's one of the business's own; null
-- means its bucket's built-in line.
alter table public.expense_categories add column if not exists line text;

commit;

notify pgrst, 'reload schema';

-- Check it landed:
--   select count(*) from information_schema.columns where table_name = 'expense_lines';          -- 8
--   select count(*) from information_schema.columns
--    where table_name = 'expense_categories' and column_name = 'line';                            -- 1

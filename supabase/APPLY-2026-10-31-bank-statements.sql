-- Bank statements: the months before the bank feed (2026-10-31).
-- Idempotent. Apply in the Supabase SQL editor.
--
-- Plaid gives a newly linked bank 90 days, so Love City's feed starts
-- 2026-07-17 and January to mid-July isn't in the app. A statement (the
-- bank's CSV or OFX download, or the PDF statement read by Claude) adds
-- those rows (bank_statements.py):
--
--   bank_statement_imports   one row per statement added: which account,
--                            the period, its opening and closing balances,
--                            whether it added up, how many rows it added
--   plaid_transactions       + statement_import_id: the statement a row
--                            came from (NULL = the bank feed). Removing a
--                            statement removes its rows; the ledger's own
--                            insert/delete trigger posts and reverses them.
--
-- Server-only, like the funds: RLS on with no policies, so only the
-- service role reads or writes the new table. The bank rows keep their
-- existing owner policies.
begin;

create table if not exists public.bank_statement_imports (
  id               uuid primary key default gen_random_uuid(),
  business_id      uuid not null references public.businesses(id) on delete cascade,
  account_id       text not null references public.plaid_accounts(account_id) on delete cascade,
  file_name        text not null check (char_length(file_name) between 1 and 200),
  kind             text not null check (kind in ('csv', 'ofx', 'pdf')),
  period_start     date not null,
  period_end       date not null,
  opening_balance  numeric(14,2),
  closing_balance  numeric(14,2),
  money_in         numeric(14,2) not null default 0 check (money_in >= 0),
  money_out        numeric(14,2) not null default 0 check (money_out >= 0),
  check_state      text not null check (check_state in ('balanced', 'off', 'one_balance', 'no_balances')),
  check_difference numeric(14,2),
  rows_read        integer not null default 0 check (rows_read >= 0),
  rows_added       integer not null default 0 check (rows_added >= 0),
  feed_rows        integer not null default 0 check (feed_rows >= 0),
  feed_missing     integer not null default 0 check (feed_missing >= 0),
  created_by       uuid,
  created_at       timestamptz not null default now(),
  check (period_end >= period_start)
);

create index if not exists bank_statement_imports_by_account
  on public.bank_statement_imports (business_id, account_id, period_start);

alter table public.plaid_transactions
  add column if not exists statement_import_id uuid
    references public.bank_statement_imports(id) on delete cascade;

create index if not exists plaid_transactions_by_statement
  on public.plaid_transactions (statement_import_id)
  where statement_import_id is not null;

comment on column public.plaid_transactions.statement_import_id is
  'The bank statement this row was added from (bank_statements.py). NULL = the bank feed.';

alter table public.bank_statement_imports enable row level security;
revoke all on public.bank_statement_imports from anon, authenticated;
grant all on public.bank_statement_imports to service_role;

commit;

-- PostgREST caches the schema; without this the new column 400s (42703)
-- until its next reload.
notify pgrst, 'reload schema';

-- Check it landed:
--   select count(*) from information_schema.columns
--    where table_name = 'bank_statement_imports';                 -- 19
--   select column_name from information_schema.columns
--    where table_name = 'plaid_transactions' and column_name = 'statement_import_id';
--   select relrowsecurity from pg_class where relname = 'bank_statement_imports';   -- true

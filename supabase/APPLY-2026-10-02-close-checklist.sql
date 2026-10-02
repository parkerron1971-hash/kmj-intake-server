-- Close the month: the two checks that are answers, not computations
-- (2026-10-02). Idempotent. Apply in the Supabase SQL editor.
--
-- Close the month (bookkeeping_close.py) is one checklist per month:
-- sync, money in, categories, statement, look it over, lock. The first
-- three are computed from the bank rows. Two are the practitioner's
-- answers, and they need a home on the month itself:
--   statements  each account's ending balance from the bank statement
--               ({account_id: {balance, at, by}}); the books' own figure
--               is recomputed on every read, so a late row re-opens it
--   reviewed    "I looked over the month" ({at, by})
--   closed_with_open  the checks still open when the month was closed
--               anyway, so the audit trail can say what was skipped
-- Written only by the server (service role); the existing owner-read
-- policy on accounting_periods covers reads. The app works before this
-- runs (those two checks read as not done) and picks it up within five
-- minutes after.
begin;

alter table public.accounting_periods
  add column if not exists close_checklist jsonb not null default '{}'::jsonb;

comment on column public.accounting_periods.close_checklist is
  'Close the month answers: statements {account_id: {balance, at, by}}, reviewed {at, by}, closed_with_open [step keys].';

commit;

-- PostgREST caches the schema; without this the new column 400s (42703)
-- until its next reload.
notify pgrst, 'reload schema';

-- Check it landed:
--   select column_name from information_schema.columns
--    where table_name = 'accounting_periods' and column_name = 'close_checklist';

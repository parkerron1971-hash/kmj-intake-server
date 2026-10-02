-- What a bank row IS, when the bank's own label is wrong (2026-10-02).
-- Idempotent. Apply in the Supabase SQL editor.
--
-- Until now the books decided income vs. spending from Plaid's category
-- alone. A move between two of the business's own accounts ("Taxes to
-- Primary") was booked as income on one side and spending on the other,
-- and a deposit could not be marked "money from the owner" or "client
-- income" at all, because the only field a practitioner could set was the
-- five-bucket SPENDING category. On KMJ's books that added $988.69 to
-- income and $1,088.39 to spending (2026-10-01).
--
-- money_kind is the practitioner's answer, and NULL keeps today's
-- automatic behaviour exactly:
--   income    a deposit that IS business income (whatever Plaid says)
--   owner     money between the owner and the business: a contribution
--             in, or a draw out. Never income, never an expense.
--   transfer  a move between the business's own accounts. Never income,
--             never an expense (the ledger books it through 1050
--             Transfers in Transit, which nets to zero once both legs
--             post).
-- Read by bank_money.py. The app works before this runs and picks it up
-- within five minutes after.
begin;

alter table public.plaid_transactions
  add column if not exists money_kind text;

alter table public.plaid_transactions
  drop constraint if exists plaid_transactions_money_kind_check;
alter table public.plaid_transactions
  add constraint plaid_transactions_money_kind_check
  check (money_kind is null or money_kind in ('income', 'owner', 'transfer'));

comment on column public.plaid_transactions.money_kind is
  'What the row is when the bank label is wrong: income | owner | transfer. NULL = automatic (Plaid category).';

-- The ledger re-posts a bank row when anything it books from changes.
-- money_kind now changes the entry, so it joins the watched columns.
-- Same trigger as the LIVE one (2026_06_09_phasei4_gl_reports.sql, which
-- added business_subcategory), plus one line.
drop trigger if exists gl_enq_plaid_upd on public.plaid_transactions;
create trigger gl_enq_plaid_upd after update on public.plaid_transactions
  for each row when (
    old.reconciliation_status is distinct from new.reconciliation_status
    or old.business_category is distinct from new.business_category
    or old.business_subcategory is distinct from new.business_subcategory
    or old.excluded_from_books is distinct from new.excluded_from_books
    or old.amount is distinct from new.amount
    or old.money_kind is distinct from new.money_kind
  ) execute function public.gl_enqueue();

commit;

-- PostgREST caches the schema; without this the new column 400s (42703)
-- until its next reload.
notify pgrst, 'reload schema';

-- Check it landed:
--   select column_name from information_schema.columns
--    where table_name = 'plaid_transactions' and column_name = 'money_kind';

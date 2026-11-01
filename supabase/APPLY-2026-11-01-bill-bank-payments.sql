-- A bill matched to the bank payment that paid it (2026-11-01, Bills step 2).
-- Idempotent. Apply in the Supabase SQL editor BEFORE the code: the ledger's
-- bills read selects paid_transaction_id, so without the column it would read
-- no bills at all.
--
-- Kevin: the categories Chief made should work under the Bills tab too. A
-- bill books Dr expense / Cr AP; its bank payment, filed under a category,
-- books the expense and the cash again. Matched (bill_payments.py), the bill
-- books a settle (Dr AP / Cr its expense) instead of a second cash leg, so it
-- counts once (gl_engine.desired_for_bill).
begin;

-- The bank row (plaid_transactions.transaction_id) that paid this bill.
alter table public.bills add column if not exists paid_transaction_id text;

-- One bank payment pays one bill.
create unique index if not exists bills_one_bank_payment
  on public.bills (business_id, paid_transaction_id) where paid_transaction_id is not null;

-- The ledger re-posts a bill when it's matched or unmatched, and when its
-- category's name changes (a category rename now moves bills too).
drop trigger if exists gl_enq_bills_upd on public.bills;
create trigger gl_enq_bills_upd after update on public.bills
  for each row when (
    old.amount is distinct from new.amount
    or old.status is distinct from new.status
    or old.paid_at is distinct from new.paid_at
    or old.paid_amount is distinct from new.paid_amount
    or old.category is distinct from new.category
    or old.subcategory is distinct from new.subcategory
    or old.due_date is distinct from new.due_date
    or old.paid_transaction_id is distinct from new.paid_transaction_id
  ) execute function public.gl_enqueue();

commit;

notify pgrst, 'reload schema';

-- Check it landed:
--   select count(*) from information_schema.columns
--    where table_name = 'bills' and column_name = 'paid_transaction_id';      -- 1
--   select count(*) from pg_trigger where tgname = 'gl_enq_bills_upd';         -- 1

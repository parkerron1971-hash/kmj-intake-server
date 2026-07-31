-- APPLY-2026-07-31-expense-receipts.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Receipt capture (rails demand-driven): a bank line says "$80 at
-- Home Depot"; the photographed receipt says WHAT was bought, the tax,
-- and which job it belonged to. The image is stored in the existing
-- business-documents bucket; this column is the proof-link from the
-- expense row to its original image — the audit-time "show me the
-- receipt behind this number".
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

alter table public.business_expenses
  add column if not exists receipt_path text;

comment on column public.business_expenses.receipt_path is
  'Storage path of the photographed receipt behind this expense (business-documents bucket). The original image is the proof at tax time.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select count(*) as receipt_column_ok from information_schema.columns
 where table_schema='public' and table_name='business_expenses'
   and column_name='receipt_path';

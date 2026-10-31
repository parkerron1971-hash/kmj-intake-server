-- A housing allowance's paper trail (housing_allowance.py; Kevin
-- 2026-10-31, on what the IRS would ask to see: "add these structure and
-- rules in there as well").
--
--   minister_housing_allowances
--     minister_recused     the minister stepped out of the board's vote
--                          (null = not said; false = they voted on it)
--     comparables_note     what the board compared the pay with
--     minister_credential  ordained | licensed | commissioned
--     credential_detail    by whom, and when
--     se_tax_plan          estimates | withholding | exempt_4361: how the
--                          minister pays self-employment tax
--     cash_salary          the year's salary apart from the allowance (for
--                          the self-employment tax estimate)
--     fair_rental_basis    how the home's fair rental value was set
--     receipts_kept_where  where receipts not kept here are
--     w2_checked_on        the day the year's W-2 was checked
--   minister_housing_entries
--     receipt_path         a housing cost's receipt, in the private
--                          business-documents bucket (housing-receipts/)
--     receipt_type         image | pdf
--
-- Additive and idempotent; no drops. The tables stay server-only (RLS on,
-- no policies), which covers the new columns.
begin;

alter table public.minister_housing_allowances
  add column if not exists minister_recused boolean,
  add column if not exists comparables_note text check (comparables_note is null or length(comparables_note) <= 1000),
  add column if not exists minister_credential text
    check (minister_credential is null or minister_credential in ('ordained', 'licensed', 'commissioned')),
  add column if not exists credential_detail text check (credential_detail is null or length(credential_detail) <= 1000),
  add column if not exists se_tax_plan text
    check (se_tax_plan is null or se_tax_plan in ('estimates', 'withholding', 'exempt_4361')),
  add column if not exists cash_salary numeric(12,2) check (cash_salary is null or cash_salary >= 0),
  add column if not exists fair_rental_basis text check (fair_rental_basis is null or length(fair_rental_basis) <= 1000),
  add column if not exists receipts_kept_where text
    check (receipts_kept_where is null or length(receipts_kept_where) <= 1000),
  add column if not exists w2_checked_on date;

alter table public.minister_housing_entries
  add column if not exists receipt_path text check (receipt_path is null or length(receipt_path) <= 300),
  add column if not exists receipt_type text check (receipt_type is null or receipt_type in ('image', 'pdf'));

commit;

notify pgrst, 'reload schema';

-- Check after applying (eleven rows):
--   select table_name, column_name from information_schema.columns
--    where table_schema = 'public'
--      and ((table_name = 'minister_housing_allowances' and column_name in ('minister_recused',
--            'comparables_note', 'minister_credential', 'credential_detail', 'se_tax_plan', 'cash_salary',
--            'fair_rental_basis', 'receipts_kept_where', 'w2_checked_on'))
--        or (table_name = 'minister_housing_entries' and column_name in ('receipt_path', 'receipt_type')))
--    order by 1, 2;

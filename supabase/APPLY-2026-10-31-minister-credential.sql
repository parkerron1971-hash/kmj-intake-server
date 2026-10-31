-- How a minister in Pay your team is one (payroll_router.py; Kevin
-- 2026-10-31, "fix the three": only a church marks someone a minister, and
-- the owner says how they are one).
--
--   employees.minister_credential  ordained | licensed | commissioned: the
--                                  IRS's test for a minister (Publication
--                                  517). Required while `minister` is on;
--                                  cleared when it's turned off
--
-- Additive and idempotent; no drops. The table's existing RLS covers the
-- new column.
begin;

alter table public.employees
  add column if not exists minister_credential text
    check (minister_credential is null
           or minister_credential in ('ordained', 'licensed', 'commissioned'));

commit;

notify pgrst, 'reload schema';

-- Check after applying (one row):
--   select column_name, data_type from information_schema.columns
--    where table_schema = 'public' and table_name = 'employees'
--      and column_name = 'minister_credential';

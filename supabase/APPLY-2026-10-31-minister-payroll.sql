-- A minister in Pay your team (payroll_calc.py, payroll_router.py; Kevin
-- 2026-10-31, on his housing allowance: he isn't paid through the app yet,
-- "it's something in the future i want accounted for").
--
--   employees.minister                     paid for ministerial services: the
--                                          church withholds and pays no Social
--                                          Security or Medicare (the minister
--                                          pays self-employment tax), and no
--                                          FUTA (IRC 3121(b)(8), 3306(c)(8))
--   employees.housing_allowance_per_period the part of each check paid as
--                                          housing allowance, the default for
--                                          a new pay run's line
--   pay_run_items.housing_allowance        that part on one check (W-2 Box 14;
--                                          left out of Box 1). When the run is
--                                          marked paid it is logged to the
--                                          minister's housing allowance record
--
-- Additive and idempotent; no drops. The tables' existing RLS covers the
-- new columns.
begin;

alter table public.employees
  add column if not exists minister boolean not null default false,
  add column if not exists housing_allowance_per_period numeric(12,2)
    check (housing_allowance_per_period is null or housing_allowance_per_period >= 0);

alter table public.pay_run_items
  add column if not exists housing_allowance numeric(12,2) not null default 0
    check (housing_allowance >= 0);

commit;

notify pgrst, 'reload schema';

-- Check after applying (three rows):
--   select table_name, column_name, data_type from information_schema.columns
--    where table_schema = 'public'
--      and ((table_name = 'employees' and column_name in ('minister', 'housing_allowance_per_period'))
--        or (table_name = 'pay_run_items' and column_name = 'housing_allowance'))
--    order by 1, 2;

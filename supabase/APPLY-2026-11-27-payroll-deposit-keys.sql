-- APPLY-2026-11-27-payroll-deposit-keys.sql
--
-- M-6 (2026-11-27): two more deposit schedules for very small employers
-- (payroll_calendar.QUARTERLY, ANNUAL): paying with the quarter's Form 941,
-- and filing Form 944 for the year. Their keys are federal:YYYYQn,
-- federal:YYYY and forms:944:YYYY.
--
-- APPLY-2026-11-19-payroll-deposits.sql already carries the new key shape,
-- so a table made from it now needs nothing here. This file is only for a
-- table made from that file BEFORE it was updated: it swaps the key check
-- for the new one. Safe to run either way, and more than once: it does
-- nothing when the table doesn't exist yet.
--
-- The check must match payroll_calendar.KEY_RE (__tests__/test_payroll_calendar.py
-- reads both).

begin;

set local lock_timeout = '5s';

do $$
begin
  if to_regclass('public.payroll_deposits') is not null then
    alter table public.payroll_deposits drop constraint if exists payroll_deposits_key_shape;
    alter table public.payroll_deposits add constraint payroll_deposits_key_shape check (
      key ~ '^(federal:[0-9]{4}-[0-9]{2}(-[0-9]{2})?|federal:[0-9]{4}(Q[1-4])?|state:[0-9]{4}-[0-9]{2}|forms:941:[0-9]{4}Q[1-4]|forms:944:[0-9]{4}|forms:w2:[0-9]{4})$');
  end if;
end $$;

commit;

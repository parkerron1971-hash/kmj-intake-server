-- A group that gathers once a month (the first, second, third, fourth or
-- last of its weekday; the approved canvas "Church Groups, Together":
-- schedules beyond weekly). Idempotent.
--
--   groups.meet_every   1 every week, 2 every other week, 4 once a month
--   groups.meet_nth     which one in the month: 1-4, or 5 = the last
begin;

alter table public.groups drop constraint if exists groups_meet_every_check;
alter table public.groups add constraint groups_meet_every_check check (meet_every in (1, 2, 4));
alter table public.groups add column if not exists meet_nth smallint check (meet_nth is null or meet_nth between 1 and 5);

commit;

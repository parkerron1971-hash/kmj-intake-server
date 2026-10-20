-- A group that gathers every other week (the approved canvas "Church
-- Groups, Together": "every-other-week schedules"). Idempotent.
--
--   groups.meet_every   1 = every week (as before), 2 = every other week
--   groups.meet_from    a date the group gathers, the week the cycle counts
--                       from (needed for every other week; unused weekly)
begin;

alter table public.groups add column if not exists meet_every smallint not null default 1
  check (meet_every in (1, 2));
alter table public.groups add column if not exists meet_from date;

commit;

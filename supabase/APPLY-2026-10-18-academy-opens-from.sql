-- How lessons open, step 1 of the class schedule (approved "Class Schedule"
-- design, 2026-10-18).
--
-- "One lesson a week" used to count from the day each person joined, so
-- a class that meets on Thursdays had everyone on a different week. A
-- class can now run together: opens_from is when week 1 opens for
-- everyone, and each later lesson opens a week after the one before it
-- (or its own number of days after, on a custom schedule). Someone who
-- joins late finds the weeks already past open, to catch up.
--
-- opens_tz is the time zone the owner set it in, so "Thursdays at 6 PM"
-- stays 6 PM on the clock after daylight saving changes (days are added
-- to the local time, not to UTC). A name Postgres doesn't know is refused
-- when it is saved, so no classroom read can trip over it.
--
-- Left empty, nothing changes: lessons count from the day each person
-- joins, as before. "All at once" ignores it.
--
-- academy_lesson_unlock is the one rule every classroom read and write
-- already goes through (the classroom, slides, journal, work, finishing a
-- lesson); public_site._learn_unlock says the same in Python.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

alter table public.academy_courses add column if not exists opens_from timestamptz;
alter table public.academy_courses add column if not exists opens_tz text;
comment on column public.academy_courses.opens_from is
  'When week 1 opens for everyone in a class that runs together (one a week, or its own schedule). Empty: lessons count from the day each person joins.';
comment on column public.academy_courses.opens_tz is
  'The time zone opens_from was set in (IANA name); later weeks open at the same clock time. Empty: UTC days.';

create or replace function public.academy_course_tz_check()
returns trigger language plpgsql set search_path to 'public', 'pg_temp' as $$
begin
  if new.opens_tz is not null then
    if length(new.opens_tz) > 64 then raise exception 'Unknown time zone' using errcode = '22023'; end if;
    begin
      perform now() at time zone new.opens_tz;
    exception when others then
      raise exception 'Unknown time zone: %', new.opens_tz using errcode = '22023';
    end;
  end if;
  return new;
end $$;
drop trigger if exists academy_course_tz_check on public.academy_courses;
create trigger academy_course_tz_check before insert or update of opens_tz on public.academy_courses
  for each row execute function public.academy_course_tz_check();

create or replace function public.academy_lesson_unlock(p_course public.academy_courses, p_lesson public.academy_lessons, p_enrolled timestamptz)
returns timestamptz language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select case when p_course.drip_mode in ('weekly', 'custom') and p_course.opens_from is not null
    then ((p_course.opens_from at time zone coalesce(p_course.opens_tz, 'UTC')) + make_interval(days => d.n))
           at time zone coalesce(p_course.opens_tz, 'UTC')
    else p_enrolled + make_interval(days => d.n) end
  from (select case p_course.drip_mode
    when 'weekly' then (select count(*)::integer * 7 from public.academy_lessons l where l.course_id=p_course.id and (l.sort_order,l.id)<(p_lesson.sort_order,p_lesson.id))
    when 'custom' then greatest(0, p_lesson.drip_offset_days) else 0 end as n) d;
$$;

commit;

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
-- Left empty, nothing changes: lessons count from the day each person
-- joins, as before. "All at once" ignores it.
--
-- academy_lesson_unlock is the one rule every classroom read and write
-- already goes through (the classroom, slides, journal, work, finishing a
-- lesson); public_site._learn_unlock says the same in Python.
--
-- Rehearsed with a rollback probe; applied by hand like every APPLY file.

begin;

alter table public.academy_courses add column if not exists opens_from timestamptz;
comment on column public.academy_courses.opens_from is
  'When week 1 opens for everyone in a class that runs together (one a week, or its own schedule). Empty: lessons count from the day each person joins.';

create or replace function public.academy_lesson_unlock(p_course public.academy_courses, p_lesson public.academy_lessons, p_enrolled timestamptz)
returns timestamptz language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select (case when p_course.drip_mode in ('weekly', 'custom') and p_course.opens_from is not null
               then p_course.opens_from else p_enrolled end)
    + make_interval(days => case p_course.drip_mode
    when 'weekly' then (select count(*)::integer * 7 from public.academy_lessons l where l.course_id=p_course.id and (l.sort_order,l.id)<(p_lesson.sort_order,p_lesson.id))
    when 'custom' then greatest(0, p_lesson.drip_offset_days) else 0 end);
$$;

commit;

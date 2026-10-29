-- Classes in the church member app (2026-10-18), phase 5 of the approved
-- "Class Experience" design ("One deck, every room"): the member app's
-- Connect gains Classes beside Groups, where a signed-in member sees
--   * the next class night of a class they are in (or one live now),
--   * their classes, with how far they've come and their class link,
--   * the road of each program they're on (The Making's four tracks):
--     done, now, open to join, later,
--   * the church's classes they can join with one tap.
--
-- academy_member_classes reads all of it for one member in one call. The
-- member app signs people in with its own cookie (member_portal.py), not a
-- Supabase user, so the backend calls it as the service role with the
-- member's own contact id from that session; it is service-only, like
-- academy_public_join (which the one-tap join uses as it is).
--
-- Only published classes are shown; an archived or draft one never is. A
-- member who was taken off a class (dropped) never sees it offered again.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

create or replace function public.academy_member_classes(p_business uuid, p_contact uuid)
returns jsonb language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  with mine as (
    select e.course_id, e.status, e.portal_token, e.certificate_code, e.enrolled_at, coalesce(e.progress, '{}'::jsonb) as progress,
           c.title
      from public.academy_enrollments e
      join public.academy_courses c on c.id = e.course_id and c.business_id = e.business_id and c.status = 'published'
     where e.business_id = p_business and e.contact_id = p_contact and e.status in ('active', 'completed')
  ),
  track as (
    select pc.course_id, pc.program_id, pc.position, pc.teacher_name, p.title as program_title
      from public.academy_program_courses pc join public.academy_programs p on p.id = pc.program_id
     where p.business_id = p_business
  ),
  coming as (
    -- Each class's next meeting: one live now, else the next one scheduled.
    select distinct on (s.course_id) s.course_id, s.starts_at, s.duration_minutes, s.status, s.title,
           (select l.title from public.academy_lessons l where l.id = s.lesson_id) as lesson_title,
           s.teacher_name
      from public.academy_live_sessions s
      join public.academy_courses c on c.id = s.course_id and c.business_id = p_business and c.status = 'published'
     where s.status = 'live'
        or (s.status = 'scheduled' and s.starts_at > now() - make_interval(mins => s.duration_minutes))
     order by s.course_id, (s.status = 'live') desc, s.starts_at
  ),
  my_programs as (
    select distinct t.program_id from track t join mine m on m.course_id = t.course_id
  )
  select jsonb_build_object(
    'mine', coalesce((
      select jsonb_agg(jsonb_build_object(
          'course_id', m.course_id, 'title', m.title, 'status', m.status, 'token', m.portal_token,
          'certificate', m.certificate_code,
          'done', (select count(*) from public.academy_lessons l where l.course_id = m.course_id and m.progress ? l.id::text),
          'total', (select count(*) from public.academy_lessons l where l.course_id = m.course_id),
          'program', t.program_title, 'position', t.position, 'teacher', coalesce(n.teacher_name, t.teacher_name),
          'next', case when n.course_id is not null then jsonb_build_object(
              'starts_at', n.starts_at, 'minutes', n.duration_minutes, 'live', n.status = 'live',
              'title', n.title, 'lesson', n.lesson_title) end)
        order by (m.status = 'completed'), n.starts_at nulls last, t.position nulls last, m.enrolled_at desc)
        from mine m left join track t on t.course_id = m.course_id left join coming n on n.course_id = m.course_id), '[]'::jsonb),
    'programs', coalesce((
      select jsonb_agg(jsonb_build_object(
          'id', p.id, 'title', p.title, 'finish_title', p.finish_title, 'finish_at', p.finish_at,
          'tracks', (
            select coalesce(jsonb_agg(jsonb_build_object(
                'course_id', c.id, 'title', c.title, 'teacher', pc.teacher_name,
                'starts_at', (select min(s.starts_at) from public.academy_live_sessions s
                               where s.course_id = c.id and s.status <> 'cancelled'),
                'state', case when m.status = 'completed' then 'done' when m.course_id is not null then 'now'
                              when public.academy_course_open(c) and not exists (
                                     select 1 from public.academy_enrollments x where x.course_id = c.id and x.contact_id = p_contact)
                                then 'open'
                              else 'later' end,
                'token', m.portal_token)
              order by pc.position, c.created_at), '[]'::jsonb)
              from public.academy_program_courses pc
              join public.academy_courses c on c.id = pc.course_id and c.status <> 'archived'
              left join mine m on m.course_id = c.id
             where pc.program_id = p.id))
        order by p.created_at)
        from public.academy_programs p where p.id in (select program_id from my_programs)), '[]'::jsonb),
    'open', coalesce((
      select jsonb_agg(jsonb_build_object(
          'course_id', c.id, 'title', c.title, 'about', left(coalesce(c.description, ''), 240),
          'lessons', (select count(*) from public.academy_lessons l where l.course_id = c.id),
          'program', t.program_title, 'position', t.position, 'teacher', t.teacher_name,
          'starts_at', (select min(s.starts_at) from public.academy_live_sessions s
                         where s.course_id = c.id and s.status in ('scheduled', 'live') and s.starts_at > now() - interval '3 hours'),
          'opens_from', c.opens_from, 'drip', c.drip_mode)
        order by t.program_title nulls last, t.position nulls last, c.title)
        from public.academy_courses c left join track t on t.course_id = c.id
       where c.business_id = p_business and public.academy_course_open(c)
         and not exists (select 1 from public.academy_enrollments x where x.course_id = c.id and x.contact_id = p_contact)
         -- A track of a program they're on is offered on that program's road instead.
         and (t.program_id is null or t.program_id not in (select program_id from my_programs))), '[]'::jsonb)
  )
$$;
revoke all on function public.academy_member_classes(uuid, uuid) from public, anon, authenticated;
grant execute on function public.academy_member_classes(uuid, uuid) to service_role;

commit;

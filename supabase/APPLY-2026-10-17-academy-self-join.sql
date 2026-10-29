-- Free classes people join themselves (phase 4b of "One deck, every room").
--
-- A published class with no product to buy is open to anyone from its
-- public page, unless its owner closes it (self_join). The public join
-- runs on the server (academy_join.py, service role): it finds or makes
-- the person's contact, then takes ONE step here, academy_public_join,
-- which enrolls them or hands back the enrollment they already have.
--
-- A student can also join another track of their program from inside
-- their classroom (academy_join_track): their own class link is the
-- proof of who they are, so there is nothing to type.
--
-- Rehearsed with a rollback probe; applied by hand like every APPLY file.

begin;

alter table public.academy_courses add column if not exists self_join boolean not null default true;
comment on column public.academy_courses.self_join is
  'Anyone may join from the class page while the class is published and has no product to buy. Off: only people the owner adds.';

-- The one rule for "open to join", shared by every path below and by the
-- public page (public_site._academy_join_open says the same in Python).
-- A class with a product is joined by paying, even before its checkout
-- link exists.
create or replace function public.academy_course_open(c public.academy_courses)
returns boolean language sql immutable set search_path to 'public', 'pg_temp' as $$
  select c.status = 'published' and c.self_join and c.product_id is null
$$;

-- The public join's one step. state: joined (new), already (their own
-- link again), dropped (the owner took them off: no link, the owner is
-- told), closed (not open, or the contact is another business's).
create or replace function public.academy_public_join(p_course uuid, p_contact uuid)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare c public.academy_courses; e public.academy_enrollments; made boolean;
begin
  select * into c from public.academy_courses where id = p_course;
  if not found or not public.academy_course_open(c)
     or not exists (select 1 from public.contacts where id = p_contact and business_id = c.business_id) then
    return jsonb_build_object('state', 'closed');
  end if;
  insert into public.academy_enrollments (course_id, business_id, contact_id)
    values (c.id, c.business_id, p_contact)
    on conflict (course_id, contact_id) do nothing
    returning * into e;
  made := found;
  if not made then
    select * into e from public.academy_enrollments where course_id = c.id and contact_id = p_contact;
  end if;
  return jsonb_build_object(
    'state', case when made then 'joined' when e.status = 'dropped' then 'dropped' else 'already' end,
    'enrollment_id', e.id,
    'token', case when e.status <> 'dropped' then e.portal_token end);
end $$;
revoke all on function public.academy_public_join(uuid, uuid) from public, anon, authenticated;
grant execute on function public.academy_public_join(uuid, uuid) to service_role;

-- Join another track of my program, from my classroom.
create or replace function public.academy_join_track(p_token uuid, p_course uuid)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; c public.academy_courses; t public.academy_enrollments;
begin
  select * into e from public.academy_enrollments where portal_token = p_token and status in ('active', 'completed');
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id = p_course and business_id = e.business_id;
  if not found or not public.academy_course_open(c) or not exists (
      select 1 from public.academy_program_courses a
      join public.academy_program_courses b on b.program_id = a.program_id
      where a.course_id = e.course_id and b.course_id = c.id) then
    raise exception 'This class is not open to join';
  end if;
  insert into public.academy_enrollments (course_id, business_id, contact_id)
    values (c.id, c.business_id, e.contact_id)
    on conflict (course_id, contact_id) do nothing
    returning * into t;
  if not found then
    select * into t from public.academy_enrollments where course_id = c.id and contact_id = e.contact_id;
  end if;
  if t.status = 'dropped' then raise exception 'This class is not open to join'; end if;
  return jsonb_build_object('token', t.portal_token);
end $$;
revoke all on function public.academy_join_track(uuid, uuid) from public;
grant execute on function public.academy_join_track(uuid, uuid) to anon, authenticated;

-- The classroom's program strip: a track they are not in says whether they
-- can join it themselves.
create or replace function public.academy_classroom_program(p_course uuid, p_contact uuid)
returns jsonb language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select jsonb_build_object('id', p.id, 'title', p.title, 'finish_title', p.finish_title, 'finish_at', p.finish_at,
    'certificate', (select code from public.academy_program_certificates where program_id = p.id and contact_id = p_contact),
    'tracks', coalesce((select jsonb_agg(jsonb_build_object(
        'course_id', c2.id, 'title', c2.title, 'teacher_name', pc.teacher_name,
        'starts_at', (select min(s.starts_at) from public.academy_live_sessions s where s.course_id = c2.id and s.status <> 'cancelled'),
        'ends_at', (select max(s.starts_at) from public.academy_live_sessions s where s.course_id = c2.id and s.status <> 'cancelled'),
        'state', case when c2.id = p_course then 'here' when e2.status = 'completed' then 'done'
                      when e2.id is not null then 'enrolled' else 'not_enrolled' end,
        'token', case when e2.id is not null and c2.status = 'published' then e2.portal_token end,
        'joinable', e2.id is null and public.academy_course_open(c2)
          and not exists (select 1 from public.academy_enrollments x where x.course_id = c2.id and x.contact_id = p_contact))
        order by pc.position, c2.created_at)
      from public.academy_program_courses pc join public.academy_courses c2 on c2.id = pc.course_id
      left join public.academy_enrollments e2 on e2.course_id = c2.id and e2.contact_id = p_contact and e2.status in ('active', 'completed')
      where pc.program_id = p.id and c2.status <> 'archived'), '[]'::jsonb))
  from public.academy_program_courses pc0 join public.academy_programs p on p.id = pc0.program_id
  where pc0.course_id = p_course
$$;
revoke all on function public.academy_classroom_program(uuid, uuid) from public, anon, authenticated;

commit;

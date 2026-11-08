-- A private class (2026-11-08). Kevin, training one leader toward ordination:
-- "i will only be doing this with her so i believe private access".
--
-- "Only people you add" (academy_courses.self_join) closes the sign-up form
-- and nothing else: the class's title, description and lesson titles stay on
-- the church's public website, and every office login can read the class, its
-- lessons, its homework items and its enrollment rows, each of which holds the
-- student's class link and the teacher's notes.
--
-- academy_courses.private closes the rest. A private class:
--   * is never open to join (academy_course_open), so the member app and the
--     class page never offer it;
--   * is on no public page (public_site._serve_academy, in code);
--   * can be read only by the owner and the class's named teachers. An office
--     login's tenant_member_read and the schedule's read both stop at it.
--     The student keeps coming in by their class link, as always.
--
-- Default off: nothing changes for any class until its owner chooses this.
--
-- The check on lessons, enrollments and schedule items reads academy_courses,
-- so it goes through a SECURITY DEFINER helper (docs/RLS_MODEL.md, rule 2: a
-- cross-table check inlined in a policy is how 42P17 took production down).
-- Teachers keep their own policies (academy_can_teach) and owners theirs, so
-- only the seat policies below are replaced.
--
-- Idempotent. Applied by hand like every APPLY file.
--
-- Verify (expected: one row per policy, each mentioning private):
--   select tablename, policyname, qual from pg_policies
--    where schemaname = 'public'
--      and ((tablename in ('academy_courses', 'academy_lessons', 'academy_enrollments')
--            and policyname = 'tenant_member_read')
--           or policyname = 'academy_schedule_items_read');

begin;

alter table public.academy_courses add column if not exists private boolean not null default false;
comment on column public.academy_courses.private is
  'Only the owner, the class''s teachers and the people the owner adds. On no public page, offered to nobody, not counted in church attendance, read by no office login.';

create or replace function public.academy_course_private(p_course uuid)
returns boolean language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select coalesce((select c.private from public.academy_courses c where c.id = p_course), false)
$$;
revoke all on function public.academy_course_private(uuid) from public, anon;
grant execute on function public.academy_course_private(uuid) to authenticated, service_role;

-- The one rule for "open to join" (APPLY-2026-10-17-academy-self-join.sql).
create or replace function public.academy_course_open(c public.academy_courses)
returns boolean language sql immutable set search_path to 'public', 'pg_temp' as $$
  select c.status = 'published' and c.self_join and c.product_id is null and not c.private
$$;

-- The seat policies (APPLY-2026-07-31-seat-access-data-plane.sql), each now
-- stopping at a private class.
drop policy if exists tenant_member_read on public.academy_courses;
create policy tenant_member_read on public.academy_courses for select to authenticated
  using (public.is_business_member(business_id) and not private);

drop policy if exists tenant_member_read on public.academy_lessons;
create policy tenant_member_read on public.academy_lessons for select to authenticated
  using (public.is_business_member(business_id) and not public.academy_course_private(course_id));

-- Enrollments have no teacher policy of their own, so an office login who is a
-- named teacher of the private class keeps its roster here.
drop policy if exists tenant_member_read on public.academy_enrollments;
create policy tenant_member_read on public.academy_enrollments for select to authenticated
  using (public.is_business_member(business_id)
         and (not public.academy_course_private(course_id) or public.academy_can_teach(course_id)));

drop policy if exists academy_schedule_items_read on public.academy_schedule_items;
create policy academy_schedule_items_read on public.academy_schedule_items for select to authenticated
  using (public.academy_can_teach(course_id)
         or (public.is_business_member(business_id) and not public.academy_course_private(course_id)));

commit;

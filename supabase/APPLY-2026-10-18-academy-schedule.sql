-- The class schedule, step 2 of the approved "Class Schedule" design
-- (2026-10-18): what happens each week beyond the lesson itself.
--
-- academy_schedule_items: homework that goes past the slides (write an
-- answer, upload, do something this week, read or watch; a lesson's own quiz
-- stays in the lesson, where it already counts)
-- and gatherings (a serve day, a dinner). Each belongs to a week through
-- its lesson: it opens when that lesson opens for the student, and
-- homework is due due_days after (6 = the day before next week's class).
-- A gathering has its own time and place. Items the teacher hasn't
-- approved yet (status draft, e.g. Chief's) are never shown to students.
--
-- academy_item_work: one row per student per item: done, their answer or
-- one line, steps ticked (a chapter a day), the teacher's reply. Students
-- write only through academy_save_item_work, by their own class link.
--
-- Finishing a class: an item that counts toward finishing must be done
-- too (Kevin's pick: on for homework and projects, off for gatherings).
-- academy_enrollment_settle is the one rule; finishing a lesson and
-- finishing an item both call it.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

create table if not exists public.academy_schedule_items (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.academy_courses(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  lesson_id uuid references public.academy_lessons(id) on delete set null,
  kind text not null check (kind in ('homework', 'gathering')),
  how text not null default 'write' check (how in ('write', 'upload', 'do', 'read', 'rsvp')),
  title text not null check (length(btrim(title)) between 1 and 160),
  details text not null default '' check (length(details) <= 4000),
  done_with text not null default 'tick' check (done_with in ('tick', 'line', 'photo')),
  steps integer not null default 1 check (steps between 1 and 31),
  due_days integer not null default 6 check (due_days between 0 and 365),
  starts_at timestamptz,
  place text not null default '' check (length(place) <= 200),
  counts boolean not null default true,
  shared boolean not null default false,
  status text not null default 'published' check (status in ('draft', 'published')),
  position integer not null default 0,
  created_by uuid default auth.uid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint academy_schedule_items_gathering_time check (kind <> 'gathering' or starts_at is not null)
);
create index if not exists academy_schedule_items_course on public.academy_schedule_items (course_id, position);
alter table public.academy_schedule_items enable row level security;
revoke all on table public.academy_schedule_items from anon;

drop policy if exists academy_schedule_items_read on public.academy_schedule_items;
create policy academy_schedule_items_read on public.academy_schedule_items for select to authenticated
  using (public.academy_can_teach(course_id) or public.is_business_member(business_id));
drop policy if exists academy_schedule_items_write on public.academy_schedule_items;
create policy academy_schedule_items_write on public.academy_schedule_items for all to authenticated
  using (public.academy_can_teach(course_id, true))
  with check (public.academy_can_teach(course_id, true)
    and exists (select 1 from public.academy_courses c where c.id = course_id and c.business_id = academy_schedule_items.business_id)
    and (lesson_id is null or exists (select 1 from public.academy_lessons l where l.id = lesson_id and l.course_id = academy_schedule_items.course_id)));

create table if not exists public.academy_item_work (
  enrollment_id uuid not null references public.academy_enrollments(id) on delete cascade,
  item_id uuid not null references public.academy_schedule_items(id) on delete cascade,
  course_id uuid not null references public.academy_courses(id) on delete cascade,
  done boolean not null default false,
  answer text not null default '' check (length(answer) <= 8000),
  steps_done integer not null default 0 check (steps_done between 0 and 31),
  file_path text,
  feedback text not null default '' check (length(feedback) <= 4000),
  feedback_at timestamptz,
  done_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (enrollment_id, item_id)
);
create index if not exists academy_item_work_item on public.academy_item_work (item_id);
alter table public.academy_item_work enable row level security;
revoke all on table public.academy_item_work from anon;
drop policy if exists academy_item_work_teacher_read on public.academy_item_work;
create policy academy_item_work_teacher_read on public.academy_item_work for select to authenticated
  using (public.academy_can_teach(course_id));

-- When an item opens and is due for one student: its lesson's opening
-- (academy_lesson_unlock, the class's own rule), then due_days later on the
-- class's clock. An item without a lesson is open from the start.
create or replace function public.academy_item_due(p_course public.academy_courses, p_opens timestamptz, p_days integer)
returns timestamptz language sql stable set search_path to 'public', 'pg_temp' as $$
  select case when p_opens is null then null
    else ((p_opens at time zone coalesce(p_course.opens_tz, 'UTC')) + make_interval(days => p_days))
           at time zone coalesce(p_course.opens_tz, 'UTC') end
$$;

-- Every item that counts toward finishing is done (published ones only).
create or replace function public.academy_items_done(p_enrollment uuid)
returns boolean language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select not exists (
    select 1 from public.academy_enrollments e
      join public.academy_schedule_items i on i.course_id = e.course_id
     where e.id = p_enrollment and i.status = 'published' and i.counts and i.kind = 'homework'
       and not exists (select 1 from public.academy_item_work w where w.enrollment_id = e.id and w.item_id = i.id and w.done))
$$;
revoke all on function public.academy_items_done(uuid) from public, anon, authenticated;

-- The one rule for "finished": every lesson done, every activity in,
-- every counted item done. Sets the enrollment and says whether it is.
-- Only finishing a lesson may reopen a finished class (as it always
-- could); ticking an item never undoes a teacher's "finished".
create or replace function public.academy_enrollment_settle(p_enrollment uuid, p_may_reopen boolean default true)
returns boolean language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare g jsonb; finished boolean;
begin
  g := public.academy_grade_result(p_enrollment);
  finished := (g->>'total')::integer > 0 and g->>'completed' = g->>'total' and g->>'submitted' = g->>'assessments'
              and public.academy_items_done(p_enrollment);
  if finished then
    update public.academy_enrollments set status = 'completed', completed_at = coalesce(completed_at, now())
     where id = p_enrollment and status in ('active', 'completed');
  elsif p_may_reopen then
    update public.academy_enrollments set status = 'active', completed_at = null
     where id = p_enrollment and status in ('active', 'completed');
  end if;
  return finished;
end $$;
revoke all on function public.academy_enrollment_settle(uuid, boolean) from public, anon, authenticated;

-- Finishing a lesson: as before, with the one rule for finished.
create or replace function public.academy_complete_lesson(p_token uuid, p_lesson uuid)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; c public.academy_courses; l public.academy_lessons; r public.academy_lesson_responses; next_progress jsonb; finished boolean;
begin
  select * into e from public.academy_enrollments where portal_token=p_token and status in ('active','completed') for update;
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id=e.course_id and business_id=e.business_id and status='published';
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into l from public.academy_lessons where id=p_lesson and course_id=c.id and business_id=c.business_id;
  if not found then raise exception 'Lesson unavailable'; end if;
  if public.academy_lesson_unlock(c,l,e.enrolled_at)>now() then raise exception 'Lesson not yet available'; end if;
  if coalesce(btrim(l.homework),'')<>'' or jsonb_array_length(coalesce(l.learning_design->'workbook'->'prompts','[]'))>0 or jsonb_array_length(coalesce(l.learning_design->'questions','[]'))>0 then
    select * into r from public.academy_lesson_responses where enrollment_id=e.id and lesson_id=l.id;
    if not found or r.submitted_at is null or r.assessment_signature is distinct from
      public.academy_assessment_signature(l)
      then raise exception 'Submit all of the current lesson activities first'; end if;
  end if;
  next_progress := coalesce(e.progress,'{}') || jsonb_build_object(l.id::text,true);
  update public.academy_enrollments set progress=next_progress where id=e.id;
  finished := public.academy_enrollment_settle(e.id);
  return jsonb_build_object('completed',true,'course_complete',finished);
end $$;

-- The student's schedule: every published item of their class, when it
-- opens and is due for them, their own work, and (where the teacher chose
-- to share) classmates' answers by first name.
create or replace function public.academy_classroom_schedule(p_token uuid)
returns jsonb language plpgsql stable security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; c public.academy_courses;
begin
  select en.* into e from public.academy_enrollments en join public.academy_courses co on co.id = en.course_id and co.business_id = en.business_id
    where en.portal_token = p_token and en.status in ('active', 'completed') and co.status = 'published';
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id = e.course_id;
  return jsonb_build_object('items', coalesce((
    select jsonb_agg(x.item order by x.sort, x.position, x.created_at) from (
      select i.position, i.created_at, coalesce(l.sort_order, 2147483647) as sort,
        jsonb_build_object('id', i.id, 'kind', i.kind, 'how', i.how, 'title', i.title,
          'details', case when o.opens is null or o.opens <= now() then i.details else '' end,
          'done_with', i.done_with, 'steps', i.steps, 'counts', i.counts, 'shared', i.shared,
          'lesson_id', i.lesson_id, 'starts_at', i.starts_at, 'place', i.place,
          'opens_at', o.opens, 'locked', coalesce(o.opens > now(), false),
          'due_at', case when i.kind = 'homework' then public.academy_item_due(c, coalesce(o.opens, e.enrolled_at), i.due_days) end,
          'work', (select jsonb_build_object('done', w.done, 'answer', w.answer, 'steps_done', w.steps_done,
                     'feedback', w.feedback, 'feedback_at', w.feedback_at, 'done_at', w.done_at, 'has_file', w.file_path is not null)
                     from public.academy_item_work w where w.enrollment_id = e.id and w.item_id = i.id),
          'answers', case when i.shared then coalesce((
            select jsonb_agg(jsonb_build_object('name', split_part(btrim(ct.name), ' ', 1), 'answer', w2.answer) order by w2.done_at)
              from (select * from public.academy_item_work w3 where w3.item_id = i.id and w3.enrollment_id <> e.id
                      and w3.done and length(btrim(w3.answer)) > 0 order by w3.done_at limit 50) w2
              join public.academy_enrollments e2 on e2.id = w2.enrollment_id and e2.status in ('active', 'completed')
              join public.contacts ct on ct.id = e2.contact_id), '[]'::jsonb) end) as item
        from public.academy_schedule_items i
        left join public.academy_lessons l on l.id = i.lesson_id
        left join lateral (select case when l.id is null then null else public.academy_lesson_unlock(c, l, e.enrolled_at) end as opens) o on true
       where i.course_id = c.id and i.status = 'published') x), '[]'::jsonb),
    'items_done', public.academy_items_done(e.id));
end $$;
revoke all on function public.academy_classroom_schedule(uuid) from public;
grant execute on function public.academy_classroom_schedule(uuid) to anon, authenticated;

-- A student marks an item done, writes their line, ticks a day, or says
-- they're coming, by their own class link. Opens when its week opens.
create or replace function public.academy_save_item_work(p_token uuid, p_item uuid, p_done boolean,
  p_answer text default null, p_steps_done integer default null)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; c public.academy_courses; i public.academy_schedule_items; l public.academy_lessons;
  w public.academy_item_work; done boolean; steps integer; answer text; finished boolean;
begin
  select * into e from public.academy_enrollments where portal_token = p_token and status in ('active', 'completed') for update;
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id = e.course_id and business_id = e.business_id and status = 'published';
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into i from public.academy_schedule_items where id = p_item and course_id = c.id and status = 'published';
  if not found then raise exception 'That isn''t part of this class'; end if;
  if i.lesson_id is not null then
    select * into l from public.academy_lessons where id = i.lesson_id;
    if found and public.academy_lesson_unlock(c, l, e.enrolled_at) > now() then raise exception 'Not open yet'; end if;
  end if;
  select * into w from public.academy_item_work where enrollment_id = e.id and item_id = i.id;
  answer := left(btrim(coalesce(p_answer, w.answer, '')), 8000);
  steps := least(i.steps, greatest(0, coalesce(p_steps_done, w.steps_done, 0)));
  done := case when i.how = 'read' and i.steps > 1 then steps >= i.steps else coalesce(p_done, false) end;
  if done and i.how = 'write' and answer = '' then raise exception 'Write your answer first'; end if;
  if done and i.done_with = 'line' and i.how = 'do' and answer = '' then raise exception 'Write one line about how it went first'; end if;
  if done and (i.how = 'upload' or i.done_with = 'photo') and w.file_path is null then raise exception 'Add the file first'; end if;
  insert into public.academy_item_work (enrollment_id, item_id, course_id, done, answer, steps_done, done_at, updated_at)
    values (e.id, i.id, c.id, done, answer, steps, case when done then now() end, now())
  on conflict (enrollment_id, item_id) do update set done = excluded.done, answer = excluded.answer,
    steps_done = excluded.steps_done, updated_at = now(),
    done_at = case when excluded.done then coalesce(academy_item_work.done_at, now()) else null end
  returning * into w;
  finished := public.academy_enrollment_settle(e.id, false);
  return jsonb_build_object('done', w.done, 'answer', w.answer, 'steps_done', w.steps_done, 'done_at', w.done_at,
    'course_complete', finished);
end $$;
revoke all on function public.academy_save_item_work(uuid, uuid, boolean, text, integer) from public;
grant execute on function public.academy_save_item_work(uuid, uuid, boolean, text, integer) to anon, authenticated;

-- The teacher replies to one student's work.
create or replace function public.academy_item_feedback(p_enrollment uuid, p_item uuid, p_feedback text)
returns void language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare i public.academy_schedule_items;
begin
  select * into i from public.academy_schedule_items where id = p_item;
  if not found or not public.academy_can_teach(i.course_id) then raise exception 'Not authorized'; end if;
  update public.academy_item_work set feedback = left(btrim(coalesce(p_feedback, '')), 4000), feedback_at = now(), updated_at = now()
   where enrollment_id = p_enrollment and item_id = p_item;
  if not found then raise exception 'Nothing has been turned in yet'; end if;
end $$;
revoke all on function public.academy_item_feedback(uuid, uuid, text) from public, anon;
grant execute on function public.academy_item_feedback(uuid, uuid, text) to authenticated;

commit;

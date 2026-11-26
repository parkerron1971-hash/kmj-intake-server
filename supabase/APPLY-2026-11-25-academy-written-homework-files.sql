-- Written homework can take a file too (Kevin 2026-11-25: "add an upload
-- area for people to upload homework and i am able to recieve the homework").
--
-- Until now only "upload" homework (and "do it, add a photo") took a file.
-- After this, "write" homework does too: a photo of their pages, a PDF, a
-- voice note or a short video, beside or instead of the typed answer. The
-- files go where every homework file goes (the private academy-work bucket,
-- through academy_work.py), and the teacher reads them where they read the
-- work already. Nothing else changes: the same link, item, week and path
-- checks; classmates never see a file.
--
--   1. academy_item_file_target: a written homework is a target, and takes
--      any kind of file (not photo only). academy_item_attach calls it, so it
--      follows.
--   2. academy_save_item_work: a written homework with a file can be turned
--      in with no typed answer. Recreated from the latest definition
--      (APPLY-2026-10-18-academy-discussions.sql) with that one line changed.
-- Idempotent (create or replace); grants restated as they were.

create or replace function public.academy_item_file_target(p_token uuid, p_item uuid)
returns jsonb language plpgsql stable security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; c public.academy_courses; i public.academy_schedule_items; l public.academy_lessons;
  w public.academy_item_work;
begin
  select * into e from public.academy_enrollments where portal_token = p_token and status in ('active', 'completed');
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id = e.course_id and business_id = e.business_id and status = 'published';
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into i from public.academy_schedule_items where id = p_item and course_id = c.id and status = 'published' and kind = 'homework';
  if not found then raise exception 'That isn''t part of this class'; end if;
  if not (i.how in ('upload', 'write') or i.done_with = 'photo') then raise exception 'This one doesn''t take a file'; end if;
  if i.lesson_id is not null then
    select * into l from public.academy_lessons where id = i.lesson_id;
    if found and public.academy_lesson_unlock(c, l, e.enrolled_at) > now() then raise exception 'Not open yet'; end if;
  end if;
  select * into w from public.academy_item_work where enrollment_id = e.id and item_id = i.id;
  return jsonb_build_object('business_id', c.business_id, 'course_id', c.id, 'enrollment_id', e.id, 'item_id', i.id,
    'photo_only', i.how not in ('upload', 'write'), 'file_path', w.file_path);
end $$;
revoke all on function public.academy_item_file_target(uuid, uuid) from public, anon, authenticated;
grant execute on function public.academy_item_file_target(uuid, uuid) to service_role;

create or replace function public.academy_save_item_work(p_token uuid, p_item uuid, p_done boolean,
  p_answer text default null, p_steps_done integer default null)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; c public.academy_courses; i public.academy_schedule_items; l public.academy_lessons;
  w public.academy_item_work; done boolean; steps integer; answer text; finished boolean; opens timestamptz;
begin
  select * into e from public.academy_enrollments where portal_token = p_token and status in ('active', 'completed') for update;
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id = e.course_id and business_id = e.business_id and status = 'published';
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into i from public.academy_schedule_items where id = p_item and course_id = c.id and status = 'published' and kind <> 'project';
  if not found then raise exception 'That isn''t part of this class'; end if;
  if i.lesson_id is not null then
    select * into l from public.academy_lessons where id = i.lesson_id;
    if found then
      opens := public.academy_lesson_unlock(c, l, e.enrolled_at);
      if opens > now() then raise exception 'Not open yet'; end if;
    end if;
  end if;
  if i.kind = 'discussion' and public.academy_item_due(c, coalesce(opens, e.enrolled_at), i.due_days) < now() then
    raise exception 'This discussion has closed';
  end if;
  select * into w from public.academy_item_work where enrollment_id = e.id and item_id = i.id;
  answer := left(btrim(coalesce(p_answer, w.answer, '')), 8000);
  steps := least(i.steps, greatest(0, coalesce(p_steps_done, w.steps_done, 0)));
  done := case when i.how = 'read' and i.steps > 1 then steps >= i.steps else coalesce(p_done, false) end;
  if done and (i.how = 'write' or i.kind = 'discussion') and answer = ''
     and not (i.kind = 'homework' and i.how = 'write' and w.file_path is not null) then raise exception 'Write your answer first'; end if;
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

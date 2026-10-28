-- Uploads, the last part of the approved "Class Schedule" design (2026-10-18):
-- homework a student answers with a photo, a file, a voice note or a video
-- ("Upload"), and "tick it off and add a photo".
--
-- The files live in a PRIVATE bucket, academy-work, with no storage policies
-- at all: nobody reads or writes it but the backend's service role. The
-- backend takes the upload by the class link (POST /academy-work/<link>/<item>),
-- checks the bytes are what they claim (a photo is decoded and saved again
-- without its location), stores it under
--   <business>/<course>/<enrollment>-<item>-<random>.<ext>
-- and attaches it with academy_item_attach, which re-checks the link and the
-- item and refuses a path outside that student's own name. The teacher sees
-- a file through a short-lived signed link the backend mints after reading the
-- work row AS THE TEACHER (academy_item_work's teacher-read policy decides);
-- the student sees their own the same way, by their link. Classmates never
-- see a file, even on an item shared with the class.
--
-- academy_save_item_work already refuses "done" on such an item until a file
-- is attached (step 2), so nothing there changes.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

-- The bucket. 50 MB is a short phone video; the backend's own limits per kind
-- are lower (a photo 20 MB, a PDF 20 MB, a voice note 25 MB).
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('academy-work', 'academy-work', false, 52428800,
        array['image/jpeg', 'image/png', 'application/pdf', 'audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/wav',
              'audio/webm', 'video/mp4', 'video/quicktime', 'video/webm'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

alter table public.academy_item_work add column if not exists file_name text;
alter table public.academy_item_work add column if not exists file_type text;
alter table public.academy_item_work add column if not exists file_size bigint;
alter table public.academy_item_work add column if not exists file_at timestamptz;
alter table public.academy_item_work drop constraint if exists academy_item_work_file_meta;
alter table public.academy_item_work add constraint academy_item_work_file_meta check (
  (file_name is null or length(file_name) between 1 and 160)
  and (file_type is null or file_type in ('image/jpeg', 'image/png', 'application/pdf', 'audio/mpeg', 'audio/mp4', 'audio/ogg',
                                          'audio/wav', 'audio/webm', 'video/mp4', 'video/quicktime', 'video/webm'))
  and (file_size is null or file_size between 1 and 52428800)
  and (file_path is null or file_path ~ '^[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}-[0-9a-f-]{36}-[0-9a-f]{8}\.(jpg|png|pdf|mp3|m4a|ogg|wav|webm|mp4|mov)$'));

-- Where a student's file for one item may go, or why not: the class link is
-- active, the class published, the item is published homework that takes a
-- file, and its week is open. The backend asks before it stores a byte.
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
  if not (i.how = 'upload' or i.done_with = 'photo') then raise exception 'This one doesn''t take a file'; end if;
  if i.lesson_id is not null then
    select * into l from public.academy_lessons where id = i.lesson_id;
    if found and public.academy_lesson_unlock(c, l, e.enrolled_at) > now() then raise exception 'Not open yet'; end if;
  end if;
  select * into w from public.academy_item_work where enrollment_id = e.id and item_id = i.id;
  return jsonb_build_object('business_id', c.business_id, 'course_id', c.id, 'enrollment_id', e.id, 'item_id', i.id,
    'photo_only', i.how <> 'upload', 'file_path', w.file_path);
end $$;
revoke all on function public.academy_item_file_target(uuid, uuid) from public, anon, authenticated;
grant execute on function public.academy_item_file_target(uuid, uuid) to service_role;

-- Attach a stored file to the student's work (replacing any before it, whose
-- path comes back for the backend to delete). The path must be the one the
-- backend was told to use: this student, this item, this class.
create or replace function public.academy_item_attach(p_token uuid, p_item uuid, p_path text, p_name text,
  p_type text, p_size bigint)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare t jsonb; w public.academy_item_work; old text;
begin
  -- One student's uploads land one at a time, so a replaced file is always the one handed back.
  perform 1 from public.academy_enrollments where portal_token = p_token and status in ('active', 'completed') for update;
  t := public.academy_item_file_target(p_token, p_item);
  if p_path is null or left(p_path, 148) <> concat(t->>'business_id', '/', t->>'course_id', '/', t->>'enrollment_id', '-', t->>'item_id', '-') then
    raise exception 'That file isn''t filed under this student';
  end if;
  old := t->>'file_path';
  insert into public.academy_item_work (enrollment_id, item_id, course_id, file_path, file_name, file_type, file_size, file_at, updated_at)
    values ((t->>'enrollment_id')::uuid, p_item, (t->>'course_id')::uuid, p_path, left(btrim(coalesce(p_name, '')), 160), p_type, p_size, now(), now())
  on conflict (enrollment_id, item_id) do update set file_path = excluded.file_path, file_name = excluded.file_name,
    file_type = excluded.file_type, file_size = excluded.file_size, file_at = now(), updated_at = now()
  returning * into w;
  return jsonb_build_object('old_path', case when old is distinct from p_path then old end,
    'file_name', w.file_name, 'file_type', w.file_type, 'file_size', w.file_size, 'done', w.done);
end $$;
revoke all on function public.academy_item_attach(uuid, uuid, text, text, text, bigint) from public, anon, authenticated;
grant execute on function public.academy_item_attach(uuid, uuid, text, text, text, bigint) to service_role;

-- A student's own file for one item, by their link (for a signed link).
create or replace function public.academy_item_my_file(p_token uuid, p_item uuid)
returns jsonb language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select jsonb_build_object('file_path', w.file_path, 'file_name', w.file_name, 'file_type', w.file_type)
    from public.academy_enrollments e
    join public.academy_courses c on c.id = e.course_id and c.business_id = e.business_id and c.status = 'published'
    join public.academy_item_work w on w.enrollment_id = e.id and w.item_id = p_item and w.file_path is not null
   where e.portal_token = p_token and e.status in ('active', 'completed')
$$;
revoke all on function public.academy_item_my_file(uuid, uuid) from public, anon, authenticated;
grant execute on function public.academy_item_my_file(uuid, uuid) to service_role;

-- The student's schedule (step 3's), now with their file's name and type.
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
          'due_at', case when i.kind in ('homework', 'discussion') then public.academy_item_due(c, coalesce(o.opens, e.enrolled_at), i.due_days) end,
          'project_id', i.project_id,
          'project', case when i.project_id is not null then (select jsonb_build_object('title', p.title,
              'step', (select count(*) from public.academy_schedule_items s where s.project_id = p.id and s.status = 'published'
                         and (s.position, s.created_at) <= (i.position, i.created_at)),
              'steps', (select count(*) from public.academy_schedule_items s where s.project_id = p.id and s.status = 'published'))
            from public.academy_schedule_items p where p.id = i.project_id) end,
          'work', (select jsonb_build_object('done', w.done, 'answer', w.answer, 'steps_done', w.steps_done,
                     'feedback', w.feedback, 'feedback_at', w.feedback_at, 'done_at', w.done_at, 'has_file', w.file_path is not null, 'file_name', w.file_name, 'file_type', w.file_type,
                     'hidden', w.hidden, 'amens', (select count(*) from public.academy_item_amens a where a.work_id = w.id))
                     from public.academy_item_work w where w.enrollment_id = e.id and w.item_id = i.id),
          'answers', case when i.kind = 'discussion' and (o.opens is null or o.opens <= now())
                            then public.academy_item_answers(i.id, e.id)
                          when i.shared and exists (select 1 from public.academy_item_work m where m.enrollment_id = e.id and m.item_id = i.id and m.done)
                            then public.academy_item_answers(i.id, e.id) end) as item
        from public.academy_schedule_items i
        left join public.academy_lessons l on l.id = i.lesson_id
        left join lateral (select case when l.id is null then null else public.academy_lesson_unlock(c, l, e.enrolled_at) end as opens) o on true
       where i.course_id = c.id and i.status = 'published' and i.kind <> 'project') x), '[]'::jsonb),
    'projects', coalesce((
      select jsonb_agg(jsonb_build_object('id', p.id, 'title', p.title, 'details', p.details,
        'steps', (select count(*) from public.academy_schedule_items s where s.project_id = p.id and s.status = 'published'),
        'done', (select count(*) from public.academy_schedule_items s join public.academy_item_work w on w.item_id = s.id and w.enrollment_id = e.id and w.done
                  where s.project_id = p.id and s.status = 'published')) order by p.position, p.created_at)
        from public.academy_schedule_items p where p.course_id = c.id and p.kind = 'project' and p.status = 'published'), '[]'::jsonb),
    'items_done', public.academy_items_done(e.id));
end $$;
revoke all on function public.academy_classroom_schedule(uuid) from public;
grant execute on function public.academy_classroom_schedule(uuid) to anon, authenticated;

commit;

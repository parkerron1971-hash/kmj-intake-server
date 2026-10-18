-- Discussions and projects, step 3 of the approved "Class Schedule" design
-- (2026-10-18), on top of step 2's schedule (APPLY-2026-10-18-academy-schedule.sql).
--
-- A discussion is one question the class answers together through the
-- week: every answer is seen by the whole class (Kevin's pick), by first
-- name; classmates say Amen; the teacher hides any answer and stars the
-- ones to bring back on class night. It closes due_days after its week
-- opens. It doesn't count toward finishing unless the teacher says so.
--
-- A project is bigger work across weeks: the project row holds its title
-- and purpose, and each step is ordinary homework (write, do it this week,
-- read) with project_id set, in its own week with its own due date. The
-- steps count toward finishing; the project row itself is never "done".
--
-- On the TV: a starred answer goes up over the slides from the presenter
-- (academy_present_sessions.answer, said by academy_present_update and
-- read by academy_present_view), and comes down again. Names never go on
-- the screen.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

alter table public.academy_schedule_items drop constraint if exists academy_schedule_items_kind_check;
alter table public.academy_schedule_items add constraint academy_schedule_items_kind_check
  check (kind in ('homework', 'gathering', 'discussion', 'project'));
alter table public.academy_schedule_items add column if not exists project_id uuid
  references public.academy_schedule_items(id) on delete cascade;
create index if not exists academy_schedule_items_project on public.academy_schedule_items (project_id) where project_id is not null;

-- A project's step is homework in the same class; a project has no step of its own.
create or replace function public.academy_schedule_items_guard()
returns trigger language plpgsql set search_path to 'public', 'pg_temp' as $$
begin
  if new.project_id is not null then
    if new.kind <> 'homework' or new.project_id = new.id or not exists (
        select 1 from public.academy_schedule_items p where p.id = new.project_id and p.course_id = new.course_id and p.kind = 'project') then
      raise exception 'A project''s step is homework in the same class' using errcode = '23514';
    end if;
  end if;
  if new.kind in ('project', 'discussion') then
    new.how := 'write';
  end if;
  if new.kind = 'discussion' then
    new.shared := true;
  end if;
  return new;
end $$;
drop trigger if exists academy_schedule_items_guard on public.academy_schedule_items;
create trigger academy_schedule_items_guard before insert or update on public.academy_schedule_items
  for each row execute function public.academy_schedule_items_guard();

-- Each answer can be pointed at (Amen, a star, hiding it).
alter table public.academy_item_work add column if not exists id uuid not null default gen_random_uuid();
create unique index if not exists academy_item_work_id on public.academy_item_work (id);
alter table public.academy_item_work add column if not exists hidden boolean not null default false;
alter table public.academy_item_work add column if not exists starred boolean not null default false;

create table if not exists public.academy_item_amens (
  work_id uuid not null references public.academy_item_work(id) on delete cascade,
  enrollment_id uuid not null references public.academy_enrollments(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (work_id, enrollment_id)
);
alter table public.academy_item_amens enable row level security;
revoke all on table public.academy_item_amens from anon, authenticated;

-- Counted items: homework (a project's steps too) and discussions the teacher made count.
create or replace function public.academy_items_done(p_enrollment uuid)
returns boolean language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select not exists (
    select 1 from public.academy_enrollments e
      join public.academy_schedule_items i on i.course_id = e.course_id
     where e.id = p_enrollment and i.status = 'published' and i.counts and i.kind in ('homework', 'discussion')
       and not exists (select 1 from public.academy_item_work w where w.enrollment_id = e.id and w.item_id = i.id and w.done))
$$;
revoke all on function public.academy_items_done(uuid) from public, anon, authenticated;

-- Classmates' answers on one item, as a student sees them: never hidden ones,
-- never their own (that's their work), by first name, with Amens.
create or replace function public.academy_item_answers(p_item uuid, p_me uuid)
returns jsonb language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', w.id, 'name', split_part(btrim(ct.name), ' ', 1), 'answer', w.answer,
      'amens', (select count(*) from public.academy_item_amens a where a.work_id = w.id),
      'amened', exists (select 1 from public.academy_item_amens a where a.work_id = w.id and a.enrollment_id = p_me),
      'starred', w.starred) order by w.done_at), '[]'::jsonb)
    from (select * from public.academy_item_work w3 where w3.item_id = p_item and w3.enrollment_id <> p_me
            and w3.done and not w3.hidden and length(btrim(w3.answer)) > 0 order by w3.done_at limit 100) w
    join public.academy_enrollments e2 on e2.id = w.enrollment_id and e2.status in ('active', 'completed')
    join public.contacts ct on ct.id = e2.contact_id
$$;
revoke all on function public.academy_item_answers(uuid, uuid) from public, anon, authenticated;

-- The student's schedule (step 2's, with discussions, projects and Amens).
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
                     'feedback', w.feedback, 'feedback_at', w.feedback_at, 'done_at', w.done_at, 'has_file', w.file_path is not null,
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

-- Saving work (step 2's), with a discussion's answer and its closing.
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
  if done and (i.how = 'write' or i.kind = 'discussion') and answer = '' then raise exception 'Write your answer first'; end if;
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

-- Amen to a classmate's answer (or take it back), by the class link.
create or replace function public.academy_amen(p_token uuid, p_work uuid, p_on boolean default true)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; w public.academy_item_work; i public.academy_schedule_items;
begin
  select * into e from public.academy_enrollments where portal_token = p_token and status in ('active', 'completed');
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into w from public.academy_item_work where id = p_work;
  if not found or w.course_id <> e.course_id or w.enrollment_id = e.id or w.hidden or not w.done then
    raise exception 'That answer isn''t here';
  end if;
  select * into i from public.academy_schedule_items where id = w.item_id and status = 'published';
  if not found or not (i.kind = 'discussion' or i.shared) then raise exception 'That answer isn''t here'; end if;
  if p_on then
    insert into public.academy_item_amens (work_id, enrollment_id) values (w.id, e.id) on conflict do nothing;
  else
    delete from public.academy_item_amens where work_id = w.id and enrollment_id = e.id;
  end if;
  return jsonb_build_object('amens', (select count(*) from public.academy_item_amens where work_id = w.id),
    'amened', exists (select 1 from public.academy_item_amens where work_id = w.id and enrollment_id = e.id));
end $$;
revoke all on function public.academy_amen(uuid, uuid, boolean) from public;
grant execute on function public.academy_amen(uuid, uuid, boolean) to anon, authenticated;

-- The teacher hides an answer from the class, or stars it for class night.
create or replace function public.academy_item_moderate(p_work uuid, p_hidden boolean default null, p_starred boolean default null)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare w public.academy_item_work;
begin
  select * into w from public.academy_item_work where id = p_work;
  if not found or not public.academy_can_teach(w.course_id) then raise exception 'Not authorized'; end if;
  update public.academy_item_work set hidden = coalesce(p_hidden, hidden), starred = coalesce(p_starred, starred),
    updated_at = now() where id = p_work returning * into w;
  return jsonb_build_object('hidden', w.hidden, 'starred', w.starred);
end $$;
revoke all on function public.academy_item_moderate(uuid, boolean, boolean) from public, anon;
grant execute on function public.academy_item_moderate(uuid, boolean, boolean) to authenticated;

-- An answer on the TV, over the slides: {text, label}; '{}' takes it down.
alter table public.academy_present_sessions add column if not exists answer jsonb;
drop function if exists public.academy_present_update(uuid, integer, boolean, jsonb, boolean);
create or replace function public.academy_present_update(p_session uuid, p_index integer default null, p_blank boolean default null,
  p_slides jsonb default null, p_end boolean default false, p_answer jsonb default null)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare s academy_present_sessions; n integer;
begin
  select * into s from academy_present_sessions where id = p_session for update;
  if not found or not public.academy_can_teach(s.course_id) then
    raise exception 'Presenting is not available for this account';
  end if;
  if s.ended_at is not null then
    return jsonb_build_object('ended', true);
  end if;
  if p_end then
    update academy_present_sessions set ended_at = now(), state_version = state_version + 1 where id = p_session;
    return jsonb_build_object('ended', true);
  end if;
  if p_slides is not null then
    if not public.academy_valid_slides(p_slides) or jsonb_array_length(p_slides) = 0 then
      raise exception 'These slides could not be shown';
    end if;
    s.slides := public.academy_strip_notes(p_slides);
    s.slides_version := s.slides_version + 1;
  end if;
  if p_answer is not null then
    if p_answer = '{}'::jsonb then
      s.answer := null;
    elsif jsonb_typeof(p_answer) <> 'object' or length(btrim(coalesce(p_answer->>'text', ''))) not between 1 and 600
          or length(coalesce(p_answer->>'label', '')) > 80 then
      raise exception 'That answer could not be shown';
    else
      s.answer := jsonb_build_object('text', btrim(p_answer->>'text'), 'label', left(btrim(coalesce(p_answer->>'label', '')), 80));
    end if;
  end if;
  n := jsonb_array_length(s.slides);
  update academy_present_sessions
     set slides = s.slides,
         slides_version = s.slides_version,
         slide_index = greatest(0, least(n - 1, coalesce(p_index, s.slide_index))),
         blank = coalesce(p_blank, s.blank),
         answer = s.answer,
         state_version = s.state_version + 1,
         expires_at = greatest(expires_at, now() + interval '2 hours')
   where id = p_session
   returning * into s;
  return jsonb_build_object('ended', false, 'index', s.slide_index, 'blank', s.blank, 'answer', s.answer,
    'state_version', s.state_version, 'slides_version', s.slides_version);
end $$;
revoke all on function public.academy_present_update(uuid, integer, boolean, jsonb, boolean, jsonb) from public, anon;
grant execute on function public.academy_present_update(uuid, integer, boolean, jsonb, boolean, jsonb) to authenticated, service_role;

create or replace function public.academy_present_view(p_code text, p_slides_version integer default 0)
returns jsonb language plpgsql stable security definer set search_path to 'public', 'pg_temp' as $$
declare s academy_present_sessions; biz text; v_code text := upper(btrim(coalesce(p_code, '')));
begin
  if v_code !~ '^[A-HJ-NP-Z2-9]{6}$' then
    return jsonb_build_object('found', false);
  end if;
  select * into s from academy_present_sessions
   where code = v_code and ended_at is null and expires_at > now()
   order by started_at desc limit 1;
  if not found then
    -- A class that just ended reads as ended, not as a wrong code.
    if exists (select 1 from academy_present_sessions where code = v_code and started_at > now() - interval '12 hours') then
      return jsonb_build_object('found', true, 'ended', true);
    end if;
    return jsonb_build_object('found', false);
  end if;
  select name into biz from businesses where id = s.business_id;
  return jsonb_build_object(
    'found', true, 'ended', false,
    'index', s.slide_index, 'blank', s.blank, 'answer', s.answer,
    'state_version', s.state_version, 'slides_version', s.slides_version,
    'title', s.title, 'business', coalesce(biz, ''), 'theme', s.theme, 'count', jsonb_array_length(s.slides))
    || case when coalesce(p_slides_version, 0) <> s.slides_version
         then jsonb_build_object('slides', s.slides) else '{}'::jsonb end;
end $$;

commit;

-- Apply after APPLY-2026-10-17-academy-slides.sql.
-- The live class room (Kevin, 2026-10-17, "One deck, every room" boards 7-11):
--   * a live class can name its lesson (whose slides the teacher presents)
--     and who is teaching it ("Pastor Kevin is teaching");
--   * the room's chat, questions and answers to a question slide are kept
--     (academy_live_messages), written only by the backend after the same
--     access check as joining, with a per-person pace;
--   * the access check now tells the room when the class starts (the lobby
--     opens 15 minutes before), which lesson it is, the teacher's own name
--     instead of "Teacher", and the business's type (a church says Amen);
--   * academy_course_brand gives a teacher the colors and fonts the slides are
--     drawn in, even a teacher who is not a member of the business.
begin;

alter table public.academy_live_sessions
  add column if not exists lesson_id uuid references public.academy_lessons(id) on delete set null,
  add column if not exists teacher_name text
    check (teacher_name is null or length(btrim(teacher_name)) between 1 and 80);

-- ─── Kept chat, questions and answers ────────────────────────────────
create table if not exists public.academy_live_messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.academy_live_sessions(id) on delete cascade,
  identity text not null check (identity ~ '^(student|teacher)_[0-9a-f-]{36}$'),
  display_name text not null default 'Participant' check (length(display_name) between 1 and 160),
  teacher boolean not null default false,
  kind text not null check (kind in ('chat', 'question', 'answer')),
  body text not null check (length(btrim(body)) between 1 and 1000),
  slide_id text check (slide_id is null or slide_id ~ '^[A-Za-z0-9_-]{1,64}$'),
  -- shown: everyone sees it; held: waiting for the teacher (a student's link);
  -- hidden: the teacher took it down. Answers are only ever seen by teachers,
  -- and by everyone without a name once the teacher puts one on screen.
  status text not null default 'shown' check (status in ('shown', 'held', 'hidden')),
  pinned boolean not null default false,
  answered_at timestamptz,
  onscreen_at timestamptz,
  created_at timestamptz not null default now(),
  check (kind <> 'answer' or slide_id is not null)
);
create index if not exists academy_live_messages_session on public.academy_live_messages(session_id, created_at);
-- One answer per person per question slide: a new answer replaces the old.
create unique index if not exists academy_live_messages_one_answer
  on public.academy_live_messages(session_id, identity, slide_id) where kind = 'answer';
alter table public.academy_live_messages enable row level security;
revoke all on public.academy_live_messages from public, anon, authenticated;
grant select on public.academy_live_messages to authenticated;
grant all on public.academy_live_messages to service_role;
drop policy if exists academy_live_messages_teacher on public.academy_live_messages;
create policy academy_live_messages_teacher on public.academy_live_messages for select to authenticated
  using (exists (select 1 from public.academy_live_sessions s
                 where s.id = session_id and public.academy_can_teach(s.course_id)));

-- Service-only: the backend calls this after academy_live_access. One message
-- a second per person, 400 a class for a student; a new answer to the same
-- question slide replaces the old one (and comes off the screen).
create or replace function public.academy_live_post(
  p_session uuid, p_identity text, p_name text, p_teacher boolean,
  p_kind text, p_body text, p_slide text default null, p_held boolean default false)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare m public.academy_live_messages; recent integer; total integer;
begin
  perform pg_advisory_xact_lock(hashtext('academy_live_post:' || p_session::text || ':' || p_identity));
  select count(*) filter (where created_at > clock_timestamp() - interval '1 second'), count(*)
    into recent, total
    from public.academy_live_messages where session_id = p_session and identity = p_identity;
  if recent > 0 then
    raise exception 'Give it a second before sending again.' using errcode = 'P0001';
  end if;
  if total >= 400 and not p_teacher then
    raise exception 'You have sent as many messages as one class allows.' using errcode = 'P0001';
  end if;
  if p_kind = 'answer' then
    insert into public.academy_live_messages(session_id, identity, display_name, teacher, kind, body, slide_id, status, created_at)
      values (p_session, p_identity, left(coalesce(nullif(btrim(p_name), ''), 'Participant'), 160), p_teacher,
              'answer', btrim(p_body), p_slide, 'shown', clock_timestamp())
    on conflict (session_id, identity, slide_id) where kind = 'answer'
      do update set body = excluded.body, created_at = excluded.created_at, onscreen_at = null, status = 'shown'
    returning * into m;
  else
    insert into public.academy_live_messages(session_id, identity, display_name, teacher, kind, body, status, created_at)
      values (p_session, p_identity, left(coalesce(nullif(btrim(p_name), ''), 'Participant'), 160), p_teacher,
              p_kind, btrim(p_body), case when p_held then 'held' else 'shown' end, clock_timestamp())
    returning * into m;
  end if;
  return to_jsonb(m);
end;
$$;
revoke all on function public.academy_live_post(uuid, text, text, boolean, text, text, text, boolean) from public, anon, authenticated;
grant execute on function public.academy_live_post(uuid, text, text, boolean, text, text, text, boolean) to service_role;

-- ─── Scheduling names the lesson and who is teaching ─────────────────
drop function if exists public.academy_schedule_live(uuid, text, timestamptz, integer, text, integer);
create or replace function public.academy_schedule_live(p_course uuid, p_title text, p_starts_at timestamptz,
  p_duration integer default 60, p_mode text default 'broadcast', p_capacity integer default 30,
  p_lesson uuid default null, p_teacher text default null)
returns public.academy_live_sessions language plpgsql security definer set search_path = public, pg_temp as $$
declare s public.academy_live_sessions;
begin
  if not public.academy_can_teach(p_course) then raise exception 'Not authorized'; end if;
  if not exists (select 1 from public.academy_courses where id = p_course and status <> 'archived') then raise exception 'Course unavailable'; end if;
  if p_starts_at is null or p_starts_at < now() - interval '5 minutes' then raise exception 'Choose a current or future start time'; end if;
  if p_lesson is not null and not exists (select 1 from public.academy_lessons where id = p_lesson and course_id = p_course) then
    raise exception 'Choose a lesson from this class';
  end if;
  insert into public.academy_live_sessions(course_id, title, starts_at, duration_minutes, mode, max_participants, created_by, lesson_id, teacher_name)
    values (p_course, btrim(p_title), p_starts_at, p_duration, p_mode, p_capacity, auth.uid(), p_lesson,
            nullif(left(btrim(coalesce(p_teacher, '')), 80), ''))
    returning * into s;
  return s;
end;
$$;
revoke all on function public.academy_schedule_live(uuid, text, timestamptz, integer, text, integer, uuid, text) from public, anon;
grant execute on function public.academy_schedule_live(uuid, text, timestamptz, integer, text, integer, uuid, text) to authenticated;

-- ─── The access check carries what the room needs ────────────────────
create or replace function public.academy_live_access(p_session uuid, p_token uuid default null)
returns jsonb language plpgsql stable security definer set search_path = public, pg_temp as $$
declare s public.academy_live_sessions; c public.academy_courses; e public.academy_enrollments;
  ident text; display text; teacher boolean = false; btype text;
begin
  select * into s from public.academy_live_sessions where id = p_session;
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id = s.course_id;
  if p_token is null and auth.uid() is not null then teacher := public.academy_can_teach(c.id); end if;
  if teacher then
    ident := 'teacher_' || auth.uid()::text;
    -- The teacher who scheduled the class goes by the name it was given;
    -- anyone else on the teaching team by their own account name.
    select coalesce(case when s.created_by = auth.uid() then nullif(btrim(s.teacher_name), '') end,
                    nullif(btrim(coalesce(u.raw_user_meta_data->>'full_name', u.raw_user_meta_data->>'name', '')), ''))
      into display from auth.users u where u.id = auth.uid();
    display := left(coalesce(display, 'Teacher'), 160);
  else
    select * into e from public.academy_enrollments where portal_token = p_token and course_id = c.id
      and business_id = c.business_id and status in ('active', 'completed');
    if not found or c.status <> 'published' then raise exception 'Classroom unavailable'; end if;
    ident := 'student_' || e.id::text;
    select coalesce(nullif(btrim(name), ''), 'Student') into display from public.contacts where id = e.contact_id and business_id = c.business_id;
  end if;
  if exists (select 1 from public.academy_live_members where session_id = s.id and identity = ident and blocked) then raise exception 'Access removed by teacher'; end if;
  select b.type into btype from public.businesses b where b.id = c.business_id;
  return jsonb_build_object('session_id', s.id, 'course_id', c.id, 'business_id', c.business_id, 'room_name', s.room_name,
    'identity', ident, 'name', coalesce(display, 'Student'), 'teacher', teacher, 'mode', s.mode, 'status', s.status,
    'max_participants', s.max_participants, 'title', s.title, 'duration_minutes', s.duration_minutes,
    'starts_at', s.starts_at, 'lesson_id', s.lesson_id, 'teacher_name', s.teacher_name, 'business_type', btype,
    'can_publish', teacher or coalesce((select can_publish from public.academy_live_members where session_id = s.id and identity = ident), s.mode = 'interactive'));
end;
$$;
revoke all on function public.academy_live_access(uuid, uuid) from public;
grant execute on function public.academy_live_access(uuid, uuid) to anon, authenticated;

create or replace function public.academy_student_live(p_token uuid)
returns jsonb language plpgsql stable security definer set search_path = public, pg_temp as $$
declare e public.academy_enrollments;
begin
  select en.* into e from public.academy_enrollments en join public.academy_courses c on c.id = en.course_id and c.business_id = en.business_id
    where en.portal_token = p_token and en.status in ('active', 'completed') and c.status = 'published';
  if not found then raise exception 'Classroom unavailable'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('id', s.id, 'course_id', s.course_id, 'title', s.title, 'starts_at', s.starts_at,
    'duration_minutes', s.duration_minutes, 'mode', s.mode, 'status', s.status, 'max_participants', s.max_participants,
    'started_at', s.started_at, 'ended_at', s.ended_at, 'lesson_id', s.lesson_id, 'teacher_name', s.teacher_name) order by s.starts_at desc)
    from public.academy_live_sessions s where s.course_id = e.course_id and s.status <> 'cancelled'), '[]'::jsonb);
end;
$$;
revoke all on function public.academy_student_live(uuid) from public;
grant execute on function public.academy_student_live(uuid) to anon, authenticated;

-- ─── The colors the slides are drawn in, for any teacher ─────────────
create or replace function public.academy_course_brand(p_course uuid)
returns jsonb language plpgsql stable security definer set search_path = public, pg_temp as $$
declare result jsonb;
begin
  if not public.academy_can_teach(p_course) then raise exception 'Not authorized'; end if;
  select jsonb_build_object('name', b.name, 'business_type', b.type, 'kit', jsonb_strip_nulls(jsonb_build_object(
      'colors', k.kit->'colors', 'primary_color', k.kit->'primary_color',
      'font_heading', k.kit->'font_heading', 'font_body', k.kit->'font_body', 'font_pair', k.kit->'font_pair',
      'logo_url', k.kit->'logo_url')))
    into result
    from public.academy_courses c join public.businesses b on b.id = c.business_id
    cross join lateral (select case when jsonb_typeof(b.settings->'brand_kit') = 'object' then b.settings->'brand_kit' else '{}'::jsonb end as kit) k
    where c.id = p_course;
  return result;
end;
$$;
revoke all on function public.academy_course_brand(uuid) from public, anon;
grant execute on function public.academy_course_brand(uuid) to authenticated;

commit;

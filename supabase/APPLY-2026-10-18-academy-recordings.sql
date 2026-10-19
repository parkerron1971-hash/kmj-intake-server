-- Class recordings (2026-10-18). Kevin, 2026-10-17, settled: recording on
-- from the start ("allows for people that need to go back to have that
-- ability"). academy_recordings.py records a live class through the app's
-- /class-recorder page into the business's private bucket, once its
-- storage is connected; nothing is recorded until then.
--
--   academy_courses.record_live        the owner's switch in Course setup;
--                                      on unless they turn it off.
--   academy_live_sessions.recording_egress_id / recording_path /
--   recording_status ('recording', 'ready', 'failed') /
--   recording_started_at / recording_ended_at / recording_seconds /
--   recording_bytes                    the night's one recording. Written
--                                      by the backend; the teaching team
--                                      reads them like the rest of the night.
--   academy_student_live               also says whether the night has a
--                                      recording ready ('recording'); the
--                                      link to it is signed by the backend
--                                      for that student's own class link.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

alter table public.academy_courses add column if not exists record_live boolean not null default true;

alter table public.academy_live_sessions add column if not exists recording_egress_id text;
alter table public.academy_live_sessions add column if not exists recording_path text;
alter table public.academy_live_sessions add column if not exists recording_status text;
alter table public.academy_live_sessions add column if not exists recording_started_at timestamptz;
alter table public.academy_live_sessions add column if not exists recording_ended_at timestamptz;
alter table public.academy_live_sessions add column if not exists recording_seconds integer;
alter table public.academy_live_sessions add column if not exists recording_bytes bigint;
alter table public.academy_live_sessions drop constraint if exists academy_live_sessions_recording_status;
alter table public.academy_live_sessions add constraint academy_live_sessions_recording_status
  check (recording_status is null or recording_status in ('recording', 'ready', 'failed'));
create unique index if not exists academy_live_sessions_recording_egress
  on public.academy_live_sessions(recording_egress_id) where recording_egress_id is not null;

-- ─── Live classes, with how long this student was there ──────────────
-- (APPLY-2026-10-18-academy-class-nights.sql, plus 'recording')
create or replace function public.academy_student_live(p_token uuid)
 returns jsonb language plpgsql stable security definer set search_path to 'public', 'pg_temp' as $function$
declare e public.academy_enrollments;
begin
  select en.* into e from public.academy_enrollments en join public.academy_courses c on c.id = en.course_id and c.business_id = en.business_id
    where en.portal_token = p_token and en.status in ('active', 'completed') and c.status = 'published';
  if not found then raise exception 'Classroom unavailable'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('id', s.id, 'course_id', s.course_id, 'title', s.title, 'starts_at', s.starts_at,
    'duration_minutes', s.duration_minutes, 'mode', s.mode, 'status', s.status, 'max_participants', s.max_participants,
    'started_at', s.started_at, 'ended_at', s.ended_at, 'lesson_id', s.lesson_id, 'teacher_name', s.teacher_name,
    'attended_minutes', (select round(sum(extract(epoch from (coalesce(a.left_at, s.ended_at, now()) - a.joined_at))) / 60)::integer
       from public.academy_live_attendance a where a.session_id = s.id and a.identity = 'student_' || e.id and a.joined_at is not null),
    'room', exists (select 1 from public.academy_live_here h where h.session_id = s.id and h.enrollment_id = e.id),
    'counted', s.entry_id is not null and exists (select 1 from public.attendance att
                                                   where att.entry_id = s.entry_id and att.contact_id = e.contact_id),
    'recording', s.status = 'ended' and s.recording_status = 'ready'
    ) order by s.starts_at desc)
    from public.academy_live_sessions s where s.course_id = e.course_id and s.status <> 'cancelled'), '[]'::jsonb);
end;
$function$;
revoke all on function public.academy_student_live(uuid) from public;
grant execute on function public.academy_student_live(uuid) to anon, authenticated;

commit;

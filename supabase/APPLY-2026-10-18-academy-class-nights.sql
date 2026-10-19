-- Class nights after they end (2026-10-18). Kevin, asked whether online
-- class nights count toward a church's attendance (the approved class
-- design's recap: "counted toward church attendance"): "Count class
-- nights".
--
-- When a live class ends, academy_class_nights.sweep_tick (every ten
-- minutes) makes the night its own occasion in the church's Services &
-- Events (private: never on the public events page or a member's own)
-- and checks in everyone who came: online (they were in the live room) or
-- in the room (they tapped "I'm in the room", or the teacher marked
-- them). A class never makes anyone a first-time visitor, and a class
-- night is never a Sunday to the drifting rule (church_shepherd_signals).
-- For any kind of business, a teacher who asked ("Send tonight's slides to
-- who wasn't here") has each active student who didn't come emailed the
-- way into their class.
--
--   academy_live_sessions.entry_id     the night's occasion, once counted
--   academy_live_sessions.counted_at   set once, when it was counted
--   academy_live_sessions.send_missed  the teacher's ask
--   academy_live_sessions.missed_sent_at
--                                      set once, when those emails were
--                                      claimed
--   academy_live_here                  who was in the room: marked by the
--                                      student ('self') or the teacher;
--                                      the teaching team reads it, the
--                                      backend writes it
--   module_entries_class_session       one occasion per class night
--   academy_live_count_night(session, entry)
--                                      marks the night counted and, at a
--                                      church, checks in who came, in one
--                                      statement; null when it was already
--                                      counted or hasn't ended. Service
--                                      role only.
--   academy_live_missed_claim(session) marks the night's emails sent and
--                                      hands back who missed it (active
--                                      students who were in the class
--                                      before it ended); null when already
--                                      claimed or not asked for. Service
--                                      role only.
--   academy_live_missed_release(session)
--                                      un-marks them when every email
--                                      failed (a send outage). Service role
--                                      only.
--   academy_student_live               also says whether this student was
--                                      in the room and whether the night
--                                      was counted for them.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

alter table public.academy_live_sessions add column if not exists entry_id uuid references public.module_entries(id) on delete set null;
alter table public.academy_live_sessions add column if not exists counted_at timestamptz;
alter table public.academy_live_sessions add column if not exists send_missed boolean not null default false;
alter table public.academy_live_sessions add column if not exists missed_sent_at timestamptz;

create table if not exists public.academy_live_here (
  session_id uuid not null references public.academy_live_sessions(id) on delete cascade,
  enrollment_id uuid not null references public.academy_enrollments(id) on delete cascade,
  marked_by text not null check (marked_by in ('self', 'teacher')),
  marked_at timestamptz not null default now(),
  primary key (session_id, enrollment_id)
);
alter table public.academy_live_here enable row level security;
revoke all on public.academy_live_here from public, anon, authenticated;
grant select on public.academy_live_here to authenticated;
grant all on public.academy_live_here to service_role;
drop policy if exists academy_live_here_teacher on public.academy_live_here;
create policy academy_live_here_teacher on public.academy_live_here for select to authenticated
  using (exists (select 1 from public.academy_live_sessions s
                  where s.id = academy_live_here.session_id and public.academy_can_teach(s.course_id)));

-- A mark is only ever for a student of that class.
create or replace function public.academy_live_here_guard()
returns trigger language plpgsql set search_path to 'public', 'pg_temp' as $$
begin
  if not exists (select 1 from public.academy_live_sessions s join public.academy_enrollments e on e.course_id = s.course_id
                  where s.id = new.session_id and e.id = new.enrollment_id) then
    raise exception 'That student is not in this class' using errcode = '23514';
  end if;
  return new;
end $$;
drop trigger if exists academy_live_here_guard on public.academy_live_here;
create trigger academy_live_here_guard before insert or update on public.academy_live_here
  for each row execute function public.academy_live_here_guard();

create unique index if not exists module_entries_class_session
  on public.module_entries(business_id, (data->>'_class_session')) where (data ? '_class_session');

create or replace function public.academy_live_count_night(p_session uuid, p_entry uuid)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare s public.academy_live_sessions; biz uuid; n integer := 0;
begin
  select c.business_id into biz from public.academy_live_sessions ls join public.academy_courses c on c.id = ls.course_id
   where ls.id = p_session;
  if p_entry is not null and not exists (select 1 from public.module_entries m where m.id = p_entry and m.business_id = biz
                                            and m.data->>'_class_session' = p_session::text) then
    raise exception 'That occasion is not this class night' using errcode = '23514';
  end if;
  update public.academy_live_sessions set counted_at = now(), entry_id = p_entry
   where id = p_session and status = 'ended' and counted_at is null
  returning * into s;
  if not found then
    return null;
  end if;
  if p_entry is not null then
    insert into public.attendance (business_id, entry_id, contact_id, name, method, first_time, checked_in_at)
    select biz, p_entry, e.contact_id, left(coalesce(nullif(btrim(ct.name), ''), 'A member'), 160),
           case h.marked_by when 'teacher' then 'staff' when 'self' then 'self' else 'online' end,
           false, coalesce(s.started_at, s.starts_at)
      from public.academy_enrollments e
      join public.contacts ct on ct.id = e.contact_id and ct.business_id = e.business_id
      left join public.academy_live_here h on h.session_id = s.id and h.enrollment_id = e.id
     where e.course_id = s.course_id and e.business_id = biz and e.status in ('active', 'completed')
       and (h.enrollment_id is not null
            or exists (select 1 from public.academy_live_attendance a
                        where a.session_id = s.id and a.identity = 'student_' || e.id::text and a.joined_at is not null))
    on conflict (entry_id, contact_id) where contact_id is not null do nothing;
    get diagnostics n = row_count;
  end if;
  return jsonb_build_object('session_id', s.id, 'counted', n);
end $$;
revoke all on function public.academy_live_count_night(uuid, uuid) from public, anon, authenticated;
grant execute on function public.academy_live_count_night(uuid, uuid) to service_role;

create or replace function public.academy_live_missed_claim(p_session uuid)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare s public.academy_live_sessions;
begin
  update public.academy_live_sessions set missed_sent_at = now()
   where id = p_session and status = 'ended' and send_missed and missed_sent_at is null
  returning * into s;
  if not found then
    return null;
  end if;
  return jsonb_build_object(
    'session_id', s.id, 'course_id', s.course_id,
    'students', coalesce((
      select jsonb_agg(jsonb_build_object('enrollment_id', e.id, 'contact_id', e.contact_id, 'token', e.portal_token,
                                          'name', ct.name, 'email', ct.email) order by e.enrolled_at)
        from public.academy_enrollments e join public.contacts ct on ct.id = e.contact_id and ct.business_id = e.business_id
       where e.course_id = s.course_id and e.status = 'active' and e.enrolled_at <= coalesce(s.ended_at, now())
         and not exists (select 1 from public.academy_live_here h where h.session_id = s.id and h.enrollment_id = e.id)
         and not exists (select 1 from public.academy_live_attendance a
                          where a.session_id = s.id and a.identity = 'student_' || e.id::text and a.joined_at is not null)),
      '[]'::jsonb));
end $$;
revoke all on function public.academy_live_missed_claim(uuid) from public, anon, authenticated;
grant execute on function public.academy_live_missed_claim(uuid) to service_role;

create or replace function public.academy_live_missed_release(p_session uuid)
returns void language sql security definer set search_path to 'public', 'pg_temp' as $$
  update public.academy_live_sessions set missed_sent_at = null where id = p_session and send_missed
$$;
revoke all on function public.academy_live_missed_release(uuid) from public, anon, authenticated;
grant execute on function public.academy_live_missed_release(uuid) to service_role;

-- ─── Live classes, with how long this student was there ──────────────
-- (APPLY-2026-10-17-academy-student-side.sql, plus 'room' and 'counted')
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
                                                   where att.entry_id = s.entry_id and att.contact_id = e.contact_id)
    ) order by s.starts_at desc)
    from public.academy_live_sessions s where s.course_id = e.course_id and s.status <> 'cancelled'), '[]'::jsonb);
end;
$function$;
revoke all on function public.academy_student_live(uuid) from public;
grant execute on function public.academy_student_live(uuid) to anon, authenticated;

commit;

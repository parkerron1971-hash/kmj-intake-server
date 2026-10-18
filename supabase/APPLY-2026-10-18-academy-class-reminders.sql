-- Class-night reminders (2026-10-18), phase 5 of the approved "Class
-- Experience" design. Kevin's 10/17 pick: reminders, and member
-- notifications, yes.
--
-- A few hours before each live class (the evening before for a morning
-- one), academy_reminders.sweep_tick emails every active student the way
-- into their classroom, and a church's member app sends its "Class nights"
-- notification when the church has that kind on (member_push).
--
--   academy_courses.remind_live   the owner's switch in Course setup; on
--                                 unless they turn it off.
--   academy_live_sessions.reminded_at
--                                 set once, when a night's reminder is
--                                 claimed: each night is reminded once.
--   academy_live_reminder_claim(session)
--                                 claims an unreminded, scheduled night of a
--                                 published class whose reminders are on, and
--                                 hands back who to tell (active students,
--                                 their name, email and class link); null
--                                 when someone else claimed it first or it
--                                 no longer qualifies. Service role only.
--   academy_live_reminder_release(session)
--                                 un-marks a night whose emails all failed
--                                 (a send outage), so the next sweep tries
--                                 again; the emails' idempotency keys keep a
--                                 retry from reaching anyone twice. Service
--                                 role only.
--   academy_live_sessions_remind_again
--                                 a night moved to another time is reminded
--                                 again, at its new time.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

alter table public.academy_courses add column if not exists remind_live boolean not null default true;
alter table public.academy_live_sessions add column if not exists reminded_at timestamptz;

create or replace function public.academy_live_reminder_claim(p_session uuid)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare s public.academy_live_sessions;
begin
  update public.academy_live_sessions ls set reminded_at = now()
    from public.academy_courses c
   where ls.id = p_session and ls.reminded_at is null and ls.status = 'scheduled'
     and c.id = ls.course_id and c.status = 'published' and c.remind_live
  returning ls.* into s;
  if not found then
    return null;
  end if;
  return jsonb_build_object(
    'session_id', s.id, 'course_id', s.course_id,
    'students', coalesce((
      select jsonb_agg(jsonb_build_object('enrollment_id', e.id, 'contact_id', e.contact_id, 'token', e.portal_token,
                                          'name', ct.name, 'email', ct.email) order by e.enrolled_at)
        from public.academy_enrollments e join public.contacts ct on ct.id = e.contact_id and ct.business_id = e.business_id
       where e.course_id = s.course_id and e.status = 'active'), '[]'::jsonb));
end $$;
revoke all on function public.academy_live_reminder_claim(uuid) from public, anon, authenticated;
grant execute on function public.academy_live_reminder_claim(uuid) to service_role;

create or replace function public.academy_live_reminder_release(p_session uuid)
returns void language sql security definer set search_path to 'public', 'pg_temp' as $$
  update public.academy_live_sessions set reminded_at = null where id = p_session and status = 'scheduled'
$$;
revoke all on function public.academy_live_reminder_release(uuid) from public, anon, authenticated;
grant execute on function public.academy_live_reminder_release(uuid) to service_role;

create or replace function public.academy_live_sessions_remind_again()
returns trigger language plpgsql set search_path to 'public', 'pg_temp' as $$
begin
  if new.starts_at is distinct from old.starts_at then
    new.reminded_at := null;
  end if;
  return new;
end $$;
drop trigger if exists academy_live_sessions_remind_again on public.academy_live_sessions;
create trigger academy_live_sessions_remind_again before update of starts_at on public.academy_live_sessions
  for each row execute function public.academy_live_sessions_remind_again();

commit;

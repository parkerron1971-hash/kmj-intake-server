-- Apply after APPLY-2026-09-08-academy-school.sql.
-- One provider project; course ownership and enrollment stay in Solutionist.
begin;

create table if not exists public.academy_live_sessions (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.academy_courses(id) on delete cascade,
  title text not null check (length(btrim(title)) between 1 and 160),
  starts_at timestamptz not null,
  duration_minutes integer not null default 60 check (duration_minutes between 5 and 180),
  mode text not null default 'broadcast' check (mode in ('broadcast','interactive')),
  max_participants integer not null default 30 check (max_participants between 2 and 100),
  status text not null default 'scheduled' check (status in ('scheduled','live','ended','cancelled')),
  room_name text not null unique default ('class_' || gen_random_uuid()::text),
  started_at timestamptz,
  ended_at timestamptz,
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now()
);
create index if not exists academy_live_course_time on public.academy_live_sessions(course_id,starts_at);
alter table public.academy_live_sessions enable row level security;
revoke all on public.academy_live_sessions from public,anon,authenticated;
grant select on public.academy_live_sessions to authenticated;
grant all on public.academy_live_sessions to service_role;
drop policy if exists academy_live_teacher_read on public.academy_live_sessions;
create policy academy_live_teacher_read on public.academy_live_sessions for select to authenticated
  using (public.academy_can_teach(course_id));

create table if not exists public.academy_live_members (
  session_id uuid not null references public.academy_live_sessions(id) on delete cascade,
  identity text not null,
  can_publish boolean,
  blocked boolean not null default false,
  last_token_at timestamptz,
  primary key(session_id,identity)
);
alter table public.academy_live_members enable row level security;
revoke all on public.academy_live_members from public,anon,authenticated;
grant all on public.academy_live_members to service_role;

create table if not exists public.academy_live_attendance (
  participant_sid text primary key,
  session_id uuid not null references public.academy_live_sessions(id) on delete cascade,
  identity text not null,
  display_name text not null default 'Participant',
  joined_at timestamptz,
  left_at timestamptz
);
alter table public.academy_live_attendance enable row level security;
revoke all on public.academy_live_attendance from public,anon,authenticated;
grant select on public.academy_live_attendance to authenticated;
grant all on public.academy_live_attendance to service_role;
drop policy if exists academy_live_attendance_teacher on public.academy_live_attendance;
create policy academy_live_attendance_teacher on public.academy_live_attendance for select to authenticated
  using (exists(select 1 from public.academy_live_sessions s where s.id=session_id and public.academy_can_teach(s.course_id)));

create or replace function public.academy_schedule_live(p_course uuid,p_title text,p_starts_at timestamptz,
  p_duration integer default 60,p_mode text default 'broadcast',p_capacity integer default 30)
returns public.academy_live_sessions language plpgsql security definer set search_path=public,pg_temp as $$
declare s public.academy_live_sessions;
begin
  if not public.academy_can_teach(p_course) then raise exception 'Not authorized'; end if;
  if not exists(select 1 from public.academy_courses where id=p_course and status<>'archived') then raise exception 'Course unavailable'; end if;
  if p_starts_at is null or p_starts_at < now()-interval '5 minutes' then raise exception 'Choose a current or future start time'; end if;
  insert into public.academy_live_sessions(course_id,title,starts_at,duration_minutes,mode,max_participants,created_by)
    values(p_course,btrim(p_title),p_starts_at,p_duration,p_mode,p_capacity,auth.uid()) returning * into s;
  return s;
end;
$$;
revoke all on function public.academy_schedule_live(uuid,text,timestamptz,integer,text,integer) from public,anon;
grant execute on function public.academy_schedule_live(uuid,text,timestamptz,integer,text,integer) to authenticated;

create or replace function public.academy_cancel_live(p_session uuid)
returns void language plpgsql security definer set search_path=public,pg_temp as $$
declare s public.academy_live_sessions;
begin
  select * into s from public.academy_live_sessions where id=p_session for update;
  if not found or not public.academy_can_teach(s.course_id) then raise exception 'Not authorized'; end if;
  if s.status<>'scheduled' then raise exception 'Only scheduled classes can be cancelled'; end if;
  update public.academy_live_sessions set status='cancelled',ended_at=now() where id=s.id;
end;
$$;
revoke all on function public.academy_cancel_live(uuid) from public,anon;
grant execute on function public.academy_cancel_live(uuid) to authenticated;

-- Student links are existing bearer credentials, never room names or API secrets.
create or replace function public.academy_student_live(p_token uuid)
returns jsonb language plpgsql stable security definer set search_path=public,pg_temp as $$
declare e public.academy_enrollments;
begin
  select en.* into e from public.academy_enrollments en join public.academy_courses c on c.id=en.course_id and c.business_id=en.business_id
    where en.portal_token=p_token and en.status in ('active','completed') and c.status='published';
  if not found then raise exception 'Classroom unavailable'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('id',s.id,'course_id',s.course_id,'title',s.title,'starts_at',s.starts_at,
    'duration_minutes',s.duration_minutes,'mode',s.mode,'status',s.status,'max_participants',s.max_participants,
    'started_at',s.started_at,'ended_at',s.ended_at) order by s.starts_at desc)
    from public.academy_live_sessions s where s.course_id=e.course_id and s.status<>'cancelled'),'[]'::jsonb);
end;
$$;
revoke all on function public.academy_student_live(uuid) from public;
grant execute on function public.academy_student_live(uuid) to anon,authenticated;

-- Called with the caller's JWT, not the service-role JWT. The Railway backend
-- trusts only this database-derived identity, role, room and enrollment.
create or replace function public.academy_live_access(p_session uuid,p_token uuid default null)
returns jsonb language plpgsql stable security definer set search_path=public,pg_temp as $$
declare s public.academy_live_sessions; c public.academy_courses; e public.academy_enrollments;
  ident text; display text; teacher boolean=false;
begin
  select * into s from public.academy_live_sessions where id=p_session;
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id=s.course_id;
  if p_token is null and auth.uid() is not null then teacher:=public.academy_can_teach(c.id); end if;
  if teacher then
    ident:='teacher_'||auth.uid()::text;
    display:='Teacher';
  else
    select * into e from public.academy_enrollments where portal_token=p_token and course_id=c.id
      and business_id=c.business_id and status in ('active','completed');
    if not found or c.status<>'published' then raise exception 'Classroom unavailable'; end if;
    ident:='student_'||e.id::text;
    select coalesce(nullif(btrim(name),''),'Student') into display from public.contacts where id=e.contact_id and business_id=c.business_id;
  end if;
  if exists(select 1 from public.academy_live_members where session_id=s.id and identity=ident and blocked) then raise exception 'Access removed by teacher'; end if;
  return jsonb_build_object('session_id',s.id,'course_id',c.id,'business_id',c.business_id,'room_name',s.room_name,
    'identity',ident,'name',coalesce(display,'Student'),'teacher',teacher,'mode',s.mode,'status',s.status,
    'max_participants',s.max_participants,'title',s.title,'duration_minutes',s.duration_minutes,
    'can_publish',teacher or coalesce((select can_publish from public.academy_live_members where session_id=s.id and identity=ident),s.mode='interactive'));
end;
$$;
revoke all on function public.academy_live_access(uuid,uuid) from public;
grant execute on function public.academy_live_access(uuid,uuid) to anon,authenticated;

-- Service-only token throttle. Repeated calls cannot bypass a classroom block.
create or replace function public.academy_live_token_claim(p_session uuid,p_identity text)
returns void language plpgsql security definer set search_path=public,pg_temp as $$
declare m public.academy_live_members;
begin
  insert into public.academy_live_members(session_id,identity) values(p_session,p_identity) on conflict do nothing;
  select * into m from public.academy_live_members where session_id=p_session and identity=p_identity for update;
  if m.blocked then raise exception 'Access removed by teacher'; end if;
  if m.last_token_at>clock_timestamp()-interval '3 seconds' then raise exception 'Please wait before joining again'; end if;
  update public.academy_live_members set last_token_at=clock_timestamp() where session_id=p_session and identity=p_identity;
end;
$$;
revoke all on function public.academy_live_token_claim(uuid,text) from public,anon,authenticated;
grant execute on function public.academy_live_token_claim(uuid,text) to service_role;

-- Provider retries and out-of-order delivery do not duplicate attendance.
create or replace function public.academy_live_attendance_event(p_room text,p_sid text,p_identity text,p_name text,p_joined timestamptz,p_left timestamptz)
returns void language plpgsql security definer set search_path=public,pg_temp as $$
declare session_id uuid;
begin
  select id into session_id from public.academy_live_sessions where room_name=p_room;
  if session_id is null then return; end if;
  insert into public.academy_live_attendance(participant_sid,session_id,identity,display_name,joined_at,left_at)
    values(p_sid,session_id,p_identity,left(coalesce(p_name,'Participant'),160),p_joined,p_left)
  on conflict(participant_sid) do update set
    joined_at=least(academy_live_attendance.joined_at,excluded.joined_at),
    left_at=greatest(academy_live_attendance.left_at,excluded.left_at);
end;
$$;
revoke all on function public.academy_live_attendance_event(text,text,text,text,timestamptz,timestamptz) from public,anon,authenticated;
grant execute on function public.academy_live_attendance_event(text,text,text,text,timestamptz,timestamptz) to service_role;
commit;

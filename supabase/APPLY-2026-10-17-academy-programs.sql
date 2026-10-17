-- Apply after APPLY-2026-10-17-academy-certificate-trigger-fix.sql.
-- Programs (Kevin, 2026-10-17, "One deck, every room" boards 17-19, phase 4):
-- a series of classes taken in order with a finish line. Love City's The
-- Making is one program of four tracks (Foundation, Formation, Family,
-- Function) ending in graduation night; a coach's "Owner's Money Path" is
-- three courses with a certificate at the end.
--   * academy_programs / academy_program_courses: the program, its tracks in
--     order, and who teaches each track (the name people know them by);
--   * academy_program_schedule: one call sets a live class for every lesson
--     of every track (the dates are worked out on the page, skipped weeks and
--     all), each with its lesson and its track's teacher;
--   * academy_program_certificates: finishing every track issues one
--     certificate for the program, checked with the same short codes;
--   * academy_classroom tells a student which program their class is in, the
--     tracks with their dates, which they have done, and links to their own
--     other tracks.
begin;

-- ─── Programs and their tracks ───────────────────────────────────────
create table if not exists public.academy_programs (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  title text not null check (length(btrim(title)) between 1 and 120),
  description text not null default '' check (length(description) <= 2000),
  -- What the end is called (Graduation, Commissioning, Certificate) and when.
  finish_title text not null default 'Graduation' check (length(btrim(finish_title)) between 1 and 60),
  finish_at timestamptz,
  created_by uuid default auth.uid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists academy_programs_business on public.academy_programs(business_id);

create table if not exists public.academy_program_courses (
  program_id uuid not null references public.academy_programs(id) on delete cascade,
  -- A class belongs to one program at most.
  course_id uuid not null unique references public.academy_courses(id) on delete cascade,
  position integer not null default 0 check (position between 0 and 99),
  -- Who teaches this track, as people know them ("Pastor Kevin").
  teacher_name text check (teacher_name is null or length(btrim(teacher_name)) between 1 and 80),
  primary key (program_id, course_id)
);

-- A track is one of the program's own business's classes.
create or replace function public.academy_program_course_guard()
returns trigger language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
begin
  if not exists (select 1 from public.academy_programs p join public.academy_courses c on c.business_id = p.business_id
                  where p.id = new.program_id and c.id = new.course_id) then
    raise exception 'A track must be one of this business''s classes';
  end if;
  return new;
end $$;
revoke all on function public.academy_program_course_guard() from public, anon, authenticated;
drop trigger if exists academy_program_courses_guard on public.academy_program_courses;
create trigger academy_program_courses_guard before insert or update on public.academy_program_courses
  for each row execute function public.academy_program_course_guard();

drop trigger if exists academy_programs_touch on public.academy_programs;
create trigger academy_programs_touch before update on public.academy_programs
  for each row execute function public.academy_touch_updated_at();

alter table public.academy_programs enable row level security;
alter table public.academy_program_courses enable row level security;
revoke all on public.academy_programs, public.academy_program_courses from anon;

-- The policies ask about the other table through these, so neither table's
-- policy reads the other's (which Postgres refuses as recursion).
create or replace function public.academy_program_business(p_program uuid)
returns uuid language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select business_id from public.academy_programs where id = p_program
$$;
create or replace function public.academy_program_teaches(p_program uuid)
returns boolean language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select exists (select 1 from public.academy_program_courses pc where pc.program_id = p_program and public.academy_can_teach(pc.course_id))
$$;
create or replace function public.academy_owns_business(p_business uuid)
returns boolean language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select exists (select 1 from public.businesses b where b.id = p_business and b.owner_id = auth.uid())
$$;
revoke all on function public.academy_program_business(uuid), public.academy_program_teaches(uuid), public.academy_owns_business(uuid) from public, anon;
grant execute on function public.academy_program_business(uuid), public.academy_program_teaches(uuid), public.academy_owns_business(uuid) to authenticated;

-- The owner writes; the business's members and the teaching team of any
-- track read.
drop policy if exists academy_programs_owner on public.academy_programs;
create policy academy_programs_owner on public.academy_programs for all to authenticated
  using (public.academy_owns_business(academy_programs.business_id))
  with check (public.academy_owns_business(academy_programs.business_id));
drop policy if exists academy_programs_read on public.academy_programs;
create policy academy_programs_read on public.academy_programs for select to authenticated
  using (public.is_business_member(academy_programs.business_id) or public.academy_program_teaches(academy_programs.id));

drop policy if exists academy_program_courses_owner on public.academy_program_courses;
create policy academy_program_courses_owner on public.academy_program_courses for all to authenticated
  using (public.academy_owns_business(public.academy_program_business(academy_program_courses.program_id)))
  with check (public.academy_owns_business(public.academy_program_business(academy_program_courses.program_id)));
drop policy if exists academy_program_courses_read on public.academy_program_courses;
create policy academy_program_courses_read on public.academy_program_courses for select to authenticated
  using (public.is_business_member(public.academy_program_business(academy_program_courses.program_id))
    or public.academy_can_teach(academy_program_courses.course_id));

-- ─── Every lesson of every track, scheduled in one go ────────────────
-- p_plan: [{lesson_id, starts_at}] — the page works out the dates (weekly,
-- weeks skipped). A lesson that already has a class coming or live keeps
-- it. Each class is titled for its lesson and taught by its track's teacher.
create or replace function public.academy_program_schedule(p_program uuid, p_plan jsonb,
  p_duration integer default 60, p_mode text default 'broadcast', p_capacity integer default 30, p_finish_at timestamptz default null)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare p public.academy_programs; item jsonb; l public.academy_lessons; pc public.academy_program_courses; at timestamptz;
  made integer := 0; kept integer := 0;
begin
  select * into p from public.academy_programs where id = p_program;
  if not found then raise exception 'Program unavailable'; end if;
  if not exists (select 1 from public.businesses b where b.id = p.business_id and b.owner_id = auth.uid()) then
    raise exception 'Not authorized';
  end if;
  if p_plan is null or jsonb_typeof(p_plan) <> 'array' or jsonb_array_length(p_plan) = 0 or jsonb_array_length(p_plan) > 200 then
    raise exception 'Choose the dates first';
  end if;
  for item in select value from jsonb_array_elements(p_plan) loop
    select * into l from public.academy_lessons where id = (item->>'lesson_id')::uuid;
    if not found then raise exception 'A lesson in the plan was not found'; end if;
    select * into pc from public.academy_program_courses where program_id = p.id and course_id = l.course_id;
    if not found then raise exception 'A lesson in the plan is not in this program'; end if;
    at := (item->>'starts_at')::timestamptz;
    if exists (select 1 from public.academy_live_sessions s where s.lesson_id = l.id and s.status in ('scheduled', 'live')) then
      kept := kept + 1;
      continue;
    end if;
    perform public.academy_schedule_live(l.course_id, l.title, at, p_duration, p_mode, p_capacity, l.id, pc.teacher_name);
    made := made + 1;
  end loop;
  if p_finish_at is not null then
    update public.academy_programs set finish_at = p_finish_at where id = p.id;
  end if;
  return jsonb_build_object('scheduled', made, 'kept', kept);
end $$;
revoke all on function public.academy_program_schedule(uuid, jsonb, integer, text, integer, timestamptz) from public, anon;
grant execute on function public.academy_program_schedule(uuid, jsonb, integer, text, integer, timestamptz) to authenticated;

-- ─── One certificate for the whole program ───────────────────────────
create table if not exists public.academy_program_certificates (
  program_id uuid not null references public.academy_programs(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  code text not null unique check (code ~ '^[A-HJ-NP-Z2-9]{8}$'),
  completed_at timestamptz not null default now(),
  primary key (program_id, contact_id)
);
alter table public.academy_program_certificates enable row level security;
revoke all on public.academy_program_certificates from anon;
drop policy if exists academy_program_certificates_read on public.academy_program_certificates;
create policy academy_program_certificates_read on public.academy_program_certificates for select to authenticated
  using (public.is_business_member(public.academy_program_business(academy_program_certificates.program_id))
    or public.academy_owns_business(public.academy_program_business(academy_program_certificates.program_id)));

-- Codes are unique across class and program certificates.
create or replace function public.academy_new_certificate_code()
returns text language plpgsql volatile set search_path to 'public', 'pg_temp' as $$
declare letters constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; v text;
begin
  loop
    select string_agg(substr(letters, 1 + floor(random() * 32)::integer, 1), '') into v from generate_series(1, 8);
    exit when not exists (select 1 from public.academy_enrollments where certificate_code = v)
          and not exists (select 1 from public.academy_program_certificates where code = v);
  end loop;
  return v;
end $$;
revoke all on function public.academy_new_certificate_code() from public, anon, authenticated;

-- Has this person finished every track of this program?
create or replace function public.academy_program_finished(p_program uuid, p_contact uuid)
returns boolean language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select exists (select 1 from public.academy_program_courses where program_id = p_program)
     and not exists (
       select 1 from public.academy_program_courses pc join public.academy_courses c on c.id = pc.course_id
        where pc.program_id = p_program and c.status <> 'archived'
          and not exists (select 1 from public.academy_enrollments e
                           where e.course_id = pc.course_id and e.contact_id = p_contact and e.status = 'completed'))
$$;
revoke all on function public.academy_program_finished(uuid, uuid) from public, anon, authenticated;

-- Finishing the last track issues the program's certificate. It runs as its
-- owner: the code maker is server-only, and Course Studio finishes a student
-- with the owner's own signed-in update.
create or replace function public.academy_issue_program_certificate()
returns trigger language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare prog uuid;
begin
  if new.status <> 'completed' then return null; end if;
  select program_id into prog from public.academy_program_courses where course_id = new.course_id;
  if prog is null then return null; end if;
  if public.academy_program_finished(prog, new.contact_id) then
    insert into public.academy_program_certificates (program_id, contact_id, code)
      values (prog, new.contact_id, public.academy_new_certificate_code())
      on conflict (program_id, contact_id) do nothing;
  end if;
  return null;
end $$;
revoke all on function public.academy_issue_program_certificate() from public, anon, authenticated;
drop trigger if exists academy_enrollments_program_certificate on public.academy_enrollments;
create trigger academy_enrollments_program_certificate after insert or update of status on public.academy_enrollments
  for each row execute function public.academy_issue_program_certificate();

-- The check reads either kind. A program certificate is valid while every
-- track is still finished.
create or replace function public.academy_certificate_check(p_code text)
returns jsonb language plpgsql stable security definer set search_path to 'public', 'pg_temp' as $$
declare v text := upper(btrim(coalesce(p_code, ''))); e public.academy_enrollments; c public.academy_courses; b public.businesses;
  pcert public.academy_program_certificates; p public.academy_programs;
begin
  if v !~ '^[A-HJ-NP-Z2-9]{8}$' then return jsonb_build_object('found', false); end if;
  select * into e from public.academy_enrollments where certificate_code = v;
  if found then
    if e.status <> 'completed' then return jsonb_build_object('found', true, 'valid', false); end if;
    select * into c from public.academy_courses where id = e.course_id;
    select * into b from public.businesses where id = e.business_id;
    return jsonb_build_object('found', true, 'valid', true, 'code', v, 'kind', 'class',
      'student', coalesce((select name from public.contacts where id = e.contact_id), ''),
      'course', c.title, 'school', b.name, 'business_type', b.type,
      'completed_at', e.completed_at, 'teacher_name', public.academy_course_teacher(c.id),
      'brand', public.academy_brand_kit(b.id));
  end if;
  select * into pcert from public.academy_program_certificates where code = v;
  if not found then return jsonb_build_object('found', false); end if;
  if not public.academy_program_finished(pcert.program_id, pcert.contact_id) then
    return jsonb_build_object('found', true, 'valid', false);
  end if;
  select * into p from public.academy_programs where id = pcert.program_id;
  select * into b from public.businesses where id = p.business_id;
  return jsonb_build_object('found', true, 'valid', true, 'code', v, 'kind', 'program',
    'student', coalesce((select name from public.contacts where id = pcert.contact_id), ''),
    'course', p.title, 'school', b.name, 'business_type', b.type, 'completed_at', pcert.completed_at,
    'finish_title', p.finish_title,
    'tracks', coalesce((select jsonb_agg(c2.title order by pc.position, c2.created_at)
       from public.academy_program_courses pc join public.academy_courses c2 on c2.id = pc.course_id
       where pc.program_id = p.id and c2.status <> 'archived'), '[]'::jsonb),
    'teacher_name', null,
    'brand', public.academy_brand_kit(b.id));
end $$;

-- ─── The classroom knows its program ─────────────────────────────────
create or replace function public.academy_classroom_program(p_course uuid, p_contact uuid)
returns jsonb language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select jsonb_build_object('id', p.id, 'title', p.title, 'finish_title', p.finish_title, 'finish_at', p.finish_at,
    'certificate', (select code from public.academy_program_certificates where program_id = p.id and contact_id = p_contact),
    'tracks', coalesce((select jsonb_agg(jsonb_build_object(
        'course_id', c2.id, 'title', c2.title, 'teacher_name', pc.teacher_name,
        'starts_at', (select min(s.starts_at) from public.academy_live_sessions s where s.course_id = c2.id and s.status <> 'cancelled'),
        'ends_at', (select max(s.starts_at) from public.academy_live_sessions s where s.course_id = c2.id and s.status <> 'cancelled'),
        'state', case when c2.id = p_course then 'here' when e2.status = 'completed' then 'done'
                      when e2.id is not null then 'enrolled' else 'not_enrolled' end,
        'token', case when e2.id is not null and c2.status = 'published' then e2.portal_token end)
        order by pc.position, c2.created_at)
      from public.academy_program_courses pc join public.academy_courses c2 on c2.id = pc.course_id
      left join public.academy_enrollments e2 on e2.course_id = c2.id and e2.contact_id = p_contact and e2.status in ('active', 'completed')
      where pc.program_id = p.id and c2.status <> 'archived'), '[]'::jsonb))
  from public.academy_program_courses pc0 join public.academy_programs p on p.id = pc0.program_id
  where pc0.course_id = p_course
$$;
revoke all on function public.academy_classroom_program(uuid, uuid) from public, anon, authenticated;

create or replace function public.academy_classroom(p_token uuid)
 returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $function$
declare e public.academy_enrollments; c public.academy_courses; l public.academy_lessons;
  items jsonb='[]'; item jsonb; design jsonb; opens timestamptz; work jsonb; journal jsonb;
begin
  select * into e from public.academy_enrollments where portal_token=p_token and status in ('active','completed');
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id=e.course_id and business_id=e.business_id and status='published';
  if not found then raise exception 'Classroom unavailable'; end if;
  for l in select * from public.academy_lessons where course_id=c.id and business_id=c.business_id order by sort_order,id loop
    opens := public.academy_lesson_unlock(c,l,e.enrolled_at);
    item := jsonb_build_object('id',l.id,'title',l.title,'locked',opens>now(),'unlock_at',opens);
    if opens<=now() then
      design := coalesce(l.learning_design,'{}');
      -- Construct each public question from an allowlist. Answer keys never leave the server.
      design := jsonb_set(design,'{questions}',coalesce((select jsonb_agg(jsonb_build_object(
        'id',q->>'id','prompt',q->>'prompt','kind',q->>'kind','options',q->'options','required',q->'required'
      )) from jsonb_array_elements(coalesce(design->'questions','[]')) q),'[]'));
      item := item || jsonb_build_object('course_id',l.course_id,'content',l.content,'video_url',l.video_url,
        'resource_url',l.resource_url,'homework',l.homework,'sort_order',l.sort_order,'lesson_type',l.lesson_type,
        'duration_minutes',l.duration_minutes,'drip_offset_days',l.drip_offset_days,'learning_design',design);
    end if;
    items := items || jsonb_build_array(item);
  end loop;
  select coalesce(jsonb_object_agg(r.lesson_id::text,jsonb_build_object('answers',r.answers,'score',case when r.assessment_signature=public.academy_assessment_signature(lesson) then r.score end,'passed',r.passed and r.assessment_signature=public.academy_assessment_signature(lesson),'submitted_at',case when r.assessment_signature=public.academy_assessment_signature(lesson) then r.submitted_at end,'feedback',case when r.assessment_signature=public.academy_assessment_signature(lesson) then r.feedback else '' end,'teacher_score',case when r.assessment_signature=public.academy_assessment_signature(lesson) then r.teacher_score end,'updated_at',r.updated_at,'needs_resubmission',r.assessment_signature is distinct from public.academy_assessment_signature(lesson))),'{}') into work
    from public.academy_lesson_responses r join public.academy_lessons lesson on lesson.id=r.lesson_id
    where r.enrollment_id=e.id and lesson.course_id=c.id and public.academy_lesson_unlock(c,lesson,e.enrolled_at)<=now();
  select coalesce(jsonb_object_agg(j.lesson_id::text, jsonb_build_object('notes',j.notes,'thoughts',j.thoughts,'ticks',j.ticks,'updated_at',j.updated_at)),'{}') into journal
    from public.academy_lesson_journal j join public.academy_lessons jl on jl.id=j.lesson_id
    where j.enrollment_id=e.id and jl.course_id=c.id and public.academy_lesson_unlock(c,jl,e.enrolled_at)<=now();
  return jsonb_build_object('course',jsonb_build_object('id',c.id,'title',c.title,'description',c.description,'grading_mode',c.grading_mode,
      'cover_url',c.cover_url,'teacher_name',coalesce((select pc.teacher_name from public.academy_program_courses pc where pc.course_id=c.id),public.academy_course_teacher(c.id))),
    'grade',public.academy_grade_result(e.id),
    'school',(select name from public.businesses where id=c.business_id),
    'business_type',(select type from public.businesses where id=c.business_id),
    'brand',public.academy_brand_kit(c.business_id),
    'student',(select name from public.contacts where id=e.contact_id),
    'enrollment',jsonb_build_object('status',e.status,'completed_at',e.completed_at,
      'certificate',case when e.status='completed' then e.certificate_code end),
    'program',public.academy_classroom_program(c.id, e.contact_id),
    'lessons',items,'progress',coalesce(e.progress,'{}') - array(select pending_l.id::text from public.academy_lessons pending_l left join public.academy_lesson_responses r on r.lesson_id=pending_l.id and r.enrollment_id=e.id where pending_l.course_id=c.id and (coalesce(btrim(pending_l.homework),'')<>'' or jsonb_array_length(coalesce(pending_l.learning_design->'workbook'->'prompts','[]'))>0 or jsonb_array_length(coalesce(pending_l.learning_design->'questions','[]'))>0) and (r.submitted_at is null or r.assessment_signature is distinct from public.academy_assessment_signature(pending_l))),
    'responses',work,'journal',journal);
end;
$function$;

commit;

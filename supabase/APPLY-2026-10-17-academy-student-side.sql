-- Apply after APPLY-2026-10-17-academy-live-room.sql.
-- The student's side of a class (Kevin, 2026-10-17, "One deck, every room"
-- boards 12-16, phase 3):
--   * the classroom wears the business's colors, fonts and logo, and knows
--     its type (a church's classes go by weeks);
--   * a lesson opens on the class slides: academy_lesson_slides gives a
--     student the saved deck without the teacher's notes;
--   * a student keeps their own notes, their thoughts on the discussion
--     questions and the ticks on "this week" per lesson
--     (academy_lesson_journal): only they read it, through their class link;
--   * finishing a course issues a certificate with a short code anyone can
--     check (academy_certificate_check), and the classroom and "My school"
--     carry it;
--   * academy_student_live says how long this student was in each class.
begin;

-- ─── The brand a classroom wears ─────────────────────────────────────
-- The same subset academy_course_brand gives a teacher: colors, fonts, logo.
create or replace function public.academy_brand_kit(p_business uuid)
returns jsonb language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select coalesce((select jsonb_strip_nulls(jsonb_build_object(
      'colors', k.kit->'colors', 'primary_color', k.kit->'primary_color',
      'font_heading', k.kit->'font_heading', 'font_body', k.kit->'font_body', 'font_pair', k.kit->'font_pair',
      'logo_url', k.kit->'logo_url'))
    from public.businesses b
    cross join lateral (select case when jsonb_typeof(b.settings->'brand_kit') = 'object' then b.settings->'brand_kit' else '{}'::jsonb end as kit) k
    where b.id = p_business), '{}'::jsonb)
$$;
revoke all on function public.academy_brand_kit(uuid) from public, anon, authenticated;

-- Who teaches a course, as people know them: the latest class that names one.
create or replace function public.academy_course_teacher(p_course uuid)
returns text language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select s.teacher_name from public.academy_live_sessions s
   where s.course_id = p_course and s.status <> 'cancelled' and s.teacher_name is not null
   order by s.starts_at desc limit 1
$$;
revoke all on function public.academy_course_teacher(uuid) from public, anon, authenticated;

-- ─── A student's own notes, thoughts and ticks, one row per lesson ───
-- thoughts: {key: text} keyed by a short fingerprint of the discussion
-- question; ticks: [key] of the "this week" items done. The keys come from
-- the lesson's words, so an edited item starts unticked instead of moving.
create table if not exists public.academy_lesson_journal (
  enrollment_id uuid not null references public.academy_enrollments(id) on delete cascade,
  lesson_id uuid not null references public.academy_lessons(id) on delete cascade,
  course_id uuid not null references public.academy_courses(id) on delete cascade,
  notes text not null default '' check (length(notes) <= 6000),
  thoughts jsonb not null default '{}'::jsonb check (jsonb_typeof(thoughts) = 'object'),
  ticks jsonb not null default '[]'::jsonb check (jsonb_typeof(ticks) = 'array'),
  updated_at timestamptz not null default now(),
  primary key (enrollment_id, lesson_id)
);
create index if not exists academy_lesson_journal_course on public.academy_lesson_journal(course_id);
-- Server-only: read and written through the student's class link below.
alter table public.academy_lesson_journal enable row level security;
revoke all on public.academy_lesson_journal from anon, authenticated;

create or replace function public.academy_save_journal(p_token uuid, p_lesson uuid,
  p_notes text default null, p_thoughts jsonb default null, p_ticks jsonb default null)
returns jsonb language plpgsql security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; c public.academy_courses; l public.academy_lessons; j public.academy_lesson_journal;
begin
  if p_notes is not null and length(p_notes) > 6000 then raise exception 'Notes are too long'; end if;
  if p_thoughts is not null and (jsonb_typeof(p_thoughts) <> 'object' or (select count(*) from jsonb_object_keys(p_thoughts)) > 40
    or exists (select 1 from jsonb_each(p_thoughts) t where t.key !~ '^[a-z0-9]{1,16}$' or jsonb_typeof(t.value) <> 'string' or length(t.value #>> '{}') > 2000))
    then raise exception 'Invalid thoughts'; end if;
  if p_ticks is not null and (jsonb_typeof(p_ticks) <> 'array' or jsonb_array_length(p_ticks) > 40
    or exists (select 1 from jsonb_array_elements(p_ticks) t where jsonb_typeof(t) <> 'string' or (t #>> '{}') !~ '^[a-z0-9]{1,16}$'))
    then raise exception 'Invalid ticks'; end if;
  select * into e from public.academy_enrollments where portal_token = p_token and status in ('active', 'completed');
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id = e.course_id and business_id = e.business_id and status = 'published';
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into l from public.academy_lessons where id = p_lesson and course_id = c.id and business_id = c.business_id;
  if not found then raise exception 'Lesson unavailable'; end if;
  if public.academy_lesson_unlock(c, l, e.enrolled_at) > now() then raise exception 'Lesson not yet available'; end if;
  insert into public.academy_lesson_journal (enrollment_id, lesson_id, course_id, notes, thoughts, ticks)
    values (e.id, l.id, c.id, coalesce(p_notes, ''), coalesce(p_thoughts, '{}'::jsonb), coalesce(p_ticks, '[]'::jsonb))
  on conflict (enrollment_id, lesson_id) do update set
    notes = coalesce(p_notes, academy_lesson_journal.notes),
    thoughts = coalesce(p_thoughts, academy_lesson_journal.thoughts),
    ticks = coalesce(p_ticks, academy_lesson_journal.ticks),
    updated_at = now()
  returning * into j;
  return jsonb_build_object('notes', j.notes, 'thoughts', j.thoughts, 'ticks', j.ticks, 'updated_at', j.updated_at);
end $$;
revoke all on function public.academy_save_journal(uuid, uuid, text, jsonb, jsonb) from public;
grant execute on function public.academy_save_journal(uuid, uuid, text, jsonb, jsonb) to anon, authenticated;

-- ─── The class slides, for a student ─────────────────────────────────
-- The deck the teacher saved, without anyone's notes; {saved:false} when the
-- lesson has none yet (the classroom then builds it from the lesson's words,
-- as the Slides tab does).
create or replace function public.academy_lesson_slides(p_token uuid, p_lesson uuid)
returns jsonb language plpgsql stable security definer set search_path to 'public', 'pg_temp' as $$
declare e public.academy_enrollments; c public.academy_courses; l public.academy_lessons; d public.academy_decks;
begin
  select * into e from public.academy_enrollments where portal_token = p_token and status in ('active', 'completed');
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into c from public.academy_courses where id = e.course_id and business_id = e.business_id and status = 'published';
  if not found then raise exception 'Classroom unavailable'; end if;
  select * into l from public.academy_lessons where id = p_lesson and course_id = c.id and business_id = c.business_id;
  if not found then raise exception 'Lesson unavailable'; end if;
  if public.academy_lesson_unlock(c, l, e.enrolled_at) > now() then raise exception 'Lesson not yet available'; end if;
  select * into d from public.academy_decks where lesson_id = l.id and course_id = c.id;
  if not found or jsonb_typeof(d.slides) <> 'array' or jsonb_array_length(d.slides) = 0 then
    return jsonb_build_object('saved', false);
  end if;
  return jsonb_build_object('saved', true, 'revision', d.revision, 'slides', public.academy_strip_notes(d.slides));
end $$;
revoke all on function public.academy_lesson_slides(uuid, uuid) from public;
grant execute on function public.academy_lesson_slides(uuid, uuid) to anon, authenticated;

-- ─── Certificates ────────────────────────────────────────────────────
alter table public.academy_enrollments add column if not exists certificate_code text
  check (certificate_code is null or certificate_code ~ '^[A-HJ-NP-Z2-9]{8}$');
create unique index if not exists academy_enrollments_certificate_code
  on public.academy_enrollments(certificate_code) where certificate_code is not null;

create or replace function public.academy_new_certificate_code()
returns text language plpgsql volatile set search_path to 'public', 'pg_temp' as $$
declare letters constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; v text;
begin
  loop
    select string_agg(substr(letters, 1 + floor(random() * 32)::integer, 1), '') into v from generate_series(1, 8);
    exit when not exists (select 1 from public.academy_enrollments where certificate_code = v);
  end loop;
  return v;
end $$;
revoke all on function public.academy_new_certificate_code() from public, anon, authenticated;

-- Finishing a course issues the code once; it stays the same if they go back
-- over a lesson and finish again.
create or replace function public.academy_issue_certificate()
returns trigger language plpgsql set search_path to 'public', 'pg_temp' as $$
begin
  if new.status = 'completed' and new.certificate_code is null then
    new.certificate_code := public.academy_new_certificate_code();
  end if;
  return new;
end $$;
revoke all on function public.academy_issue_certificate() from public, anon, authenticated;
drop trigger if exists academy_enrollments_certificate on public.academy_enrollments;
create trigger academy_enrollments_certificate before insert or update on public.academy_enrollments
  for each row execute function public.academy_issue_certificate();

update public.academy_enrollments set certificate_code = public.academy_new_certificate_code()
 where status = 'completed' and certificate_code is null;

-- Anyone holding a certificate can show it's real: the code says who
-- finished what, where and when. A course no longer finished reads as not
-- valid, without a name.
create or replace function public.academy_certificate_check(p_code text)
returns jsonb language plpgsql stable security definer set search_path to 'public', 'pg_temp' as $$
declare v text := upper(btrim(coalesce(p_code, ''))); e public.academy_enrollments; c public.academy_courses; b public.businesses;
begin
  if v !~ '^[A-HJ-NP-Z2-9]{8}$' then return jsonb_build_object('found', false); end if;
  select * into e from public.academy_enrollments where certificate_code = v;
  if not found then return jsonb_build_object('found', false); end if;
  if e.status <> 'completed' then return jsonb_build_object('found', true, 'valid', false); end if;
  select * into c from public.academy_courses where id = e.course_id;
  select * into b from public.businesses where id = e.business_id;
  return jsonb_build_object('found', true, 'valid', true, 'code', v,
    'student', coalesce((select name from public.contacts where id = e.contact_id), ''),
    'course', c.title, 'school', b.name, 'business_type', b.type,
    'completed_at', e.completed_at, 'teacher_name', public.academy_course_teacher(c.id),
    'brand', public.academy_brand_kit(b.id));
end $$;
revoke all on function public.academy_certificate_check(text) from public;
grant execute on function public.academy_certificate_check(text) to anon, authenticated;

-- ─── The classroom: brand, type, journal, certificate ────────────────
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
      'cover_url',c.cover_url,'teacher_name',public.academy_course_teacher(c.id)),
    'grade',public.academy_grade_result(e.id),
    'school',(select name from public.businesses where id=c.business_id),
    'business_type',(select type from public.businesses where id=c.business_id),
    'brand',public.academy_brand_kit(c.business_id),
    'student',(select name from public.contacts where id=e.contact_id),
    'enrollment',jsonb_build_object('status',e.status,'completed_at',e.completed_at,
      'certificate',case when e.status='completed' then e.certificate_code end),
    'lessons',items,'progress',coalesce(e.progress,'{}') - array(select pending_l.id::text from public.academy_lessons pending_l left join public.academy_lesson_responses r on r.lesson_id=pending_l.id and r.enrollment_id=e.id where pending_l.course_id=c.id and (coalesce(btrim(pending_l.homework),'')<>'' or jsonb_array_length(coalesce(pending_l.learning_design->'workbook'->'prompts','[]'))>0 or jsonb_array_length(coalesce(pending_l.learning_design->'questions','[]'))>0) and (r.submitted_at is null or r.assessment_signature is distinct from public.academy_assessment_signature(pending_l))),
    'responses',work,'journal',journal);
end;
$function$;

-- ─── Live classes, with how long this student was there ──────────────
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
       from public.academy_live_attendance a where a.session_id = s.id and a.identity = 'student_' || e.id and a.joined_at is not null)
    ) order by s.starts_at desc)
    from public.academy_live_sessions s where s.course_id = e.course_id and s.status <> 'cancelled'), '[]'::jsonb);
end;
$function$;

-- ─── My school: each class with its brand and certificate ────────────
create or replace function public.academy_my_school()
 returns jsonb language plpgsql stable security definer set search_path to 'public', 'pg_temp' as $function$
declare verified_email text;
begin
  select lower(email) into verified_email from auth.users where id=auth.uid() and email_confirmed_at is not null;
  if verified_email is null then raise exception 'Sign in with a verified email'; end if;
  return jsonb_build_object('email',verified_email,
    'learning',coalesce((select jsonb_agg(jsonb_build_object('id',e.id,'title',c.title,'school',b.name,'token',e.portal_token,'result',public.academy_grade_result(e.id),
        'business_type',b.type,'brand',public.academy_brand_kit(b.id),'status',e.status,
        'certificate',case when e.status='completed' then e.certificate_code end) order by c.title)
      from public.academy_enrollments e join public.contacts ct on ct.id=e.contact_id and ct.business_id=e.business_id
      join public.academy_courses c on c.id=e.course_id and c.business_id=e.business_id join public.businesses b on b.id=c.business_id
      where lower(btrim(ct.email))=verified_email and e.status in ('active','completed') and c.status='published'),'[]'),
    'teaching',coalesce((select jsonb_agg(jsonb_build_object('id',c.id,'title',c.title,'school',b.name,'business_id',c.business_id,'role',t.role,'drip_mode',c.drip_mode,'grading_mode',c.grading_mode) order by c.title)
      from public.academy_teachers t join public.academy_courses c on c.id=t.course_id join public.businesses b on b.id=c.business_id where t.email=verified_email),'[]'));
end;
$function$;

commit;

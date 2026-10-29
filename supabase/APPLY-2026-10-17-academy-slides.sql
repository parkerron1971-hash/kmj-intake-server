-- Class slides (Kevin, 2026-10-17: "presentations to be created for visuals
-- for the class… chief needs to be able to create visuals").
--
-- One deck per lesson. Until someone edits it, the app builds the deck from
-- the lesson's own text, so nothing is stored; the first save stores it.
-- Teacher notes live inside each slide (`notes`) and never leave through a
-- presenting session: academy_present_start / _update strip them.
--
-- A present session is what a TV (or a phone following along) watches:
-- a short code, a snapshot of the slides, the slide showing now. The TV
-- reads it through academy_present_view without signing in; the code is
-- the key and expires with the class.
--
-- Apply after the academy school + authoring migrations. Idempotent.
begin;

-- ─── Decks ───────────────────────────────────────────────────────────
create table if not exists public.academy_decks (
  lesson_id uuid primary key references public.academy_lessons(id) on delete cascade,
  course_id uuid not null references public.academy_courses(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  slides jsonb not null default '[]'::jsonb,
  -- sha256 of the lesson text the deck was last rebuilt from; the editor
  -- offers a rebuild when the lesson has changed since.
  source_hash text,
  revision integer not null default 1,
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint academy_decks_slides check (
    jsonb_typeof(slides) = 'array'
    and jsonb_array_length(slides) <= 60
    and octet_length(slides::text) <= 400000)
);
create index if not exists academy_decks_course on public.academy_decks(course_id);
alter table public.academy_decks enable row level security;
revoke all on public.academy_decks from public, anon;
grant select, delete on public.academy_decks to authenticated;
drop policy if exists academy_decks_read on public.academy_decks;
create policy academy_decks_read on public.academy_decks for select to authenticated
  using (public.academy_can_teach(course_id));
-- Deleting a deck = "rebuild from the lesson". Writes go through
-- academy_save_deck so size, layout and revision are checked in one place.
drop policy if exists academy_decks_delete on public.academy_decks;
create policy academy_decks_delete on public.academy_decks for delete to authenticated
  using (public.academy_can_teach(course_id, true));

create or replace function public.academy_valid_slides(p_slides jsonb)
returns boolean language sql immutable set search_path = public, pg_temp as $$
  select jsonb_typeof(p_slides) = 'array'
    and jsonb_array_length(p_slides) between 0 and 60
    and octet_length(p_slides::text) <= 400000
    and not exists (
      select 1 from jsonb_array_elements(p_slides) s
      where jsonb_typeof(s) <> 'object'
         or length(coalesce(s->>'id', '')) not between 1 and 64
         or coalesce(s->>'layout', '') not in
            ('title','quote','point','list','tiles','columns','diagram','question','memory','chart','picture','closing')
         or (s ? 'image' and coalesce(s->'image'->>'url', '') !~ '^https://'))
$$;

create or replace function public.academy_save_deck(
  p_lesson uuid, p_slides jsonb, p_source_hash text default null, p_revision integer default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare l academy_lessons; d academy_decks;
begin
  select * into l from academy_lessons where id = p_lesson;
  if not found or not public.academy_can_teach(l.course_id, true) then
    raise exception 'Slides not available for this account';
  end if;
  if not public.academy_valid_slides(p_slides) then
    raise exception 'These slides could not be saved: each needs an id and a known layout, pictures need an https link, and a deck holds up to 60 slides.';
  end if;
  if p_source_hash is not null and p_source_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'Invalid lesson fingerprint';
  end if;
  select * into d from academy_decks where lesson_id = p_lesson for update;
  if found then
    if p_revision is not null and d.revision <> p_revision then
      raise exception 'These slides changed since you opened them. Reload to see the latest.';
    end if;
    update academy_decks
       set slides = p_slides, source_hash = p_source_hash, revision = d.revision + 1,
           updated_by = auth.uid(), updated_at = now()
     where lesson_id = p_lesson
     returning * into d;
  else
    insert into academy_decks (lesson_id, course_id, business_id, slides, source_hash, updated_by)
    values (p_lesson, l.course_id, l.business_id, p_slides, p_source_hash, auth.uid())
    returning * into d;
  end if;
  return jsonb_build_object('lesson_id', d.lesson_id, 'course_id', d.course_id,
    'revision', d.revision, 'updated_at', d.updated_at);
end $$;
revoke all on function public.academy_valid_slides(jsonb) from public, anon;
revoke all on function public.academy_save_deck(uuid, jsonb, text, integer) from public, anon;
grant execute on function public.academy_save_deck(uuid, jsonb, text, integer) to authenticated;

-- Chief reads a lesson's saved slides with the rest of the course. The
-- lesson `revision` stays the hash of the lesson row alone, so saving
-- slides never invalidates a lesson edit in flight.
create or replace function public.academy_inspect(p_business uuid, p_course uuid default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if not exists(select 1 from businesses where id = p_business and owner_id = auth.uid()) then
    raise exception 'Course not available for this account';
  end if;
  if p_course is null then
    return jsonb_build_object('courses', coalesce((select jsonb_agg(jsonb_build_object('id', c.id, 'title', c.title, 'description', c.description, 'status', c.status) order by c.created_at desc) from academy_courses c where business_id = p_business), '[]'));
  end if;
  if not exists(select 1 from academy_courses where id = p_course and business_id = p_business) then
    raise exception 'Course not available for this account';
  end if;
  return jsonb_build_object(
    'course', (select to_jsonb(c) from academy_courses c where id = p_course),
    'lessons', coalesce((
      select jsonb_agg(
        to_jsonb(l) || jsonb_build_object('revision', md5(to_jsonb(l)::text))
          || case when d.lesson_id is null
               then jsonb_build_object('slides_saved', false)
               else jsonb_build_object('slides_saved', true, 'slides', d.slides, 'slides_revision', d.revision) end
        order by l.sort_order, l.id)
      from academy_lessons l left join academy_decks d on d.lesson_id = l.id
      where l.course_id = p_course and l.business_id = p_business), '[]'));
end $$;
revoke all on function public.academy_inspect(uuid, uuid) from public, anon;
grant execute on function public.academy_inspect(uuid, uuid) to authenticated;

-- ─── Presenting ──────────────────────────────────────────────────────
create table if not exists public.academy_present_sessions (
  id uuid primary key default gen_random_uuid(),
  code text not null,
  business_id uuid not null references public.businesses(id) on delete cascade,
  course_id uuid not null references public.academy_courses(id) on delete cascade,
  lesson_id uuid not null references public.academy_lessons(id) on delete cascade,
  title text not null default '',
  slides jsonb not null default '[]'::jsonb,
  theme jsonb not null default '{}'::jsonb,
  slide_index integer not null default 0,
  blank boolean not null default false,
  state_version integer not null default 1,
  slides_version integer not null default 1,
  started_by uuid,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  expires_at timestamptz not null default now() + interval '8 hours',
  constraint academy_present_code check (code ~ '^[A-HJ-NP-Z2-9]{6}$')
);
create unique index if not exists academy_present_live_code
  on public.academy_present_sessions(code) where ended_at is null;
create index if not exists academy_present_lesson on public.academy_present_sessions(lesson_id, started_at desc);
alter table public.academy_present_sessions enable row level security;
-- Only the functions below touch it.
revoke all on public.academy_present_sessions from public, anon, authenticated;

create or replace function public.academy_strip_notes(p_slides jsonb)
returns jsonb language sql immutable set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(s - 'notes' order by ord), '[]'::jsonb)
  from jsonb_array_elements(p_slides) with ordinality as t(s, ord)
$$;
revoke all on function public.academy_strip_notes(jsonb) from public, anon;

create or replace function public.academy_present_start(
  p_lesson uuid, p_slides jsonb, p_theme jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare l academy_lessons; s academy_present_sessions; v_code text; tries integer := 0;
  alphabet constant text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
begin
  select * into l from academy_lessons where id = p_lesson;
  if not found or not public.academy_can_teach(l.course_id) then
    raise exception 'Presenting is not available for this account';
  end if;
  if not public.academy_valid_slides(p_slides) or jsonb_array_length(p_slides) = 0 then
    raise exception 'This lesson has no slides to present';
  end if;
  if jsonb_typeof(coalesce(p_theme, '{}'::jsonb)) <> 'object' or octet_length(coalesce(p_theme, '{}'::jsonb)::text) > 4000 then
    raise exception 'Invalid slide colors';
  end if;
  -- Codes are unique among live sessions; expired ones give theirs back.
  update academy_present_sessions set ended_at = now()
   where ended_at is null and (expires_at < now() or lesson_id = p_lesson);
  loop
    tries := tries + 1;
    v_code := '';
    for i in 1..6 loop
      v_code := v_code || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    end loop;
    exit when not exists (select 1 from academy_present_sessions where code = v_code and ended_at is null);
    if tries > 20 then raise exception 'No presenting code is free right now. Try again.'; end if;
  end loop;
  insert into academy_present_sessions (code, business_id, course_id, lesson_id, title, slides, theme, started_by)
  values (v_code, l.business_id, l.course_id, l.id, left(coalesce(l.title, ''), 200),
          public.academy_strip_notes(p_slides), coalesce(p_theme, '{}'::jsonb), auth.uid())
  returning * into s;
  return jsonb_build_object('id', s.id, 'code', s.code, 'expires_at', s.expires_at);
end $$;

create or replace function public.academy_present_update(
  p_session uuid, p_index integer default null, p_blank boolean default null,
  p_slides jsonb default null, p_end boolean default false)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
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
  n := jsonb_array_length(s.slides);
  update academy_present_sessions
     set slides = s.slides,
         slides_version = s.slides_version,
         slide_index = greatest(0, least(n - 1, coalesce(p_index, s.slide_index))),
         blank = coalesce(p_blank, s.blank),
         state_version = s.state_version + 1,
         expires_at = greatest(expires_at, now() + interval '2 hours')
   where id = p_session
   returning * into s;
  return jsonb_build_object('ended', false, 'index', s.slide_index, 'blank', s.blank,
    'state_version', s.state_version, 'slides_version', s.slides_version);
end $$;

-- The TV's read. Anyone holding the code sees the slides (never the notes)
-- while the class is presenting; slides only come back when they changed.
create or replace function public.academy_present_view(p_code text, p_slides_version integer default 0)
returns jsonb language plpgsql stable security definer set search_path = public, pg_temp as $$
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
    'index', s.slide_index, 'blank', s.blank,
    'state_version', s.state_version, 'slides_version', s.slides_version,
    'title', s.title, 'business', coalesce(biz, ''), 'theme', s.theme, 'count', jsonb_array_length(s.slides))
    || case when coalesce(p_slides_version, 0) <> s.slides_version
         then jsonb_build_object('slides', s.slides) else '{}'::jsonb end;
end $$;

revoke all on function public.academy_present_start(uuid, jsonb, jsonb) from public, anon;
revoke all on function public.academy_present_update(uuid, integer, boolean, jsonb, boolean) from public, anon;
revoke all on function public.academy_present_view(text, integer) from public;
grant execute on function public.academy_present_start(uuid, jsonb, jsonb) to authenticated;
grant execute on function public.academy_present_update(uuid, integer, boolean, jsonb, boolean) to authenticated;
grant execute on function public.academy_present_view(text, integer) to anon, authenticated;

commit;

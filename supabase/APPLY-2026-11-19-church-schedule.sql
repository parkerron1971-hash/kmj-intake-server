-- APPLY-2026-11-19-church-schedule.sql
--
-- The leaders schedule, step 1: its tables (docs/CHURCH_SCHEDULE.md). Nothing
-- reads them yet; church_schedule.py, church_schedule_tell.py and
-- member_portal_dates.py come in the PRs after this one.
-- Kevin, 2026-11-18: "I want to be able to build Leaders schedule. this is
-- for when leaders are planning time off and have certain obiligations so
-- that we as a church can plan around meeting ... making sure that everyone
-- is not gone at the same time on our services. allowing only so many people
-- off at the same time. ... there should volunteers one and one for
-- leadership ... divided amongs the department to manage there department as
-- well." And, shown the five calls the plan rests on: "Yes build to all
-- five".
--
-- serve_away stays the one table of facts: "this person is away these dates".
-- Everything that reads it today reads it as before. What is new:
--
--   church_away_asks        a leader asks to be away: who, the dates, the kind
--                           (time off, another commitment, can't make it), a
--                           private reason, who covers, who it went to (a
--                           login or one of the church's people, never both),
--                           its state (asked, yes, no, withdrawn), who decided
--                           and when, and its flags. A yes writes one
--                           serve_away row that names the ask. The reason
--                           never leaves this table. Nothing to do with
--                           church_map_asks or member_asks.
--   church_away_settle()    one decision in one transaction: the ask's state,
--                           and its serve_away row made (yes) or taken off
--                           (withdrawn). Answers with whether anything
--                           changed, so two people answering at once is safe.
--   serve_away.ask_id       the ask a fact came from (null = an away date
--                           added the way it always was); one fact an ask
--   serve_away.kind         that ask's kind (null = a plain away date)
--   church_away_commitments something that repeats ("I work every second
--                           Saturday"): a weekday, how it repeats, from when.
--                           Read by the leaders calendar and the scheduler.
--   church_schedule_people  the church's own add list and remove list for
--                           who is on the leaders schedule
--   church_schedule_settings  how many days' notice the church asks for
--                           (14 unless it says otherwise)
--
-- Server-only: every new table RLS on with no policies, anon and authenticated
-- revoked, service_role granted; every function revoked from public, anon and
-- authenticated. One transaction, lock_timeout 5s, safe to run twice, no table,
-- column or row dropped (triggers are dropped and made again, as every file
-- here does). serve_away's two new columns are null on every row that exists,
-- so its foreign key and its check go in NOT VALID: nothing old is scanned
-- under the lock and every row written from now on is checked. Ends with
-- NOTIFY pgrst so the API sees the tables and the function at once.
-- Apply before the code that reads it: until then church_schedule.ready() is
-- False, the routes answer 404 and the scheduler reads as it always did.
begin;

set local lock_timeout = '5s';

-- ─── The church's settings ──────────────────────────────────────────────

create table if not exists public.church_schedule_settings(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  notice_days smallint not null default 14 check (notice_days between 0 and 90),
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now()
);

-- ─── Who is on the leaders schedule, past what the church's data says ───

create table if not exists public.church_schedule_people(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  listed text not null check (listed in ('add', 'remove')),
  grp text check (grp in ('leaders', 'office')),
  set_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (business_id, contact_id),
  constraint church_schedule_people_group check ((listed = 'add') = (grp is not null))
);

-- ─── An ask ─────────────────────────────────────────────────────────────

create table if not exists public.church_away_asks(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  made_by uuid references auth.users(id) on delete set null,
  grp text not null check (grp in ('leaders', 'office', 'volunteers')),
  department_id uuid references public.church_departments(id) on delete set null,
  kind text not null check (kind in ('time_off', 'commitment', 'cant')),
  starts_on date not null,
  ends_on date not null,
  reason text check (reason is null or char_length(reason) <= 500),
  cover_contact_id uuid references public.contacts(id) on delete set null,
  cover_name text check (cover_name is null or char_length(btrim(cover_name)) between 1 and 80),
  to_user_id uuid references auth.users(id) on delete set null,
  to_contact_id uuid references public.contacts(id) on delete set null,
  state text not null default 'asked' check (state in ('asked', 'yes', 'no', 'withdrawn')),
  flags text[] not null default '{}'
    check (flags <@ array['short_notice', 'over_limit', 'protected_day', 'pair', 'serving']::text[]),
  decided_by_user_id uuid references auth.users(id) on delete set null,
  decided_by_contact_id uuid references public.contacts(id) on delete set null,
  decided_at timestamptz,
  decided_note text check (decided_note is null or char_length(decided_note) <= 300),
  withdrawn_at timestamptz,
  told_at timestamptz,
  answer_told_at timestamptz,
  nudged_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_away_asks_days check (ends_on >= starts_on and ends_on - starts_on <= 366),
  constraint church_away_asks_to_one check (to_user_id is null or to_contact_id is null),
  constraint church_away_asks_by_one check (decided_by_user_id is null or decided_by_contact_id is null),
  -- What church_away_settle writes, state by state. A withdrawn ask keeps
  -- decided_at when it had been a yes, and has none when it was still waiting.
  constraint church_away_asks_decided check (
    (state = 'asked' and decided_at is null and withdrawn_at is null)
    or (state in ('yes', 'no') and decided_at is not null and withdrawn_at is null)
    or (state = 'withdrawn' and withdrawn_at is not null)),
  constraint church_away_asks_cover_other check (cover_contact_id is null or cover_contact_id <> contact_id)
);

-- An ask stays with its church and its person, and everyone else it names is
-- its own church's, whatever the caller passes. Each of them is checked only
-- when a write names them: a foreign key setting one of them null (a person
-- removed, a church going) checks nothing.
create or replace function public.church_away_asks_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_op = 'UPDATE' then
    if new.business_id <> old.business_id or new.contact_id <> old.contact_id then
      raise exception 'An ask stays with its church and its person';
    end if;
  end if;
  if tg_op = 'INSERT' then
    if not exists (select 1 from public.contacts c
                   where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this church';
    end if;
  end if;
  if new.cover_contact_id is not null
     and (tg_op = 'INSERT' or new.cover_contact_id is distinct from old.cover_contact_id) then
    if not exists (select 1 from public.contacts c
                   where c.id = new.cover_contact_id and c.business_id = new.business_id) then
      raise exception 'The person covering is not in this church';
    end if;
  end if;
  if new.to_contact_id is not null
     and (tg_op = 'INSERT' or new.to_contact_id is distinct from old.to_contact_id) then
    if not exists (select 1 from public.contacts c
                   where c.id = new.to_contact_id and c.business_id = new.business_id) then
      raise exception 'The person it goes to is not in this church';
    end if;
  end if;
  if new.decided_by_contact_id is not null
     and (tg_op = 'INSERT' or new.decided_by_contact_id is distinct from old.decided_by_contact_id) then
    if not exists (select 1 from public.contacts c
                   where c.id = new.decided_by_contact_id and c.business_id = new.business_id) then
      raise exception 'The person who answered is not in this church';
    end if;
  end if;
  if new.department_id is not null
     and (tg_op = 'INSERT' or new.department_id is distinct from old.department_id) then
    if not exists (select 1 from public.church_departments d
                   where d.id = new.department_id and d.business_id = new.business_id) then
      raise exception 'That department is not in this church';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_away_asks_same_business() from public, anon, authenticated;

drop trigger if exists church_away_asks_same_business on public.church_away_asks;
create trigger church_away_asks_same_business
  before insert or update of business_id, contact_id, cover_contact_id, to_contact_id,
                             decided_by_contact_id, department_id
  on public.church_away_asks
  for each row execute function public.church_away_asks_same_business();

-- A person's asks, newest first; what waits for a login's or a person's yes;
-- the calendar's and the scheduler's window; the sweep's two reads.
create index if not exists church_away_asks_mine
  on public.church_away_asks (business_id, contact_id, starts_on desc);
create index if not exists church_away_asks_to_login
  on public.church_away_asks (business_id, to_user_id) where state = 'asked';
create index if not exists church_away_asks_to_person
  on public.church_away_asks (business_id, to_contact_id) where state = 'asked';
create index if not exists church_away_asks_window
  on public.church_away_asks (business_id, ends_on) where state in ('asked', 'yes');
create index if not exists church_away_asks_untold
  on public.church_away_asks (created_at) where told_at is null;
create index if not exists church_away_asks_answer_untold
  on public.church_away_asks (decided_at) where decided_at is not null and answer_told_at is null;
-- A double press never makes two asks for the same days.
create unique index if not exists church_away_asks_one_open
  on public.church_away_asks (business_id, contact_id, starts_on, ends_on) where state = 'asked';

-- ─── serve_away: the fact names its ask ─────────────────────────────────

alter table public.serve_away
  add column if not exists ask_id uuid,
  add column if not exists kind text;

-- An ask only ever goes with its person or its church, and their facts go
-- with them by serve_away's own keys; "set null" is for an ask deleted by
-- hand, whose fact then stays as a plain away date.
do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'serve_away_ask_id_fkey' and conrelid = 'public.serve_away'::regclass) then
    alter table public.serve_away
      add constraint serve_away_ask_id_fkey foreign key (ask_id)
        references public.church_away_asks(id) on delete set null not valid;
  end if;
  if not exists (select 1 from pg_constraint
                 where conname = 'serve_away_kind' and conrelid = 'public.serve_away'::regclass) then
    alter table public.serve_away
      add constraint serve_away_kind
        check (kind is null or kind in ('time_off', 'commitment', 'cant')) not valid;
  end if;
end $$;

-- One fact an ask: a second yes, or a retry, writes nothing.
create unique index if not exists serve_away_one_per_ask
  on public.serve_away (ask_id) where ask_id is not null;

-- The ask a fact names is the same church's and the same person's: checked
-- when a fact is written with an ask, and when a fact that has one is moved.
create or replace function public.serve_away_ask_guard() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.ask_id is not null then
    if not exists (select 1 from public.church_away_asks a
                   where a.id = new.ask_id and a.business_id = new.business_id
                     and a.contact_id = new.contact_id) then
      raise exception 'That ask is not this person''s';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.serve_away_ask_guard() from public, anon, authenticated;

drop trigger if exists serve_away_ask_guard on public.serve_away;
create trigger serve_away_ask_guard
  before insert or update of ask_id, business_id, contact_id on public.serve_away
  for each row execute function public.serve_away_ask_guard();

-- ─── One decision, in one transaction ───────────────────────────────────

-- yes / no: only an ask still waiting. withdrawn: one waiting, or one already
-- said yes to (its fact goes). {"changed": false, "ask": …} when it had
-- already moved on; null when there is no such ask at this church. It never
-- makes a fact again for an ask that is already a yes: a fact that is gone
-- was taken off by its person.
create or replace function public.church_away_settle(
  p_business_id uuid, p_ask_id uuid, p_state text,
  p_by_user uuid default null, p_by_contact uuid default null, p_note text default null)
returns jsonb
language plpgsql set search_path = public as $$
declare
  v public.church_away_asks;
begin
  if p_state is null or p_state not in ('yes', 'no', 'withdrawn') then
    raise exception 'An ask is answered yes or no, or withdrawn';
  end if;
  select * into v from public.church_away_asks a
   where a.id = p_ask_id and a.business_id = p_business_id for update;
  if not found then
    return null;
  end if;
  if (p_state in ('yes', 'no') and v.state <> 'asked')
     or (p_state = 'withdrawn' and v.state not in ('asked', 'yes')) then
    return jsonb_build_object('changed', false, 'ask', to_jsonb(v));
  end if;
  if p_state = 'withdrawn' then
    update public.church_away_asks a
       set state = 'withdrawn', withdrawn_at = clock_timestamp(), updated_at = clock_timestamp()
     where a.id = v.id returning * into v;
    delete from public.serve_away s where s.ask_id = v.id and s.business_id = v.business_id;
  else
    update public.church_away_asks a
       set state = p_state, decided_at = clock_timestamp(), decided_by_user_id = p_by_user,
           decided_by_contact_id = p_by_contact, decided_note = nullif(btrim(left(coalesce(p_note, ''), 300)), ''),
           answer_told_at = null, updated_at = clock_timestamp()
     where a.id = v.id returning * into v;
    if p_state = 'yes' then
      insert into public.serve_away(business_id, contact_id, starts_on, ends_on, note, ask_id, kind)
      values (v.business_id, v.contact_id, v.starts_on, v.ends_on, '', v.id, v.kind)
      on conflict (ask_id) where ask_id is not null do nothing;
    end if;
  end if;
  return jsonb_build_object('changed', true, 'ask', to_jsonb(v));
end $$;
revoke all on function public.church_away_settle(uuid, uuid, text, uuid, uuid, text) from public, anon, authenticated;
grant execute on function public.church_away_settle(uuid, uuid, text, uuid, uuid, text) to service_role;

-- ─── Something that repeats ─────────────────────────────────────────────

create table if not exists public.church_away_commitments(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  label text not null check (char_length(btrim(label)) between 1 and 80),
  weekday smallint not null check (weekday between 1 and 7),          -- 1 Monday … 7 Sunday
  pattern text not null check (pattern in ('weekly', 'every_other', 'month_nth')),
  nth smallint check (nth between 1 and 5),                           -- 5 = the last one of the month
  starts_on date not null,
  until_on date,
  told_at timestamptz,
  created_at timestamptz not null default now(),
  constraint church_away_commitments_nth check ((pattern = 'month_nth') = (nth is not null)),
  constraint church_away_commitments_until check (until_on is null or until_on >= starts_on),
  -- every other week counts from starts_on, so starts_on is one of its days
  constraint church_away_commitments_anchor
    check (pattern <> 'every_other' or extract(isodow from starts_on) = weekday)
);
create index if not exists church_away_commitments_by_person
  on public.church_away_commitments (business_id, contact_id);

-- The person on the add list or the remove list, and the person a commitment
-- is, are the church's own.
create or replace function public.church_schedule_person_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_op = 'UPDATE' then
    if new.business_id <> old.business_id then
      raise exception 'It stays with its church';
    end if;
  end if;
  if tg_op = 'INSERT' or new.contact_id is distinct from old.contact_id then
    if not exists (select 1 from public.contacts c
                   where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this church';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_schedule_person_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['church_away_commitments', 'church_schedule_people'] loop
    execute format('drop trigger if exists church_schedule_person_same_business on public.%I', t);
    execute format('create trigger church_schedule_person_same_business
      before insert or update of business_id, contact_id on public.%I
      for each row execute function public.church_schedule_person_same_business()', t);
  end loop;
  foreach t in array array['church_schedule_settings', 'church_schedule_people', 'church_away_asks',
                           'church_away_commitments'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

comment on table public.church_away_asks is
  'The leaders schedule (church_schedule.py): a leader asks to be away; the person over them says yes or not this one. A yes writes one serve_away row naming the ask (church_away_settle). Unrelated to church_map_asks and member_asks. Server-only (RLS on, no policies).';
comment on column public.church_away_asks.reason is
  'Private. Read only by the asker, whoever it went to, the owner and whoever oversees the office. Never copied to serve_away.';
comment on column public.church_away_asks.made_by is
  'The login that entered it in the office app (their own, or for someone). Null: the person asked in the member app.';
comment on column public.church_away_asks.grp is
  'The schedule they were on when they asked: leaders, office, or volunteers (step 2).';
comment on column public.church_away_asks.to_user_id is
  'The login it went to (church_over.above). Never set with to_contact_id. Both null: nobody is over them (the owner asked), or that login is gone and the owner answers.';
comment on column public.church_away_asks.to_contact_id is
  'The person it went to (the ask''s own church''s). Never set with to_user_id.';
comment on column public.church_away_asks.state is
  'asked | yes | no | withdrawn. A yes with nobody in decided_by needed no yes: can''t make it, or nobody is over them.';
comment on column public.church_away_asks.flags is
  'short_notice (inside the church''s notice days when asked). Step 2: over_limit, protected_day, pair, serving (a volunteer who already said yes to serve one of the days).';
comment on column public.church_away_asks.told_at is
  'Whoever it went to was told (claimed before the send, let go if it fails).';
comment on column public.church_away_asks.answer_told_at is
  'The asker was told the answer (claimed before the send).';
comment on column public.serve_away.ask_id is
  'The leaders schedule: the ask this away fact came from. Null = an away date added the way it always was.';
comment on column public.serve_away.kind is
  'The leaders schedule: the ask''s kind (time_off, commitment, cant). Null = a plain away date.';
comment on table public.church_away_commitments is
  'The leaders schedule: something that repeats (weekly, every other week from starts_on, or the nth weekday of the month). Server-only.';
comment on table public.church_schedule_people is
  'The leaders schedule: the church''s add list (with the group) and remove list, over who its own data puts on the schedule. Server-only.';
comment on table public.church_schedule_settings is
  'The leaders schedule: the church''s notice days (14 by default). Server-only.';

commit;

notify pgrst, 'reload schema';

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--     from pg_class c where c.relnamespace = 'public'::regnamespace
--      and c.relname in ('church_schedule_settings','church_schedule_people','church_away_asks','church_away_commitments');
--   -- 4 rows: true, 0, false, false
--   select conname, convalidated from pg_constraint
--    where conrelid = 'public.serve_away'::regclass and conname in ('serve_away_ask_id_fkey','serve_away_kind');
--   -- 2 rows, convalidated false (validate later: alter table public.serve_away validate constraint <name>;)
--   select has_function_privilege('authenticated', f, 'execute') as browser_runs,
--          has_function_privilege('anon', f, 'execute') as anon_runs,
--          has_function_privilege('service_role', f, 'execute') as server_runs
--     from (select 'public.church_away_settle(uuid, uuid, text, uuid, uuid, text)'::regprocedure as f) x;
--   -- false, false, true
--   select count(*) from serve_away where ask_id is not null or kind is not null;
--   -- 0
--
-- Rollback (loses every ask and commitment; away facts stay as plain away dates):
--   drop function if exists public.church_away_settle(uuid, uuid, text, uuid, uuid, text);
--   drop trigger if exists serve_away_ask_guard on public.serve_away;
--   drop function if exists public.serve_away_ask_guard();
--   drop index if exists public.serve_away_one_per_ask;
--   alter table public.serve_away drop column if exists ask_id, drop column if exists kind;
--   drop table if exists public.church_away_commitments, public.church_away_asks,
--                        public.church_schedule_people, public.church_schedule_settings;
--   drop function if exists public.church_away_asks_same_business();
--   drop function if exists public.church_schedule_person_same_business();
--   notify pgrst, 'reload schema';

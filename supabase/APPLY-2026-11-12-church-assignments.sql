-- APPLY-2026-11-12-church-assignments.sql
--
-- Church assignments (church_assignments.py, church_over.py, church_startup.py,
-- church_work_checks.py; docs/CHURCH_ASSIGNMENTS.md). Kevin, 2026-11-11: "lets
-- build what is missing", "we also need to allow for the admin to pick days for
-- work load that works for them", "we also need to allow for Jessica to be able
-- to hand out assignments to each of them as well", and "this needs to be a way
-- for churches to set this up in a general sense when they establish leaders
-- over people."
--
-- An assignment IS a task (public.tasks), handed to one login (assigned_to) or
-- one of the church's people (assigned_contact_id); tasks_handed_to_one already
-- holds that. Everything that tells, escalates and shows a handed task stays
-- the one list. The new columns only add what an assignment has that a task
-- didn't:
--
--   duty                  the church_duties.CATALOG key (or a leader's switch,
--                         lead / oversee) it belongs to; null = none
--   done_when             what done means, in the church's words (300 at most)
--   check_key             a church_work_checks key that can tick it off
--   startup_key           the church_startup template it came from; null =
--                         handed by hand
--   stuck_note, stuck_at  why it's stuck (500 at most) and since when; both
--                         null = not stuck
--   raised_at             when it was sent up to whoever is over the one who
--                         sent it
--   raised_to             the login it was sent up to, or
--   raised_to_contact_id  the person (never both: tasks_raised_to_one; always
--                         the task's own church's: tasks_raised_same_business)
--   raised_by             the login that sent it up (named in the email)
--   raised_told_at        the sweep told them (claimed before the send)
--   checked_at            a check ticked it off (status done, done by no one)
--
-- tasks_startup_once: a start-up item is made once per person per template.
--
-- church_duty_days (server-only: RLS on, no policies, browser roles revoked):
-- the day a login picked for one of its duties. A login that's deleted takes
-- its rows; a church that goes takes everything.
--
-- Additive, one transaction, safe to run twice, nothing dropped. Apply before
-- the code that reads it: until then the routes answer 503 for the platform
-- owner's church (the switch's default) and the sweep's reads fail quietly.
--
-- The lock: adding columns, constraints and indexes to tasks holds ACCESS
-- EXCLUSIVE on it until commit, so the file keeps that short. Every new
-- column is null on every row that exists, so there is nothing old to check:
-- the two CHECKs and the three foreign keys are added NOT VALID (no scan of
-- the table under the lock), and every row written from now on is still
-- checked. Each can be validated later, under a lighter lock, with
--   alter table public.tasks validate constraint <name>;
-- The three indexes are built here as they are: tasks is small on this
-- platform.
begin;

set local lock_timeout = '5s';

alter table public.tasks
  add column if not exists duty text,
  add column if not exists done_when text,
  add column if not exists check_key text,
  add column if not exists startup_key text,
  add column if not exists stuck_note text,
  add column if not exists stuck_at timestamptz,
  add column if not exists raised_at timestamptz,
  add column if not exists raised_to uuid,
  add column if not exists raised_to_contact_id uuid,
  add column if not exists raised_by uuid,
  add column if not exists raised_told_at timestamptz,
  add column if not exists checked_at timestamptz;

do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'tasks_raised_to_fkey' and conrelid = 'public.tasks'::regclass) then
    alter table public.tasks
      add constraint tasks_raised_to_fkey foreign key (raised_to)
        references auth.users(id) on delete set null not valid;
  end if;
  if not exists (select 1 from pg_constraint
                 where conname = 'tasks_raised_to_contact_id_fkey' and conrelid = 'public.tasks'::regclass) then
    alter table public.tasks
      add constraint tasks_raised_to_contact_id_fkey foreign key (raised_to_contact_id)
        references public.contacts(id) on delete set null not valid;
  end if;
  if not exists (select 1 from pg_constraint
                 where conname = 'tasks_raised_by_fkey' and conrelid = 'public.tasks'::regclass) then
    alter table public.tasks
      add constraint tasks_raised_by_fkey foreign key (raised_by)
        references auth.users(id) on delete set null not valid;
  end if;
  if not exists (select 1 from pg_constraint
                 where conname = 'tasks_raised_to_one' and conrelid = 'public.tasks'::regclass) then
    alter table public.tasks
      add constraint tasks_raised_to_one check (raised_to is null or raised_to_contact_id is null) not valid;
  end if;
  if not exists (select 1 from pg_constraint
                 where conname = 'tasks_assignment_lengths' and conrelid = 'public.tasks'::regclass) then
    alter table public.tasks
      add constraint tasks_assignment_lengths check (
        (done_when is null or char_length(done_when) <= 300)
        and (stuck_note is null or char_length(stuck_note) <= 500)
        and (duty is null or duty ~ '^[a-z][a-z0-9_]{1,39}$')
        and (check_key is null or check_key ~ '^[a-z][a-z0-9_]{1,39}$')
        and (startup_key is null or startup_key ~ '^[a-z][a-z0-9_.]{1,79}$')) not valid;
  end if;
end $$;

-- The person a stuck item was sent up to is the task's own church's,
-- whatever the caller passes (as tasks_leader_same_business holds the leader).
create or replace function public.tasks_raised_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.raised_to_contact_id is not null
     and (tg_op = 'INSERT' or new.raised_to_contact_id is distinct from old.raised_to_contact_id
          or new.business_id is distinct from old.business_id)
     and not exists (select 1 from public.contacts c
                     where c.id = new.raised_to_contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  return new;
end $$;

drop trigger if exists tasks_raised_same_business on public.tasks;
create trigger tasks_raised_same_business
  before insert or update of raised_to_contact_id, business_id on public.tasks
  for each row execute function public.tasks_raised_same_business();

revoke all on function public.tasks_raised_same_business() from public, anon, authenticated;

-- A start-up item, once per person per template.
create unique index if not exists tasks_startup_once
  on public.tasks (business_id, coalesce(assigned_to, assigned_contact_id), startup_key)
  where startup_key is not null;

-- The hourly sweep's two reads: what was sent up and not told, and what a
-- check can tick off.
create index if not exists tasks_raised_untold
  on public.tasks (raised_at)
  where raised_at is not null and raised_told_at is null and status <> 'done';
create index if not exists tasks_check_open
  on public.tasks (business_id)
  where check_key is not null and status <> 'done';

comment on column public.tasks.duty is
  'Church assignments (church_assignments.py): the church_duties.CATALOG key, or a leader''s switch (lead, oversee), it belongs to. Null = none.';
comment on column public.tasks.done_when is
  'Church assignments: what done means, in the church''s words (300 at most).';
comment on column public.tasks.check_key is
  'Church assignments: a church_work_checks key that can tick it off (status done, checked_at set, done by no one).';
comment on column public.tasks.startup_key is
  'Church assignments: the church_startup template a first-assignment item came from. Null = handed by hand. Unique per person (tasks_startup_once).';
comment on column public.tasks.stuck_note is
  'Church assignments: why it''s stuck (500 at most). Null with stuck_at null = not stuck.';
comment on column public.tasks.stuck_at is
  'Church assignments: when it was marked stuck. Null = not stuck.';
comment on column public.tasks.raised_at is
  'Church assignments: when it was sent up to whoever is over the login that sent it (church_over.above).';
comment on column public.tasks.raised_to is
  'Church assignments: the login it was sent up to. Never set with raised_to_contact_id.';
comment on column public.tasks.raised_to_contact_id is
  'Church assignments: the person (the task''s own church''s) it was sent up to. Never set with raised_to.';
comment on column public.tasks.raised_by is
  'Church assignments: the login that sent it up, named in the email to whoever it went to.';
comment on column public.tasks.raised_told_at is
  'Church assignments sweep: when whoever it was sent up to was told (claimed before the send, let go if it fails).';
comment on column public.tasks.checked_at is
  'Church assignments: when a check ticked it off (church_work_checks). Null for one a person marked done.';

-- The day a login picked for one of its duties (church_my_week.rhythm, the team
-- page and the Monday roll-up read it).
create table if not exists public.church_duty_days(
  business_id uuid not null references public.businesses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  duty text not null check (duty ~ '^[a-z][a-z0-9_]{1,39}$'),
  day text not null check (day in ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')),
  set_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  primary key (business_id, user_id, duty)
);

alter table public.church_duty_days enable row level security;
revoke all on public.church_duty_days from anon, authenticated;
grant all on public.church_duty_days to service_role;

comment on table public.church_duty_days is
  'Church assignments (church_assignments.py): the day a login picked for one of its duties. Server-only (RLS on, no policies). A Sunday job never has a row.';

commit;

-- Check:
--   select count(*) from information_schema.columns
--    where table_schema = 'public' and table_name = 'tasks'
--      and column_name in ('duty','done_when','check_key','startup_key','stuck_note','stuck_at','raised_at',
--                          'raised_to','raised_to_contact_id','raised_by','raised_told_at','checked_at');
--   -- 12
--   select count(*) from pg_indexes
--    where schemaname = 'public' and indexname in ('tasks_startup_once','tasks_raised_untold','tasks_check_open');
--   -- 3
--   select conname, convalidated from pg_constraint
--    where conrelid = 'public.tasks'::regclass
--      and conname in ('tasks_raised_to_fkey','tasks_raised_to_contact_id_fkey','tasks_raised_by_fkey',
--                      'tasks_raised_to_one','tasks_assignment_lengths');
--   -- 5 rows, each convalidated false (NOT VALID: enforced on every new write)
--   select c.relrowsecurity, (select count(*) from pg_policies p where p.schemaname = 'public'
--                             and p.tablename = 'church_duty_days') as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads
--     from pg_class c where c.oid = 'public.church_duty_days'::regclass;
--   -- true, 0, false
--
-- Rollback (loses every pick, and every assignment's stuck, sent-up and start-up marks):
--   drop table if exists public.church_duty_days;
--   drop trigger if exists tasks_raised_same_business on public.tasks;
--   drop function if exists public.tasks_raised_same_business();
--   drop index if exists public.tasks_startup_once, public.tasks_raised_untold, public.tasks_check_open;
--   alter table public.tasks drop constraint if exists tasks_raised_to_one,
--     drop constraint if exists tasks_assignment_lengths,
--     drop column if exists duty, drop column if exists done_when, drop column if exists check_key,
--     drop column if exists startup_key, drop column if exists stuck_note, drop column if exists stuck_at,
--     drop column if exists raised_at, drop column if exists raised_to, drop column if exists raised_to_contact_id,
--     drop column if exists raised_by, drop column if exists raised_told_at, drop column if exists checked_at;

-- APPLY-2026-11-12-church-lead-assignments.sql
--
-- A leader's assignments on the member app's Lead tab (member_portal_assign.py;
-- docs/CHURCH_ASSIGNMENTS.md, PR C2). Kevin, 2026-11-12, on the phone mock:
-- "phone view idea is good. we can move forward with that."
--
-- Leaders don't get office logins: a leader over others gives an assignment,
-- starts a first assignment and sends a stuck one up from the member app, as
-- one of the church's people. tasks.handed_by and tasks.raised_by name logins
-- (auth.users), so a leader's own hand couldn't be recorded and the page and
-- the emails would have said "the church office". Two nullable columns say who:
--
--   handed_by_contact_id  the person (one of the task's own church's people)
--                         who handed it out; handed_by stays the login's, and a
--                         login's later hand (its own stamp) is read first
--   raised_by_contact_id  the person who sent it up; raised_by stays the
--                         login's, and the server writes only one of the two
--
-- Both go with the person (on delete set null) and are the task's own church's
-- (tasks_people_same_business). The foreign keys go in NOT VALID: every new
-- column is null on every row that exists, so nothing old is scanned under the
-- lock, and every row written from now on is still checked (validate later
-- with `alter table public.tasks validate constraint <name>` if wanted).
--
-- Additive, one transaction, safe to run twice, nothing dropped. Apply BEFORE
-- the code that reads it merges: church_assignments reads both columns on every
-- assignment read, so until this file is applied the assignment routes and the
-- Lead tab's assignments answer 503 for the churches the switch is open to.
begin;

set local lock_timeout = '5s';

alter table public.tasks
  add column if not exists handed_by_contact_id uuid,
  add column if not exists raised_by_contact_id uuid;

do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'tasks_handed_by_contact_id_fkey' and conrelid = 'public.tasks'::regclass) then
    alter table public.tasks
      add constraint tasks_handed_by_contact_id_fkey foreign key (handed_by_contact_id)
        references public.contacts(id) on delete set null not valid;
  end if;
  if not exists (select 1 from pg_constraint
                 where conname = 'tasks_raised_by_contact_id_fkey' and conrelid = 'public.tasks'::regclass) then
    alter table public.tasks
      add constraint tasks_raised_by_contact_id_fkey foreign key (raised_by_contact_id)
        references public.contacts(id) on delete set null not valid;
  end if;
end $$;

-- The person who handed it out, and the person who sent it up, are the task's
-- own church's, whatever the caller passes.
create or replace function public.tasks_people_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.handed_by_contact_id is not null
     and (tg_op = 'INSERT' or new.handed_by_contact_id is distinct from old.handed_by_contact_id
          or new.business_id is distinct from old.business_id)
     and not exists (select 1 from public.contacts c
                     where c.id = new.handed_by_contact_id and c.business_id = new.business_id) then
    raise exception 'The person who handed it out is not in this church';
  end if;
  if new.raised_by_contact_id is not null
     and (tg_op = 'INSERT' or new.raised_by_contact_id is distinct from old.raised_by_contact_id
          or new.business_id is distinct from old.business_id)
     and not exists (select 1 from public.contacts c
                     where c.id = new.raised_by_contact_id and c.business_id = new.business_id) then
    raise exception 'The person who sent it up is not in this church';
  end if;
  return new;
end $$;

drop trigger if exists tasks_people_same_business on public.tasks;
create trigger tasks_people_same_business
  before insert or update of handed_by_contact_id, raised_by_contact_id, business_id on public.tasks
  for each row execute function public.tasks_people_same_business();

revoke all on function public.tasks_people_same_business() from public, anon, authenticated;

comment on column public.tasks.handed_by_contact_id is
  'Church assignments (member_portal_assign.py): the person (this church''s) who handed it out from the member app. handed_by, a login''s, is read first.';
comment on column public.tasks.raised_by_contact_id is
  'Church assignments: the person (this church''s) who sent it up from the member app, named to whoever it went to. raised_by names a login.';

commit;

-- Check:
--   select count(*) from information_schema.columns
--    where table_schema = 'public' and table_name = 'tasks'
--      and column_name in ('handed_by_contact_id', 'raised_by_contact_id');
--   -- 2
--   select conname, convalidated from pg_constraint
--    where conrelid = 'public.tasks'::regclass
--      and conname in ('tasks_handed_by_contact_id_fkey', 'tasks_raised_by_contact_id_fkey');
--   -- 2 rows, each convalidated false (NOT VALID: enforced on every new write)
--   select count(*) from pg_trigger where tgname = 'tasks_people_same_business' and not tgisinternal;
--   -- 1
--
-- Rollback (loses who handed out or sent up what, from the member app):
--   drop trigger if exists tasks_people_same_business on public.tasks;
--   drop function if exists public.tasks_people_same_business();
--   alter table public.tasks drop constraint if exists tasks_handed_by_contact_id_fkey,
--     drop constraint if exists tasks_raised_by_contact_id_fkey,
--     drop column if exists handed_by_contact_id, drop column if exists raised_by_contact_id;

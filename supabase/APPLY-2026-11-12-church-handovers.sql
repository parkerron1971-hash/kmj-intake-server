-- APPLY-2026-11-12-church-handovers.sql
--
-- From the office (church_handovers.py; docs/CHURCH_ASSIGNMENTS.md, PR C1).
-- Kevin, 2026-11-12: "admins can not give work to elders and pastors but they
-- can give them things that is related to their area that they need for them
-- to have."
--
-- A hand-over is something an office login (the owner, an Admin, a Manager)
-- sends one of the church's leaders for their area: what it is, a note, an
-- https link, the day it's for, the department it's for. It is never a task:
-- never late, never escalated, never judged. The leader sees it in the member
-- app's Lead tab (or My week, when their person is a login) and taps Got it
-- (seen_at); the sender sees Seen or Not yet seen. The hourly sweep tells
-- each person by one email for what arrived (told_at, claimed before the send).
--
-- church_handovers (server-only: RLS on, no policies, browser roles revoked):
--   contact_id     the leader it's for: one of the church's own people
--                  (church_handovers_same_business); goes with the person
--   sent_by        the login that sent it (named to the leader); a login
--                  that's deleted leaves the row, sent by "the church office"
--   title          140 at most, never empty
--   note           1000 at most
--   link           https only, 500 at most
--   for_date       the day it's for, or none
--   department_id  the department it's for (the church's own), or none; a
--                  department that's deleted leaves the row
--   seen_at        Got it; told_at  the sweep told them
-- A church that goes takes everything.
--
-- New table only: one transaction, safe to run twice, nothing dropped. Apply
-- before the code that reads it: until then the routes answer 503 for the
-- platform owner's church (the switch's default) and the sweep's read fails
-- quietly.
begin;

set local lock_timeout = '5s';

create table if not exists public.church_handovers(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  sent_by uuid references auth.users(id) on delete set null,
  title text not null check (char_length(btrim(title)) between 1 and 140),
  note text check (note is null or char_length(note) <= 1000),
  link text check (link is null or (char_length(link) <= 500 and link ~ '^https://[^[:space:]]+$')),
  for_date date,
  department_id uuid references public.church_departments(id) on delete set null,
  created_at timestamptz not null default now(),
  seen_at timestamptz,
  told_at timestamptz
);

-- The person (and the department) are the hand-over's own church's, whatever
-- the caller passes.
create or replace function public.church_handovers_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.contacts c
                 where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  if new.department_id is not null
     and not exists (select 1 from public.church_departments d
                     where d.id = new.department_id and d.business_id = new.business_id) then
    raise exception 'That department is not in this church';
  end if;
  return new;
end $$;

drop trigger if exists church_handovers_same_business on public.church_handovers;
create trigger church_handovers_same_business
  before insert or update of contact_id, department_id, business_id on public.church_handovers
  for each row execute function public.church_handovers_same_business();

revoke all on function public.church_handovers_same_business() from public, anon, authenticated;

-- A leader's list (theirs, newest first), what a login sent, and the sweep's
-- untold.
create index if not exists church_handovers_for
  on public.church_handovers (business_id, contact_id, created_at desc);
create index if not exists church_handovers_sent
  on public.church_handovers (business_id, sent_by, created_at desc);
create index if not exists church_handovers_untold
  on public.church_handovers (created_at)
  where told_at is null;

alter table public.church_handovers enable row level security;
revoke all on public.church_handovers from anon, authenticated;
grant all on public.church_handovers to service_role;

comment on table public.church_handovers is
  'From the office (church_handovers.py): something an office login sent one of the church''s leaders for their area. Never a task: never late, never escalated. Server-only (RLS on, no policies).';
comment on column public.church_handovers.sent_by is
  'The login that sent it, named to the leader. Null once that login is deleted (said as the church office).';
comment on column public.church_handovers.seen_at is
  'Got it: when the leader marked it seen. The sender sees Seen or Not yet seen.';
comment on column public.church_handovers.told_at is
  'The hourly sweep emailed the leader (claimed before the send, let go if it fails).';

commit;

-- Check:
--   select c.relrowsecurity, (select count(*) from pg_policies p where p.schemaname = 'public'
--                             and p.tablename = 'church_handovers') as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--     from pg_class c where c.oid = 'public.church_handovers'::regclass;
--   -- true, 0, false, false
--   select count(*) from pg_indexes where schemaname = 'public'
--      and indexname in ('church_handovers_for', 'church_handovers_sent', 'church_handovers_untold');
--   -- 3
--   select count(*) from pg_trigger where tgname = 'church_handovers_same_business' and not tgisinternal;
--   -- 1
--
-- Rollback (loses every hand-over):
--   drop table if exists public.church_handovers;
--   drop function if exists public.church_handovers_same_business();

-- APPLY-2026-11-18-care-login-due.sql
--
-- A Prayer & care request handed to an office login gets a heads-up and a
-- due time (care_handoff.py; private_care.update_request). Kevin,
-- 2026-11-18: "build the heads-up and due time for logins". Until now a
-- hand-off to a login only showed on that login's My week: nobody was told,
-- nothing was due, and nobody heard when it waited. A hand-off to the
-- prayer team already had all three (leader_told_at, leader_due_at,
-- leader_late_level); this gives a login's hand-off the same.
--
-- ministry_care_requests gets:
--   assigned_due_at      when the login's first step is due: a day after
--                        it was handed to them
--   assigned_told_at     when they got the heads-up (a push to the office
--                        app and an email; never the request's words, never
--                        the person's name). The sweep claims it before it
--                        sends, so it goes once
--   assigned_acted_at    their first step: a note, "I'm on it", marked
--                        prayed or done. Nothing is late after it
--   assigned_late_level  how far it climbed while it waited: 1 they were
--                        reminded when it was due, 2 a day late the one who
--                        handed it to them heard, 3 three days late the
--                        office was asked to hand it to someone else
--
-- Requests already with a login count as told (assigned_told_at = when
-- they were handed on) and have no due time, so applying this sends nobody
-- anything about an old hand-off. Only hand-offs from now on are timed.
--
-- The code reads without these columns until this is applied (hand-offs
-- work as before, untimed), so the order doesn't matter.
--
-- Additive: one transaction, safe to run twice, nothing dropped.
begin;

set local lock_timeout = '5s';

alter table public.ministry_care_requests
  add column if not exists assigned_due_at timestamptz,
  add column if not exists assigned_told_at timestamptz,
  add column if not exists assigned_acted_at timestamptz,
  add column if not exists assigned_late_level smallint not null default 0;

do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'ministry_care_requests_assigned_late_level_check'
                   and conrelid = 'public.ministry_care_requests'::regclass) then
    alter table public.ministry_care_requests
      add constraint ministry_care_requests_assigned_late_level_check
      check (assigned_late_level between 0 and 3);
  end if;
end $$;

-- Old hand-offs: told already, never due.
update public.ministry_care_requests
   set assigned_told_at = coalesce(assigned_at, now())
 where assigned_to is not null
   and assigned_told_at is null
   and assigned_due_at is null;

-- The sweep's two reads: untold hand-offs, and the ones still waiting on a
-- first step.
create index if not exists ministry_care_requests_login_untold
  on public.ministry_care_requests (assigned_at)
  where assigned_to is not null and assigned_told_at is null;

create index if not exists ministry_care_requests_login_due
  on public.ministry_care_requests (assigned_due_at)
  where assigned_to is not null and assigned_acted_at is null and assigned_late_level < 3;

comment on column public.ministry_care_requests.assigned_due_at is
  'care_handoff.py: when the login it was handed to owes a first step (a day after the hand-off). Null = untimed.';
comment on column public.ministry_care_requests.assigned_told_at is
  'care_handoff.py: when that login got the heads-up (claimed before sending, so once). Never carries the request.';
comment on column public.ministry_care_requests.assigned_acted_at is
  'care_handoff.py: that login''s first step (a note, I''m on it, prayed, done). Nothing is late after it.';
comment on column public.ministry_care_requests.assigned_late_level is
  'care_handoff.py: 0 on time, 1 reminded, 2 the one who handed it heard, 3 the office was asked to hand it on.';

commit;

notify pgrst, 'reload schema';

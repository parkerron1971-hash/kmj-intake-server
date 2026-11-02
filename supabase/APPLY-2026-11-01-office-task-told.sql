-- APPLY-2026-11-01-office-task-told.sql
--
-- A task handed to an office login reaches them (church_office_tasks.py;
-- Love City's office checkup, Kevin 2026-11-01). A task handed to a login
-- (tasks.assigned_to, APPLY-2026-10-26-task-hand-off.sql) landed in their
-- My week and nowhere else: no email, no push, and a late one went to no
-- one. The hourly sweep now tells the login once, and a late one goes up
-- once. It needs:
--
--   seat_told_at        the login was told it's theirs (claimed before the
--                       send, let go if the send fails)
--   seat_late_told_at   whoever handed it, and the Executive Pastor, were
--                       told it's past due (once, in the church's morning)
--   handed_by           now stamped for a hand-off to a login as well as to
--                       a leader (it was the leader's only), so the sweep can
--                       name who handed it and tell them when it's late
--
-- A new login is told afresh; a new due date can be late again.
-- Every task already handed to a login counts as told, so only hand-offs
-- from now on are emailed (nothing floods anyone's inbox on the first run).
--
-- Additive and safe to run twice. Apply before the code that reads it.

begin;

alter table public.tasks
  add column if not exists seat_told_at timestamptz,
  add column if not exists seat_late_told_at timestamptz;

-- Who handed it: a leader's hand-off as before, and a login's too.
create or replace function public.tasks_handed_by_stamp() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.assigned_contact_id is null and new.assigned_to is null then
    new.handed_by := null;
  elsif tg_op = 'INSERT'
        or new.assigned_contact_id is distinct from old.assigned_contact_id
        or new.assigned_to is distinct from old.assigned_to then
    new.handed_by := coalesce(auth.uid(), new.handed_by);
  elsif new.handed_by is not null then
    -- Never moved to someone else by hand. Cleared is allowed: a login
    -- that's deleted clears it (on delete set null).
    new.handed_by := old.handed_by;
  end if;
  return new;
end $$;

drop trigger if exists tasks_handed_by_stamp on public.tasks;
create trigger tasks_handed_by_stamp
  before insert or update of assigned_contact_id, assigned_to, handed_by on public.tasks
  for each row execute function public.tasks_handed_by_stamp();

-- A new login hears afresh; a new due date can be late again.
create or replace function public.tasks_seat_told_reset() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.assigned_to is distinct from old.assigned_to then
    new.seat_told_at := null;
    new.seat_late_told_at := null;
  elsif new.due_date is distinct from old.due_date then
    new.seat_late_told_at := null;
  end if;
  return new;
end $$;

drop trigger if exists tasks_seat_told_reset on public.tasks;
create trigger tasks_seat_told_reset
  before update of assigned_to, due_date on public.tasks
  for each row execute function public.tasks_seat_told_reset();

revoke all on function public.tasks_seat_told_reset() from public, anon, authenticated;

-- What's already handed to a login counts as told.
update public.tasks set seat_told_at = now()
  where assigned_to is not null and seat_told_at is null;

-- The sweep's two reads.
create index if not exists tasks_seat_untold
  on public.tasks (created_at)
  where assigned_to is not null and seat_told_at is null and status <> 'done';
create index if not exists tasks_seat_late
  on public.tasks (due_date)
  where assigned_to is not null and seat_late_told_at is null and status <> 'done';

comment on column public.tasks.seat_told_at is
  'church_office_tasks sweep: when the login this task was handed to (assigned_to) was told it is theirs (claimed before the send). Cleared when it is handed to another login.';
comment on column public.tasks.seat_late_told_at is
  'church_office_tasks sweep: when whoever handed it and the Executive Pastor were told it is past due. Cleared on a new login or a new due date.';

commit;

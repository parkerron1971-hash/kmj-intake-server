-- APPLY-2026-10-27-task-handed-by.sql
--
-- Who handed a leader a task (church_leader_tasks.py; Kevin 2026-10-27, the
-- open item after "My tasks for leaders"). A task handed to a leader
-- (tasks.assigned_contact_id) didn't record which office login handed it, so
-- when it ran late and the leader answers to no one (a group leader with no
-- role above them) nobody was told, and the leader's page said "From the
-- church office".
--
--   handed_by  the login (auth.users.id) that handed the task to its leader.
--              Set by the database, not the caller: an office login's own
--              write is stamped with who they are, whatever it passes; the
--              server (a token with no person in it, as the Board's "Make
--              tasks") passes who acted. Cleared when the task is no longer
--              handed to a leader, or the login is deleted. It can't be
--              moved to someone else by hand (only cleared).
--
-- A late task goes up to whoever the leader answers to, as before; with no
-- one above them, it goes back to the person who handed it out.
--
-- Additive and safe to run twice; no drops. Apply BEFORE the code that reads
-- it deploys: until it is applied, My tasks for leaders stays quiet (its
-- readiness probe names this column), never a 500.
begin;

alter table public.tasks
  add column if not exists handed_by uuid references auth.users(id) on delete set null;

create or replace function public.tasks_handed_by_stamp() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.assigned_contact_id is null then
    new.handed_by := null;
  elsif tg_op = 'INSERT' or new.assigned_contact_id is distinct from old.assigned_contact_id then
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
  before insert or update of assigned_contact_id, handed_by on public.tasks
  for each row execute function public.tasks_handed_by_stamp();

commit;

-- Check:
--   select column_name from information_schema.columns
--    where table_schema = 'public' and table_name = 'tasks' and column_name = 'handed_by';
--   select tgname from pg_trigger where tgname = 'tasks_handed_by_stamp';

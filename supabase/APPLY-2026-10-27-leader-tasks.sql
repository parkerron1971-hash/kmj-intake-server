-- APPLY-2026-10-27-leader-tasks.sql
--
-- My tasks for leaders (church_leader_tasks.py; Kevin 2026-10-27: "yes build
-- my tasks for leaders"). A church's office logins are few, and each one
-- reads every member record, so its leaders (elders, the worship pastor, the
-- youth pastor, team leaders) work from the member app's Lead tab on their
-- phone. Until now a task could only be handed to an office login
-- (tasks.assigned_to, APPLY-2026-10-26-task-hand-off.sql). Now it can be
-- handed to a leader instead: one of the church's people.
--
--   assigned_contact_id  the leader (contacts.id) the task is handed to.
--                        One person per task: a login (assigned_to) or a
--                        leader, never both (tasks_handed_to_one). Always the
--                        task's own church's person (the trigger below).
--   leader_told_at       the leader was emailed that it's theirs (the hourly
--                        sweep claims it before sending, and lets it go if
--                        the send fails)
--   late_told_at         the person the leader answers to was told it's past
--                        due (once, in the church's morning)
--   done_by_contact_id   who marked it done from the phone
--
-- Handing it to someone else starts it over: the trigger clears
-- leader_told_at and late_told_at, so the new leader is told; a new due date
-- clears late_told_at. It hands work over and grants nothing: who can read
-- and change tasks is unchanged (the office still writes tasks straight to
-- the database with its own token).
--
-- Additive and safe to run twice; no drops. Apply before switching
-- CHURCH_LEADER_TASKS on (the code stays quiet without it).
begin;

alter table public.tasks
  add column if not exists assigned_contact_id uuid references public.contacts(id) on delete set null,
  add column if not exists leader_told_at timestamptz,
  add column if not exists late_told_at timestamptz,
  add column if not exists done_by_contact_id uuid references public.contacts(id) on delete set null;

-- One person per task: a login or a leader.
do $$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'tasks_handed_to_one' and conrelid = 'public.tasks'::regclass) then
    alter table public.tasks
      add constraint tasks_handed_to_one check (assigned_to is null or assigned_contact_id is null);
  end if;
end $$;

-- The leader (and whoever marked it done) is one of the task's own church's
-- people, whatever the caller passes; each is checked when it is set or the
-- task's church changes (so a person leaving the list, which sets them to
-- null one column at a time, never trips over the other). A new leader is
-- told afresh; a new due date can be late again.
create or replace function public.tasks_leader_same_business() returns trigger
language plpgsql set search_path = public as $$
declare
  check_leader boolean := tg_op = 'INSERT';
  check_done boolean := tg_op = 'INSERT';
begin
  if tg_op = 'UPDATE' then
    check_leader := new.business_id is distinct from old.business_id
                    or new.assigned_contact_id is distinct from old.assigned_contact_id;
    check_done := new.business_id is distinct from old.business_id
                  or new.done_by_contact_id is distinct from old.done_by_contact_id;
  end if;
  if check_leader and new.assigned_contact_id is not null and not exists (
      select 1 from public.contacts c where c.id = new.assigned_contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  if check_done and new.done_by_contact_id is not null and not exists (
      select 1 from public.contacts c where c.id = new.done_by_contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  if tg_op = 'UPDATE' then
    if new.assigned_contact_id is distinct from old.assigned_contact_id then
      new.leader_told_at := null;
      new.late_told_at := null;
    elsif new.due_date is distinct from old.due_date then
      new.late_told_at := null;
    end if;
  end if;
  return new;
end $$;
create or replace trigger tasks_leader_same_business
  before insert or update of assigned_contact_id, done_by_contact_id, business_id, due_date
  on public.tasks for each row execute function public.tasks_leader_same_business();
revoke all on function public.tasks_leader_same_business() from public, anon, authenticated;

-- A leader's open tasks (the Lead tab, the sweep).
create index if not exists tasks_leader_open
  on public.tasks (business_id, assigned_contact_id)
  where assigned_contact_id is not null and status <> 'done';

comment on column public.tasks.assigned_contact_id is
  'My tasks for leaders (church_leader_tasks.py): the leader, one of the church''s people, this task was handed to. Null = not handed to a leader. Never set together with assigned_to.';
comment on column public.tasks.leader_told_at is
  'church_leader_tasks sweep: when the leader was emailed that the task is theirs (claimed before the send). Cleared when it is handed to someone else.';
comment on column public.tasks.late_told_at is
  'church_leader_tasks sweep: when the person the leader answers to was told it is past due. Cleared on a new leader or a new due date.';
comment on column public.tasks.done_by_contact_id is
  'church_leader_tasks: the leader who marked it done from the Lead tab.';

commit;

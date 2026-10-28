-- APPLY-2026-10-26-task-hand-off.sql
--
-- Who sees what (Kevin, 2026-10-26; canvas 99aFvCSRXU1x9pmqUcncoP): a task
-- can be handed to one person. tasks.assigned_to holds the login it was
-- handed to (the owner's or a seat's user id, as sessions.assigned_to and
-- ministry_care_requests.assigned_to do). Null means no one in particular,
-- as every task was before. It lands in that person's My week
-- (church_my_week.py) and so in their morning note.
--
-- It hands work over. It grants and walls nothing: who can read and change
-- tasks is the same as before.
--
-- Additive and safe to run twice. Apply before the code that reads it.

alter table public.tasks
  add column if not exists assigned_to uuid;

create index if not exists tasks_handed_open
  on public.tasks (business_id, assigned_to)
  where assigned_to is not null and status <> 'done';

comment on column public.tasks.assigned_to is
  'Who sees what (church_my_week.py): the login this task was handed to (owner or seat user id). Null = no one in particular. Hands work over; grants nothing.';

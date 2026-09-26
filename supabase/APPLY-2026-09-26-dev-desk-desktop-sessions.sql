-- Dev Desk desktop sessions (2026-09-26). A session Kevin opens by hand in
-- Solution Space announces itself to the Dev Desk, so Mission Control shows
-- every project open on the desktop — not only the tasks dispatched from it —
-- and a reply from the phone is typed into it like any task's.
--
--   origin     'dev_desk' — dispatched from the Dev Desk or by Chief (every
--              row before this file); 'desktop' — opened by hand and
--              announced by the device.
--   device_id  which Solution Space announced it, so that device's sweep
--              closes only its own sessions after a restart or a crash.
--
-- Desktop rows carry no authority_record (nothing was authorized — Kevin
-- opened them himself), so dev_task_authority_immutable never engages.
--
-- Additive and idempotent. Safe to apply BEFORE the code ships: old code
-- neither reads nor writes these columns, and the default keeps its inserts
-- valid. The new code reads `origin`, so apply this FIRST.
begin;

alter table public.dev_tasks
  add column if not exists origin text not null default 'dev_desk';
alter table public.dev_tasks drop constraint if exists dev_tasks_origin_check;
alter table public.dev_tasks
  add constraint dev_tasks_origin_check check (origin in ('dev_desk', 'desktop'));

alter table public.dev_tasks
  add column if not exists device_id uuid
    references public.dev_bridge_devices(id) on delete set null;

-- The Dev Desk reads desktop sessions newest-activity first; the sweep reads
-- one device's live ones.
create index if not exists dev_tasks_desktop_idx
  on public.dev_tasks (device_id, updated_at desc)
  where origin = 'desktop';

commit;

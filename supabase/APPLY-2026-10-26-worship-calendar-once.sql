-- APPLY-2026-10-26-worship-calendar-once.sql
--
-- "Bring in from the calendar" (worship_announce_import.py): an event comes
-- onto a church's announcements board once. The code reads what's there
-- before it writes, but two quick presses (or two people) could both read
-- "not yet"; this index makes the second insert fail instead of doubling the
-- announcement, and the code counts it as already there. Only live calendar
-- rows: one taken off the board (archived) can come in again.
--
-- Safe to run twice. Fails (and changes nothing) if duplicates already
-- exist; check first:
--   select business_id, source_ref, count(*) from worship_announcements
--   where source = 'calendar' and archived_at is null group by 1, 2 having count(*) > 1;

create unique index if not exists worship_announcements_calendar_once
  on public.worship_announcements (business_id, source_ref)
  where source = 'calendar' and archived_at is null;

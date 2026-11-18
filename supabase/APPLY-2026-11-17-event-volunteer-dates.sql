-- Who serves when, past Sunday (serve_dates.py, sunday_planning.py; Kevin
-- 2026-11-17: "build that", about scheduling the volunteer teams for an event
-- that isn't on a Sunday: a Thursday outreach night, a Saturday event, a
-- Wednesday Bible study).
--
--   worship_services.kind            'service': every row there today, a
--                                    Sunday plan (ChurchSavvy's or Sunday
--                                    Planning's). 'event': an event date,
--                                    scheduled for the Volunteers' teams only
--                                    (greeters, ushers, parking, kids,
--                                    hospitality). It has no order of service,
--                                    is never a template, and ChurchSavvy's
--                                    views never show it.
--   worship_services.place           where an event date is ('' when unsaid).
--   worship_services.event_entry_id  the Services & Events entry it was made
--                                    from (module_entries), so the event and
--                                    its volunteers are the same thing. If the
--                                    entry is deleted it becomes null and the
--                                    asks stay. One live event date per entry.
--
-- Event dates live in worship_services so every serving read already follows
-- them (serve_assignments.service_id references it): asks, subs, reminders,
-- the member app, the .ics, the alerts and the hours work as for a Sunday.
--
-- Additive: every row there now becomes kind 'service' (the default), so
-- nothing anyone sees changes until an event date is added. Server-only like
-- the rest of worship_services (RLS on, no policies, browser roles revoked:
-- APPLY-2026-10-19-worship-show.sql), so no policy is added and the browser
-- still reads none of it. Safe to run twice; one transaction; ends with
-- NOTIFY pgrst so the API sees the columns at once. Until it is applied the
-- server never selects or filters on these columns and Who serves when
-- offers no event date (serve_dates.ready); nothing is a 500.
--
-- Verify after:
--   select column_name, data_type, is_nullable, column_default
--     from information_schema.columns
--    where table_schema = 'public' and table_name = 'worship_services'
--      and column_name in ('kind', 'place', 'event_entry_id') order by 1;
--   -- 3 rows: event_entry_id uuid YES (null) · kind text NO 'service'::text · place text NO ''::text
--   select conname from pg_constraint
--    where conname in ('worship_services_kind_known', 'worship_services_place_short',
--                      'worship_services_event_plain', 'worship_services_entry_is_event') order by 1;   -- 4 rows
--   select kind, count(*) from public.worship_services group by kind;   -- only 'service' until an event date is added
--
-- Rollback (take every event date off Who serves when first):
--   drop trigger if exists worship_services_entry_same_business on public.worship_services;
--   drop function if exists public.worship_services_entry_same_business();
--   drop index if exists public.worship_services_one_per_event;
--   alter table public.worship_services drop column if exists event_entry_id,
--     drop column if exists place, drop column if exists kind;
begin;
set local lock_timeout = '5s';

alter table public.worship_services
  add column if not exists kind text not null default 'service',
  add column if not exists place text not null default '',
  add column if not exists event_entry_id uuid references public.module_entries(id) on delete set null;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'worship_services_kind_known') then
    alter table public.worship_services
      add constraint worship_services_kind_known check (kind in ('service', 'event'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'worship_services_place_short') then
    alter table public.worship_services
      add constraint worship_services_place_short check (char_length(place) <= 120);
  end if;
  -- An event date is never a template and carries no order of service.
  if not exists (select 1 from pg_constraint where conname = 'worship_services_event_plain') then
    alter table public.worship_services
      add constraint worship_services_event_plain
        check (kind = 'service' or (not is_template and items = '[]'::jsonb));
  end if;
  -- Only an event date names a Services & Events entry.
  if not exists (select 1 from pg_constraint where conname = 'worship_services_entry_is_event') then
    alter table public.worship_services
      add constraint worship_services_entry_is_event check (event_entry_id is null or kind = 'event');
  end if;
end $$;

create unique index if not exists worship_services_one_per_event
  on public.worship_services (event_entry_id)
  where event_entry_id is not null and archived_at is null;

-- The entry is the same church's: a second guard beside the server's own.
create or replace function public.worship_services_entry_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.event_entry_id is not null and not exists (
       select 1 from public.module_entries e
        where e.id = new.event_entry_id and e.business_id = new.business_id) then
    raise exception 'That event is not in this church';
  end if;
  return new;
end $$;
revoke all on function public.worship_services_entry_same_business() from public, anon, authenticated;

drop trigger if exists worship_services_entry_same_business on public.worship_services;
create trigger worship_services_entry_same_business
  before insert or update of event_entry_id, business_id on public.worship_services
  for each row execute function public.worship_services_entry_same_business();

commit;

notify pgrst, 'reload schema';

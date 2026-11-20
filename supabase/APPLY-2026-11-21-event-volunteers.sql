-- An event's volunteers, one structure (docs/EVENT_VOLUNTEERS.md; Kevin
-- 2026-11-20: "when a event is made there should be questions asked normal
-- service volunteers or special volunteers… so people can request for an
-- amount of volunteers for their event", then "go" on the proposal
-- https://claude.ai/artifact/98Z9QFcaZ6ZNQhLdarKHQB).
--
--   worship_services.needs        an event date's own numbers for the
--                                 Volunteers' places: {"<serve_positions.id>": n},
--                                 n a whole number 1-50, at most 60 places. A
--                                 place not named isn't needed that night.
--                                 null = every Volunteers place at its Sunday
--                                 number, which is how every event date made
--                                 before this file keeps working. Only an
--                                 event date carries it, never a Sunday.
--   event_volunteer_requests      an organizer's ask for the serving teams:
--                                 the event (a Services & Events entry), the
--                                 numbers, a note, who asked; waiting until
--                                 whoever schedules the Volunteers' teams says
--                                 yes (then `on`, with the event date it made)
--                                 or no (`declined`, with a note back). Also
--                                 `withdrawn` (the organizer took it back) and
--                                 `cancelled` (the event went away). One live
--                                 (waiting or on) request per event. When the
--                                 organizer can schedule the teams themselves
--                                 the row is written `on` at once.
--
-- The special roles (chaperones, the grill), the flyer and the minutes a
-- special helper's yes counts toward their hours are kept on the event itself
-- (module_entries.data: _roles, _flyer, _serve_minutes) and need nothing here.
--
-- Additive. Every row there now keeps needs null, so nothing anyone sees
-- changes. The table is server-only like worship_services: RLS on, no
-- policies, the browser's roles revoked; only service_role reads or writes
-- it. Safe to run twice; one transaction; lock_timeout 5s; ends with NOTIFY
-- pgrst. Until it is applied the server never selects or writes `needs` and
-- the request routes answer 404 (event_volunteers.ready); nothing is a 500.
--
-- Needs, in order: APPLY-2026-10-19-worship-show.sql,
-- APPLY-2026-10-23-sunday-planning.sql, APPLY-2026-11-17-event-volunteer-dates.sql
-- (all applied).
--
-- Verify after:
--   select column_name, data_type, is_nullable from information_schema.columns
--    where table_schema = 'public' and table_name = 'worship_services' and column_name = 'needs';
--   -- 1 row: needs jsonb YES
--   select relrowsecurity, (select count(*) from pg_policies where tablename = 'event_volunteer_requests') as policies,
--          has_table_privilege('anon', 'public.event_volunteer_requests', 'select') as anon_reads,
--          has_table_privilege('authenticated', 'public.event_volunteer_requests', 'select') as browser_reads
--     from pg_class where oid = 'public.event_volunteer_requests'::regclass;
--   -- 1 row: true · 0 · false · false
--   select conname from pg_constraint
--    where conname in ('worship_services_needs_event', 'event_volunteer_requests_status_known',
--                      'event_volunteer_requests_needs_ok', 'event_volunteer_requests_decided') order by 1;   -- 4 rows
--   select count(*) from public.worship_services where needs is not null;   -- 0 until an event asks
--
-- Rollback (nothing reads these once the server's switch is off):
--   drop table if exists public.event_volunteer_requests;
--   drop function if exists public.event_volunteer_requests_same_business();
--   alter table public.worship_services drop constraint if exists worship_services_needs_event;
--   alter table public.worship_services drop column if exists needs;
--   drop function if exists public.event_needs_ok(jsonb);
begin;
set local lock_timeout = '5s';

-- ─── An event date's own numbers ─────────────────────────────────────

-- The shape the server writes: a non-empty object of serve_positions ids,
-- each a whole number from 1 to 50, at most 60 of them. Which places are the
-- church's own Volunteers places is the server's check (it reads them).
create or replace function public.event_needs_ok(n jsonb) returns boolean
language sql immutable set search_path = public as $$
  select n is not null
     and jsonb_typeof(n) = 'object'
     and n <> '{}'::jsonb
     and (select count(*) from jsonb_object_keys(n)) <= 60
     and not exists (
       select 1 from jsonb_each(n) e
        where e.key !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           or jsonb_typeof(e.value) <> 'number'
           or (e.value)::numeric <> trunc((e.value)::numeric)
           or (e.value)::numeric < 1
           or (e.value)::numeric > 50)
$$;
revoke all on function public.event_needs_ok(jsonb) from public, anon, authenticated;
grant execute on function public.event_needs_ok(jsonb) to service_role;

alter table public.worship_services add column if not exists needs jsonb;

do $$
begin
  -- Only an event date carries numbers, and only in the shape above.
  if not exists (select 1 from pg_constraint where conname = 'worship_services_needs_event') then
    alter table public.worship_services
      add constraint worship_services_needs_event
        check (needs is null or (kind = 'event' and public.event_needs_ok(needs)));
  end if;
end $$;

-- ─── An organizer's ask for the serving teams ────────────────────────

create table if not exists public.event_volunteer_requests (
  id              uuid primary key default gen_random_uuid(),
  business_id     uuid not null references public.businesses(id) on delete cascade,
  -- The event. Null once the event is deleted: the request is then cancelled
  -- by the server, and its copy of the title and day still reads.
  entry_id        uuid references public.module_entries(id) on delete set null,
  title           text not null,
  starts_at       timestamptz not null,
  place           text not null default '',
  needs           jsonb not null,
  note            text not null default '',
  asked_by        uuid not null,
  asked_by_name   text not null default '',
  status          text not null default 'waiting',
  -- The event date a yes made (worship_services kind 'event').
  service_id      uuid references public.worship_services(id) on delete set null,
  decided_by      uuid,
  decided_by_name text not null default '',
  decided_at      timestamptz,
  decided_note    text not null default '',
  -- The notice ledger: the schedulers were told of the ask; the organizer was
  -- told of the answer. A sweep that finds either null tells them once.
  told_at         timestamptz,
  answer_told_at  timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint event_volunteer_requests_status_known
    check (status in ('waiting', 'on', 'declined', 'withdrawn', 'cancelled')),
  constraint event_volunteer_requests_title_short check (char_length(title) between 1 and 120),
  constraint event_volunteer_requests_place_short check (char_length(place) <= 120),
  constraint event_volunteer_requests_note_short check (char_length(note) <= 300),
  constraint event_volunteer_requests_decided_note_short check (char_length(decided_note) <= 300),
  constraint event_volunteer_requests_names_short
    check (char_length(asked_by_name) <= 80 and char_length(decided_by_name) <= 80),
  constraint event_volunteer_requests_needs_ok check (public.event_needs_ok(needs)),
  -- A yes or a no says who and when.
  constraint event_volunteer_requests_decided
    check (status not in ('on', 'declined') or (decided_at is not null and decided_by is not null))
);

-- One live request per event: a second ask while one waits or is on is a 409.
create unique index if not exists event_volunteer_requests_one_live
  on public.event_volunteer_requests (entry_id)
  where entry_id is not null and status in ('waiting', 'on');
create index if not exists event_volunteer_requests_by_status
  on public.event_volunteer_requests (business_id, status, starts_at);
create index if not exists event_volunteer_requests_by_service
  on public.event_volunteer_requests (service_id) where service_id is not null;

-- The event and the event date are the same church's, a second guard beside
-- the server's own; and updated_at follows every change.
create or replace function public.event_volunteer_requests_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.entry_id is not null and not exists (
       select 1 from public.module_entries e
        where e.id = new.entry_id and e.business_id = new.business_id) then
    raise exception 'That event is not in this church';
  end if;
  if new.service_id is not null and not exists (
       select 1 from public.worship_services s
        where s.id = new.service_id and s.business_id = new.business_id and s.kind = 'event') then
    raise exception 'That date is not one of this church''s event dates';
  end if;
  new.updated_at := now();
  return new;
end $$;
revoke all on function public.event_volunteer_requests_same_business() from public, anon, authenticated;

drop trigger if exists event_volunteer_requests_same_business on public.event_volunteer_requests;
create trigger event_volunteer_requests_same_business
  before insert or update on public.event_volunteer_requests
  for each row execute function public.event_volunteer_requests_same_business();

alter table public.event_volunteer_requests enable row level security;
revoke all on public.event_volunteer_requests from public, anon, authenticated;
grant select, insert, update, delete on public.event_volunteer_requests to service_role;

commit;

notify pgrst, 'reload schema';

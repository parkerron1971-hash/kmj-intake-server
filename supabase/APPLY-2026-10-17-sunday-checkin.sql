-- Sunday check-in (Kevin, 2026-10-17: "the app checkin and online checkin
-- for online view are all good. kiosk is for children"). Members check
-- themselves and their family in from their own phones (a code on the
-- welcome slide opens their member page); online viewers count with
-- "I'm here"; the Kids self kiosk counts the parent who checks children in.
-- Idempotent.
--
--   attendance.method        + 'kids_parent' (the adult who checked children
--                            in at the self kiosk). 'self' (a member's phone)
--                            and 'online' were already allowed.
--   church_checkin_settings  the church's Sunday service, set once: day,
--                            time, timezone, how long check-in stays open.
--                            Server-only (the service role), like the role
--                            library: the office reads and writes it
--                            through /church/checkin.
--   module_entries           one check-in occasion per church per day,
--                            however many phones ask for it at once.
begin;

alter table public.attendance drop constraint if exists attendance_method_check;
alter table public.attendance add constraint attendance_method_check
  check (method in ('staff','station','self','rsvp','online','kids_parent'));

create table if not exists public.church_checkin_settings(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  enabled boolean not null default false,
  -- Python's weekday: Monday 0 … Sunday 6.
  weekday smallint not null default 6 check (weekday between 0 and 6),
  start_time text not null default '11:00' check (start_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'),
  timezone text not null default 'America/New_York' check (length(timezone) between 1 and 64),
  opens_before_min smallint not null default 30 check (opens_before_min between 0 and 240),
  closes_after_min smallint not null default 180 check (closes_after_min between 30 and 720),
  -- The occasion's name; blank uses the church's own undated service entry,
  -- else "Sunday service".
  title text not null default '' check (length(title) <= 80),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

alter table public.church_checkin_settings enable row level security;
revoke all on public.church_checkin_settings from anon, authenticated;
grant all on public.church_checkin_settings to service_role;

create unique index if not exists module_entries_checkin_day
  on public.module_entries(business_id, (data->>'_checkin_day'))
  where (data ? '_checkin_day');

commit;

-- APPLY-2026-11-18-care-lock.sql
--
-- How Prayer & care locks itself, one row a church (private_care.py:
-- lock_settings, save_lock_settings). Kevin, 2026-11-18, on the care desk
-- mock (artifact BJhieg2rPsVoEzqj2qCGmw): the page should lock when no work
-- has been done and ask for a password to open again, "but that should be
-- custom to settings because others might like something else".
--
-- ministry_care_settings (server-only: RLS on, no policies, browser roles
-- revoked, like ministry_care_requests):
--   lock_minutes      how long the page waits, with nothing done, before it
--                     locks: 0 (never by itself), 5, 10, 15, 30 or 60
--   require_password  true: opening it again asks for the login's own
--                     password (POST /auth/step-up, scope "care"), and the
--                     server refuses the requests without that proof
--   updated_by, updated_at  who changed it last
--
-- No row is the default: locks after 10 quiet minutes, asks for the
-- password. The code reads the default until this is applied (and when a
-- read fails), so applying it changes nothing anyone sees; it only lets a
-- church save a different choice (until then saving answers 503).
--
-- New table only: one transaction, safe to run twice, nothing dropped.
begin;

set local lock_timeout = '5s';

create table if not exists public.ministry_care_settings(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  lock_minutes smallint not null default 10,
  require_password boolean not null default true,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'ministry_care_settings_lock_minutes'
                 and conrelid = 'public.ministry_care_settings'::regclass) then
    alter table public.ministry_care_settings
      add constraint ministry_care_settings_lock_minutes check (lock_minutes in (0, 5, 10, 15, 30, 60));
  end if;
end $$;

alter table public.ministry_care_settings enable row level security;
revoke all on public.ministry_care_settings from anon, authenticated;
grant select, insert, update, delete on public.ministry_care_settings to service_role;

commit;

notify pgrst, 'reload schema';

-- Checks (read-only):
--   select relrowsecurity from pg_class where oid = 'public.ministry_care_settings'::regclass;   -- true
--   select count(*) from pg_policies where tablename = 'ministry_care_settings';                  -- 0
--   select has_table_privilege('authenticated', 'public.ministry_care_settings', 'select');       -- false
--   select conname from pg_constraint where conrelid = 'public.ministry_care_settings'::regclass; -- pkey, fkey, lock_minutes
--
-- Rollback:
--   drop table if exists public.ministry_care_settings;

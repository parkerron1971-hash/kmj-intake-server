-- APPLY-2026-11-20-settings-server-keys-refresh.sql
--
-- The settings guard's list catches up with the server's.
--
-- APPLY-2026-11-17-settings-server-keys.sql is IN production (read 2026-11-20
-- in the SQL editor: business_settings_server_keys() present, 42 keys). It was
-- applied before three keys joined business_settings.SERVER_KEYS:
--   extra_storage   church extra storage (2026-11-17)
--   payroll         Payroll, the free version (2026-11-19)
--   guest_calls     "Who calls our guests" (2026-11-20, kmj-intake-server#2007)
-- Until this runs, an app login's whole-object settings write can still carry a
-- stale copy of those three over the server's (the guard keeps only the keys on
-- its list). This file replaces the list function with all 45, in the same
-- signature, so the trigger and the merge function pick them up at once.
--
-- One function replaced, nothing else: no table, no data, no trigger change.
-- Safe to run twice. If the 11-17 file isn't in (another database), this makes
-- the list function alone and the 11-17 file later writes the same list.
-- APPLY-2026-11-19-payroll-deposits.sql writes the same 45 when it runs.

begin;
set local lock_timeout = '5s';

create or replace function public.business_settings_server_keys() returns text[]
language sql immutable parallel safe set search_path = public as $$
  select array[
    -- money, plans and offers
    'founding_church', 'no_card_trial', 'sample_church', 'church_move', 'extra_logins',
    'extra_storage', 'church_texts_bill', 'stripe', 'churchsavvy_only', 'platform_books',
    -- gates the API holds behind the owner, a role or a step-up unlock
    'computer', 'email_domain', 'autonomy', 'content_autonomy', 'automations_paused',
    'church_owner_contact_id',
    -- the server's own records
    'lifecycle_emails', 'chief_insights', 'chief_playbook', 'maturity',
    'church_leaders_note', 'church_team_rollup', 'interview_events',
    -- settings with their own checked endpoint
    'availability', 'booking_page', 'business_picture', 'church_serving', 'churchsavvy',
    'client_sources', 'concierge', 'doc_defaults', 'giving', 'journeys', 'member_portal',
    'messaging', 'new_here', 'news', 'reading_plan', 'site_prefs', 'sms_replies', 'studio',
    'superbill', 'texting_hours',
    'payroll',
    'guest_calls'
  ]::text[]
$$;

revoke all on function public.business_settings_server_keys() from public, anon;
grant execute on function public.business_settings_server_keys() to authenticated, service_role;

notify pgrst, 'reload schema';
commit;

-- Checks (read-only):
--   select cardinality(public.business_settings_server_keys());                  -- 45
--   select 'guest_calls' = any(public.business_settings_server_keys())
--      and 'payroll' = any(public.business_settings_server_keys())
--      and 'extra_storage' = any(public.business_settings_server_keys());        -- true
--
-- Rollback: run APPLY-2026-11-17-settings-server-keys.sql's list function as it
-- stood before 2026-11-17's extra_storage (not recommended: it unguards three
-- keys the server already treats as its own).

-- APPLY-2026-11-19-payroll-deposits.sql
--
-- Payroll, the free version (payroll_deposits.py, payroll_reminders.py;
-- Kevin, 2026-11-19: "build the free version now and will think about the
-- other option later"). The church pays its people from its own bank and
-- sends its own tax deposits; Solutionist prepares the numbers, the
-- statements, the calendar and the reminders. Nothing here moves money or
-- files anything.
--
-- payroll_deposits (server-only: RLS on, no policies, browser roles revoked):
-- one row a business and key, a federal or state tax deposit, or a form,
-- that the church marked sent itself.
--   key          federal:YYYY-MM (a monthly depositor's month),
--                federal:YYYY-MM-DD (a semiweekly depositor's pay date),
--                state:YYYY-MM, forms:941:YYYYQn, forms:w2:YYYY
--   kind         federal | state | forms
--   period       the part of the key after its kind ("2026-11", "2026Q4")
--   amount       what was sent, as the church typed it
--   due_on       the due date the calendar worked out when it was marked
--   sent_on      the day the church says it went
--   reference    the EFTPS acknowledgement or the state's, as typed
--   marked_by    the login that marked it (no foreign key: a login that
--                leaves leaves the record)
--   marked_at    when it was marked (marking again updates the row)
--
-- payroll_reminders_sent (server-only, the same way): the reminders' memory.
-- One row a business, key and audience ("team" three days before, "owner"
-- the day before), claimed BEFORE the alert goes, so nobody hears the same
-- thing twice, whichever replica runs the hourly job.
--   key          a deposit or forms key above, or approve:<pay run id>
--   sent_on      the church's local day it was claimed
--
-- Why server-only: a deposit's amount and reference are the church's tax
-- records, and the reminders' memory is the server's own. The app reads both
-- through the payroll routes, which ask the church money wall first.
--
-- Two new tables (one transaction), then 'payroll' added to the settings
-- guard's server keys if that guard is in (a second transaction, section 2).
-- Safe to run twice, nothing dropped, no existing table touched. Apply any
-- time. Until then the code reads "no
-- deposits marked" (GET /payroll/calendar answers deposits_ready: false),
-- marking a deposit answers 503 "Deposit tracking is being switched on. Try
-- again shortly.", and the hourly reminders skip.
begin;

set local lock_timeout = '5s';

create table if not exists public.payroll_deposits(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  key text not null,
  kind text not null check (kind in ('federal', 'state', 'forms')),
  period text not null,
  amount numeric(12,2) not null check (amount >= 0),
  due_on date,
  sent_on date not null,
  reference text check (reference is null or char_length(reference) <= 120),
  marked_by uuid,
  marked_at timestamptz not null default now(),
  constraint payroll_deposits_key_shape check (
    key ~ '^(federal:[0-9]{4}-[0-9]{2}(-[0-9]{2})?|state:[0-9]{4}-[0-9]{2}|forms:941:[0-9]{4}Q[1-4]|forms:w2:[0-9]{4})$'),
  constraint payroll_deposits_one_a_key unique (business_id, key)
);

create table if not exists public.payroll_reminders_sent(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  key text not null check (char_length(key) <= 80),
  sent_on date not null,
  audience text not null check (audience in ('team', 'owner')),
  created_at timestamptz not null default now(),
  constraint payroll_reminders_sent_once unique (business_id, key, audience)
);

alter table public.payroll_deposits enable row level security;
revoke all on public.payroll_deposits from public, anon, authenticated;
grant all on public.payroll_deposits to service_role;

alter table public.payroll_reminders_sent enable row level security;
revoke all on public.payroll_reminders_sent from public, anon, authenticated;
grant all on public.payroll_reminders_sent to service_role;

commit;

-- 2. settings.payroll (the deposit schedule and the state's day, written by
-- PUT /payroll/settings) is the server's: business_settings.SERVER_KEYS has
-- 'payroll' since 2026-11-19. The settings guard keeps the app's own logins
-- from writing a server key straight to the row; its list is the function
-- below. Pre-check: when the guard (APPLY-2026-11-17-settings-server-keys.sql)
-- is already in, its list gains 'payroll' here (the same 45 keys, the same
-- function signature, so its grants and the trigger stay as they are); when
-- it isn't, nothing happens here, and that file brings 'payroll' itself (it
-- was added there before that file was applied). Either order ends with 45.
-- (guest_calls joined both lists on 2026-11-20, before either was applied.)
begin;

set local lock_timeout = '5s';

do $guard$
begin
  if to_regprocedure('public.business_settings_server_keys()') is null then
    raise notice 'the settings guard is not applied yet: APPLY-2026-11-17-settings-server-keys.sql brings payroll itself';
    return;
  end if;
  execute $fn$
create or replace function public.business_settings_server_keys() returns text[]
language sql immutable parallel safe set search_path = public as $body$
  select array[
    'founding_church', 'no_card_trial', 'sample_church', 'church_move', 'extra_logins',
    'extra_storage', 'church_texts_bill', 'stripe', 'churchsavvy_only', 'platform_books',
    'computer', 'email_domain', 'autonomy', 'content_autonomy', 'automations_paused',
    'church_owner_contact_id',
    'lifecycle_emails', 'chief_insights', 'chief_playbook', 'maturity',
    'church_leaders_note', 'church_team_rollup', 'interview_events',
    'availability', 'booking_page', 'business_picture', 'church_serving', 'churchsavvy',
    'client_sources', 'concierge', 'doc_defaults', 'giving', 'journeys', 'member_portal',
    'messaging', 'new_here', 'news', 'reading_plan', 'site_prefs', 'sms_replies', 'studio',
    'superbill', 'texting_hours',
    'payroll',
    'guest_calls'
  ]::text[]
$body$
$fn$;
end
$guard$;

commit;

notify pgrst, 'reload schema';

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads,
--          has_table_privilege('service_role', c.oid, 'insert') as server_writes
--     from pg_class c
--    where c.oid in ('public.payroll_deposits'::regclass, 'public.payroll_reminders_sent'::regclass)
--    order by c.relname;
--   -- 2 rows: payroll_deposits and payroll_reminders_sent, each true, 0, false, false, true
--   select conrelid::regclass, conname, contype from pg_constraint
--    where conrelid in ('public.payroll_deposits'::regclass, 'public.payroll_reminders_sent'::regclass)
--    order by 1, 2;
--   -- payroll_deposits: the key shape and one-a-key (u) constraints, the primary key, the foreign key to
--   -- businesses and the checks on kind, amount and reference; payroll_reminders_sent: once (u), the
--   -- primary key, the foreign key and the checks on key and audience
--   select count(*) from public.payroll_deposits;        -- 0
--   select count(*) from public.payroll_reminders_sent;  -- 0
--   -- Only when the settings guard is in (to_regprocedure('public.business_settings_server_keys()') is not null):
--   select cardinality(public.business_settings_server_keys()),
--          'payroll' = any(public.business_settings_server_keys());                   -- 45, true
--
-- Rollback (loses which deposits were marked sent, and the reminders may repeat once; no money record,
-- run or person changes):
--   drop table if exists public.payroll_reminders_sent;
--   drop table if exists public.payroll_deposits;

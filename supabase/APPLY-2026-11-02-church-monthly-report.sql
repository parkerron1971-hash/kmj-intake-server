-- APPLY-2026-11-02-church-monthly-report.sql
--
-- The monthly report (church_monthly_report.py; Kevin 2026-11-01:
-- "gathering the reports from admin should be Jessica", and it has "nothing
-- about money"). The Executive Pastor gathers each month from the office's
-- lanes: the numbers come from tables the app already keeps; what this table
-- holds is hers, one row a church a month:
--
--   notes          a line or a short paragraph for each lane (office_leadership,
--                  people_care, sunday_serving, media_comms), and who wrote
--                  them and when
--   send_id ...    the last send to the pastor: claimed before the email goes
--                  (send_id, send_state 'sending'), 'sent' once it went, put
--                  back when it didn't; sends counts them (a resend is asked
--                  for by name)
--
-- No money, ever: there is no column for an amount, and the code reads none.
-- Server-only, as the other church tables: RLS on, no policies, the browser's
-- roles revoked; church_monthly_report.py reads and writes it as the server.
-- A church that goes takes its rows. Additive, idempotent, nothing dropped.
-- Rollback: drop table public.church_monthly_reports;
begin;

create table if not exists public.church_monthly_reports(
  business_id uuid not null references public.businesses(id) on delete cascade,
  month text not null check (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  notes jsonb not null default '{}'::jsonb check (jsonb_typeof(notes) = 'object'),
  notes_by uuid,
  notes_by_name text check (notes_by_name is null or length(notes_by_name) <= 200),
  notes_at timestamptz,
  send_id text check (send_id is null or send_id ~ '^[0-9a-f]{32}$'),
  send_state text check (send_state is null or send_state in ('sending', 'sent')),
  sent_at timestamptz,
  sent_by uuid,
  sent_by_name text check (sent_by_name is null or length(sent_by_name) <= 200),
  sends integer not null default 0 check (sends >= 0),
  created_at timestamptz not null default now(),
  primary key (business_id, month)
);

alter table public.church_monthly_reports enable row level security;
revoke all on public.church_monthly_reports from anon, authenticated;
grant all on public.church_monthly_reports to service_role;

commit;

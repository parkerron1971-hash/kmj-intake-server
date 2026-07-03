-- email-suppressions-migration.sql
-- Hardening pass 1 (2026-07-03): deliverability protection.
--
-- Resend tells us when an address hard-bounces or the recipient marks
-- us as spam; until now those events were accepted and IGNORED
-- (email_sender.py webhook), so the system would keep sending to dead
-- or hostile addresses — the classic way a sending domain's reputation
-- dies. This table is the suppression list: the webhook writes to it,
-- and every outbound send checks it first.
--
-- Service-role only: RLS is enabled with NO policies, so PostgREST
-- access requires the service key (the backend). Practitioners never
-- see or edit this table directly.

create table if not exists public.email_suppressions (
  email       text primary key,
  reason      text not null default 'bounced',   -- 'bounced' | 'complained'
  event_type  text,                              -- raw Resend event type
  first_seen  timestamptz not null default now(),
  last_seen   timestamptz not null default now(),
  hits        integer not null default 1
);

alter table public.email_suppressions enable row level security;

comment on table public.email_suppressions is
  'Addresses we must not email again (hard bounce / spam complaint from Resend). Checked by email_sender.send_via_resend before every send.';

-- sms-consents-migration.sql
-- A2P CTA fix (2026-07-04): the public opt-in page at /sms records
-- every web-form consent here — the AUDIT TRAIL carriers can ask for
-- (who consented, when, from where). Keyword opt-ins are already
-- evidenced by the inbound sms_messages row + binding; this covers
-- the web-form path.

create table if not exists public.sms_consents (
  id           bigint generated always as identity primary key,
  phone        text not null,
  name         text,
  source       text not null default 'web_form',   -- 'web_form' | future sources
  consented_at timestamptz not null default now(),
  ip           text,
  user_agent   text
);
create index if not exists sms_consents_phone_idx on public.sms_consents (phone);

alter table public.sms_consents enable row level security;

-- Backend (anon key) writes; same permissive pattern as the other
-- sms_* tables — tighten alongside the broader RLS pass.
drop policy if exists sms_consents_all on public.sms_consents;
create policy sms_consents_all on public.sms_consents
  for all using (true) with check (true);

comment on table public.sms_consents is
  'Web-form SMS opt-in audit trail (public /sms page). Proof of consent for carrier audits.';

-- The devotional by text, a day at a time (devotional_daily.py; Kevin,
-- 2026-10-25: "how can we make this devotional available where people can
-- get them daily before i reveal the app?" ... "build the page and nightly
-- text"). One table, server-only (RLS on, no policies, browser roles
-- revoked):
--
--   devotional_texts   one row per church and phone: a person who asked,
--                      on the church's /daily page or by texting DAILY to
--                      its own number, for tomorrow's day each evening.
--                      The row is the consent for THESE texts and nothing
--                      else (it is not an sms_consents row, so campaigns
--                      and reminders never count it). `consent` keeps the
--                      words they agreed to. STOP (sms_opt_outs) still
--                      wins at send time. `last_key` is the evening claim:
--                      "<devotional id>_<day>", moved by one PATCH whose
--                      filter only matches a row not yet on that key, so
--                      one replica wins and nobody gets a day twice.
-- Idempotent.
begin;

create table if not exists public.devotional_texts(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  phone text not null check (phone ~ '^\+[1-9][0-9]{7,14}$'),
  name text check (name is null or char_length(name) <= 120),
  source text not null default 'web' check (source in ('web', 'text')),
  consent text check (consent is null or char_length(consent) <= 600),
  joined_at timestamptz not null default now(),
  stopped_at timestamptz,
  last_key text check (last_key is null or char_length(last_key) <= 80),
  last_sent_at timestamptz,
  unique (business_id, phone)
);

create index if not exists devotional_texts_live
  on public.devotional_texts (business_id) where stopped_at is null;

alter table public.devotional_texts enable row level security;
revoke all on public.devotional_texts from anon, authenticated;

commit;

-- sms-routing-migration.sql
-- SMS routing layer (2026-07-04, Kevin's architecture brief):
-- ONE Twilio number for the whole platform; Chief routes every inbound
-- by BINDING FIRST, KEYWORD SECOND. The keyword introduces; the stored
-- binding sustains.
--
--   sms_keywords  — per-practitioner routing keywords (dynamic, chosen
--                   in the app; NEVER carrier-registered; platform
--                   consent words START/STOP/HELP/... are reserved).
--   sms_bindings  — customer_phone ↔ business pairings. A phone may be
--                   bound to multiple businesses (genuinely shared
--                   customer); last_routed_at gives conversation
--                   continuity for bare replies.
--   sms_opt_outs  — STOP ledger. business_id NULL = platform-wide
--                   (Direct model: one number, STOP suppresses all).
--                   Kept per-pair-capable so the ISV migration is a
--                   config change, not a schema change.
--
-- RLS: matches the existing sms_messages pattern — the backend talks
-- through the anon key with permissive policies (tighten alongside the
-- broader RLS pass). Practitioners manage their own keyword row from
-- the app; routing tables are backend-written.

create table if not exists public.sms_keywords (
  id          bigint generated always as identity primary key,
  business_id uuid not null unique,
  keyword     text not null unique
              check (keyword = upper(keyword) and keyword ~ '^[A-Z0-9]{3,20}$'),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists sms_keywords_kw_idx on public.sms_keywords (keyword);

create table if not exists public.sms_bindings (
  id             bigint generated always as identity primary key,
  customer_phone text not null,
  business_id    uuid not null,
  bound_at       timestamptz not null default now(),
  last_routed_at timestamptz not null default now(),
  unique (customer_phone, business_id)
);
create index if not exists sms_bindings_phone_idx on public.sms_bindings (customer_phone);

create table if not exists public.sms_opt_outs (
  id           bigint generated always as identity primary key,
  phone        text not null,
  business_id  uuid,                    -- NULL = platform-wide (Direct)
  opted_out_at timestamptz not null default now(),
  unique (phone, business_id)
);
create index if not exists sms_opt_outs_phone_idx on public.sms_opt_outs (phone);

alter table public.sms_keywords enable row level security;
alter table public.sms_bindings enable row level security;
alter table public.sms_opt_outs enable row level security;

-- Permissive (anon) policies — same trust model as sms_messages today.
drop policy if exists sms_keywords_all on public.sms_keywords;
create policy sms_keywords_all on public.sms_keywords
  for all using (true) with check (true);
drop policy if exists sms_bindings_all on public.sms_bindings;
create policy sms_bindings_all on public.sms_bindings
  for all using (true) with check (true);
drop policy if exists sms_opt_outs_all on public.sms_opt_outs;
create policy sms_opt_outs_all on public.sms_opt_outs
  for all using (true) with check (true);

comment on table public.sms_keywords is
  'Per-practitioner SMS routing keywords (app-layer only; not carrier-registered). Reserved consent words are enforced in sms_routing.py.';
comment on table public.sms_bindings is
  'customer_phone ↔ business routing bindings. Keyword introduces, binding sustains. Multiple bindings per phone = genuinely shared customer.';
comment on table public.sms_opt_outs is
  'STOP ledger. business_id NULL = platform-wide suppression (Direct model). Checked before EVERY outbound send.';

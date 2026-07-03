-- launch-ops-migration.sql
-- Mission Control launch operations (2026-07-03):
--   1. Multi-use invite links (share one code with a beta group)
--   2. usage_grants — owner-granted bonus Chief interactions
--   3. businesses.comp_tier — comp a business at any tier, no Stripe
-- All backend code fails soft pre-migration (single-use invites keep
-- working; grants read as 0; comp_tier select retries without it).

-- 1. Multi-use invites ------------------------------------------------
alter table public.invite_tokens
  add column if not exists max_uses integer not null default 1,
  add column if not exists uses_count integer not null default 0,
  add column if not exists label text;
alter table public.invite_tokens alter column email drop not null;

-- 2. Bonus unit grants (service-role only — RLS with no policies) -----
create table if not exists public.usage_grants (
  id          bigint generated always as identity primary key,
  business_id uuid not null,
  units       integer not null,
  month       text,           -- 'YYYY-MM' = that month only; NULL = every month
  reason      text,
  created_at  timestamptz not null default now()
);
create index if not exists usage_grants_biz_idx
  on public.usage_grants (business_id);
alter table public.usage_grants enable row level security;

comment on table public.usage_grants is
  'Owner-granted bonus Chief interactions. NULL month = recurring monthly bonus. Read by usage_metering.usage_summary; written via POST /access/grant-units.';

-- 3. Comp tier override ------------------------------------------------
alter table public.businesses
  add column if not exists comp_tier text
  check (comp_tier is null or comp_tier in ('starter', 'professional', 'practice'));

comment on column public.businesses.comp_tier is
  'Owner-set tier override (beta testers / partners / comps). feature_gates.plan_of prefers this over the Stripe-derived plan. Set via POST /access/business/{id}/tier.';

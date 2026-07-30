-- APPLY-2026-07-30-tier-vocab-launch-ops.sql
-- 7/30 tier-readiness arc. Two fixes in one pass:
--
-- 1. businesses.tier CHECK still allowed only the RETIRED vocabulary
--    (starter|pro|enterprise) — 'professional', 'practice', 'founder'
--    would 23514. The webhook now mirrors the resolved plan key into
--    tier (stripe_billing._apply_subscription_state), so the CHECK must
--    accept the real catalog. Legacy values stay valid: live data holds
--    20×starter + 1×pro and nothing rewrites history.
--
-- 2. The 2026-07-03 launch-ops migration was NEVER APPLIED (found
--    during this arc: comp_tier column, usage_grants table, and the
--    multi-use invite columns are all absent live, so comping a tier
--    or granting bonus units fails silently). Applied verbatim below —
--    everything is idempotent (IF NOT EXISTS / additive).

-- 1. Tier vocabulary --------------------------------------------------
alter table public.businesses drop constraint if exists businesses_tier_check;
alter table public.businesses add constraint businesses_tier_check
  check (tier in ('starter', 'pro', 'enterprise',
                  'professional', 'practice', 'founder', 'free'));

-- 2a. Multi-use invites ----------------------------------------------
alter table public.invite_tokens
  add column if not exists max_uses integer not null default 1,
  add column if not exists uses_count integer not null default 0,
  add column if not exists label text;
alter table public.invite_tokens alter column email drop not null;

-- 2b. Bonus unit grants (service-role only — RLS with no policies) ----
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

-- 2c. Comp tier override ----------------------------------------------
alter table public.businesses
  add column if not exists comp_tier text
  check (comp_tier is null or comp_tier in ('starter', 'professional', 'practice'));

comment on column public.businesses.comp_tier is
  'Owner-set tier override (beta testers / partners / comps). feature_gates.plan_of prefers this over the Stripe-derived plan. Set via POST /access/business/{id}/tier.';

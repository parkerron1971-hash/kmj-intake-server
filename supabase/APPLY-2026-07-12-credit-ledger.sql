-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-12 — credit_ledger (Pricing v2 Phase C, spec §6.1)
--
-- Prepaid credit packs replace postpaid overage. Every movement of
-- credits is one row here:
--   purchase  +units  (Stripe credit-pack checkout completed)
--   grant     +units  (owner-granted: beta comps, goodwill, promos)
--   burn      -units  (usage beyond the monthly plan allowance)
-- Balance = SUM(delta_units). Credits never expire (Kevin's ruling).
--
-- Idempotency rails:
--   * stripe_payment_id UNIQUE (partial) — a Stripe webhook retry can
--     never double-grant a pack, even though the webhook-event dedupe
--     runs after processing.
--   * one burn row per business per month (source = 'auto:YYYY-MM',
--     UNIQUE partial) — the lazy draw-down UPSERTs the month's burn
--     instead of appending, so concurrent reads can't double-burn.
-- ══════════════════════════════════════════════════════════════════

create table if not exists public.credit_ledger (
  id                 uuid primary key default gen_random_uuid(),
  business_id        uuid not null references public.businesses(id) on delete cascade,
  delta_units        integer not null,
  kind               text not null check (kind in ('purchase', 'grant', 'burn')),
  -- Where it came from: 'stripe:pack_small', 'owner:beta-comp',
  -- 'auto:2026-07' (monthly burn row), …
  source             text,
  stripe_payment_id  text,
  note               text,
  created_at         timestamptz not null default now(),
  -- Signs must match kinds — the balance is only trustworthy if they do.
  constraint credit_ledger_sign check (
    (kind in ('purchase', 'grant') and delta_units > 0)
    or (kind = 'burn' and delta_units < 0)
  )
);

create index if not exists credit_ledger_biz_idx
  on public.credit_ledger (business_id, created_at desc);

-- One grant per Stripe payment, ever (webhook-retry armor).
create unique index if not exists credit_ledger_stripe_uniq
  on public.credit_ledger (stripe_payment_id)
  where stripe_payment_id is not null;

-- One burn row per business per month (draw-down upsert target).
create unique index if not exists credit_ledger_burn_month_uniq
  on public.credit_ledger (business_id, source)
  where kind = 'burn';

alter table public.credit_ledger enable row level security;

-- Owners can SEE their ledger (the Plan & Usage meter reads it client-
-- side if ever needed); ALL writes go through the backend service role
-- only — no insert/update/delete policies for authenticated users.
drop policy if exists credit_ledger_owner_read on public.credit_ledger;
create policy credit_ledger_owner_read on public.credit_ledger
  for select using (
    business_id in (select id from public.businesses where owner_id = auth.uid())
  );

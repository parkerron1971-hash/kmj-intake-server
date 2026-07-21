-- Campaigns Phase 1 (2026-07-21) — "Chief as Marketing Director" spine.
-- A campaign = goal + audience slice + a sequence of touches (email/SMS)
-- drafted by Chief in the practitioner's voice, approved once, executed
-- on schedule by campaigns_tick (scheduler leader, minute cadence).
--
-- campaign_sends = the idempotency ledger: ONE row per
-- (campaign, touch, contact) — the sweep can crash and re-run without
-- double-sending (same armor as credit_ledger's stripe_payment_id).
--
-- Apply in the Supabase SQL editor. Safe to re-run (IF NOT EXISTS).

create table if not exists public.campaigns (
  id          uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name        text not null,
  goal        text,
  -- {kind: 'silent'|'leads'|'clients'|'all', days_silent: int}
  audience    jsonb not null default '{}'::jsonb,
  -- [{channel:'email'|'sms', offset_days:int, subject:text, body:text,
  --   completed_at:timestamptz|null}]
  touches     jsonb not null default '[]'::jsonb,
  -- draft -> running -> completed (pause slots between run states)
  status      text not null default 'draft'
              check (status in ('draft','running','paused','completed')),
  start_at    timestamptz,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists campaigns_biz_idx
  on public.campaigns (business_id, status);

create table if not exists public.campaign_sends (
  id          uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns(id) on delete cascade,
  business_id uuid not null,
  touch_idx   int  not null,
  contact_id  uuid not null,
  channel     text not null,
  sent_at     timestamptz not null default now(),
  -- exactly-once per (campaign, touch, contact)
  unique (campaign_id, touch_idx, contact_id)
);

create index if not exists campaign_sends_campaign_idx
  on public.campaign_sends (campaign_id, touch_idx);

-- RLS: owner-only reads via the businesses row (one-directional check —
-- businesses policies never reference campaigns, so no 42P17 cycle).
-- All writes go through the backend service role.
alter table public.campaigns enable row level security;
alter table public.campaign_sends enable row level security;

drop policy if exists campaigns_owner_select on public.campaigns;
create policy campaigns_owner_select on public.campaigns
  for select using (
    exists (select 1 from public.businesses b
            where b.id = campaigns.business_id and b.owner_id = auth.uid())
  );

drop policy if exists campaign_sends_owner_select on public.campaign_sends;
create policy campaign_sends_owner_select on public.campaign_sends
  for select using (
    exists (select 1 from public.businesses b
            where b.id = campaign_sends.business_id and b.owner_id = auth.uid())
  );

comment on table public.campaigns is
  'Marketing campaigns: Chief-drafted touch sequences (email/SMS) executed by campaigns_router.campaigns_tick on the scheduler leader.';
comment on table public.campaign_sends is
  'Exactly-once send ledger per (campaign, touch, contact) — idempotency armor for the campaign sweep.';

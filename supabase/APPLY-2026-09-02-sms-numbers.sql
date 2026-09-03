-- APPLY-2026-09-02-sms-numbers.sql
--
-- Dedicated SMS numbers, phase B: the table. One row per number a
-- business texts from. Numbers are bought on the PLATFORM's Twilio
-- account (never a reseller arrangement) and added to the one Messaging
-- Service, so they ride the existing 10DLC campaign. The practitioner
-- rents a service that includes a number.
--
-- Readers: sms_service.sender_for (outbound: the business's own line,
-- else TWILIO_PLATFORM_NUMBER) and sms_routing.route_inbound (inbound:
-- the To number IS the routing — no keyword, no disambiguation).
-- Writers: phase C's provisioning endpoints, service role only.
--
-- Apply by hand in the Supabase SQL editor. Ledger: docs/MIGRATIONS.md.
-- Rollback: drop table public.sms_numbers;  (nothing else references it)

create table if not exists public.sms_numbers (
  id                    uuid primary key default gen_random_uuid(),
  business_id           uuid not null references public.businesses(id) on delete cascade,
  phone_number          text not null unique
                        check (phone_number ~ '^\+[1-9][0-9]{6,14}$'),   -- E.164
  provider              text not null default 'twilio',
  provider_sid          text,                          -- PN… (null only for a hand-inserted test row)
  messaging_service_sid text,                          -- MG… it was attached to
  status                text not null default 'provisioning'
                        check (status in ('provisioning','active','suspended','releasing','released')),
  area_code             text,
  friendly_label        text,                          -- "Studio line"
  billing_ref           text,                          -- Stripe subscription item id, if add-on
  purchased_at          timestamptz not null default now(),
  release_after         timestamptz,                   -- grace window before the Twilio release
  released_at           timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

-- One live number per business. Released rows stay as history.
create unique index if not exists sms_numbers_one_live_per_business
  on public.sms_numbers (business_id)
  where status in ('provisioning','active','suspended','releasing');

-- Inbound lookup: To number → business.
create index if not exists sms_numbers_phone_live_idx
  on public.sms_numbers (phone_number)
  where status in ('active','suspended');

alter table public.sms_numbers enable row level security;

-- Owner-scoped SELECT — the same shape as sms_messages_owner_select
-- (applied, live, and a policy on a CHILD table referencing businesses
-- is the safe direction; the 42P17 recursion in docs/RLS_MODEL.md was a
-- policy ON businesses reaching back into a member table). No write
-- policies: every write goes through the service role.
drop policy if exists sms_numbers_owner_select on public.sms_numbers;
create policy sms_numbers_owner_select on public.sms_numbers
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = sms_numbers.business_id
      and b.owner_id = auth.uid()
  ));

comment on table public.sms_numbers is
  'Dedicated SMS numbers, one live row per business. Bought on the platform Twilio account and attached to the shared Messaging Service. status: provisioning → active → (suspended) → releasing → released.';

-- ── Verify ────────────────────────────────────────────────────────────
-- select count(*) from public.sms_numbers;                       -- 0 on first apply
-- select indexname from pg_indexes where tablename = 'sms_numbers';
--   → sms_numbers_pkey, sms_numbers_phone_number_key,
--     sms_numbers_one_live_per_business, sms_numbers_phone_live_idx
--
-- ── Try it before phase C exists ──────────────────────────────────────
-- Buy one SMS-capable local number in the Twilio console, add it to the
-- Messaging Service's sender pool, then:
--   insert into public.sms_numbers (business_id, phone_number, provider_sid, status)
--   values ('<business uuid>', '+1XXXXXXXXXX', 'PN…', 'active');
-- Text that number: it lands in that business's thread with no keyword.

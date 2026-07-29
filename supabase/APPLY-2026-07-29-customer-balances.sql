-- APPLY-2026-07-29-customer-balances.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- The drawdown ledger: what a customer has PAID FOR but not yet RECEIVED.
--
-- THE GAP
--   The vertical readiness audit scored "Money in" PARTIAL for all seven
--   verticals, on one finding: a repo-wide grep for sessions_remaining,
--   package_balance, drawdown, retainer_balance and session_credit returned
--   ZERO matches. Every vertical could SELL a package and none could track
--   its consumption. A coach sold six sessions and then counted them in
--   their head.
--
-- WHY A LEDGER AND NOT A COUNTER
--   A `sessions_remaining` column on contacts would be simpler and wrong.
--   It cannot answer "why is it four", cannot be audited, and races under
--   concurrent writes. This is money the customer has already handed over,
--   so it gets the same treatment the GL gets: append-only signed rows,
--   balance derived by summation, nothing ever mutated in place.
--
--   Positive delta = granted (they bought it).
--   Negative delta = consumed (they used it).
--   Balance       = SUM(delta). Always reconstructible from history.
--
-- ONE TABLE, FIVE MONEY MODELS
--   coach       package  / session : +6 on purchase, -1 per session
--   consultant  retainer / money   : +5000 on invoice, -750 per milestone
--   lawyer      retainer / hour    : +20 hours, -1.5 per time entry
--   contractor  deposit  / money   : +500 taken, -500 applied to final
--   any         gift_card / money  : +100 sold, -35 redeemed
--
-- NOT platform credits. public.credit_ledger is a DIFFERENT thing entirely
-- (AI action units a business buys from KMJ). This is a business's own
-- customer prepaying that business. Named customer_ledger to keep the two
-- from ever being confused in a query.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.customer_ledger (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,
  contact_id    uuid not null references public.contacts(id) on delete cascade,

  -- WHAT kind of prepaid thing this is.
  kind          text not null check (kind in
                  ('package','retainer','deposit','gift_card')),
  -- WHAT is being counted. 'money' balances carry currency; 'session' and
  -- 'hour' are counts and ignore it.
  unit          text not null check (unit in ('session','hour','money')),

  -- Signed. Positive grants, negative consumes. Never zero — a zero row
  -- is a bug, not a no-op, so the constraint says so.
  delta         numeric(14,4) not null check (delta <> 0),
  currency      text not null default 'usd',

  -- Why this row exists, in the practitioner's words. Required: an
  -- unexplained movement in a money ledger is worse than no ledger.
  reason        text not null,

  -- Provenance. All optional — a grant usually has an invoice, a draw
  -- usually has a booking, and a manual adjustment has neither.
  offering_id   uuid references public.offerings(id) on delete set null,
  invoice_id    uuid references public.invoices(id)  on delete set null,
  booking_id    uuid,
  session_id    uuid,

  -- Grants may expire; draws never do. Enforced below.
  expires_at    timestamptz,

  created_by    uuid,
  created_at    timestamptz not null default now(),

  -- A draw cannot carry an expiry — only the grant it draws against can.
  constraint customer_ledger_expiry_on_grants_only
    check (expires_at is null or delta > 0)
);

-- The read this table exists to serve: "what does this contact have left?"
create index if not exists idx_customer_ledger_balance
  on public.customer_ledger (business_id, contact_id, kind, unit);
create index if not exists idx_customer_ledger_biz_created
  on public.customer_ledger (business_id, created_at desc);
-- Partial index for the expiry sweep — only grants can expire.
create index if not exists idx_customer_ledger_expiring
  on public.customer_ledger (business_id, expires_at)
  where expires_at is not null;

alter table public.customer_ledger enable row level security;

-- Owner-scoped, matching the pattern used by chief_scheduled_actions.
-- The server writes through the service role; the owner reads their own.
drop policy if exists customer_ledger_owner_select on public.customer_ledger;
create policy customer_ledger_owner_select on public.customer_ledger
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = customer_ledger.business_id
      and b.owner_id = auth.uid()
  ));

comment on table public.customer_ledger is
  'Append-only drawdown ledger: what a customer prepaid and has not yet consumed. Positive delta grants, negative consumes, balance = SUM(delta). Covers coach packages, consultant/lawyer retainers, contractor deposits and gift cards. NOT public.credit_ledger, which is platform AI credits.';

-- ─── Balance view ───────────────────────────────────────────────────
-- Derived, never stored. security_invoker so the caller's RLS applies
-- rather than the view owner's — without it this view would leak every
-- business's balances to any authenticated user.
create or replace view public.customer_balances
with (security_invoker = true) as
select
  business_id,
  contact_id,
  kind,
  unit,
  currency,
  sum(delta)                                    as balance,
  sum(delta) filter (where delta > 0)           as granted,
  -abs(sum(delta) filter (where delta < 0))     as consumed,
  max(created_at)                               as last_activity_at,
  min(expires_at) filter (where expires_at is not null and delta > 0)
                                                as next_expiry_at
from public.customer_ledger
group by business_id, contact_id, kind, unit, currency;

comment on view public.customer_balances is
  'Derived balances per (business, contact, kind, unit). security_invoker so owner RLS on customer_ledger applies.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select
  (select count(*) from information_schema.tables
    where table_schema='public' and table_name='customer_ledger')  as ledger_ok,
  (select count(*) from information_schema.views
    where table_schema='public' and table_name='customer_balances') as view_ok;

-- APPLY-2026-07-31-barber-money.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- The barber/salon money model — deposits, tips, no-show fees.
--
-- offerings gains four columns:
--   requires_deposit   — booking checkout charges a deposit instead of
--                        the full price when true
--   deposit_type       — 'percent' (deposit_amount = % of price) or
--                        'flat' (deposit_amount = dollars)
--   deposit_amount     — numeric; interpreted per deposit_type
--   no_show_fee_cents  — >0 means the booking checkout stores the card
--                        (setup_future_usage=off_session) and the
--                        operator can charge the fee from Sessions via
--                        POST /payments/charge-no-show. NEVER automatic.
--
-- Deposit math lives server-side in
-- stripe_checkout_helpers.compute_deposit_cents (percent rounds to the
-- cent; a computed deposit >= the full price degrades to a normal
-- full-price checkout). Code FAILS SOFT before this migration applies:
-- missing columns read as no-deposit / no-fee.
--
-- Tips need NO schema: the tip is a separate Stripe line item +
-- metadata[tip_cents], mirrored into module_entries.data.tip_cents by
-- the webhook (module_entries.data is jsonb).
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

alter table public.offerings
  add column if not exists requires_deposit boolean not null default false;

alter table public.offerings
  add column if not exists deposit_type text
    check (deposit_type in ('percent', 'flat'));

alter table public.offerings
  add column if not exists deposit_amount numeric
    check (deposit_amount is null or deposit_amount >= 0);

alter table public.offerings
  add column if not exists no_show_fee_cents integer
    check (no_show_fee_cents is null or no_show_fee_cents >= 0);

comment on column public.offerings.requires_deposit is
  'Booking checkout charges the computed deposit instead of the full price. Remainder is collected at the visit.';
comment on column public.offerings.deposit_type is
  '''percent'' → deposit_amount is a percentage of current_price; ''flat'' → deposit_amount is dollars.';
comment on column public.offerings.deposit_amount is
  'Interpreted per deposit_type. Deposit cents are always computed server-side (compute_deposit_cents).';
comment on column public.offerings.no_show_fee_cents is
  'When >0, checkout stores the card on the connected account (disclosed at booking) and the operator may charge this fee via /payments/charge-no-show. Operator-triggered only, never automatic.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expect: 4 rows, one per new column.
select column_name, data_type, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'offerings'
  and column_name in ('requires_deposit', 'deposit_type',
                      'deposit_amount', 'no_show_fee_cents')
order by column_name;

-- Expect: the three check constraints present (deposit_type,
-- deposit_amount, no_show_fee_cents).
select conname
from pg_constraint
where conrelid = 'public.offerings'::regclass
  and (conname like '%deposit%' or conname like '%no_show%');

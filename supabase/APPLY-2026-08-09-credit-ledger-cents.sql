-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-08-09 — credit_ledger.cents (pack purchases as REVENUE)
--
-- credit_ledger records how many UNITS moved. It has never recorded
-- how much MONEY moved. margin.py says so in its own docstring:
--
--     "There is no table anywhere in this service recording a
--      credit-pack PURCHASE — usage_grants records units granted, not
--      money taken — so pack revenue cannot be counted here."
--
-- So the margin panel reports subscriptions only, and real margin is
-- understated by exactly the value of every pack ever sold.
--
-- The price is technically derivable — `source` is 'stripe:pack_medium'
-- and pricing_config.credit_packs() knows what medium costs — but only
-- the price TODAY. Packs have already been repriced once (#448/#450
-- rescaled all three), so deriving historical revenue from the current
-- list would restate past months every time a price changes. That is
-- the same class of error api_usage_logger already guards against:
-- "old rows keep their captured cost".
--
-- So the amount actually charged is captured on the row, at purchase.
--
-- Nullable on purpose. Rows written before this column existed cannot
-- be back-filled with a fact nobody recorded, and inventing one from
-- today's price list would be a guess wearing the costume of a
-- measurement. margin.py reports captured and estimated pack revenue
-- SEPARATELY for exactly this reason.
--
-- Safe to re-run. Adding a nullable column takes no table rewrite and
-- no lock worth worrying about at this size.
-- ══════════════════════════════════════════════════════════════════

alter table public.credit_ledger
  add column if not exists cents integer;

comment on column public.credit_ledger.cents is
  'Money actually charged for this row, in cents, captured at the time '
  'of purchase. Set for kind=purchase written after 2026-08-09. NULL '
  'for grants and burns (no money moves) and for purchases predating '
  'this column — margin.py estimates those from the current price list '
  'and reports them separately rather than mixing measured with '
  'inferred revenue.';

-- Money never moves for a grant or a burn. A non-null cents on either
-- would mean something has misunderstood the ledger, and it would land
-- in the revenue number, so it is refused at the table rather than
-- trusted to every future writer.
alter table public.credit_ledger
  drop constraint if exists credit_ledger_cents_only_on_purchase;

alter table public.credit_ledger
  add constraint credit_ledger_cents_only_on_purchase check (
    cents is null or (kind = 'purchase' and cents > 0)
  );

-- margin.py sums purchases over a date window.
create index if not exists credit_ledger_purchase_window_idx
  on public.credit_ledger (created_at desc)
  where kind = 'purchase';

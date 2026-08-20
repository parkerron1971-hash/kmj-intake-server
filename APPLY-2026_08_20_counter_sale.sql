-- APPLY-2026_08_20_counter_sale.sql
-- THE TILL — a sale rung up at the counter.
--
-- WHY THERE IS NO counter_sales TABLE
--   A counter sale IS an order. Same rows the storefront writes, with
--   source='counter'. That is the whole design: it inherits the GL
--   mapping, the refund machinery, the Orders list, the revenue reports
--   and the audit triggers, all of which already exist and are already
--   tested. A second money table would have meant a second version of
--   every one of those, and the second version is the one that drifts.
--
-- WHY payment_method IS LOAD-BEARING AND NOT DECORATION
--   gl_engine._order_cash_account reads it to decide where the money
--   landed. Store checkout is Stripe, so it debits Stripe Clearing
--   (1150) and a payout clears it later. Cash over a counter never
--   passes through our Stripe account, so NO payout is coming — booking
--   it to 1150 would leave the clearing account permanently out by the
--   value of every counter sale ever rung up. Cash and a card on the
--   shop's own reader debit Cash (1000), exactly as invoices already do.
--
--   Existing rows default to source='store' and a NULL payment_method,
--   which _order_cash_account reads as "the store flow, always Stripe" —
--   so every order written before today keeps the books it already had.
--
-- Status: APPLIED to production 2026-08-20 via the Management API.

alter table orders add column if not exists source text not null default 'store';
alter table orders add column if not exists payment_method text;

-- "What did we take at the counter today" is the one question this
-- makes people ask, and it should not scan the whole orders table.
create index if not exists orders_business_source_idx
  on orders (business_id, source, created_at desc);

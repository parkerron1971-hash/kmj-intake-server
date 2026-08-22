-- APPLY-2026_08_22_chief_can_reorder.sql
-- ─────────────────────────────────────────────────────────────────────
-- ONE TAP, AND WHO IT IS ALLOWED FOR.
--
-- Today a low-stock alert says "tap and Chief drafts the purchase
-- order". The tap produces a preview, and sending it is a second,
-- separate act. For a vendor somebody orders from every month that is
-- one step too many — the deciding was done when the reorder point was
-- set.
--
-- WHAT CHANGES, AND WHAT DOES NOT
--   The notification's action becomes send_purchase_order instead of
--   draft_purchase_order, for vendors the owner has explicitly enabled.
--   One tap sends.
--
--   Nothing about the trust model moves. send_purchase_order is class C
--   and stays class C — proposal-only, never unprompted. The
--   /agents/notifications/{id}/act rail already executes class C
--   deliberately, and the registry says why: "Clicking 'Yes, do that' IS
--   the approval, so class C executes here exactly as it does in chat."
--   A tap is a person deciding. Nothing here sends unattended, and this
--   is NOT the outbox/class-B change that would allow that.
--
-- WHY A PER-VENDOR SWITCH RATHER THAN A GLOBAL ONE
--   "Chief may send orders" is not a property of a business, it is a
--   property of a relationship. You know Northwind, you have an account
--   with them, you order the same hoodies every month — a tap is plenty.
--   The vendor you found last week and have never spoken to is a
--   different question, and one setting cannot answer both.
--
-- DEFAULT FALSE, ALWAYS. Nobody is opted into a one-tap send by an
-- upgrade. The owner turns it on per vendor, and only the owner can.
--
-- WHAT THE ROUTER ENFORCES ON TOP (see suppliers_router):
--   * a vendor with no email address cannot have it turned on — the tap
--     would fail at the send, which is a worse experience than the
--     button never appearing
--   * the sweep only offers the one-tap send when a reorder QUANTITY is
--     on file, because the notification has to be able to say exactly
--     what one tap will order. "Tap to send an order" without a number
--     is asking for approval of something unstated.
--
-- Status: APPLIED to production 2026-08-22 via the Management API.
-- Verified: column present, default false.

alter table public.suppliers
  add column if not exists chief_can_reorder boolean not null default false;

comment on column public.suppliers.chief_can_reorder is
  'Owner granted: a low-stock alert for a product this vendor supplies '
  'offers to SEND the purchase order on one tap, rather than drafting it '
  'for a second confirmation. The tap is still the approval — this does '
  'not make anything unattended.';

-- The sweep asks "can this vendor be one-tapped" per business, so the
-- partial index keeps that to the few rows that say yes.
create index if not exists suppliers_chief_can_reorder_idx
  on public.suppliers (business_id) where chief_can_reorder;

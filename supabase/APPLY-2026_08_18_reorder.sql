-- THE REORDER BRAIN (2026-08-18)
--
-- Chief watches stock and drafts the purchase order before the
-- practitioner knew they were low. These five columns are the whole
-- data model: a per-offering reorder point, how many to order, who to
-- order from, and the duplicate-order guard.
--
-- reorder_pending_at is the guard: stamped when a PO goes out, cleared
-- when a restock lifts inventory_qty back above reorder_at. While it is
-- set, the sweep skips the offering — a standing low-stock condition
-- with an outstanding order is not a new alarm.
--
-- Columns on offerings (not a new table): inventory already lives there
-- (inventory_qty, arc 27), and RLS/owner policies on offerings carry
-- over with zero new policy surface. A suppliers entity stays deferred,
-- same ruling as bills.vendor_name.

alter table public.offerings
  add column if not exists reorder_at         integer,
  add column if not exists reorder_qty        integer,
  add column if not exists supplier_name      text,
  add column if not exists supplier_email     text,
  add column if not exists reorder_pending_at timestamptz;

comment on column public.offerings.reorder_at is
  'Reorder point: when inventory_qty falls to/below this, the reorder sweep raises a Chief notification. Null = no reorder plan.';
comment on column public.offerings.reorder_qty is
  'Default quantity for a drafted purchase order.';
comment on column public.offerings.reorder_pending_at is
  'Stamped when a PO is sent to the supplier; cleared when a restock lifts stock above reorder_at. Suppresses duplicate reorder alerts.';

-- Arc 27 — e-commerce store MVP.
-- 1) offerings grow product fields (offerings stay the ONE catalog —
--    Kevin's unification ruling; the legacy products table is sunset
--    for new work, not migrated here).
-- 2) orders + order_items: multi-item purchases via Stripe Checkout on
--    the practitioner's connected account (source_type='order' rides
--    the existing webhook metadata pattern).
-- Service-role access only: RLS enabled, no policies (the
-- push_subscriptions convention) — all reads/writes go through backend
-- endpoints. No cross-table RLS anywhere (SECURITY DEFINER rule moot).

alter table offerings add column if not exists image_url text;
alter table offerings add column if not exists sku text;
alter table offerings add column if not exists inventory_qty integer;          -- null = untracked
alter table offerings add column if not exists requires_shipping boolean default false;
alter table offerings add column if not exists fulfillment_note text;          -- shown post-purchase (e.g. download/pickup instructions)

create table if not exists public.orders (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null,
  customer_email text,
  customer_name text,
  contact_id uuid,
  status text not null default 'pending'
    check (status in ('pending','paid','fulfilled','canceled','refunded')),
  subtotal_cents integer not null default 0,
  tax_cents integer not null default 0,
  shipping_cents integer not null default 0,
  total_cents integer not null default 0,
  currency text not null default 'usd',
  shipping_address jsonb,
  stripe_checkout_session_id text,
  stripe_payment_intent_id text,
  stripe_charge_id text,
  refund_amount_cents integer,
  refunded_at timestamptz,
  paid_at timestamptz,
  fulfilled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_orders_business on public.orders (business_id, created_at desc);
create index if not exists idx_orders_checkout_session on public.orders (stripe_checkout_session_id);

create table if not exists public.order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  offering_id uuid,
  name_at_purchase text not null,
  unit_amount_cents integer not null,
  quantity integer not null check (quantity > 0),
  created_at timestamptz not null default now()
);

create index if not exists idx_order_items_order on public.order_items (order_id);

alter table public.orders enable row level security;
alter table public.order_items enable row level security;

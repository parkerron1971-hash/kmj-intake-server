-- APPLY-2026_08_21_suppliers.sql
-- ─────────────────────────────────────────────────────────────────────
-- THE SOURCING DESK, STAGE 0 — a supplier becomes a thing.
--
-- WHAT WAS WRONG
--   A supplier was two free-text columns on a product:
--   offerings.supplier_name and offerings.supplier_email (the REORDER
--   BRAIN, 8/18). That works for exactly one purpose — addressing the
--   purchase-order email — and fails at everything else:
--
--     • six products from one vendor = the name typed six times, six ways
--     • no phone, no website, no MOQ, no lead time, no payment terms
--     • no "what do I buy from them", no order history
--     • nowhere for a quote to live
--     • nowhere for a SEARCH RESULT to be saved into
--
--   Every later stage of this arc (find vendors, send an RFQ, compare
--   quotes, land the winner) needs somewhere to put a vendor. This is
--   that somewhere. There is no AI in this migration on purpose.
--
-- THE COLUMNS ARE NOT REMOVED, AND THAT IS DELIBERATE
--   offerings.supplier_name/supplier_email stay, and stay written. They
--   become a DENORMALIZED CACHE of whichever supplier is primary for
--   that product, maintained by suppliers_router on every write that
--   could change it (link, unlink, primary change, supplier edit,
--   supplier delete).
--
--   Why cache instead of resolving the link at send time: the shipped
--   reorder brain — the hourly sweep, compose_purchase_order(), the
--   notification action payload, the Chief inventory verbs and the
--   frontend's own reorder dialog — all read those two columns today.
--   Repointing five live readers at a join is how a working feature
--   breaks on a Tuesday. The cache keeps every one of them correct while
--   the entity becomes the thing people actually edit. Stage 3 can move
--   the readers over one at a time, with the cache still right underneath.
--
-- ONE PRIMARY PER PRODUCT
--   Enforced in the database (partial unique index), not in the router,
--   because "who do I order this from" must have exactly one answer and
--   two code paths can both set it.
--
-- RLS mirrors chief_missions / the invoices trio exactly: owner ALL via
-- businesses, seat-member read, seat-writer write. The OWNER policy is
-- the one that must exist or every new signup is locked out of a table
-- they own — the new-table-owner-RLS-gap class, which has bitten twice.
--
-- Verified against production before shipping, inside a DO block that
-- ended in `raise exception` so every fixture row rolled back (leftover
-- check after: 0 offerings, 0 suppliers, 0 links). Three throwaway
-- products, one vendor typed two ways plus a second vendor:
--
--   vendors=2 links=3                    backfill created both, linked all
--   northwind_links=2 distinct=1         "Northwind Supply" and "northwind
--                                        supply" at the same address
--                                        collapsed to ONE vendor — the
--                                        whole reason this table exists
--   links_after_rerun=3                  idempotent, second pass added none
--   second_primary_rejected=ok           the partial unique index holds
--   second_quote_allowed=ok              a second NON-primary quote on the
--                                        same product is fine (stage 3)
--   owner_sees_vendors=3 links=4         the OWNER policy works
--   stranger_sees=0                      isolation holds
--
-- The backfill was a no-op on production the day it ran (no offering had
-- a supplier typed in yet — the reorder brain shipped 8/18), which is
-- exactly why it was proven against fixtures instead of assumed.
--
-- Status: APPLIED to production 2026-08-21 via the Management API.


-- ─── 1. The vendor ───────────────────────────────────────────────────

create table if not exists public.suppliers (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,

  name          text not null,
  website       text,
  email         text,
  phone         text,
  contact_name  text,

  -- What they supply, in the practitioner's own words. Free text on
  -- purpose: a fixed category list would be a lookup table that is wrong
  -- for the seventh vertical.
  categories    text[] not null default '{}',

  -- Free text, not numeric: a minimum is quoted as "$500" or "24 units"
  -- or "1 case" and normalizing that would lose what the vendor said.
  min_order       text,
  lead_time_days  int,
  payment_terms   text,
  notes           text,

  -- Provenance. 'sourcing' rows come from a web search and MUST carry
  -- the source_url they were found at — a vendor we cannot point back at
  -- a real page is a vendor we invented.
  source        text not null default 'manual'
                check (source in ('manual','sourcing','import')),
  source_url    text,
  found_at      timestamptz,

  -- candidate → contacted → active, or passed. A vendor typed in by hand
  -- is 'active' because the practitioner already knows they are real;
  -- 'candidate' is what a search result starts as.
  status        text not null default 'active'
                check (status in ('candidate','contacted','active','passed')),

  last_ordered_at timestamptz,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists suppliers_business_status_idx
  on public.suppliers (business_id, status);

-- Name lookup for "do I already have this vendor?" on save-from-search.
create index if not exists suppliers_business_name_idx
  on public.suppliers (business_id, lower(name));

alter table public.suppliers enable row level security;

drop policy if exists business_member_access on public.suppliers;
create policy business_member_access on public.suppliers
  for all
  using (business_id in (select id from public.businesses
                         where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses
                              where owner_id = auth.uid()));

drop policy if exists tenant_member_read on public.suppliers;
create policy tenant_member_read on public.suppliers
  for select
  using (is_business_member(business_id));

drop policy if exists tenant_writer_write on public.suppliers;
create policy tenant_writer_write on public.suppliers
  for all
  using (is_business_writer(business_id))
  with check (is_business_writer(business_id));

comment on table public.suppliers is
  'THE SOURCING DESK stage 0: a vendor as an entity rather than two '
  'free-text columns on a product. offerings.supplier_name/email are a '
  'denormalized cache of the primary link, maintained by suppliers_router.';


-- ─── 2. The link, and the per-product deal ───────────────────────────

create table if not exists public.offering_suppliers (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,
  offering_id   uuid not null references public.offerings(id) on delete cascade,
  supplier_id   uuid not null references public.suppliers(id) on delete cascade,

  -- The deal for THIS product from THIS vendor. Two vendors quoting the
  -- same product is the normal case, which is why the terms live on the
  -- link and not on either side of it.
  unit_cost       numeric(12,2),
  moq             int,
  sku_at_supplier text,
  notes           text,

  is_primary    boolean not null default false,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  unique (offering_id, supplier_id)
);

create index if not exists offering_suppliers_business_idx
  on public.offering_suppliers (business_id);
create index if not exists offering_suppliers_supplier_idx
  on public.offering_suppliers (supplier_id);

-- "Who do I order this from" has exactly one answer, enforced here so
-- that two code paths cannot both claim it.
create unique index if not exists offering_suppliers_one_primary_idx
  on public.offering_suppliers (offering_id) where is_primary;

alter table public.offering_suppliers enable row level security;

drop policy if exists business_member_access on public.offering_suppliers;
create policy business_member_access on public.offering_suppliers
  for all
  using (business_id in (select id from public.businesses
                         where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses
                              where owner_id = auth.uid()));

drop policy if exists tenant_member_read on public.offering_suppliers;
create policy tenant_member_read on public.offering_suppliers
  for select
  using (is_business_member(business_id));

drop policy if exists tenant_writer_write on public.offering_suppliers;
create policy tenant_writer_write on public.offering_suppliers
  for all
  using (is_business_writer(business_id))
  with check (is_business_writer(business_id));

comment on table public.offering_suppliers is
  'Which vendors supply which product, and on what terms. Two vendors '
  'quoting one product is the normal case, so unit_cost/moq/sku live on '
  'the link. Exactly one link per offering may be is_primary.';


-- ─── 3. Backfill: the columns become rows ────────────────────────────
--
-- Every distinct (supplier_name, supplier_email) already typed against a
-- product becomes one supplier row per business, and the product links to
-- it as primary. Idempotent — matches on lower(name) + lower(email) so
-- re-running adds nothing, and skips any offering that already has a link.
--
-- Matching is case-insensitive on both fields because the whole reason
-- this table exists is that the same vendor was typed six different ways.

do $backfill$
declare
  r          record;
  v_supplier uuid;
  n_new      int := 0;
  n_linked   int := 0;
begin
  for r in
    select o.business_id,
           btrim(coalesce(o.supplier_name, ''))  as sname,
           btrim(coalesce(o.supplier_email, '')) as semail
      from public.offerings o
     where btrim(coalesce(o.supplier_name, ''))  <> ''
        or btrim(coalesce(o.supplier_email, '')) <> ''
     group by 1, 2, 3
  loop
    select s.id into v_supplier
      from public.suppliers s
     where s.business_id = r.business_id
       and lower(coalesce(s.name, ''))  = lower(r.sname)
       and lower(coalesce(s.email, '')) = lower(r.semail)
     limit 1;

    if v_supplier is null then
      insert into public.suppliers (business_id, name, email, source, status)
      values (r.business_id,
              -- A row with only an address still needs a name to be
              -- findable; the address is the honest stand-in.
              case when r.sname <> '' then r.sname else r.semail end,
              nullif(r.semail, ''),
              'manual', 'active')
      returning id into v_supplier;
      n_new := n_new + 1;
    end if;

    insert into public.offering_suppliers
      (business_id, offering_id, supplier_id, is_primary)
    select o.business_id, o.id, v_supplier, true
      from public.offerings o
     where o.business_id = r.business_id
       and lower(btrim(coalesce(o.supplier_name, '')))  = lower(r.sname)
       and lower(btrim(coalesce(o.supplier_email, ''))) = lower(r.semail)
       -- Never fight an existing primary, and never double-link.
       and not exists (select 1 from public.offering_suppliers os
                        where os.offering_id = o.id)
    on conflict (offering_id, supplier_id) do nothing;

    get diagnostics n_linked = row_count;
  end loop;

  raise notice 'suppliers backfill: % vendors created', n_new;
end
$backfill$;

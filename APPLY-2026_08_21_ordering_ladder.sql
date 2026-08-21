-- APPLY-2026_08_21_ordering_ladder.sql
-- ─────────────────────────────────────────────────────────────────────
-- HOW CAN WE ACTUALLY ORDER FROM THIS VENDOR?
--
-- The sourcing arc can now find a vendor, ask them for a price, compare
-- the answers and pick one. The question it could not answer is the one
-- that decides how much work is left for the practitioner: when it is
-- time to buy, what actually happens?
--
-- THE LADDER, AND WHY IT IS A LADDER
--   Every vendor sits on exactly one rung, and every rung has a next
--   step — so a vendor is never a dead end, which is the point. Kevin's
--   ask: have a structure for the vendors that do NOT have the modern
--   setup, because that is almost all of them.
--
--     contact   we have a way to reach them and nothing more.
--               NEXT: ask whether they take purchase orders.
--     email_po  they accept a PO by email. Chief drafts it, the
--               practitioner approves, it sends. Works everywhere.
--               NEXT: open a trade account.
--     account   there is an account number with them and terms. The PO
--               carries the account number; they ship and invoice; the
--               invoice is paid on terms. This is the Grainger shape and
--               it is the realistic ceiling for most supply.
--               NEXT: nothing. This is a good place to stop.
--     agent     the site publishes a UCP manifest, so an order can be
--               constructed end to end.
--
--   The rungs are ordered by how little the practitioner has to do, NOT
--   by how good the vendor is. That distinction is the whole reason this
--   is not a star rating — see below.
--
-- WHY EVERY RUNG IS EVIDENCE, NEVER AN IMPRESSION
--   contact  — a phone, an email or a website exists
--   email_po — takes_email_po is true, because somebody said so or a PO
--              was actually sent and answered
--   account  — account_number is filled in. Theirs, never ours.
--   agent    — agent_checked_at is set and agent_ready is true, from a
--              live probe of /.well-known/ucp
--
--   Nothing here is derived from what a model thought about a website.
--   The one field that IS model-read (ordering_notes, from the sourcing
--   search) is explicitly a NOTE and never moves the rung on its own.
--
-- WHY THIS IS NOT A STAR RATING
--   A rating implies a judgement about the vendor's quality, which we
--   have not earned and do not want the liability for. This rates the
--   ORDERING RELATIONSHIP — how much of a purchase can be handled for
--   you — and a one-rung vendor may well be the best supplier in the
--   trade. The UI says "how you can order", never "how good they are".
--
-- WHAT THE PROBE ACTUALLY FOUND (2026-08-21), AND THE CORRECTION
--   First sample, sixteen ENTERPRISE suppliers — Grainger, Uline,
--   McMaster, SanMar, S&S, alphabroder, Vistaprint, Moo, Printful,
--   Printify, 4imprint, Faire, Alibaba, Staples, Office Depot,
--   WebstaurantStore: ZERO agent-ready. The obvious conclusion was "B2B
--   has not arrived", and it was WRONG, because the sample was.
--
--   Those names are enterprise distributors with EDI and their own
--   portals; they have no reason to adopt a retail-shaped protocol. The
--   suppliers these practitioners actually buy from are small and
--   mid-sized wholesalers, and a great many of those run on Shopify —
--   which is where UCP adoption is happening.
--
--   Second sample, sixteen beauty and barber wholesalers: FOUR were
--   agent-ready (annieinc.com, ebonyline.com, hairstopandshop.com,
--   kissusa.com) — about one in four. Including the very first vendor a
--   practitioner saved on this platform.
--
--   So `agent` is NOT a tripwire for some later year. It is live now for
--   a meaningful slice of real supply, and the rung exists because that
--   slice is already here.
--
-- Verified against production inside a DO block ending in `raise
-- exception`, so every fixture rolled back (leftovers after: 0 test
-- bills, 0 counters; the one supplier on the platform is a real one a
-- practitioner saved and was untouched):
--
--   contact / email_po / account / agent   each rung derived from its
--                                          own evidence, nothing else
--   po_no_email=contact                    ticking "takes email POs"
--                                          with no address to send one
--                                          to does NOT reach that rung —
--                                          the ladder is about what can
--                                          actually happen
--   agent_beats_account=agent              ordering holds
--   after_agent_false=account
--   after_account_cleared=contact          evidence removed, the rung
--                                          falls back on its own; no
--                                          stale state to clean up
--   po=PO-2026-0001,0002,0003 unique=3     the sequence cannot collide
--   bill_linked=1                          an invoice can point at both
--                                          the vendor and the order
--   bill_survives_vendor_delete=1
--   link_nulled=1                          deleting a vendor does NOT
--                                          delete their invoice — money
--                                          owed outlives the relationship
--
-- Status: APPLIED to production 2026-08-21 via the Management API.


-- ─── 1. What we know about ordering from them ────────────────────────

alter table public.suppliers
  -- THEIRS, NEVER OURS. The supplier issues a trade account number when
  -- an account is opened. It goes on the purchase order so their system
  -- can route it. Inventing one would put a fabricated identifier on a
  -- commercial document — ignored at best, and worse than that at worst.
  add column if not exists account_number text,

  -- Do they accept a purchase order by email? The rung that works for
  -- almost every vendor on earth and needs no integration at all.
  add column if not exists takes_email_po boolean,

  -- Free text, in their words: "PO by email to orders@, Net 30 after
  -- account approval". Read off their site during a sourcing search or
  -- typed in after a phone call. A NOTE — it never moves the rung.
  add column if not exists ordering_notes text,

  -- The live probe of /.well-known/ucp. checked_at separate from ready
  -- so "we asked and they don't" is distinguishable from "we never
  -- asked" — those are different facts and the UI shows them
  -- differently.
  add column if not exists agent_ready boolean,
  add column if not exists agent_checked_at timestamptz,
  add column if not exists agent_detail jsonb;

create index if not exists suppliers_account_number_idx
  on public.suppliers (business_id) where account_number is not null;


-- ─── 2. The rung, derived — never stored ─────────────────────────────
--
-- A generated column rather than a field somebody has to remember to
-- update. The evidence IS the answer, so there is no second place for it
-- to be wrong, and no router has to keep it honest.

alter table public.suppliers
  add column if not exists ordering_level text
  generated always as (
    case
      when agent_ready is true then 'agent'
      when coalesce(btrim(account_number), '') <> '' then 'account'
      when takes_email_po is true
        and coalesce(btrim(email), '') <> '' then 'email_po'
      else 'contact'
    end
  ) stored;

create index if not exists suppliers_ordering_level_idx
  on public.suppliers (business_id, ordering_level);

comment on column public.suppliers.ordering_level is
  'How much of a purchase can be handled for the practitioner: contact < '
  'email_po < account < agent. Derived from evidence only (an account '
  'number, a confirmed email-PO route, a live UCP probe) — never from an '
  'impression of a website. Rates the ORDERING RELATIONSHIP, not the '
  'vendor.';


-- ─── 3. The purchase order gets a number that cannot collide ─────────
--
-- compose_purchase_order built "PO-{yyyymmdd}-{first 6 of the PRODUCT
-- id}". Two orders of the same product on the same day therefore carried
-- the SAME purchase order number, which is the one thing a PO number
-- exists not to do — it is how a supplier's invoice finds its way back
-- to the order it is for. It was also keyed to the product rather than
-- the order, which stops making sense the moment a PO has two lines.
--
-- A per-business sequence: readable, ordered, and unique for the life of
-- the business.

create table if not exists public.po_counters (
  business_id uuid primary key references public.businesses(id) on delete cascade,
  next_number bigint not null default 1,
  updated_at  timestamptz not null default now()
);

alter table public.po_counters enable row level security;

drop policy if exists business_member_access on public.po_counters;
create policy business_member_access on public.po_counters
  for all
  using (business_id in (select id from public.businesses
                         where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses
                              where owner_id = auth.uid()));

-- Row-locked so two concurrent sends cannot take the same number. The
-- whole point of the sequence is uniqueness; a read-then-write would
-- hand it back at the worst possible moment.
create or replace function public.next_po_number(p_business_id uuid)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  n bigint;
begin
  insert into public.po_counters (business_id, next_number)
  values (p_business_id, 1)
  on conflict (business_id) do nothing;

  update public.po_counters
     set next_number = next_number + 1,
         updated_at = now()
   where business_id = p_business_id
  returning next_number - 1 into n;

  return 'PO-' || to_char(now() at time zone 'utc', 'YYYY') || '-'
         || lpad(n::text, 4, '0');
end;
$fn$;

revoke all on function public.next_po_number(uuid) from public;
revoke all on function public.next_po_number(uuid) from anon, authenticated;
grant execute on function public.next_po_number(uuid) to service_role;


-- ─── 4. The invoice can find the order it belongs to ─────────────────
--
-- bills.vendor_name is free text with no link to anything, so when a
-- supplier's invoice arrived there was nothing tying it back to the
-- purchase order that caused it. That is the last hop of
-- order -> invoice -> payment, and it was open. It is the hop that lets
-- Chief place orders without ever touching money: the invoice lands in
-- AP and is paid on terms like every other bill.

alter table public.bills
  add column if not exists supplier_id uuid references public.suppliers(id) on delete set null,
  add column if not exists po_number text;

create index if not exists bills_supplier_idx
  on public.bills (business_id, supplier_id) where supplier_id is not null;
create index if not exists bills_po_number_idx
  on public.bills (business_id, po_number) where po_number is not null;

comment on column public.bills.po_number is
  'The purchase order this bill answers. Set when a supplier invoice is '
  'matched to an order, so order -> invoice -> payment closes without '
  'Chief ever holding a payment method.';

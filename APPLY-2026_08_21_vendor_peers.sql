-- APPLY-2026_08_21_vendor_peers.sql
-- ─────────────────────────────────────────────────────────────────────
-- THE SOURCING DESK, STAGE 4 — "somebody else here works with them."
--
-- This is the one stage of the arc that is a PRIVACY decision wearing an
-- engineering costume, so the rules are enforced in the database rather
-- than left to whichever router happens to call it next.
--
-- WHAT IS AND IS NOT SHARED
--   Shared:     a vendor's DOMAIN. northwind.com is Northwind's public
--               identity, not a practitioner's private data.
--   Never shared: WHO buys from them. Not the business name, not the id,
--               not the count when the count is small enough to identify
--               anybody, not prices, not volumes, not what was ordered.
--
--   The private fact is the PAIRING — "this business buys from that
--   vendor" — and every rule below exists to stop that pairing being
--   recoverable from an aggregate.
--
-- FOUR RULES, ALL ENFORCED IN THE FUNCTION
--   1. OPT-IN. A business contributes only after saying so, in a row
--      with a timestamp on it. Silence is not consent, and a jsonb flag
--      would lose when it was given.
--   2. RECIPROCAL. You see the signal only while you are contributing to
--      it. Not a lever — a signal nobody feeds does not exist, and
--      reading what others share while sharing nothing is the shape that
--      makes people stop sharing.
--   3. k-ANONYMITY. Below PEER_MIN distinct OTHER businesses, the answer
--      is "not enough", never a number. The threshold is applied INSIDE
--      the function so the raw count cannot leak through a future caller
--      who forgets to check it.
--   4. NO ENUMERATION. The function answers about one domain at a time
--      and the router only passes domains the asking business already
--      holds. It is not a directory you can walk.
--
-- WHY TWO SLICES
--   Platform-wide fires sooner and is LESS identifying. Trade-scoped is
--   the more useful sentence but, on a platform whose largest trade
--   cohort is single digits today, would essentially never fire. Both
--   are returned, and each is independently gated at PEER_MIN — so the
--   trade line simply does not appear until that slice is itself
--   anonymous.
--
-- WHY 'active' ONLY
--   A 'candidate' vendor is something somebody found once. That is not
--   evidence anybody works with them, and counting it would turn one
--   practitioner's search results into everybody's "signal".
--
-- COLD START, STATED PLAINLY: on the day this ships there are 25
-- businesses and 0 suppliers, so this correctly reports "not enough"
-- for every vendor. That is the feature behaving, not a fault, and it is
-- why the surface says nothing at all rather than showing a zero.
--
-- Verified against production inside a DO block that ended in `raise
-- exception` — five throwaway businesses, one vendor written five
-- different ways. Leftover check after: 0 businesses, 0 suppliers,
-- 0 consents.
--
--   distinct_domains=1              five spellings (www, protocol, path,
--                                   query, and an email address) collapsed
--                                   to ONE vendor
--   [not_shared]  shared=f any=null not contributing -> no answer at all
--   [alone]       shared=t any=null opted in, nobody else -> nothing
--   [two_peers]   any=null trade=null   TWO is below k: null, not "2"
--   [three_any_two_trade] any=3 trade=null
--                                   platform-wide cleared while the trade
--                                   slice (2 agencies) stayed hidden —
--                                   the two slices gate independently
--   [four_any_three_trade] any=4 trade=3
--                                   trade cleared on its own. any=4 and
--                                   not 5 proves the asker is excluded
--   [after_E_opts_out] any=3 trade=null
--                                   withdrawal removes them from
--                                   everybody's count, immediately
--   [candidates_dont_count] any=null    only vendors somebody actually
--                                   works with ('active') are counted
--   [asker_opted_out] shared=f any=null reciprocity: stop sharing, stop
--                                   seeing
--   [unknown_domain] any=null       nothing to leak about a stranger
--
-- And the grant, checked directly: EXECUTE is false for anon and for
-- authenticated, true for service_role.
--
-- Status: APPLIED to production 2026-08-21 via the Management API.


-- ─── 1. The join key ─────────────────────────────────────────────────
--
-- A generated column rather than a router-maintained one on purpose:
-- this module already carries one denormalized cache (offerings.supplier_*)
-- that a router has to keep honest, and a second one would be a second
-- thing to forget. The database derives this from the row itself, so it
-- cannot drift.

alter table public.suppliers
  add column if not exists domain text
  generated always as (
    nullif(
      regexp_replace(
        regexp_replace(
          lower(coalesce(
            nullif(btrim(website), ''),
            split_part(coalesce(email, ''), '@', 2)
          )),
          '^\s*https?://', ''
        ),
        '^www\.|[/?#].*$', '', 'g'
      ),
      ''
    )
  ) stored;

create index if not exists suppliers_domain_idx
  on public.suppliers (domain) where domain is not null;

comment on column public.suppliers.domain is
  'The vendor''s public domain, derived from website or email. The join '
  'key for the stage-4 peer signal. A vendor''s domain is the vendor''s '
  'own identity; what stays private is which business buys from them.';


-- ─── 2. Consent, with a date on it ───────────────────────────────────

create table if not exists public.vendor_sharing_consent (
  business_id   uuid primary key references public.businesses(id) on delete cascade,
  opted_in_at   timestamptz not null default now(),
  -- Withdrawal is a timestamp, not a delete: "they turned it off in
  -- September" is a fact worth being able to answer.
  opted_out_at  timestamptz,
  actor         uuid,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

alter table public.vendor_sharing_consent enable row level security;

drop policy if exists business_member_access on public.vendor_sharing_consent;
create policy business_member_access on public.vendor_sharing_consent
  for all
  using (business_id in (select id from public.businesses
                         where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses
                              where owner_id = auth.uid()));

drop policy if exists tenant_member_read on public.vendor_sharing_consent;
create policy tenant_member_read on public.vendor_sharing_consent
  for select
  using (is_business_member(business_id));

comment on table public.vendor_sharing_consent is
  'Stage-4 opt-in. A business contributes to the anonymous vendor signal '
  'only while a row exists with opted_out_at null. Withdrawal is stamped, '
  'not deleted.';


-- ─── 3. The only way to read across businesses ───────────────────────
--
-- SECURITY DEFINER because the whole point is a count that crosses the
-- RLS boundary. That makes it the most dangerous function in the schema,
-- so it is also the narrowest: one domain in, two k-gated integers out,
-- nothing that names anybody, and EXECUTE revoked from anon and
-- authenticated so only the service role behind an authenticated router
-- can reach it at all.

create or replace function public.vendor_peer_counts(
  p_business_id uuid,
  p_domain      text,
  p_min         int default 3,
  out peers_any   int,
  out peers_trade int,
  out shared      boolean,
  out trade       text
)
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  v_type   text;
  n_any    int;
  n_trade  int;
begin
  peers_any := null;
  peers_trade := null;
  shared := false;
  trade := null;

  if p_domain is null or btrim(p_domain) = '' then
    return;
  end if;

  -- Rule 2: reciprocal. Not contributing means no answer, and we say so
  -- through `shared` rather than by returning a misleading zero.
  select true into shared
    from public.vendor_sharing_consent c
   where c.business_id = p_business_id and c.opted_out_at is null;
  if not coalesce(shared, false) then
    shared := false;
    return;
  end if;

  select b.type into v_type from public.businesses b where b.id = p_business_id;
  trade := nullif(btrim(coalesce(v_type, '')), '');

  -- Rule 1 + 3: opted-in businesses only, this one excluded, and only
  -- vendors somebody actually works with.
  select count(distinct s.business_id) into n_any
    from public.suppliers s
    join public.vendor_sharing_consent c
      on c.business_id = s.business_id and c.opted_out_at is null
   where s.domain = lower(btrim(p_domain))
     and s.status = 'active'
     and s.business_id <> p_business_id;

  if n_any >= p_min then
    peers_any := n_any;
  end if;

  if trade is not null then
    select count(distinct s.business_id) into n_trade
      from public.suppliers s
      join public.vendor_sharing_consent c
        on c.business_id = s.business_id and c.opted_out_at is null
      join public.businesses b
        on b.id = s.business_id
     where s.domain = lower(btrim(p_domain))
       and s.status = 'active'
       and s.business_id <> p_business_id
       and btrim(coalesce(b.type, '')) = trade;

    -- Independently gated: the trade line does not appear until the
    -- trade slice is itself anonymous.
    if n_trade >= p_min then
      peers_trade := n_trade;
    end if;
  end if;
end;
$fn$;

revoke all on function public.vendor_peer_counts(uuid, text, int) from public;
revoke all on function public.vendor_peer_counts(uuid, text, int) from anon, authenticated;
grant execute on function public.vendor_peer_counts(uuid, text, int) to service_role;

comment on function public.vendor_peer_counts(uuid, text, int) is
  'Stage-4 anonymous peer signal. Opt-in, reciprocal, k-anonymous (the '
  'threshold is applied here so a raw count cannot leak through a caller '
  'that forgets), and it names nobody. service_role only.';

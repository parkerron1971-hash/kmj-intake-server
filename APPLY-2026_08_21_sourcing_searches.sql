-- APPLY-2026_08_21_sourcing_searches.sql
-- ─────────────────────────────────────────────────────────────────────
-- THE SOURCING DESK, STAGE 1 — "who makes this?", written down.
--
-- WHY A SEARCH IS A ROW AND NOT A REQUEST/RESPONSE
--   A sourcing run costs several live web searches plus two model calls.
--   Three things follow from that, and all three need a table:
--
--   1. THE DAILY CAP. Kevin's ruling: sourcing runs on every tier and is
--      credit-metered. Metering alone is not a cap — a stuck client can
--      loop a paid action. Counting today's rows for this business is the
--      cap, and it lives in the same place as the receipts.
--   2. IT COMES BACK. A practitioner who ran "blank hoodies, 200/run" on
--      Tuesday should see Tuesday's answer on Wednesday without paying
--      for it again.
--   3. PROVENANCE. `sources` is the list of URLs the web search actually
--      returned, kept separately from the candidates the model wrote.
--      That is what makes the citation rule checkable AFTER the fact and
--      not just at the moment of the call.
--
-- WHAT IS DELIBERATELY NOT HERE
--   No vendor rows. A search result is not a vendor — it becomes one only
--   when the practitioner saves it, through /suppliers with
--   source='sourcing' and the source_url that the router already refuses
--   to accept as empty. A search that auto-created vendors would fill the
--   list with places nobody chose.
--
-- RLS mirrors suppliers exactly: owner ALL via businesses, seat-member
-- read, seat-writer write. The OWNER policy is the one that must exist or
-- every new signup is locked out of their own table.
--
-- Verified against production inside a DO block that ended in `raise
-- exception`, so every fixture rolled back (leftover check after: 0):
--
--   in_window=2 all_rows=3     the 24h cap window excluded a 30-hour-old
--                              run — the cap counts the right rows
--   jsonb_queryable=1          candidates round-trips as real jsonb, not
--                              as a quoted string, so `@>` works on it
--   owner_sees=3               the OWNER policy works
--   stranger_sees=0            isolation holds
--
-- Status: APPLIED to production 2026-08-21 via the Management API.

create table if not exists public.sourcing_searches (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,

  -- What they asked for, in their words. The prompt is built from this,
  -- and the history list shows it back to them verbatim.
  need          text not null,
  region        text,
  qty           int,
  budget_per_unit numeric(12,2),

  -- [{name, website, source_url, why, moq, region, contact_route}, ...]
  -- Every entry has passed the citation check: its source_url appeared in
  -- an actual web search result for THIS run.
  candidates    jsonb not null default '[]'::jsonb,

  -- Every URL the search returned, whether or not a candidate came from
  -- it. The check is `candidate.source_url ∈ sources`, so keeping the
  -- right-hand side is what makes the check auditable later.
  sources       jsonb not null default '[]'::jsonb,

  -- The honest paragraph about what this kind of search does and does not
  -- cover. Shown with the results, never hidden behind a tooltip.
  coverage_note text not null default '',

  -- How many the model proposed vs how many survived the citation check.
  -- A run where those differ a lot is the early warning that the prompt
  -- or the model drifted, and it is cheaper to notice here than in a
  -- support ticket.
  proposed_count  int not null default 0,
  dropped_count   int not null default 0,

  model         text,
  created_by    uuid,
  created_at    timestamptz not null default now()
);

create index if not exists sourcing_searches_business_time_idx
  on public.sourcing_searches (business_id, created_at desc);

alter table public.sourcing_searches enable row level security;

drop policy if exists business_member_access on public.sourcing_searches;
create policy business_member_access on public.sourcing_searches
  for all
  using (business_id in (select id from public.businesses
                         where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses
                              where owner_id = auth.uid()));

drop policy if exists tenant_member_read on public.sourcing_searches;
create policy tenant_member_read on public.sourcing_searches
  for select
  using (is_business_member(business_id));

drop policy if exists tenant_writer_write on public.sourcing_searches;
create policy tenant_writer_write on public.sourcing_searches
  for all
  using (is_business_writer(business_id))
  with check (is_business_writer(business_id));

comment on table public.sourcing_searches is
  'THE SOURCING DESK stage 1: one row per vendor search. Holds the daily '
  'cap, the re-readable answer, and the provenance (sources) that makes '
  'the citation rule checkable after the fact.';

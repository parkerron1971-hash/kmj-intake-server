-- APPLY-2026_08_21_search_breakdown.sql
-- ─────────────────────────────────────────────────────────────────────
-- THE SEARCH RESULT, IN PARTS.
--
-- coverage_note was one prose blob carrying four different jobs at once:
-- how well the web covers this trade, what was found and dropped, what
-- would beat the list, and a standing disclaimer. On screen it was a
-- paragraph nobody reads — Kevin's words: "it's a lot to read".
--
-- The content was good. The shape was wrong. Three of those jobs are
-- lists, and the fourth is not the model's to write.
--
--   coverage_note   stays, but SHORT — two sentences at most
--   left_out        [{what, why}] — the listicles and unverifiable pages
--                   that were deliberately not listed. This is the most
--                   trust-building thing on the page and it was buried
--                   mid-paragraph
--   better_routes   [{name, why}] — named trade distributors, a local
--                   decorator, a trade show. LEADS, not candidates: they
--                   carry no source_url, never pass the citation gate,
--                   and must render as visibly different from a found
--                   vendor. That is why they are their own column rather
--                   than more prose
--
-- The disclaimer moved OUT of the model's output entirely. It is
-- identical every time, it is a policy statement rather than a finding,
-- and having a model regenerate it each run costs tokens and risks it
-- drifting or being dropped. It is app chrome now.
--
-- Status: APPLIED to production 2026-08-21 via the Management API.

alter table public.sourcing_searches
  add column if not exists left_out jsonb not null default '[]'::jsonb,
  add column if not exists better_routes jsonb not null default '[]'::jsonb;

comment on column public.sourcing_searches.better_routes is
  'Leads that would beat the found list — named distributors, a local '
  'decorator, a trade show. NOT candidates: no source_url, never through '
  'the citation gate, and rendered as unverified leads.';

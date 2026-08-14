-- APPLY-2026_08_14_site_events_business.sql
--
-- THE LEAD ARC, follow-on — the top of the funnel.
--
-- ═══════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═══════════════════════════════════════════════════════════════════
--   site_events holds anonymous traffic for mysolutionist.app and
--   nothing else. It has no business_id, and /admin/traffic is gated to
--   PLATFORM_OWNER_EMAIL.
--
--   So a practitioner whose whole site was built by this system could
--   not answer "how many people visited, and how many of them became a
--   lead". WebsiteTraffic.tsx counts form submissions, bookings, link
--   clicks and downloads — every one of them a CONVERSION. The
--   denominator did not exist anywhere.
--
--   That is the last hole in the lead arc: PRs #574-581 made every lead
--   visible and measurable from the moment it arrives. This is the step
--   before arrival.
--
-- ═══════════════════════════════════════════════════════════════════
-- NULLABLE, DELIBERATELY
-- ═══════════════════════════════════════════════════════════════════
--   NULL means "the marketing site" — mysolutionist.app keeps writing
--   rows with no business_id and /admin/traffic keeps reading them
--   unchanged. One table, two tenants of it, no migration of history
--   and no second ingest path to keep in sync.
--
--   NOT a foreign key, on purpose. This column is written by an
--   anonymous public endpoint from a value baked into a page that
--   anyone can view-source. A real FK would turn a junk value into a
--   500 on a tracking beacon — and a tracking beacon must never be able
--   to fail loudly on somebody's website. site_analytics validates the
--   id against businesses before storing it and stores NULL when it
--   does not resolve, which is the same protection without the blast
--   radius.
--
-- ═══════════════════════════════════════════════════════════════════
-- THE PRIVACY CONTRACT IS UNCHANGED
-- ═══════════════════════════════════════════════════════════════════
--   site_analytics.py states it, and every clause still holds for
--   customer sites:
--     · no IP address stored
--     · no user-agent stored (read to drop bots, then dropped)
--     · no cookie ever set — session_id lives in sessionStorage and
--       dies with the tab, so it cannot follow anyone across visits
--     · referrer reduced to its HOST before storage
--   Adding a business_id says WHOSE SITE was visited. It says nothing
--   more about WHO visited, which is what keeps the no-cookie-banner
--   position honest for the practitioner as well as for Kevin.
--
-- SAFETY: additive, nullable, no default, no backfill, no rewrite, no
-- policy change. RLS stays as it is — service role writes, and reads go
-- through the owner-checked API rather than through PostgREST.

ALTER TABLE public.site_events
  ADD COLUMN IF NOT EXISTS business_id uuid;

COMMENT ON COLUMN public.site_events.business_id IS
  'Whose site was visited. NULL = mysolutionist.app (the marketing '
  'site), which is what every row held before 2026-08-14. Validated '
  'against businesses at ingest and stored NULL when it does not '
  'resolve — deliberately not a foreign key, because a tracking beacon '
  'must never be able to 500 on somebody''s website.';

-- The per-business read: one tenant, one window, newest first.
-- Partial, so the marketing site's rows (business_id IS NULL, the large
-- majority today) stay out of an index nothing queries that way.
CREATE INDEX IF NOT EXISTS site_events_business_ts_idx
  ON public.site_events (business_id, ts DESC)
  WHERE business_id IS NOT NULL;

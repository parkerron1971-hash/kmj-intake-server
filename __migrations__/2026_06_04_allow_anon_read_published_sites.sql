-- ─────────────────────────────────────────────────────────────────
-- Phase D.2.1 — Allow anon SELECT on published + booking_only sites
-- ─────────────────────────────────────────────────────────────────
-- Run via:  Supabase Studio → SQL editor → paste + Run
-- Idempotent. Defensive (uses DROP POLICY IF EXISTS).
--
-- What this does:
--   1. Ensures RLS is enabled on business_sites (no-op if already on).
--   2. Drops any prior version of this policy with the same name.
--   3. Creates a SELECT policy granting the anon role read access ONLY
--      to rows where status IN ('published','booking_only').
--      Drafts + archives stay invisible to anonymous visitors.
--
-- Why this is safe:
--   - Slug is the public identifier already exposed in URLs:
--     <slug>.mysolutionist.app is meant to be hit by anonymous users.
--   - The route filters by slug + limit 1, so anon can't enumerate
--     other practitioners' rows.
--   - Existing 'draft' rows remain owner-only via existing policies.
--   - 'booking_only' is the new D.2.1 status — practitioners get a
--     real public URL the moment they exist, even before they publish
--     a full MySite. The hosted page itself is gated by
--     settings.booking_page.published — anon can still SEE the row,
--     but render_not_published_page handles the not-published variant.
--
-- After running this, re-smoke:
--   curl -H "Host: embrace-the-shift.mysolutionist.app" \
--        https://kmj-intake-server-production.up.railway.app/
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE public.business_sites ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS public_can_read_published_sites ON public.business_sites;

CREATE POLICY public_can_read_published_sites
ON public.business_sites
FOR SELECT
TO anon
USING (status IN ('published', 'booking_only'));

-- Verify:
SELECT
    schemaname,
    tablename,
    policyname,
    roles,
    cmd,
    qual
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename  = 'business_sites'
  AND policyname = 'public_can_read_published_sites';

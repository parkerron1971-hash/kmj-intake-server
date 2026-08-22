-- APPLY-2026_08_22_signup_attribution.sql
-- GROWTH ARC Rung 1 — which door did each practitioner walk in through?
--
-- One nullable jsonb column per funnel stage, each holding the
-- whitelisted campaign blob lead_attribution.py builds (utm_*, gclid,
-- fbclid, ref, referrer_host, landing_path, captured_at, via). NULL
-- means "nothing to record" — never an empty object that reads like a
-- failed lookup.
--
--   marketing_leads.attribution — the /get-started application
--   waitlist.attribution        — the app's waitlist screen
--   businesses.attribution      — stamped once at creation; either sent
--                                 by the app (direct signup) or copied
--                                 from the lead/waitlist row by email
--                                 (the invite funnel crosses days and
--                                 devices, so the signup URL carries
--                                 nothing — email is the join key)
--   site_events.data            — marketing-site pageviews now carry the
--                                 session's campaign params, so visits
--                                 can be counted by channel next to the
--                                 signups they produced
--
-- marketing_leads has no migration file (created ad-hoc in Studio), so
-- its ALTER is guarded — a fresh environment without the table must not
-- fail the whole apply.

DO $$
BEGIN
  IF to_regclass('public.marketing_leads') IS NOT NULL THEN
    ALTER TABLE public.marketing_leads ADD COLUMN IF NOT EXISTS attribution jsonb;
  END IF;
END $$;

ALTER TABLE public.waitlist    ADD COLUMN IF NOT EXISTS attribution jsonb;
ALTER TABLE public.businesses  ADD COLUMN IF NOT EXISTS attribution jsonb;
ALTER TABLE public.site_events ADD COLUMN IF NOT EXISTS data jsonb;

-- Rollback:
-- ALTER TABLE public.marketing_leads DROP COLUMN IF EXISTS attribution;
-- ALTER TABLE public.waitlist    DROP COLUMN IF EXISTS attribution;
-- ALTER TABLE public.businesses  DROP COLUMN IF EXISTS attribution;
-- ALTER TABLE public.site_events DROP COLUMN IF EXISTS data;

SELECT 'signup_attribution ready' AS status;

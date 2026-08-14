-- APPLY-2026_08_14_lead_attribution.sql
--
-- THE LEAD ARC PR 6 — where the lead came from.
--
-- ═══════════════════════════════════════════════════════════════════
-- source_detail: A COLUMN THREE FILES ALREADY USE AND NONE OF THEM
-- COULD HAVE BEEN WORKING
-- ═══════════════════════════════════════════════════════════════════
--
--   BuildAnalytics.tsx:88   select=id,status,lead_score,source_detail,source
--   WebsiteTraffic.tsx:123  select=id,status,lead_score,source_detail,source
--   OperationsDashboard.tsx:994   POST /contacts { ..., source_detail: 'dashboard_quick_add' }
--
-- It has never existed. PostgREST rejects an unknown column outright —
-- this repo already learned that the hard way and wrote it down, in
-- booking_widget_router.py:1082: "'lifecycle_stage' is NOT a real column
-- on contacts — the prior typo caused PGRST204 and a 500 on the widget
-- submission."
--
-- So:
--   · both analytics reads 400. `intakeContacts` is permanently empty,
--     which is why every form on the funnel shows avg lead score "—"
--     and conversion "—" no matter how many leads it has produced.
--   · the dashboard's quick-add-a-lead button has NEVER worked. It
--     posts the column, gets a 400, and shows "Couldn't add:".
--
-- The column is the fix for all three at once.
--
-- ═══════════════════════════════════════════════════════════════════
-- attribution: WHERE THEY ACTUALLY CAME FROM
-- ═══════════════════════════════════════════════════════════════════
--
-- WebsiteTraffic.tsx:188 computes a form's top traffic source as
--
--     ev.data?.utm_source || ev.data?.referrer_host || ev.data?.referrer
--                                                   || 'direct'
--
-- and NOTHING IN EITHER REPO WRITES ANY OF THE THREE. Every form has
-- therefore reported "direct" since the day that line was written — a
-- UI stating a fact it has no way to know.
--
-- lead_attribution.py fills it in, and does it SERVER-SIDE from the
-- Referer header rather than asking the client. The contact form is
-- emitted from at least four renderers (contact_footer, movement,
-- sections/contact, and whatever the builder's LLM writes), so any
-- design that needs every client to cooperate would be partially
-- deployed forever.
--
-- PRIVACY. Referrers are reduced to a HOST before storage — the same
-- doctrine site_analytics.py already states: "Full referrer URLs leak
-- search terms." Query strings are dropped except an explicit
-- whitelist of campaign keys (utm_*, gclid, fbclid, ref), because a
-- query string on somebody else's page can contain anything at all.
--
-- SAFETY. Both columns additive and nullable. No default, no backfill,
-- no table rewrite, no policy change.

ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS source_detail text;

ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS attribution jsonb;

COMMENT ON COLUMN public.contacts.source_detail IS
  'Which specific thing produced this lead, within contacts.source — '
  'the intake form''s name, the page path a website form sat on, the '
  'booking module. The funnel groups per-form conversion by this.';

COMMENT ON COLUMN public.contacts.attribution IS
  'Campaign and arrival context captured at the door, server-side from '
  'the Referer header: {utm_source, utm_medium, utm_campaign, utm_term, '
  'utm_content, gclid, fbclid, ref, landing_host, landing_path, '
  'referrer_host, device, captured_at}. Referrers are stored as HOST '
  'only and query strings are dropped except the campaign whitelist — '
  'full referrer URLs leak search terms.';

-- Per-form rollups on the funnel read source_detail within a business.
CREATE INDEX IF NOT EXISTS contacts_source_detail_idx
  ON public.contacts (business_id, source_detail)
  WHERE source_detail IS NOT NULL;

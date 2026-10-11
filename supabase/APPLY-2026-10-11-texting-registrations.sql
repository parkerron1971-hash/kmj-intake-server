-- APPLY-2026-10-11-texting-registrations.sql
-- ─────────────────────────────────────────────────────────────────────
-- Texting under each business's own name (Twilio ISV), step 1
-- (docs/plans/ISV_TEXTING_PLAN_2026-10-11.md; Kevin, 2026-10-11: "write up
-- the isv build plan and start it"). texting_registration.py.
--
--   texting_registrations  one row per business: the owner's answers for
--                          Twilio (legal name, type, address, website, the
--                          person Twilio may contact, whether there is an
--                          EIN — NEVER the EIN itself), the status, and from
--                          step 3 the Twilio ids and a rejection's reason.
--
-- Service role only. Idempotent.
--
-- Rollback:
--   DROP TABLE IF EXISTS public.texting_registrations;
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.texting_registrations (
  business_id  uuid PRIMARY KEY REFERENCES public.businesses(id) ON DELETE CASCADE,
  answers      jsonb NOT NULL DEFAULT '{}'::jsonb
               CONSTRAINT texting_registrations_no_ein CHECK (NOT (answers ? 'ein')),
  status       text NOT NULL DEFAULT 'draft'
               CONSTRAINT texting_registrations_status CHECK (status IN
                 ('draft', 'submitted', 'brand_pending', 'campaign_pending', 'approved', 'failed')),
  twilio       jsonb NOT NULL DEFAULT '{}'::jsonb,
  failure      text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.texting_registrations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.texting_registrations FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.texting_registrations TO service_role;

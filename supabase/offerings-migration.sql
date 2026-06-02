-- ═══════════════════════════════════════════════════════════════════════
-- offerings — canonical pricing layer (Phase C.1.2)
-- ═══════════════════════════════════════════════════════════════════════
-- Promotes pricing to a first-class business-level concept that every
-- archetype with pricing-bearing entities references rather than
-- duplicates. Replaces the inline `agent_config.services` array shipped
-- in C.1.1 for booking_calendar; future archetypes (Loyalty, Invoicing
-- referenced offerings, Sessions, Courses, etc.) reference offerings by
-- id via the new `offering_ref` field type.
--
-- Pattern: reference + denormalize at moment of commitment (P5).
--   Each module_entries.data row that uses an offering stores BOTH:
--     offering_id          — live reference (current_price, name)
--     price_at_booking     — denormalized at create-time, frozen
--     service_name_at_booking   — same
--     duration_min_at_booking   — same
--   When the practitioner edits the offering's current_price, existing
--   entries preserve the historical price; future bookings use the new.
--
-- ─── EXPLICIT EXCLUSION: donations / giving ────────────────────────
-- The category CHECK below INTENTIONALLY does NOT include 'donation'.
-- Giving/donations live in their own restricted domain (Fork 25 Giving
-- guard) — a different access-control + recordkeeping model. Mixing
-- donations into offerings would blur tax + reporting + privacy lines.
-- If a future practitioner archetype needs donation-tracking, it goes
-- through the restricted-modules surface, NOT here.
--
-- ─── EXPLICIT EXCLUSION: platform subscription pricing ────────────
-- This table is for per-business practitioner offerings ONLY. The
-- Solutionist platform's $X/mo subscription tiers are Stripe-managed
-- Products/Prices on the Solutionist account itself, surfaced via
-- billing_status view. Those are orthogonal. No commingling.
--
-- NON-DESTRUCTIVE + IDEMPOTENT.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS public.offerings (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  name          text NOT NULL,
  slug          text NOT NULL,
  description   text,
  category      text NOT NULL,
  current_price numeric,                      -- nullable for "contact for quote"
  currency      text NOT NULL DEFAULT 'usd',
  duration_min  int,                          -- service/session-type; null for products
  show_price_to_customer boolean NOT NULL DEFAULT true,
  is_active     boolean NOT NULL DEFAULT true,
  archived_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  -- 'donation' deliberately not in this list — see header comment.
  CONSTRAINT offerings_category_check CHECK (category IN (
    'service',    -- haircut, massage, consultation
    'session',    -- coaching session, lesson, therapy
    'event',      -- retreat, workshop, conference (one-time)
    'course',     -- self-paced or cohort-based education
    'product',    -- physical or digital good
    'package',    -- bundle of other offerings (e.g. 5-session pack)
    'custom'      -- catch-all for shapes not yet named — surfaces a flag for review
  )),
  CONSTRAINT offerings_price_nonneg CHECK (current_price IS NULL OR current_price >= 0),
  CONSTRAINT offerings_duration_nonneg CHECK (duration_min IS NULL OR duration_min > 0)
);

-- Stable kebab-case ref per business — Bookings field stores offering_id,
-- but the slug is the human-stable handle for upgrades + cross-arc refs.
CREATE UNIQUE INDEX IF NOT EXISTS offerings_biz_slug_uniq
  ON public.offerings (business_id, lower(slug));

-- Fast lookup by category + active for the widget's runtime resolve.
CREATE INDEX IF NOT EXISTS offerings_biz_cat_active_idx
  ON public.offerings (business_id, category) WHERE is_active = true;

ALTER TABLE public.offerings ENABLE ROW LEVEL SECURITY;

-- Practitioner-only access — same pattern as business_customers + the
-- rest of the RLS-aware tables (module_specs, workflow_definitions, etc).
DROP POLICY IF EXISTS offerings_owner_all ON public.offerings;
CREATE POLICY offerings_owner_all ON public.offerings
  FOR ALL TO authenticated
  USING  (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()))
  WITH CHECK (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));

-- Anon role has NO policy → no direct REST access. Customer-facing reads
-- of offerings go through the booking widget endpoints (/widgets/booking/...)
-- which use service-role internally and scope by business_id + token claims.

COMMIT;

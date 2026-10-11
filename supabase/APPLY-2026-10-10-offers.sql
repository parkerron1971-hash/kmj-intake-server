-- APPLY-2026-10-10-offers.sql
-- ─────────────────────────────────────────────────────────────────────
-- Offers (the Reach plan's step 3; Kevin, 2026-10-10: "go" on the four
-- money defaults). An offer is a code, a link and a QR code in one
-- (offers.py): "$10 off your first cut", for anyone / a first visit /
-- regulars, optionally only in slow hours, from a start day to an end day,
-- once per person, up to N uses.
--
--   offers           the owner's offers. The discount is decided by our own
--                    booking page (who, when, how many), frozen on the
--                    booking (module_entries.data.offer), and taken off the
--                    online payment only when the booking is paid in full
--                    online; otherwise it is taken off at the counter.
--   marketing_links  an offer's link (part 0, to share) and its printed QR
--                   (part 1, counted apart): kind 'offer'.
--
-- Service role only. Idempotent.
--
-- Rollback:
--   DROP TABLE IF EXISTS public.offers;
--   ALTER TABLE public.marketing_links DROP CONSTRAINT IF EXISTS marketing_links_kind;
--   ALTER TABLE public.marketing_links ADD CONSTRAINT marketing_links_kind CHECK (kind IN ('campaign', 'journey'));
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.offers (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id     uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  code            text NOT NULL CONSTRAINT offers_code CHECK (code ~ '^[A-Z0-9][A-Z0-9-]{1,23}$'),
  kind            text NOT NULL CONSTRAINT offers_kind CHECK (kind IN ('amount_off', 'percent_off', 'free_item')),
  amount_cents    integer CONSTRAINT offers_amount CHECK (amount_cents IS NULL OR amount_cents BETWEEN 1 AND 10000000),
  percent         integer CONSTRAINT offers_percent CHECK (percent IS NULL OR percent BETWEEN 1 AND 100),
  free_item       text CONSTRAINT offers_free_item CHECK (free_item IS NULL OR char_length(free_item) BETWEEN 1 AND 80),
  title           text NOT NULL CONSTRAINT offers_title CHECK (char_length(title) BETWEEN 1 AND 120),
  who             text NOT NULL DEFAULT 'anyone' CONSTRAINT offers_who CHECK (who IN ('anyone', 'first_visit', 'regulars')),
  hours           jsonb,
  starts_on       date,
  ends_on         date,
  one_per_person  boolean NOT NULL DEFAULT true,
  max_uses        integer CONSTRAINT offers_max_uses CHECK (max_uses IS NULL OR max_uses BETWEEN 1 AND 100000),
  status          text NOT NULL DEFAULT 'on' CONSTRAINT offers_status CHECK (status IN ('on', 'paused')),
  source          text NOT NULL DEFAULT 'owner' CONSTRAINT offers_source CHECK (source IN ('owner', 'referral')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT offers_code_unique UNIQUE (business_id, code),
  CONSTRAINT offers_window CHECK (ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on),
  CONSTRAINT offers_what CHECK (
    (kind = 'amount_off' AND amount_cents IS NOT NULL) OR
    (kind = 'percent_off' AND percent IS NOT NULL) OR
    (kind = 'free_item' AND free_item IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS offers_business ON public.offers (business_id, created_at DESC);

ALTER TABLE public.offers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.offers FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.offers TO service_role;

ALTER TABLE public.marketing_links DROP CONSTRAINT IF EXISTS marketing_links_kind;
ALTER TABLE public.marketing_links ADD CONSTRAINT marketing_links_kind CHECK (kind IN ('campaign', 'journey', 'offer'));

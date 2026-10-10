-- APPLY-2026-10-09-journeys.sql
-- ─────────────────────────────────────────────────────────────────────
-- Outreach that runs by itself (the Reach plan's step 2; Kevin, 2026-10-09:
-- "Build now, texts after"): an after-visit review ask on every plan, and
-- win-back, rebook and birthday notes from the Week level up
-- (outreach_journeys.py).
--
--   journey_sends   one row per note a journey sent: whose (business_id),
--                   which journey, to whom (contact_id), why (key: the visit
--                   it follows, the last visit it answers, the birthday's
--                   year), and how (channel). UNIQUE (business_id, journey,
--                   key): the sweep claims the row BEFORE it sends, so a
--                   crash or a second worker can never send the same note
--                   twice (a lost note costs less than a duplicate).
--   marketing_links a journey's {{link}} is a tracked link like a campaign
--                   touch's (business_marketing_sent_links): kind 'journey'.
--
-- Service role only. Idempotent.
--
-- Rollback:
--   DROP TABLE IF EXISTS public.journey_sends;
--   ALTER TABLE public.marketing_links DROP CONSTRAINT IF EXISTS marketing_links_kind;
--   ALTER TABLE public.marketing_links ADD CONSTRAINT marketing_links_kind CHECK (kind IN ('campaign'));
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.journey_sends (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  journey      text NOT NULL CONSTRAINT journey_sends_journey CHECK (journey IN ('review_ask', 'win_back', 'rebook', 'birthday')),
  contact_id   uuid NOT NULL,
  key          text NOT NULL CONSTRAINT journey_sends_key CHECK (char_length(key) BETWEEN 1 AND 120),
  channel      text NOT NULL CONSTRAINT journey_sends_channel CHECK (channel IN ('email', 'sms')),
  sent_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT journey_sends_once UNIQUE (business_id, journey, key)
);

CREATE INDEX IF NOT EXISTS journey_sends_business ON public.journey_sends (business_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS journey_sends_contact ON public.journey_sends (business_id, contact_id, journey);

ALTER TABLE public.journey_sends ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.journey_sends FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.journey_sends TO service_role;

ALTER TABLE public.marketing_links DROP CONSTRAINT IF EXISTS marketing_links_kind;
ALTER TABLE public.marketing_links ADD CONSTRAINT marketing_links_kind CHECK (kind IN ('campaign', 'journey'));

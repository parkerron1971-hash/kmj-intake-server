-- APPLY-2026-10-11-refer-a-friend.sql
-- ─────────────────────────────────────────────────────────────────────
-- Refer a friend: give $10, get $10 (the Reach plan's step 3, the approved
-- Offers board; Kevin, 2026-10-10, "go" on default 3: the friend's code
-- works on a first visit only, and the regular's thank-you is sent when the
-- friend's visit is paid). refer_a_friend.py.
--
--   offers            the program is the business's one offer with source
--                     'referral': what the friend gets (amount_cents, a
--                     first visit, once per person), on or paused, plus
--                     reward_cents (what the regular gets) and in_notes
--                     (each client's link rides on their "time for your
--                     next visit" note as a P.S.).
--   referral_links    each client's own code (ANDRE-7K); their link is the
--                     booking page with ?offer=CODE.
--   referral_rewards  one thank-you per friend: a THANKS-XXXX code for the
--                     regular, issued when the friend's visit is paid, and
--                     how it reached them.
--
-- Service role only. Idempotent.
--
-- Rollback:
--   DROP TABLE IF EXISTS public.referral_rewards;
--   DROP TABLE IF EXISTS public.referral_links;
--   DROP INDEX IF EXISTS public.offers_one_referral;
--   ALTER TABLE public.offers DROP CONSTRAINT IF EXISTS offers_reward;
--   ALTER TABLE public.offers DROP COLUMN IF EXISTS reward_cents;
--   ALTER TABLE public.offers DROP COLUMN IF EXISTS in_notes;
-- ─────────────────────────────────────────────────────────────────────

ALTER TABLE public.offers ADD COLUMN IF NOT EXISTS reward_cents integer;
ALTER TABLE public.offers ADD COLUMN IF NOT EXISTS in_notes boolean NOT NULL DEFAULT false;
ALTER TABLE public.offers DROP CONSTRAINT IF EXISTS offers_reward;
ALTER TABLE public.offers ADD CONSTRAINT offers_reward CHECK (
  (source = 'referral' AND reward_cents BETWEEN 100 AND 100000) OR (source <> 'referral' AND reward_cents IS NULL));

-- One program per business.
CREATE UNIQUE INDEX IF NOT EXISTS offers_one_referral ON public.offers (business_id) WHERE source = 'referral';

CREATE TABLE IF NOT EXISTS public.referral_links (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  contact_id   uuid NOT NULL REFERENCES public.contacts(id) ON DELETE CASCADE,
  code         text NOT NULL CONSTRAINT referral_links_code CHECK (code ~ '^[A-Z0-9][A-Z0-9-]{1,23}$'),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT referral_links_code_unique UNIQUE (business_id, code),
  CONSTRAINT referral_links_one_per_client UNIQUE (business_id, contact_id)
);

CREATE TABLE IF NOT EXISTS public.referral_rewards (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id          uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  referrer_contact_id  uuid NOT NULL REFERENCES public.contacts(id) ON DELETE CASCADE,
  friend_contact_id    uuid REFERENCES public.contacts(id) ON DELETE SET NULL,
  -- The friend's booking (module_entries.id). No foreign key: the thank-you
  -- stands even if that booking is later archived.
  friend_booking_id    uuid NOT NULL,
  code                 text NOT NULL CONSTRAINT referral_rewards_code CHECK (code ~ '^[A-Z0-9][A-Z0-9-]{1,23}$'),
  amount_cents         integer NOT NULL CONSTRAINT referral_rewards_amount CHECK (amount_cents BETWEEN 100 AND 100000),
  -- How the friend's visit was known to be paid.
  paid_how             text NOT NULL CONSTRAINT referral_rewards_paid_how CHECK (paid_how IN ('online', 'invoice', 'owner')),
  issued_at            timestamptz NOT NULL DEFAULT now(),
  -- How the thank-you reached the regular: claimed (sent_at) before it is sent.
  sent_at              timestamptz,
  sent_by              text CONSTRAINT referral_rewards_sent_by CHECK (sent_by IS NULL OR sent_by IN ('email', 'sms', 'none')),
  CONSTRAINT referral_rewards_code_unique UNIQUE (business_id, code),
  CONSTRAINT referral_rewards_one_per_booking UNIQUE (friend_booking_id),
  CONSTRAINT referral_rewards_one_per_friend UNIQUE (business_id, friend_contact_id)
);

CREATE INDEX IF NOT EXISTS referral_rewards_unsent ON public.referral_rewards (issued_at) WHERE sent_at IS NULL;
CREATE INDEX IF NOT EXISTS referral_rewards_business ON public.referral_rewards (business_id, issued_at DESC);

ALTER TABLE public.referral_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referral_rewards ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.referral_links FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.referral_rewards FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.referral_links TO service_role;
GRANT ALL ON public.referral_rewards TO service_role;

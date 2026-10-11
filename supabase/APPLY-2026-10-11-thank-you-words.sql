-- APPLY-2026-10-11-thank-you-words.sql
-- ─────────────────────────────────────────────────────────────────────
-- Refer a friend's thank-you: the owner's own words, and how long a
-- thank-you code is good for (refer_a_friend.py; Kevin, 2026-10-11:
-- "continue to build the next steps", after editable thank-you words and
-- an end date for thank-you codes were offered).
--
--   offers.thanks_words      {subject, email, text} the owner wrote for
--                            the thank-you (null = the suggested words).
--   offers.thanks_days       days a new thank-you code is good for
--                            (null = no end).
--   referral_rewards.expires_on  the last day this thank-you works, on
--                            the business's clock (null = no end); set
--                            when it is made, so a later change to
--                            thanks_days never shortens one already sent.
--
-- Additive. Idempotent.
--
-- Rollback:
--   ALTER TABLE public.offers DROP CONSTRAINT IF EXISTS offers_thanks_days;
--   ALTER TABLE public.offers DROP COLUMN IF EXISTS thanks_words;
--   ALTER TABLE public.offers DROP COLUMN IF EXISTS thanks_days;
--   ALTER TABLE public.referral_rewards DROP COLUMN IF EXISTS expires_on;
-- ─────────────────────────────────────────────────────────────────────

ALTER TABLE public.offers ADD COLUMN IF NOT EXISTS thanks_words jsonb;
ALTER TABLE public.offers ADD COLUMN IF NOT EXISTS thanks_days integer;
ALTER TABLE public.offers DROP CONSTRAINT IF EXISTS offers_thanks_days;
ALTER TABLE public.offers ADD CONSTRAINT offers_thanks_days CHECK (
  thanks_days IS NULL OR (source = 'referral' AND thanks_days BETWEEN 7 AND 365));

ALTER TABLE public.referral_rewards ADD COLUMN IF NOT EXISTS expires_on date;

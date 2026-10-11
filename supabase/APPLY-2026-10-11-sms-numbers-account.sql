-- APPLY-2026-10-11-sms-numbers-account.sql
-- ─────────────────────────────────────────────────────────────────────
-- Texting under each business's own name (Twilio ISV), step 4
-- (docs/plans/ISV_TEXTING_PLAN_2026-10-11.md). Once a business's
-- registration is approved, its number lives in its OWN Twilio sub-account,
-- on its own Messaging Service (its own campaign).
--
--   sms_numbers.account_sid   the Twilio account that holds the number:
--                             NULL = our main account (every number
--                             before this), AC… = the business's
--                             sub-account. Sends from it go through that
--                             account; its webhooks are signed with that
--                             account's token; releasing it happens there.
--
-- Additive and nullable: nothing existing changes. Idempotent.
--
-- Rollback:
--   DROP INDEX IF EXISTS public.sms_numbers_account_sid;
--   ALTER TABLE public.sms_numbers DROP COLUMN IF EXISTS account_sid;
-- ─────────────────────────────────────────────────────────────────────

ALTER TABLE public.sms_numbers ADD COLUMN IF NOT EXISTS account_sid text;

CREATE INDEX IF NOT EXISTS sms_numbers_account_sid
  ON public.sms_numbers (account_sid) WHERE account_sid IS NOT NULL;

NOTIFY pgrst, 'reload schema';

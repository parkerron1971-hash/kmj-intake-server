-- ═════════════════════════════════════════════════════════════════════
-- Arc 19 Phase B — launch access control + usage metering tables
-- ═════════════════════════════════════════════════════════════════════
-- 1. user_profiles — per-USER flags (grandfather, invite). auth.users is
--    Supabase-managed, so flags live here with an FK.
--    MASS-MARK: every user existing at deploy time → grandfathered
--    (Kevin's ruling: pre-launch accounts are free forever as comp).
-- 2. waitlist + invite_tokens — invite-only signup gate.
-- 3. usage_notifications + usage_stripe_reports — threshold-email dedup
--    and incremental Stripe metered-usage reporting state.
--
-- RLS: cross-table checks use the SECURITY DEFINER helper pattern (see
-- 2026_06_10_hotfix_rls_recursion.sql lesson). These tables are written
-- exclusively by the backend service role; practitioners get self-read
-- only where it's useful.
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.user_profiles (
  user_id              uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  is_grandfathered     boolean NOT NULL DEFAULT false,
  grandfathered_at     timestamptz,
  grandfathered_reason text,
  invited_via_token    uuid,
  created_at           timestamptz DEFAULT now(),
  updated_at           timestamptz DEFAULT now()
);

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_profiles_self_read ON public.user_profiles;
CREATE POLICY user_profiles_self_read ON public.user_profiles
  FOR SELECT USING (user_id = auth.uid());
-- (writes: backend service role only — no insert/update policies)

-- MASS-MARK every existing account as grandfathered (idempotent).
INSERT INTO public.user_profiles (user_id, is_grandfathered, grandfathered_at, grandfathered_reason)
SELECT u.id, true, now(), 'pre-launch account (auto-grandfathered at Phase B deploy)'
FROM auth.users u
ON CONFLICT (user_id) DO UPDATE
  SET is_grandfathered = true,
      grandfathered_at = COALESCE(public.user_profiles.grandfathered_at, now()),
      grandfathered_reason = COALESCE(public.user_profiles.grandfathered_reason,
                                      'pre-launch account (auto-grandfathered at Phase B deploy)');

CREATE TABLE IF NOT EXISTS public.waitlist (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email      text NOT NULL UNIQUE,
  name       text,
  source     text DEFAULT 'signup_page',
  created_at timestamptz DEFAULT now()
);
ALTER TABLE public.waitlist ENABLE ROW LEVEL SECURITY;
-- service-role only (no policies on purpose)

CREATE TABLE IF NOT EXISTS public.invite_tokens (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token                uuid NOT NULL DEFAULT gen_random_uuid(),
  email                text NOT NULL,
  created_by           text,
  created_at           timestamptz DEFAULT now(),
  expires_at           timestamptz DEFAULT (now() + interval '30 days'),
  accepted_at          timestamptz,
  accepted_by_user_id  uuid,
  status               text NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','accepted','expired','revoked'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_invite_tokens_token ON public.invite_tokens (token);
ALTER TABLE public.invite_tokens ENABLE ROW LEVEL SECURITY;
-- service-role only

CREATE TABLE IF NOT EXISTS public.usage_notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL,
  month       text NOT NULL,            -- 'YYYY-MM'
  threshold   int  NOT NULL,            -- 50 / 80 / 100 / 200 (=cap)
  created_at  timestamptz DEFAULT now(),
  UNIQUE (business_id, month, threshold)
);
ALTER TABLE public.usage_notifications ENABLE ROW LEVEL SECURITY;
-- service-role only

CREATE TABLE IF NOT EXISTS public.usage_stripe_reports (
  business_id    uuid NOT NULL,
  month          text NOT NULL,
  reported_units int  NOT NULL DEFAULT 0,
  updated_at     timestamptz DEFAULT now(),
  PRIMARY KEY (business_id, month)
);
ALTER TABLE public.usage_stripe_reports ENABLE ROW LEVEL SECURITY;
-- service-role only

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.usage_stripe_reports;
--   DROP TABLE IF EXISTS public.usage_notifications;
--   DROP TABLE IF EXISTS public.invite_tokens;
--   DROP TABLE IF EXISTS public.waitlist;
--   DROP TABLE IF EXISTS public.user_profiles;

SELECT 'phase B launch access ready' AS status;

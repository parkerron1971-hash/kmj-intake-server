-- Mission Control → Money (platform_money.py). Owner-only: what the platform
-- costs Kevin each month, when each bill is due, and how what's left over
-- splits into tax, a reserve and his own pay. Kevin, 2026-11-14: "build a
-- system that literally can track all of this for my business. when
-- everything is due and cost and savings and a plan so i can see how much
-- money I should pay myself".
--
-- Two tables, service role only (RLS on, no policies, like the other
-- platform_* tables): the bills (one row a vendor; the seed is Kevin's real
-- numbers on 2026-11-14) and the single split row (tax / reserve / pay).
-- Until this is applied the Money room reads the same seed from the code and
-- saving a bill or the split answers 503.
--
-- Safe twice: create if not exists, seeds on conflict do nothing.
-- Rollback: the lines at the end of the file.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.platform_money_bills (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key text UNIQUE NOT NULL,
  vendor text NOT NULL,
  what text,
  kind text NOT NULL CHECK (kind IN ('flat','usage')),
  amount_cents integer NOT NULL DEFAULT 0 CHECK (amount_cents >= 0),
  billing_day integer CHECK (billing_day BETWEEN 1 AND 31),
  -- Which live reader fills a usage bill (platform_money.LIVE_KEYS): 'railway',
  -- 'digitalocean', 'twilio', 'api_usage:<provider>', or null for none.
  live text,
  note text,
  watch boolean NOT NULL DEFAULT false,
  active boolean NOT NULL DEFAULT true,
  sort integer NOT NULL DEFAULT 100,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.platform_money_config (
  id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  tax_pct numeric NOT NULL DEFAULT 30 CHECK (tax_pct BETWEEN 0 AND 100),
  reserve_pct numeric NOT NULL DEFAULT 10 CHECK (reserve_pct BETWEEN 0 AND 100),
  pay_pct numeric NOT NULL DEFAULT 60 CHECK (pay_pct BETWEEN 0 AND 100),
  reserve_goal_months integer NOT NULL DEFAULT 3 CHECK (reserve_goal_months BETWEEN 0 AND 24),
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.platform_money_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.platform_money_bills ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_money_config ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_money_bills, public.platform_money_config FROM anon, authenticated;
GRANT ALL ON public.platform_money_bills, public.platform_money_config TO service_role;

-- Kevin's bills on 2026-11-14. amount_cents is the monthly amount for a flat
-- bill, and the fallback estimate for a usage bill when no live reader answers.
INSERT INTO public.platform_money_bills
  (key, vendor, what, kind, amount_cents, billing_day, live, note, watch, sort)
VALUES
  ('claude',       'Claude plan',   'Your building tool',                    'flat',  20000, 4,    NULL, NULL, false, 10),
  ('supabase',     'Supabase',      'The database',                          'flat',   3500, 22,   NULL, NULL, false, 20),
  ('vercel',       'Vercel',        'Hosts the app',                         'flat',   2000, 7,    NULL, NULL, false, 30),
  ('resend',       'Resend',        'Email',                                 'flat',   2000, 23,   NULL, 'May go up to $35', true, 40),
  ('railway',      'Railway',       'The servers Chief runs on',             'usage',  1300, 27,   'railway', NULL, false, 50),
  ('digitalocean', 'DigitalOcean',  'The live-stream server',                'usage',   600, 1,    'digitalocean', NULL, false, 60),
  ('twilio',       'Twilio',        'Texts and phone numbers',               'usage',  4000, NULL, 'twilio', 'Paid from your Twilio balance', false, 70),
  ('anthropic',    'Anthropic',     'Chief''s AI, by the message',           'usage',  7000, NULL, 'api_usage:anthropic', NULL, false, 80),
  ('openai',       'OpenAI',        'Voice, transcription, backup AI',       'usage',   200, NULL, 'api_usage:openai', NULL, false, 90),
  ('inworld',      'Inworld',       'Spoken voice, pay as you go',           'usage',     0, NULL, 'api_usage:inworld', NULL, false, 100),
  ('elevenlabs',   'ElevenLabs',    'Old voice, being replaced by Inworld',  'usage',     0, NULL, 'api_usage:elevenlabs', NULL, false, 110),
  ('livekit',      'LiveKit',       'Live classes and group meetings',       'usage',     0, NULL, NULL,
     'Free plan stops at 5,000 participant-minutes a month; the $50 plan covers 150,000', true, 120),
  ('r2',           'Cloudflare R2', 'Stored service recordings',             'usage',     0, NULL, NULL, NULL, false, 130)
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- Verify:
--   select key, kind, amount_cents, billing_day, live, watch from public.platform_money_bills order by sort;  -- 13 rows
--   select * from public.platform_money_config;  -- 1 row: 30 / 10 / 60, 3 months
--   select relrowsecurity from pg_class where oid = 'public.platform_money_bills'::regclass;  -- true
--
-- Rollback (the Money room goes back to reading the seed from the code):
--   drop table if exists public.platform_money_bills;
--   drop table if exists public.platform_money_config;

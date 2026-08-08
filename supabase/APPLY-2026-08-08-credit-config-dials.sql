-- APPLY-2026-08-08-credit-config-dials.sql
--
-- Ships with the config-driven credit system (Kevin's ruling 2026-08-08:
-- launch on conservative opening defaults, refine against real data once
-- the meter works). Three additive columns on api_usage. All nullable,
-- no backfill, no default that changes existing behaviour.
--
-- ───────────────────────────────────────────────────────────────────
-- 1. api_usage.units — THE PRICE OF AN ACTION, WRITTEN ON THE ROW
-- ───────────────────────────────────────────────────────────────────
-- usage_metering priced actions by ENDPOINT alone (UNIT_WEIGHTS lookup).
-- That table physically cannot express the ruled price list, because
-- three of the seven prices are context-dependent on an endpoint that
-- logs exactly one label:
--
--   /composer/compose  = a build (base + sections x per_section)
--                        OR a revamp (flat)      — same function
--   /composer/atelier  = a standalone Studio section rewrite (120)
--                        OR a build-internal fragment (0, already paid
--                        for by the build marker) — same function
--
-- So the price is computed at log time and stored here. NULL means
-- "price me from my endpoint" — which is every row written before today,
-- so history keeps reading correctly with no backfill.
--
-- 0 is MEANINGFUL (build internals are deliberately free), which is why
-- the read path tests `IS NOT NULL` rather than truthiness.
ALTER TABLE api_usage ADD COLUMN IF NOT EXISTS units integer;

COMMENT ON COLUMN api_usage.units IS
  'Credits this action cost the practitioner. NULL = price from the '
  'endpoint via pricing_config.unit_weights(). 0 is meaningful (build '
  'internals are free; the build marker carries the whole bill).';

-- ───────────────────────────────────────────────────────────────────
-- 2 + 3. cache_read_tokens / cache_creation_tokens
-- ───────────────────────────────────────────────────────────────────
-- api_usage_logger has PRICED cache traffic since the understating fix
-- (read 0.10x, write 1.25x, folded into cost_cents) but never PERSISTED
-- the counts — so the cache-hit rate was paid for and unmeasurable.
-- On the 30-day Chief sample, cache traffic is ~55% of a turn's cost;
-- these two columns are what make that reducible rather than merely
-- observed once by hand.
--
-- Only chief_of_staff.py sends cache breakpoints today. The composer
-- lanes send none, so their rows land 0/0 — which is the honest answer,
-- not a gap.
ALTER TABLE api_usage ADD COLUMN IF NOT EXISTS cache_read_tokens integer DEFAULT 0;
ALTER TABLE api_usage ADD COLUMN IF NOT EXISTS cache_creation_tokens integer DEFAULT 0;

COMMENT ON COLUMN api_usage.cache_read_tokens IS
  'Anthropic cache_read_input_tokens. Priced at 0.10x base input inside '
  'cost_cents; stored so the cache-hit rate is measurable.';
COMMENT ON COLUMN api_usage.cache_creation_tokens IS
  'Anthropic cache_creation_input_tokens. Priced at 1.25x base input '
  'inside cost_cents; stored so cache writes are measurable.';

-- ───────────────────────────────────────────────────────────────────
-- 4. The index the meter now reads through
-- ───────────────────────────────────────────────────────────────────
-- weighted_usage_this_month() and chat_turns_today() both filter
-- (business_id, created_at) and paginate. Until today the month filter
-- was malformed and PostgREST 400'd every call, so this path has never
-- actually served a row — it is about to start.
CREATE INDEX IF NOT EXISTS idx_api_usage_business_created
  ON api_usage (business_id, created_at DESC);

-- ───────────────────────────────────────────────────────────────────
-- Verification
-- ───────────────────────────────────────────────────────────────────
SELECT column_name, data_type, column_default, is_nullable
  FROM information_schema.columns
 WHERE table_name = 'api_usage'
   AND column_name IN ('units', 'cache_read_tokens', 'cache_creation_tokens')
 ORDER BY column_name;

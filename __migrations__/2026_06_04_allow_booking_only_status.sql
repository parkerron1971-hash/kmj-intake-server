-- ─────────────────────────────────────────────────────────────────
-- Phase D.2.1 — Allow 'booking_only' on business_sites.status
-- ─────────────────────────────────────────────────────────────────
-- Run via:  Supabase Studio → SQL editor → paste + Run
-- Idempotent. Forward-only (strictly widens the allowed set).
-- Safe to run multiple times — uses DO blocks + IF EXISTS.
--
-- What this does:
--   1. Finds + drops any existing CHECK constraint that restricts
--      business_sites.status to a fixed list (the constraint name
--      can vary across environments — DO block discovers it
--      dynamically).
--   2. Adds a new CHECK constraint allowing:
--      'draft', 'published', 'archived', 'booking_only'
--
-- After running this, re-run:
--   railway run python __migrations__/backfill_business_sites_for_booking.py
-- ─────────────────────────────────────────────────────────────────

DO $$
DECLARE
    cname text;
BEGIN
    -- Discover the existing CHECK constraint on the status column
    -- (handles both auto-generated names and explicitly-named ones).
    SELECT conname INTO cname
    FROM pg_constraint
    WHERE conrelid = 'public.business_sites'::regclass
      AND contype  = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%status%';

    IF cname IS NOT NULL THEN
        RAISE NOTICE 'dropping existing CHECK constraint: %', cname;
        EXECUTE format('ALTER TABLE public.business_sites DROP CONSTRAINT %I', cname);
    ELSE
        RAISE NOTICE 'no existing CHECK constraint on status — adding fresh';
    END IF;
END $$;

ALTER TABLE public.business_sites
    ADD CONSTRAINT business_sites_status_check
    CHECK (status IN ('draft', 'published', 'archived', 'booking_only'));

-- Verify:
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'public.business_sites'::regclass
  AND contype  = 'c'
  AND conname  = 'business_sites_status_check';

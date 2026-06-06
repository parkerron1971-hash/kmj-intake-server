-- ─────────────────────────────────────────────────────────────────
-- Path C Phase 1 — 1a Diagnostic SELECTs
-- ─────────────────────────────────────────────────────────────────
-- READ-ONLY. Paste into Supabase Studio → SQL editor → Run.
-- Surfaces the actual scope of businesses.type / business_profiles
-- .business_type / business_type_archetypes drift before the FK
-- migration runs. Output drives 1b (which archetype rows to seed)
-- and 1f (whether the FK migration is safe to apply).
--
-- Re-run anytime; nothing is written.
-- ─────────────────────────────────────────────────────────────────

-- ─── Q1. Distinct businesses.type values + counts ────────────────
SELECT type, COUNT(*) AS n
FROM public.businesses
GROUP BY type
ORDER BY n DESC, type ASC;

-- ─── Q2. Distinct business_profiles.business_type values + counts
SELECT business_type, COUNT(*) AS n
FROM public.business_profiles
WHERE business_type IS NOT NULL
GROUP BY business_type
ORDER BY n DESC, business_type ASC;

-- ─── Q3. Current archetype table contents
SELECT business_type, display_name
FROM public.business_type_archetypes
ORDER BY business_type ASC;

-- ─── Q4. Drift report — type ≠ profile.business_type
SELECT
  b.id,
  b.name,
  b.type                    AS businesses_type,
  bp.business_type          AS profile_business_type
FROM public.businesses b
LEFT JOIN public.business_profiles bp
       ON bp.business_id = b.id
WHERE bp.business_type IS NOT NULL
  AND b.type IS DISTINCT FROM bp.business_type
ORDER BY b.name;

-- ─── Q5. businesses.type values NOT yet in archetypes (must be
--     seeded before the FK in 1f can be applied)
SELECT DISTINCT b.type AS missing_archetype_for_type
FROM public.businesses b
WHERE b.type IS NOT NULL
  AND b.type NOT IN (
    SELECT business_type FROM public.business_type_archetypes
  )
ORDER BY 1;

-- ─── Q6. business_profiles.business_type values NOT yet in
--     archetypes (informs Phase 2 ruling on the profiles FK)
SELECT DISTINCT bp.business_type AS missing_archetype_for_profile_type
FROM public.business_profiles bp
WHERE bp.business_type IS NOT NULL
  AND bp.business_type NOT IN (
    SELECT business_type FROM public.business_type_archetypes
  )
ORDER BY 1;

-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-13 — Chief standing playbook (compounding intelligence, part 3)
--
-- Semantic memory and the weekly insights each grow a LIST. A list is
-- retrieval material, not a point of view. This adds one distilled brief
-- per business — WHO THIS IS / WHAT WORKS / WHAT TO AVOID / RIGHT NOW —
-- re-written (cheaply) whenever the underlying facts change, and prepended
-- to every Chief conversation as background truth.
--
-- One row per business (business_id is the PK, so the backend upserts via
-- resolution=merge-duplicates). Service-role only — no policies on purpose,
-- the backend is the sole reader/writer. Additive + idempotent.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.chief_playbooks (
  business_id   uuid PRIMARY KEY,
  body          text NOT NULL,          -- the distilled standing brief
  sources_count int  DEFAULT 0,         -- memories + insights it was built from
  fingerprint   text,                   -- source signature (skip re-distill when unchanged)
  model         text,                   -- which lane wrote it
  generated_at  timestamptz DEFAULT now()
);

ALTER TABLE public.chief_playbooks ENABLE ROW LEVEL SECURITY;
-- service-role only (no policies on purpose — backend-mediated)

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.chief_playbooks;

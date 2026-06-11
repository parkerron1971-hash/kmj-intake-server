-- ═════════════════════════════════════════════════════════════════════
-- Arc 20 Phase B — Tier 1 rules engine + generic Chief proposals
-- ═════════════════════════════════════════════════════════════════════
-- practitioner_rules — the closed-grammar automations (versioned).
-- rule_runs          — every execution: trigger snapshot + condition
--                      trace + action results (the audit answer).
-- chief_proposals    — GENERIC proposal table for non-bookkeeping
--                      domains (follow-up email / task / contact tag /
--                      scheduling / content). chief_bookkeeping_proposals
--                      stays untouched — it's a working prod surface with
--                      bookkeeping-specific columns; a union endpoint
--                      reads both. Rule "ask-me-first" actions land HERE
--                      (the convergence).
--
-- RLS: owner READ via the SECURITY DEFINER helpers from the recursion
-- hotfix (public.is_business_owner) — NEVER inline cross-table EXISTS.
-- All writes go through the backend service role.
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.practitioner_rules (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id    uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  name           text NOT NULL,
  rationale      text NOT NULL,           -- "what is this automation for"
  enabled        boolean NOT NULL DEFAULT true,
  trigger_type   text NOT NULL,
  trigger_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  conditions     jsonb NOT NULL DEFAULT '[]'::jsonb,
  actions        jsonb NOT NULL DEFAULT '[]'::jsonb,
  version        int NOT NULL DEFAULT 1,
  created_by     uuid,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rules_biz_trigger
  ON public.practitioner_rules (business_id, trigger_type) WHERE enabled;

ALTER TABLE public.practitioner_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rules_owner_read ON public.practitioner_rules;
CREATE POLICY rules_owner_read ON public.practitioner_rules
  FOR SELECT USING (public.is_business_owner(practitioner_rules.business_id));

CREATE TABLE IF NOT EXISTS public.rule_runs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id     uuid NOT NULL,
  rule_id         uuid,
  rule_version    int,
  event_type      text,
  event           jsonb,
  condition_trace jsonb,
  results         jsonb,
  status          text,
  chain_depth     int DEFAULT 0,
  created_at      timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rule_runs_biz
  ON public.rule_runs (business_id, created_at DESC);

ALTER TABLE public.rule_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rule_runs_owner_read ON public.rule_runs;
CREATE POLICY rule_runs_owner_read ON public.rule_runs
  FOR SELECT USING (public.is_business_owner(rule_runs.business_id));

-- Retention (run manually or via future cron): rule_runs older than 90
-- days are prunable — the rules engine itself prunes nothing in v1.

CREATE TABLE IF NOT EXISTS public.chief_proposals (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  proposal_type text NOT NULL CHECK (proposal_type IN (
                  'propose_followup_email', 'propose_task',
                  'propose_contact_tag', 'propose_schedule_followup',
                  'propose_content_draft')),
  source        text NOT NULL DEFAULT 'chief',   -- 'chief' | 'rule:<id>' | 'agent:<id>'
  proposed      jsonb NOT NULL DEFAULT '{}'::jsonb,
  confidence    numeric(3,2),
  reasoning     text,
  status        text NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','approved','rejected','expired')),
  resolved_at   timestamptz,
  approved_by   uuid,
  created_at    timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chief_proposals_biz
  ON public.chief_proposals (business_id, status, created_at DESC);

ALTER TABLE public.chief_proposals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chief_proposals_owner_read ON public.chief_proposals;
CREATE POLICY chief_proposals_owner_read ON public.chief_proposals
  FOR SELECT USING (public.is_business_owner(chief_proposals.business_id));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.chief_proposals;
--   DROP TABLE IF EXISTS public.rule_runs;
--   DROP TABLE IF EXISTS public.practitioner_rules;

SELECT 'arc 20 rules + proposals ready' AS status;

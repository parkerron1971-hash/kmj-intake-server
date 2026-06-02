-- ═══════════════════════════════════════════════════════════════════════
-- chief_suggestions — Chief's proactive suggestion lifecycle (Phase C.1.3)
-- ═══════════════════════════════════════════════════════════════════════
-- Per the Navigation Taxonomy Audit (NT8b–NT8d): Chief proactively
-- surfaces suggestions on meaningful business-state changes (foundation
-- phase completed, low module count, just signed up, etc). Each
-- suggestion travels a lifecycle: proposed → snoozed → dismissed →
-- accepted. Default snooze is 14 days; dismissed re-emerges only on a
-- new meaningful state change (NT8b discipline).
--
-- Suggestions are NEVER customer-facing — they belong to the
-- practitioner. RLS scoped to practitioner-only access via owner_id,
-- same pattern as business_customers / module_specs / workflow_definitions.
--
-- Chief constructs these server-side (service-role insert from
-- _maybe_emit_proactive_suggestions in chief_of_staff.py). The
-- practitioner sees them in the HOME ChiefRecommendsPanel and acts on
-- them via dismiss_chief_suggestion / snooze_chief_suggestion / accept
-- (the accept path runs the same propose_module_from_intake flow).
--
-- NON-DESTRUCTIVE + IDEMPOTENT.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS public.chief_suggestions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id         uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  -- Suggestion shape — closed enum.
  kind                text NOT NULL,
  -- Closed enum for the archetype Chief proposes (matches ArchetypeEnum
  -- from module_spec_generator). NT8e: only chief_can_suggest=true
  -- archetypes are ever stored here.
  archetype           text,
  -- The practitioner-readable summary Chief surfaces in the panel.
  title               text NOT NULL,
  rationale           text,
  -- Lifecycle: proposed | snoozed | dismissed | accepted.
  status              text NOT NULL DEFAULT 'proposed',
  -- When Chief decided to emit. The "what triggered this" anchor.
  triggered_by        text,
  -- For snoozed entries: when to re-emerge. NULL for non-snoozed.
  snoozed_until       timestamptz,
  -- For accepted entries: the module_id or spec_id the suggestion led to.
  resolved_module_id  uuid,
  resolved_spec_id    uuid,
  -- For dismissed entries: the optional reason the practitioner gave.
  dismiss_reason      text,
  -- Intake-style seed for when the suggestion is accepted and runs
  -- through propose_module_from_intake (NT8b's "vertical-aware intake").
  intake_seed         text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT chief_suggestions_status_check CHECK (status IN
    ('proposed','snoozed','dismissed','accepted')),
  CONSTRAINT chief_suggestions_kind_check CHECK (kind IN
    ('module','offering_curation','workflow_setup','growth_objective','custom'))
);

-- Active-suggestions lookup (the most common read path: "what's active for
-- this business right now?"). Partial index keeps it small.
CREATE INDEX IF NOT EXISTS chief_suggestions_business_active_idx
  ON public.chief_suggestions(business_id, status, created_at DESC)
  WHERE status IN ('proposed','snoozed');

-- Snooze re-emergence sweep (a scheduled task moves snoozed → proposed when
-- snoozed_until elapses). Index supports the cron-style scan.
CREATE INDEX IF NOT EXISTS chief_suggestions_snoozed_until_idx
  ON public.chief_suggestions(snoozed_until)
  WHERE status = 'snoozed';

ALTER TABLE public.chief_suggestions ENABLE ROW LEVEL SECURITY;

-- Practitioner-only access via owner_id. Same pattern as business_customers,
-- module_specs, workflow_definitions, offerings.
DROP POLICY IF EXISTS chief_suggestions_owner_all ON public.chief_suggestions;
CREATE POLICY chief_suggestions_owner_all ON public.chief_suggestions
  FOR ALL TO authenticated
  USING  (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()))
  WITH CHECK (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));

-- Anon role gets NO policy → no access by default. Suggestions are
-- never customer-facing.

COMMIT;

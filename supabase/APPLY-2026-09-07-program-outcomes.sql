-- Private report snapshots; application rechecks every source module on access.
BEGIN;
CREATE TABLE IF NOT EXISTS public.program_outcome_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  configuration jsonb NOT NULL CHECK (jsonb_typeof(configuration) = 'object'),
  snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[a-f0-9]{64}$'),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved')),
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  approved_by uuid,
  approved_at timestamptz,
  CHECK ((status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
      OR (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS program_outcomes_business_created ON public.program_outcome_reports(business_id,created_at DESC);
ALTER TABLE public.program_outcome_reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.program_outcome_reports FROM anon, authenticated;
GRANT ALL ON public.program_outcome_reports TO service_role;

CREATE OR REPLACE FUNCTION public.preserve_program_outcome_snapshot() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.business_id IS DISTINCT FROM OLD.business_id
    OR NEW.configuration IS DISTINCT FROM OLD.configuration OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
    OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.created_by IS DISTINCT FROM OLD.created_by
    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Report snapshots are immutable; create a new report';
  END IF;
  IF OLD.status = 'approved' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Approved reports are immutable';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS preserve_program_outcome_snapshot ON public.program_outcome_reports;
CREATE TRIGGER preserve_program_outcome_snapshot BEFORE UPDATE ON public.program_outcome_reports
FOR EACH ROW EXECUTE FUNCTION public.preserve_program_outcome_snapshot();

CREATE OR REPLACE FUNCTION public.approve_program_outcome_report(
  p_business_id uuid, p_report_id uuid, p_content_hash text, p_actor_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE saved public.program_outcome_reports;
BEGIN
  SELECT * INTO saved FROM public.program_outcome_reports
  WHERE id=p_report_id AND business_id=p_business_id AND content_hash=p_content_hash FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('conflict',true); END IF;
  IF saved.status='approved' THEN RETURN to_jsonb(saved); END IF;
  UPDATE public.program_outcome_reports SET status='approved',approved_by=p_actor_id,approved_at=now()
  WHERE id=p_report_id RETURNING * INTO saved;
  RETURN to_jsonb(saved);
END $$;
REVOKE ALL ON FUNCTION public.approve_program_outcome_report(uuid,uuid,text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.approve_program_outcome_report(uuid,uuid,text,uuid) TO service_role;
COMMIT;

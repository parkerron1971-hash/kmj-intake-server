-- A documented erasure retains the chain tip and writes a tombstone. Counting
-- only surviving rows then rejects the NEXT legitimate audit event. Include
-- the recorded erased range in the bound; never reset the tip or disable audit.
CREATE INDEX IF NOT EXISTS ledger_tombstones_business_last ON public.ledger_tombstones(business_id,last_sequence DESC);
CREATE OR REPLACE FUNCTION public.ledger_tip_forward_only() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE v_max bigint;
BEGIN
  IF TG_OP='UPDATE' AND NEW.last_sequence < OLD.last_sequence THEN
    RAISE EXCEPTION 'ledger_chain_state.last_sequence cannot move backwards'
      USING ERRCODE='restrict_violation';
  END IF;
  SELECT greatest(
    coalesce((SELECT max(sequence) FROM public.audit_log WHERE business_id=NEW.business_id),0),
    coalesce((SELECT max(last_sequence) FROM public.ledger_tombstones WHERE business_id=NEW.business_id),0)
  ) INTO v_max;
  IF NEW.last_sequence > v_max+1 THEN
    RAISE EXCEPTION 'Ledger tip cannot exceed recorded or documented erased history by more than one'
      USING ERRCODE='restrict_violation';
  END IF;
  RETURN NEW;
END $$;

-- Conversation desk: retain the existing archive/recall table and add thread
-- metadata. Apply before enabling cloud writes from the new frontend.
BEGIN;
ALTER TABLE public.chief_conversations
  ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Replace this table's older permissive policy with the ownership convention
-- used by the application's other business-scoped records. Service-role
-- Chief recall continues to work through the normal RLS bypass.
ALTER TABLE public.chief_conversations ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE p record;
BEGIN
  FOR p IN SELECT policyname FROM pg_policies WHERE schemaname = 'public' AND tablename = 'chief_conversations'
  LOOP
    EXECUTE format('DROP POLICY %I ON public.chief_conversations', p.policyname);
  END LOOP;
END $$;
CREATE POLICY chief_conversations_business_owner ON public.chief_conversations
  FOR ALL TO authenticated
  USING (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()))
  WITH CHECK (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));

CREATE INDEX IF NOT EXISTS chief_conversations_business_id_id
  ON public.chief_conversations (business_id, id);
NOTIFY pgrst, 'reload schema';
COMMIT;

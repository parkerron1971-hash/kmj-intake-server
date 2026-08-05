-- APPLY-business-doc-templates.sql
-- Learn-from-upload: a practitioner's own uploaded contract, converted
-- into a reusable template. One row per learned template; the template
-- jsonb matches doc_templates.py's shape (title/subtitle/description/
-- fields/sections) so the generation core runs it unchanged.
--
-- RLS: owner-only via the businesses ownership subquery (no cycle —
-- businesses policies never reference this table). Backend traffic is
-- service-role; the policy protects any future direct PostgREST read.

CREATE TABLE IF NOT EXISTS business_doc_templates (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  template    jsonb NOT NULL,
  source_path text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bdt_business
  ON business_doc_templates (business_id, created_at DESC);

ALTER TABLE business_doc_templates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bdt_owner_all ON business_doc_templates;
CREATE POLICY bdt_owner_all ON business_doc_templates
  FOR ALL
  USING (business_id IN (SELECT id FROM businesses WHERE owner_id = auth.uid()))
  WITH CHECK (business_id IN (SELECT id FROM businesses WHERE owner_id = auth.uid()));

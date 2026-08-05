-- APPLY-agent-queue-document-action-type.sql
-- APPLIED 2026-08-05 (verified with a rolled-back test insert).
--
-- The bug this fixes: doc_templates lands generated documents as
-- agent_queue rows with action_type='document', but the table's CHECK
-- predates that value — every generate_document insert was rejected
-- (PostgREST 400 -> sb helper None -> the honest 502 "couldn't queue
-- the document for review"). Kevin hit it live on 8/05 with Chief's
-- first real engagement-letter run.

ALTER TABLE agent_queue DROP CONSTRAINT agent_queue_action_type_check;
ALTER TABLE agent_queue ADD CONSTRAINT agent_queue_action_type_check
  CHECK (action_type = ANY (ARRAY['email'::text, 'sms'::text,
    'follow_up'::text, 'proposal'::text, 'invoice'::text,
    'check_in'::text, 'onboarding'::text, 'alert'::text,
    'document'::text, 'other'::text]));

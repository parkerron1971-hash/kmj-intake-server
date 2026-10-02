-- APPLY 2026-10-02 — support drafts (agent operations plan, Wave 3)
--
-- The Support desk agent (support_drafts.py) reads each ticket waiting on
-- an answer, looks at the business and the conversation, and leaves a
-- DRAFT reply for a person to read, edit and send. It never sends. The
-- draft lives on the operator-only triage row, next to severity and the
-- problem key, because nothing on support_triage is ever shown to the
-- practitioner (support_router: "nothing may cross from the first to the
-- second" without a person pressing Send).
--
-- draft_for_at: the moment the draft answers (the practitioner's latest
-- message, or the ticket's creation when nobody has answered yet). A newer
-- practitioner message makes the draft stale, and the agent drafts again.

ALTER TABLE public.support_triage
  ADD COLUMN IF NOT EXISTS draft_reply    text,
  ADD COLUMN IF NOT EXISTS draft_summary  text,
  ADD COLUMN IF NOT EXISTS draft_category text,
  ADD COLUMN IF NOT EXISTS draft_severity text,
  ADD COLUMN IF NOT EXISTS draft_for_at   timestamptz,
  ADD COLUMN IF NOT EXISTS drafted_at     timestamptz,
  ADD COLUMN IF NOT EXISTS draft_model    text;

COMMENT ON COLUMN public.support_triage.draft_reply IS
  'Support desk agent''s suggested reply. Operator-only; sent only when a person sends it.';

NOTIFY pgrst, 'reload schema';

-- VERIFY:
--   SELECT column_name FROM information_schema.columns
--    WHERE table_schema = 'public' AND table_name = 'support_triage'
--      AND column_name LIKE 'draft%' OR column_name = 'drafted_at';   -- 7 rows
--
-- ROLLBACK:
--   ALTER TABLE public.support_triage
--     DROP COLUMN IF EXISTS draft_reply, DROP COLUMN IF EXISTS draft_summary,
--     DROP COLUMN IF EXISTS draft_category, DROP COLUMN IF EXISTS draft_severity,
--     DROP COLUMN IF EXISTS draft_for_at, DROP COLUMN IF EXISTS drafted_at,
--     DROP COLUMN IF EXISTS draft_model;
--   NOTIFY pgrst, 'reload schema';

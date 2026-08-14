-- APPLY-2026_08_14_first_response_clock.sql
--
-- THE LEAD ARC PR 4 — how long a lead waits.
--
-- WHY THIS COLUMN EXISTS
--   Nothing in either repo measured it. Not a field, not a metric, not
--   a query. The closest thing was growth_engine's stale-lead check,
--   which flags a lead at THIRTY DAYS OLD PLUS FOURTEEN DAYS SILENT —
--   a monthly retrospective, not a clock. A lead that arrived this
--   morning and is still untouched on Thursday triggered nothing,
--   appeared nowhere, and cost nothing to ignore.
--
--   First-response time is the number that decides whether an enquiry
--   becomes a customer. A system that promises to help a solo operator
--   capture leads and never tells them one has been sitting for two
--   days is not doing the job it says it does.
--
-- WHY IT IS DERIVED, NOT STAMPED
--   The obvious implementation is to write this at every outbound send.
--   There are at least six such paths — email_sender, sms_service,
--   approvals_router, two in chief_of_staff, and the frontend, which
--   PATCHes agent_queue to 'sent' directly from ContactDetail.tsx. Six
--   call sites is six chances to miss one, and a missed one shows up as
--   a lead that looks permanently unanswered: a false alarm, which is
--   the fastest way to teach somebody to ignore a real one.
--
--   Every one of those paths already leaves a durable record — an
--   outbound sms_messages row, an agent_queue row with sent_at, a
--   spine event, a session. lead_response.py derives the answer from
--   those and materialises it here. One place to be right, it covers
--   history as well as new activity, and a send path added next month
--   is picked up without anyone remembering to instrument it.
--
-- NULL MEANS "NOT YET", NOT "UNKNOWN"
--   The reconciler leaves the column null when it finds no response,
--   and re-checks on the next tick, because a response can still
--   arrive. Unanswered leads are therefore re-scanned every pass —
--   which is fine, since that is precisely the set worth looking at,
--   and if it is ever large enough for the cost to matter then the
--   business has a much more expensive problem than this query.
--
-- SAFETY
--   Additive and nullable. No default, no backfill in DDL, no rewrite
--   of the table, no change to any existing policy. Every reader that
--   does not know about the column is unaffected.

ALTER TABLE public.contacts
  ADD COLUMN IF NOT EXISTS first_response_at timestamptz;

COMMENT ON COLUMN public.contacts.first_response_at IS
  'When this contact first heard back from the business — earliest of: '
  'an outbound SMS, an agent_queue row marked sent, an agent_message_sent '
  'or sms_sent event, a session booked, or their status moving off '
  '"lead". Derived by lead_response.reconcile_tick, not stamped at the '
  'send sites. NULL means no response yet, and is re-checked every tick.';

-- The reconciler''s working set: leads still waiting. Partial, so it
-- indexes only the rows anyone asks about and stays small even as
-- contacts grows — a full index here would be almost entirely rows
-- that have already been answered and will never be queried this way.
CREATE INDEX IF NOT EXISTS contacts_awaiting_first_response_idx
  ON public.contacts (business_id, created_at DESC)
  WHERE first_response_at IS NULL;

-- The other direction: the funnel's median response time, and the
-- per-business read behind it.
CREATE INDEX IF NOT EXISTS contacts_first_response_idx
  ON public.contacts (business_id, first_response_at)
  WHERE first_response_at IS NOT NULL;

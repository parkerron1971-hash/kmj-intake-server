-- APPLY-2026-09-05-concierge-qualification.sql
-- Apply via the Supabase Management API (whole file) in the same arc as
-- the code — code and schema ship together.
--
-- THE SITE CONCIERGE learns to QUALIFY and to BOOK (site_concierge.py,
-- concierge_qualify.py, 2026-09-05). Two additive columns on the
-- conversation row:
--
--   qualification   jsonb — {tier: hot|warm|cold, score, signals[],
--                            answers{question: answer}, service,
--                            booked, extracted, at}. Written by the
--                            backend at lead capture and at an in-chat
--                            booking. The operator list reads it.
--   appointment_id  text  — the module_entries row an in-chat booking
--                            created (text, not a FK: module_entries
--                            ids are the archetype's, and a deleted
--                            appointment must not null the conversation).
--
-- ACCESS MODEL unchanged: writes are backend service-role only; reads
-- ride the existing tenant_member_read policy (no new policy needed —
-- columns inherit the row policy).
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

alter table public.concierge_conversations
  add column if not exists qualification jsonb,
  add column if not exists appointment_id text;

-- The operator panel filters "hot first"; a small expression index
-- keeps that cheap as conversations pile up.
create index if not exists idx_concierge_conversations_tier
  on public.concierge_conversations (business_id, ((qualification->>'tier')));

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
select column_name, data_type
  from information_schema.columns
 where table_schema = 'public'
   and table_name = 'concierge_conversations'
   and column_name in ('qualification', 'appointment_id')
 order by column_name;

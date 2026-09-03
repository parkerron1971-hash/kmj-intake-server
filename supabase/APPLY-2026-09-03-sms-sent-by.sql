-- APPLY-2026-09-03-sms-sent-by.sql
--
-- Who sent an outbound text. The thread on the desk showed every
-- outbound as "You:" — a text Chief sent on the practitioner's behalf
-- and a booking reminder the scheduler sent looked identical to one
-- the practitioner typed. Kevin, 2026-09-03: "in the text thread it
-- shows up with something letting me know it's chief that texted."
--
--   practitioner  typed on the desk (/sms/send, broadcast)
--   chief         the AI, on the practitioner's behalf (Chief's send_sms,
--                 incl. scheduled ones)
--   system        automated: booking confirmations, reminders, campaigns
--   NULL          inbound, and outbound rows older than this migration
--
-- Apply by hand in the Supabase SQL editor. Ledger: docs/MIGRATIONS.md.
-- Rollback: alter table public.sms_messages drop column sent_by;

alter table public.sms_messages
  add column if not exists sent_by text
  check (sent_by in ('practitioner','chief','system'));

comment on column public.sms_messages.sent_by is
  'Outbound author: practitioner (typed on the desk), chief (the AI), system (booking alerts, reminders, campaigns). NULL on inbound and on rows older than 2026-09-03.';

-- Verify:
-- select 'applied' as result, count(*) filter (where sent_by is not null) as tagged from public.sms_messages;

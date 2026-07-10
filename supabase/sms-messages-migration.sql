-- sms-messages-migration.sql
-- RETROACTIVE DOCUMENTATION (2026-07-10): this table has existed in the
-- live Supabase since the SMS rail shipped, but the migration file was
-- referenced from sms_service.py without ever being committed. This
-- captures the schema the code writes (sms_service._store_sms) so a
-- fresh environment can be stood up and the columns are documented.
-- Safe to run against the live DB: IF NOT EXISTS everywhere.

create table if not exists sms_messages (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid references businesses(id),
  contact_id   uuid references contacts(id),
  phone_number text not null,            -- counterpart E.164
  message      text not null,
  direction    text not null,            -- 'inbound' | 'outbound'
  status       text not null default 'received',
                                         -- outbound: 'sent'|'delivered'|'failed'
                                         -- inbound:  'received'
  telnyx_id    text,                     -- provider message id (Telnyx OR Twilio SID)
  media_urls   text[],                   -- MMS attachments (inbound)
  read         boolean not null default false,
  created_at   timestamptz not null default now()
);

create index if not exists idx_sms_messages_business_created
  on sms_messages (business_id, created_at desc);
create index if not exists idx_sms_messages_contact
  on sms_messages (contact_id, created_at desc);
-- The unread badge query: direction='inbound' AND read=false
create index if not exists idx_sms_messages_unread
  on sms_messages (business_id) where direction = 'inbound' and read = false;
-- Delivery callbacks PATCH by provider id
create index if not exists idx_sms_messages_provider
  on sms_messages (telnyx_id);

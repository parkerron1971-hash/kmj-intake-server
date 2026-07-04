-- sms-consents-business-migration.sql
-- Booking-consent wiring (2026-07-04): consents recorded from booking
-- forms carry the business they were given to. Platform /sms page
-- consents keep business_id NULL (platform-level).
alter table public.sms_consents
  add column if not exists business_id uuid;
create index if not exists sms_consents_biz_idx
  on public.sms_consents (business_id);

-- Prayer & care requests can be handed to a teammate (Kevin, 2026-10-14:
-- "others should be able to see prayer request"). The owner still sees
-- every request; a request with assigned_to set is also visible to that
-- seat, and only that one. Enforced in private_care.care_access: the
-- table stays service-role only (RLS on, no policies). Idempotent.
begin;

alter table public.ministry_care_requests
  add column if not exists assigned_to uuid,
  add column if not exists assigned_at timestamptz,
  add column if not exists assigned_by uuid;

create index if not exists ministry_care_assigned
  on public.ministry_care_requests(business_id, assigned_to, created_at desc)
  where assigned_to is not null;

commit;

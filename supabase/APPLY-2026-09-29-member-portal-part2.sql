-- Member page, part 2 (member_portal_church.py): a prayer request sent from
-- a member's own page is linked to their record. Idempotent.
begin;
alter table public.ministry_care_requests
  add column if not exists contact_id uuid references public.contacts(id) on delete set null;
create index if not exists ministry_care_contact
  on public.ministry_care_requests(business_id, contact_id) where contact_id is not null;
commit;

-- The church register (church_register.py; Kevin 2026-10-27 on the Church
-- Office Prototypes, "Church register" tab: "lets go with your list").
-- Baptisms, baby dedications, weddings, funerals and membership dates, kept
-- for good, with certificates. One table, server-only (RLS on, no policies,
-- browser roles revoked); church_register.py reads and writes it.
--
--   church_register_entries   one event: its kind (and for membership:
--                             joined, transferred_in, transferred_out or
--                             removed), done or planned, its day; its people
--                             as recorded ([{role, contact_id, name}]) and
--                             their contact ids (contact_ids, so a person's
--                             page finds their milestones); the officiant,
--                             the place, the other church for a transfer,
--                             notes; where it came from (the office, a
--                             member's ask from the app, the Subsplash
--                             import). care_request_id is unique (an ask
--                             becomes one entry at most) and so is
--                             (business_id, import_key) (an imported baptism
--                             date comes in once). Removing sets removed_at:
--                             the entry leaves the page and the year's
--                             numbers and stays on file
--
-- A trigger keeps an entry's people and its Prayer & care ask its own
-- church's. Additive, no drop statements. Idempotent.
begin;

create table if not exists public.church_register_entries(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null check (kind in ('baptism', 'dedication', 'wedding', 'funeral', 'membership')),
  membership text check (membership is null or membership in ('joined', 'transferred_in', 'transferred_out', 'removed')),
  status text not null default 'done' check (status in ('planned', 'done')),
  event_on date not null,
  people jsonb not null default '[]'::jsonb
    check (jsonb_typeof(people) = 'array' and jsonb_array_length(people) between 1 and 12),
  contact_ids uuid[] not null default '{}',
  officiant text check (officiant is null or char_length(officiant) <= 120),
  place text check (place is null or char_length(place) <= 160),
  other_church text check (other_church is null or char_length(other_church) <= 160),
  notes text not null default '' check (char_length(notes) <= 2000),
  source text not null default 'office' check (source in ('office', 'app', 'import')),
  care_request_id uuid references public.ministry_care_requests(id) on delete set null,
  import_key text check (import_key is null or char_length(import_key) <= 120),
  created_by uuid,
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  removed_at timestamptz,
  removed_by uuid,
  constraint church_register_membership_kind check ((kind = 'membership') = (membership is not null)),
  constraint church_register_one_ask unique (care_request_id),
  constraint church_register_one_import unique (business_id, import_key)
);

create index if not exists church_register_by_day
  on public.church_register_entries(business_id, event_on desc) where removed_at is null;
create index if not exists church_register_people
  on public.church_register_entries using gin (contact_ids);

-- An entry's people and its Prayer & care ask belong to its own church,
-- whatever the caller passes.
create or replace function public.church_register_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if exists (select 1 from unnest(new.contact_ids) as p(id)
             where not exists (select 1 from public.contacts c where c.id = p.id and c.business_id = new.business_id)) then
    raise exception 'That person is not in this church';
  end if;
  if new.care_request_id is not null and not exists (
      select 1 from public.ministry_care_requests r
      where r.id = new.care_request_id and r.business_id = new.business_id) then
    raise exception 'That request is not in this church';
  end if;
  return new;
end $$;
create or replace trigger church_register_same_business
  before insert or update of contact_ids, care_request_id, business_id
  on public.church_register_entries for each row execute function public.church_register_same_business();
revoke all on function public.church_register_same_business() from public, anon, authenticated;

alter table public.church_register_entries enable row level security;
revoke all on public.church_register_entries from anon, authenticated;
grant all on public.church_register_entries to service_role;

commit;

-- Check after applying (one row, RLS on, no policies; the trigger is there):
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies,
--          (select count(*) from pg_trigger t where t.tgrelid = c.oid and not t.tgisinternal) as triggers
--     from pg_class c where c.relname = 'church_register_entries';

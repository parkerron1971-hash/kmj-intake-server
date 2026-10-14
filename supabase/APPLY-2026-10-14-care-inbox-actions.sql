-- The Prayer & care inbox can act, not just read (Subsplash exit plan,
-- step 1, 2026-10-14). A request moves new -> reviewed -> closed, can be
-- marked "prayed", and carries private notes. Idempotent.
--
-- Same lock as the requests themselves: service role only. The browser
-- never reads or writes these; private_care.py does, after its own owner
-- check (see docs/RLS_MODEL.md: no cross-table policy, so no 42P17).
begin;

alter table public.ministry_care_requests
  add column if not exists prayed_at timestamptz,
  add column if not exists status_changed_at timestamptz,
  add column if not exists updated_at timestamptz;

create table if not exists public.ministry_care_notes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  request_id uuid not null references public.ministry_care_requests(id) on delete cascade,
  author_id uuid,
  body text not null check (length(btrim(body)) between 1 and 4000),
  created_at timestamptz not null default now()
);
create index if not exists ministry_care_notes_request
  on public.ministry_care_notes(request_id, created_at);
create index if not exists ministry_care_notes_business
  on public.ministry_care_notes(business_id, created_at desc);

alter table public.ministry_care_notes enable row level security;
revoke all on public.ministry_care_notes from anon, authenticated;
grant all on public.ministry_care_notes to service_role;

-- A note belongs to a request in the same business, whatever the caller
-- passes.
create or replace function public.ministry_care_note_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.ministry_care_requests r
                 where r.id = new.request_id and r.business_id = new.business_id) then
    raise exception 'That request is not in this business';
  end if;
  return new;
end $$;
drop trigger if exists ministry_care_note_same_business on public.ministry_care_notes;
create trigger ministry_care_note_same_business before insert or update on public.ministry_care_notes
  for each row execute function public.ministry_care_note_same_business();

commit;

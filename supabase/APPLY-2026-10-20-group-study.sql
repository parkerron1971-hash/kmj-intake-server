-- This week's study: questions from Sunday's message (the approved canvas
-- "Church Groups, Together", boards Meet, Lead, Settings and Main:
-- "Questions from Sunday's message: Chief drafts them each week; Tasha
-- approves before the group sees them"). Idempotent.
--
--   groups.study_on   the office's switch per group (on unless turned off)
--   group_studies     one group's questions for one message: drafted from
--                     the office's own questions or by Chief (`drafted`,
--                     kept as made), the leader's version (`questions`),
--                     and when a leader posted it (null = still a draft
--                     only its leaders see)
begin;

alter table public.groups add column if not exists study_on boolean not null default true;

create table if not exists public.group_studies(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.groups(id) on delete cascade,
  sermon_id uuid not null references public.sermons(id) on delete cascade,
  source text not null check (source in ('office','chief')),
  drafted jsonb not null default '[]'::jsonb
    check (jsonb_typeof(drafted) = 'array' and jsonb_array_length(drafted) <= 8 and octet_length(drafted::text) <= 4000),
  questions jsonb not null default '[]'::jsonb
    check (jsonb_typeof(questions) = 'array' and jsonb_array_length(questions) <= 8 and octet_length(questions::text) <= 4000),
  posted_at timestamptz,
  posted_by uuid references public.contacts(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (group_id, sermon_id)
);
create index if not exists group_studies_group on public.group_studies(business_id, group_id, created_at desc);
create index if not exists group_studies_sermon on public.group_studies(sermon_id);

-- The office reads them; only the server writes (the weekly drafts, and a
-- leader's post after checking they lead the group).
alter table public.group_studies enable row level security;
drop policy if exists tenant_member_read on public.group_studies;
create policy tenant_member_read on public.group_studies for select to authenticated
  using (public.is_business_member(business_id));
drop policy if exists business_owner_read on public.group_studies;
create policy business_owner_read on public.group_studies for select to authenticated
  using (business_id in (select id from public.businesses where owner_id = auth.uid()));
revoke all on public.group_studies from anon, authenticated;
grant select on public.group_studies to authenticated;
grant all on public.group_studies to service_role;

create or replace function public.group_studies_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
    raise exception 'That group is not in this business';
  end if;
  if not exists (select 1 from public.sermons s where s.id = new.sermon_id and s.business_id = new.business_id) then
    raise exception 'That message is not in this business';
  end if;
  if new.posted_by is not null and not exists (
       select 1 from public.contacts c where c.id = new.posted_by and c.business_id = new.business_id) then
    raise exception 'That person is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.group_studies_same_business() from public, anon, authenticated;
drop trigger if exists group_studies_same_business on public.group_studies;
create trigger group_studies_same_business before insert or update on public.group_studies
  for each row execute function public.group_studies_same_business();

commit;

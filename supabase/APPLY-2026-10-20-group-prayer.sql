-- A group's prayer wall (part 3 of the approved canvas "Church Groups,
-- Together", boards Prayer and Settings; Kevin, 2026-10-20: "anything that
-- I could be missing"). Requests the group prays over together; a private
-- one still goes only to the pastors (ministry_care_requests, as /my/prayer
-- does), and words about harm, abuse or a death always go to a pastor: the
-- wall then shows only that a pastor has it. Idempotent.
--
--   group_prayers       a request on the wall (or the "a pastor has it" card)
--   group_prayer_marks  "I'm praying" and "Praise God", one of each per person
begin;

create table if not exists public.group_prayers(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  group_id uuid not null references public.groups(id) on delete cascade,
  contact_id uuid references public.contacts(id) on delete set null,
  -- null on a card whose words went to a pastor instead of the wall
  body text check (body is null or length(btrim(body)) between 1 and 1000),
  to_pastor boolean not null default false,
  answered_at timestamptz,
  praise text not null default '' check (length(praise) <= 500),
  removed_at timestamptz,
  removed_by uuid,
  created_at timestamptz not null default now(),
  check (to_pastor or body is not null),
  check (not to_pastor or body is null)
);
create index if not exists group_prayers_wall on public.group_prayers(group_id, created_at desc) where removed_at is null;
create index if not exists group_prayers_business on public.group_prayers(business_id, created_at);

create table if not exists public.group_prayer_marks(
  prayer_id uuid not null references public.group_prayers(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null check (kind in ('praying','praise')),
  created_at timestamptz not null default now(),
  primary key (prayer_id, contact_id, kind)
);
create index if not exists group_prayer_marks_business on public.group_prayer_marks(business_id, created_at);

-- Server-only, like the group's chat: members reach it through the member
-- app, which checks they're in the group.
alter table public.group_prayers enable row level security;
alter table public.group_prayer_marks enable row level security;
revoke all on public.group_prayers from anon, authenticated;
revoke all on public.group_prayer_marks from anon, authenticated;
grant all on public.group_prayers to service_role;
grant all on public.group_prayer_marks to service_role;

-- Everything on a wall is this church's own: its group, its people.
create or replace function public.group_prayer_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'group_prayers' then
    if not exists (select 1 from public.groups g where g.id = new.group_id and g.business_id = new.business_id) then
      raise exception 'That group is not in this business';
    end if;
    if new.contact_id is not null and not exists (
        select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  else
    if not exists (select 1 from public.group_prayers p where p.id = new.prayer_id and p.business_id = new.business_id) then
      raise exception 'That prayer is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.group_prayer_same_business() from public, anon, authenticated;
do $$ declare t text; begin
  foreach t in array array['group_prayers','group_prayer_marks'] loop
    execute format('drop trigger if exists group_prayer_same_business on public.%I', t);
    execute format('create trigger group_prayer_same_business before insert or update on public.%I
      for each row execute function public.group_prayer_same_business()', t);
  end loop;
end $$;

commit;

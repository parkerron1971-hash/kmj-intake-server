-- Families and children (Kevin, 2026-09-29: attendance first, then
-- families and children's check-in, then check-in stations). Idempotent.
--
-- A child is NOT a contact. Contacts are the CRM: they get email
-- audiences, follow-ups and Chief's attention, and no six-year-old belongs
-- there. A child lives in `children`, inside a household whose adults ARE
-- contacts (the parents the church already knows).
--
-- Every table here is server-only: no browser role can read or write it.
-- kids_router.py is the one door, and it checks the caller's seat:
--   names, rooms, pickups, allergies  → any seat that can edit (member+),
--                                       because the welcome desk needs them
--   medical and custody notes         → manager and above
-- The check-in station (a later phase) goes through the same router.
begin;

create table if not exists public.households(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null check (length(btrim(name)) between 1 and 120),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists households_business on public.households(business_id, name);

create table if not exists public.household_adults(
  household_id uuid not null references public.households(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  relationship text not null default 'parent'
    check (relationship in ('parent','guardian','grandparent','other')),
  created_at timestamptz not null default now(),
  primary key (household_id, contact_id)
);
create index if not exists household_adults_contact on public.household_adults(contact_id);

create table if not exists public.children(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  household_id uuid not null references public.households(id) on delete cascade,
  first_name text not null check (length(btrim(first_name)) between 1 and 80),
  last_name text not null default '' check (length(last_name) <= 80),
  birthdate date check (birthdate is null or birthdate between date '1990-01-01' and date '2100-01-01'),
  grade text not null default '' check (length(grade) <= 20),
  -- The room they usually go to ("Nursery", "Preschool"): the church names its own.
  room text not null default '' check (length(room) <= 60),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists children_household on public.children(household_id);
create index if not exists children_business on public.children(business_id, active, first_name);

-- Others a family allows to pick their children up (a grandparent, a
-- neighbour). The household's own adults are always allowed.
create table if not exists public.household_pickups(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  household_id uuid not null references public.households(id) on delete cascade,
  name text not null check (length(btrim(name)) between 1 and 120),
  phone text not null default '' check (length(phone) <= 40),
  relationship text not null default '' check (length(relationship) <= 60),
  created_at timestamptz not null default now()
);
create index if not exists household_pickups_household on public.household_pickups(household_id);

-- The sensitive part of a child's record.
create table if not exists public.child_care_notes(
  child_id uuid primary key references public.children(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  -- Printed on the name tag and shown at check-in: keep it short.
  allergies text not null default '' check (length(allergies) <= 200),
  medical text not null default '' check (length(medical) <= 1000),
  -- Court orders, "never release to…": managers and above only.
  custody text not null default '' check (length(custody) <= 1000),
  updated_at timestamptz not null default now(),
  updated_by uuid
);

do $$ declare t text; begin
  foreach t in array array['households','household_adults','children','household_pickups','child_care_notes'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- Every row's household, contact and child must be this business's own.
create or replace function public.kids_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name in ('household_adults','children','household_pickups') then
    if not exists (select 1 from public.households h
                   where h.id = new.household_id and h.business_id = new.business_id) then
      raise exception 'That family is not in this business';
    end if;
  end if;
  if tg_table_name = 'household_adults' then
    if not exists (select 1 from public.contacts c
                   where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  if tg_table_name = 'child_care_notes' then
    if not exists (select 1 from public.children k
                   where k.id = new.child_id and k.business_id = new.business_id) then
      raise exception 'That child is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.kids_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['household_adults','children','household_pickups','child_care_notes'] loop
    execute format('drop trigger if exists kids_same_business on public.%I', t);
    execute format('create trigger kids_same_business before insert or update on public.%I
      for each row execute function public.kids_same_business()', t);
  end loop;
end $$;

commit;

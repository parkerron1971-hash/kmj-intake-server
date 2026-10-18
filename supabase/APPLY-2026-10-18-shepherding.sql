-- Shepherding, round 1 (Kevin, 2026-10-17: "yes you can start design and
-- do as what we planned and those that can shepherd are elders and
-- pastors. visitors should go under welcome for now"; canvas
-- 31su6kdYmYecH5b2NxjBJN). Every member family belongs to a pastor or an
-- elder who reaches them once a month. Idempotent.
--
--   children.contact_id        a member who is a child (under 18) joins their
--                              family as a child, linked to their record in
--                              Members. Never as a household adult: household
--                              adults may pick children up at the Kids kiosk.
--   church_family_dismissals   "Not a family": a suggestion Chief stops making.
--   church_shepherd_settings   the Ministers switch, families per shepherd
--                              (12) and for the Lead Pastor (10), the rhythm.
--   church_shepherds           which shepherd has which family.
--   church_shepherd_drafts     Chief's proposal, kept with the pastor's moves
--                              until it is approved or thrown away.
--   church_shepherd_touches    a call, a visit, a text or a talk at church,
--                              with the shepherd's note. Read by the family's
--                              shepherd and the office; never the family.
--
-- Every table is server-only, like the families tables: no browser role can
-- read or write it; church_router and member_portal_lead are the doors.
begin;

-- ─── a member who is a child ─────────────────────────────────────────
alter table public.children add column if not exists contact_id uuid
  references public.contacts(id) on delete set null;
create unique index if not exists children_contact on public.children(contact_id) where contact_id is not null;

-- Every row's household, contact and child must be this business's own
-- (2026-09-29), and now a child's linked member record too.
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
  -- Nested, not "and": plpgsql may read new.contact_id on a table without it.
  if tg_table_name = 'children' then
    if new.contact_id is not null then
      if not exists (select 1 from public.contacts c
                     where c.id = new.contact_id and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
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

-- ─── shepherding ─────────────────────────────────────────────────────
create table if not exists public.church_family_dismissals(
  business_id uuid not null references public.businesses(id) on delete cascade,
  key text not null check (key ~ '^f_[0-9a-f]{12}$'),
  created_at timestamptz not null default now(),
  primary key (business_id, key)
);

create table if not exists public.church_shepherd_settings(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  ministers boolean not null default false,
  cap smallint not null default 12 check (cap between 1 and 40),
  lead_cap smallint not null default 10 check (lead_cap between 1 and 40),
  rhythm_days smallint not null default 30 check (rhythm_days between 7 and 120),
  updated_by uuid,
  updated_at timestamptz not null default now()
);

create table if not exists public.church_shepherds(
  household_id uuid primary key references public.households(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  shepherd_contact_id uuid not null references public.contacts(id) on delete cascade,
  assigned_at timestamptz not null default now(),
  assigned_by uuid,
  reason text not null default '' check (length(reason) <= 300)
);
create index if not exists church_shepherds_business on public.church_shepherds(business_id, shepherd_contact_id);

create table if not exists public.church_shepherd_drafts(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  rows jsonb not null default '[]'::jsonb check (jsonb_typeof(rows) = 'array'),
  made_at timestamptz not null default now(),
  made_by uuid
);

create table if not exists public.church_shepherd_touches(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  household_id uuid not null references public.households(id) on delete cascade,
  shepherd_contact_id uuid references public.contacts(id) on delete set null,
  kind text not null check (kind in ('call','visit','text','church')),
  note text not null default '' check (length(note) <= 2000),
  needs_pastor boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists church_shepherd_touches_household on public.church_shepherd_touches(household_id, created_at desc);
create index if not exists church_shepherd_touches_business on public.church_shepherd_touches(business_id, created_at desc);

do $$ declare t text; begin
  foreach t in array array['church_family_dismissals','church_shepherd_settings','church_shepherds',
                           'church_shepherd_drafts','church_shepherd_touches'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- A family and its shepherd are always this business's own.
create or replace function public.church_shepherd_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.households h
                 where h.id = new.household_id and h.business_id = new.business_id) then
    raise exception 'That family is not in this business';
  end if;
  if new.shepherd_contact_id is not null and not exists (
      select 1 from public.contacts c where c.id = new.shepherd_contact_id and c.business_id = new.business_id) then
    raise exception 'That shepherd is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.church_shepherd_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['church_shepherds','church_shepherd_touches'] loop
    execute format('drop trigger if exists church_shepherd_same_business on public.%I', t);
    execute format('create trigger church_shepherd_same_business before insert or update on public.%I
      for each row execute function public.church_shepherd_same_business()', t);
  end loop;
end $$;

commit;

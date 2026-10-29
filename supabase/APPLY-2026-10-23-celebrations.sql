-- Celebrations in the church's news (part 3 of the approved canvas "Church
-- News & Celebrations", Hfrz3Y174kbDmJv1G4puVq). Kevin, 2026-10-23: "Build a
-- celebration of members: Birthdays, Anniversary, Achievements … a thread
-- like Facebook where people can say congratulations", and his call the
-- same day: ask each member first.
--   * member_celebrations: what each member said yes to (null birthday =
--     never asked); the office's stop, for someone who has passed away;
--   * member_anniversaries: a couple's day, celebrated only when BOTH said
--     yes;
--   * church_posts gains the day a celebration is for and, for an
--     anniversary, the other spouse; one post per person, kind and day.
-- Idempotent.

begin;

create table if not exists public.member_celebrations(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  -- null = never answered; true = celebrate my birthday; false = please don't
  birthday boolean,
  -- the day, when the record has no birthdate: a member gives month and day
  -- only, never a year (a guessed year would change who counts as a teen)
  birthday_md text check (birthday_md ~ '^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'),
  milestones boolean not null default false,
  answered_at timestamptz,
  -- the office stops every celebration of someone (they passed away, or asked)
  stopped text check (stopped in ('passed','office')),
  stopped_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (business_id, contact_id)
);

create table if not exists public.member_anniversaries(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  a_id uuid not null references public.contacts(id) on delete cascade,
  b_id uuid not null references public.contacts(id) on delete cascade,
  married_on date not null check (married_on > date '1900-01-01'),
  a_yes boolean not null default false,
  b_yes boolean not null default false,
  show_years boolean not null default false,
  created_at timestamptz not null default now(),
  check (a_id <> b_id)
);
create unique index if not exists member_anniversaries_couple
  on public.member_anniversaries(business_id, least(a_id, b_id), greatest(a_id, b_id));
create index if not exists member_anniversaries_b on public.member_anniversaries(b_id);

alter table public.church_posts add column if not exists celebrate_on date;
alter table public.church_posts add column if not exists partner_id uuid references public.contacts(id) on delete cascade;
create unique index if not exists church_posts_celebrate_once
  on public.church_posts(business_id, kind, person_id, celebrate_on) where celebrate_on is not null;

do $$ declare t text; begin
  foreach t in array array['member_celebrations','member_anniversaries'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists business_owner_read on public.%I', t);
    execute format('create policy business_owner_read on public.%I for select to authenticated
      using (business_id in (select id from public.businesses where owner_id = auth.uid()))', t);
    execute format('drop policy if exists tenant_member_read on public.%I', t);
    execute format('create policy tenant_member_read on public.%I for select to authenticated
      using (public.is_business_member(business_id))', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- The people in a choice or a couple must be this church's own; a post's
-- other spouse too.
create or replace function public.celebrations_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name = 'member_celebrations' then
    if not exists (select 1 from public.contacts c where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif tg_table_name = 'member_anniversaries' then
    if not exists (select 1 from public.contacts c where c.id = new.a_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
    if not exists (select 1 from public.contacts c where c.id = new.b_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  elsif tg_table_name = 'church_posts' then
    if new.partner_id is not null then
      if not exists (select 1 from public.contacts c where c.id = new.partner_id and c.business_id = new.business_id) then
        raise exception 'That person is not in this business';
      end if;
    end if;
  end if;
  return new;
end $$;
revoke all on function public.celebrations_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['member_celebrations','member_anniversaries','church_posts'] loop
    execute format('drop trigger if exists celebrations_same_business on public.%I', t);
    execute format('create trigger celebrations_same_business before insert or update on public.%I
      for each row execute function public.celebrations_same_business()', t);
  end loop;
end $$;

commit;

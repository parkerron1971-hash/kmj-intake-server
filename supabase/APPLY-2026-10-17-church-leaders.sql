-- Leaders & follow-up (Kevin, 2026-10-17: "assigning leadership roles to
-- members so the system can recognize them … see assigned work that chief
-- gives, make comments from conversations they had with members"; design
-- canvas LG4Q97HqtEM4ByyXmmSrCP, "build it"). Idempotent.
--
--   church_leader_roles     a member (a contact) holds a role: pastor,
--                           baptism minister, care team, Welcome Team lead,
--                           a team's leader (scope = the team's name), a
--                           class's teacher (scope = the course id)
--   church_follow_ups       one person, one card: the leader Chief handed
--                           them to, why, the path's steps and the clock
--   church_follow_up_notes  what happened: a leader's conversation, Chief's
--                           assignment, a nudge, a step marked done
--
-- Every table is server-only: no browser role can read or write it.
-- church_follow_up.py is the one door. The office reaches it through
-- church_router (owner and staff seats); a leader through their member
-- page (member_portal_lead.py), which shows only the follow-ups handed to
-- them. Prayer and care never come here (private_care keeps those).
begin;

create table if not exists public.church_leader_roles(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  role text not null check (role in ('pastor','baptism_minister','care_team','welcome_lead','team_leader','class_teacher')),
  scope text not null default '' check (length(scope) <= 120),
  status text not null default 'invited' check (status in ('invited','active','declined')),
  invited_by uuid,
  invited_at timestamptz not null default now(),
  answered_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (business_id, contact_id, role, scope)
);
create index if not exists church_leader_roles_business on public.church_leader_roles(business_id, role, status);
create index if not exists church_leader_roles_contact on public.church_leader_roles(contact_id);

create table if not exists public.church_follow_ups(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  card_key text not null check (length(card_key) between 1 and 80),
  card_name text not null default '' check (length(card_name) <= 120),
  path_kind text not null check (path_kind in ('baptism','serve','visit','connect','general')),
  answers jsonb not null default '[]'::jsonb,
  steps jsonb not null default '[]'::jsonb,
  step integer not null default 0 check (step between 0 and 20),
  leader_contact_id uuid references public.contacts(id) on delete set null,
  leader_role text not null default '' check (length(leader_role) <= 40),
  reason text not null default '' check (length(reason) <= 400),
  assigned_by text not null default 'chief' check (length(assigned_by) <= 60),
  assigned_at timestamptz,
  -- When the leader was told it's theirs (the sweep emails them once).
  leader_told_at timestamptz,
  due_at timestamptz,
  status text not null default 'open' check (status in ('open','done','handed_back','closed')),
  late_level integer not null default 0 check (late_level between 0 and 3),
  source_event text not null default '' check (length(source_event) <= 80),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  done_at timestamptz
);
create index if not exists church_follow_ups_board on public.church_follow_ups(business_id, status, created_at desc);
create index if not exists church_follow_ups_leader on public.church_follow_ups(leader_contact_id, status);
create index if not exists church_follow_ups_due on public.church_follow_ups(status, due_at) where status = 'open';
-- One follow-up per submission: a retried card never makes two.
create unique index if not exists church_follow_ups_source
  on public.church_follow_ups(business_id, source_event) where source_event <> '';

create table if not exists public.church_follow_up_notes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  follow_up_id uuid not null references public.church_follow_ups(id) on delete cascade,
  author_kind text not null check (author_kind in ('leader','office','chief')),
  author_contact_id uuid references public.contacts(id) on delete set null,
  author_user_id uuid,
  author_name text not null default '' check (length(author_name) <= 120),
  kind text not null check (kind in ('talked','message','noanswer','notnow','note','assigned','reassigned',
                                     'step','nudged','pastors_told','reassign_asked','handed_back','done')),
  body text not null default '' check (length(body) <= 4000),
  pastors_only boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists church_follow_up_notes_follow_up on public.church_follow_up_notes(follow_up_id, created_at desc);

do $$ declare t text; begin
  foreach t in array array['church_leader_roles','church_follow_ups','church_follow_up_notes'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- Every person, leader and follow-up a row names must be this business's own.
create or replace function public.church_leaders_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_table_name in ('church_leader_roles','church_follow_ups') then
    if not exists (select 1 from public.contacts c
                   where c.id = new.contact_id and c.business_id = new.business_id) then
      raise exception 'That person is not in this business';
    end if;
  end if;
  if tg_table_name = 'church_follow_ups' and new.leader_contact_id is not null then
    if not exists (select 1 from public.contacts c
                   where c.id = new.leader_contact_id and c.business_id = new.business_id) then
      raise exception 'That leader is not in this business';
    end if;
  end if;
  if tg_table_name = 'church_follow_up_notes' then
    if not exists (select 1 from public.church_follow_ups f
                   where f.id = new.follow_up_id and f.business_id = new.business_id) then
      raise exception 'That follow-up is not in this business';
    end if;
  end if;
  return new;
end $$;
revoke all on function public.church_leaders_same_business() from public, anon, authenticated;

do $$ declare t text; begin
  foreach t in array array['church_leader_roles','church_follow_ups','church_follow_up_notes'] loop
    execute format('drop trigger if exists church_leaders_same_business on public.%I', t);
    execute format('create trigger church_leaders_same_business before insert or update on public.%I
      for each row execute function public.church_leaders_same_business()', t);
  end loop;
end $$;

commit;

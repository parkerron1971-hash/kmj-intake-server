-- Notifications to members' phones (Subsplash exit plan, open decision 1;
-- Kevin, 2026-10-14: yes). The installed member app (/my) can receive Web
-- Push. Kept apart from the staff table push_subscriptions on purpose: a
-- staff send (morning brief, send_to_business) must never reach a member.
-- Idempotent.
--
-- Service role only. The member app has no Supabase session; member_push.py
-- writes and reads these after its own signed-session check.
begin;

-- One row per device the member turned notifications on for.
create table if not exists public.member_push_subscriptions(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  endpoint text not null unique,
  subscription jsonb not null,
  user_agent text,
  created_at timestamptz not null default now(),
  last_sent_at timestamptz
);
create index if not exists member_push_subscriptions_person
  on public.member_push_subscriptions(business_id, contact_id);

-- The kinds a member turned off. Per person, not per device: "members can
-- turn each kind off".
create table if not exists public.member_push_prefs(
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  off text[] not null default '{}',
  updated_at timestamptz not null default now(),
  primary key (business_id, contact_id)
);

-- Every send, once: announcements the church wrote (who, what, how many
-- phones) and automatic notes (kind + the thing they are about), so a
-- sweep never sends the same note twice.
create table if not exists public.member_push_sends(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null,
  ref_id text not null,
  title text not null,
  body text,
  url text,
  sent_by uuid,
  recipients int not null default 0,
  created_at timestamptz not null default now(),
  unique (business_id, kind, ref_id)
);
create index if not exists member_push_sends_business
  on public.member_push_sends(business_id, created_at desc);

alter table public.member_push_subscriptions enable row level security;
alter table public.member_push_prefs enable row level security;
alter table public.member_push_sends enable row level security;
revoke all on public.member_push_subscriptions from anon, authenticated;
revoke all on public.member_push_prefs from anon, authenticated;
revoke all on public.member_push_sends from anon, authenticated;
grant all on public.member_push_subscriptions to service_role;
grant all on public.member_push_prefs to service_role;
grant all on public.member_push_sends to service_role;

-- A device belongs to a person in the same church, whatever the caller passes.
create or replace function public.member_push_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.contacts c
                 where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  return new;
end $$;
drop trigger if exists member_push_subscriptions_same_business on public.member_push_subscriptions;
create trigger member_push_subscriptions_same_business before insert or update on public.member_push_subscriptions
  for each row execute function public.member_push_same_business();
drop trigger if exists member_push_prefs_same_business on public.member_push_prefs;
create trigger member_push_prefs_same_business before insert or update on public.member_push_prefs
  for each row execute function public.member_push_same_business();

commit;

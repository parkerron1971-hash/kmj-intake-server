-- Shepherding, round 2: what Chief watches, and who is told (canvas
-- 31su6kdYmYecH5b2NxjBJN, board 4). Drifting is judged on Sundays only
-- (attendance, never giving); nobody is flagged unless they came 2 of the
-- 6 recorded Sundays before the 3 they missed; a week with no reach goes
-- one step up the shepherd's chain. Idempotent.
--
--   church_shepherd_signals   one row per family that started drifting: the
--                             first Sunday they missed, the last Sunday they
--                             were here, how far up the chain it has gone and
--                             when; resolved when they come back.
--   church_shepherd_notices   every email the shepherding sweep sends, by key,
--                             so each is sent once (Monday digests and briefs,
--                             care-need notices, the week's run itself).
--
-- Server-only, like the rest of shepherding: no browser role can read or
-- write either table; church_shepherd_signals.py is the one door.
begin;

create table if not exists public.church_shepherd_signals(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  household_id uuid not null references public.households(id) on delete cascade,
  kind text not null default 'drift' check (kind in ('drift')),
  started_on date not null,
  last_seen date,
  level smallint not null default 0 check (level between 0 and 20),
  told_at timestamptz not null default now(),
  resolved_at timestamptz,
  created_at timestamptz not null default now()
);
-- One open signal of a kind per family.
create unique index if not exists church_shepherd_signals_open
  on public.church_shepherd_signals(household_id, kind) where resolved_at is null;
create index if not exists church_shepherd_signals_business
  on public.church_shepherd_signals(business_id, resolved_at);

create table if not exists public.church_shepherd_notices(
  business_id uuid not null references public.businesses(id) on delete cascade,
  key text not null check (length(key) between 1 and 200),
  sent_at timestamptz not null default now(),
  primary key (business_id, key)
);

do $$ declare t text; begin
  foreach t in array array['church_shepherd_signals','church_shepherd_notices'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- A signal's family is always this business's own. (church_shepherd_same_business
-- reads a shepherd column this table doesn't have, so it gets its own check.)
create or replace function public.church_shepherd_signal_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if not exists (select 1 from public.households h
                 where h.id = new.household_id and h.business_id = new.business_id) then
    raise exception 'That family is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.church_shepherd_signal_same_business() from public, anon, authenticated;

drop trigger if exists church_shepherd_signal_same_business on public.church_shepherd_signals;
create trigger church_shepherd_signal_same_business before insert or update on public.church_shepherd_signals
  for each row execute function public.church_shepherd_signal_same_business();

commit;

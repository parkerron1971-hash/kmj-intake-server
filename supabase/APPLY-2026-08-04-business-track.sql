-- APPLY-2026-08-04-business-track.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- THE BUSINESS TRACK — the established-business counterpart to the
-- Strategy Track.
--
-- Until now the intake fork at onboarding step 1 was lopsided:
--   "I have an idea I want to launch"      -> strategy_tracks, an 8-phase
--                                             coached Strategy Session
--   "I have a business I want to manage"   -> a 12-turn chat inside
--                                             onboarding whose answers were
--                                             harvested by a 6-keyword regex
--
-- The established path now gets its own coached, resumable, multi-session
-- track that opens the same way the Strategy Session does — immediately
-- after the base questions. Eight phases, each producing a structured
-- deliverable that Chief reads afterwards:
--
--   1. owner        -> who the practitioner is, how they work  (practitioners)
--   2. business     -> shape/size/history of the business  (business_profiles)
--   3. offerings    -> what they sell and what they charge  (offerings)
--   4. clients      -> who they serve today  (voice_profile, chief_memories)
--   5. money        -> how money moves in and out
--   6. operations   -> the stack they already run on, what is manual
--   7. growth       -> where they want to be  (goals)
--   8. plan         -> the first 30 days + the day-one plug-in list
--
-- Mirrors strategy_tracks structurally so the coach machinery, the session
-- ledger and the exit ramp are shared shapes rather than parallel designs.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

create table if not exists public.business_tracks (
  id                uuid primary key default gen_random_uuid(),
  business_id       uuid not null references public.businesses(id) on delete cascade,
  status            text not null default 'in_progress'
                      check (status in ('in_progress', 'completed', 'paused')),
  current_phase     text not null default 'owner',
  -- Catch-all for unstructured phases + the session ledger
  -- (phases.session_log[] = [{date, ts, summary, phases_progressed[]}]).
  phases            jsonb not null default '{}'::jsonb,
  -- One column per structured deliverable.
  owner_profile     jsonb not null default '{}'::jsonb,
  business_shape    jsonb not null default '{}'::jsonb,
  offerings_captured jsonb not null default '[]'::jsonb,
  audience          jsonb not null default '{}'::jsonb,
  money_map         jsonb not null default '{}'::jsonb,
  operations_map    jsonb not null default '{}'::jsonb,
  growth_plan       jsonb not null default '{}'::jsonb,
  first_30_days     jsonb not null default '{}'::jsonb,
  completed_at      timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_business_tracks_business
  on public.business_tracks(business_id);
create index if not exists idx_business_tracks_status
  on public.business_tracks(business_id, status);

-- Standard updated_at trigger (function created in earlier migrations).
drop trigger if exists trg_business_tracks_updated on public.business_tracks;
create trigger trg_business_tracks_updated
  before update on public.business_tracks
  for each row execute function public.set_updated_at_timestamp();

-- ─── RLS ────────────────────────────────────────────────────────────
-- The seat-access pattern (APPLY-2026-07-31-seat-access-data-plane.sql):
-- SECURITY DEFINER helpers, never inline cross-table EXISTS — that is the
-- 42P17 recursion outage class. Read for any active seat, write for
-- writers (the owner included). The backend's service-role paths are
-- unaffected either way.
alter table public.business_tracks enable row level security;

drop policy if exists tenant_member_read on public.business_tracks;
create policy tenant_member_read on public.business_tracks
  for select to authenticated
  using (public.is_business_member(business_id));

drop policy if exists tenant_writer_write on public.business_tracks;
create policy tenant_writer_write on public.business_tracks
  for all to authenticated
  using (public.is_business_writer(business_id))
  with check (public.is_business_writer(business_id));

-- Realtime, matching strategy_tracks.
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    begin
      alter publication supabase_realtime add table public.business_tracks;
    exception when duplicate_object then null;
    end;
  end if;
end $$;

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expected: 2 rows — tenant_member_read (SELECT), tenant_writer_write (ALL).
select policyname, cmd
  from pg_policies
 where schemaname = 'public'
   and tablename = 'business_tracks'
 order by policyname;

-- Expected: 1 row, business_tracks with rowsecurity = true.
select relname, relrowsecurity as rowsecurity
  from pg_class
 where relname = 'business_tracks'
   and relnamespace = 'public'::regnamespace;

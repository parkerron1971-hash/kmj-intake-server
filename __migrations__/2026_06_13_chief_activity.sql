-- 2026_06_13_chief_activity.sql
-- "Chief, while you were away" — a log of the actions Chief executed on
-- the practitioner's behalf, tagged with the originating device (source).
-- This lets the DESKTOP surface a "from your phone, I did X, Y, Z" recap
-- when the practitioner returns, and a live toast as actions land. It is
-- also the rail that Feature 2 (queued desk jobs) writes its completion
-- notices onto later.
--
-- Writes go through the Railway service role (the chief chat handler).
-- RLS lets a practitioner read/update ONLY their own rows — the recap is
-- "what YOU did from your other device", so user-id scoping is exact and
-- needs no cross-table EXISTS (Rule R2 / RLS-cycle lesson honored).

create table if not exists public.chief_activity (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null,
  business_id uuid not null,
  source      text not null default 'desktop',  -- 'mobile' | 'desktop' | 'voice' | 'system'
  action_type text,                              -- the [ACTION:] type that ran
  label       text not null,                     -- human label ("Client Care")
  summary     text,                              -- result string ("drafted", "health = 82")
  nav         text,                              -- deep-link target, if the action had one
  seen_at     timestamptz,                       -- null until the desktop recap shows it
  created_at  timestamptz not null default now()
);

create index if not exists idx_chief_activity_user
  on public.chief_activity (user_id, created_at desc);
create index if not exists idx_chief_activity_unseen
  on public.chief_activity (user_id, seen_at) where seen_at is null;

alter table public.chief_activity enable row level security;

drop policy if exists chief_activity_select_own on public.chief_activity;
create policy chief_activity_select_own on public.chief_activity
  for select using (auth.uid() = user_id);

-- INSERT policy is REQUIRED: the chat handler logs activity under the
-- practitioner's own JWT (authenticated role, not service_role), so RLS
-- must permit a caller to insert rows for themselves. Without this, every
-- log write is silently rejected and the recap stays empty. The check
-- mirrors the data the handler writes (user_id = the caller).
drop policy if exists chief_activity_insert_own on public.chief_activity;
create policy chief_activity_insert_own on public.chief_activity
  for insert with check (auth.uid() = user_id);

drop policy if exists chief_activity_update_own on public.chief_activity;
create policy chief_activity_update_own on public.chief_activity
  for update using (auth.uid() = user_id);

-- Service role bypasses RLS for the insert (chat handler logs activity).
grant select, insert, update, delete on public.chief_activity to service_role;

-- Live toast on desktop relies on realtime; add the table to the
-- publication idempotently (no-op if already present).
do $$
begin
  begin
    alter publication supabase_realtime add table public.chief_activity;
  exception
    when duplicate_object then null;
    when undefined_object then null;  -- publication not present (non-realtime env)
  end;
end $$;

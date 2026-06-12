-- 2026_06_12_push_subscriptions.sql
-- Chief-in-your-pocket — Web Push subscriptions (one row per device).
-- Writes go through the Railway service role (push router); RLS lets a
-- practitioner read/delete only their own devices. Rule R2: helpers +
-- explicit service_role grant, no cross-table EXISTS.

create table if not exists public.push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  business_id uuid not null,
  endpoint text not null unique,
  subscription jsonb not null,
  user_agent text,
  created_at timestamptz not null default now()
);

create index if not exists idx_push_subs_user on public.push_subscriptions (user_id);
create index if not exists idx_push_subs_business on public.push_subscriptions (business_id);

alter table public.push_subscriptions enable row level security;

drop policy if exists push_subs_select_own on public.push_subscriptions;
create policy push_subs_select_own on public.push_subscriptions
  for select using (auth.uid() = user_id);

drop policy if exists push_subs_delete_own on public.push_subscriptions;
create policy push_subs_delete_own on public.push_subscriptions
  for delete using (auth.uid() = user_id);

-- Service role bypasses RLS for insert/upsert/prune (router + senders).
grant select, insert, update, delete on public.push_subscriptions to service_role;

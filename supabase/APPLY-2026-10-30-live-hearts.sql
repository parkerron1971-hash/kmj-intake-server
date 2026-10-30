-- APPLY-2026-10-30-live-hearts.sql
--
-- The live room's hearts (Kevin 2026-10-30, "the design is great! build
-- it": the member app's /my/live redesign, member_portal_live.py). A heart
-- is a tap, not a message: it isn't kept per person, only counted on the
-- live service, so every phone can float the hearts the others sent.
--
--   live_sessions.hearts   how many hearts this service has had
--   live_add_hearts(...)   adds a phone's batch (1..30) to a LIVE service,
--                          atomically, and returns the new total; the
--                          server only (the tables are server-only too)
--
-- Phones read the total with the chat poll they already make (the same
-- live_sessions row), so hearts cost no extra read. A heart never bumps
-- chat_version, so it never makes a phone fetch the chat again.
--
-- Apply BEFORE the code that reads live_sessions.hearts deploys: the
-- live page selects the column. Check after:
--   select column_name from information_schema.columns
--    where table_name = 'live_sessions' and column_name = 'hearts';
--   select proname from pg_proc where proname = 'live_add_hearts';
-- Rollback: drop the function, then the column (the code must go first).

alter table public.live_sessions add column if not exists hearts integer not null default 0;

create or replace function public.live_add_hearts(p_session uuid, p_business uuid, p_n integer)
returns integer
language sql
security definer
set search_path = public
as $$
  update public.live_sessions
     set hearts = hearts + greatest(1, least(coalesce(p_n, 1), 30))
   where id = p_session and business_id = p_business and status = 'live'
  returning hearts;
$$;

revoke all on function public.live_add_hearts(uuid, uuid, integer) from public, anon, authenticated;
grant execute on function public.live_add_hearts(uuid, uuid, integer) to service_role;

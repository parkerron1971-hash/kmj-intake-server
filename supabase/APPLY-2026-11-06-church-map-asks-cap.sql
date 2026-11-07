-- Ten a day, held by the database (docs/CHURCH_LEADERS_STEP2.md §10, "Is this right?"; the open item from
-- kmj-intake-server#1761). An office login sends at most ten fixes and gaps a day (church_map_asks.CAP).
-- The code checks the count before it saves and counts again after (_held_to_cap), but two saves in the same
-- instant can both pass the first check, and the recount takes one back only after both were in.
--
-- This file adds one BEFORE INSERT trigger on church_map_asks for kind fix or gap. It takes a transaction
-- lock for that church and that login (pg_advisory_xact_lock), so two saves from one login wait for each
-- other, then counts that login's fixes and gaps in the last 24 hours. With ten already there it refuses the
-- insert with its own SQLSTATE, PT429 (PostgREST answers it as HTTP 429), and a message that starts with
-- church_map_asks_cap. church_map_asks._insert reads that refusal (sb_clients.last_error) and answers the
-- same 429 words as the check before it. Before this file, the code's own checks still hold.
--
--   church_map_asks_cap()   the trigger function: SECURITY INVOKER (it runs as whoever inserts: the server's
--                           service role, which reads every row), search_path empty (every name qualified),
--                           VOLATILE, so its count after the lock sees a save the lock waited for
--   church_map_asks_cap     BEFORE INSERT ... FOR EACH ROW WHEN (new.kind in ('fix', 'gap'))
--
-- A confirmed check (kind confirmed) isn't counted, as in the code. A row with no asked_by isn't counted
-- (the code always sets it). The count uses the church_map_asks_mine index (business_id, asked_by,
-- asked_at desc). No table, column, policy or grant on church_map_asks changes; RLS is as it was. Idempotent:
-- create or replace the function, drop the trigger if it exists, then create it. Needs
-- APPLY-2026-11-05-church-map-asks.sql first. Applied by hand after review.
begin;

-- Fail fast rather than queue behind a long read (creating a trigger locks the table briefly).
set local lock_timeout = '5s';

create or replace function public.church_map_asks_cap() returns trigger
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  v_sent integer;
begin
  if new.asked_by is null then
    return new;
  end if;
  -- One save at a time for this login at this church, held to the end of the save's transaction.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'church_map_asks_cap:' || new.business_id::text || ':' || new.asked_by::text, 0));
  select pg_catalog.count(*) into v_sent
    from public.church_map_asks a
   where a.business_id = new.business_id
     and a.asked_by = new.asked_by
     and a.kind in ('fix', 'gap')
     and a.asked_at >= pg_catalog.now() - interval '24 hours';
  if v_sent >= 10 then
    raise exception using
      errcode = 'PT429',
      message = 'church_map_asks_cap: this login sent ten fixes and gaps in the last 24 hours',
      hint = 'The code answers this with the cap''s own words (church_map_asks.CAP).';
  end if;
  return new;
end $$;
revoke all on function public.church_map_asks_cap() from public, anon, authenticated;

drop trigger if exists church_map_asks_cap on public.church_map_asks;
create trigger church_map_asks_cap
  before insert on public.church_map_asks
  for each row
  when (new.kind in ('fix', 'gap'))
  execute function public.church_map_asks_cap();

notify pgrst, 'reload schema';

commit;

-- Check after applying (one trigger, enabled, on its function; the function is security invoker with an
-- empty search_path, and the browser roles can't run it):
--   select t.tgname, t.tgenabled, p.proname, p.prosecdef, p.provolatile, p.proconfig,
--          has_function_privilege('authenticated', p.oid, 'execute') as browser_runs
--     from pg_trigger t join pg_proc p on p.oid = t.tgfoid
--    where t.tgrelid = 'public.church_map_asks'::regclass and not t.tgisinternal;
--     -- church_map_asks_cap | O | church_map_asks_cap | false | v | {search_path=""} | false
--   select pg_get_triggerdef(oid) from pg_trigger where tgname = 'church_map_asks_cap';
--     -- CREATE TRIGGER church_map_asks_cap BEFORE INSERT ON public.church_map_asks FOR EACH ROW
--     --   WHEN ((new.kind = ANY (ARRAY['fix'::text, 'gap'::text]))) EXECUTE FUNCTION church_map_asks_cap()
--
-- Rollback (the code's own checks hold without it):
--   begin; drop trigger if exists church_map_asks_cap on public.church_map_asks;
--   drop function if exists public.church_map_asks_cap(); notify pgrst, 'reload schema'; commit;

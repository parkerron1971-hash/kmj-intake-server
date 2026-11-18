-- ROLLBACK-2026-11-18-church-money-holders.sql
--
-- Undoes APPLY-2026-11-18-church-money-holders.sql: the money rows open
-- again for the owner, an active Admin seat and the outside accountant, and
-- nobody else, whatever church_money_holders says.
--
-- The instant stop needs none of this: with no rows the tick is false for
-- everyone, so
--     delete from public.church_money_holders;
-- puts every reading answer back at once and leaves the functions and
-- policies in place. Run this file only to take the objects away as well.
--
-- What it restores, and where each body is copied from:
--   ministry_finance_guard(b)    APPLY-2026-09-29-ministry-readiness.sql,
--                                word for word
--   ministry_giving_access(b)    APPLY-2026-10-27-church-keys-gift-rows.sql,
--                                word for word; only while church_giving_open
--                                exists (if that file has been rolled back
--                                the function is gone and stays gone)
-- What it removes (all added by the apply file; nothing older is touched):
--   the policies ministry_financial_write_insert / _update / _delete on the
--   nine money tables, church_money_bank on the two bank tables,
--   church_money_event_update / _delete on events and
--   church_money_alert_update / _delete on chief_notifications; the
--   functions ministry_finance_write_guard, ministry_finance_bank_guard,
--   church_money_giving_write, church_money_tick, ministry_finance_walled,
--   church_money_grant, church_money_answer and church_money_ask.
-- What that brings back: the unfiltered write the apply file closed. A
--   Member or Manager seat's `delete from events` or `update
--   chief_notifications set ...` with no WHERE again reaches the money rows
--   it cannot see, as it did before 2026-11-18.
-- What it leaves: the two tables and their rows (who held the tick, and the
-- asks), so applying again brings every tick back. To drop them as well,
-- only when the server no longer reads them:
--     -- drop table if exists public.church_money_holders;
--     -- drop table if exists public.church_money_asks;
--
-- ministry_finance_access, church_giving_open, gift_row_privacy,
-- ministry_financial_privacy, church_giving_bank, the events and
-- notifications SELECT policies and the trigger protect_gift_classification
-- were never changed, and are not changed here. One transaction, safe to run
-- twice.
begin;

set local lock_timeout = '5s';

-- The policies first: they are what calls the new guards.
do $$ declare t text; begin
 foreach t in array array['invoices','journal_entries','ledger_entries','plaid_transactions','plaid_accounts','customer_ledger','business_expenses','bills','chief_bookkeeping_proposals'] loop
  if to_regclass('public.'||t) is not null then
   execute format('drop policy if exists ministry_financial_write_insert on public.%I', t);
   execute format('drop policy if exists ministry_financial_write_update on public.%I', t);
   execute format('drop policy if exists ministry_financial_write_delete on public.%I', t);
  end if;
 end loop;
 foreach t in array array['plaid_transactions','plaid_accounts'] loop
  if to_regclass('public.'||t) is not null then
   execute format('drop policy if exists church_money_bank on public.%I', t);
  end if;
 end loop;
 if to_regclass('public.events') is not null then
  drop policy if exists church_money_event_update on public.events;
  drop policy if exists church_money_event_delete on public.events;
 end if;
 if to_regclass('public.chief_notifications') is not null then
  drop policy if exists church_money_alert_update on public.chief_notifications;
  drop policy if exists church_money_alert_delete on public.chief_notifications;
 end if;
end $$;

-- The two replaced functions, as they were.
create or replace function public.ministry_finance_guard(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and
  (lower(regexp_replace(trim(coalesce(b.type,'')), '[-[:space:]]+', '_', 'g')) not in
    ('ministry','ministries','church','churches','pastor','parachurch','faith','faith_based','religious','religious_org','synagogue','mosque','temple','congregation','nonprofit','non_profit','not_for_profit','nonprofit_org')
   or public.ministry_finance_access(b_id)));
$$;
do $$
begin
  if to_regprocedure('public.church_giving_open(uuid)') is not null then
    execute $f$
create or replace function public.ministry_giving_access(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $body$
 select public.ministry_finance_access(b_id) and public.church_giving_open(b_id);
$body$;
    $f$;
  end if;
end $$;

-- Then what they no longer call.
drop function if exists public.church_money_ask(uuid, uuid, uuid, text, boolean, boolean);
drop function if exists public.church_money_answer(uuid, boolean, uuid);
drop function if exists public.church_money_grant(uuid, uuid, text, boolean, boolean, uuid, uuid);
drop function if exists public.church_money_giving_write(uuid);
drop function if exists public.ministry_finance_write_guard(uuid);
drop function if exists public.ministry_finance_bank_guard(uuid);
drop function if exists public.church_money_tick(uuid, text);
drop function if exists public.ministry_finance_walled(uuid);

commit;

notify pgrst, 'reload schema';

-- Check:
--   select policyname, count(*) from pg_policies
--    where schemaname = 'public'
--      and (policyname like 'ministry_financial_write_%' or policyname like 'church_money_%')
--    group by 1;
--   -- 0 rows
--   select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public'
--      and p.proname in ('ministry_finance_walled', 'church_money_tick', 'ministry_finance_write_guard',
--                        'ministry_finance_bank_guard', 'church_money_giving_write',
--                        'church_money_grant', 'church_money_answer', 'church_money_ask');
--   -- 0
--   select p.proname, p.prosrc ~ 'church_money_tick' as still_reads_the_tick from pg_proc p
--    where p.oid in ('public.ministry_finance_guard(uuid)'::regprocedure, 'public.ministry_giving_access(uuid)'::regprocedure);
--   -- 2 rows, each false

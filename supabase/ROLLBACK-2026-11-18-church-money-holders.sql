-- ROLLBACK-2026-11-18-church-money-holders.sql
--
-- Undoes APPLY-2026-11-18-church-money-holders.sql: the money rows open
-- again for the owner, an active Admin seat and the outside accountant, and
-- nobody else, whatever church_money_holders says.
--
-- The instant stop needs none of this: with no rows the tick is false for
-- everyone, so
--     delete from public.church_money_holders;
-- puts every answer back at once and leaves the functions and policies in
-- place. Run this file only to take the objects away as well.
--
-- What it restores, and where each body is copied from:
--   ministry_finance_access(b)   APPLY-2026-09-29-ministry-readiness.sql,
--                                word for word
--   ministry_giving_access(b)    APPLY-2026-10-27-church-keys-gift-rows.sql,
--                                word for word
-- What it removes (all added by the apply file; nothing older is touched):
--   the policies ministry_financial_write_insert / _update / _delete on the
--   nine money tables and church_money_bank on the two bank tables; the
--   functions ministry_finance_write_guard, ministry_finance_bank_guard,
--   church_money_tick, ministry_finance_base, ministry_finance_walled,
--   church_money_grant and church_money_answer.
-- What it leaves: the two tables and their rows (who held the tick, and the
-- asks), so applying again brings every tick back. To drop them as well,
-- only when the server no longer reads them:
--     -- drop table if exists public.church_money_holders;
--     -- drop table if exists public.church_money_asks;
--
-- ministry_finance_guard, church_giving_open, gift_row_privacy,
-- ministry_financial_privacy, church_giving_bank, the events and
-- notifications policies and the trigger protect_gift_classification were
-- never changed, and are not changed here. One transaction, safe to run
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
end $$;

-- The two replaced functions, as they were.
create or replace function public.ministry_finance_access(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and b.owner_id=auth.uid())
 or exists(select 1 from business_users u where u.business_id=b_id and u.user_id=auth.uid() and u.status='active' and u.role='admin')
 or exists(select 1 from business_collaborators c where c.business_id=b_id and c.user_id=auth.uid() and c.status='active' and c.role='accountant');
$$;
create or replace function public.ministry_giving_access(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select public.ministry_finance_access(b_id) and public.church_giving_open(b_id);
$$;

-- Then what they no longer call.
drop function if exists public.church_money_answer(uuid, boolean, uuid);
drop function if exists public.church_money_grant(uuid, uuid, text, boolean, boolean, uuid, uuid);
drop function if exists public.ministry_finance_write_guard(uuid);
drop function if exists public.ministry_finance_bank_guard(uuid);
drop function if exists public.church_money_tick(uuid, text);
drop function if exists public.ministry_finance_base(uuid);
drop function if exists public.ministry_finance_walled(uuid);

commit;

notify pgrst, 'reload schema';

-- Check:
--   select policyname, count(*) from pg_policies
--    where schemaname = 'public'
--      and policyname in ('ministry_financial_write_insert', 'ministry_financial_write_update',
--                         'ministry_financial_write_delete', 'church_money_bank')
--    group by 1;
--   -- 0 rows
--   select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public'
--      and p.proname in ('ministry_finance_base', 'ministry_finance_walled', 'church_money_tick',
--                        'ministry_finance_write_guard', 'ministry_finance_bank_guard',
--                        'church_money_grant', 'church_money_answer');
--   -- 0
--   select pg_get_functiondef('public.ministry_finance_access(uuid)'::regprocedure) ~ 'church_money_tick' as still_reads_the_tick;
--   -- false

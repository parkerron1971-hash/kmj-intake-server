-- Undoes APPLY-2026-10-27-church-keys-gift-rows.sql: the gift rows, the
-- giving events, the gift alerts and the bank go back to the 2026-09-29
-- rule (owner, admin, the outside accountant), with no keeper in it. The
-- server's doors (church_keys.wall) are untouched. Idempotent.
begin;

drop policy if exists gift_row_privacy on public.invoices;
create policy gift_row_privacy on public.invoices as restrictive for all to authenticated
 using(not is_gift or public.ministry_finance_access(business_id))
 with check(not is_gift or public.ministry_finance_access(business_id));
create or replace function public.protect_gift_classification() returns trigger
language plpgsql set search_path=public as $$ begin
 if current_user='authenticated' and (old.is_gift or new.is_gift)
    and not public.ministry_finance_access(old.business_id) then
  raise exception 'Giving records require finance access';
 end if;
 return new;
end $$;

drop policy if exists ministry_financial_events on public.events;
create policy ministry_financial_events on public.events as restrictive for select to authenticated
 using(case when event_type ~ '^giving' then public.ministry_finance_access(business_id)
  when event_type ~ '^(invoice|payment)' then public.ministry_finance_guard(business_id) else true end);
drop policy if exists ministry_financial_notifications on public.chief_notifications;
create policy ministry_financial_notifications on public.chief_notifications as restrictive for select to authenticated
 using(case when data->>'kind' in ('gift_received','recurring_gift_ended') then public.ministry_finance_access(business_id)
  when data->>'kind'='invoice_paid' then public.ministry_finance_guard(business_id) else true end);

do $$ declare t text; begin
 foreach t in array array['plaid_transactions','plaid_accounts'] loop
  if to_regclass('public.'||t) is not null then
   execute format('drop policy if exists church_giving_bank on public.%I',t);
  end if;
 end loop;
end $$;

drop function if exists public.ministry_giving_access(uuid);
drop function if exists public.church_giving_open(uuid);

commit;

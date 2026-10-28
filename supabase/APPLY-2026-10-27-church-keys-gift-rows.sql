-- Church Areas, step 2, part 3: the Giving keeper in the database. Kevin
-- 2026-10-23: "if Pastor look at money another leader is notified and have
-- to recieve a code from that person to get into money"; his picks
-- 2026-10-26: the lock binds the owner too, a yes opens for an hour.
--
-- The server's doors (church_keys.wall, kmj-intake-server#1621) read with
-- the service role. The app also reads gift rows itself, with the
-- person's own login: the Bills page lists every invoice with its
-- contact, so a gift showed its giver there to an owner or admin the
-- keeper hadn't let in. This puts the same rule on the rows:
--
--   church_giving_open(b)     false only for someone who belongs to the
--                             business (owner, a seat, a collaborator)
--                             while it has an active Giving keeper and
--                             they neither keep it nor hold an open key
--                             (church_keepers / church_area_keys, as
--                             church_keys.opened reads them). No keeper,
--                             no lock. Anyone else gets true: the
--                             business's own policies already refuse
--                             them, and a constant tells them nothing
--   ministry_giving_access(b) ministry_finance_access (owner, admin, the
--                             outside accountant) and church_giving_open
--
-- Behind it: gift rows (invoices.is_gift), the giving events, the gift
-- alerts in the bell, and the bank (plaid_transactions, plaid_accounts).
-- What a gift was worth, when and to which fund stays open to the finance
-- roles through GET /giving/{id}/amounts (the service role, no names), so
-- the church's Home and its giving goal keep their numbers.
--
-- The CHURCH_KEYS switch is the server's; this lock follows the keepers
-- alone. To take it away, remove the church's keepers or run
-- ROLLBACK-2026-10-27-church-keys-gift-rows.sql. Idempotent.
begin;

create or replace function public.church_giving_open(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select not exists(select 1 from church_keepers k where k.business_id=b_id and k.area='giving_money'
          and k.starts_at<=now() and (k.ends_at is null or k.ends_at>now()))
  or not (exists(select 1 from businesses b where b.id=b_id and b.owner_id=auth.uid())
       or exists(select 1 from business_users u where u.business_id=b_id and u.user_id=auth.uid() and u.status='active')
       or exists(select 1 from business_collaborators c where c.business_id=b_id and c.user_id=auth.uid() and c.status='active'))
  or exists(select 1 from church_keepers k where k.business_id=b_id and k.area='giving_money' and k.user_id=auth.uid()
          and k.starts_at<=now() and (k.ends_at is null or k.ends_at>now()))
  or exists(select 1 from church_area_keys g where g.business_id=b_id and g.area='giving_money' and g.user_id=auth.uid()
          and g.status='open' and g.opens_until>now());
$$;
create or replace function public.ministry_giving_access(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select public.ministry_finance_access(b_id) and public.church_giving_open(b_id);
$$;
revoke all on function public.church_giving_open(uuid), public.ministry_giving_access(uuid) from public, anon;
grant execute on function public.church_giving_open(uuid), public.ministry_giving_access(uuid) to authenticated, service_role;

-- Gift rows: as APPLY-2026-09-29-ministry-readiness.sql, plus the keeper.
drop policy if exists gift_row_privacy on public.invoices;
create policy gift_row_privacy on public.invoices as restrictive for all to authenticated
 using(not is_gift or public.ministry_giving_access(business_id))
 with check(not is_gift or public.ministry_giving_access(business_id));
create or replace function public.protect_gift_classification() returns trigger
language plpgsql set search_path=public as $$ begin
 if current_user='authenticated' and (old.is_gift or new.is_gift)
    and not public.ministry_giving_access(old.business_id) then
  raise exception 'Giving records require finance access';
 end if;
 return new;
end $$;

-- The giving events and the gift alerts.
drop policy if exists ministry_financial_events on public.events;
create policy ministry_financial_events on public.events as restrictive for select to authenticated
 using(case when event_type ~ '^giving' then public.ministry_giving_access(business_id)
  when event_type ~ '^(invoice|payment)' then public.ministry_finance_guard(business_id) else true end);
drop policy if exists ministry_financial_notifications on public.chief_notifications;
create policy ministry_financial_notifications on public.chief_notifications as restrictive for select to authenticated
 using(case when data->>'kind' in ('gift_received','recurring_gift_ended') then public.ministry_giving_access(business_id)
  when data->>'kind'='invoice_paid' then public.ministry_finance_guard(business_id) else true end);

-- The bank.
do $$ declare t text; begin
 foreach t in array array['plaid_transactions','plaid_accounts'] loop
  if to_regclass('public.'||t) is not null then
   execute format('drop policy if exists church_giving_bank on public.%I',t);
   execute format('create policy church_giving_bank on public.%I as restrictive for all to authenticated using(public.church_giving_open(business_id)) with check(public.church_giving_open(business_id))',t);
  end if;
 end loop;
end $$;

commit;

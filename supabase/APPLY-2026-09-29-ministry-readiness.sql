-- Ministry readiness repairs. Apply before the corresponding backend/frontend release.
-- Idempotent. No gifts inferred from ordinary service invoices or generic restricted categories.
begin;
alter table public.invoices add column if not exists is_gift boolean not null default false;
alter table public.invoices add column if not exists gift_fund text;
update public.invoices set is_gift=true,
 gift_fund=coalesce(gift_fund, nullif(regexp_replace(coalesce(items->0->>'description',''), '^Gift — ', ''), ''), 'General')
 where invoice_number like 'GIVE-%' and not is_gift;
create index if not exists invoices_giving_period on public.invoices(business_id,paid_at,id) where is_gift and status='paid';

create or replace function public.ministry_finance_access(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and b.owner_id=auth.uid())
 or exists(select 1 from business_users u where u.business_id=b_id and u.user_id=auth.uid() and u.status='active' and u.role='admin')
 or exists(select 1 from business_collaborators c where c.business_id=b_id and c.user_id=auth.uid() and c.status='active' and c.role='accountant');
$$;
create or replace function public.ministry_finance_guard(b_id uuid)
returns boolean language sql stable security definer set search_path=public as $$
 select exists(select 1 from businesses b where b.id=b_id and
  (lower(regexp_replace(trim(coalesce(b.type,'')), '[-[:space:]]+', '_', 'g')) not in
    ('ministry','ministries','church','churches','pastor','parachurch','faith','faith_based','religious','religious_org','synagogue','mosque','temple','congregation','nonprofit','non_profit','not_for_profit','nonprofit_org')
   or public.ministry_finance_access(b_id)));
$$;
revoke all on function public.ministry_finance_access(uuid), public.ministry_finance_guard(uuid) from public;
grant execute on function public.ministry_finance_access(uuid), public.ministry_finance_guard(uuid) to authenticated;
-- Restrictive policies intersect existing permissive owner/team policies: no new grants.
do $$ declare t text; begin
 foreach t in array array['invoices','journal_entries','ledger_entries','plaid_transactions','plaid_accounts','customer_ledger','business_expenses','bills','chief_bookkeeping_proposals'] loop
  if to_regclass('public.'||t) is not null then
   execute format('drop policy if exists ministry_financial_privacy on public.%I',t);
   execute format('create policy ministry_financial_privacy on public.%I as restrictive for all to authenticated using(public.ministry_finance_guard(business_id)) with check(public.ministry_finance_guard(business_id))',t);
  end if;
 end loop;
end $$;
-- Gifts stay private even when a business changes its vertical.
drop policy if exists gift_row_privacy on public.invoices;
create policy gift_row_privacy on public.invoices as restrictive for all to authenticated
 using(not is_gift or public.ministry_finance_access(business_id))
 with check(not is_gift or public.ministry_finance_access(business_id));
-- Prevent ordinary seats from relabeling financial records to evade the gift policy.
create or replace function public.protect_gift_classification() returns trigger
language plpgsql set search_path=public as $$ begin
 if current_user='authenticated' and (old.is_gift or new.is_gift)
    and not public.ministry_finance_access(old.business_id) then
  raise exception 'Giving records require finance access';
 end if;
 return new;
end $$;
drop trigger if exists protect_gift_classification on public.invoices;
create trigger protect_gift_classification before update on public.invoices for each row execute function public.protect_gift_classification();

create table if not exists public.ministry_care_requests(
 id uuid primary key default gen_random_uuid(), business_id uuid not null references businesses(id),
 form_id uuid, submission jsonb not null, status text not null default 'new' check(status in ('new','reviewed','closed')),
 created_at timestamptz not null default now(), legacy_source text unique);
alter table public.ministry_care_requests enable row level security;
revoke all on public.ministry_care_requests from anon,authenticated;
grant all on public.ministry_care_requests to service_role;
create index if not exists ministry_care_business on public.ministry_care_requests(business_id,created_at desc);

-- Preserve identifiable historical private intake copies in locked storage before redacting.
create or replace function public.has_private_care(v jsonb) returns boolean
language plpgsql immutable set search_path=public as $$ declare k text; item jsonb; begin
 if jsonb_typeof(v)='object' then
  if lower(coalesce(v->>'confidential','')) in ('yes','true','1','on') or nullif(v->>'prayer_request','') is not null or nullif(v->>'pastoral_care','') is not null or lower(coalesce(v->>'form_name','')) like '%prayer%' then return true; end if;
  for k,item in select * from jsonb_each(v) loop if public.has_private_care(item) then return true; end if; end loop;
 elsif jsonb_typeof(v)='array' then
  for item in select * from jsonb_array_elements(v) loop if public.has_private_care(item) then return true; end if; end loop;
 end if;
 return false;
end $$;
revoke all on function public.has_private_care(jsonb) from public;
-- Contact metadata is preserved as one private historical record; identity remains operational.
insert into public.ministry_care_requests(business_id,submission,legacy_source)
 select business_id,jsonb_build_object('contact_id',id,'legacy_metadata',metadata),'contact:'||id||':'||md5(coalesce(metadata,'null'::jsonb)::text)
 from public.contacts c where public.has_private_care(metadata)
  or exists(select 1 from public.events e where e.business_id=c.business_id and e.contact_id=c.id and public.has_private_care(e.data))
 on conflict(legacy_source) do nothing;
update public.contacts c set metadata=jsonb_build_object('private_care_archived',true)
 where public.has_private_care(c.metadata)
  or exists(select 1 from public.events e where e.business_id=c.business_id and e.contact_id=c.id and public.has_private_care(e.data));
insert into public.ministry_care_requests(business_id,submission,legacy_source)
 select business_id,jsonb_build_object('contact_id',contact_id,'legacy_event',data),'event:'||id||':'||md5(data::text)
 from public.events where public.has_private_care(data)
 on conflict(legacy_source) do nothing;
update public.events set data=jsonb_build_object('private_care_archived',true)
 where public.has_private_care(data);
-- Intake drafts may quote the request. Archive before removing them from ordinary queues.
insert into public.ministry_care_requests(business_id,submission,legacy_source)
 select q.business_id,jsonb_build_object('legacy_draft',to_jsonb(q)),'draft:'||q.id||':'||md5(to_jsonb(q)::text)
 from public.agent_queue q where q.agent='intake'
  and (coalesce(q.body,'') <> 'Archived to private care. Owner access required.' or q.ai_reasoning is not null) and exists(
  select 1 from public.ministry_care_requests p where p.business_id=q.business_id
  and p.submission->>'contact_id'=q.contact_id::text)
 on conflict(legacy_source) do nothing;
update public.agent_queue q set subject='Private care request',body='Archived to private care. Owner access required.',ai_reasoning=null,status='rejected'
 where q.agent='intake' and exists(select 1 from public.ministry_care_requests p where p.legacy_source='draft:'||q.id||':'||md5(to_jsonb(q)::text));

-- Keep financial notifications/events out of ordinary member activity reads.
drop policy if exists ministry_financial_events on public.events;
create policy ministry_financial_events on public.events as restrictive for select to authenticated
 using(case when event_type ~ '^giving' then public.ministry_finance_access(business_id)
  when event_type ~ '^(invoice|payment)' then public.ministry_finance_guard(business_id) else true end);
drop policy if exists ministry_financial_notifications on public.chief_notifications;
create policy ministry_financial_notifications on public.chief_notifications as restrictive for select to authenticated
 using(case when data->>'kind' in ('gift_received','recurring_gift_ended') then public.ministry_finance_access(business_id)
  when data->>'kind'='invoice_paid' then public.ministry_finance_guard(business_id) else true end);

-- Every roster write advances its concurrency token, even within the same transaction.
create or replace function public.advance_module_revision() returns trigger
language plpgsql set search_path=public as $$ begin
 new.updated_at=greatest(clock_timestamp(),coalesce(old.updated_at,'-infinity'::timestamptz)+interval '1 microsecond');
 return new;
end $$;
drop trigger if exists zz_module_revision on public.module_entries;
create trigger zz_module_revision before update on public.module_entries for each row execute function public.advance_module_revision();
create unique index if not exists invoices_gift_request on public.invoices(business_id,invoice_number) where is_gift;
create table if not exists public.ministry_gift_history(
 id bigint generated always as identity primary key, business_id uuid not null,
 invoice_id uuid not null, changed_at timestamptz not null default now(), actor_id uuid,
 previous jsonb not null, current_record jsonb not null);
alter table public.ministry_gift_history enable row level security;
revoke all on public.ministry_gift_history from anon,authenticated;
grant all on public.ministry_gift_history to service_role;
grant usage,select on sequence public.ministry_gift_history_id_seq to service_role;
create or replace function public.audit_gift_change() returns trigger
language plpgsql security definer set search_path=public as $$ begin
 if old.is_gift or new.is_gift then
  insert into ministry_gift_history(business_id,invoice_id,actor_id,previous,current_record)
  values(old.business_id,old.id,auth.uid(),to_jsonb(old),to_jsonb(new));
 end if;
 return new;
end $$;
drop trigger if exists audit_gift_change on public.invoices;
create trigger audit_gift_change after update on public.invoices for each row execute function public.audit_gift_change();
commit;

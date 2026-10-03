-- Apply before CHIEF_DURABLE_EVENTS=on. No historical events are replayed.
begin;
create table if not exists public.chief_event_deliveries (
  event_id text primary key,
  business_id uuid not null references public.businesses(id) on delete cascade,
  token uuid not null,
  phase text not null check (phase in ('planning','acting','completed','needs_review','resolved')),
  lease_until timestamptz not null,
  attempts integer not null default 1,
  summary text not null default '',
  updated_at timestamptz not null default now()
);
alter table public.chief_event_deliveries enable row level security;
revoke all on public.chief_event_deliveries from public, anon, authenticated;
grant select, insert, update, delete on public.chief_event_deliveries to service_role;
create index if not exists chief_event_delivery_business on public.chief_event_deliveries(business_id,phase);

create or replace function public.chief_event_pending(p_types text[])
returns setof public.events language sql security definer set search_path=public as $$
  select e.* from public.events e left join public.chief_event_deliveries d on d.event_id=e.id::text
  where e.agent_handled_at is null and e.event_type=any(p_types)
    and ((d.event_id is null and e.created_at>=now()-interval '24 hours')
      or (d.phase='planning' and d.lease_until<=now() and d.attempts<3))
  order by e.created_at limit 200
$$;

create or replace function public.chief_event_claim(p_business uuid,p_ids text[],p_token uuid)
returns setof public.chief_event_deliveries language sql security definer set search_path=public as $$
  insert into public.chief_event_deliveries(event_id,business_id,token,phase,lease_until)
  select e.id::text,e.business_id,p_token,'planning',now()+interval '3 minutes'
  from public.events e where e.business_id=p_business and e.id::text=any(p_ids)
    and e.agent_handled_at is null
    and (e.created_at>=now()-interval '24 hours' or exists (
      select 1 from public.chief_event_deliveries d where d.event_id=e.id::text and d.phase='planning'))
  on conflict(event_id) do update set token=excluded.token,phase='planning',
    lease_until=excluded.lease_until,attempts=chief_event_deliveries.attempts+1,updated_at=now()
  where chief_event_deliveries.business_id=p_business and chief_event_deliveries.phase='planning'
    and chief_event_deliveries.lease_until<=now() and chief_event_deliveries.attempts<3
  returning *
$$;

create or replace function public.chief_event_checkpoint(p_business uuid,p_ids text[],p_token uuid,p_phase text,p_summary text default '')
returns boolean language plpgsql security definer set search_path=public as $$
declare n integer;
begin
  if p_phase not in ('planning','acting','completed','needs_review') or cardinality(p_ids)=0 then return false; end if;
  -- Lock the whole batch before changing any row. A stale worker cannot act.
  perform 1 from public.chief_event_deliveries where business_id=p_business and event_id=any(p_ids) for update;
  select count(*) into n from public.chief_event_deliveries where business_id=p_business
    and event_id=any(p_ids) and token=p_token and lease_until>now() and phase in ('planning','acting');
  if n<>cardinality(p_ids) then return false; end if;
  if p_phase='planning' and exists(select 1 from public.chief_event_deliveries where event_id=any(p_ids) and phase='acting') then return false; end if;
  update public.chief_event_deliveries set phase=p_phase,summary=left(p_summary,600),
    lease_until=now()+interval '3 minutes',updated_at=now()
    where business_id=p_business and event_id=any(p_ids) and token=p_token;
  -- Fence the legacy cursor once effects are possible, even after flag rollback.
  if p_phase in ('acting','completed','needs_review') then
    update public.events set agent_handled_at=now() where business_id=p_business and id::text=any(p_ids);
  end if;
  return true;
end $$;

create or replace function public.chief_event_renew(p_business uuid,p_ids text[],p_token uuid)
returns boolean language plpgsql security definer set search_path=public as $$
declare n integer;
begin
  update public.chief_event_deliveries set lease_until=now()+interval '3 minutes',updated_at=now()
    where business_id=p_business and event_id=any(p_ids) and token=p_token
      and lease_until>now() and phase in ('planning','acting');
  get diagnostics n=row_count;
  return n=cardinality(p_ids) and n>0;
end $$;

create or replace function public.chief_event_recover()
returns integer language plpgsql security definer set search_path=public as $$
declare n integer;
begin
  update public.chief_event_deliveries set phase='needs_review',updated_at=now(),
    summary=case when phase='acting' then 'Work was interrupted after actions became possible. Check the records before starting it again.'
      else 'Chief could not finish preparing this work after three attempts. It needs a review.' end
    where lease_until<=now() and (phase='acting' or (phase='planning' and attempts>=3));
  get diagnostics n=row_count;
  return n;
end $$;

create or replace function public.chief_event_resolve(p_business uuid,p_event text,p_updated_at timestamptz)
returns boolean language plpgsql security definer set search_path=public as $$
declare n integer;
begin
  update public.chief_event_deliveries set phase='resolved',updated_at=now(),
    summary='Reviewed by the owner. No actions were replayed.'
    where business_id=p_business and event_id=p_event and phase='needs_review' and updated_at=p_updated_at;
  get diagnostics n=row_count;
  if n=1 then
    update public.events set agent_handled_at=now() where business_id=p_business and id::text=p_event;
  end if;
  return n=1;
end $$;

revoke all on function public.chief_event_pending(text[]) from public,anon,authenticated;
revoke all on function public.chief_event_claim(uuid,text[],uuid) from public,anon,authenticated;
revoke all on function public.chief_event_checkpoint(uuid,text[],uuid,text,text) from public,anon,authenticated;
revoke all on function public.chief_event_renew(uuid,text[],uuid) from public,anon,authenticated;
revoke all on function public.chief_event_recover() from public,anon,authenticated;
revoke all on function public.chief_event_resolve(uuid,text,timestamptz) from public,anon,authenticated;
grant execute on function public.chief_event_pending(text[]),public.chief_event_claim(uuid,text[],uuid),
  public.chief_event_checkpoint(uuid,text[],uuid,text,text),public.chief_event_renew(uuid,text[],uuid),
  public.chief_event_recover() to service_role;
grant execute on function public.chief_event_resolve(uuid,text,timestamptz) to service_role;
notify pgrst, 'reload schema';
commit;

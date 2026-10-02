-- Durable Chief work orders. Apply before enabling CHIEF_BUILDS.
-- Existing jobs retain their concurrency rule. Build jobs queue independently.
begin;
alter table public.chief_jobs add column if not exists build_lease_token uuid;
alter table public.chief_jobs add column if not exists build_lease_until timestamptz;
alter table public.chief_jobs add column if not exists build_revision integer not null default 0;
drop index if exists public.chief_jobs_one_active_per_business_kind;
create unique index chief_jobs_one_active_per_business_kind on public.chief_jobs(business_id,kind)
 where status in ('queued','running') and kind <> 'build';
create unique index if not exists chief_build_order_unique on public.chief_jobs(business_id,(params->>'order_id')) where kind='build';

create or replace function public.chief_build_claim(p_id uuid,p_token uuid)
returns setof public.chief_jobs language plpgsql security definer set search_path=public as $$
declare b uuid;
begin
 select business_id into b from chief_jobs where id=p_id and kind='build';
 if b is null then return; end if;
 perform pg_advisory_xact_lock(hashtextextended(b::text,918));
 -- Serialize builds within a business, including across replicas.
 if exists(select 1 from chief_jobs where business_id=b and kind='build' and id<>p_id
   and status='running' and build_lease_until>now()) then return; end if;
 return query update chief_jobs set status='running',build_lease_token=p_token,
   build_lease_until=now()+interval '150 seconds',started_at=coalesce(started_at,now())
 where id=p_id and kind='build' and status in ('queued','running')
   and (build_lease_until is null or build_lease_until<now()) returning *;
end $$;

create or replace function public.chief_build_save(p_id uuid,p_token uuid,p_result jsonb,p_status text default 'running')
returns setof public.chief_jobs language plpgsql security definer set search_path=public as $$
begin
 if p_status not in ('running','done','failed','cancelled') then raise exception 'Invalid build state'; end if;
 return query update chief_jobs set result=p_result,status=p_status,build_revision=build_revision+1,
  build_lease_until=case when p_status='running' then now()+interval '150 seconds' else null end,
  build_lease_token=case when p_status='running' then p_token else null end,
  finished_at=case when p_status='running' then null else now() end
 where id=p_id and kind='build' and build_lease_token=p_token and build_lease_until>now() returning *;
end $$;

create or replace function public.chief_build_renew(p_id uuid,p_token uuid)
returns boolean language plpgsql security definer set search_path=public as $$
begin
 update chief_jobs set build_lease_until=now()+interval '150 seconds'
 where id=p_id and kind='build' and status='running' and build_lease_token=p_token and build_lease_until>now();
 return found;
end $$;

create or replace function public.chief_build_respond(p_id uuid,p_user uuid,p_revision integer,p_params jsonb,p_result jsonb,p_cancel boolean default false)
returns setof public.chief_jobs language plpgsql security definer set search_path=public as $$
begin
 return query update chief_jobs set params=p_params,result=p_result,
 status=case when p_cancel then 'cancelled' else 'queued' end,
 build_revision=build_revision+1,build_lease_token=null,build_lease_until=null,finished_at=null
 where id=p_id and kind='build' and user_id=p_user and build_revision=p_revision
 and (build_lease_until is null or build_lease_until<now()) returning *;
end $$;

-- An authenticated owner can reserve via the existing image function. A durable
-- worker has no stored user JWT; this service-only wrapper rechecks the owner.
create or replace function public.reserve_chief_build_image(p_record jsonb,p_user uuid)
returns setof public.image_artworks language plpgsql security definer set search_path=public as $$
begin
 if not exists(select 1 from businesses where id=(p_record->>'business_id')::uuid and owner_id=p_user) then raise exception 'Business access denied'; end if;
 perform set_config('request.jwt.claim.sub',p_user::text,true);
 perform set_config('request.jwt.claims',jsonb_build_object('sub',p_user)::text,true);
 return query select * from public.reserve_image_artwork(p_record,20);
end $$;
revoke all on function public.chief_build_claim(uuid,uuid) from public,anon,authenticated;
revoke all on function public.chief_build_save(uuid,uuid,jsonb,text) from public,anon,authenticated;
revoke all on function public.chief_build_renew(uuid,uuid) from public,anon,authenticated;
revoke all on function public.chief_build_respond(uuid,uuid,integer,jsonb,jsonb,boolean) from public,anon,authenticated;
revoke all on function public.reserve_chief_build_image(jsonb,uuid) from public,anon,authenticated;
grant execute on function public.chief_build_claim(uuid,uuid),public.chief_build_save(uuid,uuid,jsonb,text),public.chief_build_renew(uuid,uuid),public.chief_build_respond(uuid,uuid,integer,jsonb,jsonb,boolean),public.reserve_chief_build_image(jsonb,uuid) to service_role;
commit;

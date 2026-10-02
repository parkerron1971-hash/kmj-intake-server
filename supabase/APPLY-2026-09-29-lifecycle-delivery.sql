-- Transactional lifecycle delivery ledger. Apply before deploying the backend.
-- No recipient backfill: password signups explicitly mark business intent;
-- OAuth users enroll only when they open business onboarding.
begin;
create table if not exists public.lifecycle_signup_intents (
 user_id uuid primary key references auth.users(id) on delete cascade,
 started_at timestamptz not null default now()
);
create table if not exists public.lifecycle_email_deliveries (
 delivery_key text primary key,
 payload jsonb not null,
 state text not null default 'pending' check(state in ('pending','sending','sent','review')),
 first_attempt_at timestamptz not null default now(),
 lease_until timestamptz,
 claim_token uuid,
 attempts integer not null default 0,
 sent_at timestamptz,
 provider_id text,
 last_error text
);
alter table public.lifecycle_signup_intents enable row level security;
alter table public.lifecycle_email_deliveries enable row level security;
revoke all on public.lifecycle_signup_intents, public.lifecycle_email_deliveries from public, anon, authenticated;
grant select, insert, update, delete on public.lifecycle_signup_intents, public.lifecycle_email_deliveries to service_role;

create or replace function public.lifecycle_claim(p_key text, p_payload jsonb)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare r public.lifecycle_email_deliveries; token uuid := gen_random_uuid();
begin
 insert into public.lifecycle_email_deliveries(delivery_key,payload) values(p_key,p_payload) on conflict do nothing;
 select * into r from public.lifecycle_email_deliveries where delivery_key=p_key for update;
 if r.state='sent' then return jsonb_build_object('state','sent','provider_id',r.provider_id); end if;
 -- Resend keeps idempotency keys for 24h. Hold uncertain sends for review
 -- before that boundary rather than risk a duplicate after it expires.
 if r.first_attempt_at < now()-interval '23 hours' then
  update public.lifecycle_email_deliveries set state='review' where delivery_key=p_key;
  return jsonb_build_object('state','review');
 end if;
 if r.lease_until > now() then return jsonb_build_object('state','busy'); end if;
 update public.lifecycle_email_deliveries set state='sending',claim_token=token,
  lease_until=now()+interval '10 minutes',attempts=attempts+1 where delivery_key=p_key;
 return jsonb_build_object('state','claimed','token',token,'payload',r.payload);
end $$;
create or replace function public.lifecycle_finish(p_key text,p_token uuid,p_provider_id text)
returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
begin
 update public.lifecycle_email_deliveries set state='sent',sent_at=now(),provider_id=p_provider_id,
  lease_until=null,last_error=null where delivery_key=p_key and claim_token=p_token and state='sending';
 return found;
end $$;
create or replace function public.lifecycle_fail(p_key text,p_token uuid,p_error text)
returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
begin
 update public.lifecycle_email_deliveries set state='pending',lease_until=now()+interval '15 minutes',
 last_error=left(p_error,120) where delivery_key=p_key and claim_token=p_token and state='sending';
 return found;
end $$;

create or replace function public.lifecycle_signup_candidates(p_user_id uuid default null)
returns table(user_id uuid,email text,first_name text,kind text)
language sql stable security definer set search_path = pg_catalog, public as $$
 with candidates as (
 select u.id,u.email,coalesce(u.raw_user_meta_data->>'full_name',u.raw_user_meta_data->>'name','') as full_name,
 coalesce(i.started_at,u.created_at) as started_at
 from auth.users u left join public.lifecycle_signup_intents i on i.user_id=u.id
 where (p_user_id is null or u.id=p_user_id)
 and (i.user_id is not null or u.raw_user_meta_data->>'solutionist_signup_intent'='business')
 and u.email_confirmed_at is not null and u.email is not null
 and u.invited_at is null and coalesce(u.is_anonymous,false)=false
 and u.deleted_at is null and (u.banned_until is null or u.banned_until < now())
 and not exists(select 1 from public.businesses b where b.owner_id=u.id)
 and not exists(select 1 from public.user_profiles p where p.user_id=u.id and p.is_grandfathered)
 and not exists(select 1 from public.business_users m where m.user_id=u.id or lower(m.invited_email)=lower(u.email))
 and not exists(select 1 from public.business_collaborators m where m.user_id=u.id or lower(m.invited_email)=lower(u.email))
 ), due as (
 select id,email,full_name,started_at,
 case when started_at>now()-interval '3 days' then 'signup_day_one' else 'signup_day_three' end as kind
 from candidates where started_at<=now()-interval '1 day' and started_at>now()-interval '7 days'
 )
 select d.id,d.email,split_part(d.full_name,' ',1),d.kind from due d
 where not exists(select 1 from public.lifecycle_email_deliveries e
 where e.delivery_key='signup/'||d.id||'/'||d.kind and e.state in ('sent','review'))
 and not exists(select 1 from public.lifecycle_email_deliveries e
 where e.delivery_key like 'signup/'||d.id||'/%' and e.sent_at>now()-interval '1 day')
 order by d.started_at,d.id limit 500;
$$;
revoke all on function public.lifecycle_claim(text,jsonb), public.lifecycle_finish(text,uuid,text), public.lifecycle_fail(text,uuid,text), public.lifecycle_signup_candidates(uuid) from public, anon, authenticated;
grant execute on function public.lifecycle_claim(text,jsonb), public.lifecycle_finish(text,uuid,text), public.lifecycle_fail(text,uuid,text), public.lifecycle_signup_candidates(uuid) to service_role;
notify pgrst, 'reload schema';
commit;

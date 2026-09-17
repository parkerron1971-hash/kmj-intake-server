-- Control plane: model text and browser database clients cannot authorize work.
begin;
alter table public.dev_tasks add column if not exists authority_record jsonb;
create or replace function public.dev_task_authority_immutable() returns trigger
language plpgsql set search_path=public as $$
begin
  if old.authority_record is not null and
     (new.authority_record,new.lane,new.repo,new.project_path,new.title,new.details)
     is distinct from
     (old.authority_record,old.lane,old.repo,old.project_path,old.title,old.details) then
    raise exception 'Authorized development scope is immutable';
  end if;
  return new;
end $$;
drop trigger if exists dev_task_authority_immutable on public.dev_tasks;
create trigger dev_task_authority_immutable before update on public.dev_tasks
for each row execute function public.dev_task_authority_immutable();
create table if not exists public.platform_chief_permissions (
  owner_id uuid primary key references auth.users(id),
  revision integer not null check (revision > 0),
  settings jsonb not null,
  updated_at timestamptz not null default now()
);
create table if not exists public.platform_chief_authorizations (
  id uuid primary key,
  owner_id uuid not null references auth.users(id),
  request_id uuid not null,
  action jsonb not null,
  action_hash text not null check (action_hash ~ '^[a-f0-9]{64}$'),
  automatic boolean not null default false,
  status text not null default 'pending' check (status in ('pending','executing','done','denied','uncertain')),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '24 hours',
  decided_at timestamptz,
  decided_by uuid references auth.users(id),
  completed_at timestamptz,
  result jsonb
);
create index if not exists platform_chief_authorizations_owner_created
  on public.platform_chief_authorizations(owner_id, created_at desc);
alter table public.platform_chief_permissions enable row level security;
alter table public.platform_chief_authorizations enable row level security;
revoke all on public.platform_chief_permissions, public.platform_chief_authorizations from public, anon, authenticated, service_role;
grant select, insert, update on public.platform_chief_permissions, public.platform_chief_authorizations to service_role;

create or replace function public.platform_chief_immutable_authorization() returns trigger
language plpgsql set search_path = public as $$
begin
  if (new.id,new.owner_id,new.request_id,new.action,new.action_hash,new.automatic,new.created_at,new.expires_at)
     is distinct from
     (old.id,old.owner_id,old.request_id,old.action,old.action_hash,old.automatic,old.created_at,old.expires_at) then
    raise exception 'Authorization scope is immutable';
  end if;
  if not ((old.status = 'pending' and new.status in ('executing','denied') and new.decided_by=old.owner_id)
       or (old.status = 'executing' and new.status in ('done','uncertain') and new.decided_by=old.decided_by)) then
    raise exception 'Invalid authorization transition';
  end if;
  return new;
end $$;
drop trigger if exists platform_chief_immutable_authorization on public.platform_chief_authorizations;
create trigger platform_chief_immutable_authorization before update on public.platform_chief_authorizations
for each row execute function public.platform_chief_immutable_authorization();

create or replace function public.platform_chief_propose(p_id uuid,p_owner uuid,p_request uuid,
 p_action jsonb,p_hash text,p_automatic boolean)
returns setof public.platform_chief_authorizations
language plpgsql security invoker set search_path=public as $$
begin
  insert into public.platform_chief_authorizations(id,owner_id,request_id,action,action_hash,automatic)
  values(p_id,p_owner,p_request,p_action,p_hash,p_automatic) on conflict(id) do nothing;
  return query select * from public.platform_chief_authorizations where id=p_id and owner_id=p_owner;
end $$;

create or replace function public.platform_chief_set_permissions(p_owner uuid,p_revision integer,p_settings jsonb)
returns setof public.platform_chief_permissions
language plpgsql security invoker set search_path=public as $$
begin
  if p_revision=0 then
    return query insert into public.platform_chief_permissions(owner_id,revision,settings)
      values(p_owner,1,p_settings) on conflict(owner_id) do nothing returning *;
  else
    return query update public.platform_chief_permissions set settings=p_settings,revision=revision+1,updated_at=now()
      where owner_id=p_owner and revision=p_revision returning *;
  end if;
end $$;
revoke all on function public.platform_chief_propose(uuid,uuid,uuid,jsonb,text,boolean) from public,anon,authenticated;
revoke all on function public.platform_chief_set_permissions(uuid,integer,jsonb) from public,anon,authenticated;
grant execute on function public.platform_chief_propose(uuid,uuid,uuid,jsonb,text,boolean) to service_role;
grant execute on function public.platform_chief_set_permissions(uuid,integer,jsonb) to service_role;
notify pgrst, 'reload schema';
create or replace function public.platform_chief_today_spend() returns numeric
language sql stable security invoker set search_path=public as $$
  select coalesce(sum(cost_cents),0) from public.api_usage
  where created_at >= date_trunc('day',now() at time zone 'UTC') at time zone 'UTC';
$$;
revoke all on function public.platform_chief_today_spend() from public,anon,authenticated;
grant execute on function public.platform_chief_today_spend() to service_role;
commit;

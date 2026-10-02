-- Apply after marketing-campaigns and the September 24 Dev Desk agents migration.
-- Private, owner-requested conversations on paired subscription-authenticated CLIs.
begin;
create table if not exists public.platform_chief_work (
 id uuid primary key references public.dev_tasks(id),
 owner_id uuid not null,
 request_hash text not null,
 campaign_id uuid references public.platform_marketing_campaigns(id),
 campaign_revision integer,
 brief_hash text,
 item_id uuid,
 purpose text not null check(purpose in ('conversation','strategy','production')),
 device_id uuid references public.dev_bridge_devices(id),
 result jsonb,
 result_version integer not null default 0,
 created_at timestamptz not null default now()
);
alter table public.platform_chief_work enable row level security;
revoke all on public.platform_chief_work from public,anon,authenticated;
grant select,insert,update on public.platform_chief_work to service_role;
create index if not exists chief_work_owner on public.platform_chief_work(owner_id,created_at desc);
create index if not exists chief_work_campaign on public.platform_chief_work(campaign_id,created_at desc);

create or replace function public.chief_work_create(work jsonb, task jsonb) returns uuid
language plpgsql set search_path=pg_catalog,public as $$
declare old public.platform_chief_work; key uuid := (work->>'id')::uuid;
begin
 perform pg_advisory_xact_lock(hashtextextended(key::text,92626));
 select * into old from public.platform_chief_work where id=key;
 if found then
   if old.owner_id<>(work->>'owner_id')::uuid or old.request_hash<>work->>'request_hash' then
     raise exception 'Request changed';
   end if;
   return key;
 end if;
 if task->>'agent' not in ('claude','codex') then raise exception 'Invalid agent'; end if;
 insert into public.dev_tasks(id,lane,status,title,details,repo,agent,project_path,report_key,authority_record,notes)
 values(key,'local','queued',task->>'title',task->>'details',task->>'repo',task->>'agent',
   task->>'project_path',task->>'report_key',task->'authority_record',coalesce(task->'notes','[]'));
 insert into public.platform_chief_work(id,owner_id,request_hash,campaign_id,campaign_revision,brief_hash,item_id,purpose)
 values(key,(work->>'owner_id')::uuid,work->>'request_hash',(work->>'campaign_id')::uuid,
   (work->>'campaign_revision')::integer,work->>'brief_hash',(work->>'item_id')::uuid,work->>'purpose');
 return key;
end $$;

create or replace function public.chief_work_claim(task_id uuid, device uuid) returns boolean
language plpgsql set search_path=pg_catalog,public as $$
declare t public.dev_tasks; w public.platform_chief_work; d public.dev_bridge_devices;
begin
 select * into w from public.platform_chief_work where id=task_id for update;
 if not found then return false; end if;
 select * into d from public.dev_bridge_devices where id=device and not revoked;
 if not found or not ('workbench-v1'=any(coalesce(d.agents,'{}'))) then return false; end if;
 select * into t from public.dev_tasks where id=task_id for update;
 if t.status<>'queued' or not(t.agent=any(coalesce(d.agents,'{}'))) then return false; end if;
 update public.platform_chief_work set device_id=device where id=task_id;
 update public.dev_tasks set status='picked_up',picked_up_at=now(),updated_at=now() where id=task_id;
 return true;
end $$;

-- Atomic append and reply de-duplication keep polling/reporting from losing a message.
create or replace function public.chief_work_note(task_id uuid, note jsonb, reopen boolean default false) returns boolean
language plpgsql set search_path=pg_catalog,public as $$
declare t public.dev_tasks;
begin
 select * into t from public.dev_tasks where id=task_id for update;
 if not found or not exists(select 1 from public.platform_chief_work where id=task_id) then
   raise exception 'Unknown work';
 end if;
 if note->>'id' is not null and exists(select 1 from jsonb_array_elements(t.notes) n where n->>'id'=note->>'id') then return false; end if;
 if jsonb_array_length(t.notes)>=200 then raise exception 'Conversation full; start a new conversation'; end if;
 update public.dev_tasks set notes=notes||jsonb_build_array(note),updated_at=now(),
   report_key=case when reopen and status in ('done','failed','cancelled') then gen_random_uuid()::text||gen_random_uuid()::text else report_key end,
   status=case when reopen and status in ('done','failed','cancelled') then 'queued' else status end,
   finished_at=case when reopen then null else finished_at end where id=task_id;
 return true;
end $$;

create or replace function public.chief_work_ack(task_id uuid, stamps jsonb) returns void
language plpgsql set search_path=pg_catalog,public as $$
begin
 perform 1 from public.dev_tasks where id=task_id for update;
 update public.dev_tasks set notes=(select coalesce(jsonb_agg(case
   when n->>'from'='kevin' and stamps ? (n->>'at') then n||jsonb_build_object('delivered_at',now()) else n end order by ord),'[]')
   from jsonb_array_elements(notes) with ordinality e(n,ord)) where id=task_id;
end $$;

revoke all on function public.chief_work_create(jsonb,jsonb),public.chief_work_claim(uuid,uuid),
 public.chief_work_note(uuid,jsonb,boolean),public.chief_work_ack(uuid,jsonb) from public,anon,authenticated;
grant execute on function public.chief_work_create(jsonb,jsonb),public.chief_work_claim(uuid,uuid),
 public.chief_work_note(uuid,jsonb,boolean),public.chief_work_ack(uuid,jsonb) to service_role;
notify pgrst,'reload schema';
commit;

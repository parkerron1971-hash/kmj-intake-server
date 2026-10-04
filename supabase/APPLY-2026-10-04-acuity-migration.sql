-- Reviewed Acuity imports: one provider, no sends, no charges, one transaction.
begin;

create table if not exists public.acuity_migration_batches (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  owner_id uuid not null,
  plan jsonb not null,
  state text not null default 'prepared' check(state in ('prepared','imported')),
  receipt jsonb,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '24 hours',
  imported_at timestamptz
);
create index if not exists acuity_migration_business_idx on public.acuity_migration_batches(business_id,created_at desc);
create table if not exists public.acuity_migration_records (
  business_id uuid not null references public.businesses(id) on delete cascade,
  source_id text not null,
  entry_id uuid references public.module_entries(id) on delete set null,
  source_hash text not null,
  batch_id uuid not null references public.acuity_migration_batches(id) on delete cascade,
  primary key(business_id,source_id)
);
alter table public.acuity_migration_batches enable row level security;
alter table public.acuity_migration_records enable row level security;
revoke all on public.acuity_migration_batches,public.acuity_migration_records from public,anon,authenticated;
grant all on public.acuity_migration_batches,public.acuity_migration_records to service_role;

-- Normal bookings and imports share this lock. Businesses without imported
-- appointments keep their existing policy; migrated calendars reject races.
create or replace function public.acuity_booking_guard() returns trigger
language plpgsql security definer set search_path=public as $$
declare s timestamptz; mins integer; cap integer; occupied integer;
begin
  if new.status<>'active' or not exists(select 1 from custom_modules where id=new.module_id and business_id=new.business_id and archetype='booking_calendar') then return new; end if;
  perform pg_advisory_xact_lock(hashtextextended('acuity-calendar:'||new.business_id::text,0));
  if not exists(select 1 from acuity_migration_batches where business_id=new.business_id and state='imported'
    and jsonb_array_length(plan->'appointments')>0) then return new; end if;
  s:=coalesce((new.data->>'appointment_at')::timestamptz,new.appointment_at);
  mins:=coalesce((new.data->>'duration_min_at_booking')::integer,new.duration_min_at_booking,60);
  if s is null or mins not between 1 and 1440 then raise exception 'A migrated calendar needs a valid appointment time and duration'; end if;
  new.appointment_at:=s; new.duration_min_at_booking:=mins;
  if tg_op='UPDATE' and old.status=new.status
    and coalesce((old.data->>'appointment_at')::timestamptz,old.appointment_at)=s
    and coalesce((old.data->>'duration_min_at_booking')::integer,old.duration_min_at_booking,60)=mins then return new; end if;
  if s+make_interval(mins=>mins)<=now() then return new; end if;
  select greatest(coalesce((settings#>>'{availability,concurrent_capacity}')::integer,1),1) into cap from businesses where id=new.business_id;
  select count(*) into occupied from module_entries e join custom_modules m on m.id=e.module_id
    where e.business_id=new.business_id and m.archetype='booking_calendar' and e.status='active' and e.id<>new.id
    and coalesce(e.appointment_at,(e.data->>'appointment_at')::timestamptz)<s+make_interval(mins=>mins)
    and coalesce(e.appointment_at,(e.data->>'appointment_at')::timestamptz)+make_interval(mins=>coalesce(e.duration_min_at_booking,(e.data->>'duration_min_at_booking')::integer,60))>s;
  if occupied>=cap then raise exception 'This appointment overlaps an existing booking'; end if;
  return new;
end $$;
drop trigger if exists acuity_booking_guard on public.module_entries;
create trigger acuity_booking_guard before insert or update of data,appointment_at,duration_min_at_booking,status on public.module_entries
for each row execute function public.acuity_booking_guard();
revoke all on function public.acuity_booking_guard() from public,anon,authenticated;

create or replace function public.acuity_migration_commit(p_business uuid,p_owner uuid,p_batch uuid)
returns jsonb language plpgsql security definer set search_path=public as $$
declare b acuity_migration_batches%rowtype; p jsonb; a jsonb; r acuity_migration_records%rowtype;
  cid uuid; eid uuid; mid uuid; oid uuid; n integer; created_contacts integer:=0; existing_contacts integer:=0;
  created_appointments integer:=0; existing_appointments integer:=0; contact_map jsonb:='{}';
  d jsonb; mod custom_modules%rowtype; result jsonb; money_ccy text; s timestamptz; mins integer;
begin
  if not exists(select 1 from businesses where id=p_business and owner_id=p_owner) then raise exception 'Not authorized'; end if;
  perform pg_advisory_xact_lock(hashtextextended('acuity-calendar:'||p_business::text,0));
  select * into b from acuity_migration_batches where id=p_batch and business_id=p_business and owner_id=p_owner for update;
  if not found then raise exception 'Import review not found'; end if;
  if b.state='imported' then return b.receipt; end if;
  if b.expires_at<now() then raise exception 'Import review expired; review the files again'; end if;
  if b.plan->>'ready'<>'true' or jsonb_array_length(b.plan->'issues')<>0 then raise exception 'Resolve every import issue first'; end if;
  if jsonb_array_length(b.plan->'clients')>1000 or jsonb_array_length(b.plan->'appointments')>500 then raise exception 'Import is too large'; end if;
  mid:=nullif(b.plan->>'module_id','')::uuid;
  if jsonb_array_length(b.plan->'appointments')>0 then
    select * into mod from custom_modules where id=mid and business_id=p_business and archetype='booking_calendar' and is_active=true;
    if not found then raise exception 'Booking calendar changed; review the import again'; end if;
    if (select coalesce((settings#>>'{availability,concurrent_capacity}')::integer,1) from businesses where id=p_business)<>1 then
      raise exception 'This import supports a single provider calendar';
    end if;
  end if;
  -- The flag participates in the same transaction as the new rows and guard.
  update acuity_migration_batches set state='imported' where id=p_batch;
  for p in select value from jsonb_array_elements(b.plan->'clients') loop
    select count(*),(array_agg(id order by created_at))[1] into n,cid from contacts where business_id=p_business and lower(trim(email))=p->>'email';
    if n>1 then raise exception 'Multiple clients share an email; review the import again'; end if;
    if n=0 then
      insert into contacts(business_id,name,email,phone,status,source,metadata)
      values(p_business,p->>'name',p->>'email',nullif(p->>'phone',''),'active','acuity_import',
        jsonb_build_object('acuity_import',p->'source','migration_batch',p_batch,'email_opt_out',true)) returning id into cid;
      created_contacts:=created_contacts+1;
    else existing_contacts:=existing_contacts+1;
    end if;
    contact_map:=contact_map||jsonb_build_object(p->>'email',cid);
  end loop;
  for a in select value from jsonb_array_elements(b.plan->'appointments') loop
    select * into r from acuity_migration_records where business_id=p_business and source_id=a->>'source_id';
    if found then
      if r.entry_id is null then raise exception 'An imported appointment was deleted; review it before importing again'; end if;
      if r.source_hash<>a->>'source_hash' then raise exception 'An imported Acuity appointment changed; review it in the calendar'; end if;
      existing_appointments:=existing_appointments+1;
      continue;
    end if;
    oid:=(a->>'offering_id')::uuid;
    select currency into money_ccy from offerings where id=oid and business_id=p_business and is_active=true;
    if not found then raise exception 'A mapped service changed; review the import again'; end if;
    cid:=(contact_map->>(a->>'email'))::uuid;
    if cid is null then raise exception 'Client mapping is missing'; end if;
    s:=(a->>'start')::timestamptz; mins:=(a->>'duration')::integer;
    -- Independently entered sessions must also be considered. Booking mirrors
    -- are already checked by the module-entry trigger below.
    if s+make_interval(mins=>mins)>now() and exists(select 1 from sessions where business_id=p_business and status='scheduled'
      and scheduled_for<s+make_interval(mins=>mins) and scheduled_for+make_interval(mins=>duration_minutes)>s) then
      raise exception 'An appointment overlaps the current calendar; review the import again';
    end if;
    d:=jsonb_build_object('contact_id',cid,'customer_name',a->>'name','customer_email',a->>'email',
      'offering_id',oid,'offering_name',a->>'service','service_name_at_booking',a->>'service',
      'appointment_at',a->>'start','duration_min_at_booking',mins,'currency',money_ccy,
      'price_at_booking',(a->>'price')::numeric,'booked_by','acuity_import',
      'acuity_source_id',a->>'source_id','acuity_source',a->'source',
      'acuity_payment_record',jsonb_build_object('paid',a->'paid','paid_online',a->'paid_online'),
      'migration_batch',p_batch,'migration_reminders_paused',true);
    d:=d||jsonb_build_object(coalesce(mod.archetype_params->>'primary_date_field','appointment_at'),a->>'start');
    for p in select value from jsonb_array_elements(coalesce(mod.schema->'fields','[]')) loop
      if p->>'type'='offering_ref' then d:=d||jsonb_build_object(p->>'name',oid); end if;
    end loop;
    if mod.archetype_params->>'duration_minutes_field' is not null then
      d:=d||jsonb_build_object(mod.archetype_params->>'duration_minutes_field',mins);
    end if;
    insert into module_entries(business_id,module_id,data,status,created_by,appointment_at,duration_min_at_booking)
    values(p_business,mid,d,'active','acuity_import',s,mins) returning id into eid;
    insert into sessions(business_id,contact_id,title,session_type,status,scheduled_for,duration_minutes,notes,metadata)
    values(p_business,cid,a->>'service','other','scheduled',
      s,mins,'Imported from Acuity. [booking:'||eid::text||']',jsonb_build_object('migration_batch',p_batch,'migration_reminders_paused',true));
    insert into business_customers(business_id,contact_id,email,name)
    values(p_business,cid,a->>'email',a->>'name') on conflict do nothing;
    insert into acuity_migration_records(business_id,source_id,entry_id,source_hash,batch_id)
    values(p_business,a->>'source_id',eid,a->>'source_hash',p_batch);
    created_appointments:=created_appointments+1;
  end loop;
  result:=jsonb_build_object('batch_id',p_batch,'clients_imported',created_contacts,'clients_existing',existing_contacts,
    'appointments_imported',created_appointments,'appointments_existing',existing_appointments,
    'reminders','paused','messages_sent',0,'charges_created',0,'imported_at',now(),
    'not_transferred',b.plan->'not_transferred','next_steps',b.plan->'next_steps');
  update acuity_migration_batches set receipt=result,imported_at=now() where id=p_batch;
  return result;
end $$;
revoke all on function public.acuity_migration_commit(uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.acuity_migration_commit(uuid,uuid,uuid) to service_role;

create or replace function public.acuity_migration_reminders(p_business uuid,p_owner uuid,p_batch uuid,p_enabled boolean)
returns jsonb language plpgsql security definer set search_path=public as $$
declare result jsonb;
begin
  if not exists(select 1 from businesses where id=p_business and owner_id=p_owner) then raise exception 'Not authorized'; end if;
  select receipt into result from acuity_migration_batches where id=p_batch and business_id=p_business and state='imported' for update;
  if not found then raise exception 'Completed import not found'; end if;
  update sessions set metadata=coalesce(metadata,'{}')||jsonb_build_object('migration_reminders_paused',not p_enabled)
    where business_id=p_business and metadata->>'migration_batch'=p_batch::text;
  update module_entries set data=data||jsonb_build_object('migration_reminders_paused',not p_enabled)
    where business_id=p_business and data->>'migration_batch'=p_batch::text;
  result:=result||jsonb_build_object('reminders',case when p_enabled then 'enabled' else 'paused' end,'reminders_changed_at',now());
  update acuity_migration_batches set receipt=result where id=p_batch;
  return result;
end $$;
revoke all on function public.acuity_migration_reminders(uuid,uuid,uuid,boolean) from public,anon,authenticated;
grant execute on function public.acuity_migration_reminders(uuid,uuid,uuid,boolean) to service_role;

notify pgrst,'reload schema';
commit;

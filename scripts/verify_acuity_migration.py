"""Rehearse the migration and fixture import inside a rolled-back transaction.

Requires the existing management credential. Never commits, sends, or charges.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from verify_backup import live_query

ROOT = Path(__file__).resolve().parent.parent
ddl = (ROOT / 'supabase/APPLY-2026-10-04-acuity-migration.sql').read_text(encoding='utf-8')
ddl = ddl.replace('begin;', '', 1).rsplit('commit;', 1)[0]
test = r"""
do $test$
declare b uuid; owner uuid; module uuid; offering uuid; batch uuid; second_batch uuid;
  plan jsonb; receipt jsonb; again jsonb; c integer; appt uuid; original_count integer;
begin
  select id,owner_id into strict b,owner from businesses where name='Vertical Test Coach';
  insert into custom_modules(business_id,name,slug,schema,archetype)
    values(b,'Migration rollback calendar','acuity-rollback-calendar','{"fields":[]}','booking_calendar') returning id into module;
  insert into offerings(business_id,name,slug,category,duration_min)
    values(b,'Migration rollback service','acuity-rollback-service','service',60) returning id into offering;
  update businesses set settings=jsonb_set(coalesce(settings,'{}'),'{availability}',
    coalesce(settings->'availability','{}')||'{"concurrent_capacity":1}'::jsonb) where id=b;
  plan:=jsonb_build_object('ready',true,'issues','[]'::jsonb,'module_id',module,
    'clients',jsonb_build_array(jsonb_build_object('name','Migration rollback fixture','email','acuity-rollback@example.invalid','phone','', 'source','{}'::jsonb)),
    'appointments',jsonb_build_array(jsonb_build_object('source_id','987654321009999','source_hash','fixture-v1',
      'email','acuity-rollback@example.invalid','name','Migration rollback fixture','offering_id',offering,
      'service','Migration verification','start','2098-01-04T14:00:00Z','duration',60,'price','75.00',
      'paid',true,'paid_online','25.00','source','{}'::jsonb)),
    'not_transferred','[]'::jsonb,'next_steps','[]'::jsonb);
  insert into acuity_migration_batches(business_id,owner_id,plan) values(b,owner,plan) returning id into batch;
  begin
    perform acuity_migration_commit(b,gen_random_uuid(),batch);
    raise exception 'foreign owner was allowed' using errcode='XX999';
  exception when others then if sqlstate='XX999' then raise; end if; end;
  receipt:=acuity_migration_commit(b,owner,batch);
  if receipt->>'appointments_imported'<>'1' or receipt->>'clients_imported'<>'1' then raise exception 'wrong receipt: %',receipt; end if;
  again:=acuity_migration_commit(b,owner,batch);
  if again<>receipt then raise exception 'retry receipt changed'; end if;
  select entry_id into strict appt from acuity_migration_records where business_id=b and source_id='987654321009999';
  select count(*) into c from sessions where business_id=b and metadata->>'migration_batch'=batch::text
    and session_type='other' and metadata->>'migration_reminders_paused'='true';
  if c<>1 then raise exception 'mirror/reminder pause missing'; end if;
  begin
    perform acuity_migration_reminders(b,gen_random_uuid(),batch,true);
    raise exception 'foreign owner enabled reminders' using errcode='XX999';
  exception when others then if sqlstate='XX999' then raise; end if; end;
  again:=acuity_migration_reminders(b,owner,batch,true);
  if again->>'reminders'<>'enabled' or exists(select 1 from sessions where business_id=b
    and metadata->>'migration_batch'=batch::text and metadata->>'migration_reminders_paused'<>'false') then
    raise exception 'reminders did not enable';
  end if;
  again:=acuity_migration_reminders(b,owner,batch,false);
  if again->>'reminders'<>'paused' or (select data->>'migration_reminders_paused' from module_entries where id=appt)<>'true' then
    raise exception 'reminders did not pause';
  end if;
  if (select data->'acuity_payment_record'->>'paid' from module_entries where id=appt)<>'true' then raise exception 'paid record lost'; end if;
  if (select paid_at from module_entries where id=appt) is not null then raise exception 'import fabricated a payment'; end if;
  insert into acuity_migration_batches(business_id,owner_id,plan) values(b,owner,plan) returning id into second_batch;
  again:=acuity_migration_commit(b,owner,second_batch);
  if again->>'appointments_existing'<>'1' or again->>'appointments_imported'<>'0' then raise exception 're-export created a duplicate'; end if;
  -- A normal widget insert after migration cannot race into the imported slot.
  begin
    insert into module_entries(business_id,module_id,data,status,created_by)
      values(b,module,jsonb_build_object('appointment_at','2098-01-04T14:30:00Z','duration_min_at_booking',60),'active','booking_widget');
    raise exception 'overlapping normal booking was allowed' using errcode='XX999';
  exception when others then if sqlstate='XX999' then raise; end if; end;
  -- A changed source is never silently overwritten, and partial writes roll back.
  plan:=jsonb_set(plan,'{appointments,0,source_hash}','"changed"');
  plan:=jsonb_set(plan,'{clients,0,email}','"acuity-rollback-second@example.invalid"');
  insert into acuity_migration_batches(business_id,owner_id,plan) values(b,owner,plan) returning id into second_batch;
  select count(*) into original_count from contacts where business_id=b;
  begin
    perform acuity_migration_commit(b,owner,second_batch);
    raise exception 'changed source was allowed' using errcode='XX999';
  exception when others then if sqlstate='XX999' then raise; end if; end;
  select count(*) into c from contacts where business_id=b;
  if c<>original_count then raise exception 'failed import leaked a partial contact'; end if;
  if has_table_privilege('authenticated','acuity_migration_batches','SELECT')
    or has_table_privilege('anon','acuity_migration_records','SELECT')
    or has_function_privilege('authenticated','acuity_migration_commit(uuid,uuid,uuid)','EXECUTE') then raise exception 'browser database access allowed'; end if;
end $test$;
"""
live_query("begin; set local lock_timeout='5s'; set local statement_timeout='25s';\n" + ddl + test + '\nrollback;')
remaining = live_query("select count(*) as n from contacts where email in ('acuity-rollback@example.invalid','acuity-rollback-second@example.invalid')")[0]['n']
assert remaining == 0
print(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),'mode':'transaction rolled back',
    'checks':['schema compatibility','owner isolation','atomic import','durable retry receipt','source deduplication',
              'changed source rejection','calendar mirror','reminders paused','owner-only reminder cutover','no fabricated payment','overlap guard',
              'partial failure rollback','browser grants denied'], 'fixture_records_remaining':remaining},indent=2))

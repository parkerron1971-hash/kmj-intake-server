// Disposable SQL verification; never connects to Supabase.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db = new PGlite();
await db.exec([
'create role anon; create role authenticated; create role service_role bypassrls;',
'create schema storage;',
'create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);',
'create table storage.objects(id uuid primary key default gen_random_uuid(),bucket_id text);',
'alter table storage.objects enable row level security;',
'grant usage on schema public,storage to anon,authenticated,service_role;',
'grant all on storage.objects to anon,authenticated,service_role;',
'create policy broad_old_policy on storage.objects for all to anon,authenticated using(true) with check(true);',
'create table dev_bridge_devices(id uuid primary key,revoked boolean default false);',
'grant all on dev_bridge_devices to service_role;'
].join('\n'));
const sql = readFileSync('supabase/APPLY-2026-10-15-dev-desk-relay.sql','utf8');
await db.exec(sql); await db.exec(sql);
const id = n => '00000000-0000-4000-8000-'+String(n).padStart(12,'0');
const key = n => 's-'+id(n);
const call = async (name,args) => (await db.query('select '+name+'('+args.map((_,i)=>'$'+(i+1)).join(',')+') as result',args)).rows[0].result;
const session = (n,state='working') => ({session_key:key(n),kind:'claude',owner:'kai',state});
await db.query('insert into dev_bridge_devices(id) values($1),($2)',[id(1),id(2)]);
await db.exec('set role service_role');
await call('dev_fleet_sync',[id(1),true,[session(1),session(2)]]);
await call('dev_fleet_sync',[id(2),true,[session(1)]]);
await call('dev_fleet_sync',[id(1),false,[session(2,'needs-you')]]);
assert.equal((await db.query("select count(*) as n from dev_fleet_sessions where state='ended'")).rows[0].n,0);
await call('dev_fleet_sync',[id(1),true,[session(2)]]);
assert.equal((await db.query("select count(*) as n from dev_fleet_sessions where state='ended'")).rows[0].n,1);
assert.equal((await db.query('select state from dev_fleet_sessions where device_id=$1',[id(2)])).rows[0].state,'working');
assert.equal((await call('dev_fleet_sync',[id(1),true,Array.from({length:61},(_,i)=>session(i+10))])).error,413);
await call('dev_fleet_sync',[id(1),true,Array.from({length:60},(_,i)=>session(i+10))]);
assert.equal((await call('dev_fleet_sync',[id(1),false,[session(80)]])).error,413);
const screen = rev => call('dev_fleet_screen',[id(2),key(1),rev,'screen','working','2026-10-15T16:00:00Z']);
assert.deepEqual(await screen(3),{ok:true});
assert.deepEqual(await screen(2),{ok:true,stale:true});
assert.equal((await screen(4)).error,429);
await db.exec("update dev_fleet_screens set received_at=now()-interval '2 seconds'");
assert.deepEqual(await screen(4),{ok:true});
assert.equal((await call('dev_fleet_screen',[id(2),key(2),1,'bad',null,null])).error,404);
assert.equal((await db.query('select screen_rev from dev_fleet_sessions where device_id=$1',[id(2)])).rows[0].screen_rev,4);
await db.exec("update dev_fleet_screens set received_at=now()-interval '2 seconds'");
assert.equal((await call('dev_fleet_screen',[id(2),key(1),5,'x'.repeat(16001),null,null])).error,413);
let serial=100;
const alert = (source,keyValue,device=id(1),watch=null) => ({id:id(serial++),source,key:keyValue,device_id:device,watch_id:watch,
  level:'warn',title:'Alert',body:'Body',kind:'event',nav:'studio:platform-dev-desk:alerts'});
const first = alert('kai','abc');
assert.equal((await call('dev_alert_claim',[first])).deduped,false);
assert.equal((await call('dev_alert_claim',[{...first,id:id(serial++)}])).deduped,true);
assert.equal((await db.query('select count from dev_alerts where id=$1',[first.id])).rows[0].count,2);
await db.exec("update dev_alert_dedupe set seen_at=now()-interval '31 minutes'");
assert.equal((await call('dev_alert_claim',[{...first,id:id(serial++)}])).deduped,false);
for (const transition of ['down','up','down']) {
  assert.equal((await call('dev_alert_claim',[alert('sites',transition)])).deduped,false);
  assert.equal((await call('dev_alert_claim',[alert('sites',transition)])).deduped,true);
}
const ci=alert('ci','run-1-failed');
await call('dev_alert_claim',[ci]);
await db.exec("update dev_alert_dedupe set seen_at=now()-interval '40 days'");
await db.query('delete from dev_alerts where id=$1',[ci.id]);
assert.equal((await call('dev_alert_claim',[{...ci,id:id(serial++)}])).deduped,true);
assert.equal((await call('dev_alert_claim',[alert('kai','abc',id(2))])).deduped,false);
await db.query('update dev_bridge_devices set revoked=true where id=$1',[id(2)]);
assert.equal((await call('dev_fleet_sync',[id(2),true,[]])).error,401);
assert.equal((await screen(9)).error,401);
await assert.rejects(()=>db.query("insert into dev_cards(device_id,kind) values($1,'link')",[id(2)]),/revoked/);
await db.query('delete from dev_fleet_sessions where device_id=$1',[id(2)]);
assert.equal((await db.query('select count(*) as n from dev_fleet_screens')).rows[0].n,0);
await db.exec('reset role');
for(const role of ['anon','authenticated']) {
  await db.exec('set role '+role);
  for(const table of ['dev_fleet_sessions','dev_fleet_screens','dev_cards','dev_alerts','dev_alert_dedupe','dev_alert_settings']) {
    await assert.rejects(()=>db.query('select * from '+table),/permission denied/);
  }
  await assert.rejects(()=>call('dev_fleet_sync',[id(1),true,[]]),/permission denied/);
  await assert.rejects(()=>call('dev_alert_claim',[first]),/permission denied/);
  await assert.rejects(()=>db.query("insert into storage.objects(bucket_id) values('dev-desk')"),/row-level security/);
  await db.query("insert into storage.objects(bucket_id) values('unrelated')");
  await db.exec('reset role');
}
assert.equal((await db.query("select public from storage.buckets where id='dev-desk'")).rows[0].public,false);
assert.equal((await db.query("select * from pg_policies where tablename like 'dev_%'")).rows.length,0);
await db.close();
console.log('Dev relay SQL passed: idempotence, isolation, snapshot caps, stale screens, cadence, revocation, dedupe, retention tombstones, RLS and storage privacy.');

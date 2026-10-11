import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(pathToFileURL(process.env.PGLITE_MODULE).href);
const db = new PGlite();
const b='11111111-1111-4111-8111-111111111111',u='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',other='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
await db.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS; CREATE TABLE businesses(id uuid PRIMARY KEY, owner_id uuid NOT NULL);');
await db.query('INSERT INTO businesses VALUES($1,$2)',[b,u]);
for(const name of ['2026-10-08-square-connections','2026-10-09-square-locations','2026-10-11-square-booking-sync']) {
 const sql=await readFile(new URL('../supabase/APPLY-'+name+'.sql',import.meta.url),'utf8');
 await db.exec(sql); await db.exec(sql);
}
await db.query("INSERT INTO square_connections(business_id,environment,status,merchant_id,selected_location_ids) VALUES($1,'sandbox','connected','merchant',ARRAY['L1'])",[b]);
const connection=async()=> (await db.query('SELECT * FROM square_connections')).rows[0];
const state=async()=> (await db.query('SELECT * FROM square_booking_sync')).rows[0];
const rpc=async(name,args)=>(await db.query('SELECT * FROM square_'+name+'('+args.map((_,i)=>'$'+(i+1)).join(',')+')',args)).rows;
let checks=0;
const equal=(a,b)=>{assert.deepEqual(a,b);checks++;};
let c=await connection();
const set=async(enabled=true,user=u,conn=c.connection_id,rev=c.selection_revision)=>(await rpc('sync_set',[b,'sandbox',user,conn,rev,enabled]))[0].square_sync_set;
const claim=async(user=u)=>(await rpc('sync_claim',[b,'sandbox',user]));
const start='2026-10-01T00:00:00Z',end='2026-11-01T00:00:00Z';
const finish=async(lease,rows,error=null,user=u)=>(await rpc('sync_finish',[b,'sandbox',user,lease,JSON.stringify(rows),start,end,error]))[0].square_sync_finish;
const due=async()=>db.exec("UPDATE square_booking_sync SET due_at=now()-interval '1 minute'");
equal(await set(true,other),false); equal(await set(true,u,b),false); equal(await set(),true);
equal((await state()).appointments,[]);
equal(await finish(null,[]),false);
equal((await claim(other)).length,0);
let job=(await claim())[0];assert.ok(job.lease);checks++;
equal((await claim()).length,0);
equal(await finish(b,[]),false);
equal(await finish(job.lease,[{id:'A',version:2,status:'ACCEPTED'}],null,other),false);
equal(await finish(job.lease,[{id:'A',version:2,status:'ACCEPTED'}]),true);
equal((await state()).appointments,[{id:'A',version:2,status:'ACCEPTED'}]);
equal((await claim()).length,0);
await due();job=(await claim())[0];
equal(await finish(job.lease,[],'unavailable'),true);
equal((await state()).appointments.length,1);equal((await state()).last_error,'unavailable');
await due();job=(await claim())[0];
equal(await finish(job.lease,[{id:'A',version:1,status:'ACCEPTED'}]),true);
equal((await state()).appointments[0].version,2);equal((await state()).last_error,'changed');
await due();job=(await claim())[0];
equal(await finish(job.lease,[{id:'A',version:3,status:'CANCELLED_BY_SELLER'}]),true);
equal((await state()).appointments[0].status,'CANCELLED_BY_SELLER');
await due();job=(await claim())[0];
equal(await finish(job.lease,[]),true);equal((await state()).appointments,[]);
await due();job=(await claim())[0];
equal(await set(false),true);equal(await state(),undefined);equal(await finish(job.lease,[{id:'late',version:5}]),false);
equal(await set(),true);job=(await claim())[0];
await db.exec("UPDATE square_booking_sync SET lease_until=now()-interval '1 second'");
equal(await finish(job.lease,[]),false);const retry=(await claim())[0];assert.notEqual(job.lease,retry.lease);checks++;
equal(await finish(job.lease,[]),false);
// Selection changes purge data and invalidate in-flight claims in the SAME transaction.
await rpc('save_locations',[b,'sandbox',u,c.connection_id,c.selection_revision,['L2']]);
equal(await state(),undefined);equal(await finish(retry.lease,[]),false);equal(await set(),false);
c=await connection();equal(await set(),true);job=(await claim())[0];
await db.query('UPDATE businesses SET owner_id=$1 WHERE id=$2',[other,b]);
equal(await state(),undefined);equal(await finish(job.lease,[]),false);
await db.query('UPDATE businesses SET owner_id=$1 WHERE id=$2',[u,b]);
equal(await set(),true);job=(await claim())[0];
await rpc('disconnect',[b,'sandbox',u]);equal(await state(),undefined);equal(await finish(job.lease,[]),false);
for(const role of ['anon','authenticated']) {
 await db.exec('SET ROLE '+role);
 await assert.rejects(db.query('SELECT * FROM square_booking_sync'),/permission denied/);checks++;
 for(const [name,args] of [['sync_set',[b,'sandbox',u,c.connection_id,c.selection_revision,true]],['sync_claim',[b,'sandbox',u]],['sync_finish',[b,'sandbox',u,b,'[]',start,end,null]]]) {
  await assert.rejects(rpc(name,args),/permission denied/);checks++;
 }
 await db.exec('RESET ROLE');
}
equal((await db.query("SELECT relrowsecurity FROM pg_class WHERE oid='square_booking_sync'::regclass")).rows[0].relrowsecurity,true);
console.log(checks+' Square sync database checks passed');
await db.close();

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const { PGlite } = await import(process.env.PGLITE_MODULE || process.argv[2] || '@electric-sql/pglite');
const db = new PGlite();
await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
create schema auth; create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz,
 raw_user_meta_data jsonb default '{}',created_at timestamptz default now(),invited_at timestamptz,
 is_anonymous boolean default false,deleted_at timestamptz,banned_until timestamptz);
create table businesses(id uuid primary key,owner_id uuid);
create table user_profiles(user_id uuid,is_grandfathered boolean);
create table business_users(user_id uuid,invited_email text);
create table business_collaborators(user_id uuid,invited_email text);
grant usage on schema public,auth to service_role,authenticated,anon;`);
const sql = readFileSync('supabase/APPLY-2026-09-29-lifecycle-delivery.sql','utf8');
await db.exec(sql); await db.exec(sql);
const id=n=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0');
for(let n=1;n<=12;n++) await db.query(`insert into auth.users(id,email,email_confirmed_at,raw_user_meta_data,created_at)
values($1,$2,now(),'{"solutionist_signup_intent":"business"}',now()-interval '2 days')`,[id(n),'user'+n+'@example.com']);
await db.query('insert into businesses values($1,$2)',[id(100),id(2)]);
await db.query('insert into business_users values($1,null)',[id(3)]);
await db.query('insert into business_collaborators values(null,$1)',['USER4@example.com']);
await db.query('update auth.users set email_confirmed_at=null where id=$1',[id(5)]);
await db.query('update auth.users set invited_at=now() where id=$1',[id(6)]);
await db.query("update auth.users set raw_user_meta_data='{}' where id=$1",[id(7)]); // student/non-business account
await db.query("update auth.users set banned_until=now()+interval '1 day' where id=$1",[id(8)]);
await db.query('update auth.users set deleted_at=now() where id=$1',[id(9)]);
await db.query('insert into user_profiles values($1,true)',[id(10)]);
await db.query("update auth.users set created_at=now()-interval '8 days' where id=$1",[id(11)]);
await db.query('update auth.users set is_anonymous=true where id=$1',[id(12)]);
for(const role of ['anon','authenticated']) {
 await db.exec('set role '+role);
 await assert.rejects(()=>db.query('select * from lifecycle_email_deliveries'),/permission denied/);
 await assert.rejects(()=>db.query('select lifecycle_claim($1,$2)',['forged',{}]),/permission denied/);
 await assert.rejects(()=>db.query('select * from lifecycle_signup_candidates()'),/permission denied/);
 await db.exec('reset role');
}
await db.exec('set role service_role');
const candidates=async()=> (await db.query('select * from lifecycle_signup_candidates()')).rows;
assert.deepEqual((await candidates()).map(r=>r.user_id),[id(1)]);
const key='signup/'+id(1)+'/signup_day_one';
const claim=async(k=key,p={body:'original'})=>(await db.query('select lifecycle_claim($1,$2) as v',[k,p])).rows[0].v;
const first=await claim(); assert.equal(first.state,'claimed');
assert.equal((await claim()).state,'busy');
assert.equal((await db.query('select lifecycle_finish($1,$2,$3) as v',[key,id(99),'wrong'])).rows[0].v,false);
await db.query("update lifecycle_email_deliveries set lease_until=now()-interval '1 minute' where delivery_key=$1",[key]);
const retry=await claim(key,{body:'changed'}); assert.equal(retry.payload.body,'original');
assert.notEqual(retry.token,first.token);
assert.equal((await db.query('select lifecycle_finish($1,$2,$3) as v',[key,retry.token,'resend-id'])).rows[0].v,true);
assert.equal((await claim()).state,'sent');
assert.equal((await candidates()).length,0);
await db.exec('reset role');
await db.query("update auth.users set created_at=now()-interval '4 days' where id=$1",[id(1)]);
await db.exec('set role service_role');
assert.equal((await candidates()).length,0); // minimum one day between reminders
await db.query("update lifecycle_email_deliveries set sent_at=now()-interval '25 hours' where delivery_key=$1",[key]);
assert.equal((await candidates())[0].kind,'signup_day_three');
await db.exec('reset role');
await db.query('insert into businesses values($1,$2)',[id(101),id(1)]);
await db.exec('set role service_role');
assert.equal((await candidates()).length,0); // stop as soon as setup completes
await claim('ambiguous');
await db.query("update lifecycle_email_deliveries set first_attempt_at=now()-interval '24 hours',lease_until=null where delivery_key='ambiguous'");
assert.equal((await claim('ambiguous')).state,'review');
const failed=await claim('retry');
assert.equal((await db.query('select lifecycle_fail($1,$2,$3) as v',['retry',failed.token,'TimeoutError'])).rows[0].v,true);
assert.equal((await claim('retry')).state,'busy'); // retry backoff
await db.query("update lifecycle_email_deliveries set lease_until=now()-interval '1 second' where delivery_key='retry'");
assert.equal((await claim('retry')).state,'claimed');
await db.exec('reset role');
await db.query("insert into lifecycle_signup_intents(user_id,started_at) values($1,now()-interval '2 days')",[id(7)]);
await db.exec('set role service_role');
assert.deepEqual((await candidates()).map(r=>r.user_id),[id(7)]); // explicit onboarding for OAuth
await db.close();
console.log('Lifecycle SQL passed: private ledger, exclusive claims, retry backoff, frozen payload, no replay, review cutoff, recipient exclusions, spaced reminders, completion stop, explicit OAuth intent.');

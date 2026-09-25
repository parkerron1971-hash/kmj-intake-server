// Actual PostgreSQL semantics, synthetic identities; no remote database.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db = new PGlite();
await db.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS; CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY); CREATE TABLE businesses(id uuid PRIMARY KEY);');
const sql = readFileSync('supabase/APPLY-2026-09-24-lane-wallet.sql', 'utf8');
await db.exec(sql); await db.exec(sql);
const id = n => '00000000-0000-4000-8000-' + String(n).padStart(12, '0');
await db.query('INSERT INTO businesses VALUES($1),($2)', [id(1),id(2)]);
await db.query('INSERT INTO auth.users VALUES($1),($2)', [id(3),id(4)]);
const rpc = async (fn, args) => (await db.query('SELECT ' + fn + '(' + args.map((_,i) => '$'+(i+1)).join(',') + ') AS v', args)).rows[0].v;
const create = [id(1),id(3),id(5),'ciphertext','a'.repeat(64)];
assert.equal(await rpc('lane_purchase_create', create),true);
assert.equal(await rpc('lane_purchase_create', create),true);
assert.equal(await rpc('lane_purchase_create',[id(2),...create.slice(1)]),false);
assert.equal(await rpc('lane_purchase_create',[id(1),id(3),id(6),'ciphertext','b'.repeat(64)]),false);
const a=[id(1),id(3),id(5),id(7)];
assert.equal((await rpc('lane_purchase_acquire',a)).revision,0);
assert.equal(await rpc('lane_purchase_acquire',[...a.slice(0,3),id(8)]),null);
assert.equal(await rpc('lane_purchase_acquire',[id(2),...a.slice(1)]),null);
const save=(rev,claim=false,phase='approved') => [...a,rev,phase,'lint_test','encrypted-'+rev,claim];
assert.equal((await rpc('lane_purchase_save',save(0))).revision,1);
assert.equal(await rpc('lane_purchase_save',save(0)),null); // stale CAS
assert.equal(await rpc('lane_purchase_save',[id(2),...save(1).slice(1)]),null);
assert.equal((await rpc('lane_purchase_save',save(1,true,'checkout_unknown'))).checkout_claimed,true);
assert.equal(await rpc('lane_purchase_save',save(2,true,'checkout_unknown')),null);
await db.query("UPDATE lane_purchases SET lease_until=clock_timestamp()-interval '1 second'");
assert.equal(await rpc('lane_purchase_save',save(2)),null);
const b=[id(1),id(3),id(5),id(8)];
const restarted=await rpc('lane_purchase_acquire',b);
assert.equal(restarted.checkout_claimed,true);
assert.equal(restarted.phase,'checkout_unknown');
assert.equal(await rpc('lane_purchase_release',a),false);
assert.equal(await rpc('lane_purchase_save',save(2)),null);
assert.equal((await rpc('lane_purchase_save',[...b,2,'running','lint_test','encrypted-new',false])).checkout_claimed,true);
assert.equal((await rpc('lane_purchase_list',[id(2),id(3)])).length,0);
assert.equal((await rpc('lane_purchase_list',[id(1),id(4)])).length,0);
assert.equal((await rpc('lane_purchase_list',[id(1),id(3)])).length,1);
assert.equal(await rpc('lane_purchase_save',[...b,3,'running','lint_other','x',false]),null);
const functions=['lane_purchase_create(uuid,uuid,uuid,text,text)','lane_purchase_list(uuid,uuid)','lane_purchase_acquire(uuid,uuid,uuid,uuid)','lane_purchase_save(uuid,uuid,uuid,uuid,integer,text,text,text,boolean)','lane_purchase_release(uuid,uuid,uuid,uuid)'];
for(const role of ['anon','authenticated']){
 assert.equal((await db.query("SELECT has_table_privilege($1,'lane_purchases','SELECT') AS v",[role])).rows[0].v,false);
 for(const fn of functions) assert.equal((await db.query("SELECT has_function_privilege($1,$2,'EXECUTE') AS v",[role,fn])).rows[0].v,false);
}
await db.exec('SET ROLE service_role');
assert.equal((await rpc('lane_purchase_list',[id(1),id(3)])).length,1);
await db.close();
console.log('PASS: migration replay, tenant isolation, duplicate drafts, leases, stale writers, permanent checkout claims, and service-only access.');

process.on('uncaughtException',e=>{ console.error(e.message, e.where || ''); process.exit(1); });
import {pathToFileURL} from 'node:url';
const {PGlite} = await import(process.env.PGLITE_MODULE ? pathToFileURL(process.env.PGLITE_MODULE).href : '@electric-sql/pglite');
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const db=new PGlite();
await db.exec(`create role anon; create role authenticated; create role service_role;
create schema auth;
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
create table businesses(id uuid primary key,owner_id uuid);
create table image_artworks(id uuid primary key,business_id uuid,owner_id uuid default auth.uid(),prompt text,model text,quality text,size text,reference_ids jsonb,created_at timestamptz default now());`);
await db.exec(await readFile('__migrations__/2026_06_13_chief_jobs.sql','utf8'));
await db.exec(await readFile('supabase/APPLY-2026-08-13-chief-jobs-single-active.sql','utf8'));
const imageSql=await readFile('supabase/APPLY-2026-09-08-image-studio.sql','utf8');
await db.exec(imageSql.slice(imageSql.indexOf('create or replace function public.reserve_image_artwork'),imageSql.indexOf('-- Atomic merge')));
await db.exec(await readFile('supabase/APPLY-2026-09-18-chief-builds.sql','utf8'));
const lanes=await readFile('supabase/APPLY-2026-09-26-chief-build-lanes.sql','utf8');
await db.exec(lanes);await db.exec(lanes);
const b='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',other='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',u='11111111-1111-1111-1111-111111111111';
await db.query('insert into businesses values ($1,$2),($3,$2)',[b,u,other]);
const ids={};let n=0;
async function job(name,kind,biz=b){
  const id=`0000000${++n}-0000-4000-8000-000000000000`;ids[name]=id;
  await db.query("insert into chief_jobs(id,user_id,business_id,kind,status,params) values ($1,$2,$3,'build','queued',$4)",[id,u,biz,{order_id:id,kind}]);
}
const claim=async(name,token)=>(await db.query('select * from chief_build_claim($1,$2)',[ids[name],token])).rows.length;
const tok=i=>`9999999${i}-0000-4000-8000-000000000000`;
for(const [name,kind] of [['workshop','event_setup'],['door','site_door'],['form','form_and_link'],['flyer','flyer'],['flyer2','flyer'],['plan','plan'],['plan2','plan'],['legacy',null]])await job(name,kind);
await job('elsewhere','event_setup',other);
// One message: a workshop, a flyer and a plan all start at once.
assert.equal(await claim('workshop',tok(1)),1);
assert.equal(await claim('flyer',tok(2)),1);
assert.equal(await claim('plan',tok(3)),1);
// Things that share the site, the image lane or the plan lane still take turns.
assert.equal(await claim('door',tok(4)),0);
assert.equal(await claim('form',tok(4)),0);
assert.equal(await claim('legacy',tok(4)),0);
assert.equal(await claim('flyer2',tok(4)),0);
assert.equal(await claim('plan2',tok(4)),0);
// Another business is never held up by this one.
assert.equal(await claim('elsewhere',tok(5)),1);
// When the workshop finishes, the next site job can start.
await db.query("select * from chief_build_save($1,$2,$3,'done')",[ids.workshop,tok(1),{status:'done'}]);
assert.equal(await claim('door',tok(6)),1);
// A lease that ran out frees its lane.
await db.query("update chief_jobs set build_lease_until=now()-interval '1 second' where id=$1",[ids.plan]);
assert.equal(await claim('plan2',tok(7)),1);
const lanesOf=(await db.query("select chief_build_lane('flyer') f, chief_build_lane('plan') p, chief_build_lane('event_setup') e, chief_build_lane(null) x")).rows[0];
assert.deepEqual(lanesOf,{f:'image',p:'plan',e:'site',x:'site'});
for(const fn of ['chief_build_claim(uuid,uuid)','chief_build_lane(text)'])
  assert.equal((await db.query(`select has_function_privilege('authenticated','${fn}','EXECUTE') as allowed`)).rows[0].allowed,false);
assert.equal((await db.query("select has_function_privilege('service_role','chief_build_claim(uuid,uuid)','EXECUTE') as allowed")).rows[0].allowed,true);
console.log('SQL checks passed: build lanes replay, side-by-side lanes, same-lane turns, other businesses unaffected, finish frees a lane, expired lease frees a lane, RPC permissions.');
await db.close();

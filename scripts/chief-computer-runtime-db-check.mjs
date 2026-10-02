// Real PostgreSQL transaction/state invariants. No live services or secrets.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {PGlite}=await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db=new PGlite();
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE TABLE businesses(id uuid PRIMARY KEY, settings jsonb DEFAULT '{}');
CREATE TABLE chief_jobs(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid, business_id uuid,
kind text,status text,source text,params jsonb);
CREATE UNIQUE INDEX one_active ON chief_jobs(business_id,kind) WHERE status IN ('queued','running');
CREATE FUNCTION is_business_owner(uuid) RETURNS boolean LANGUAGE sql AS 'SELECT false';
CREATE FUNCTION is_business_member(uuid) RETURNS boolean LANGUAGE sql AS 'SELECT false';`);
await db.exec(readFileSync('supabase/APPLY-2026-09-12-chief-computer.sql','utf8'));
const migration=readFileSync('supabase/APPLY-2026-09-12-chief-computer-runtime.sql','utf8');
await db.exec(migration);
await db.exec(migration);
await db.query('INSERT INTO businesses(id,settings) VALUES($1,$2)',[id(1),{unrelated:{keep:true}}]);
const plan={business_id:id(1),user_id:id(2),kind:'reorder',title:'Fixture reorder',
    plan:{items:[{offering_id:id(3),qty:1}]},hosts:['supplier.test'],spend_limit_cents:15000,
    planned_total_cents:200,idempotency_key:'today-fixture'};
const rpc=async(name,args)=> (await db.query(`SELECT to_jsonb(${name}(${args.map((_,i)=>'$'+(i+1)).join(',')})) AS result`,args)).rows[0].result;
const refuses=async(query,pattern)=>{
    await db.exec('SAVEPOINT denied');
    await assert.rejects(query,pattern);
    await db.exec('ROLLBACK TO denied; RELEASE denied');
};
await db.exec('BEGIN');
const e=await rpc('chief_errand_plan',[plan]);
assert.equal(e.status,'planned');
assert.equal((await rpc('chief_errand_plan',[plan])).id,e.id);
assert.equal((await rpc('chief_errand_plan',[{...plan,idempotency_key:'other',plan:{items:[{offering_id:id(3),qty:40},{offering_id:id(4),qty:1}]}}])).id,e.id);
for(const role of ['anon','authenticated']) {
    await db.exec(`SET LOCAL ROLE ${role}`);
    await refuses(()=>rpc('chief_errand_plan',[plan]),/permission denied/);
    await refuses(()=>rpc('chief_errand_approve',[id(1),e.id,id(2),'button']),/permission denied/);
    await db.exec('RESET ROLE');
}
const approved=await rpc('chief_errand_approve',[id(1),e.id,id(2),'button']);
assert.equal(approved.errand.job_id,approved.job.id);
assert.equal(approved.job.params.errand_id,e.id);
await refuses(()=>rpc('chief_errand_approve',[id(1),e.id,id(2),'button']),/errand_changed/);
assert.equal((await db.query('SELECT * FROM chief_jobs')).rows.length,1);
const other=await rpc('chief_errand_plan',[{...plan,idempotency_key:'other-item',plan:{items:[{offering_id:id(9),qty:1}]}}]);
await refuses(()=>rpc('chief_errand_approve',[id(1),other.id,id(2),'button']),/duplicate key/);
assert.equal((await db.query('SELECT status FROM chief_errands WHERE id=$1',[other.id])).rows[0].status,'planned');
const change=(expected,patch,hold=null)=>rpc('chief_errand_transition',[id(1),e.id,expected,patch,{kind:'note',note:'Fixture transition'},hold]);
await refuses(()=>change(['approved'],{status:'done'}),/transition_not_allowed/);
await refuses(()=>change(['approved'],{business_id:id(9)}),/patch_not_allowed/);
await change(['approved'],{status:'running'});
await change(['running'],{status:'needs_you',hold:{id:'hold-1',kind:'secret'}});
await refuses(()=>change(['needs_you'],{status:'running'},'other-hold'),/errand_changed/);
await change(['needs_you'],{status:'paused'});
assert.equal((await db.query('SELECT hold FROM chief_errands WHERE id=$1',[e.id])).rows[0].hold.id,'hold-1');
await change(['paused'],{status:'needs_you'});
await change(['needs_you'],{status:'running',hold:null},'hold-1');
await change(['running'],{status:'done',finished_at:new Date().toISOString()});
await refuses(()=>change(['done'],{status:'running'}),/transition_not_allowed/);
const events=(await db.query('SELECT n FROM chief_errand_events WHERE errand_id=$1 ORDER BY n',[e.id])).rows;
assert.deepEqual(events.map(e=>e.n),Array.from({length:events.length},(_,i)=>i+1));
await rpc('chief_computer_settings',[id(1),{spend_limit_cents:200}]);
assert.deepEqual((await db.query('SELECT settings FROM businesses')).rows[0].settings,
    {unrelated:{keep:true},computer:{spend_limit_cents:200}});
await db.exec('ROLLBACK');
await db.close();
console.log('Chief runtime SQL passed: role denial, atomic approval/job, duplicate/overlap refusal, hold CAS, state transitions, event sequencing and settings preservation.');

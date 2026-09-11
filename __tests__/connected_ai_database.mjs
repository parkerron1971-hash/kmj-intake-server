// Executes the shipped PL/pgSQL in real PostgreSQL (PGlite, one connection).
// Pass an installed @electric-sql/pglite module path as argv[2]. No live DB.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
const {PGlite}=await import(process.argv[2] ? pathToFileURL(process.argv[2]).href : '@electric-sql/pglite');
const db=new PGlite();
await db.exec(`
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE TABLE businesses(id uuid PRIMARY KEY,owner_id uuid,name text);
CREATE TABLE contacts(id uuid PRIMARY KEY,business_id uuid,name text,email text);
CREATE TABLE invoices(id uuid PRIMARY KEY,business_id uuid,customer_name text,customer_email text,
 amount_due_cents integer,currency text DEFAULT 'usd',due_date date,status text DEFAULT 'open'
 CHECK(status IN ('draft','open','paid','uncollectible','void')),archived_at timestamptz,paid_at timestamptz,
 updated_at timestamptz DEFAULT now());
CREATE TABLE chief_jobs(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),user_id uuid NOT NULL,business_id uuid NOT NULL,
 kind text NOT NULL,status text NOT NULL DEFAULT 'queued',source text NOT NULL DEFAULT 'desktop',
 params jsonb NOT NULL DEFAULT '{}',result jsonb,error text,created_at timestamptz DEFAULT now(),
 started_at timestamptz,finished_at timestamptz);
CREATE UNIQUE INDEX chief_jobs_one_active_per_business_kind ON chief_jobs(business_id,kind) WHERE status IN ('queued','running');
CREATE TABLE agent_queue(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),business_id uuid NOT NULL,contact_id uuid,
 agent text NOT NULL,action_type text NOT NULL CHECK(action_type IN ('email','sms','follow_up','proposal','invoice','check_in','onboarding','alert','document','other')),
 channel text CHECK(channel IN ('email','sms','in_app','slack','other')),subject text,body text,
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','sent','dismissed','failed','expired')),
 priority text CHECK(priority IN ('urgent','high','medium','low')),ai_reasoning text,reviewed_at timestamptz,sent_at timestamptz);
`);
const migration=await readFile(new URL('../supabase/APPLY-2026-09-11-connected-ai.sql',import.meta.url),'utf8');
await db.exec(migration); await db.exec(migration);
let checks=1;
const b=randomUUID(),owner=randomUUID(),other=randomUUID(),contact=randomUUID(),invoice=randomUUID();
await db.query('INSERT INTO businesses VALUES($1,$2,$3)',[b,owner,'Example Studio']);
await db.query('INSERT INTO contacts VALUES($1,$2,$3,$4)',[contact,b,'Alex Example','alex@example.test']);
await db.query("INSERT INTO invoices(id,business_id,customer_email,amount_due_cents,due_date) VALUES($1,$2,$3,12000,current_date-7)",[invoice,b,'alex@example.test']);
async function call(op,data={},actor=owner,business=b){return (await db.query('SELECT connected_ai_transition($1,$2,$3,$4::jsonb) AS result',[op,business,actor,JSON.stringify(data)])).rows[0].result;}
async function rejects(op,data,error,actor=owner,business=b){await assert.rejects(call(op,data,actor,business),new RegExp(error));checks++;}
async function pairDevice(provider='chatgpt'){
 const hash=randomUUID(),token=randomUUID();
 await call('pair',{provider,secret_hash:hash});
 const d=await call('claim',{secret_hash:hash,token_hash:token,label:'Fixture desktop'});
 assert.equal(d.token_hash,undefined); checks++;
 await rejects('claim',{secret_hash:hash,token_hash:randomUUID(),label:'Replay'},'pairing_expired');
 const auth={device_id:d.id,token_hash:token};
 await call('heartbeat',{...auth,state:'signed_in'});
 return auth;
}
let auth=await pairDevice();
const request=randomUUID();
const input={device_id:auth.device_id,invoice_id:invoice,request_id:request};
const j=await call('enqueue',input);
assert.equal((await call('enqueue',input)).id,j.id);checks++;
await rejects('enqueue',{...input,device_id:randomUUID()},'request_conflict');
await rejects('status',{},'owner_required',other);
await rejects('enqueue',{...input,request_id:randomUUID()},'job_already_active');
await rejects('heartbeat',{...auth,token_hash:'wrong',state:'signed_in'},'device_revoked');
const lease_hash=randomUUID();
const work=(await call('lease',{...auth,lease_hash})).job;
assert.equal(work.id,j.id);
assert.deepEqual(Object.keys(work.facts).sort(),['amount_due_cents','business_name','contact_name','currency','due_date','invoice_number']);checks++;
const completed={...auth,job_id:j.id,lease_hash,subject:'Invoice reminder',body:'Hello Alex, please review your overdue invoice.'};
await rejects('complete',{...completed,lease_hash:'wrong'},'lease_invalid');
const draft=await call('complete',completed);
assert.equal(draft.sent,false);assert.equal((await call('complete',completed)).queue_id,draft.queue_id);checks++;
const status=await call('status');
assert.equal(status.devices[0].token_hash,undefined);
assert.equal(status.jobs[0].params,undefined);checks++;
await db.query('UPDATE invoices SET amount_due_cents=13000 WHERE id=$1',[invoice]);
await rejects('claim_send',{job_id:j.id},'invoice_changed');
await db.query('UPDATE invoices SET amount_due_cents=12000 WHERE id=$1',[invoice]);
const send=await call('claim_send',{job_id:j.id,subject:'Reviewed reminder',body:completed.body});
assert.equal(send.expected_email,'alex@example.test');assert.equal(send.item.subject,'Reviewed reminder');checks++;
await rejects('claim_send',{job_id:j.id},'already_reviewed');
await call('settle_send',{job_id:j.id,sent:true,provider_id:'fixture-message'});
await rejects('settle_send',{job_id:j.id,sent:true},'already_reviewed');
await rejects('enqueue',{...input,request_id:randomUUID()},'job_already_active');

// Independent invoices exercise cancellation, lease expiry, stale completion,
// revocation, provider limits, and an uncertain/crashed send without any email.
async function nextJob(){
 const id=randomUUID();
 await db.query("INSERT INTO invoices(id,business_id,customer_email,amount_due_cents,due_date) VALUES($1,$2,$3,12000,current_date-7)",[id,b,'alex@example.test']);
 await call('heartbeat',{...auth,state:'signed_in'});
 const job=await call('enqueue',{device_id:auth.device_id,invoice_id:id,request_id:randomUUID()});
 const lease=randomUUID();await call('lease',{...auth,lease_hash:lease});
 return {id,job,data:{...completed,...auth,job_id:job.id,lease_hash:lease}};
}
let n=await nextJob();await call('cancel',{job_id:n.job.id});
assert.equal((await call('heartbeat',{...auth,state:'signed_in',job_id:n.job.id,lease_hash:n.data.lease_hash})).active,false);checks++;
await rejects('complete',n.data,'lease_expired');
n=await nextJob();await db.query("UPDATE invoices SET status='paid',paid_at=now() WHERE id=$1",[n.id]);
assert.equal((await call('complete',n.data)).error,'invoice_changed');checks++;
n=await nextJob();await db.query("UPDATE chief_jobs SET params=params||jsonb_build_object('lease_until',now()-interval '1 second') WHERE id=$1",[n.job.id]);
await call('status');await rejects('complete',n.data,'lease_expired');
n=await nextJob();await call('fail',{...n.data,error:'usage_limits'});
assert.equal((await call('status')).devices[0].state,'usage_limits');checks++;
n=await nextJob();await call('complete',n.data);await call('revoke',{device_id:auth.device_id});
await rejects('complete',n.data,'device_revoked');
await rejects('claim_send',{job_id:n.job.id},'already_reviewed');
assert.equal((await db.query('SELECT status FROM agent_queue WHERE connected_ai_job_id=$1',[n.job.id])).rows[0].status,'dismissed');checks++;
auth=await pairDevice('claude');
n=await nextJob();await call('complete',n.data);await call('claim_send',{job_id:n.job.id});
await db.query("UPDATE chief_jobs SET params=params||jsonb_build_object('send_started_at',now()-interval '6 minutes') WHERE id=$1",[n.job.id]);
assert.equal((await call('status')).jobs.find(v=>v.id===n.job.id).delivery_state,'unknown');checks++;
await rejects('claim_send',{job_id:n.job.id},'already_reviewed');
await rejects('enqueue',{device_id:auth.device_id,invoice_id:n.id,request_id:randomUUID()},'job_already_active');
const expired=randomUUID();await call('pair',{provider:'claude',secret_hash:expired});
await db.query("UPDATE connected_ai_pairings SET expires_at=now()-interval '1 second' WHERE secret_hash=$1",[expired]);
await rejects('claim',{secret_hash:expired,token_hash:randomUUID(),label:'Expired'},'pairing_expired');
await db.exec('SET ROLE authenticated');
await assert.rejects(db.query('SELECT connected_ai_transition($1,$2,$3,$4)', ['status',b,owner,'{}']),/permission denied/);checks++;
await db.exec('RESET ROLE');
await db.query('UPDATE businesses SET owner_id=$1 WHERE id=$2',[other,b]);
await rejects('heartbeat',{...auth,state:'signed_in'},'owner_required');
console.log(`${checks} PostgreSQL lifecycle checks passed; migration applied twice. Single-connection test, not a parallel-process race test.`);
await db.close();

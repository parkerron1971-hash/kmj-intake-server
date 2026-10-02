// Run with: node --experimental-default-type=module __tests__/marketing_campaigns_db.mjs
// Install @electric-sql/pglite into output/marketing-qa first (see setup doc).
const { PGlite } = await import(process.env.PGLITE_MODULE || '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const db=new PGlite();
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);`);
await db.exec(await readFile(new URL('../supabase/APPLY-2026-09-15-platform-marketing.sql',import.meta.url),'utf8'));
const migration=await readFile(new URL('../supabase/APPLY-2026-09-26-marketing-campaigns.sql',import.meta.url),'utf8');
await db.exec(migration); await db.exec(migration);
const campaign='10000000-0000-4000-8000-000000000001',actor='10000000-0000-4000-8000-000000000002';
const request='10000000-0000-4000-8000-000000000003',post='10000000-0000-4000-8000-000000000004';
await db.query(`INSERT INTO platform_marketing_campaigns(id,tracking_key,name,brief,brief_hash,updated_by) VALUES($1,'mc-test','Campaign','{}','hash',$2)`,[campaign,actor]);
assert.equal((await db.query('SELECT count(*)::int n FROM platform_marketing_campaign_events')).rows[0].n,1);
await db.exec('SET ROLE service_role');
const claim=await db.query('SELECT platform_marketing_claim_plan($1,$2,1) claim',[request,campaign]);
assert.equal(claim.rows[0].claim.claimed,true);
assert.equal((await db.query('SELECT platform_marketing_claim_plan($1,$2,1) claim',[request,campaign])).rows[0].claim.claimed,false);
await assert.rejects(db.query('SELECT platform_marketing_claim_plan($1,$2,1)',[post,campaign]));
await db.query(`UPDATE platform_marketing_plan_runs SET status='succeeded' WHERE id=$1`,[request]);
await assert.rejects(db.query('SELECT platform_marketing_claim_plan($1,$2,2)',[post,campaign]));
await db.query(`INSERT INTO platform_marketing_posts(id,campaign,campaign_id,payload,content_hash,run_at,expires_at,status,provider_id)
VALUES($1,'mc-test',$2,'{"channel_id":"one"}','hash',now()-interval '1 hour',now()+interval '1 hour','published','buffer-one')`,[post,campaign]);
const work=(await db.query('SELECT platform_marketing_claim_metrics() claim')).rows[0].claim;
assert.equal(work.claimed,true); assert.equal(work.posts.length,1);
assert.equal((await db.query('SELECT platform_marketing_claim_metrics() claim')).rows[0].claim.claimed,false);
const metric={post_id:post,provider_id:'buffer-one',metrics:[{type:'impressions',value:12,unit:'count'}],source_updated_at:'2026-09-26T10:00:00Z',error:null};
await db.query('SELECT platform_marketing_store_metrics($1)',[JSON.stringify([metric])]);
await db.query('SELECT platform_marketing_store_metrics($1)',[JSON.stringify([{...metric,metrics:[],source_updated_at:null,error:'Unavailable'}])]);
const retained=(await db.query('SELECT * FROM platform_marketing_metrics')).rows[0];
assert.equal(retained.metrics[0].value,12); assert.equal(retained.error,'Unavailable');
await assert.rejects(db.query('SELECT platform_marketing_store_metrics($1)',[JSON.stringify([{...metric,provider_id:'wrong'}])]));
await db.exec('RESET ROLE');
assert.equal((await db.query(`SELECT count(*)::int n FROM pg_class WHERE relname IN ('platform_marketing_campaigns','platform_marketing_campaign_events','platform_marketing_plan_runs','platform_marketing_metrics','platform_marketing_metric_sync') AND relrowsecurity`)).rows[0].n,5);
for(const role of ['anon','authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for(const table of ['platform_marketing_campaigns','platform_marketing_campaign_events','platform_marketing_plan_runs','platform_marketing_metrics','platform_marketing_metric_sync'])
    await assert.rejects(db.query(`SELECT * FROM ${table}`));
  await assert.rejects(db.query('SELECT platform_marketing_claim_metrics()'));
  await assert.rejects(db.query('SELECT platform_marketing_claim_plan($1,$2,1)',[request,campaign]));
  await assert.rejects(db.query('SELECT platform_marketing_store_metrics($1)',[JSON.stringify([metric])]));
  await db.exec('RESET ROLE');
}
await db.close();
console.log('Campaign SQL checks passed: replay, audit, RLS, plan claims, provider identity, cooldown and retained metrics.');

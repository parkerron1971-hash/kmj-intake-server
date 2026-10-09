// Runs real PostgreSQL semantics in an ephemeral PGlite database; no live Supabase.
import { pathToFileURL } from 'node:url';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const db = new PGlite();
const b1='11111111-1111-4111-8111-111111111111', b2='22222222-2222-4222-8222-222222222222';
const u1='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', u2='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
await db.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS; CREATE TABLE businesses(id uuid PRIMARY KEY, owner_id uuid NOT NULL);');
await db.query('INSERT INTO businesses VALUES ($1,$2),($3,$4)',[b1,u1,b2,u2]);
await db.exec(await readFile(new URL('../supabase/APPLY-2026-10-08-square-connections.sql',import.meta.url),'utf8'));
await db.exec(await readFile(new URL('../supabase/APPLY-2026-10-08-square-connections.sql',import.meta.url),'utf8'));
let checks=0;
const rpc = async (name,args) => (await db.query('SELECT * FROM square_'+name+'('+args.map((_,i)=>'$'+(i+1)).join(',')+')',args)).rows;
const truth = async (name,args,expected=true) => { assert.equal((await rpc(name,args))[0]['square_'+name],expected); checks++; };
const row = async b => (await db.query('SELECT * FROM square_connections WHERE business_id=$1 AND environment=$2',[b,'sandbox'])).rows[0];
await truth('start',[b1,'sandbox',u2,'wrong-owner'],false);
await truth('start',[b1,'sandbox',u1,'ticket1']);
await truth('begin',['ticket1','state1','browser1','production'],false);
await truth('begin',['ticket1','state1','browser1','sandbox']);
await truth('begin',['ticket1','state1','browser1','sandbox'],false);
assert.equal((await rpc('claim',['state1','wrong-browser','sandbox'])).length,0); checks++;
assert.equal((await rpc('claim',['state1','browser1','production'])).length,0); checks++;
let claim=(await rpc('claim',['state1','browser1','sandbox']))[0];
assert.equal(claim.business_id,b1); checks++;
assert.equal((await rpc('claim',['state1','browser1','sandbox'])).length,0); checks++;
const expiry=new Date(Date.now()+86400000).toISOString();
await truth('finish',[b1,'sandbox',u1,claim.attempt_id,'merchant1','ciphertext',expiry]);
assert.equal((await row(b1)).state_hash,null); checks++;
await truth('start',[b1,'sandbox',u1,'again'],false);
let revision=(await row(b1)).revision;
await truth('refresh',[b1,'sandbox',revision,'fresh-ciphertext',expiry]);
await truth('refresh',[b1,'sandbox',revision,'stale-ciphertext',expiry],false);
// Same merchant cannot attach to another business; first connection remains intact.
await truth('start',[b2,'sandbox',u2,'ticket2']);
await truth('begin',['ticket2','state2','browser2','sandbox']);
claim=(await rpc('claim',['state2','browser2','sandbox']))[0];
await truth('finish',[b2,'sandbox',u2,claim.attempt_id,'merchant1','other-ciphertext',expiry],false);
assert.equal((await row(b1)).credentials,'fresh-ciphertext'); checks++;
// Owner change between callback and save rejects the old owner.
await db.query('UPDATE businesses SET owner_id=$1 WHERE id=$2',[u1,b2]);
await truth('finish',[b2,'sandbox',u2,claim.attempt_id,'merchant2','other-ciphertext',expiry],false);
await db.query('UPDATE businesses SET owner_id=$1 WHERE id=$2',[u2,b2]);
// Disconnect cancels pending callback and a stale refresh cannot resurrect credentials.
const dc2=(await rpc('disconnect',[b2,'sandbox',u2]))[0];
await truth('finish',[b2,'sandbox',u2,claim.attempt_id,'merchant2','other-ciphertext',expiry],false);
revision=(await row(b1)).revision;
assert.equal((await rpc('disconnect',[b1,'sandbox',u2])).length,0); checks++;
const dc=(await rpc('disconnect',[b1,'sandbox',u1]))[0];
assert.equal((await row(b1)).credentials,null); checks++;
assert.equal((await row(b1)).status,'revocation_pending'); checks++;
await truth('refresh',[b1,'sandbox',revision,'resurrected',expiry],false);
await truth('start',[b1,'sandbox',u1,'pending'],false);
assert.equal((await rpc('disconnect',[b1,'sandbox',u1])).length,0); checks++;
await truth('finish_disconnect',[b1,'sandbox',revision],false);
await truth('finish_disconnect',[b1,'sandbox',dc.revision]);
await truth('finish_disconnect',[b2,'sandbox',dc2.revision]);
await truth('start',[b1,'sandbox',u1,'expired']);
await db.query("UPDATE square_connections SET attempt_expires_at=now()-interval '1 minute' WHERE business_id=$1",[b1]);
await truth('begin',['expired','s','b','sandbox'],false);
// Starting again invalidates both the previous ticket and callback state.
await truth('start',[b1,'sandbox',u1,'superseded']);
await truth('start',[b1,'sandbox',u1,'replacement']);
await truth('begin',['superseded','s','b','sandbox'],false);
// Client roles cannot read tokens or invoke any privileged state transition.
for (const role of ['anon','authenticated']) {
  await db.exec('SET ROLE '+role);
  await assert.rejects(db.query('SELECT * FROM square_connections'),/permission denied/); checks++;
  await assert.rejects(rpc('start',[b1,'sandbox',u1,'attack']),/permission denied/); checks++;
  await db.exec('RESET ROLE');
}
// Service role may execute only through explicit grants; FK business cleanup cascades.
await db.exec('GRANT SELECT,UPDATE ON businesses TO service_role; SET ROLE service_role;');
await truth('start',[b1,'sandbox',u1,'service']);
await db.exec('RESET ROLE');
await db.query('DELETE FROM businesses WHERE id=$1',[b1]);
assert.equal(await row(b1),undefined); checks++;
await db.close();
console.log(checks+' Square PostgreSQL security and state-transition checks passed.');

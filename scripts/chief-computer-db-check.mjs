// Execute the real migration under PostgreSQL semantics; no live service access.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db = new PGlite();
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$
  SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
CREATE TABLE businesses(id uuid PRIMARY KEY,owner_id uuid);
CREATE TABLE business_users(business_id uuid,user_id uuid,status text);
ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_users ENABLE ROW LEVEL SECURITY;
CREATE FUNCTION public.is_business_owner(b_id uuid) RETURNS boolean
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT EXISTS(SELECT 1 FROM businesses WHERE id=b_id AND owner_id=auth.uid()) $$;
CREATE FUNCTION public.is_business_member(b_id uuid) RETURNS boolean
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT EXISTS(SELECT 1 FROM business_users WHERE business_id=b_id AND user_id=auth.uid() AND status='active') $$;
GRANT USAGE ON SCHEMA public,auth TO anon,authenticated,service_role;`);
const migration = readFileSync('supabase/APPLY-2026-09-12-chief-computer.sql', 'utf8');
await db.exec(migration);
await db.exec(migration);
await db.exec(readFileSync('supabase/VERIFY-chief-computer-access.sql', 'utf8'));
const tableNames = ['chief_errands', 'chief_errand_events', 'business_secrets'];
assert.equal((await db.query("SELECT count(*)::int AS n FROM pg_class WHERE relname=ANY($1) AND relrowsecurity", [tableNames])).rows[0].n, 3);
assert.equal((await db.query("SELECT count(*)::int AS n FROM pg_policies WHERE tablename='business_secrets'")).rows[0].n, 0);

// Roll back every fixture row, including attempted hostile writes.
await db.exec('BEGIN');
const [biz, otherBiz, owner, otherOwner, seat, inactiveSeat, errand, otherErrand, secret] = Array.from({length: 9}, (_,n) => id(n+1));
await db.query('INSERT INTO businesses VALUES($1,$2),($3,$4)', [biz,owner,otherBiz,otherOwner]);
await db.query("INSERT INTO business_users VALUES($1,$2,'active'),($1,$3,'revoked')", [biz,seat,inactiveSeat]);
const insertErrand = (eid, bid, uid, key='same-day-key') => db.query(`INSERT INTO chief_errands
  (id,business_id,user_id,kind,title,plan,hosts,spend_limit_cents,idempotency_key)
  VALUES($1,$2,$3,'reorder','Fixture errand','{}',ARRAY['supplier.example'],15000,$4)`, [eid,bid,uid,key]);
await insertErrand(errand,biz,owner);
await insertErrand(otherErrand,otherBiz,otherOwner);
await db.query("INSERT INTO chief_errand_events(errand_id,business_id,n,kind) VALUES($1,$2,1,'note'),($3,$4,1,'note')", [errand,biz,otherErrand,otherBiz]);
await db.query("INSERT INTO business_secrets(id,business_id,kind,host,label,fields_ciphertext,created_by) VALUES($1,$2,'login','supplier.example','Fixture','encrypted-fixture',$3)", [secret,biz,owner]);
const refuses = async (fn, pattern) => {
  await db.exec('SAVEPOINT refusal');
  await assert.rejects(fn, pattern);
  await db.exec('ROLLBACK TO SAVEPOINT refusal; RELEASE SAVEPOINT refusal');
};
await refuses(() => insertErrand(id(40),biz,owner), /duplicate key/);
await refuses(() => db.query("INSERT INTO chief_errand_events(errand_id,business_id,n,kind) VALUES($1,$2,2,'note')", [errand,otherBiz]), /foreign key/);
await refuses(() => db.query("INSERT INTO chief_errand_events(errand_id,business_id,n,kind) VALUES($1,$2,1,'note')", [errand,biz]), /duplicate key/);
await refuses(() => db.query("UPDATE chief_errands SET status='invented' WHERE id=$1", [errand]), /check constraint/);
await refuses(() => db.query("UPDATE chief_errands SET planned_total_cents=-1 WHERE id=$1", [errand]), /check constraint/);
await refuses(() => db.query("UPDATE business_secrets SET kind='card' WHERE id=$1", [secret]), /check constraint/);

const as = async (uid, role='authenticated') => {
  await db.exec('RESET ROLE');
  await db.query("SELECT set_config('request.jwt.claim.sub',$1,true)", [uid || '']);
  await db.exec(`SET LOCAL ROLE ${role}`);
};
for (const uid of [owner, seat]) {
  await as(uid);
  assert.deepEqual((await db.query('SELECT id FROM chief_errands')).rows.map(r=>r.id), [errand]);
  assert.equal((await db.query('SELECT * FROM chief_errand_events')).rows.length, 1);
  await refuses(() => db.query('SELECT fields_ciphertext FROM business_secrets'), /permission denied/);
  await refuses(() => db.query("UPDATE chief_errands SET status='approved'"), /permission denied/);
  await refuses(() => db.query('DELETE FROM chief_errand_events'), /permission denied/);
  await refuses(() => insertErrand(id(41),biz,owner,'new-key'), /permission denied/);
}
await as(otherOwner);
assert.deepEqual((await db.query('SELECT id FROM chief_errands')).rows.map(r=>r.id), [otherErrand]);
await as(inactiveSeat);
assert.equal((await db.query('SELECT id FROM chief_errands')).rows.length, 0);
assert.equal((await db.query('SELECT id FROM chief_errand_events')).rows.length, 0);
await as(null,'anon');
for (const table of tableNames) await refuses(() => db.query(`SELECT * FROM ${table}`), /permission denied/);
await as(null,'service_role');
assert.equal((await db.query('SELECT fields_ciphertext FROM business_secrets')).rows.length, 1);
await db.query("UPDATE chief_errands SET status='interrupted' WHERE id=$1", [errand]);
await insertErrand(id(42),biz,owner);
await db.exec('RESET ROLE');
// RLS is an independent backstop even if a later grant is mistakenly widened.
await db.exec('GRANT SELECT ON business_secrets TO authenticated');
await as(owner);
assert.equal((await db.query('SELECT fields_ciphertext FROM business_secrets')).rows.length, 0);
await db.exec('RESET ROLE');
await db.query('DELETE FROM businesses WHERE id=$1',[biz]);
assert.equal((await db.query('SELECT id FROM business_secrets')).rows.length, 0);
assert.equal((await db.query('SELECT id FROM chief_errand_events')).rows.length, 1);
await db.exec('ROLLBACK');
for (const table of tableNames) assert.equal((await db.query(`SELECT * FROM ${table}`)).rows.length, 0);
await db.exec(migration);
await db.close();
console.log('Chief computer SQL passed: repeat application, rollback, owner/seat isolation, vault denial, write denial, dedupe, tenant event guard and erasure cascade.');

// Real PostgreSQL lease/CAS and permission tests; synthetic data only.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {PGlite} = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db = new PGlite();
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
const migration = readFileSync('supabase/APPLY-2026-09-12-chief-link-pilot.sql', 'utf8');
await db.exec(migration);
await db.exec(migration);
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
await db.query('INSERT INTO businesses VALUES($1),($2)', [id(1), id(2)]);
await db.query('INSERT INTO auth.users VALUES($1),($2)', [id(3), id(4)]);
const rpc = async (fn, args) => (await db.query(`SELECT ${fn}(${args.map((_, i) => '$' + (i + 1)).join(',')}) AS value`, args)).rows[0].value;
const a = [id(1), id(3), id(5)];
assert.equal((await rpc('chief_link_pilot_acquire', a)).acquired, true);
assert.equal((await rpc('chief_link_pilot_acquire', [id(1), id(3), id(6)])).acquired, false);
assert.equal(await rpc('chief_link_pilot_save', [...a, 'encrypted-fixture']), true);
assert.equal(await rpc('chief_link_pilot_save', [id(2), id(3), id(5), 'cross-business']), false);
assert.equal(await rpc('chief_link_pilot_save', [id(1), id(4), id(5), 'cross-user']), false);
await db.query("UPDATE chief_link_pilot_sessions SET lease_until=clock_timestamp()-interval '1 second'");
assert.equal(await rpc('chief_link_pilot_save', [...a, 'expired-write']), false);
const b = [id(1), id(3), id(6)];
assert.equal((await rpc('chief_link_pilot_acquire', b)).encrypted_state, 'encrypted-fixture');
assert.equal(await rpc('chief_link_pilot_release', a), false);
assert.equal(await rpc('chief_link_pilot_save', [...a, 'stale-write']), false);
assert.equal(await rpc('chief_link_pilot_save', [...b, 'new-state']), true);
assert.equal(await rpc('chief_link_pilot_release', b), true);
for (const role of ['anon', 'authenticated']) {
  const values = (await db.query(`SELECT
    has_table_privilege($1,'public.chief_link_pilot_sessions','SELECT') AS readable,
    has_function_privilege($1,'public.chief_link_pilot_acquire(uuid,uuid,uuid)','EXECUTE') AS callable`, [role])).rows[0];
  assert.equal(values.readable, false);
  assert.equal(values.callable, false);
}
await db.exec('SET ROLE service_role');
assert.equal((await rpc('chief_link_pilot_acquire', a)).acquired, true);
await db.close();
console.log('Link pilot: migration rerun, tenant isolation, lease expiry, stale writers and service-only access passed.');

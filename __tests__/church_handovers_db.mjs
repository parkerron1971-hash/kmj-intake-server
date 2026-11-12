// From the office, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-12-church-handovers.sql. Running it twice changes
// nothing; a hand-over's person and department are its own church's; the
// title, note and link keep their shapes (https only); the table is
// server-only; a login deleted leaves the row (sent by the church office), a
// department deleted leaves it, and a person or a church deleted takes it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_handovers_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const u1 = 'aaaaaaaa-1111-4111-8111-111111111111';
const c1 = 'cccccccc-1111-4111-8111-111111111111';
const c2 = 'cccccccc-2222-4222-8222-222222222222';
const c3 = 'cccccccc-3333-4333-8333-333333333333';
const d1 = 'dddddddd-1111-4111-8111-111111111111';
const d2 = 'dddddddd-2222-4222-8222-222222222222';
// What Supabase already has: the roles, auth.users, businesses, contacts and
// the map's departments.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid REFERENCES public.businesses(id) ON DELETE CASCADE);
  CREATE TABLE public.church_departments(id uuid PRIMARY KEY, business_id uuid, name text);`);
await db.query('INSERT INTO businesses VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO auth.users VALUES ($1)', [u1]);
await db.query('INSERT INTO contacts VALUES ($1, $2), ($3, $4), ($5, $2)', [c1, b1, c2, b2, c3]);
await db.query(`INSERT INTO church_departments VALUES ($1, $2, 'Youth'), ($3, $4, 'Youth')`, [d1, b1, d2, b2]);

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const ok = async (text, args) => { await db.query(text, args); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const send = `INSERT INTO church_handovers(business_id, contact_id, sent_by, title, note, link, department_id)
  VALUES ($1, $2, $3, $4, $5, $6, $7)`;

const sql = await readFile(new URL('../supabase/APPLY-2026-11-12-church-handovers.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);                       // twice: nothing changes, nothing fails
checks++;

// One for a leader of this church, for one of its departments.
await ok(send, [b1, c1, u1, 'Room keys for the lock-in', 'At the front desk.', 'https://example.org/keys', d1]);
const row = await one(`SELECT seen_at, told_at, created_at IS NOT NULL AS stamped FROM church_handovers`);
assert.deepEqual(row, { seen_at: null, told_at: null, stamped: true }); checks++;

// The person and the department are its own church's, on insert and update.
await refuses(send, [b1, c2, u1, 'x', null, null, null], /not in this church/);
await refuses(send, [b1, c1, u1, 'x', null, null, d2], /department is not in this church/);
await refuses(`UPDATE church_handovers SET contact_id = $1`, [c2], /not in this church/);
await refuses(`UPDATE church_handovers SET department_id = $1`, [d2], /department is not in this church/);

// Shapes: a title, never empty, 140 at most; a note 1000; a link https only.
await refuses(send, [b1, c1, u1, '   ', null, null, null], /check constraint/);
await refuses(send, [b1, c1, u1, 'a'.repeat(141), null, null, null], /check constraint/);
await ok(send, [b1, c1, u1, 'a'.repeat(140), 'n'.repeat(1000), null, null]);
await refuses(send, [b1, c1, u1, 'x', 'n'.repeat(1001), null, null], /check constraint/);
for (const bad of ['http://example.org', 'javascript:alert(1)', 'https://exa mple.org', 'https://' + 'a'.repeat(500)]) {
  await refuses(send, [b1, c1, u1, 'x', null, bad, null], /check constraint/);
}

// Server-only: RLS on, no policies, and neither browser role reads or writes it.
const rls = await one(`SELECT relrowsecurity FROM pg_class WHERE oid = 'public.church_handovers'::regclass`);
assert.equal(rls.relrowsecurity, true); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_policies WHERE tablename = 'church_handovers'`)).n, 0); checks++;
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM church_handovers', [], /permission denied/);
  await refuses(send, [b1, c1, u1, 'x', null, null, null], /permission denied/);
  await db.exec('RESET ROLE');
}
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_indexes WHERE indexname IN
  ('church_handovers_for', 'church_handovers_sent', 'church_handovers_untold')`)).n, 3); checks++;

// A login deleted leaves the row, sent by the church office; a department
// deleted leaves it; the person, or the church, takes it.
await ok('DELETE FROM auth.users WHERE id = $1', [u1]);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_handovers WHERE sent_by IS NULL`)).n, 2); checks++;
await ok('DELETE FROM church_departments WHERE id = $1', [d1]);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_handovers WHERE department_id IS NULL`)).n, 2); checks++;
await ok(send, [b1, c3, null, 'For Ruth', null, null, null]);
await ok('DELETE FROM contacts WHERE id = $1', [c1]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_handovers')).n, 1); checks++;
await ok('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_handovers')).n, 0); checks++;

console.log(`church handovers db: ${checks} checks passed`);

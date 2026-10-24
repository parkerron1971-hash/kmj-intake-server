// ChurchSavvy Planning, the member's side, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-23-serving-member.sql over APPLY-2026-10-23-sunday-planning.sql.
// How often a member would like to serve is one row each, one of three
// wishes, and only a person of that church; someone asked to cover a Sunday
// is a person of that church too, and a person who leaves stops being
// asked (the Sunday stays with whoever said yes); the browser's roles can't
// read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/serving_member_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const team = '33333333-3333-4333-8333-333333333333';
const kendra = '66666666-6666-4666-8666-666666666666';
const ty = '77777777-7777-4777-8777-777777777777';
const outsider = '88888888-8888-4888-8888-888888888888';
const sunday = '99999999-9999-4999-8999-999999999999';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.groups(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE,
    kind text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.worship_services(id uuid PRIMARY KEY,
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query(`INSERT INTO groups(id, business_id, kind) VALUES ($1, $2, 'team')`, [team, b1]);
await db.query('INSERT INTO contacts(id, business_id) VALUES ($1, $3), ($2, $3), ($4, $5)', [kendra, ty, b1, outsider, b2]);
await db.query('INSERT INTO worship_services(id, business_id) VALUES ($1, $2)', [sunday, b1]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const one = async (text, args = []) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
await db.exec(await sql('APPLY-2026-10-23-serving-member.sql'));
await db.exec(await sql('APPLY-2026-10-23-serving-member.sql'));   // idempotent

// How often: one wish each, one of three, this church's people only.
const pref = 'INSERT INTO serve_prefs(business_id, contact_id, often) VALUES ($1, $2, $3)';
await db.query(pref, [b1, kendra, 'two']); checks++;
await refuses(pref, [b1, kendra, 'one'], /duplicate key|unique/);
await refuses(pref, [b1, ty, 'always'], /check constraint/);
await refuses(pref, [b1, outsider, 'one'], /not in this business/);

// The office's tables still hold their rules under the new trigger.
await db.query('INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2)', [team, b1]);
const place = await one(`INSERT INTO serve_positions(business_id, group_id, name) VALUES ($1, $2, 'Sound') RETURNING id`, [b1, team]);
const a = await one(`INSERT INTO serve_assignments(business_id, service_id, position_id, contact_id, status)
  VALUES ($1, $2, $3, $4, 'yes') RETURNING *`, [b1, sunday, place.id, kendra]);
assert.equal(a.swap_to, null); checks++;
await refuses(`INSERT INTO serve_assignments(business_id, service_id, position_id, contact_id) VALUES ($1, $2, $3, $4)`,
  [b1, sunday, place.id, outsider], /not in this business/);

// A cover: this church's people only; they stay asked until they answer.
await refuses('UPDATE serve_assignments SET swap_to = $2, swap_asked_at = now() WHERE id = $1', [a.id, outsider], /not in this business/);
await db.query('UPDATE serve_assignments SET swap_to = $2, swap_asked_at = now() WHERE id = $1', [a.id, ty]);
assert.equal((await one('SELECT swap_to FROM serve_assignments WHERE id = $1', [a.id])).swap_to, ty); checks++;
// Ty leaves the church: nobody's asked to cover, and Kendra is still on.
await db.query('DELETE FROM contacts WHERE id = $1', [ty]);
const after = await one('SELECT contact_id, status, swap_to FROM serve_assignments WHERE id = $1', [a.id]);
assert.deepEqual([after.contact_id, after.status, after.swap_to], [kendra, 'yes', null]); checks++;

// A church that leaves takes the wishes with it.
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await one('SELECT count(*)::int AS n FROM serve_prefs')).n, 0); checks++;

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM serve_prefs', [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`serving_member: ${checks} checks passed`);

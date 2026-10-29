// ChurchSavvy Planning, step 5 (the Sunday pack: "I'm here"), on a real
// Postgres (PGlite): supabase/APPLY-2026-10-24-serve-here.sql over the office's
// migration. An arrival starts empty, is marked once by a guarded update, and
// the browser's roles still can't read it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/serve_here_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const team = '33333333-3333-4333-8333-333333333333';
const kendra = '66666666-6666-4666-8666-666666666666';
const sunday = '99999999-9999-4999-8999-999999999999';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.groups(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE,
    kind text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.worship_services(id uuid PRIMARY KEY,
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await db.query(`INSERT INTO groups(id, business_id, kind) VALUES ($1, $2, 'team')`, [team, b1]);
await db.query('INSERT INTO contacts(id, business_id) VALUES ($1, $2)', [kendra, b1]);
await db.query('INSERT INTO worship_services(id, business_id) VALUES ($1, $2)', [sunday, b1]);
let checks = 0;
const one = async (text, args = []) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
await db.exec(await sql('APPLY-2026-10-24-serve-here.sql'));
await db.exec(await sql('APPLY-2026-10-24-serve-here.sql'));   // idempotent

await db.query('INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2)', [team, b1]);
const place = await one(`INSERT INTO serve_positions(business_id, group_id, name) VALUES ($1, $2, 'Sound') RETURNING id`, [b1, team]);
const a = await one(`INSERT INTO serve_assignments(business_id, service_id, position_id, contact_id, status)
  VALUES ($1, $2, $3, $4, 'yes') RETURNING *`, [b1, sunday, place.id, kendra]);
assert.equal(a.here_at, null); checks++;
// "I'm here" once: the second tap finds nothing to mark.
const tap = `UPDATE serve_assignments SET here_at = now() WHERE id = $1 AND status = 'yes' AND here_at IS NULL RETURNING id`;
assert.equal((await db.query(tap, [a.id])).rows.length, 1); checks++;
assert.equal((await db.query(tap, [a.id])).rows.length, 0); checks++;
assert.ok((await one('SELECT here_at FROM serve_assignments WHERE id = $1', [a.id])).here_at); checks++;

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await assert.rejects(db.query('SELECT here_at FROM serve_assignments', []), /permission denied/); checks++;
  await db.exec('RESET ROLE');
}

console.log(`serve_here: ${checks} checks passed`);

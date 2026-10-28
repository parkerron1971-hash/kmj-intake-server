// ChurchSavvy Planning, step 4 (one order of service for every team), on a
// real Postgres (PGlite): supabase/APPLY-2026-10-24-serve-notes.sql over the
// office's migration. One note per item per team (or for everyone), short,
// for that church's service and one of its Sunday teams; it goes when the
// service or the church goes; the browser's roles can't read or write it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/serve_notes_db.mjs
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
const notTeam = '44444444-4444-4444-8444-444444444444';
const theirs = '55555555-5555-4555-8555-555555555555';
const sunday = '99999999-9999-4999-8999-999999999999';
const elsewhere = '99999999-9999-4999-8999-999999999998';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.groups(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE,
    kind text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.worship_services(id uuid PRIMARY KEY,
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query(`INSERT INTO groups(id, business_id, kind) VALUES ($1, $3, 'team'), ($2, $3, 'team'), ($4, $5, 'team')`,
  [team, notTeam, b1, theirs, b2]);
await db.query('INSERT INTO worship_services(id, business_id) VALUES ($1, $2), ($3, $4)', [sunday, b1, elsewhere, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const one = async (text, args = []) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
await db.exec(await sql('APPLY-2026-10-24-serve-notes.sql'));
await db.exec(await sql('APPLY-2026-10-24-serve-notes.sql'));   // idempotent
await db.query('INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2), ($3, $4)', [team, b1, theirs, b2]);

const add = 'INSERT INTO serve_notes(business_id, service_id, item_id, team, note) VALUES ($1, $2, $3, $4, $5)';
await db.query(add, [b1, sunday, 'ff', team, 'Bridge twice, then a soft chorus']); checks++;
await db.query(add, [b1, sunday, 'ff', 'all', 'Everyone serving today']); checks++;
// One note per item per team.
await refuses(add, [b1, sunday, 'ff', team, 'Again'], /duplicate key|unique/);
// Short, never empty, a plan item's id, a team id or "all".
await refuses(add, [b1, sunday, 'gj', team, ''], /check constraint/);
await refuses(add, [b1, sunday, 'gj', team, 'x'.repeat(301)], /check constraint/);
await refuses(add, [b1, sunday, 'Not An Id!', team, 'x'], /check constraint/);
await refuses(add, [b1, sunday, 'gj', 'everyone', 'x'], /team is not in this business|check constraint/);
// That church's service, and one of its Sunday teams.
await refuses(add, [b1, elsewhere, 'gj', 'all', 'x'], /service is not in this business/);
await refuses(add, [b1, sunday, 'gj', notTeam, 'x'], /team is not in this business/);
await refuses(add, [b1, sunday, 'gj', theirs, 'x'], /team is not in this business/);
await refuses('UPDATE serve_notes SET team = $1 WHERE item_id = $2 AND team = $3', [theirs, 'ff', team], /team is not in this business/);

// A service that goes takes its notes; so does a church.
await db.query('INSERT INTO worship_services(id, business_id) VALUES ($1, $2)', ['99999999-9999-4999-8999-999999999997', b1]);
await db.query(add, [b1, '99999999-9999-4999-8999-999999999997', 'ff', 'all', 'Next week']);
await db.query('DELETE FROM worship_services WHERE id = $1', ['99999999-9999-4999-8999-999999999997']);
assert.equal((await one('SELECT count(*)::int AS n FROM serve_notes')).n, 2); checks++;
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await one('SELECT count(*)::int AS n FROM serve_notes')).n, 0); checks++;

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM serve_notes', [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`serve_notes: ${checks} checks passed`);

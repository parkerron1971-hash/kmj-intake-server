// ChurchSavvy Planning, step 3 (asks and reminders reach people), on a real
// Postgres (PGlite): supabase/APPLY-2026-10-24-serving-alerts.sql over the
// office's and the member side's migrations. The email copy is on unless a
// member turned it off; a member can set How I hear before saying how often;
// each reminder is its own mark, empty until it's said; the one-church rule
// and the browser's roles still hold.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/serving_alerts_db.mjs
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
const jo = '77777777-7777-4777-8777-777777777777';
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
await db.query('INSERT INTO contacts(id, business_id) VALUES ($1, $3), ($2, $3), ($4, $5)', [kendra, jo, b1, outsider, b2]);
await db.query('INSERT INTO worship_services(id, business_id) VALUES ($1, $2)', [sunday, b1]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const one = async (text, args = []) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
await db.exec(await sql('APPLY-2026-10-23-serving-member.sql'));
await db.exec(await sql('APPLY-2026-10-24-serving-alerts.sql'));
await db.exec(await sql('APPLY-2026-10-24-serving-alerts.sql'));   // idempotent

// How I hear before how often: the wish can wait; the email copy is on.
await db.query('INSERT INTO serve_prefs(business_id, contact_id, email) VALUES ($1, $2, false)', [b1, kendra]);
await db.query('INSERT INTO serve_prefs(business_id, contact_id, often) VALUES ($1, $2, $3)', [b1, jo, 'two']);
const k = await one('SELECT often, email FROM serve_prefs WHERE contact_id = $1', [kendra]);
const j = await one('SELECT often, email FROM serve_prefs WHERE contact_id = $1', [jo]);
assert.deepEqual([k.often, k.email, j.often, j.email], [null, false, 'two', true]); checks++;
// A wish is still one of three; the email copy is never left unknown.
await refuses('UPDATE serve_prefs SET often = $2 WHERE contact_id = $1', [jo, 'always'], /check constraint/);
await refuses('UPDATE serve_prefs SET email = null WHERE contact_id = $1', [jo], /null value|not-null/);
await refuses('INSERT INTO serve_prefs(business_id, contact_id, email) VALUES ($1, $2, true)', [b1, outsider], /not in this business/);

// Each reminder is its own mark, empty until it's said.
await db.query('INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2)', [team, b1]);
const place = await one(`INSERT INTO serve_positions(business_id, group_id, name) VALUES ($1, $2, 'Sound') RETURNING id`, [b1, team]);
const a = await one(`INSERT INTO serve_assignments(business_id, service_id, position_id, contact_id, status)
  VALUES ($1, $2, $3, $4, 'yes') RETURNING *`, [b1, sunday, place.id, kendra]);
assert.deepEqual([a.leader_told_at, a.week_sent_at, a.day_sent_at, a.morning_sent_at, a.swap_told_at],
  [null, null, null, null, null]); checks++;
// A claim is a guarded update: the second one finds nothing to mark.
const claim = 'UPDATE serve_assignments SET day_sent_at = now() WHERE id = $1 AND day_sent_at IS NULL RETURNING id';
assert.equal((await db.query(claim, [a.id])).rows.length, 1); checks++;
assert.equal((await db.query(claim, [a.id])).rows.length, 0); checks++;
// The sweep's index is there.
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_indexes WHERE indexname = 'serve_assignments_to_remind'`)).n, 1); checks++;
// The one-church rule still holds on the reminder table.
await refuses('UPDATE serve_assignments SET swap_to = $2, swap_told_at = now() WHERE id = $1', [a.id, outsider], /not in this business/);

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT email FROM serve_prefs', [], /permission denied/);
  await refuses('SELECT week_sent_at FROM serve_assignments', [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`serving_alerts: ${checks} checks passed`);

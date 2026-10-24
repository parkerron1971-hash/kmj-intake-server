// ChurchSavvy Planning by email ("Stop these emails"), on a real Postgres
// (PGlite): supabase/APPLY-2026-10-24-serve-email-stop.sql over the serving
// migrations. A stop is recorded with the email copy off, the upsert the
// server uses keeps one row per person, turning the copy back on clears the
// stop, and the browser's roles still can't read it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/serve_email_stop_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const kendra = '66666666-6666-4666-8666-666666666666';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.groups(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE,
    kind text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.worship_services(id uuid PRIMARY KEY,
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await db.query('INSERT INTO contacts(id, business_id) VALUES ($1, $2)', [kendra, b1]);
let checks = 0;
const one = async (text, args = []) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
await db.exec(await sql('APPLY-2026-10-23-serving-member.sql'));
await db.exec(await sql('APPLY-2026-10-24-serving-alerts.sql'));
await db.exec(await sql('APPLY-2026-10-24-serve-email-stop.sql'));
await db.exec(await sql('APPLY-2026-10-24-serve-email-stop.sql'));   // idempotent

// The server's upsert (sunday_serving._save_prefs): on_conflict business_id,contact_id.
const save = (fields) => db.query(
  `INSERT INTO serve_prefs(business_id, contact_id, email, email_stopped_at) VALUES ($1, $2, $3, $4)
   ON CONFLICT (business_id, contact_id) DO UPDATE SET email = excluded.email, email_stopped_at = excluded.email_stopped_at
   RETURNING *`, [b1, kendra, fields.email, fields.stopped ?? null]);
const stopped = (await save({ email: false, stopped: new Date().toISOString() })).rows[0];
assert.equal(stopped.email, false); checks++;
assert.ok(stopped.email_stopped_at); checks++;
const back = (await save({ email: true, stopped: null })).rows[0];
assert.equal(back.email, true); checks++;
assert.equal(back.email_stopped_at, null); checks++;
assert.equal((await one('SELECT count(*)::int AS n FROM serve_prefs')).n, 1); checks++;
// Someone from no church can't be stopped into existence.
await assert.rejects(db.query(`INSERT INTO serve_prefs(business_id, contact_id, email_stopped_at)
  VALUES ($1, '77777777-7777-4777-8777-777777777777', now())`, [b1])); checks++;

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await assert.rejects(db.query('SELECT email_stopped_at FROM serve_prefs', []), /permission denied/); checks++;
  await db.exec('RESET ROLE');
}

console.log(`serve_email_stop: ${checks} checks passed`);

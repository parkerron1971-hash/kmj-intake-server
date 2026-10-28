// A group that gathers once a month, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-monthly.sql (after the every-other-week
// one). Every week, every other week or once a month, nothing else; which
// one in the month is 1-4 or 5 for the last. Applied twice (it is
// idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_monthly_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-every-other-week.sql'));
const g = (await db.query(`INSERT INTO groups(business_id, name, meet_every) VALUES ($1,'Sisters',2) RETURNING id`, [b1])).rows[0].id;
await db.exec(await sql('APPLY-2026-10-20-group-monthly.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-monthly.sql'));   // twice

assert.equal((await db.query('SELECT meet_every FROM groups WHERE id=$1', [g])).rows[0].meet_every, 2); checks++;   // kept
await db.query(`UPDATE groups SET meet_every = 4, meet_nth = 5 WHERE id=$1`, [g]); checks++;
await refuses(`UPDATE groups SET meet_every = 3 WHERE id=$1`, [g], /check constraint/);
await refuses(`UPDATE groups SET meet_nth = 6 WHERE id=$1`, [g], /check constraint/);
await refuses(`UPDATE groups SET meet_nth = 0 WHERE id=$1`, [g], /check constraint/);

console.log(`group monthly db: ${checks} checks passed`);

// A group that gathers every other week, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-every-other-week.sql. Groups that were
// already there gather every week; it's every week or every other week,
// nothing else; the week it counts from is a date. Applied twice (it is
// idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_every_db.mjs
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
const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Sisters') RETURNING id`, [b1])).rows[0].id;
await db.exec(await sql('APPLY-2026-10-20-group-every-other-week.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-every-other-week.sql'));   // twice

const row = (await db.query('SELECT meet_every, meet_from FROM groups WHERE id=$1', [g])).rows[0];
assert.deepEqual([row.meet_every, row.meet_from], [1, null]); checks++;          // every week, as before
await db.query(`UPDATE groups SET meet_every = 2, meet_from = '2026-10-22' WHERE id=$1`, [g]); checks++;
await refuses(`UPDATE groups SET meet_every = 3 WHERE id=$1`, [g], /check constraint/);
await refuses(`UPDATE groups SET meet_every = NULL WHERE id=$1`, [g], /null value|not-null/);
await refuses(`UPDATE groups SET meet_from = 'next thursday' WHERE id=$1`, [g], /invalid input syntax/);

console.log(`group every db: ${checks} checks passed`);

// A word from the office to every group or to its leaders, on a real
// Postgres (PGlite): supabase/APPLY-2026-10-20-group-word.sql. A post with no
// group and no author is allowed (from the pastors); who it's for is every
// group unless it says the leaders; nothing else. Applied twice (it is
// idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_word_db.mjs
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
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text,
    birthdate date);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_manager(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-space.sql'));
const old = (await db.query(`INSERT INTO group_posts(business_id, body) VALUES ($1,'Before') RETURNING id`, [b1])).rows[0].id;
await db.exec(await sql('APPLY-2026-10-20-group-word.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-word.sql'));   // twice

// What was posted before is for every group.
assert.equal((await db.query('SELECT audience FROM group_posts WHERE id=$1', [old])).rows[0].audience, 'all'); checks++;
// From the pastors: no group, no author, to the leaders.
const w = (await db.query(`INSERT INTO group_posts(business_id, group_id, posted_by, body, audience)
  VALUES ($1, NULL, NULL, 'Leaders, a word', 'leaders') RETURNING audience`, [b1])).rows[0];
assert.equal(w.audience, 'leaders'); checks++;
await refuses(`INSERT INTO group_posts(business_id, body, audience) VALUES ($1,'x','everyone')`, [b1], /check constraint/);
await refuses(`INSERT INTO group_posts(business_id, body, audience) VALUES ($1,'x',NULL)`, [b1], /null value|not-null/);

console.log(`group word db: ${checks} checks passed`);

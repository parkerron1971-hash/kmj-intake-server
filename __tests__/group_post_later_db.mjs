// A Board post that goes out later, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-post-later.sql. Posts already there went
// out when written (no time, no told mark); a scheduled one is found by the
// job's index only while it's waiting. Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_post_later_db.mjs
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

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-space.sql'));
const old = (await db.query(`INSERT INTO group_posts(business_id, body) VALUES ($1,'Before') RETURNING id`, [b1])).rows[0].id;
await db.exec(await sql('APPLY-2026-10-20-group-post-later.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-post-later.sql'));   // twice

const was = (await db.query('SELECT publish_at, told_at FROM group_posts WHERE id=$1', [old])).rows[0];
assert.deepEqual([was.publish_at, was.told_at], [null, null]); checks++;          // went out when written

await db.query(`INSERT INTO group_posts(business_id, body, publish_at) VALUES ($1,'Later', now() + interval '1 day')`, [b1]); checks++;
const ix = (await db.query(`SELECT indexdef FROM pg_indexes WHERE indexname = 'group_posts_due'`)).rows[0];
assert.match(ix.indexdef, /publish_at IS NOT NULL/); assert.match(ix.indexdef, /told_at IS NULL/); assert.match(ix.indexdef, /removed_at IS NULL/); checks++;

console.log(`group post later db: ${checks} checks passed`);

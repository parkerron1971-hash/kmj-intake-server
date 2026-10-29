// Safety officers from a church's pastoral leaders, on a real Postgres
// (PGlite): supabase/APPLY-2026-10-20-member-safety-officers.sql. A member
// officer must be this church's own person; a logged look at a whole chat
// names a team login OR a member officer, never neither, and never another
// church's person. Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/member_safety_officers_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const elder = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', ana = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', login = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text,
    birthdate date);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_manager(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts(id, business_id, name) VALUES ($1,$2,$3),($4,$2,$5),($6,$7,$8)',
  [elder, b1, 'Ray Dunn', ana, 'Ana Rivers', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-02-messaging.sql'));
await db.exec(await sql('APPLY-2026-10-20-member-safety-officers.sql'));
await db.exec(await sql('APPLY-2026-10-20-member-safety-officers.sql'));   // twice

const name = `INSERT INTO msg_member_officers(business_id, contact_id) VALUES ($1,$2)`;
await db.query(name, [b1, elder]); checks++;
await refuses(name, [b1, elsewhere], /That person is not in this business/);
await refuses(name, [b1, elder], /duplicate key|unique/);

const thread = (await db.query(`INSERT INTO msg_threads(business_id, kind, direct_key) VALUES ($1,'direct',$2) RETURNING id`,
  [b1, `${ana}:${elder}`])).rows[0].id;
const look = `INSERT INTO msg_staff_views(business_id, thread_id, user_id, contact_id, reason) VALUES ($1,$2,$3,$4,$5)`;
await db.query(look, [b1, thread, null, elder, 'A report about this chat']); checks++;   // a member officer
await db.query(look, [b1, thread, login, null, 'A report']); checks++;                   // a team login, as before
await refuses(look, [b1, thread, null, null, 'Nobody'], /msg_staff_views_who|check constraint/);
await refuses(look, [b1, thread, null, elsewhere, 'Another church'], /That person is not in this business/);

console.log(`member safety officers db: ${checks} checks passed`);

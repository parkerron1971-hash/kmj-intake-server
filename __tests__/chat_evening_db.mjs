// How each person hears about a group's chat, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-chat-evening.sql. Everyone who was already in a
// chat keeps a note for every message; the choice is one of three; the
// evening note's mark starts empty. Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/chat_evening_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const ana = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', ben = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
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
await db.query('INSERT INTO contacts(id, business_id, name) VALUES ($1,$2,$3),($4,$2,$5)', [ana, b1, 'Ana Rivers', ben, 'Ben Cole']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-02-messaging.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-chat.sql'));
const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Sisters') RETURNING id`, [b1])).rows[0].id;
const t = (await db.query(`INSERT INTO msg_threads(business_id, kind, group_id) VALUES ($1,'group',$2) RETURNING id`, [b1, g])).rows[0].id;
await db.query(`INSERT INTO msg_participants(thread_id, contact_id, business_id) VALUES ($1,$2,$3)`, [t, ana, b1]);   // before

await db.exec(await sql('APPLY-2026-10-20-chat-evening.sql'));
await db.exec(await sql('APPLY-2026-10-20-chat-evening.sql'));   // twice

// Someone already in a chat keeps a note for every message.
const before = (await db.query('SELECT notify, summed_at FROM msg_participants WHERE contact_id=$1', [ana])).rows[0];
assert.deepEqual([before.notify, before.summed_at], ['every', null]); checks++;

// One of three.
await db.query(`INSERT INTO msg_participants(thread_id, contact_id, business_id, notify) VALUES ($1,$2,$3,'evening')`, [t, ben, b1]); checks++;
await db.query(`UPDATE msg_participants SET notify = 'replies' WHERE contact_id=$1`, [ana]); checks++;
await refuses(`UPDATE msg_participants SET notify = 'loud' WHERE contact_id=$1`, [ana], /check constraint/);
await refuses(`UPDATE msg_participants SET notify = NULL WHERE contact_id=$1`, [ana], /null value|not-null/);

// The evening note keeps its mark.
await db.query(`UPDATE msg_participants SET summed_at = now() WHERE contact_id=$1`, [ben]);
assert.ok((await db.query('SELECT summed_at FROM msg_participants WHERE contact_id=$1', [ben])).rows[0].summed_at); checks++;

// The 7 PM sweep's index exists, for the evening people only.
const ix = (await db.query(`SELECT indexdef FROM pg_indexes WHERE indexname = 'msg_participants_evening'`)).rows[0];
assert.match(ix.indexdef, /WHERE \(notify = 'evening'::text\)/); checks++;

console.log(`chat evening db: ${checks} checks passed`);

// Photos in a group's chat, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-chat-photos.sql. A photo belongs to this
// church's own message, one per message; its file sits in that message's
// own chat's folder under this church; a sensible size; server-only; it
// goes with its message. Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/chat_photos_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const ana = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
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
await db.query('INSERT INTO contacts(id, business_id, name) VALUES ($1,$2,$3)', [ana, b1, 'Ana Rivers']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-02-messaging.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-chat.sql'));
await db.exec(await sql('APPLY-2026-10-20-chat-photos.sql'));
await db.exec(await sql('APPLY-2026-10-20-chat-photos.sql'));   // twice

const [g1, g2] = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Thursday'),($1,'Youth') RETURNING id`, [b1])).rows.map(r => r.id);
const thread = async g => (await db.query(`INSERT INTO msg_threads(business_id, kind, group_id) VALUES ($1,'group',$2) RETURNING id`, [b1, g])).rows[0].id;
const t1 = await thread(g1), t2 = await thread(g2);
const say = async (tid, body) => (await db.query(
  `INSERT INTO msg_messages(business_id, thread_id, sender_contact_id, body) VALUES ($1,$2,$3,$4) RETURNING id`,
  [b1, tid, ana, body])).rows[0].id;
const m1 = await say(t1, 'Photo'), m2 = await say(t1, 'From the pantry');

const add = `INSERT INTO msg_photos(message_id, business_id, path, width, height, captioned) VALUES ($1,$2,$3,$4,$5,$6)`;
const at = (tid, f = 'a1b2.webp') => `${b1}/chat-photos/${tid}/${f}`;
await db.query(add, [m1, b1, at(t1), 1600, 1200, false]); checks++;
await refuses(add, [m1, b1, at(t1, 'c3.webp'), 10, 10, false], /duplicate key|unique/);          // one per message
await refuses(add, [m2, b1, at(t2), 10, 10, true], /not in this chat's folder/);                  // another chat's folder
await refuses(add, [m2, b1, `${b2}/chat-photos/${t1}/x.webp`, 10, 10, true], /check constraint|not in this chat's folder/); // another church's folder
await refuses(add, [m2, b1, `${b1}/member-photos/${ana}/x.webp`, 10, 10, true], /check constraint|not in this chat's folder/);
await refuses(add, [m2, b1, at(t1, 'x.png'), 10, 10, true], /check constraint/);
await refuses(add, [m2, b1, at(t1), 0, 10, true], /check constraint/);
await refuses(add, [m2, b1, at(t1), 10, 4001, true], /check constraint/);
await refuses(add, [m2, b2, `${b2}/chat-photos/${t1}/x.webp`, 10, 10, true], /That message is not in this business/);
await db.query(add, [m2, b1, at(t1, 'd4.webp'), 800, 600, true]); checks++;
await refuses(`UPDATE msg_photos SET path=$2 WHERE message_id=$1`, [m2, at(t2)], /not in this chat's folder/);

const grants = (await db.query(`SELECT grantee FROM information_schema.role_table_grants
  WHERE table_name='msg_photos' AND grantee IN ('anon','authenticated')`)).rows;
assert.deepEqual(grants, []); checks++;

await db.query(`DELETE FROM msg_messages WHERE id=$1`, [m1]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM msg_photos')).rows[0].n, 1); checks++;

console.log(`chat photos db: ${checks} checks passed`);

// All group leaders, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-leaders-room.sql. A chat may now be a church's
// leaders' room: one per church, never tied to a group or a pair; group and
// direct chats keep their rules; messages and reactions work in the room.
// Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/leaders_room_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const b3 = '33333333-3333-4333-8333-333333333333';   // a church with no room yet
const ben = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', ray = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text,
    birthdate date);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_manager(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2),($3)', [b1, b2, b3]);
await db.query('INSERT INTO contacts(id, business_id, name) VALUES ($1,$2,$3),($4,$2,$5)', [ben, b1, 'Ben Cole', ray, 'Ray Dunn']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-02-messaging.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-chat.sql'));
await db.exec(await sql('APPLY-2026-10-20-leaders-room.sql'));
await db.exec(await sql('APPLY-2026-10-20-leaders-room.sql'));   // twice

const room = `INSERT INTO msg_threads(business_id, kind, group_id, direct_key) VALUES ($1,'leaders',$2,$3) RETURNING id`;
const r1 = (await db.query(room, [b1, null, null])).rows[0].id; checks++;
await refuses(room, [b1, null, null], /duplicate key|unique/);                        // one per church
(await db.query(room, [b2, null, null])); checks++;                                    // another church has its own
const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Thursday') RETURNING id`, [b1])).rows[0].id;
const g3 = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Elders') RETURNING id`, [b3])).rows[0].id;
// Never tied to a group or a pair (b3 has no room, so only the shape can refuse).
await refuses(room, [b3, g3, null], /msg_threads_check/);
await refuses(room, [b3, null, 'a:b'], /msg_threads_check/);
await refuses(`INSERT INTO msg_threads(business_id, kind) VALUES ($1,'everyone')`, [b3], /msg_threads_(kind_)?check/);

// Group and direct chats keep their rules.
await db.query(`INSERT INTO msg_threads(business_id, kind, group_id) VALUES ($1,'group',$2)`, [b1, g]); checks++;
await db.query(`INSERT INTO msg_threads(business_id, kind, direct_key) VALUES ($1,'direct','x:y')`, [b1]); checks++;
await refuses(`INSERT INTO msg_threads(business_id, kind) VALUES ($1,'group')`, [b1], /msg_threads_check|check constraint/);
await refuses(`INSERT INTO msg_threads(business_id, kind) VALUES ($1,'direct')`, [b1], /msg_threads_check|check constraint/);

// The room is a chat like any other: messages, replies, reactions.
const say = (body, reply) => db.query(
  `INSERT INTO msg_messages(business_id, thread_id, sender_contact_id, body, reply_to) VALUES ($1,$2,$3,$4,$5) RETURNING id`,
  [b1, r1, ray, body, reply || null]);
const m1 = (await say('Thank you for shepherding')).rows[0].id; checks++;
await say('Amen', m1); checks++;
await db.query(`INSERT INTO msg_reactions(message_id, contact_id, business_id, kind) VALUES ($1,$2,$3,'pray')`, [m1, ben, b1]); checks++;

console.log(`leaders room db: ${checks} checks passed`);

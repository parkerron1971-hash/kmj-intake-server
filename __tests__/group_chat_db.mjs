// A group's chat inside the group, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-chat.sql. A reaction is Love, Praying or
// Amen, one of each per person, on this church's own message by this
// church's own person; a reply quotes a message in the SAME chat; the
// office's chat switches default to on / everyone writes. Applied twice (it
// is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_chat_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const ana = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', ben = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
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
  [ana, b1, 'Ana Rivers', ben, 'Ben Cole', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-02-messaging.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-chat.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-chat.sql'));   // twice

// An existing group reads as chat on, everyone writes; the office's choices hold.
const [g1, g2] = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Thursday'),($1,'Youth') RETURNING id, chat_on, chat_writers`, [b1])).rows;
assert.equal(g1.chat_on, true); assert.equal(g1.chat_writers, 'all'); checks++;
await db.query(`UPDATE groups SET chat_writers='leaders' WHERE id=$1`, [g1.id]); checks++;
await refuses(`UPDATE groups SET chat_writers='everyone' WHERE id=$1`, [g1.id], /check constraint|chat_writers/);

const chat = async gid => (await db.query(`INSERT INTO msg_threads(business_id, kind, group_id) VALUES ($1,'group',$2) RETURNING id`, [b1, gid])).rows[0].id;
const t1 = await chat(g1.id), t2 = await chat(g2.id);
const say = async (tid, who, body, replyTo = null) => (await db.query(
  `INSERT INTO msg_messages(business_id, thread_id, sender_contact_id, body, reply_to) VALUES ($1,$2,$3,$4,$5) RETURNING id`,
  [b1, tid, who, body, replyTo])).rows[0].id;
const first = await say(t1, ben, 'Who has the slow cooker?');
const youth = await say(t2, ben, 'Youth news');

// A reply quotes a message in the same chat, never another chat's.
const reply = await say(t1, ana, 'I do', first); checks++;
await refuses(`INSERT INTO msg_messages(business_id, thread_id, sender_contact_id, body, reply_to) VALUES ($1,$2,$3,'hi',$4)`,
  [b1, t1, ana, youth], /That reply is not to a message in this chat/);
await refuses(`UPDATE msg_messages SET reply_to=$1 WHERE id=$2`, [youth, reply], /That reply is not to a message in this chat/);
// Taking a message down still saves (the trigger reads the reply it already had).
await db.query(`UPDATE msg_messages SET status='removed' WHERE id=$1`, [reply]); checks++;
// The quoted message going away leaves the reply standing, unquoted.
await db.query(`DELETE FROM msg_messages WHERE id=$1`, [first]);
assert.equal((await db.query('SELECT reply_to FROM msg_messages WHERE id=$1', [reply])).rows[0].reply_to, null); checks++;

// Love / Praying / Amen: one of each per person, this church's own.
const react = `INSERT INTO msg_reactions(message_id, contact_id, business_id, kind) VALUES ($1,$2,$3,$4)`;
await db.query(react, [youth, ana, b1, 'pray']); checks++;
await db.query(react, [youth, ana, b1, 'amen']); checks++;
await refuses(react, [youth, ana, b1, 'pray'], /duplicate key|unique/);
await refuses(react, [youth, ana, b1, 'fire'], /check constraint|kind/);
await refuses(react, [youth, elsewhere, b1, 'love'], /That person is not in this business/);
await refuses(react, [youth, ana, b2, 'love'], /That message is not in this business/);
// Server-only: members never touch it directly.
const grants = (await db.query(`SELECT grantee FROM information_schema.role_table_grants WHERE table_name='msg_reactions'`)).rows.map(r => r.grantee);
assert.ok(!grants.includes('anon') && !grants.includes('authenticated'), grants.join(',')); checks++;
// A message's reactions go with it.
await db.query(`DELETE FROM msg_messages WHERE id=$1`, [youth]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM msg_reactions')).rows[0].n, 0); checks++;

console.log(`group chat db: ${checks} checks passed`);

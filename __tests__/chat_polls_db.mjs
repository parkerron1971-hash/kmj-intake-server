// Polls in a group's chat, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-chat-polls.sql. A poll is this church's own
// message with 2-4 choices of 1-60 characters; a vote is this church's own
// person, one per poll, for one of its choices; a group's photos and polls
// default to on; server-only; a message's poll and votes go with it.
// Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/chat_polls_db.mjs
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
await db.exec(await sql('APPLY-2026-10-20-chat-polls.sql'));
await db.exec(await sql('APPLY-2026-10-20-chat-polls.sql'));   // twice

// A group's photos and polls start on.
const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Thursday') RETURNING id, chat_extras`, [b1])).rows[0];
assert.equal(g.chat_extras, true); checks++;

const t = (await db.query(`INSERT INTO msg_threads(business_id, kind, group_id) VALUES ($1,'group',$2) RETURNING id`, [b1, g.id])).rows[0].id;
const say = async body => (await db.query(
  `INSERT INTO msg_messages(business_id, thread_id, sender_contact_id, body) VALUES ($1,$2,$3,$4) RETURNING id`,
  [b1, t, ana, body])).rows[0].id;
const q = await say('Potluck theme for Nov 19?');
const plain = await say('See you Thursday');

// A poll: 2-4 choices of 1-60 characters, on this church's own message.
const make = `INSERT INTO msg_polls(message_id, business_id, choices, closes_at) VALUES ($1,$2,$3,now() + interval '7 days')`;
await db.query(make, [q, b1, ['Soul food', 'Breakfast for dinner', 'Taco bar']]); checks++;
await refuses(make, [plain, b1, ['Only one']], /check constraint/);
await refuses(make, [plain, b1, ['a', 'b', 'c', 'd', 'e']], /check constraint/);
await refuses(make, [plain, b1, ['Fine', '   ']], /check constraint/);
await refuses(make, [plain, b1, ['Fine', 'x'.repeat(61)]], /check constraint/);
await refuses(make, [plain, b1, ['Fine', null]], /check constraint/);
await refuses(make, [plain, b2, ['Yes', 'No']], /That message is not in this business/);
await refuses(make, [q, b1, ['Yes', 'No']], /duplicate key|unique/);                 // one poll per message

// A vote: one per person, for one of the poll's own choices.
const vote = `INSERT INTO msg_poll_votes(message_id, contact_id, business_id, choice) VALUES ($1,$2,$3,$4)`;
await db.query(vote, [q, ana, b1, 0]); checks++;
await db.query(vote, [q, ben, b1, 2]); checks++;
await refuses(vote, [q, ana, b1, 1], /duplicate key|unique/);
await db.query(`DELETE FROM msg_poll_votes WHERE contact_id=$1`, [ben]);
await refuses(vote, [q, ben, b1, 3], /That poll has no such choice/);                 // three choices: 0, 1, 2
await refuses(`UPDATE msg_poll_votes SET choice=3 WHERE contact_id=$1`, [ana], /That poll has no such choice/);
await refuses(vote, [q, elsewhere, b1, 0], /That person is not in this business/);
await refuses(vote, [q, ben, b2, 0], /That poll is not in this business/);
await refuses(vote, [plain, ben, b1, 0], /foreign key|That poll is not in this business/);   // not a poll

// Server-only.
const grants = (await db.query(`SELECT grantee, table_name FROM information_schema.role_table_grants
  WHERE table_name IN ('msg_polls','msg_poll_votes') AND grantee IN ('anon','authenticated')`)).rows;
assert.deepEqual(grants, []); checks++;

// A message's poll and votes go with it.
await db.query(`DELETE FROM msg_messages WHERE id=$1`, [q]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM msg_polls')).rows[0].n, 0);
assert.equal((await db.query('SELECT count(*)::int AS n FROM msg_poll_votes')).rows[0].n, 0); checks++;

console.log(`chat polls db: ${checks} checks passed`);

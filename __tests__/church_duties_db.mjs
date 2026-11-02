// Church duties, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-01-church-duties.sql. A duty is moved to named
// logins in one step (church_duty_set): the holders it no longer names go,
// the ones it keeps keep when they were given it, the new ones come with who
// gave it, and one log row says from, to, by and at (null is the lanes'
// defaults). An undo is a change too and marks what it put back, once. One
// row a login a duty; a duty key is a plain word; a login that's deleted
// takes its rows but not the log; a church that goes takes everything; the
// browser's roles can't read, write or run any of it; running the file twice
// changes nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_duties_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const kevin = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const naiya = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const tiara = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const laquesha = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
// What Supabase already has: the roles, auth.users, the businesses.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth;
  CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO auth.users(id) VALUES ($1), ($2), ($3), ($4)', [kevin, naiya, tiara, laquesha]);
let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const move = (biz, duty, users, by, undoes = null) =>
  one('SELECT church_duty_set($1, $2, $3::uuid[], $4, $5) AS c', [biz, duty, users, by, undoes]).then(r => r.c);
const holders = async (biz, duty) => (await db.query(
  'SELECT user_id::text AS u, given_by::text AS by, given_at FROM church_duty_holders WHERE business_id = $1 AND duty = $2 ORDER BY user_id',
  [biz, duty])).rows;

await db.exec(await sql('APPLY-2026-11-01-church-duties.sql'));
await db.exec(await sql('APPLY-2026-11-01-church-duties.sql'));   // idempotent
assert.equal((await one('SELECT count(*)::int AS n FROM church_duty_holders')).n, 0, 'nothing moved yet'); checks++;

// RLS on both tables, no policies.
for (const table of ['church_duty_holders', 'church_duty_changes']) {
  const t = await one(`SELECT c.relrowsecurity AS rls,
      (SELECT count(*)::int FROM pg_policies p WHERE p.tablename = c.relname) AS policies
    FROM pg_class c WHERE c.relname = $1`, [table]);
  assert.deepEqual(t, { rls: true, policies: 0 }, table); checks++;
}

// The weekly text moves to Naiya: one holder, given by Kevin, logged from the lanes' defaults (null).
const c1 = await move(b1, 'weekly_text', [naiya], kevin);
assert.deepEqual(c1.from_holders, null); assert.deepEqual(c1.to_holders, [naiya]);
assert.equal(c1.changed_by, kevin); assert.ok(c1.changed_at && c1.id); assert.equal(c1.undoes, null); checks++;
const first = await holders(b1, 'weekly_text');
assert.deepEqual(first.map(h => [h.u, h.by]), [[naiya, kevin]]); checks++;

// Then to Naiya and Tiara (the same names twice count once): Naiya keeps when she was given it.
await new Promise(r => setTimeout(r, 5));
const c2 = await move(b1, 'weekly_text', [tiara, naiya, tiara], tiara);
assert.deepEqual(c2.from_holders, [naiya]); assert.deepEqual(c2.to_holders, [naiya, tiara].sort()); checks++;
const both = await holders(b1, 'weekly_text');
assert.deepEqual(both.map(h => h.u), [naiya, tiara].sort()); checks++;
const naiyaRow = both.find(h => h.u === naiya);
assert.equal(naiyaRow.by, kevin); assert.equal(+naiyaRow.given_at, +first[0].given_at, 'a kept holder keeps when'); checks++;
assert.equal(both.find(h => h.u === tiara).by, tiara); checks++;

// Undo the last change: back to Naiya alone, logged as an undo, and that change is marked put back.
const u1 = await move(b1, 'weekly_text', [naiya], kevin, c2.id);
assert.equal(u1.undoes, c2.id); assert.deepEqual(u1.from_holders, [naiya, tiara].sort()); assert.deepEqual(u1.to_holders, [naiya]); checks++;
assert.deepEqual((await holders(b1, 'weekly_text')).map(h => h.u), [naiya]); checks++;
assert.ok((await one('SELECT undone_at FROM church_duty_changes WHERE id = $1', [c2.id])).undone_at); checks++;
// Once only, never an undo itself, never another duty's or another church's change.
await refuses('SELECT church_duty_set($1, $2, $3::uuid[], $4, $5)', [b1, 'weekly_text', [naiya, tiara], kevin, c2.id], /already put back/);
await refuses('SELECT church_duty_set($1, $2, $3::uuid[], $4, $5)', [b1, 'weekly_text', [], kevin, u1.id], /already put back/);
await refuses('SELECT church_duty_set($1, $2, $3::uuid[], $4, $5)', [b1, 'rooms', [], kevin, c1.id], /already put back/);
await refuses('SELECT church_duty_set($1, $2, $3::uuid[], $4, $5)', [b2, 'weekly_text', [], kevin, c1.id], /already put back/);
// A refused undo changed nothing.
assert.deepEqual((await holders(b1, 'weekly_text')).map(h => h.u), [naiya]); checks++;

// Back to the lanes' defaults: no rows, logged to null. An empty list and null are the same.
const c3 = await move(b1, 'weekly_text', [], kevin);
assert.deepEqual(c3.from_holders, [naiya]); assert.equal(c3.to_holders, null); checks++;
assert.equal((await holders(b1, 'weekly_text')).length, 0); checks++;
const c4 = await move(b1, 'rooms', null, kevin);
assert.equal(c4.from_holders, null); assert.equal(c4.to_holders, null); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM church_duty_changes WHERE business_id = $1`, [b1])).n, 5); checks++;

// One row a login a duty; a duty key is a plain word; the log holds lists or null only.
await move(b1, 'rooms', [naiya, laquesha], kevin);
const give = 'INSERT INTO church_duty_holders(business_id, duty, user_id) VALUES ($1, $2, $3)';
await refuses(give, [b1, 'rooms', naiya], /duplicate key/);
await refuses(give, [b1, 'Rooms; drop table', naiya], /check constraint/);
await refuses(give, [b1, 'r', naiya], /check constraint/);
await refuses(`INSERT INTO church_duty_changes(business_id, duty, from_holders) VALUES ($1, 'rooms', '{"a": 1}')`, [b1], /check constraint/);
await refuses(give, [b1, 'posts', '99999999-9999-4999-8999-999999999999'], /foreign key/);

// A login that's deleted takes its rows; the log keeps the move with no one named as the mover.
await move(b1, 'posts', [tiara], laquesha);
await db.query('DELETE FROM auth.users WHERE id = $1', [laquesha]);
assert.deepEqual((await holders(b1, 'rooms')).map(h => h.u), [naiya]); checks++;
const posts = await one(`SELECT changed_by, to_holders FROM church_duty_changes WHERE business_id = $1 AND duty = 'posts'`, [b1]);
assert.equal(posts.changed_by, null); assert.deepEqual(posts.to_holders, [tiara]); checks++;
assert.equal((await holders(b1, 'posts'))[0].by, null); checks++;

// A church that goes takes everything; the other church keeps its own.
await move(b2, 'weekly_text', [naiya], kevin);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
for (const table of ['church_duty_holders', 'church_duty_changes']) {
  assert.equal((await one(`SELECT count(*)::int AS n FROM ${table} WHERE business_id = $1`, [b1])).n, 0); checks++;
  assert.equal((await one(`SELECT count(*)::int AS n FROM ${table}`)).n, 1); checks++;
}

// The browser's roles can't read, write or run any of it.
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const table of ['church_duty_holders', 'church_duty_changes']) {
    await refuses(`SELECT * FROM ${table}`, [], /permission denied/);
  }
  await refuses(`INSERT INTO church_duty_holders(business_id, duty, user_id) VALUES ('${b2}', 'rooms', '${naiya}')`, [], /permission denied/);
  await refuses(`UPDATE church_duty_changes SET undone_at = now()`, [], /permission denied/);
  await refuses('SELECT church_duty_set($1, $2, $3::uuid[], $4)', [b2, 'rooms', [naiya], naiya], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church duties db: ${checks} checks passed`);

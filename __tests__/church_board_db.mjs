// Board & minutes, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-board.sql. A board's quorum is a
// majority or a count (a count needs its number); a member's person is its
// own church's; meetings, items, attendance and decisions all belong to
// their own church's parents; an item is carried forward once; who moved
// and seconded are members; a church that leaves takes it all; the
// browser's roles can't read or write any of it. Applying twice is safe.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_board_db.mjs
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
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid);
  CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, title text);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const one = async (text, args) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-27-church-board.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-board.sql'));   // idempotent

// A board: a majority unless it says a count, and a count needs its number.
const deacons = await one(`INSERT INTO church_boards(business_id, name) VALUES ($1, 'Deacons') RETURNING *`, [b1]);
assert.equal(deacons.quorum_kind, 'majority'); assert.equal(deacons.quorum_count, null); assert.equal(deacons.archived, false); checks++;
await refuses(`INSERT INTO church_boards(business_id, name, quorum_kind) VALUES ($1, 'Elders', 'count')`, [b1], /check constraint/);
await refuses(`INSERT INTO church_boards(business_id, name, quorum_kind) VALUES ($1, 'Elders', 'most')`, [b1], /check constraint/);
await refuses(`INSERT INTO church_boards(business_id, name) VALUES ($1, '')`, [b1], /check constraint/);
const elders = await one(`INSERT INTO church_boards(business_id, name, quorum_kind, quorum_count) VALUES ($1, 'Elders', 'count', 3) RETURNING *`, [b1]);
assert.equal(elders.quorum_count, 3); checks++;
const theirBoard = await one(`INSERT INTO church_boards(business_id, name) VALUES ($1, 'Their deacons') RETURNING *`, [b2]);

// Members: their person is their church's; their board is their church's.
const hayes = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1])).id;
const theirs = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b2])).id;
const addMember = `INSERT INTO church_board_members(business_id, board_id, contact_id, name) VALUES ($1, $2, $3, $4) RETURNING *`;
const mHayes = await one(addMember, [b1, deacons.id, hayes, 'Darnell Hayes']);
assert.equal(mHayes.active, true); assert.equal(mHayes.title, ''); checks++;
const mMoore = await one(addMember, [b1, deacons.id, null, 'Dana Moore']);
await refuses(addMember, [b1, deacons.id, theirs, 'Grace Member'], /not in this church/);
await refuses(`UPDATE church_board_members SET contact_id = $2 WHERE id = $1`, [mHayes.id, theirs], /not in this church/);
await refuses(addMember, [b1, theirBoard.id, null, 'Sneaky'], /foreign key/);
await refuses(addMember, [b1, deacons.id, null, ''], /check constraint/);

// A meeting: planned until it starts; its board is its church's.
const addMeeting = `INSERT INTO church_board_meetings(business_id, board_id, starts_at) VALUES ($1, $2, $3) RETURNING *`;
const sep = await one(addMeeting, [b1, deacons.id, '2026-09-24T23:00:00Z']);
assert.equal(sep.status, 'planned'); assert.equal(sep.sent_count, 0); assert.equal(sep.place, ''); checks++;
await refuses(addMeeting, [b1, theirBoard.id, '2026-09-24T23:00:00Z'], /foreign key/);
await refuses(`UPDATE church_board_meetings SET status = 'done' WHERE id = $1`, [sep.id], /check constraint/);
const oct = await one(addMeeting, [b1, deacons.id, '2026-10-29T23:00:00Z']);
const theirMeeting = await one(addMeeting, [b2, theirBoard.id, '2026-10-29T23:00:00Z']);

// Items: open by default, documents an array, the known statuses; carried once.
const addItem = `INSERT INTO church_board_items(business_id, meeting_id, title, carried_from) VALUES ($1, $2, $3, $4) RETURNING *`;
const roof = await one(addItem, [b1, sep.id, 'Roof bids', null]);
assert.equal(roof.status, 'open'); assert.deepEqual(roof.documents, []); assert.equal(roof.minutes, ''); checks++;
await refuses(`UPDATE church_board_items SET status = 'maybe' WHERE id = $1`, [roof.id], /check constraint/);
await refuses(`UPDATE church_board_items SET documents = '{"a":1}' WHERE id = $1`, [roof.id], /check constraint/);
await refuses(addItem, [b1, theirMeeting.id, 'Sneaky', null], /foreign key/);
await db.query(addItem, [b1, oct.id, 'Roof bids', roof.id]); checks++;
await refuses(addItem, [b1, oct.id, 'Roof bids', roof.id], /duplicate key|unique/);
const again = await db.query(`INSERT INTO church_board_items(business_id, meeting_id, title, carried_from)
  VALUES ($1, $2, 'Roof bids', $3) ON CONFLICT (carried_from) DO NOTHING RETURNING id`, [b1, oct.id, roof.id]);
assert.equal(again.rows.length, 0, 'two presses at once carry it once'); checks++;
const task = (await one('INSERT INTO tasks(business_id, title) VALUES ($1, $2) RETURNING id', [b1, 'Roof'])).id;
await db.query('UPDATE church_board_items SET task_id = $2 WHERE id = $1', [roof.id, task]);
await db.query('DELETE FROM tasks WHERE id = $1', [task]);
assert.equal((await one('SELECT task_id FROM church_board_items WHERE id = $1', [roof.id])).task_id, null, 'a deleted task leaves the item'); checks++;

// Attendance: one row a member a meeting, the known words, the same church.
const markAt = `INSERT INTO church_board_attendance(business_id, meeting_id, member_id, status) VALUES ($1, $2, $3, $4)`;
await db.query(markAt, [b1, sep.id, mHayes.id, 'present']); checks++;
await refuses(markAt, [b1, sep.id, mHayes.id, 'absent'], /duplicate key|unique/);
await refuses(markAt, [b1, sep.id, mMoore.id, 'late'], /check constraint/);
await refuses(markAt, [b2, theirMeeting.id, mHayes.id, 'present'], /foreign key/);

// Decisions: a motion, a vote that isn't negative, a known result; who moved
// and seconded are this church's members.
const decide = `INSERT INTO church_board_decisions(business_id, board_id, meeting_id, item_id, motion, moved_by, seconded_by,
  votes_for, votes_against, result, decided_on) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, '2026-09-24') RETURNING *`;
const d = await one(decide, [b1, deacons.id, sep.id, roof.id, 'Accept Northside Roofing', mHayes.id, mMoore.id, 5, 1, 'carried']);
assert.equal(d.votes_abstain, 0); assert.equal(d.item_title, ''); checks++;
await refuses(decide, [b1, deacons.id, sep.id, roof.id, '', null, null, 1, 0, 'carried'], /check constraint/);
await refuses(decide, [b1, deacons.id, sep.id, roof.id, 'x', null, null, -1, 0, 'carried'], /check constraint/);
await refuses(decide, [b1, deacons.id, sep.id, roof.id, 'x', null, null, 1, 0, 'passed'], /check constraint/);
await refuses(decide, [b2, theirBoard.id, theirMeeting.id, roof.id, 'x', null, null, 1, 0, 'carried'], /foreign key/);
const theirMember = await one(addMember, [b2, theirBoard.id, null, 'Theirs']);
await refuses(decide, [b1, deacons.id, sep.id, roof.id, 'x', theirMember.id, null, 1, 0, 'carried'], /foreign key/);

// A meeting removed takes its items, attendance and decisions; the item it
// carried from can be carried again.
await db.query('DELETE FROM church_board_meetings WHERE id = $1', [oct.id]);
assert.equal((await one('SELECT count(*)::int n FROM church_board_items WHERE carried_from = $1', [roof.id])).n, 0); checks++;
await db.query('DELETE FROM church_board_meetings WHERE id = $1', [sep.id]);
for (const t of ['church_board_items', 'church_board_attendance', 'church_board_decisions']) {
  assert.equal((await one(`SELECT count(*)::int n FROM ${t} WHERE business_id = $1`, [b1])).n, 0, t); checks++;
}

// A church that leaves takes it all, decisions that name their movers too.
const theirItem = await one(addItem, [b2, theirMeeting.id, 'Their roof', null]);
await db.query(decide, [b2, theirBoard.id, theirMeeting.id, theirItem.id, 'Theirs', theirMember.id, null, 3, 0, 'carried']);
await db.query('DELETE FROM businesses WHERE id = $1', [b2]);
for (const t of ['church_boards', 'church_board_members', 'church_board_meetings', 'church_board_decisions']) {
  assert.equal((await one(`SELECT count(*)::int n FROM ${t} WHERE business_id = $1`, [b2])).n, 0, t); checks++;
}

// Server-only: RLS on, no policies, and the browser's roles get nothing.
for (const t of ['church_boards', 'church_board_members', 'church_board_meetings', 'church_board_items',
  'church_board_attendance', 'church_board_decisions']) {
  const r = await one(`SELECT relrowsecurity, (SELECT count(*)::int FROM pg_policies WHERE tablename = $1) AS policies
    FROM pg_class WHERE relname = $1`, [t]);
  assert.equal(r.relrowsecurity, true, t); assert.equal(r.policies, 0, t); checks++;
  for (const role of ['anon', 'authenticated']) {
    await db.exec(`SET ROLE ${role}`);
    await assert.rejects(db.query(`SELECT 1 FROM ${t} LIMIT 1`), /permission denied/); checks++;
    await db.exec('RESET ROLE');
  }
}

console.log(`church_board_db: ${checks} checks passed`);

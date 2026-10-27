// My tasks for leaders, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-leader-tasks.sql. A task can be handed to a
// leader (one of the church's people) or a login, never both; the leader and
// whoever marked it done are its own church's people; handing it to someone
// else starts the telling over, a new due date can be late again, and the
// sweep's own writes start nothing over; deleting the person lets the task
// stand with no one; an open leader task is found by the index's own shape;
// every task that was there before is handed to no leader; running the file
// twice changes nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/leader_tasks_db.mjs
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
const u1 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, name text);
  CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL,
    title text NOT NULL, status text NOT NULL DEFAULT 'todo', due_date date, completed_at timestamptz);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query(`INSERT INTO tasks (business_id, title) VALUES ($1, 'Order the VBS shirts'), ($1, 'Book the bus')`, [b1]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const one = async (text, args) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-26-task-hand-off.sql'));
await db.exec(await sql('APPLY-2026-10-27-leader-tasks.sql'));
await db.exec(await sql('APPLY-2026-10-27-leader-tasks.sql'));   // idempotent

const before = await one('SELECT count(*)::int AS n FROM tasks WHERE assigned_contact_id IS NULL AND leader_told_at IS NULL');
assert.equal(before.n, 2, 'every task that was there is handed to no leader'); checks++;

const ray = (await one(`INSERT INTO contacts(business_id, name) VALUES ($1, 'Ray Dunn') RETURNING id`, [b1])).id;
const ann = (await one(`INSERT INTO contacts(business_id, name) VALUES ($1, 'Ann Lee') RETURNING id`, [b1])).id;
const other = (await one(`INSERT INTO contacts(business_id, name) VALUES ($1, 'Elsewhere') RETURNING id`, [b2])).id;

// Handed to a leader of its own church.
const retreat = (await one(`INSERT INTO tasks(business_id, title, due_date, assigned_contact_id)
  VALUES ($1, 'Plan the fall retreat', '2026-11-15', $2) RETURNING *`, [b1, ray]));
assert.equal(retreat.assigned_contact_id, ray); assert.equal(retreat.leader_told_at, null); checks++;

// Never another church's person, as the leader or as who marked it done.
await refuses(`INSERT INTO tasks(business_id, title, assigned_contact_id) VALUES ($1, 'x', $2)`, [b1, other], /not in this church/);
await refuses(`UPDATE tasks SET assigned_contact_id = $1 WHERE id = $2`, [other, retreat.id], /not in this church/);
await refuses(`UPDATE tasks SET done_by_contact_id = $1 WHERE id = $2`, [other, retreat.id], /not in this church/);
await refuses(`UPDATE tasks SET business_id = $1 WHERE id = $2`, [b2, retreat.id], /not in this church/);

// One person per task: a login or a leader, never both.
await refuses(`UPDATE tasks SET assigned_to = $1 WHERE id = $2`, [u1, retreat.id], /tasks_handed_to_one/);
const handed = await one(`UPDATE tasks SET assigned_to = $1, assigned_contact_id = null WHERE title = 'Book the bus' RETURNING *`, [u1]);
assert.equal(handed.assigned_to, u1); checks++;
const swapped = await one(`UPDATE tasks SET assigned_to = null, assigned_contact_id = $1 WHERE id = $2 RETURNING *`, [ann, handed.id]);
assert.equal(swapped.assigned_contact_id, ann); assert.equal(swapped.assigned_to, null); checks++;

// The sweep's own writes (told, late) start nothing over.
const told = await one(`UPDATE tasks SET leader_told_at = now(), late_told_at = now() WHERE id = $1 RETURNING *`, [retreat.id]);
assert.ok(told.leader_told_at && told.late_told_at); checks++;
// An edit that changes neither the leader nor the date keeps both.
const same = await one(`UPDATE tasks SET title = 'Plan the fall retreat!', due_date = '2026-11-15',
  assigned_contact_id = $1 WHERE id = $2 RETURNING *`, [ray, retreat.id]);
assert.ok(same.leader_told_at && same.late_told_at, 'saving the same leader and date keeps what was said'); checks++;
// A new due date can be late again; the leader was already told.
const moved = await one(`UPDATE tasks SET due_date = '2026-11-22' WHERE id = $1 RETURNING *`, [retreat.id]);
assert.ok(moved.leader_told_at); assert.equal(moved.late_told_at, null); checks++;
// Handed to someone else: they're told afresh.
await db.query('UPDATE tasks SET late_told_at = now() WHERE id = $1', [retreat.id]);
const rehanded = await one(`UPDATE tasks SET assigned_contact_id = $1 WHERE id = $2 RETURNING *`, [ann, retreat.id]);
assert.equal(rehanded.leader_told_at, null); assert.equal(rehanded.late_told_at, null); checks++;

// Done from the phone: who did it is kept, and it leaves the open list.
const open = `SELECT title FROM tasks WHERE business_id = $1 AND assigned_contact_id = $2 AND status <> 'done' ORDER BY title`;
assert.deepEqual((await db.query(open, [b1, ann])).rows.map(r => r.title), ['Book the bus', 'Plan the fall retreat!']); checks++;
const done = await one(`UPDATE tasks SET status = 'done', completed_at = now(), done_by_contact_id = $1 WHERE id = $2 RETURNING *`,
  [ann, retreat.id]);
assert.equal(done.done_by_contact_id, ann); assert.ok(done.leader_told_at === null, 'marking done changes no one'); checks++;
assert.deepEqual((await db.query(open, [b1, ann])).rows.map(r => r.title), ['Book the bus']); checks++;

// The person leaves the church's list: the task stands, with no one.
await db.query('DELETE FROM contacts WHERE id = $1', [ann]);
const left = await one('SELECT assigned_contact_id, done_by_contact_id FROM tasks WHERE id = $1', [retreat.id]);
assert.equal(left.assigned_contact_id, null); assert.equal(left.done_by_contact_id, null); checks++;
await refuses(`UPDATE tasks SET assigned_contact_id = 'not-a-uuid' WHERE id = $1`, [retreat.id], /uuid/);

const idx = await one(`SELECT indexdef FROM pg_indexes WHERE indexname = 'tasks_leader_open'`);
assert.match(idx.indexdef, /\(business_id, assigned_contact_id\) WHERE \(\(assigned_contact_id IS NOT NULL\) AND \(status <> 'done'::text\)\)/); checks++;
const counts = await one(`SELECT
  (SELECT count(*)::int FROM pg_indexes WHERE indexname = 'tasks_leader_open') AS idx,
  (SELECT count(*)::int FROM pg_constraint WHERE conname = 'tasks_handed_to_one') AS con,
  (SELECT count(*)::int FROM pg_trigger WHERE tgname = 'tasks_leader_same_business') AS trg`);
assert.deepEqual(counts, { idx: 1, con: 1, trg: 1 }, 'one of each after two runs'); checks++;

console.log(`leader_tasks_db: ${checks} checks passed`);

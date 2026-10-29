// Who sees what, on a real Postgres (PGlite): supabase/APPLY-2026-10-26-task-hand-off.sql.
// A task can be handed to one login (tasks.assigned_to); every task that was
// there before stays with no one; an open handed task is found by the index's
// own shape; running the file twice changes nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/task_hand_off_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const u1 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
await db.exec(`CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL,
  title text NOT NULL, status text NOT NULL DEFAULT 'todo', due_date date);`);
await db.query(`INSERT INTO tasks (business_id, title) VALUES ($1, 'Order the VBS shirts'), ($1, 'Book the bus')`, [b1]);
let checks = 0;

await db.exec(await sql('APPLY-2026-10-26-task-hand-off.sql'));
await db.exec(await sql('APPLY-2026-10-26-task-hand-off.sql'));   // idempotent

const before = await db.query('SELECT count(*)::int AS n FROM tasks WHERE assigned_to IS NULL');
assert.equal(before.rows[0].n, 2, 'every task that was there stays with no one'); checks++;

const hand = `UPDATE tasks SET assigned_to = $1 WHERE title = 'Order the VBS shirts' RETURNING assigned_to`;
assert.equal((await db.query(hand, [u1])).rows[0].assigned_to, u1); checks++;
const mine = `SELECT title FROM tasks WHERE business_id = $1 AND assigned_to = $2 AND status <> 'done'`;
assert.deepEqual((await db.query(mine, [b1, u1])).rows.map(r => r.title), ['Order the VBS shirts']); checks++;
await db.query(`UPDATE tasks SET status = 'done' WHERE assigned_to = $1`, [u1]);
assert.equal((await db.query(mine, [b1, u1])).rows.length, 0, 'done is off their list'); checks++;
await assert.rejects(db.query(hand, ['not-a-uuid']), /uuid/); checks++;

const idx = await db.query(`SELECT count(*)::int AS n FROM pg_indexes WHERE indexname = 'tasks_handed_open'`);
assert.equal(idx.rows[0].n, 1, 'one index after two runs'); checks++;

console.log(`task_hand_off_db: ${checks} checks passed`);

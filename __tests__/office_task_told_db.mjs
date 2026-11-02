// A task handed to an office login reaches them, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-01-office-task-told.sql. Every task already handed
// to a login counts as told; a hand-off to a login is stamped with who handed
// it, as a leader's is; handing it to another login clears both told stamps;
// a new due date clears only the late one; a leader's hand-off still works as
// before; a task handed to no one has no hander; running the file twice
// changes nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/office_task_told_db.mjs
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
const jessica = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const naiya = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const tiara = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth;
  CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, name text);
  CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL,
    title text NOT NULL, status text NOT NULL DEFAULT 'todo', due_date date, completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now());`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await db.query('INSERT INTO auth.users(id) VALUES ($1), ($2), ($3)', [jessica, naiya, tiara]);
let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const as = async uid => db.query(`SELECT set_config('request.jwt.claim.sub', $1, false)`, [uid || '']);

await db.exec(await sql('APPLY-2026-10-26-task-hand-off.sql'));
await db.exec(await sql('APPLY-2026-10-27-leader-tasks.sql'));
await db.exec(await sql('APPLY-2026-10-27-task-handed-by.sql'));
// Before: one task already handed to a login, one to no one.
const old = await one(`INSERT INTO tasks (business_id, title, assigned_to) VALUES ($1, 'Order the VBS shirts', $2) RETURNING *`, [b1, naiya]);
await one(`INSERT INTO tasks (business_id, title) VALUES ($1, 'Clean the closet') RETURNING *`, [b1]);

await db.exec(await sql('APPLY-2026-11-01-office-task-told.sql'));
await db.exec(await sql('APPLY-2026-11-01-office-task-told.sql'));   // idempotent

const was = await one('SELECT * FROM tasks WHERE id = $1', [old.id]);
assert.ok(was.seat_told_at, 'a task already handed to a login counts as told'); checks++;
assert.equal(was.seat_late_told_at, null); checks++;
assert.equal((await one('SELECT count(*)::int AS n FROM tasks WHERE assigned_to IS NULL AND seat_told_at IS NOT NULL')).n, 0,
  'a task handed to no one is never stamped'); checks++;

// Jessica hands Naiya a task from the office app: stamped with who she is, not yet told.
await as(jessica);
let t = await one(`INSERT INTO tasks(business_id, title, assigned_to, due_date, handed_by)
  VALUES ($1, 'Book the fellowship hall', $2, '2026-11-04', $3) RETURNING *`, [b1, naiya, tiara]);
assert.equal(t.handed_by, jessica, 'a hand-off to a login names who handed it, whatever it passes'); checks++;
assert.equal(t.seat_told_at, null, 'a new hand-off is not yet told'); checks++;

// The sweep tells Naiya, then it's late and goes up.
await as('');
await db.query(`UPDATE tasks SET seat_told_at = now(), seat_late_told_at = now() WHERE id = $1`, [t.id]);
// A new due date: late can be told again, the hand-off stays told.
t = await one(`UPDATE tasks SET due_date = '2026-11-11' WHERE id = $1 RETURNING *`, [t.id]);
assert.ok(t.seat_told_at, 'a new due date keeps the hand-off told'); checks++;
assert.equal(t.seat_late_told_at, null, 'a new due date can be late again'); checks++;
assert.equal(t.handed_by, jessica, 'the hander stays'); checks++;

// Handed to Tiara instead: she's told afresh, and the hand-off is Jessica's again.
await as(jessica);
await db.query(`UPDATE tasks SET seat_late_told_at = now() WHERE id = $1`, [t.id]);
t = await one(`UPDATE tasks SET assigned_to = $2 WHERE id = $1 RETURNING *`, [t.id, tiara]);
assert.equal(t.seat_told_at, null, 'a new login is told afresh'); checks++;
assert.equal(t.seat_late_told_at, null); checks++;
assert.equal(t.handed_by, jessica); checks++;

// Nobody moves the hander by hand.
await as(tiara);
t = await one(`UPDATE tasks SET handed_by = $2 WHERE id = $1 RETURNING *`, [t.id, tiara]);
assert.equal(t.handed_by, jessica, 'the hander cannot be changed by hand'); checks++;

// Taken back from everyone: no hander.
t = await one(`UPDATE tasks SET assigned_to = NULL WHERE id = $1 RETURNING *`, [t.id]);
assert.equal(t.handed_by, null, 'handed to no one, no hander'); checks++;

// A leader's hand-off works as before.
const ray = (await one(`INSERT INTO contacts(business_id, name) VALUES ($1, 'Ray Dunn') RETURNING id`, [b1])).id;
await as(naiya);
const lead = await one(`INSERT INTO tasks(business_id, title, assigned_contact_id) VALUES ($1, 'Plan the retreat', $2) RETURNING *`, [b1, ray]);
assert.equal(lead.handed_by, naiya, "a leader's hand-off still names who handed it"); checks++;
assert.equal(lead.seat_told_at, null, "a leader's task is never stamped for a login"); checks++;

// The two indexes and the reset trigger are there once.
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_indexes WHERE indexname IN ('tasks_seat_untold','tasks_seat_late')`)).n, 2); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_trigger WHERE tgname IN ('tasks_seat_told_reset','tasks_handed_by_stamp')`)).n, 2); checks++;

console.log(`office task told: ${checks} checks passed`);

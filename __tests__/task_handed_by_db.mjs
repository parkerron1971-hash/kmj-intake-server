// Who handed a leader a task, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-task-handed-by.sql. An office login's own write
// is stamped with who they are, whatever it passes; the server's write (no
// person in the token) keeps the login it names; handing it to another
// leader stamps afresh; a task no longer handed to a leader has no hander;
// it can't be moved to someone else by hand; a login that's deleted leaves
// the task standing; every task that was there before has no hander; running
// the file twice changes nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/task_handed_by_db.mjs
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
const sarah = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const owner = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const mallory = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
// What Supabase already has: the roles, auth.users, auth.uid() from the JWT.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth;
  CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, name text);
  CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL,
    title text NOT NULL, status text NOT NULL DEFAULT 'todo', due_date date, completed_at timestamptz);`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await db.query('INSERT INTO auth.users(id) VALUES ($1), ($2), ($3)', [sarah, owner, mallory]);
await db.query(`INSERT INTO tasks (business_id, title) VALUES ($1, 'Order the VBS shirts')`, [b1]);
let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const as = async uid => db.query(`SELECT set_config('request.jwt.claim.sub', $1, false)`, [uid || '']);

await db.exec(await sql('APPLY-2026-10-26-task-hand-off.sql'));
await db.exec(await sql('APPLY-2026-10-27-leader-tasks.sql'));
await db.exec(await sql('APPLY-2026-10-27-task-handed-by.sql'));
await db.exec(await sql('APPLY-2026-10-27-task-handed-by.sql'));   // idempotent

assert.equal((await one('SELECT count(*)::int AS n FROM tasks WHERE handed_by IS NOT NULL')).n, 0,
  'every task that was there has no hander'); checks++;

const ray = (await one(`INSERT INTO contacts(business_id, name) VALUES ($1, 'Ray Dunn') RETURNING id`, [b1])).id;
const ann = (await one(`INSERT INTO contacts(business_id, name) VALUES ($1, 'Ann Lee') RETURNING id`, [b1])).id;

// An office login hands a task out: stamped with who they are, whatever it passes.
await as(sarah);
const retreat = await one(`INSERT INTO tasks(business_id, title, assigned_contact_id, handed_by)
  VALUES ($1, 'Plan the fall retreat', $2, $3) RETURNING *`, [b1, ray, mallory]);
assert.equal(retreat.handed_by, sarah, 'the caller is who handed it, never who they say'); checks++;

// It can't be moved to someone else by hand, for anyone.
await as(mallory);
assert.equal((await one('UPDATE tasks SET handed_by = $1 WHERE id = $2 RETURNING handed_by', [mallory, retreat.id])).handed_by,
  sarah); checks++;
// Other edits leave it as it was.
assert.equal((await one(`UPDATE tasks SET title = 'Plan the winter retreat' WHERE id = $1 RETURNING handed_by`,
  [retreat.id])).handed_by, sarah); checks++;

// Handed on to another leader: whoever handed it on.
assert.equal((await one('UPDATE tasks SET assigned_contact_id = $1 WHERE id = $2 RETURNING handed_by', [ann, retreat.id])).handed_by,
  mallory); checks++;

// No longer a leader's task (handed to a login): no hander.
const back = await one('UPDATE tasks SET assigned_contact_id = NULL, assigned_to = $1 WHERE id = $2 RETURNING *', [owner, retreat.id]);
assert.equal(back.handed_by, null); checks++;

// The server (no person in the token) names who acted, as the Board's "Make tasks" does.
await as(null);
const roof = await one(`INSERT INTO tasks(business_id, title, assigned_contact_id, handed_by)
  VALUES ($1, 'Get a third roof bid', $2, $3) RETURNING *`, [b1, ray, owner]);
assert.equal(roof.handed_by, owner); checks++;
// A task for a login, not a leader, has no hander even when one is passed.
const bulletins = await one(`INSERT INTO tasks(business_id, title, assigned_to, handed_by)
  VALUES ($1, 'Print the bulletins', $2, $2) RETURNING *`, [b1, owner]);
assert.equal(bulletins.handed_by, null); checks++;

// The login is deleted: the task stands, with no hander.
await db.query('DELETE FROM auth.users WHERE id = $1', [owner]);
const after = await one('SELECT * FROM tasks WHERE id = $1', [roof.id]);
assert.equal(after.handed_by, null); assert.equal(after.assigned_contact_id, ray); checks++;

console.log(`task handed-by db: ${checks} checks passed`);

// Church assignments, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-12-church-assignments.sql. Running it twice changes
// nothing; the two CHECKs and the three foreign keys go in NOT VALID (nothing
// old to scan under the lock) and still refuse every new row that breaks
// them; a start-up item is made once per person; the person a stuck item was
// sent up to is the task's own church's; church_duty_days is server-only and
// goes with its church and its login.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_assignments_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const u1 = 'aaaaaaaa-1111-4111-8111-111111111111';
const u2 = 'aaaaaaaa-2222-4222-8222-222222222222';
const c1 = 'cccccccc-1111-4111-8111-111111111111';
const c2 = 'cccccccc-2222-4222-8222-222222222222';
// What Supabase already has: the roles, auth.users, businesses, contacts, and
// the tasks table with an old row in it.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid);
  CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, title text,
    status text DEFAULT 'todo', assigned_to uuid, assigned_contact_id uuid, created_at timestamptz DEFAULT now());`);
await db.query('INSERT INTO businesses VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO auth.users VALUES ($1), ($2)', [u1, u2]);
await db.query('INSERT INTO contacts VALUES ($1, $2), ($3, $4)', [c1, b1, c2, b2]);
await db.query(`INSERT INTO tasks(business_id, title, assigned_to) VALUES ($1, 'an old task', $2)`, [b1, u1]);

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const ok = async (text, args) => { await db.query(text, args); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

const sql = await readFile(new URL('../supabase/APPLY-2026-11-12-church-assignments.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);                       // twice: nothing changes, nothing fails
checks++;

// Twelve columns, all null on the old row.
const cols = (await db.query(`SELECT column_name FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'tasks' AND column_name IN ('duty','done_when','check_key',
  'startup_key','stuck_note','stuck_at','raised_at','raised_to','raised_to_contact_id','raised_by','raised_told_at',
  'checked_at')`)).rows;
assert.equal(cols.length, 12); checks++;
const old = await one(`SELECT duty, startup_key, raised_to, stuck_at FROM tasks WHERE title = 'an old task'`);
assert.deepEqual(old, { duty: null, startup_key: null, raised_to: null, stuck_at: null }); checks++;

// The CHECKs and the foreign keys are NOT VALID, once each, and still refuse.
const cons = (await db.query(`SELECT conname, convalidated FROM pg_constraint WHERE conrelid = 'public.tasks'::regclass
  AND conname IN ('tasks_raised_to_fkey','tasks_raised_to_contact_id_fkey','tasks_raised_by_fkey',
  'tasks_raised_to_one','tasks_assignment_lengths') ORDER BY conname`)).rows;
assert.equal(cons.length, 5); checks++;
assert.ok(cons.every(c => c.convalidated === false), JSON.stringify(cons)); checks++;
await refuses(`INSERT INTO tasks(business_id, title, raised_to, raised_to_contact_id) VALUES ($1, 'x', $2, $3)`,
  [b1, u1, c1], /tasks_raised_to_one/);
await refuses(`INSERT INTO tasks(business_id, title, stuck_note) VALUES ($1, 'x', repeat('a', 501))`, [b1],
  /tasks_assignment_lengths/);
await refuses(`INSERT INTO tasks(business_id, title, done_when) VALUES ($1, 'x', repeat('a', 301))`, [b1],
  /tasks_assignment_lengths/);
await refuses(`INSERT INTO tasks(business_id, title, startup_key) VALUES ($1, 'x', 'Not A Key')`, [b1],
  /tasks_assignment_lengths/);
await refuses(`INSERT INTO tasks(business_id, title, raised_to) VALUES ($1, 'x', $2)`,
  [b1, 'aaaaaaaa-9999-4999-8999-999999999999'], /tasks_raised_to_fkey/);
await refuses(`INSERT INTO tasks(business_id, title, raised_by) VALUES ($1, 'x', $2)`,
  [b1, 'aaaaaaaa-9999-4999-8999-999999999999'], /tasks_raised_by_fkey/);
await ok(`INSERT INTO tasks(business_id, title, stuck_note) VALUES ($1, 'x', '')`, [b1]);

// The person it was sent up to is the task's own church's.
await ok(`INSERT INTO tasks(business_id, title, assigned_to, raised_to_contact_id) VALUES ($1, 'a', $2, $3)`, [b1, u1, c1]);
await refuses(`INSERT INTO tasks(business_id, title, assigned_to, raised_to_contact_id) VALUES ($1, 'a', $2, $3)`,
  [b1, u1, c2], /not in this church/);
await refuses(`UPDATE tasks SET raised_to_contact_id = $1 WHERE title = 'an old task'`, [c2], /not in this church/);

// A start-up item, once per person; another person, or by hand, is free.
await ok(`INSERT INTO tasks(business_id, title, assigned_to, startup_key) VALUES ($1, 's', $2, 'rooms.listed')`, [b1, u1]);
await refuses(`INSERT INTO tasks(business_id, title, assigned_to, startup_key) VALUES ($1, 's', $2, 'rooms.listed')`,
  [b1, u1], /tasks_startup_once/);
await ok(`INSERT INTO tasks(business_id, title, assigned_contact_id, startup_key) VALUES ($1, 's', $2, 'rooms.listed')`,
  [b1, c1]);
await ok(`INSERT INTO tasks(business_id, title, assigned_to, startup_key) VALUES ($1, 's', $2, 'rooms.listed')`, [b2, u1]);
await ok(`INSERT INTO tasks(business_id, title, assigned_to) VALUES ($1, 's', $2)`, [b1, u1]);

// A login or a person deleted lets go of what was sent up to them.
await ok(`INSERT INTO tasks(business_id, title, raised_to, raised_by) VALUES ($1, 'up', $2, $2)`, [b1, u2]);
await ok('DELETE FROM auth.users WHERE id = $1', [u2]);
assert.deepEqual(await one(`SELECT raised_to, raised_by FROM tasks WHERE title = 'up'`), { raised_to: null, raised_by: null });
checks++;

// The day a login picked: one a login a duty, a real day, server-only.
await ok(`INSERT INTO church_duty_days(business_id, user_id, duty, day) VALUES ($1, $2, 'weekly_text', 'Thu')`, [b1, u1]);
await refuses(`INSERT INTO church_duty_days(business_id, user_id, duty, day) VALUES ($1, $2, 'weekly_text', 'Fri')`,
  [b1, u1], /duplicate key/);
await refuses(`INSERT INTO church_duty_days(business_id, user_id, duty, day) VALUES ($1, $2, 'calendar', 'Someday')`,
  [b1, u1], /check constraint/);
const rls = await one(`SELECT relrowsecurity FROM pg_class WHERE oid = 'public.church_duty_days'::regclass`);
assert.equal(rls.relrowsecurity, true); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_policies WHERE tablename = 'church_duty_days'`)).n, 0); checks++;
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM church_duty_days', [], /permission denied/);
  await db.exec('RESET ROLE');
}
await ok('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_duty_days')).n, 0); checks++;

console.log(`church assignments db: ${checks} checks passed`);

// A leader's assignments from the member app, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-12-church-lead-assignments.sql. Running it twice
// changes nothing; the two foreign keys go in NOT VALID (nothing old to scan
// under the lock) and still refuse every new row that breaks them; the person
// who handed it out and the person who sent it up are the task's own
// church's; deleting a person lets go of what they handed out or sent up.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_lead_assignments_db.mjs
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
const c1 = 'cccccccc-1111-4111-8111-111111111111';
const c2 = 'cccccccc-2222-4222-8222-222222222222';
const c3 = 'cccccccc-3333-4333-8333-333333333333';
// What Supabase already has: the roles, businesses, contacts, and the tasks
// table with an old row in it.
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid);
  CREATE TABLE public.tasks(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, title text,
    status text DEFAULT 'todo', assigned_contact_id uuid, created_at timestamptz DEFAULT now());`);
await db.query('INSERT INTO businesses VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1, $2), ($3, $4), ($5, $2)', [c1, b1, c2, b2, c3]);
await db.query(`INSERT INTO tasks(business_id, title, assigned_contact_id) VALUES ($1, 'an old task', $2)`, [b1, c1]);

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const ok = async (text, args) => { await db.query(text, args); checks++; };
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

const sql = await readFile(new URL('../supabase/APPLY-2026-11-12-church-lead-assignments.sql', import.meta.url), 'utf8');
await db.exec(sql);
await db.exec(sql);                       // twice: nothing changes, nothing fails
checks++;

// Two columns, null on the old row.
assert.deepEqual(await one(`SELECT handed_by_contact_id, raised_by_contact_id FROM tasks WHERE title = 'an old task'`),
  { handed_by_contact_id: null, raised_by_contact_id: null }); checks++;

// The foreign keys are NOT VALID, once each, and still refuse.
const cons = (await db.query(`SELECT conname, convalidated FROM pg_constraint WHERE conrelid = 'public.tasks'::regclass
  AND conname IN ('tasks_handed_by_contact_id_fkey', 'tasks_raised_by_contact_id_fkey') ORDER BY conname`)).rows;
assert.equal(cons.length, 2); checks++;
assert.ok(cons.every(c => c.convalidated === false), JSON.stringify(cons)); checks++;
await refuses(`INSERT INTO tasks(business_id, title, handed_by_contact_id) VALUES ($1, 'x', $2)`,
  [b1, 'cccccccc-9999-4999-8999-999999999999'], /tasks_handed_by_contact_id_fkey|not in this church/);

// The people are the task's own church's, on insert and on update.
await ok(`INSERT INTO tasks(business_id, title, assigned_contact_id, handed_by_contact_id) VALUES ($1, 'given', $2, $3)`,
  [b1, c1, c3]);
await refuses(`INSERT INTO tasks(business_id, title, assigned_contact_id, handed_by_contact_id) VALUES ($1, 'x', $2, $3)`,
  [b1, c1, c2], /handed it out is not in this church/);
await refuses(`UPDATE tasks SET raised_by_contact_id = $1 WHERE title = 'given'`, [c2], /sent it up is not in this church/);
await ok(`UPDATE tasks SET raised_by_contact_id = $1 WHERE title = 'given'`, [c3]);
await refuses(`UPDATE tasks SET business_id = $1 WHERE title = 'given'`, [b2], /not in this church/);
await ok(`UPDATE tasks SET status = 'done' WHERE title = 'given'`, []);      // an update that names neither: no check

// A person deleted lets go of what they handed out and sent up.
await ok('DELETE FROM contacts WHERE id = $1', [c3]);
assert.deepEqual(await one(`SELECT handed_by_contact_id, raised_by_contact_id FROM tasks WHERE title = 'given'`),
  { handed_by_contact_id: null, raised_by_contact_id: null }); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_trigger WHERE tgname = 'tasks_people_same_business'
  AND NOT tgisinternal`)).n, 1); checks++;

console.log(`church lead assignments db: ${checks} checks passed`);

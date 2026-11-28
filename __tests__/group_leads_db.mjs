// Every group has a leader, on a real Postgres (PGlite): supabase/APPLY-2026-11-28-group-leads.sql.
// A co-leader is a leader row with co_leader; a row that stops leading stops
// being one, and a member row never is. A group answers to one person of its
// own church; a class group points at its own church's class; a ministry's
// leader is one of its own church's people. Deleting the person or the class
// lets go. Existing rows read their defaults. Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_leads_db.mjs
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
const dana = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const c1 = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', c2 = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE TABLE public.academy_courses(id uuid PRIMARY KEY, business_id uuid NOT NULL, title text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$5,$6),($7,$8,$9),($10,$11,$12)',
  [ana, b1, 'Ana Rivera', ben, b1, 'Ben Stone', dana, b1, 'Dana Owens', elsewhere, b2, 'Sam Other']);
await db.query('INSERT INTO academy_courses VALUES ($1,$2,$3),($4,$5,$6)', [c1, b1, 'New Members', c2, b2, 'Elsewhere class']);
await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
await db.exec(await sql('APPLY-2026-10-26-worship-ministries.sql').catch(() => `
  CREATE TABLE public.worship_ministries(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid NOT NULL,
    name text NOT NULL, leader_name text NOT NULL DEFAULT '', leader_email text NOT NULL DEFAULT '');`));
const g1 = (await db.query(`INSERT INTO groups(business_id, name, kind) VALUES ($1,'Parking Team','team') RETURNING id`, [b1])).rows[0].id;
const g2 = (await db.query(`INSERT INTO groups(business_id, name, kind) VALUES ($1,'Elsewhere','small_group') RETURNING id`, [b2])).rows[0].id;
await db.query(`INSERT INTO group_members(group_id, contact_id, business_id, role) VALUES ($1,$2,$3,'leader'),($1,$4,$3,'member')`,
  [g1, ana, b1, ben]);
const m1 = (await db.query(`INSERT INTO worship_ministries(business_id, name, leader_name) VALUES ($1,'Youth','Dana') RETURNING id`, [b1])).rows[0].id;

await db.exec(await sql('APPLY-2026-11-28-group-leads.sql'));
await db.exec(await sql('APPLY-2026-11-28-group-leads.sql'));   // twice

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

// Existing rows read their defaults.
assert.deepEqual(await one(`SELECT co_leader FROM group_members WHERE contact_id = $1`, [ana]), { co_leader: false }); checks++;
assert.deepEqual(await one(`SELECT answers_to_contact_id, course_id, serve_option FROM groups WHERE id = $1`, [g1]),
  { answers_to_contact_id: null, course_id: null, serve_option: null }); checks++;
assert.deepEqual(await one(`SELECT leader_contact_id FROM worship_ministries WHERE id = $1`, [m1]), { leader_contact_id: null }); checks++;

// A co-leader is a leader row; making them a member again lets the co-leader go.
await db.query(`UPDATE group_members SET role = 'leader', co_leader = true WHERE group_id = $1 AND contact_id = $2`, [g1, ben]);
assert.deepEqual(await one(`SELECT role, co_leader FROM group_members WHERE contact_id = $1`, [ben]), { role: 'leader', co_leader: true }); checks++;
await db.query(`UPDATE group_members SET role = 'member' WHERE group_id = $1 AND contact_id = $2`, [g1, ben]);
assert.deepEqual(await one(`SELECT role, co_leader FROM group_members WHERE contact_id = $1`, [ben]), { role: 'member', co_leader: false }); checks++;
// A member row is never a co-leader, even when a write says so.
await db.query(`UPDATE group_members SET co_leader = true WHERE group_id = $1 AND contact_id = $2`, [g1, ben]);
assert.equal((await one(`SELECT co_leader FROM group_members WHERE contact_id = $1`, [ben])).co_leader, false); checks++;
await db.query(`INSERT INTO group_members(group_id, contact_id, business_id, role, co_leader) VALUES ($1,$2,$3,'member',true)`, [g1, dana, b1]);
assert.equal((await one(`SELECT co_leader FROM group_members WHERE contact_id = $1`, [dana])).co_leader, false); checks++;

// The group answers to one person of its own church.
await db.query(`UPDATE groups SET answers_to_contact_id = $2 WHERE id = $1`, [g1, dana]); checks++;
await refuses(`UPDATE groups SET answers_to_contact_id = $2 WHERE id = $1`, [g1, elsewhere], /not in this church/);
await refuses(`INSERT INTO groups(business_id, name, answers_to_contact_id) VALUES ($1,'X',$2)`, [b2, ana], /not in this church/);
// A group can't move to another church carrying its person or its class.
await refuses(`UPDATE groups SET business_id = $2 WHERE id = $1`, [g1, b2], /not in this church/);

// A class group points at its own church's class.
await db.query(`UPDATE groups SET course_id = $2 WHERE id = $1`, [g2, c2]); checks++;
await refuses(`UPDATE groups SET course_id = $2 WHERE id = $1`, [g1, c2], /not in this church/);
await db.query(`UPDATE groups SET course_id = $2 WHERE id = $1`, [g1, c1]); checks++;

// A team's Serve choice: 1 to 120 characters, never blank.
await db.query(`UPDATE groups SET serve_option = 'Parking: lots and doors' WHERE id = $1`, [g1]); checks++;
await refuses(`UPDATE groups SET serve_option = '  ' WHERE id = $1`, [g1], /check constraint/);
await refuses(`UPDATE groups SET serve_option = $2 WHERE id = $1`, [g1, 'x'.repeat(121)], /check constraint/);

// A ministry's leader is one of its own church's people.
await db.query(`UPDATE worship_ministries SET leader_contact_id = $2 WHERE id = $1`, [m1, dana]); checks++;
await refuses(`UPDATE worship_ministries SET leader_contact_id = $2 WHERE id = $1`, [m1, elsewhere], /not in this church/);

// An unrelated change never re-checks (a rename keeps working).
await db.query(`UPDATE groups SET name = 'Parking & Doors' WHERE id = $1`, [g1]); checks++;

// Deleting the person or the class lets go.
await db.query(`DELETE FROM group_members WHERE contact_id = $1`, [dana]);
await db.query(`DELETE FROM contacts WHERE id = $1`, [dana]);
assert.deepEqual(await one(`SELECT answers_to_contact_id FROM groups WHERE id = $1`, [g1]), { answers_to_contact_id: null }); checks++;
assert.deepEqual(await one(`SELECT leader_contact_id FROM worship_ministries WHERE id = $1`, [m1]), { leader_contact_id: null }); checks++;
await db.query(`DELETE FROM academy_courses WHERE id = $1`, [c1]);
assert.deepEqual(await one(`SELECT course_id FROM groups WHERE id = $1`, [g1]), { course_id: null }); checks++;

// The functions are not for the browser roles.
const grants = await db.query(`SELECT p.proname, has_function_privilege('anon', p.oid, 'execute') AS anon,
  has_function_privilege('authenticated', p.oid, 'execute') AS auth FROM pg_proc p
  WHERE p.proname IN ('group_members_co_leader', 'group_leads_same_business') ORDER BY 1`);
assert.deepEqual(grants.rows.map(r => [r.proname, r.anon, r.auth]),
  [['group_leads_same_business', false, false], ['group_members_co_leader', false, false]]); checks++;

console.log(`group leads: ${checks} checks passed`);

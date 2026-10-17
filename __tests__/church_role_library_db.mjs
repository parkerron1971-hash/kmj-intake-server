// The role library on a real Postgres (PGlite): supabase/APPLY-2026-10-17-church-role-library.sql
// over the leaders tables it extends. Rows go through every trigger it adds
// (the first leaders migration passed a DDL-only probe and refused every row:
// APPLY-2026-10-17-church-leaders-trigger-fix.sql):
//   church_role_defs   a role answers to a role of the same church, never itself;
//                      a class it needs is the same church's
//   church_leader_roles a church's own role keys, shaped
//   ministry_care_requests  a request is handed to a member only when the person
//                      shared it, never when it needs a pastor, and only to the
//                      same church's member; every other row still saves
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_role_library_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const dana = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', ann = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const sam = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const course1 = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', course2 = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE TABLE public.academy_courses(id uuid PRIMARY KEY, business_id uuid NOT NULL, title text);
  CREATE TABLE public.ministry_care_requests(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES public.businesses(id), form_id uuid, submission jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'new', contact_id uuid, prayed_at timestamptz, updated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now());`);
await db.query('INSERT INTO businesses VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$2,$5),($6,$7,$8)', [dana, b1, 'Dana', ann, 'Ann', sam, b2, 'Sam']);
await db.query('INSERT INTO academy_courses VALUES ($1,$2,$3),($4,$5,$6)', [course1, b1, 'The Making', course2, b2, 'Other']);
const old = await db.query(`INSERT INTO ministry_care_requests(business_id, submission) VALUES ($1, '{"prayer_request":"before"}') RETURNING id`, [b1]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-17-church-leaders.sql'));
await db.exec(await sql('APPLY-2026-10-17-church-leaders-trigger-fix.sql'));
await db.exec(await sql('APPLY-2026-10-17-church-role-library.sql'));
await db.exec(await sql('APPLY-2026-10-17-church-role-library.sql'));   // idempotent

// Roles and the chain.
const lead = (await db.query(`INSERT INTO church_role_defs(business_id, key, title, job, handles)
  VALUES ($1,'pastor','Lead Pastor','senior','{leftover}') RETURNING id`, [b1])).rows[0].id;
const il = (await db.query(`INSERT INTO church_role_defs(business_id, key, title, job, reports_to, handles, needs_class)
  VALUES ($1,'intercessor_leader','Intercessor leader','prayer',$2,'{prayer_shared}',$3) RETURNING id`, [b1, lead, course1])).rows[0].id;
assert.ok(il); checks++;
await refuses(`UPDATE church_role_defs SET reports_to = id WHERE id = $1`, [il], /answer to itself/);
const other = (await db.query(`INSERT INTO church_role_defs(business_id, key, title, job) VALUES ($1,'pastor','Pastor','senior') RETURNING id`, [b2])).rows[0].id;
await refuses(`UPDATE church_role_defs SET reports_to = $2 WHERE id = $1`, [il, other], /not in this business/);
await refuses(`UPDATE church_role_defs SET needs_class = $2 WHERE id = $1`, [il, course2], /class is not in this business/);
await refuses(`INSERT INTO church_role_defs(business_id, key, title, job) VALUES ($1,'pastor','Again','senior')`, [b1], /duplicate key/);
await refuses(`INSERT INTO church_role_defs(business_id, key, title, job) VALUES ($1,'x','X','wizard')`, [b1], /check constraint/);
await db.query(`INSERT INTO church_role_settings(business_id, church_type, guessed_type) VALUES ($1,'nondenom','nondenom')`, [b1]);
checks++;

// Holders carry the church's own keys; a key with the wrong shape is refused.
await db.query(`INSERT INTO church_leader_roles(business_id, contact_id, role, status) VALUES ($1,$2,'intercessor_leader','active')`, [b1, dana]);
await db.query(`UPDATE church_leader_roles SET term_ends_at = now() + interval '1 year' WHERE contact_id = $1`, [dana]);
checks++;
await refuses(`INSERT INTO church_leader_roles(business_id, contact_id, role) VALUES ($1,$2,'Church Mother')`, [b1, ann], /role_key_shape/);
const fu = (await db.query(`INSERT INTO church_follow_ups(business_id, contact_id, card_key, path_kind, leader_contact_id, leader_role)
  VALUES ($1,$2,'form:x','serve',$3,'intercessor_leader') RETURNING id`, [b1, ann, dana])).rows[0].id;
for (const kind of ['overseer_told', 'next_up']) {
  await db.query(`INSERT INTO church_follow_up_notes(business_id, follow_up_id, author_kind, kind) VALUES ($1,$2,'chief',$3)`, [b1, fu, kind]);
  checks++;
}

// Prayer: handed only when shared, never when it needs a pastor, only to the church's own.
const shared = (await db.query(`INSERT INTO ministry_care_requests(business_id, submission, prayer_team, wants_call)
  VALUES ($1, '{"prayer_request":"surgery"}', true, true) RETURNING id`, [b1])).rows[0].id;
await db.query(`UPDATE ministry_care_requests SET leader_contact_id = $2, leader_role = 'intercessor_leader',
  leader_due_at = now() + interval '1 day' WHERE id = $1`, [shared, dana]);
await db.query(`UPDATE ministry_care_requests SET leader_prayed_at = now(), leader_late_level = 3 WHERE id = $1`, [shared]);
checks++;
await db.query(`UPDATE ministry_care_requests SET status = 'reviewed' WHERE id = $1`, [old.rows[0].id]);
checks++;   // a row from before the migration still changes
await refuses(`INSERT INTO ministry_care_requests(business_id, leader_contact_id) VALUES ($1,$2)`, [b1, dana],
  /shared with the prayer team/);
await refuses(`INSERT INTO ministry_care_requests(business_id, prayer_team, needs_pastor, leader_contact_id) VALUES ($1,true,true,$2)`,
  [b1, dana], /needs a pastor/);
await refuses(`UPDATE ministry_care_requests SET leader_contact_id = $2 WHERE id = $1`, [shared, sam], /not in this business/);
await refuses(`UPDATE ministry_care_requests SET leader_late_level = 4 WHERE id = $1`, [shared], /leader_late_level/);
const back = await db.query(`UPDATE ministry_care_requests SET leader_contact_id = NULL WHERE id = $1 RETURNING id`, [shared]);
assert.equal(back.rows.length, 1); checks++;

// Server-only: no grant for the browser's roles.
const grants = (await db.query(`SELECT has_table_privilege('anon','public.church_role_defs','select') a,
  has_table_privilege('authenticated','public.church_role_settings','select') b`)).rows[0];
assert.deepEqual(grants, { a: false, b: false }); checks++;

console.log(`church role library db: ${checks} checks passed`);

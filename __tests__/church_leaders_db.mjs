// Leaders & follow-up on a real Postgres (PGlite): the three tables from
// supabase/APPLY-2026-10-17-church-leaders.sql take a role, a follow-up
// with its leader, and a note, and refuse a person, leader or follow-up
// from another church. The first file alone refused every role and note
// (its trigger read new.leader_contact_id on tables without that column);
// APPLY-2026-10-17-church-leaders-trigger-fix.sql is what production runs.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_leaders_db.mjs
// (CI installs PGlite into $RUNNER_TEMP and sets PGLITE_MODULE; locally the
// fallback is output/marketing-qa, like the other database checks.)
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const member = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', pastor = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id),
    name text, email text, phone text);`);
await db.query('INSERT INTO businesses VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3,$4,$5),($6,$2,$7,$8,$5),($9,$10,$11,$12,$5)',
  [member, b1, 'Dana Reed', 'dana@example.org', '', pastor, 'Pastor Lee', 'lee@example.org', elsewhere, b2, 'Sam Other', 'sam@example.org']);
let checks = 0;

const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const addRole = [`INSERT INTO church_leader_roles(business_id, contact_id, role, scope, status, invited_by)
  VALUES ($1,$2,'pastor','','invited',$3) RETURNING id`];

// The first file alone: the bug Kevin hit ("assign and save leaders with
// invite is not working"). If this stops failing, the check below is no
// longer testing the fix.
await db.exec(await sql('APPLY-2026-10-17-church-leaders.sql'));
await refuses(addRole[0], [b1, pastor, member], /has no field "leader_contact_id"/);

// The fix, applied twice (it is idempotent).
await db.exec(await sql('APPLY-2026-10-17-church-leaders-trigger-fix.sql'));
await db.exec(await sql('APPLY-2026-10-17-church-leaders-trigger-fix.sql'));

const role = (await db.query(addRole[0], [b1, pastor, member])).rows[0];
assert.ok(role.id); checks++;
// Saying yes on the member page is an update through the same trigger.
const yes = await db.query(`UPDATE church_leader_roles SET status='active', answered_at=now() WHERE id=$1 RETURNING status`, [role.id]);
assert.equal(yes.rows[0].status, 'active'); checks++;
const fu = (await db.query(`INSERT INTO church_follow_ups(business_id, contact_id, card_key, path_kind, leader_contact_id, leader_role)
  VALUES ($1,$2,'baptism','baptism',$3,'pastor') RETURNING id`, [b1, member, pastor])).rows[0];
assert.ok(fu.id); checks++;
const note = await db.query(`INSERT INTO church_follow_up_notes(business_id, follow_up_id, author_kind, kind, body)
  VALUES ($1,$2,'chief','assigned','Handed to Pastor Lee.') RETURNING id`, [b1, fu.id]);
assert.equal(note.rows.length, 1); checks++;
const handOn = await db.query(`UPDATE church_follow_ups SET leader_contact_id=NULL, leader_role='' WHERE id=$1 RETURNING id`, [fu.id]);
assert.equal(handOn.rows.length, 1); checks++;

// Another church's people stay out.
await refuses(addRole[0], [b1, elsewhere, member], /That person is not in this business/);
await refuses(`UPDATE church_follow_ups SET leader_contact_id=$2 WHERE id=$1`, [fu.id, elsewhere], /That leader is not in this business/);
await refuses(`INSERT INTO church_follow_up_notes(business_id, follow_up_id, author_kind, kind, body)
  VALUES ($1,$2,'office','note','x')`, [b2, fu.id], /That follow-up is not in this business/);

console.log(`church leaders db: ${checks} checks passed`);

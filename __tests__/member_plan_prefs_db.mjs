// A member's choices for a plan, on a real Postgres (PGlite): supabase/APPLY-2026-11-21-member-plan-prefs.sql.
// One row a member a plan: the group they read it with (or on their own), and
// a reminder on a quarter hour (or none). The plan is named as
// member_plan_starts names it; the member and the group are the row's
// church's; a deleted group lets the choice go, a member who leaves takes
// their rows. No app login reads or writes it (no policy, browser roles
// revoked). Applied twice (it is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/member_plan_prefs_db.mjs
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
const elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const dev = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$5,$6),($7,$8,$9)',
  [ana, b1, 'Ana Rivera', ben, b1, 'Ben Stone', elsewhere, b2, 'Sam Other']);
await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
const g1 = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Young Adults') RETURNING id`, [b1])).rows[0].id;
const g2 = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Elsewhere') RETURNING id`, [b2])).rows[0].id;
await db.exec(await sql('APPLY-2026-11-21-member-plan-prefs.sql'));
await db.exec(await sql('APPLY-2026-11-21-member-plan-prefs.sql'));   // twice

let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const put = `INSERT INTO member_plan_prefs(business_id, contact_id, plan, group_id, remind_at) VALUES ($1,$2,$3,$4,$5)
  ON CONFLICT (business_id, contact_id, plan) DO UPDATE SET group_id = excluded.group_id, remind_at = excluded.remind_at,
  updated_at = now() RETURNING group_id, remind_at, reminded_on`;

// A topic plan with her group, reminded at 7:30 PM; a devotional on her own, no reminder.
const r1 = (await db.query(put, [b1, ana, 'reading:topic-anxiety', g1, '19:30'])).rows[0];
assert.deepEqual([r1.group_id, r1.remind_at, r1.reminded_on], [g1, '19:30:00', null]); checks++;
await db.query(put, [b1, ana, `devotional:${dev}`, null, null]); checks++;
await db.query(put, [b1, ben, 'reading:topic-anxiety', g1, '07:00']); checks++;
// Saved again: still one row, the new choice.
const r2 = (await db.query(put, [b1, ana, 'reading:topic-anxiety', null, '06:45'])).rows[0];
assert.deepEqual([r2.group_id, r2.remind_at], [null, '06:45:00']); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM member_plan_prefs WHERE contact_id = $1`, [ana])).rows[0].n, 2); checks++;

// The plan is named as member_plan_starts names it.
await refuses(put, [b1, ana, 'topic-anxiety', null, null], /check constraint/);
await refuses(put, [b1, ana, 'reading:Gospels 30', null, null], /check constraint/);
await refuses(put, [b1, ana, 'devotional:not-an-id', null, null], /check constraint/);
// A reminder on a quarter hour.
await refuses(put, [b1, ana, 'reading:gospels-30', null, '19:20'], /member_plan_prefs_quarter/);
await refuses(put, [b1, ana, 'reading:gospels-30', null, '19:30:15'], /member_plan_prefs_quarter/);
await db.query(put, [b1, ana, 'reading:gospels-30', null, '00:00']); checks++;

// The sweep claims a day by moving reminded_on: once.
const claim = `UPDATE member_plan_prefs SET reminded_on = $3 WHERE business_id = $1 AND contact_id = $2
  AND plan = 'reading:topic-anxiety' AND (reminded_on IS NULL OR reminded_on < $3) RETURNING plan`;
assert.equal((await db.query(claim, [b1, ana, '2026-11-22'])).rows.length, 1); checks++;
assert.equal((await db.query(claim, [b1, ana, '2026-11-22'])).rows.length, 0); checks++;

// Inside its own church.
await refuses(put, [b1, elsewhere, 'reading:gospels-30', null, null], /That person is not in this business/);
await refuses(put, [b1, ana, 'reading:gospels-30', g2, null], /That group is not in this business/);
await refuses(`UPDATE member_plan_prefs SET group_id = $2 WHERE contact_id = $1`, [ben, g2], /That group is not in this business/);
await refuses(`UPDATE member_plan_prefs SET business_id = $2 WHERE contact_id = $1`, [ben, b2], /That person is not in this business/);

// A deleted group lets the choice go; a member who leaves takes their rows.
await db.query('DELETE FROM groups WHERE id = $1', [g1]);
const benRow = (await db.query(`SELECT group_id, remind_at FROM member_plan_prefs WHERE contact_id = $1`, [ben])).rows[0];
assert.deepEqual([benRow.group_id, benRow.remind_at], [null, '07:00:00']); checks++;
await db.query('DELETE FROM contacts WHERE id = $1', [ben]);
assert.equal((await db.query(`SELECT count(*)::int AS n FROM member_plan_prefs WHERE contact_id = $1`, [ben])).rows[0].n, 0); checks++;

// Server-only: RLS on, no policy, nothing granted to the browser roles.
const r = (await db.query(`SELECT relrowsecurity FROM pg_class WHERE relname = 'member_plan_prefs'`)).rows[0];
assert.equal(r.relrowsecurity, true); checks++;
assert.equal((await db.query(`SELECT count(*)::int AS n FROM pg_policies WHERE tablename = 'member_plan_prefs'`)).rows[0].n, 0); checks++;
const grants = (await db.query(`SELECT grantee FROM information_schema.role_table_grants
  WHERE table_name = 'member_plan_prefs' AND grantee IN ('anon','authenticated','PUBLIC')`)).rows;
assert.deepEqual(grants, []); checks++;
await db.exec(`SET ROLE authenticated`);
await refuses('SELECT * FROM member_plan_prefs', [], /permission denied/);
await db.exec(`RESET ROLE; SET ROLE anon`);
await refuses('SELECT * FROM member_plan_prefs', [], /permission denied/);
await db.exec(`RESET ROLE`);

console.log(`member plan prefs db: ${checks} checks passed`);

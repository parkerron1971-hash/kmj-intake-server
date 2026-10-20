// A group's gatherings, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-gatherings.sql. The regular time is a real
// weekday and clock; the address and note have limits; an RSVP is one answer
// per person per gathering, this church's own; attendance says who said they
// were there (the office's own rows read 'office'). Applied twice (it is
// idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_gatherings_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const tasha = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$5,$6)', [tasha, b1, 'Tasha Williams', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Sisters') RETURNING id`, [b1])).rows[0].id;
const m = (await db.query(`INSERT INTO group_meetings(business_id, group_id, met_on) VALUES ($1,$2,'2026-10-15') RETURNING id`, [b1, g])).rows[0].id;
await db.query(`INSERT INTO group_meeting_attendance(meeting_id, contact_id, business_id) VALUES ($1,$2,$3)`, [m, tasha, b1]);
await db.exec(await sql('APPLY-2026-10-20-group-gatherings.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-gatherings.sql'));   // twice

// Attendance the office already took reads as the office's.
assert.equal((await db.query('SELECT how FROM group_meeting_attendance')).rows[0].how, 'office'); checks++;
await refuses(`UPDATE group_meeting_attendance SET how = 'guessed'`, [], /check constraint/);

// The regular time.
const g0 = (await db.query('SELECT meet_day, meet_time, meet_address, meet_skips FROM groups WHERE id=$1', [g])).rows[0];
assert.deepEqual([g0.meet_day, g0.meet_time, g0.meet_address, g0.meet_skips], [null, null, '', []]); checks++;
await db.query(`UPDATE groups SET meet_day = 3, meet_time = '19:00', meet_skips = '{2026-11-26}' WHERE id=$1`, [g]); checks++;
await refuses(`UPDATE groups SET meet_day = 7 WHERE id=$1`, [g], /check constraint/);
await refuses(`UPDATE groups SET meet_address = $2 WHERE id=$1`, [g, 'x'.repeat(201)], /check constraint/);
await refuses(`UPDATE groups SET meet_note = $2 WHERE id=$1`, [g, 'x'.repeat(301)], /check constraint/);

// RSVPs: one answer per person per gathering, this church's own.
const rsvp = `INSERT INTO group_rsvps(business_id, group_id, met_on, contact_id, answer) VALUES ($1,$2,'2026-10-22',$3,$4)`;
await db.query(rsvp, [b1, g, tasha, 'going']); checks++;
await refuses(rsvp, [b1, g, tasha, 'maybe'], /duplicate key|unique/);
await refuses(rsvp.replace("'2026-10-22'", "'2026-10-29'"), [b1, g, tasha, 'sure'], /check constraint/);
await refuses(rsvp.replace("'2026-10-22'", "'2026-10-29'"), [b1, g, elsewhere, 'going'], /That person is not in this business/);
await refuses(rsvp.replace("'2026-10-22'", "'2026-10-29'"), [b2, g, elsewhere, 'going'], /That group is not in this business/);

// Members never write RSVPs directly; the office reads them.
const grants = (await db.query(`SELECT grantee, privilege_type FROM information_schema.role_table_grants
  WHERE table_name = 'group_rsvps' AND grantee IN ('anon','authenticated')`)).rows;
assert.deepEqual(grants.map(r => `${r.grantee}:${r.privilege_type}`).sort(), ['authenticated:SELECT']); checks++;

console.log(`group gatherings db: ${checks} checks passed`);

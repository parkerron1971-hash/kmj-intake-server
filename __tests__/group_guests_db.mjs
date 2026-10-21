// First-time guests by name, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-guests.sql. A guest has a first name of a
// sensible length; belongs to one of this group's own gatherings; whoever
// added them and whoever they became are this church's own; members never
// write it, and the office may only link who they became. Applied twice.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_guests_db.mjs
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
const other = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Other') RETURNING id`, [b1])).rows[0].id;
const m = (await db.query(`INSERT INTO group_meetings(business_id, group_id, met_on) VALUES ($1,$2,'2026-10-22') RETURNING id`, [b1, g])).rows[0].id;
await db.exec(await sql('APPLY-2026-10-20-group-guests.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-guests.sql'));   // twice

const add = `INSERT INTO group_meeting_guests(business_id, group_id, meeting_id, first_name, phone, added_by) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id`;
const ana = (await db.query(add, [b1, g, m, 'Ana', '555-0100', tasha])).rows[0].id; checks++;
await refuses(add, [b1, g, m, '   ', '', tasha], /check constraint/);
await refuses(add, [b1, g, m, 'x'.repeat(41), '', tasha], /check constraint/);
await refuses(add, [b1, other, m, 'Ben', '', tasha], /not this group's/);              // another group's gathering
await refuses(add, [b1, g, m, 'Ben', '', elsewhere], /not in this business/);
await refuses(`UPDATE group_meeting_guests SET contact_id = $2 WHERE id=$1`, [ana, elsewhere], /not in this business/);
await db.query(`UPDATE group_meeting_guests SET contact_id = $2 WHERE id=$1`, [ana, tasha]); checks++;   // the office links who they became

const grants = (await db.query(`SELECT grantee, privilege_type FROM information_schema.role_table_grants
  WHERE table_name = 'group_meeting_guests' AND grantee IN ('anon','authenticated')`)).rows;
assert.deepEqual(grants.map(r => `${r.grantee}:${r.privilege_type}`).sort(), ['authenticated:SELECT']); checks++;
const cols = (await db.query(`SELECT column_name FROM information_schema.column_privileges
  WHERE table_name = 'group_meeting_guests' AND grantee = 'authenticated' AND privilege_type = 'UPDATE'`)).rows.map(r => r.column_name);
assert.deepEqual(cols, ['contact_id']); checks++;                                       // only who they became

await db.query(`DELETE FROM group_meetings WHERE id=$1`, [m]);
assert.equal((await db.query('SELECT count(*)::int n FROM group_meeting_guests')).rows[0].n, 0); checks++;

console.log(`group guests db: ${checks} checks passed`);

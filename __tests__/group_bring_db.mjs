// "Bring something", on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-group-bring.sql. A thing to bring has a name of
// a sensible length; it belongs to this church's own group and people; one
// thing each per gathering (a second open thing is fine, a second claim by
// the same person isn't); members never write directly. Applied twice (it
// is idempotent).
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/group_bring_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '22222222-2222-4222-8222-222222222222';
const tasha = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', monique = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const elsewhere = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA IF NOT EXISTS auth;
  CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
  CREATE TABLE public.businesses(id uuid PRIMARY KEY, owner_id uuid);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY, business_id uuid NOT NULL REFERENCES public.businesses(id), name text);
  CREATE FUNCTION public.is_business_writer(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';
  CREATE FUNCTION public.is_business_member(b uuid) RETURNS boolean LANGUAGE sql AS 'select false';`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
await db.query('INSERT INTO contacts VALUES ($1,$2,$3),($4,$5,$6),($7,$8,$9)',
  [tasha, b1, 'Tasha Williams', monique, b1, 'Monique Brown', elsewhere, b2, 'Sam Other']);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-09-30-groups.sql'));
const g = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Sisters') RETURNING id`, [b1])).rows[0].id;
const g2 = (await db.query(`INSERT INTO groups(business_id, name) VALUES ($1,'Theirs') RETURNING id`, [b2])).rows[0].id;
await db.exec(await sql('APPLY-2026-10-20-group-bring.sql'));
await db.exec(await sql('APPLY-2026-10-20-group-bring.sql'));   // twice

const add = `INSERT INTO group_bring(business_id, group_id, met_on, what, added_by) VALUES ($1,$2,$3,$4,$5) RETURNING id`;
const main = (await db.query(add, [b1, g, '2026-10-22', 'Main dish', tasha])).rows[0].id;
const greens = (await db.query(add, [b1, g, '2026-10-22', 'Greens', tasha])).rows[0].id;
const dessert = (await db.query(add, [b1, g, '2026-10-22', 'Dessert', tasha])).rows[0].id;
const later = (await db.query(add, [b1, g, '2026-11-19', 'Drinks', tasha])).rows[0].id; checks++;
assert.equal((await db.query('SELECT contact_id FROM group_bring WHERE id=$1', [main])).rows[0].contact_id, null); checks++;

// A sensible name.
await refuses(add, [b1, g, '2026-10-22', '   ', tasha], /check constraint/);
await refuses(add, [b1, g, '2026-10-22', 'x'.repeat(61), tasha], /check constraint/);

// This church's own group and people.
await refuses(add, [b1, g2, '2026-10-22', 'Rolls', tasha], /That group is not in this business/);
await refuses(add, [b1, g, '2026-10-22', 'Rolls', elsewhere], /That person is not in this business/);
await refuses(`UPDATE group_bring SET contact_id = $2 WHERE id=$1`, [main, elsewhere], /That person is not in this business/);

// One thing each per gathering; another gathering is its own.
await db.query(`UPDATE group_bring SET contact_id = $2, claimed_at = now() WHERE id=$1`, [main, monique]); checks++;
await refuses(`UPDATE group_bring SET contact_id = $2 WHERE id=$1`, [greens, monique], /duplicate key|unique/);
await db.query(`UPDATE group_bring SET contact_id = $2 WHERE id=$1`, [later, monique]); checks++;
await db.query(`UPDATE group_bring SET contact_id = $2 WHERE id=$1`, [greens, tasha]); checks++;
// Open things are many (null holds nothing).
assert.equal((await db.query(`SELECT count(*)::int n FROM group_bring WHERE met_on='2026-10-22' AND contact_id IS NULL`)).rows[0].n, 1); checks++;
assert.equal(dessert.length, 36); checks++;

// Someone deleted from the church lets go of what they held.
await db.query(`DELETE FROM contacts WHERE id=$1`, [monique]);
assert.equal((await db.query('SELECT contact_id FROM group_bring WHERE id=$1', [main])).rows[0].contact_id, null); checks++;

// Members never write it directly; the office reads it.
const grants = (await db.query(`SELECT grantee, privilege_type FROM information_schema.role_table_grants
  WHERE table_name = 'group_bring' AND grantee IN ('anon','authenticated')`)).rows;
assert.deepEqual(grants.map(r => `${r.grantee}:${r.privilege_type}`).sort(), ['authenticated:SELECT']); checks++;

// The group goes, its lists go.
await db.query(`DELETE FROM groups WHERE id=$1`, [g]);
assert.equal((await db.query('SELECT count(*)::int n FROM group_bring')).rows[0].n, 0); checks++;

console.log(`group bring db: ${checks} checks passed`);

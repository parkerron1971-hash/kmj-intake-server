// The church's own picks on the map, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-23-church-areas.sql. A role or a team is placed in
// one of the eight areas; a made-up area, a kind that isn't role or team, or
// an empty or overlong key is refused; one role (or team) has one place per
// church, and placing it again replaces it; a church that leaves takes its
// picks with it; the browser's roles can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_areas_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-23-church-areas.sql'));
await db.exec(await sql('APPLY-2026-10-23-church-areas.sql'));   // idempotent

const put = `INSERT INTO church_area_places(business_id, kind, key, area) VALUES ($1, $2, $3, $4)
  ON CONFLICT (business_id, kind, key) DO UPDATE SET area = excluded.area, updated_at = now() RETURNING *`;
const areas = ['worship_media', 'people_care', 'giving_money', 'kids_youth', 'groups_classes',
  'messages_safety', 'website_outreach', 'office'];
for (const area of areas) {
  await db.query(put, [b1, 'team', `team ${area}`, area]); checks++;
}
await refuses(put, [b1, 'role', 'armor_bearer', 'the_moon'], /check constraint/);
await refuses(put, [b1, 'person', 'armor_bearer', 'office'], /check constraint/);
await refuses(put, [b1, 'role', '', 'office'], /check constraint/);
await refuses(put, [b1, 'role', 'x'.repeat(81), 'office'], /check constraint/);

// One place each: placing it again moves it; the same key in another church is its own.
await db.query(put, [b1, 'role', 'armor_bearer', 'people_care']);
await db.query(put, [b1, 'role', 'armor_bearer', 'worship_media']);
await db.query(put, [b2, 'role', 'armor_bearer', 'office']);
const mine = await db.query(`SELECT area FROM church_area_places WHERE business_id = $1 AND kind = 'role' AND key = 'armor_bearer'`, [b1]);
assert.deepEqual(mine.rows.map(r => r.area), ['worship_media']); checks++;
// A role and a team may share a key.
await db.query(put, [b1, 'team', 'armor_bearer', 'office']); checks++;

// A church that leaves takes its picks.
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_area_places WHERE business_id = $1', [b1])).rows[0].n, 0); checks++;
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_area_places')).rows[0].n, 1); checks++;

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM church_area_places', [], /permission denied/);
  await refuses(`INSERT INTO church_area_places(business_id, kind, key, area) VALUES ('${b2}', 'role', 'pastor', 'office')`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church_area_places: ${checks} checks passed`);

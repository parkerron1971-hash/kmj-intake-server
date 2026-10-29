// Keepers and keys, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-keys.sql. A keeper keeps one of the three
// guarded areas, once per person; an ask is for a guarded area, starts as
// asked, takes only the known states and ways of opening, and keeps its
// reason short; a church that leaves takes its keepers and asks with it;
// the browser's roles can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_keys_db.mjs
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
const t = '00000000-0000-4000-8000-000000000002';
const p = '00000000-0000-4000-8000-000000000003';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-27-church-keys.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-keys.sql'));   // idempotent

// Keepers: the three guarded areas, once per person and area.
const keep = 'INSERT INTO church_keepers(business_id, area, user_id) VALUES ($1, $2, $3) RETURNING *';
for (const area of ['giving_money', 'kids_youth', 'people_care']) {
  const row = (await db.query(keep, [b1, area, t])).rows[0];
  assert.ok(row.starts_at && row.ends_at === null, 'a keeper starts now and has no end'); checks++;
}
await refuses(keep, [b1, 'office', p], /check constraint/);
await refuses(keep, [b1, 'giving_money', t], /duplicate key/);
await db.query(`INSERT INTO church_keepers(business_id, area, user_id, starts_at) VALUES ($1, 'giving_money', $2, now() + interval '7 days')
  ON CONFLICT (business_id, area, user_id) DO UPDATE SET starts_at = excluded.starts_at`, [b1, p]); checks++;

// Keys: asked by default, known states and ways only, a short reason.
const ask = `INSERT INTO church_area_keys(business_id, area, user_id, reason, code_hash) VALUES ($1, $2, $3, $4, 'h') RETURNING *`;
const key = (await db.query(ask, [b1, 'giving_money', p, 'Year-end statements'])).rows[0];
assert.equal(key.status, 'asked'); assert.equal(key.code_tries, 0); assert.ok(key.asked_at && key.id); checks++;
await refuses(ask, [b1, 'office', p, ''], /check constraint/);
await refuses(ask, [b1, 'giving_money', p, 'x'.repeat(301)], /check constraint/);
await refuses(`UPDATE church_area_keys SET status = 'maybe' WHERE id = $1`, [key.id], /check constraint/);
await refuses(`UPDATE church_area_keys SET how = 'shout' WHERE id = $1`, [key.id], /check constraint/);
await db.query(`UPDATE church_area_keys SET status = 'open', how = 'code', opens_until = now() + interval '1 hour' WHERE id = $1`, [key.id]); checks++;

// A church that leaves takes its keepers and asks; the other church keeps its own.
await db.query(keep, [b2, 'giving_money', t]);
await db.query(ask, [b2, 'kids_youth', p, '']);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
for (const table of ['church_keepers', 'church_area_keys']) {
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM ${table} WHERE business_id = $1`, [b1])).rows[0].n, 0); checks++;
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM ${table}`)).rows[0].n, 1); checks++;
}

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const table of ['church_keepers', 'church_area_keys']) {
    await refuses(`SELECT * FROM ${table}`, [], /permission denied/);
  }
  await refuses(`INSERT INTO church_keepers(business_id, area, user_id) VALUES ('${b2}', 'giving_money', '${p}')`, [], /permission denied/);
  await refuses(`UPDATE church_area_keys SET status = 'open'`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church keepers and keys: ${checks} checks passed`);

// Sundays on screens on a real Postgres (PGlite):
// supabase/APPLY-2026-10-19-worship-show.sql. Rows go through every check:
//   worship_services  a service and its items; a blank title, 81 items or
//                     items that aren't a list are refused
//   worship_screens   a screen and its link; a role that isn't one, a link
//                     that's too short or used twice, an impossible size
//   worship_settings  one look a church
//   worship_live      one row a church; rev never below 0; the service it
//                     points at can be deleted (the row stays, pointing nowhere)
// a church that leaves takes all four with it, and the browser's roles can't
// read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/worship_show_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111', b2 = '99999999-9999-4999-8999-999999999999';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1),($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-19-worship-show.sql'));
await db.exec(await sql('APPLY-2026-10-19-worship-show.sql'));   // idempotent

// What worship_show_router.create_service writes.
const items = JSON.stringify([
  { id: 'worship', kind: 'section', title: 'Worship', show: 'all', notes: '', who: '', minutes: null },
  { id: 'well', kind: 'song', song_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', arrangement_id: null, show: 'all', notes: '', who: '', minutes: 5 },
]);
const svc = (await db.query(`INSERT INTO worship_services(business_id, title, starts_at, items) VALUES ($1, 'Sunday, Oct 25', '2026-10-25T15:05:00Z', $2::jsonb) RETURNING *`,
  [b1, items])).rows[0];
assert.equal(svc.is_template, false); assert.equal(svc.notes, ''); assert.equal(svc.archived_at, null); checks += 3;
await refuses(`INSERT INTO worship_services(business_id, title) VALUES ($1, '  ')`, [b1], /check constraint/);
await refuses(`INSERT INTO worship_services(business_id, items) VALUES ($1, '{"a":1}'::jsonb)`, [b1], /check constraint|non-array/);
const many = JSON.stringify(Array.from({ length: 81 }, (_, i) => ({ id: `s${i}`, kind: 'section' })));
await refuses(`INSERT INTO worship_services(business_id, items) VALUES ($1, $2::jsonb)`, [b1, many], /check constraint/);

// Screens, and their links.
const token = 'A'.repeat(43);
await db.query(`INSERT INTO worship_screens(business_id, name, role, width, height, led, token) VALUES ($1, 'LED wall', 'led', 2304, 768, '{"across":12,"down":4,"px":192}', $2)`, [b1, token]);
checks++;
await refuses(`INSERT INTO worship_screens(business_id, name, token) VALUES ($1, 'Twin', $2)`, [b2, token], /duplicate key|unique/);
await refuses(`INSERT INTO worship_screens(business_id, name, role, token) VALUES ($1, 'x', 'ceiling', $2)`, [b1, 'B'.repeat(43)], /check constraint/);
await refuses(`INSERT INTO worship_screens(business_id, name, token) VALUES ($1, 'x', 'short')`, [b1], /check constraint/);
await refuses(`INSERT INTO worship_screens(business_id, name, width, token) VALUES ($1, 'x', 99, $2)`, [b1, 'C'.repeat(43)], /check constraint/);
await refuses(`INSERT INTO worship_screens(business_id, name, token) VALUES ($1, ' ', $2)`, [b1, 'D'.repeat(43)], /check constraint/);

// One look, one live row a church: the upserts the router does.
const upsertLook = `INSERT INTO worship_settings(business_id, look) VALUES ($1, $2::jsonb)
  ON CONFLICT (business_id) DO UPDATE SET look = excluded.look, updated_at = now()`;
await db.query(upsertLook, [b1, '{"size":"big"}']);
await db.query(upsertLook, [b1, '{"size":"small"}']);
assert.equal((await db.query('SELECT look FROM worship_settings WHERE business_id = $1', [b1])).rows[0].look.size, 'small'); checks++;
await refuses(`INSERT INTO worship_settings(business_id, look) VALUES ($1, '[]'::jsonb)`, [b2], /check constraint/);

const upsertLive = `INSERT INTO worship_live(business_id, service_id, state, rev) VALUES ($1, $2, $3::jsonb, $4)
  ON CONFLICT (business_id) DO UPDATE SET service_id = excluded.service_id, state = excluded.state, rev = excluded.rev, updated_at = now()`;
await db.query(upsertLive, [b1, svc.id, '{"slide":0}', 1760900000000]);
await db.query(upsertLive, [b1, svc.id, '{"slide":1}', 1760900000500]);
const live = (await db.query('SELECT * FROM worship_live WHERE business_id = $1', [b1])).rows[0];
assert.equal(live.state.slide, 1); assert.equal(Number(live.rev), 1760900000500); checks += 2;
await refuses(upsertLive, [b2, null, '{}', -1], /check constraint/);

// Deleting a service leaves the live row, pointing nowhere.
await db.query('DELETE FROM worship_services WHERE id = $1', [svc.id]);
assert.equal((await db.query('SELECT service_id FROM worship_live WHERE business_id = $1', [b1])).rows[0].service_id, null); checks++;

// A church that leaves takes all four with it.
await db.query(`INSERT INTO worship_services(business_id) VALUES ($1)`, [b1]);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
for (const t of ['worship_services', 'worship_screens', 'worship_settings', 'worship_live']) {
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM ${t} WHERE business_id = $1`, [b1])).rows[0].n, 0); checks++;
}

// Server-only: the browser's roles see nothing and change nothing.
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const t of ['worship_services', 'worship_screens', 'worship_settings', 'worship_live']) {
    await refuses(`SELECT * FROM ${t}`, [], /permission denied/);
  }
  await refuses(`INSERT INTO worship_screens(business_id, name, token) VALUES ('${b2}', 'x', '${'E'.repeat(43)}')`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`worship_show: ${checks} checks passed`);

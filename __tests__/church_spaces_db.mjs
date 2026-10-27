// Rooms & spaces, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-spaces.sql. Two booked bookings of one
// space never overlap (the exclusion constraint, even for two inserts in one
// statement), while requests, declined and cancelled rows may; back-to-back
// bookings don't clash; a booking's space is its own church's; a space is a
// room, a vehicle or equipment; a church that leaves takes its spaces and
// bookings; a deleted bill or person leaves the booking; the browser's roles
// can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_spaces_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);
const { btree_gist } = await import(new URL('./contrib/btree_gist.js', base).href);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite({ extensions: { btree_gist } });
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const who = '00000000-0000-4000-8000-000000000002';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA extensions;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid);
  CREATE TABLE public.invoices(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-27-church-spaces.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-spaces.sql'));   // idempotent

// Spaces: a room by default, the three kinds only, a name.
const space = async (biz, name, kind = 'room') =>
  (await db.query('INSERT INTO church_spaces(business_id, name, kind) VALUES ($1, $2, $3) RETURNING *', [biz, name, kind])).rows[0];
const hall = await space(b1, 'Fellowship hall');
assert.equal(hall.kind, 'room'); assert.equal(hall.active, true); assert.equal(hall.notes, ''); checks++;
const van = await space(b1, 'The van', 'vehicle');
const other = await space(b2, 'Sanctuary');
await refuses('INSERT INTO church_spaces(business_id, name, kind) VALUES ($1, $2, $3)', [b1, 'Boat', 'boat'], /check constraint/);
await refuses('INSERT INTO church_spaces(business_id, name) VALUES ($1, $2)', [b1, ''], /check constraint/);

// Bookings: requested by default; booked ones of one space never overlap.
const add = `INSERT INTO church_space_bookings(business_id, space_id, title, start_at, end_at, status)
  VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`;
const sat = (h1, h2) => [`2026-10-31T${h1}:00:00Z`, `2026-10-31T${h2}:00:00Z`];
const meal = (await db.query(add, [b1, hall.id, 'Funeral meal', ...sat(17, 20), 'booked'])).rows[0];
assert.equal(meal.kind, 'use'); assert.equal(meal.fee_cents, 0); checks++;
const ask = `INSERT INTO church_space_bookings(business_id, space_id, title, start_at, end_at)
  VALUES ($1, $2, $3, $4, $5) RETURNING status`;
assert.equal((await db.query(ask, [b1, hall.id, 'Youth night', ...sat(18, 21)])).rows[0].status, 'requested', 'a request may overlap'); checks++;
await refuses(add, [b1, hall.id, 'Choir', ...sat(19, 22), 'booked'], /exclusion constraint|conflicting key/);
await db.query(add, [b1, hall.id, 'Clean up', ...sat(20, 21), 'booked']); checks++;   // starts as the meal ends
await db.query(add, [b1, van.id, 'Van to the cemetery', ...sat(17, 20), 'booked']); checks++;   // another space
for (const st of ['declined', 'cancelled']) {
  await db.query(add, [b1, hall.id, `Old ${st}`, ...sat(17, 20), st]); checks++;
}
// Two clashing rows in one statement (a weekly repeat over itself) fail together.
await refuses(`INSERT INTO church_space_bookings(business_id, space_id, title, start_at, end_at, status) VALUES
  ($1, $2, 'A', '2026-11-07T10:00:00Z', '2026-11-07T12:00:00Z', 'booked'),
  ($1, $2, 'B', '2026-11-07T11:00:00Z', '2026-11-07T13:00:00Z', 'booked')`, [b1, hall.id], /exclusion constraint|conflicting key/);
assert.equal((await db.query(`SELECT count(*)::int AS n FROM church_space_bookings WHERE title IN ('A', 'B')`)).rows[0].n, 0); checks++;
// Approving a request over a booked time is refused.
await refuses(`UPDATE church_space_bookings SET status = 'booked' WHERE title = 'Youth night'`, [], /exclusion constraint|conflicting key/);

// A booking's times, status and kind.
await refuses(add, [b1, hall.id, 'Backwards', ...sat(20, 17), 'booked'], /check constraint/);
await refuses(add, [b1, hall.id, 'Forever', '2026-11-01T00:00:00Z', '2026-12-01T00:00:00Z', 'requested'], /check constraint/);
await refuses(add, [b1, hall.id, 'Maybe', ...sat(8, 9), 'maybe'], /check constraint/);
await refuses(`UPDATE church_space_bookings SET kind = 'loan' WHERE id = $1`, [meal.id], /check constraint/);
await refuses(`UPDATE church_space_bookings SET fee_cents = -1 WHERE id = $1`, [meal.id], /check constraint/);

// A booking's space is its own church's.
await refuses(add, [b1, other.id, 'Borrowed', ...sat(8, 9), 'booked'], /foreign key/);

// A rental's bill and person: deleting either leaves the booking.
const inv = (await db.query('INSERT INTO invoices(business_id) VALUES ($1) RETURNING id', [b1])).rows[0].id;
const person = (await db.query('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1])).rows[0].id;
await db.query(`UPDATE church_space_bookings SET kind = 'rental', fee_cents = 25000, deposit_cents = 10000,
  invoice_id = $2, contact_id = $3 WHERE id = $1`, [meal.id, inv, person]);
await db.query('DELETE FROM invoices WHERE id = $1', [inv]);
await db.query('DELETE FROM contacts WHERE id = $1', [person]);
const kept = (await db.query('SELECT invoice_id, contact_id, fee_cents FROM church_space_bookings WHERE id = $1', [meal.id])).rows[0];
assert.equal(kept.invoice_id, null); assert.equal(kept.contact_id, null); assert.equal(kept.fee_cents, 25000); checks++;

// A church that leaves takes its spaces and bookings; the other keeps its own.
await db.query(add, [b2, other.id, 'Sunday', ...sat(9, 12), 'booked']);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
for (const table of ['church_spaces', 'church_space_bookings']) {
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM ${table} WHERE business_id = $1`, [b1])).rows[0].n, 0); checks++;
  assert.equal((await db.query(`SELECT count(*)::int AS n FROM ${table} WHERE business_id = $1`, [b2])).rows[0].n, 1); checks++;
}

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const table of ['church_spaces', 'church_space_bookings']) {
    await refuses(`SELECT * FROM ${table}`, [], /permission denied/);
  }
  await refuses(`INSERT INTO church_spaces(business_id, name) VALUES ('${b2}', 'Mine')`, [], /permission denied/);
  await refuses(`UPDATE church_space_bookings SET status = 'cancelled'`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church spaces and bookings: ${checks} checks passed`);

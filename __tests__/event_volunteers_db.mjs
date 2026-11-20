// An event's volunteers, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-21-event-volunteers.sql. Every row already there
// keeps needs null; only an event date carries numbers, and only in the
// server's shape (uuid keys, whole numbers 1-50, 1-60 places); a request
// names an event and an event date of the same church; one live request per
// event; a yes or a no says who and when; deleting the event keeps the
// request; running the file again changes nothing; the browser's roles read
// and run none of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/event_volunteers_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const FILE = 'APPLY-2026-11-21-event-volunteers.sql';
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const u1 = '33333333-3333-4333-8333-333333333333';
const p1 = '44444444-4444-4444-8444-444444444444';
const p2 = '55555555-5555-4555-8555-555555555555';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.groups(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE, kind text NOT NULL, name text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.module_entries(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE, data jsonb NOT NULL DEFAULT '{}');
  GRANT ALL ON public.businesses, public.module_entries TO service_role;`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.exec(await sql('APPLY-2026-10-19-worship-show.sql'));
await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));
await db.exec(await sql('APPLY-2026-11-17-event-volunteer-dates.sql'));

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

// Before the file: a Sunday plan and an event date made on Nov 17's terms.
const sunday = await one(`INSERT INTO worship_services(business_id, title, starts_at, items)
  VALUES ($1, 'Sunday service', '2026-12-13T16:30:00Z', '[{"id":"a1","kind":"text"}]') RETURNING id`, [b1]);
const entry = await one(`INSERT INTO module_entries(business_id, data) VALUES ($1, '{"title":"Youth Lock-in"}') RETURNING id`, [b1]);
const older = await one(`INSERT INTO worship_services(business_id, title, starts_at, items, kind, place)
  VALUES ($1, 'Outreach night', '2026-12-03T00:00:00Z', '[]', 'event', 'Gym') RETURNING id`, [b1]);

await db.exec(await sql(FILE));
for (const id of [sunday.id, older.id]) {
  assert.equal((await one('SELECT needs FROM worship_services WHERE id = $1', [id])).needs, null); checks++;
}
// Running it again changes nothing.
await db.exec(await sql(FILE));
assert.equal((await one('SELECT count(*)::int AS n FROM worship_services WHERE needs IS NOT NULL')).n, 0); checks++;

// ─── needs on worship_services ──────────────────────────────────────
const ev = await one(`INSERT INTO worship_services(business_id, title, starts_at, items, kind, place, event_entry_id, needs)
  VALUES ($1, 'Youth Lock-in', '2026-12-12T00:00:00Z', '[]', 'event', 'Fellowship hall', $2, $3) RETURNING id, needs`,
  [b1, entry.id, JSON.stringify({ [p1]: 2, [p2]: 4 })]);
assert.deepEqual(ev.needs, { [p1]: 2, [p2]: 4 }); checks++;
// A Sunday never carries numbers.
await refuses('UPDATE worship_services SET needs = $2 WHERE id = $1', [sunday.id, JSON.stringify({ [p1]: 2 })], /worship_services_needs_event/);
// An event date may go back to its Sunday numbers.
await db.query('UPDATE worship_services SET needs = NULL WHERE id = $1', [older.id]); checks++;
const bad = [
  ['{}', 'empty'],
  ['[]', 'an array'],
  ['"3"', 'a string'],
  [JSON.stringify({ greeters: 2 }), 'a key that is not an id'],
  [JSON.stringify({ 'ABCDEF12-3456-4789-8abc-def012345678': 2 }), 'an id in capitals'],
  [JSON.stringify({ [p1]: 0 }), 'zero'],
  [JSON.stringify({ [p1]: 51 }), 'over 50'],
  [JSON.stringify({ [p1]: 2.5 }), 'a fraction'],
  [JSON.stringify({ [p1]: '2' }), 'a number as text'],
  [JSON.stringify({ [p1]: null }), 'null'],
  [JSON.stringify({ [p1]: -1 }), 'below zero'],
];
for (const [v] of bad) await refuses('UPDATE worship_services SET needs = $2::jsonb WHERE id = $1', [ev.id, v], /worship_services_needs_event/);
const many = n => JSON.stringify(Object.fromEntries(Array.from({ length: n }, (_, i) =>
  [`${String(i).padStart(8, '0')}-0000-4000-8000-000000000000`, 1])));
await db.query('UPDATE worship_services SET needs = $2::jsonb WHERE id = $1', [ev.id, many(60)]); checks++;
await refuses('UPDATE worship_services SET needs = $2::jsonb WHERE id = $1', [ev.id, many(61)], /worship_services_needs_event/);
// 1 and 50 are both fine.
await db.query('UPDATE worship_services SET needs = $2::jsonb WHERE id = $1', [ev.id, JSON.stringify({ [p1]: 1, [p2]: 50 })]); checks++;
// A Sunday plan still saves its order, and a template still saves.
await db.query(`UPDATE worship_services SET items = '[{"id":"a1","kind":"text"},{"id":"a2","kind":"song"}]' WHERE id = $1`, [sunday.id]); checks++;
await db.query(`INSERT INTO worship_services(business_id, title, is_template) VALUES ($1, 'Usual Sunday', true)`, [b1]); checks++;

// ─── event_volunteer_requests ───────────────────────────────────────
const NEEDS = JSON.stringify({ [p1]: 2 });
const ask = (biz, entryId, status = 'waiting', extra = {}) => db.query(
  `INSERT INTO event_volunteer_requests(business_id, entry_id, title, starts_at, place, needs, asked_by, asked_by_name,
     status, service_id, decided_by, decided_at)
   VALUES ($1, $2, $3, '2026-12-12T00:00:00Z', 'Fellowship hall', $4::jsonb, $5, 'Tiara', $6, $7, $8, $9) RETURNING *`,
  [biz, entryId, extra.title ?? 'Youth Lock-in', extra.needs ?? NEEDS, u1, status, extra.service ?? null,
   extra.decidedBy ?? null, extra.decidedAt ?? null]);

const r1 = (await ask(b1, entry.id)).rows[0];
assert.equal(r1.status, 'waiting'); assert.equal(r1.note, ''); assert.equal(r1.told_at, null); checks++;
// One live request per event.
await refuses(`INSERT INTO event_volunteer_requests(business_id, entry_id, title, starts_at, needs, asked_by)
  VALUES ($1, $2, 'Again', now(), $3::jsonb, $4)`, [b1, entry.id, NEEDS, u1], /event_volunteer_requests_one_live/);
// A yes says who and when.
await refuses('UPDATE event_volunteer_requests SET status = $2 WHERE id = $1', [r1.id, 'on'], /event_volunteer_requests_decided/);
await refuses('UPDATE event_volunteer_requests SET status = $2 WHERE id = $1', [r1.id, 'declined'], /event_volunteer_requests_decided/);
const before = r1.updated_at;
await new Promise(r => setTimeout(r, 15));
const yes = await one(`UPDATE event_volunteer_requests SET status = 'on', service_id = $2, decided_by = $3, decided_by_name = 'Laquesha',
  decided_at = now() WHERE id = $1 RETURNING status, service_id, updated_at`, [r1.id, ev.id, u1]);
assert.equal(yes.status, 'on'); assert.equal(yes.service_id, ev.id); checks++;
assert.ok(new Date(yes.updated_at) > new Date(before)); checks++;
// Still one live: an `on` request blocks a second ask too.
await refuses(`INSERT INTO event_volunteer_requests(business_id, entry_id, title, starts_at, needs, asked_by)
  VALUES ($1, $2, 'Again', now(), $3::jsonb, $4)`, [b1, entry.id, NEEDS, u1], /event_volunteer_requests_one_live/);
// Once it's no longer live, the event can ask again.
await db.query(`UPDATE event_volunteer_requests SET status = 'cancelled' WHERE id = $1`, [r1.id]); checks++;
const r2 = (await ask(b1, entry.id)).rows[0];
await db.query(`UPDATE event_volunteer_requests SET status = 'withdrawn' WHERE id = $1`, [r2.id]); checks++;
const r3 = (await ask(b1, entry.id)).rows[0];
await db.query(`UPDATE event_volunteer_requests SET status = 'declined', decided_by = $2, decided_at = now(),
  decided_note = 'Short that weekend' WHERE id = $1`, [r3.id, u1]); checks++;

// The shape of every field.
await refuses('UPDATE event_volunteer_requests SET status = $2 WHERE id = $1', [r3.id, 'maybe'], /event_volunteer_requests_status_known/);
await refuses('UPDATE event_volunteer_requests SET title = $2 WHERE id = $1', [r3.id, ''], /event_volunteer_requests_title_short/);
await refuses('UPDATE event_volunteer_requests SET title = $2 WHERE id = $1', [r3.id, 'x'.repeat(121)], /event_volunteer_requests_title_short/);
await refuses('UPDATE event_volunteer_requests SET place = $2 WHERE id = $1', [r3.id, 'x'.repeat(121)], /event_volunteer_requests_place_short/);
await refuses('UPDATE event_volunteer_requests SET note = $2 WHERE id = $1', [r3.id, 'x'.repeat(301)], /event_volunteer_requests_note_short/);
await refuses('UPDATE event_volunteer_requests SET decided_note = $2 WHERE id = $1', [r3.id, 'x'.repeat(301)], /event_volunteer_requests_decided_note_short/);
await refuses('UPDATE event_volunteer_requests SET asked_by_name = $2 WHERE id = $1', [r3.id, 'x'.repeat(81)], /event_volunteer_requests_names_short/);
for (const [v] of bad) await refuses('UPDATE event_volunteer_requests SET needs = $2::jsonb WHERE id = $1', [r3.id, v], /event_volunteer_requests_needs_ok/);
await refuses('UPDATE event_volunteer_requests SET needs = NULL WHERE id = $1', [r3.id], /null value|not-null/);

// Same church: the event, and the date (an event date, never a Sunday).
const other = await one(`INSERT INTO module_entries(business_id, data) VALUES ($1, '{}') RETURNING id`, [b2]);
await refuses(`INSERT INTO event_volunteer_requests(business_id, entry_id, title, starts_at, needs, asked_by)
  VALUES ($1, $2, 'Theirs', now(), $3::jsonb, $4)`, [b1, other.id, NEEDS, u1], /not in this church/);
const theirsDate = await one(`INSERT INTO worship_services(business_id, title, starts_at, items, kind)
  VALUES ($1, 'Their night', '2026-12-04T00:00:00Z', '[]', 'event') RETURNING id`, [b2]);
await refuses('UPDATE event_volunteer_requests SET service_id = $2 WHERE id = $1', [r3.id, theirsDate.id], /not one of this church's event dates/);
await refuses('UPDATE event_volunteer_requests SET service_id = $2 WHERE id = $1', [r3.id, sunday.id], /not one of this church's event dates/);

// Deleting the event keeps the requests, with their copies of the title and day.
const gone = await one(`INSERT INTO module_entries(business_id, data) VALUES ($1, '{}') RETURNING id`, [b1]);
const r4 = (await ask(b1, gone.id, 'waiting', { title: 'Fall festival' })).rows[0];
await db.query('DELETE FROM module_entries WHERE id = $1', [gone.id]);
const kept = await one('SELECT entry_id, title, status FROM event_volunteer_requests WHERE id = $1', [r4.id]);
assert.equal(kept.entry_id, null); assert.equal(kept.title, 'Fall festival'); assert.equal(kept.status, 'waiting'); checks++;
// Two requests that lost their event don't collide on the one-live rule.
const gone2 = await one(`INSERT INTO module_entries(business_id, data) VALUES ($1, '{}') RETURNING id`, [b1]);
await ask(b1, gone2.id, 'waiting', { title: 'Fall festival' });
await db.query('DELETE FROM module_entries WHERE id = $1', [gone2.id]); checks++;
// A church that goes takes its requests with it.
await ask(b2, null, 'waiting', { title: 'Their night' });
await db.query('DELETE FROM event_volunteer_requests WHERE business_id = $1', [b2]);
await db.query('DELETE FROM worship_services WHERE business_id = $1', [b2]);
await db.query('DELETE FROM module_entries WHERE business_id = $1', [b2]);
await ask(b2, null, 'waiting', { title: 'Their night' });
await db.query('DELETE FROM businesses WHERE id = $1', [b2]);
assert.equal((await one('SELECT count(*)::int AS n FROM event_volunteer_requests WHERE business_id = $1', [b2])).n, 0); checks++;

// ─── Server-only ────────────────────────────────────────────────────
const rls = await one(`SELECT relrowsecurity AS on FROM pg_class WHERE oid = 'public.event_volunteer_requests'::regclass`);
assert.equal(rls.on, true); checks++;
assert.equal((await one(`SELECT count(*)::int AS n FROM pg_policies WHERE tablename = 'event_volunteer_requests'`)).n, 0); checks++;
for (const role of ['anon', 'authenticated']) {
  for (const priv of ['select', 'insert', 'update', 'delete']) {
    assert.equal((await one(`SELECT has_table_privilege($1, 'public.event_volunteer_requests', $2) AS ok`, [role, priv])).ok, false); checks++;
  }
  assert.equal((await one(`SELECT has_function_privilege($1, 'public.event_needs_ok(jsonb)', 'execute') AS ok`, [role])).ok, false); checks++;
  assert.equal((await one(`SELECT has_function_privilege($1, 'public.event_volunteer_requests_same_business()', 'execute') AS ok`, [role])).ok, false); checks++;
}
for (const priv of ['select', 'insert', 'update', 'delete']) {
  assert.equal((await one(`SELECT has_table_privilege('service_role', 'public.event_volunteer_requests', $1) AS ok`, [priv])).ok, true); checks++;
}
assert.equal((await one(`SELECT has_function_privilege('service_role', 'public.event_needs_ok(jsonb)', 'execute') AS ok`)).ok, true); checks++;

// The service role writes through RLS and the checks.
const e5 = await one(`INSERT INTO module_entries(business_id, data) VALUES ($1, '{}') RETURNING id`, [b1]);
await db.exec('SET ROLE service_role');
const sr = await one(`UPDATE worship_services SET needs = $2::jsonb WHERE id = $1 RETURNING needs`, [ev.id, NEEDS]);
assert.deepEqual(sr.needs, { [p1]: 2 }); checks++;
const r5 = await one(`INSERT INTO event_volunteer_requests(business_id, entry_id, title, starts_at, needs, asked_by)
  VALUES ($1, $2, 'Choir night', now(), $3::jsonb, $4) RETURNING status`, [b1, e5.id, NEEDS, u1]);
assert.equal(r5.status, 'waiting'); checks++;
await db.exec('RESET ROLE');

// A third run on a database with requests in it changes nothing.
const count = (await one('SELECT count(*)::int AS n FROM event_volunteer_requests')).n;
await db.exec(await sql(FILE));
assert.equal((await one('SELECT count(*)::int AS n FROM event_volunteer_requests')).n, count); checks++;
assert.deepEqual((await one('SELECT needs FROM worship_services WHERE id = $1', [ev.id])).needs, { [p1]: 2 }); checks++;

console.log(`event volunteers db check: ${checks} checks passed`);

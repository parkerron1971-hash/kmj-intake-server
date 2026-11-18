// Event dates on Who serves when, on a real Postgres (PGlite):
// supabase/APPLY-2026-11-17-event-volunteer-dates.sql. Every row already
// there becomes a Sunday plan (kind 'service') and keeps its order; an event
// date is kind 'event', never a template and never carries an order; only an
// event date names a Services & Events entry, and only one of the church's
// own, once while it's on the schedule; deleting the entry keeps the date
// and its asks; a Sunday's asks and an event date's asks both still point at
// a service of the same church; running the file again changes nothing; the
// browser's roles still read none of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/event_volunteer_dates_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.groups(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE, kind text NOT NULL, name text NOT NULL);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE);
  CREATE TABLE public.module_entries(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id uuid NOT NULL REFERENCES businesses ON DELETE CASCADE, data jsonb NOT NULL DEFAULT '{}');`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.exec(await sql('APPLY-2026-10-19-worship-show.sql'));
await db.exec(await sql('APPLY-2026-10-23-sunday-planning.sql'));

let checks = 0;
const one = async (text, args) => (await db.query(text, args)).rows[0];
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

// A church's Sunday plan before the file, with its order of service.
const sunday = await one(`INSERT INTO worship_services(business_id, title, starts_at, items)
  VALUES ($1, 'Sunday service', '2026-11-22T16:30:00Z', '[{"id":"a1","kind":"text"}]') RETURNING id`, [b1]);
const tmpl = await one(`INSERT INTO worship_services(business_id, title, is_template) VALUES ($1, 'Usual Sunday', true) RETURNING id`, [b1]);

await db.exec(await sql('APPLY-2026-11-17-event-volunteer-dates.sql'));
for (const id of [sunday.id, tmpl.id]) {
  const r = await one('SELECT kind, place, event_entry_id, jsonb_array_length(items) AS n FROM worship_services WHERE id = $1', [id]);
  assert.equal(r.kind, 'service'); assert.equal(r.place, ''); assert.equal(r.event_entry_id, null); checks++;
}
assert.equal((await one('SELECT jsonb_array_length(items) AS n FROM worship_services WHERE id = $1', [sunday.id])).n, 1); checks++;

// Running it again changes nothing, and the Sunday still saves its order.
await db.exec(await sql('APPLY-2026-11-17-event-volunteer-dates.sql'));
await db.query(`UPDATE worship_services SET items = '[{"id":"a1","kind":"text"},{"id":"a2","kind":"song"}]' WHERE id = $1`, [sunday.id]);
assert.equal((await one('SELECT kind FROM worship_services WHERE id = $1', [sunday.id])).kind, 'service'); checks++;

// An event date: typed, and one made from a Services & Events entry.
const entry = await one(`INSERT INTO module_entries(business_id, data) VALUES ($1, '{"title":"Outreach night"}') RETURNING id`, [b1]);
const typed = await one(`INSERT INTO worship_services(business_id, title, starts_at, kind, place)
  VALUES ($1, 'Saturday clean-up', '2026-11-21T15:00:00Z', 'event', 'The lot') RETURNING id, kind, place, items`, [b1]);
assert.equal(typed.kind, 'event'); assert.equal(typed.place, 'The lot'); assert.deepEqual(typed.items, []); checks++;
const linked = await one(`INSERT INTO worship_services(business_id, title, starts_at, kind, event_entry_id)
  VALUES ($1, 'Outreach night', '2026-11-20T00:00:00Z', 'event', $2) RETURNING id`, [b1, entry.id]);

// Never another kind, never a long place, never an order of service or a template.
await refuses(`INSERT INTO worship_services(business_id, kind) VALUES ($1, 'concert')`, [b1], /check constraint/);
await refuses(`UPDATE worship_services SET place = repeat('x', 121) WHERE id = $1`, [typed.id], /check constraint/);
await refuses(`UPDATE worship_services SET items = '[{"id":"a1","kind":"song"}]' WHERE id = $1`, [typed.id], /check constraint/);
await refuses(`UPDATE worship_services SET is_template = true WHERE id = $1`, [typed.id], /check constraint/);
await refuses(`UPDATE worship_services SET kind = 'event' WHERE id = $1`, [sunday.id], /check constraint/);
await refuses(`UPDATE worship_services SET kind = NULL WHERE id = $1`, [typed.id], /null value|not-null/);

// Only an event date names an entry; only the church's own; once while it's on.
await refuses(`UPDATE worship_services SET event_entry_id = $2 WHERE id = $1`, [tmpl.id, entry.id], /check constraint/);
const theirs = await one(`INSERT INTO module_entries(business_id) VALUES ($1) RETURNING id`, [b2]);
await refuses(`INSERT INTO worship_services(business_id, title, kind, event_entry_id) VALUES ($1, 'X', 'event', $2)`,
  [b1, theirs.id], /not in this church/);
await refuses(`UPDATE worship_services SET event_entry_id = $2 WHERE id = $1`, [typed.id, theirs.id], /not in this church/);
await refuses(`INSERT INTO worship_services(business_id, title, kind, event_entry_id) VALUES ($1, 'Again', 'event', $2)`,
  [b1, entry.id], /duplicate key|unique/);
// Taken off the schedule (archived), the entry can be scheduled again.
await db.query('UPDATE worship_services SET archived_at = now() WHERE id = $1', [linked.id]);
const again = await one(`INSERT INTO worship_services(business_id, title, kind, event_entry_id) VALUES ($1, 'Again', 'event', $2) RETURNING id`,
  [b1, entry.id]);
assert.ok(again.id); checks++;

// An ask on an event date, as on a Sunday: the serving tables' own guard still holds.
const g = await one(`INSERT INTO groups(business_id, kind, name) VALUES ($1, 'team', 'Greeters') RETURNING id`, [b1]);
await db.query('INSERT INTO serve_teams(group_id, business_id) VALUES ($1, $2)', [g.id, b1]);
const pos = await one(`INSERT INTO serve_positions(business_id, group_id, name) VALUES ($1, $2, 'Door') RETURNING id`, [b1, g.id]);
const c = await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1]);
const ask = await one(`INSERT INTO serve_assignments(business_id, service_id, position_id, contact_id)
  VALUES ($1, $2, $3, $4) RETURNING id`, [b1, again.id, pos.id, c.id]);
assert.ok(ask.id); checks++;
await refuses(`INSERT INTO serve_assignments(business_id, service_id, position_id, contact_id) VALUES ($1, $2, $3, $4)`,
  [b2, again.id, pos.id, c.id], /not in this business/);

// The entry deleted: the date stays, unlinked, with its ask.
await db.query('DELETE FROM module_entries WHERE id = $1', [entry.id]);
const kept = await one('SELECT kind, event_entry_id FROM worship_services WHERE id = $1', [again.id]);
assert.equal(kept.kind, 'event'); assert.equal(kept.event_entry_id, null); checks++;
assert.equal((await one('SELECT count(*)::int AS n FROM serve_assignments WHERE service_id = $1', [again.id])).n, 1); checks++;

// The browser's roles still read and write none of it.
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT kind, place, event_entry_id FROM worship_services', [], /permission denied/);
  await refuses(`UPDATE worship_services SET kind = 'event'`, [], /permission denied/);
  await db.exec('RESET ROLE');
}
for (const role of ['anon', 'authenticated']) {
  const r = await one(`SELECT has_function_privilege('${role}', 'public.worship_services_entry_same_business()', 'execute') AS ok`);
  assert.equal(r.ok, false, role); checks++;
}

console.log(`event volunteer dates db: ${checks} checks passed`);

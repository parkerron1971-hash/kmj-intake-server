// Paid event sign-ups, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-event-signups.sql. Places are taken by
// paid and free sign-ups and by live holds; a hold that runs out gives its
// place back; the last place goes to one person even when two ask; a full
// event fills its waitlist in order and moves it first come, first served
// (an offer carries a link whose hash alone is kept); a free place from the
// waitlist is confirmed at once; a closed or past-deadline event takes no
// one; the same press twice is one sign-up; a church that leaves takes its
// sign-ups; the browser's roles can't touch any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_event_signups_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
const base = process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : new URL('../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url).href;
const { PGlite } = await import(base);

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const b2 = '22222222-2222-4222-8222-222222222222';
const e1 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const e2 = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid);
  CREATE TABLE public.module_entries(id uuid PRIMARY KEY, business_id uuid);
  GRANT USAGE ON SCHEMA public TO service_role, anon, authenticated;`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
await db.query('INSERT INTO module_entries(id, business_id) VALUES ($1, $2), ($3, $4)', [e1, b1, e2, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-27-church-event-signups.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-event-signups.sql'));   // idempotent

const setup = (await db.query(
  `INSERT INTO church_event_signup_setups(business_id, entry_id, capacity) VALUES ($1, $2, 3) RETURNING *`,
  [b1, e1])).rows[0];
assert.equal(setup.open, true); assert.equal(setup.waitlist, true); assert.equal(setup.offer_hours, 24); checks++;
await refuses(`INSERT INTO church_event_signup_setups(business_id, entry_id) VALUES ($1, $2)`, [b1, e1], /unique|duplicate/);
await refuses(`UPDATE church_event_signup_setups SET offer_hours = 100 WHERE id = $1`, [setup.id], /check constraint/);
await refuses(`UPDATE church_event_signup_setups SET capacity = 0 WHERE id = $1`, [setup.id], /check constraint/);

// Ticket types: a price may be $0, never negative; a type is its own church's setup's.
await db.query(`INSERT INTO church_event_ticket_types(business_id, setup_id, label, price_cents) VALUES ($1, $2, 'Adult', 2500), ($1, $2, 'Under 3', 0)`, [b1, setup.id]);
checks++;
await refuses(`INSERT INTO church_event_ticket_types(business_id, setup_id, label, price_cents) VALUES ($1, $2, 'Bad', -1)`, [b1, setup.id], /check constraint/);
await refuses(`INSERT INTO church_event_ticket_types(business_id, setup_id, label, price_cents) VALUES ($1, $2, 'Theirs', 100)`, [b2, setup.id], /foreign key/);

// Everything below runs as the server does.
await db.exec('SET ROLE service_role');
const take = async (name, seats, amount, { waitlist = false, key = null, hold = 40 } = {}) => (await db.query(
  'SELECT church_event_take($1, $2, $3::jsonb, $4, $5) AS r',
  [b1, e1, JSON.stringify({ name, email: `${name.toLowerCase()}@example.org`, seats, amount_cents: amount,
                            tickets: [{ label: 'Adult', qty: seats }], answers: {}, request_key: key,
                            event_title: 'Vacation Bible School' }), waitlist, hold])).rows[0].r;
const taken = async () => (await db.query('SELECT church_event_taken($1, $2) AS n', [b1, e1])).rows[0].n;

const ann = await take('Ann', 2, 5000, { key: 'k-ann' });
assert.equal(ann.state, 'held'); assert.ok(ann.hold_expires_at); assert.equal(await taken(), 2); checks++;
const again = await take('Ann', 2, 5000, { key: 'k-ann' });
assert.equal(again.state, 'already'); assert.equal(again.id, ann.id); assert.equal(await taken(), 2, 'the same press twice is one sign-up'); checks++;
const free = await take('Bea', 1, 0);
assert.equal(free.state, 'confirmed'); assert.equal(await taken(), 3); checks++;
// Full: the next one is told so, or joins the waitlist in order.
assert.deepEqual((await take('Cal', 1, 2500)).state, 'full'); checks++;
const cal = await take('Cal', 1, 2500, { waitlist: true });
const dee = await take('Dee', 2, 5000, { waitlist: true });
const eve = await take('Eve', 1, 0, { waitlist: true });
assert.equal(cal.state, 'waiting'); assert.equal(cal.position, 1); assert.equal(dee.position, 2); assert.equal(eve.position, 3); checks++;

// Ann's hold runs out: her two places go back, and the waitlist moves in
// order: Cal (1 place, offered with a link), then Dee needs 2 with 1 left,
// so she waits, and Eve behind her waits too (first come, first served).
await db.exec('RESET ROLE');
await db.query(`UPDATE church_event_registrations SET hold_expires_at = now() - interval '1 minute' WHERE id = $1`, [ann.id]);
await db.exec('SET ROLE service_role');
assert.equal(await taken(), 1, 'a hold that ran out takes no place'); checks++;
const moved = (await db.query('SELECT church_event_settle($1, $2) AS r', [b1, e1])).rows[0].r;
assert.equal(moved.offers.length, 1); assert.equal(moved.offers[0].id, cal.id); assert.equal(moved.offers[0].status, 'offered'); checks++;
const token = moved.offers[0].token;
assert.match(token, /^[0-9a-f]{64}$/); checks++;
const row = id => db.query('SELECT * FROM church_event_registrations WHERE id = $1', [id]).then(r => r.rows[0]);
const calRow = await row(cal.id);
assert.equal(calRow.claim_hash, createHash('sha256').update(token).digest('hex'), 'only the hash of the link is kept'); checks++;
assert.ok(new Date(calRow.hold_expires_at) - Date.now() > 23 * 3600 * 1000, 'an offer lasts offer_hours'); checks++;
assert.equal((await row(ann.id)).status, 'expired'); assert.equal((await row(dee.id)).status, 'waiting'); assert.equal((await row(eve.id)).status, 'waiting'); checks++;
assert.equal(await taken(), 2); checks++;
// Someone new can't jump the line while people wait.
assert.equal((await take('Fay', 1, 2500)).state, 'full', 'a newcomer never jumps the waitlist'); checks++;

// Paid and refunded: Bea's free place is cancelled by the office; Dee fits
// now (Cal's offer + 2 = 3) and is offered; Eve's free place still waits.
await db.query(`UPDATE church_event_registrations SET status = 'cancelled' WHERE id = $1`, [free.id]);
const moved2 = (await db.query('SELECT church_event_settle($1, $2) AS r', [b1, e1])).rows[0].r;
assert.deepEqual(moved2.offers.map(o => o.id), [dee.id]); checks++;
// More places: Eve's free place is confirmed at once, no link.
await db.exec('RESET ROLE');
await db.query('UPDATE church_event_signup_setups SET capacity = 4 WHERE id = $1', [setup.id]);
await db.exec('SET ROLE service_role');
const moved3 = (await db.query('SELECT church_event_settle($1, $2) AS r', [b1, e1])).rows[0].r;
assert.equal(moved3.offers.length, 1); assert.equal(moved3.offers[0].status, 'confirmed'); assert.equal(moved3.offers[0].token, null); checks++;
assert.equal((await row(eve.id)).status, 'confirmed'); assert.equal((await row(eve.id)).claim_hash, null); checks++;

// The last place, asked for twice in one breath: one gets it.
await db.exec('RESET ROLE');
await db.query('UPDATE church_event_signup_setups SET capacity = 5, waitlist = false WHERE id = $1', [setup.id]);
await db.exec('SET ROLE service_role');
const both = await Promise.all([take('Gus', 1, 2500), take('Hal', 1, 2500)]);
assert.deepEqual(both.map(b => b.state).sort(), ['full', 'held']); assert.equal(await taken(), 5); checks++;
// A closed event and a passed deadline take nobody.
await db.exec('RESET ROLE');
await db.query('UPDATE church_event_signup_setups SET capacity = null, open = false WHERE id = $1', [setup.id]);
await db.exec('SET ROLE service_role');
assert.equal((await take('Ivy', 1, 2500)).state, 'closed'); checks++;
await db.exec('RESET ROLE');
await db.query(`UPDATE church_event_signup_setups SET open = true, deadline = now() - interval '1 hour' WHERE id = $1`, [setup.id]);
await db.exec('SET ROLE service_role');
const late = await take('Ivy', 1, 2500);
assert.equal(late.state, 'closed'); assert.equal(late.why, 'deadline'); checks++;
// An event with no setup takes nobody.
assert.equal((await db.query('SELECT church_event_take($1, $2, $3::jsonb, false, 40) AS r',
  [b2, e2, JSON.stringify({ name: 'Jo', email: 'jo@example.org', seats: 1, amount_cents: 0 })])).rows[0].r.state, 'closed'); checks++;
await db.exec('RESET ROLE');

// A hold or an offer always has an end; statuses are the eight.
await refuses(`UPDATE church_event_registrations SET hold_expires_at = null WHERE id = $1`, [cal.id], /check constraint/);
await refuses(`UPDATE church_event_registrations SET status = 'maybe' WHERE id = $1`, [cal.id], /check constraint/);
await refuses(`UPDATE church_event_registrations SET amount_cents = -1 WHERE id = $1`, [cal.id], /check constraint/);

// The event's entry going keeps its paid sign-ups (a payment record); its
// setup and ticket types go with it.
await db.query(`UPDATE church_event_registrations SET status = 'paid', paid_at = now() WHERE id = $1`, [cal.id]);
await db.query('DELETE FROM module_entries WHERE id = $1', [e1]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_event_signup_setups WHERE entry_id = $1', [e1])).rows[0].n, 0); checks++;
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_event_ticket_types WHERE setup_id = $1', [setup.id])).rows[0].n, 0); checks++;
assert.equal((await row(cal.id)).status, 'paid'); checks++;

// A church that leaves takes its sign-ups; the other keeps its own.
await db.query(`INSERT INTO church_event_registrations(business_id, entry_id, name, email, seats, amount_cents, status)
  VALUES ($1, $2, 'Kay', 'kay@example.org', 1, 0, 'confirmed')`, [b2, e2]);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_event_registrations WHERE business_id = $1', [b1])).rows[0].n, 0); checks++;
assert.equal((await db.query('SELECT count(*)::int AS n FROM church_event_registrations WHERE business_id = $1', [b2])).rows[0].n, 1); checks++;

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const table of ['church_event_signup_setups', 'church_event_ticket_types', 'church_event_registrations']) {
    await refuses(`SELECT * FROM ${table}`, [], /permission denied/);
  }
  await refuses(`UPDATE church_event_registrations SET status = 'paid'`, [], /permission denied/);
  await refuses(`SELECT church_event_take('${b2}', '${e2}', '{}'::jsonb, false, 40)`, [], /permission denied/);
  await refuses(`SELECT church_event_settle('${b2}', '${e2}')`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church event sign-ups: ${checks} checks passed`);

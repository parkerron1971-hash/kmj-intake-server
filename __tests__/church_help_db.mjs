// Help requests (benevolence), on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-help.sql. A church has one fund row
// ($150 limit unless set); a request's need, status and source are the
// known words; an app ask becomes one request at most; a request's person
// and Prayer & care row are its own church's; a record of help is its
// request's church's and goes with it; a deleted expense, person or ask
// leaves the record; a church that leaves takes it all; the browser's roles
// can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_help_db.mjs
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
  CREATE TABLE public.contacts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid);
  CREATE TABLE public.ministry_care_requests(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid);
  CREATE TABLE public.business_expenses(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, amount numeric);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const one = async (text, args) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-27-church-help.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-help.sql'));   // idempotent

// The fund: Benevolence, no budget, $150 a gift unless the church says.
const fund = await one('INSERT INTO church_help_settings(business_id) VALUES ($1) RETURNING *', [b1]);
assert.equal(fund.fund, 'Benevolence'); assert.equal(fund.monthly_budget_cents, 0); assert.equal(fund.gift_limit_cents, 15000); checks++;
await refuses('INSERT INTO church_help_settings(business_id) VALUES ($1)', [b1], /duplicate key|unique/);
await refuses('UPDATE church_help_settings SET gift_limit_cents = -1 WHERE business_id = $1', [b1], /check constraint/);
await refuses(`UPDATE church_help_settings SET fund = '' WHERE business_id = $1`, [b1], /check constraint/);

// A request: new, by phone, unless it says otherwise; only the known words.
const dana = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1])).id;
const theirs = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b2])).id;
const add = `INSERT INTO church_help_requests(business_id, need, amount_cents, contact_id) VALUES ($1, $2, $3, $4) RETURNING *`;
const bill = await one(add, [b1, 'bill', 18000, dana]);
assert.equal(bill.status, 'new'); assert.equal(bill.source, 'phone'); assert.equal(bill.anonymous, false);
assert.equal(bill.notes, ''); checks++;
await refuses(add, [b1, 'rent', 100, null], /check constraint/);
await refuses(add, [b1, 'food', -1, null], /check constraint/);
await refuses(`UPDATE church_help_requests SET status = 'maybe' WHERE id = $1`, [bill.id], /check constraint/);
await refuses(`UPDATE church_help_requests SET source = 'fax' WHERE id = $1`, [bill.id], /check constraint/);

// Its person is its own church's.
await refuses(add, [b1, 'food', null, theirs], /not in this church/);
await refuses('UPDATE church_help_requests SET contact_id = $2 WHERE id = $1', [bill.id, theirs], /not in this church/);

// An ask from the member app becomes one request at most, in its own church.
const ask = (await one('INSERT INTO ministry_care_requests(business_id) VALUES ($1) RETURNING id', [b1])).id;
const theirAsk = (await one('INSERT INTO ministry_care_requests(business_id) VALUES ($1) RETURNING id', [b2])).id;
const adopt = `INSERT INTO church_help_requests(business_id, need, source, care_request_id) VALUES ($1, 'food', 'app', $2)`;
await db.query(adopt, [b1, ask]); checks++;
await refuses(adopt, [b1, ask], /duplicate key|unique/);
const again = await db.query(`${adopt} ON CONFLICT (care_request_id) DO NOTHING RETURNING id`, [b1, ask]);
assert.equal(again.rows.length, 0, 'two presses at once make one row'); checks++;
await refuses(adopt, [b1, theirAsk], /not in this church/);

// How we helped: the known ways, a day, an amount not below zero; its
// request's church's.
const give = `INSERT INTO church_help_given(business_id, request_id, how, amount_cents, given_on, expense_id)
  VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`;
const exp = (await one('INSERT INTO business_expenses(business_id, amount) VALUES ($1, 150) RETURNING id', [b1])).id;
const check = await one(give, [b1, bill.id, 'check', 15000, '2026-10-26', exp]);
assert.equal(check.note, ''); checks++;
await refuses(give, [b1, bill.id, 'venmo', 100, '2026-10-26', null], /check constraint/);
await refuses(give, [b1, bill.id, 'cash', -5, '2026-10-26', null], /check constraint/);
await refuses(give, [b2, bill.id, 'cash', 500, '2026-10-26', null], /foreign key/);
await refuses(`INSERT INTO church_help_given(business_id, request_id, how) VALUES ($1, $2, 'ride')`, [b1, bill.id], /not-null|null value/);

// A deleted expense, person or ask leaves the record and the request.
await db.query('DELETE FROM business_expenses WHERE id = $1', [exp]);
assert.equal((await one('SELECT expense_id, amount_cents FROM church_help_given WHERE id = $1', [check.id])).expense_id, null); checks++;
await db.query('DELETE FROM contacts WHERE id = $1', [dana]);
assert.equal((await one('SELECT contact_id FROM church_help_requests WHERE id = $1', [bill.id])).contact_id, null); checks++;
await db.query('DELETE FROM ministry_care_requests WHERE id = $1', [ask]);
assert.equal((await one(`SELECT count(*)::int AS n FROM church_help_requests WHERE source = 'app' AND care_request_id IS NULL`)).n, 1); checks++;

// A request takes its records with it.
await db.query('DELETE FROM church_help_requests WHERE id = $1', [bill.id]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_help_given WHERE id = $1', [check.id])).n, 0); checks++;

// A church that leaves takes its fund, requests and records; the other keeps its own.
const kept = await one(`INSERT INTO church_help_requests(business_id, need) VALUES ($1, 'ride') RETURNING id`, [b2]);
await db.query(give, [b2, kept.id, 'ride', 0, '2026-10-26', null]);
await db.query('INSERT INTO church_help_settings(business_id) VALUES ($1)', [b2]);
const r1 = await one(`INSERT INTO church_help_requests(business_id, need) VALUES ($1, 'food') RETURNING id`, [b1]);
await db.query(give, [b1, r1.id, 'groceries', 6000, '2026-10-26', null]);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
for (const table of ['church_help_settings', 'church_help_requests', 'church_help_given']) {
  assert.equal((await one(`SELECT count(*)::int AS n FROM ${table} WHERE business_id = $1`, [b1])).n, 0); checks++;
  assert.equal((await one(`SELECT count(*)::int AS n FROM ${table} WHERE business_id = $1`, [b2])).n, 1); checks++;
}

// Server-only: RLS on, no policies, and the browser's roles get nothing.
for (const table of ['church_help_settings', 'church_help_requests', 'church_help_given']) {
  const t = await one(`SELECT relrowsecurity AS rls, (SELECT count(*)::int FROM pg_policies WHERE tablename = $1) AS policies
    FROM pg_class WHERE relname = $1`, [table]);
  assert.equal(t.rls, true); assert.equal(t.policies, 0); checks++;
}
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const table of ['church_help_settings', 'church_help_requests', 'church_help_given']) {
    await refuses(`SELECT * FROM ${table}`, [], /permission denied/);
  }
  await refuses(`INSERT INTO church_help_requests(business_id, need) VALUES ('${b2}', 'food')`, [], /permission denied/);
  await refuses(`UPDATE church_help_settings SET gift_limit_cents = 1000000`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church help requests: ${checks} checks passed`);

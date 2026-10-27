// Check requests, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-27-church-checks.sql. A church has one settings row
// ($250 limit unless set, the budget lines a JSON list); a request's status,
// source, how it was paid and its receipt's kind are the known words; an
// amount is above zero; a paid request says how and when, a check its
// number, a decline why; a request's person is its own church's; a deleted
// expense or person leaves the request; a church that leaves takes it all;
// the browser's roles can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_checks_db.mjs
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
  CREATE TABLE public.business_expenses(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), business_id uuid, amount numeric);`);
await db.query('INSERT INTO businesses(id) VALUES ($1), ($2)', [b1, b2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};
const one = async (text, args) => (await db.query(text, args)).rows[0];

await db.exec(await sql('APPLY-2026-10-27-church-checks.sql'));
await db.exec(await sql('APPLY-2026-10-27-church-checks.sql'));   // idempotent

// Settings: a $250 limit and no lines unless the church says.
const s = await one('INSERT INTO church_check_settings(business_id) VALUES ($1) RETURNING *', [b1]);
assert.equal(s.limit_cents, 25000); assert.deepEqual(s.lines, []); checks++;
await db.query(`UPDATE church_check_settings SET lines = '[{"name":"Kids","budget_cents":200000}]' WHERE business_id = $1`, [b1]);
assert.equal((await one('SELECT lines FROM church_check_settings WHERE business_id = $1', [b1])).lines[0].name, 'Kids'); checks++;
await refuses('INSERT INTO church_check_settings(business_id) VALUES ($1)', [b1], /duplicate key|unique/);
await refuses('UPDATE church_check_settings SET limit_cents = -1 WHERE business_id = $1', [b1], /check constraint/);
await refuses(`UPDATE church_check_settings SET lines = '{}' WHERE business_id = $1`, [b1], /check constraint/);

// A request: new, from the office, unless it says otherwise; only the known words.
const dana = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1])).id;
const theirs = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b2])).id;
const add = `INSERT INTO church_check_requests(business_id, ministry, about, amount_cents, contact_id)
  VALUES ($1, $2, $3, $4, $5) RETURNING *`;
const supplies = await one(add, [b1, 'Kids', 'Bible school supplies', 34000, dana]);
assert.equal(supplies.status, 'new'); assert.equal(supplies.source, 'office'); assert.equal(supplies.receipt_path, null); checks++;
await refuses(add, [b1, 'Kids', 'Free', 0, null], /check constraint/);
await refuses(add, [b1, '', 'No ministry', 100, null], /check constraint/);
await refuses(add, [b1, 'Kids', '', 100, null], /check constraint/);
await refuses(`UPDATE church_check_requests SET status = 'maybe' WHERE id = $1`, [supplies.id], /check constraint/);
await refuses(`UPDATE church_check_requests SET source = 'fax' WHERE id = $1`, [supplies.id], /check constraint/);
await refuses(`UPDATE church_check_requests SET receipt_type = 'gif' WHERE id = $1`, [supplies.id], /check constraint/);

// Paid says how and when; a check says its number; a decline says why.
await refuses(`UPDATE church_check_requests SET status = 'paid' WHERE id = $1`, [supplies.id], /check constraint/);
await refuses(`UPDATE church_check_requests SET status = 'paid', paid_how = 'check', paid_on = '2026-10-27' WHERE id = $1`,
  [supplies.id], /check constraint/);
await refuses(`UPDATE church_check_requests SET status = 'paid', paid_how = 'venmo', paid_on = '2026-10-27' WHERE id = $1`,
  [supplies.id], /check constraint/);
await refuses(`UPDATE church_check_requests SET status = 'declined' WHERE id = $1`, [supplies.id], /check constraint/);
const exp = (await one('INSERT INTO business_expenses(business_id, amount) VALUES ($1, 340) RETURNING id', [b1])).id;
const paid = await one(`UPDATE church_check_requests SET status = 'paid', paid_how = 'check', check_number = '1043',
  paid_on = '2026-10-27', expense_id = $2 WHERE id = $1 RETURNING *`, [supplies.id, exp]);
assert.equal(paid.status, 'paid'); assert.equal(paid.expense_id, exp); checks++;
const transfer = await one(add, [b1, 'Youth', 'Retreat deposit', 50000, null]);
await db.query(`UPDATE church_check_requests SET status = 'paid', paid_how = 'transfer', paid_on = '2026-10-27' WHERE id = $1`,
  [transfer.id]); checks++;
const coffee = await one(add, [b1, 'Hospitality', 'Coffee', 6218, dana]);
await db.query(`UPDATE church_check_requests SET status = 'declined', decline_reason = 'From the Costco order' WHERE id = $1`,
  [coffee.id]); checks++;

// Its person is its own church's.
await refuses(add, [b1, 'Kids', 'Snacks', 100, theirs], /not in this church/);
await refuses('UPDATE church_check_requests SET contact_id = $2 WHERE id = $1', [supplies.id, theirs], /not in this church/);

// A deleted expense or person leaves the request (and what it says).
await db.query('DELETE FROM business_expenses WHERE id = $1', [exp]);
assert.equal((await one('SELECT expense_id, status FROM church_check_requests WHERE id = $1', [supplies.id])).expense_id, null); checks++;
await db.query('DELETE FROM contacts WHERE id = $1', [dana]);
assert.equal((await one('SELECT contact_id FROM church_check_requests WHERE id = $1', [coffee.id])).contact_id, null); checks++;

// A church that leaves takes its settings and requests; the other keeps its own.
await db.query('INSERT INTO church_check_settings(business_id) VALUES ($1)', [b2]);
await db.query(add, [b2, 'Kids', 'Their snacks', 4000, theirs]);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
for (const table of ['church_check_settings', 'church_check_requests']) {
  assert.equal((await one(`SELECT count(*)::int AS n FROM ${table} WHERE business_id = $1`, [b1])).n, 0); checks++;
  assert.equal((await one(`SELECT count(*)::int AS n FROM ${table} WHERE business_id = $1`, [b2])).n, 1); checks++;
}

// Server-only: RLS on, no policies, and the browser's roles get nothing.
for (const table of ['church_check_settings', 'church_check_requests']) {
  const t = await one(`SELECT relrowsecurity AS rls, (SELECT count(*)::int FROM pg_policies WHERE tablename = $1) AS policies
    FROM pg_class WHERE relname = $1`, [table]);
  assert.equal(t.rls, true); assert.equal(t.policies, 0); checks++;
}
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  for (const table of ['church_check_settings', 'church_check_requests']) {
    await refuses(`SELECT * FROM ${table}`, [], /permission denied/);
  }
  await refuses(`INSERT INTO church_check_requests(business_id, ministry, about, amount_cents) VALUES ('${b2}', 'Kids', 'x', 100)`,
    [], /permission denied/);
  await refuses(`UPDATE church_check_settings SET limit_cents = 1000000`, [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church check requests: ${checks} checks passed`);

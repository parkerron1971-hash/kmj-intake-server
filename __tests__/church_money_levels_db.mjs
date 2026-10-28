// The money levels' yeses, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-28-church-money-levels.sql on top of the check
// requests (APPLY-2026-10-27-church-checks.sql). A yes names one of the three
// steps; a request has one yes a step and one step a person; a yes is on its
// own church's request; a request or a church that goes takes its yeses; the
// browser's roles can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_money_levels_db.mjs
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
const treasurer = 'aaaaaaaa-0000-4000-8000-000000000001';
const pastor = 'aaaaaaaa-0000-4000-8000-000000000002';
const elder = 'aaaaaaaa-0000-4000-8000-000000000003';
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
await db.exec(await sql('APPLY-2026-10-28-church-money-levels.sql'));
await db.exec(await sql('APPLY-2026-10-28-church-money-levels.sql'));   // idempotent

const add = `INSERT INTO church_check_requests(business_id, ministry, about, amount_cents) VALUES ($1, $2, $3, $4) RETURNING id`;
const roof = (await one(add, [b1, 'Building', 'Roof deposit', 300000])).id;
const bus = (await one(add, [b1, 'Youth', 'Retreat bus', 120000])).id;
const theirs = (await one(add, [b2, 'Kids', 'Their snacks', 4000])).id;

// A yes: one of the three steps, at a time of its own.
const yes = `INSERT INTO church_check_approvals(business_id, request_id, step, user_id) VALUES ($1, $2, $3, $4) RETURNING *`;
const first = await one(yes, [b1, roof, 'treasurer', treasurer]);
assert.equal(first.step, 'treasurer'); assert.ok(first.created_at); checks++;
await refuses(yes, [b1, roof, 'deacon', pastor], /check constraint/);

// One yes a step, and one step a person.
await refuses(yes, [b1, roof, 'treasurer', pastor], /one_a_step|duplicate key|unique/);
await refuses(yes, [b1, roof, 'pastor', treasurer], /one_a_person|duplicate key|unique/);
await one(yes, [b1, roof, 'pastor', pastor]);
await one(yes, [b1, roof, 'board', elder]);
await one(yes, [b1, bus, 'treasurer', treasurer]);   // another request: the same person again
assert.equal((await one('SELECT count(*)::int AS n FROM church_check_approvals WHERE request_id = $1', [roof])).n, 3); checks++;

// A yes is on its own church's request.
await refuses(yes, [b1, theirs, 'treasurer', treasurer], /not in this church/);
await refuses(yes, [b2, roof, 'pastor', elder], /not in this church/);
await refuses('UPDATE church_check_approvals SET request_id = $2 WHERE request_id = $1 AND step = $3',
  [bus, theirs, 'treasurer'], /not in this church/);

// A request that goes takes its yeses; a church that goes takes the rest.
await db.query('DELETE FROM church_check_requests WHERE id = $1', [bus]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_check_approvals WHERE request_id = $1', [bus])).n, 0); checks++;
await one(yes, [b2, theirs, 'treasurer', elder]);
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_check_approvals WHERE business_id = $1', [b1])).n, 0); checks++;
assert.equal((await one('SELECT count(*)::int AS n FROM church_check_approvals WHERE business_id = $1', [b2])).n, 1); checks++;

// Server-only: RLS on, no policies, and the browser's roles get nothing.
const t = await one(`SELECT relrowsecurity AS rls, (SELECT count(*)::int FROM pg_policies WHERE tablename = 'church_check_approvals') AS policies
  FROM pg_class WHERE relname = 'church_check_approvals'`);
assert.equal(t.rls, true); assert.equal(t.policies, 0); checks++;
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM church_check_approvals', [], /permission denied/);
  await refuses(yes, [b2, theirs, 'pastor', pastor], /permission denied/);
  await refuses('DELETE FROM church_check_approvals', [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church money levels: ${checks} checks passed`);

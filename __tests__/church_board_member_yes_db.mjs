// A board member's yes from the member app, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-28-church-board-member-yes.sql on top of the check
// requests and the money levels. A yes may come from a person as well as a
// login, one a person; a yes's person and a code's person are the request's
// church's; a person who leaves keeps their yes, with no one named; a code
// is a 64-character hash with a few tries; the browser's roles get nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/church_board_member_yes_db.mjs
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
await db.exec(await sql('APPLY-2026-10-28-church-board-member-yes.sql'));
await db.exec(await sql('APPLY-2026-10-28-church-board-member-yes.sql'));   // idempotent

const ruth = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1])).id;
const sam = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b1])).id;
const theirs = (await one('INSERT INTO contacts(business_id) VALUES ($1) RETURNING id', [b2])).id;
const add = `INSERT INTO church_check_requests(business_id, ministry, about, amount_cents) VALUES ($1, $2, $3, $4) RETURNING id`;
const roof = (await one(add, [b1, 'Building', 'Roof deposit', 300000])).id;
const their = (await one(add, [b2, 'Kids', 'Their snacks', 4000])).id;

// A yes from a login, and one from a person.
const byLogin = `INSERT INTO church_check_approvals(business_id, request_id, step, user_id) VALUES ($1, $2, $3, $4) RETURNING *`;
const byPerson = `INSERT INTO church_check_approvals(business_id, request_id, step, contact_id) VALUES ($1, $2, $3, $4) RETURNING *`;
await one(byLogin, [b1, roof, 'treasurer', treasurer]);
const yes = await one(byPerson, [b1, roof, 'board', ruth]);
assert.equal(yes.user_id, null); assert.equal(yes.contact_id, ruth); checks++;
// One step a person, and one yes a step, whoever gives it.
await refuses(byPerson, [b1, roof, 'pastor', ruth], /one_a_member|duplicate key|unique/);
await refuses(byPerson, [b1, roof, 'board', sam], /one_a_step|duplicate key|unique/);
// Their person, or our person on their request: refused.
await refuses(byPerson, [b1, roof, 'pastor', theirs], /not in this church/);
await refuses(byPerson, [b2, their, 'board', ruth], /not in this church/);

// A person who leaves keeps their yes, with no one named.
await db.query('DELETE FROM contacts WHERE id = $1', [ruth]);
const kept = await one('SELECT step, contact_id FROM church_check_approvals WHERE request_id = $1 AND step = $2', [roof, 'board']);
assert.equal(kept.step, 'board'); assert.equal(kept.contact_id, null); checks++;

// The codes: a request's, a person's, a hash, a few tries.
const code = `INSERT INTO church_check_approval_codes(business_id, request_id, contact_id, code_hash) VALUES ($1, $2, $3, $4) RETURNING *`;
const hash = 'a'.repeat(64);
const c = await one(code, [b1, roof, sam, hash]);
assert.equal(c.tries, 0); assert.equal(c.used_at, null); assert.ok(c.created_at); checks++;
await refuses(code, [b1, roof, sam, 'short'], /check constraint/);
await refuses(code, [b1, roof, theirs, hash], /not in this church/);
await refuses(code, [b2, roof, theirs, hash], /not in this church/);
await refuses('UPDATE church_check_approval_codes SET tries = 11 WHERE id = $1', [c.id], /check constraint/);
// A request that goes takes its codes; a person who goes takes theirs.
await db.query('DELETE FROM contacts WHERE id = $1', [sam]);
assert.equal((await one('SELECT count(*)::int AS n FROM church_check_approval_codes')).n, 0); checks++;

// Server-only: RLS on, no policies, and the browser's roles get nothing.
const t = await one(`SELECT relrowsecurity AS rls,
  (SELECT count(*)::int FROM pg_policies WHERE tablename = 'church_check_approval_codes') AS policies
  FROM pg_class WHERE relname = 'church_check_approval_codes'`);
assert.equal(t.rls, true); assert.equal(t.policies, 0); checks++;
for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM church_check_approval_codes', [], /permission denied/);
  await refuses('SELECT * FROM church_check_approvals', [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`church board member yes: ${checks} checks passed`);

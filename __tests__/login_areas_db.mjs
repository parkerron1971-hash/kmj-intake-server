// Who sees what, on a real Postgres (PGlite): supabase/APPLY-2026-10-26-login-areas.sql.
// An office login's areas are null (no pick) or one to eight of the eight
// known areas; a made-up area or an empty pick is refused; every login that
// was there before keeps null; running the file twice changes nothing.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/login_areas_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const u1 = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const u2 = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
await db.exec(`CREATE TABLE public.business_users(business_id uuid, user_id uuid, role text, status text,
  invited_email text, PRIMARY KEY (business_id, user_id));`);
await db.query(`INSERT INTO business_users VALUES ($1, $2, 'manager', 'active', 'sarah@example.com'),
  ($1, $3, 'member', 'active', 'mark@example.com')`, [b1, u1, u2]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-26-login-areas.sql'));
await db.exec(await sql('APPLY-2026-10-26-login-areas.sql'));   // idempotent

const before = await db.query('SELECT count(*)::int AS n FROM business_users WHERE areas IS NULL');
assert.equal(before.rows[0].n, 2); checks++;

const pick = 'UPDATE business_users SET areas = $1 WHERE user_id = $2 RETURNING areas';
assert.deepEqual((await db.query(pick, [['kids_youth'], u1])).rows[0].areas, ['kids_youth']); checks++;
const all = ['worship_media', 'people_care', 'giving_money', 'kids_youth', 'groups_classes',
  'messages_safety', 'website_outreach', 'office'];
assert.deepEqual((await db.query(pick, [all, u2])).rows[0].areas, all); checks++;
await refuses(pick, [['the_moon'], u1], /check constraint/);
await refuses(pick, [['kids_youth', 'the_moon'], u1], /check constraint/);
await refuses(pick, [[], u1], /check constraint/);
assert.equal((await db.query(pick, [null, u1])).rows[0].areas, null); checks++;

const constraints = await db.query(`SELECT count(*)::int AS n FROM pg_constraint WHERE conname = 'business_users_areas_known'`);
assert.equal(constraints.rows[0].n, 1, 'one constraint after two runs'); checks++;

console.log(`login_areas_db: ${checks} checks passed`);

// Who does what in a church's ChurchSavvy, on a real Postgres (PGlite):
// supabase/APPLY-2026-10-20-worship-team.sql. Rows go through every check:
// an invite with one or more parts goes in; no parts, a part that isn't one,
// a blank name, a status nobody set up, or an active row with nobody on it
// are refused; one token can't be two invites; one person is on a church's
// team once (a second active row is refused, a removed one isn't counted);
// a church or a person that leaves takes their rows with them; the
// browser's roles can't read or write any of it.
//
// Run: PGLITE_MODULE=<path to @electric-sql/pglite/dist/index.js> node __tests__/worship_team_db.mjs
import { pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE
  ? pathToFileURL(process.env.PGLITE_MODULE).href
  : '../output/marketing-qa/node_modules/@electric-sql/pglite/dist/index.js');

const sql = name => readFile(new URL(`../supabase/${name}`, import.meta.url), 'utf8');
const db = new PGlite();
const b1 = '11111111-1111-4111-8111-111111111111';
const sam = '33333333-3333-4333-8333-333333333333';
const jo = '44444444-4444-4444-8444-444444444444';
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
  CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
  CREATE TABLE public.businesses(id uuid PRIMARY KEY);`);
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await db.query('INSERT INTO auth.users(id) VALUES ($1), ($2)', [sam, jo]);
let checks = 0;
const refuses = async (text, args, message) => {
  await assert.rejects(db.query(text, args), e => { assert.match(e.message, message); return true; }); checks++;
};

await db.exec(await sql('APPLY-2026-10-20-worship-team.sql'));
await db.exec(await sql('APPLY-2026-10-20-worship-team.sql'));   // idempotent

const add = `INSERT INTO worship_team(business_id, name, email, roles) VALUES ($1, $2, $3, $4) RETURNING *`;
const inv = (await db.query(add, [b1, 'Sam', 'sam@example.org', ['booth', 'worship']])).rows[0];
assert.equal(inv.status, 'invited'); assert.ok(inv.token); assert.equal(inv.user_id, null); checks += 3;

await refuses(add, [b1, 'Sam', null, []], /check constraint/);
await refuses(add, [b1, 'Sam', null, ['pastor']], /check constraint/);
await refuses(add, [b1, '  ', null, ['booth']], /check constraint/);
await refuses(`UPDATE worship_team SET status = 'boss' WHERE id = $1`, [inv.id], /check constraint/);
await refuses(`UPDATE worship_team SET status = 'active' WHERE id = $1`, [inv.id], /check constraint/);
await refuses(`INSERT INTO worship_team(business_id, name, roles, token) VALUES ($1, 'Twin', '{booth}', $2)`, [b1, inv.token], /duplicate key|unique/);

// Sam joins; a second active row for Sam at this church is refused.
await db.query(`UPDATE worship_team SET status = 'active', user_id = $2, joined_at = now() WHERE id = $1`, [inv.id, sam]); checks++;
const again = (await db.query(add, [b1, 'Sam again', null, ['planner']])).rows[0];
await refuses(`UPDATE worship_team SET status = 'active', user_id = $2 WHERE id = $1`, [again.id, sam], /duplicate key|unique/);
// A removed row doesn't count: taken off, then back on.
await db.query(`UPDATE worship_team SET status = 'removed', removed_at = now() WHERE id = $1`, [inv.id]);
await db.query(`UPDATE worship_team SET status = 'active', user_id = $2 WHERE id = $1`, [again.id, sam]); checks++;

// A person who deletes their account leaves; a church that leaves takes its team.
const j = (await db.query(add, [b1, 'Jo', null, ['planner']])).rows[0];
await db.query(`UPDATE worship_team SET status = 'active', user_id = $2 WHERE id = $1`, [j.id, jo]);
await db.query('DELETE FROM auth.users WHERE id = $1', [jo]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM worship_team WHERE id = $1', [j.id])).rows[0].n, 0); checks++;
await db.query('DELETE FROM businesses WHERE id = $1', [b1]);
assert.equal((await db.query('SELECT count(*)::int AS n FROM worship_team')).rows[0].n, 0); checks++;

// The Media part (APPLY-2026-10-23-churchsavvy-media-part.sql): the old
// check is replaced, not stacked; media and all five parts go in; a part
// that isn't one still doesn't.
await db.query('INSERT INTO businesses(id) VALUES ($1)', [b1]);
await refuses(add, [b1, 'Mo', null, ['media']], /check constraint/);
await db.exec(await sql('APPLY-2026-10-23-churchsavvy-media-part.sql'));
await db.exec(await sql('APPLY-2026-10-23-churchsavvy-media-part.sql'));   // idempotent
assert.equal((await db.query(add, [b1, 'Mo', null, ['media']])).rows[0].roles[0], 'media'); checks++;
await db.query(add, [b1, 'All', null, ['planner', 'worship', 'booth', 'media', 'admin']]); checks++;
await refuses(add, [b1, 'Mo', null, ['pastor']], /check constraint/);
await refuses(add, [b1, 'Mo', null, []], /check constraint/);
const named = await db.query(`SELECT count(*)::int AS n FROM pg_constraint WHERE conrelid = 'worship_team'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%roles%'`);
assert.equal(named.rows[0].n, 1); checks++;

for (const role of ['anon', 'authenticated']) {
  await db.exec(`SET ROLE ${role}`);
  await refuses('SELECT * FROM worship_team', [], /permission denied/);
  await db.exec('RESET ROLE');
}

console.log(`worship_team: ${checks} checks passed`);
